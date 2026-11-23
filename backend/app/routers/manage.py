"""Quản lý sinh viên trên CSDL v2: danh sách, hồ sơ chi tiết, thêm, sửa, khóa tài khoản, import từ Excel.

- Quản trị: xem và sửa mọi sinh viên.
- Giảng viên: chỉ xem sinh viên lớp mình làm CVHT, và hồ sơ sinh viên trong lớp học phần mình dạy. Không sửa.
Mỗi sinh viên mới có một tài khoản đăng nhập (tên đăng nhập = mã SV) với mật khẩu tạm, chỉ hiện một lần cho quản trị.
"""

import re
import secrets
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session, selectinload

from .. import mailer
from ..agent import latest_predictions, prediction_out
from ..auth import require_roles
from ..database_v2 import get_db_v2
from ..models_v2 import (Alert, AgentRun, AuditLog, Class, CourseSection, Enrollment, Lecturer, Prediction, Student,
                         User)
from ..security import hash_password
from ..services_v2 import current_semester
from .me import student_results

router = APIRouter(prefix="/manage", tags=["Quản lý sinh viên"])
staff = require_roles("admin", "lecturer")
admin_only = require_roles("admin")

STATUS_LABELS = {"studying": "Đang học", "reserved": "Bảo lưu", "dropped": "Thôi học", "graduated": "Đã tốt nghiệp"}
CODE_RE = re.compile(r"^[A-Z0-9]{4,20}$")
PASSWORD_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"
MAX_IMPORT = 2000


class StudentIn(BaseModel):
    student_code: str = Field(min_length=4, max_length=20)
    full_name: str = Field(min_length=2, max_length=100)
    class_id: int
    gender: str | None = Field(default=None, pattern="^(M|F)$")
    date_of_birth: date | None = None
    email: str | None = Field(default=None, max_length=100)


class StudentUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=100)
    class_id: int | None = None
    gender: str | None = Field(default=None, pattern="^(M|F|)$")
    date_of_birth: date | None = None
    email: str | None = Field(default=None, max_length=100)
    status: str | None = Field(default=None, pattern="^(studying|reserved|dropped|graduated)$")
    account_active: bool | None = None


class ImportIn(BaseModel):
    rows: list[dict] = Field(max_length=MAX_IMPORT)
    dry_run: bool = True


def temp_password() -> str:
    return "".join(secrets.choice(PASSWORD_CHARS) for _ in range(10))


def _audit(db: Session, request: Request, admin: User, action: str, entity_id: int | None, old=None, new=None):
    db.add(AuditLog(user_id=admin.id, action=action, entity="students", entity_id=entity_id, old_value=old,
                    new_value=new, ip_address=request.client.host if request.client else None,
                    created_at=datetime.now()))


def _latest_run_id(db: Session) -> int | None:
    semester = current_semester(db)
    return db.scalar(select(AgentRun.id).where(AgentRun.semester_id == semester.id, AgentRun.status == "success")
                     .order_by(AgentRun.as_of.desc(), AgentRun.id.desc()))


def _can_view(db: Session, user: User, st: Student) -> bool:
    if user.role == "admin":
        return True
    lec = user.lecturer
    if lec is None:
        return False
    if st.class_.advisor_id == lec.id:
        return True
    return bool(db.scalar(select(func.count()).select_from(Enrollment).join(CourseSection)
                          .where(Enrollment.student_id == st.id, CourseSection.lecturer_id == lec.id)))


def _academic(db: Session, student_ids: list[int]) -> dict[int, dict]:
    """ĐTB tích lũy (hệ 4), tín chỉ tích lũy, số môn nợ: mỗi môn lấy lần học tốt nhất."""
    if not student_ids:
        return {}
    rows = db.execute(text("""
        SELECT t.student_id,
               SUM(CASE WHEN t.passed = 1 THEN t.credits ELSE 0 END) AS credits,
               SUM(CASE WHEN t.passed = 1 THEN t.gp * t.credits ELSE 0 END) AS points,
               SUM(CASE WHEN t.passed = 0 THEN 1 ELSE 0 END) AS owed
        FROM (SELECT e.student_id, c.id AS course_id, c.credits, MAX(e.grade_point) AS gp, MAX(e.passed) AS passed
              FROM enrollments e JOIN course_sections cs ON cs.id = e.section_id JOIN courses c ON c.id = cs.course_id
              WHERE e.final_score IS NOT NULL AND e.student_id IN :ids
              GROUP BY e.student_id, c.id) t
        GROUP BY t.student_id""").bindparams(ids=tuple(student_ids))).all()
    return {r.student_id: {"gpa4": round(float(r.points) / float(r.credits), 2) if r.credits else None,
                           "credits": int(r.credits or 0), "owed": int(r.owed or 0)} for r in rows}


def _row(st: Student, acad: dict | None, risk: dict | None) -> dict:
    u = st.user
    return {
        "id": st.id, "student_code": st.student_code, "full_name": st.full_name, "gender": st.gender,
        "date_of_birth": st.date_of_birth.isoformat() if st.date_of_birth else None,
        "class_id": st.class_id, "class_code": st.class_.code, "cohort": st.class_.cohort,
        "status": st.status, "status_label": STATUS_LABELS[st.status],
        "email": (u.email if u else None) or st.email,
        "email_verified": bool(u and u.email_verified_at),
        "account_active": bool(u and u.is_active), "has_account": u is not None,
        "gpa4": (acad or {}).get("gpa4"), "credits": (acad or {}).get("credits", 0), "owed": (acad or {}).get("owed", 0),
        "risk": risk,
    }


# ------------------------------------------------------------------ danh mục cho bộ lọc / biểu mẫu
@router.get("/options", summary="Lớp hành chính, trạng thái (cho bộ lọc và biểu mẫu)")
def options(user: User = Depends(staff), db: Session = Depends(get_db_v2)):
    query = select(Class).options(selectinload(Class.advisor).selectinload(Lecturer.user)).order_by(Class.code)
    if user.role == "lecturer":
        query = query.where(Class.advisor_id == user.lecturer.id)
    return {
        "classes": [{"id": c.id, "code": c.code, "cohort": c.cohort,
                     "advisor": c.advisor.user.full_name if c.advisor else None} for c in db.scalars(query)],
        "statuses": STATUS_LABELS,
        "can_edit": user.role == "admin",
    }


# ------------------------------------------------------------------ danh sách
@router.get("/students", summary="Danh sách sinh viên (lọc theo lớp, trạng thái, nguy cơ)")
def list_students(
    q: str | None = Query(default=None, max_length=100),
    class_id: int | None = None,
    status: str | None = Query(default=None, pattern="^(studying|reserved|dropped|graduated)$"),
    risk: str | None = Query(default=None, pattern="^(flagged|ai|high)$"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(staff), db: Session = Depends(get_db_v2),
):
    query = select(Student).join(Student.class_)
    if user.role == "lecturer":
        query = query.where(Class.advisor_id == user.lecturer.id)
    if q:
        like = f"%{q.strip()}%"
        query = query.where(or_(Student.student_code.like(like), Student.full_name.like(like)))
    if class_id:
        query = query.where(Student.class_id == class_id)
    if status:
        query = query.where(Student.status == status)
    run_id = _latest_run_id(db)
    if risk and run_id:
        cond = {"flagged": Prediction.flag_source != "none", "ai": Prediction.flag_source == "ai",
                "high": Prediction.risk_level == "high"}[risk]
        flagged = (select(Enrollment.student_id).join(Prediction, Prediction.enrollment_id == Enrollment.id)
                   .where(Prediction.run_id == run_id, cond))
        query = query.where(Student.id.in_(flagged))
    elif risk:
        query = query.where(False)

    total = db.scalar(select(func.count()).select_from(query.subquery()))
    students = db.scalars(query.options(selectinload(Student.class_), selectinload(Student.user))
                          .order_by(Student.student_code).limit(limit).offset(offset)).all()
    ids = [s.id for s in students]
    acad = _academic(db, ids)

    # Nguy cơ học kỳ hiện tại theo lần chạy Agent gần nhất: môn có xác suất trượt cao nhất
    risks: dict[int, dict] = {}
    if run_id and ids:
        preds = db.execute(select(Prediction, Enrollment.student_id, CourseSection.code)
                           .join(Enrollment, Enrollment.id == Prediction.enrollment_id)
                           .join(CourseSection, CourseSection.id == Enrollment.section_id)
                           .where(Prediction.run_id == run_id, Enrollment.student_id.in_(ids))).all()
        for p, sid, sec_code in preds:
            r = risks.setdefault(sid, {"flagged": 0, "ai": 0, "worst": None})
            if p.flag_source != "none":
                r["flagged"] += 1
            if p.flag_source == "ai":
                r["ai"] += 1
            if r["worst"] is None or p.risk_probability > r["worst"]["proba"]:
                r["worst"] = {"proba": p.risk_probability, "level": p.risk_level, "course": sec_code.split("-")[0]}
    counts = dict(db.execute(select(Student.status, func.count()).join(Student.class_)
                             .where(Class.advisor_id == user.lecturer.id if user.role == "lecturer" else True)
                             .group_by(Student.status)).all())
    return {"total": total, "counts": counts, "items": [_row(s, acad.get(s.id), risks.get(s.id)) for s in students]}


# ------------------------------------------------------------------ hồ sơ chi tiết
@router.get("/students/{student_id}", summary="Hồ sơ sinh viên: thông tin, kết quả học tập, học kỳ hiện tại, cảnh báo")
def student_detail(student_id: int, user: User = Depends(staff), db: Session = Depends(get_db_v2)):
    st = db.get(Student, student_id)
    if st is None:
        raise HTTPException(404, "Không tìm thấy sinh viên")
    if not _can_view(db, user, st):
        raise HTTPException(403, "Bạn chỉ xem được sinh viên lớp chủ nhiệm hoặc lớp học phần mình dạy")
    results = student_results(db, st)
    current = next((s for s in results["semesters"] if s["is_current"]), None)
    preds = latest_predictions(db, [c["enrollment_id"] for c in current["courses"]]) if current else {}
    if current:
        for c in current["courses"]:
            c["ai"] = prediction_out(preds.get(c["enrollment_id"]))
    alerts = db.scalars(select(Alert).where(Alert.student_id == st.id, Alert.audience == "advisor")
                        .order_by(Alert.created_at.desc(), Alert.id.desc()).limit(20)).all()
    advisor = st.class_.advisor
    u = st.user
    return {
        "student": {**_row(st, None, None),
                    "advisor": advisor.user.full_name if advisor else None,
                    "username": u.username if u else None,
                    "last_login_at": u.last_login_at.isoformat(timespec="minutes") if u and u.last_login_at else None},
        "results": results,
        "alerts": [{"created_at": a.created_at.isoformat(timespec="minutes"), "level": a.level, "title": a.title,
                    "message": a.message} for a in alerts],
        "can_edit": user.role == "admin",
    }


# ------------------------------------------------------------------ thêm, sửa
def _check_email(db: Session, email: str | None, user_id: int | None) -> str | None:
    if not email:
        return None
    email = email.strip().lower()
    if not mailer.EMAIL_RE.match(email):
        raise HTTPException(400, f"Email không hợp lệ: {email}")
    taken = db.scalar(select(func.count()).select_from(User).where(
        func.lower(User.email) == email, User.email_verified_at.is_not(None),
        User.id != user_id if user_id else True))
    if taken:
        raise HTTPException(409, f"Email {email} đã liên kết với tài khoản khác")
    return email


def _create(db: Session, code: str, full_name: str, class_id: int, gender: str | None, dob: date | None,
            email: str | None) -> tuple[Student, str]:
    password = temp_password()
    user = User(username=code, password_hash=hash_password(password), full_name=full_name, email=email,
                role="student", is_active=True, created_at=datetime.now())
    db.add(user)
    db.flush()
    st = Student(user_id=user.id, student_code=code, full_name=full_name, gender=gender, date_of_birth=dob,
                 email=email, class_id=class_id, status="studying")
    db.add(st)
    db.flush()
    return st, password


@router.post("/students", summary="Thêm sinh viên (tạo luôn tài khoản, trả về mật khẩu tạm một lần)")
def create_student(data: StudentIn, request: Request, admin: User = Depends(admin_only),
                   db: Session = Depends(get_db_v2)):
    code = data.student_code.strip().upper()
    if not CODE_RE.match(code):
        raise HTTPException(400, "Mã sinh viên chỉ gồm chữ và số, 4–20 ký tự")
    if db.scalar(select(func.count()).select_from(Student).where(Student.student_code == code)) or \
            db.scalar(select(func.count()).select_from(User).where(User.username == code)):
        raise HTTPException(409, f"Mã sinh viên {code} đã tồn tại")
    if db.get(Class, data.class_id) is None:
        raise HTTPException(400, "Lớp không tồn tại")
    email = _check_email(db, data.email, None)
    st, password = _create(db, code, data.full_name.strip(), data.class_id, data.gender, data.date_of_birth, email)
    _audit(db, request, admin, "student.create", st.id, new={"student_code": code, "class_id": data.class_id})
    db.commit()
    db.refresh(st)
    return {"student": _row(st, None, None), "username": code, "temp_password": password}


@router.patch("/students/{student_id}", summary="Sửa thông tin, đổi lớp, đổi trạng thái, khóa / mở tài khoản")
def update_student(student_id: int, data: StudentUpdate, request: Request, admin: User = Depends(admin_only),
                   db: Session = Depends(get_db_v2)):
    st = db.get(Student, student_id)
    if st is None:
        raise HTTPException(404, "Không tìm thấy sinh viên")
    changes = data.model_dump(exclude_unset=True)
    old, new = {}, {}

    def put(obj, field, value, key=None):
        current = getattr(obj, field)
        if current != value:
            old[key or field] = current.isoformat() if isinstance(current, date) else current
            new[key or field] = value.isoformat() if isinstance(value, date) else value
            setattr(obj, field, value)

    if "full_name" in changes and data.full_name:
        put(st, "full_name", data.full_name.strip())
        if st.user:
            st.user.full_name = st.full_name
    if "class_id" in changes and data.class_id:
        if db.get(Class, data.class_id) is None:
            raise HTTPException(400, "Lớp không tồn tại")
        put(st, "class_id", data.class_id)
    if "gender" in changes:
        put(st, "gender", data.gender or None)
    if "date_of_birth" in changes:
        put(st, "date_of_birth", data.date_of_birth)
    if "email" in changes:
        email = _check_email(db, data.email, st.user_id)
        put(st, "email", email)
        # Email trong hồ sơ chỉ là thông tin liên hệ; muốn nhận cảnh báo, sinh viên tự liên kết (hoặc admin gán ở
        # trang Tài khoản). Đổi sang email khác thì bỏ trạng thái đã xác nhận của email cũ.
        if st.user and (st.user.email or "") != (email or ""):
            st.user.email, st.user.email_verified_at = email, None
    if "status" in changes and data.status:
        put(st, "status", data.status)
    if "account_active" in changes and data.account_active is not None and st.user:
        put(st.user, "is_active", data.account_active, key="account_active")
    if new:
        _audit(db, request, admin, "student.update", st.id, old=old, new=new)
        db.commit()
    db.refresh(st)
    return _row(st, _academic(db, [st.id]).get(st.id), None)


@router.post("/students/{student_id}/reset-password", summary="Đặt lại mật khẩu tạm cho sinh viên")
def reset_password(student_id: int, request: Request, admin: User = Depends(admin_only),
                   db: Session = Depends(get_db_v2)):
    st = db.get(Student, student_id)
    if st is None or st.user is None:
        raise HTTPException(404, "Sinh viên chưa có tài khoản")
    password = temp_password()
    st.user.password_hash = hash_password(password)
    _audit(db, request, admin, "student.reset_password", st.id)
    db.commit()
    return {"username": st.user.username, "temp_password": password}


# ------------------------------------------------------------------ import Excel
GENDERS = {"m": "M", "nam": "M", "male": "M", "f": "F", "nu": "F", "nữ": "F", "female": "F"}
COLUMNS = {  # tiêu đề cột chấp nhận (không phân biệt hoa thường, dấu cách) -> trường
    "student_code": ["mã sv", "mã sinh viên", "masv", "ma sv", "student_code", "code"],
    "full_name": ["họ tên", "họ và tên", "ho ten", "full_name", "name"],
    "class_code": ["lớp", "lớp hành chính", "lop", "class", "class_code"],
    "gender": ["giới tính", "gioi tinh", "gender", "phái"],
    "date_of_birth": ["ngày sinh", "ngay sinh", "date_of_birth", "dob"],
    "email": ["email", "e-mail", "thư điện tử"],
}


def _field(row: dict, field: str) -> str:
    lowered = {re.sub(r"\s+", " ", str(k)).strip().lower(): v for k, v in row.items()}
    for name in COLUMNS[field]:
        if name in lowered and lowered[name] is not None:
            return str(lowered[name]).strip()
    return ""


def _parse_date(value: str) -> date:
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d.%m.%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(value)


@router.post("/students/import", summary="Import danh sách sinh viên (dry_run = chỉ kiểm tra, chưa ghi)")
def import_students(data: ImportIn, request: Request, admin: User = Depends(admin_only),
                    db: Session = Depends(get_db_v2)):
    classes = {re.sub(r"\s+", " ", c.code).upper(): c for c in db.scalars(select(Class))}
    existing = {s.student_code: s for s in db.scalars(select(Student).options(selectinload(Student.user)))}
    usernames = set(db.scalars(select(User.username)))
    emails = {e.lower(): uid for uid, e in db.execute(select(User.id, User.email)
                                                      .where(User.email_verified_at.is_not(None))) if e}
    seen: set[str] = set()
    out, credentials = [], []
    for i, raw in enumerate(data.rows, start=2):  # dòng 1 của file Excel là tiêu đề
        errors = []
        code = _field(raw, "student_code").upper().replace(" ", "")
        name = re.sub(r"\s+", " ", _field(raw, "full_name"))
        class_code = re.sub(r"\s+", " ", _field(raw, "class_code")).upper()
        gender_raw = _field(raw, "gender").lower()
        dob_raw = _field(raw, "date_of_birth")
        email = _field(raw, "email").lower() or None
        if not any([code, name, class_code]):
            continue  # dòng trống
        if not CODE_RE.match(code):
            errors.append("Mã SV phải gồm 4–20 chữ / số")
        elif code in seen:
            errors.append("Mã SV bị trùng trong file")
        seen.add(code)
        if len(name) < 2:
            errors.append("Thiếu họ tên")
        cls = classes.get(class_code)
        if cls is None:
            errors.append(f"Không có lớp '{class_code}'" if class_code else "Thiếu lớp")
        gender = GENDERS.get(gender_raw) if gender_raw else None
        if gender_raw and gender is None:
            errors.append(f"Giới tính '{gender_raw}' không hiểu (Nam / Nữ)")
        dob = None
        if dob_raw:
            try:
                dob = _parse_date(dob_raw)
            except ValueError:
                errors.append(f"Ngày sinh '{dob_raw}' không đúng dạng ngày/tháng/năm")
        st = existing.get(code)
        if email:
            if not mailer.EMAIL_RE.match(email):
                errors.append("Email không hợp lệ")
            elif email in emails and (st is None or emails[email] != st.user_id):
                errors.append("Email đã liên kết với tài khoản khác")

        action = "error" if errors else "create"
        if not errors and st is not None:
            diff = {k: v for k, v in {"full_name": name, "class_id": cls.id, "gender": gender, "date_of_birth": dob,
                                      "email": email}.items()
                    if v is not None and getattr(st, k) != v}
            action = "update" if diff else "unchanged"
            if diff and not data.dry_run:
                old = {k: (getattr(st, k).isoformat() if isinstance(getattr(st, k), date) else getattr(st, k))
                       for k in diff}
                for k, v in diff.items():
                    setattr(st, k, v)
                if "full_name" in diff and st.user:
                    st.user.full_name = name
                _audit(db, request, admin, "student.import_update", st.id, old=old,
                       new={k: (v.isoformat() if isinstance(v, date) else v) for k, v in diff.items()})
        elif not errors and code in usernames:
            action, errors = "error", ["Tên đăng nhập trùng với một tài khoản khác"]
        elif not errors and not data.dry_run:
            st, password = _create(db, code, name, cls.id, gender, dob, email)
            credentials.append({"student_code": code, "full_name": name, "class_code": cls.code,
                                "username": code, "temp_password": password})
            _audit(db, request, admin, "student.import_create", st.id, new={"student_code": code, "class_id": cls.id})
        out.append({"row": i, "student_code": code, "full_name": name, "class_code": class_code,
                    "action": action, "errors": errors})

    summary = {a: sum(1 for r in out if r["action"] == a) for a in ("create", "update", "unchanged", "error")}
    if not data.dry_run:
        if summary["error"]:
            db.rollback()
            raise HTTPException(400, f"Còn {summary['error']} dòng lỗi, chưa ghi gì. Sửa file rồi thử lại.")
        db.commit()
    return {"dry_run": data.dry_run, "summary": summary, "rows": out, "credentials": credentials}
