"""Trang của giảng viên: lớp học phần mình dạy (xem, nhập điểm, điểm danh); lớp chủ nhiệm (CVHT).

Giảng viên chỉ xem lớp học phần mình dạy và lớp hành chính mình làm CVHT. Quản trị xem được tất cả.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, selectinload

from ..agent import latest_predictions, prediction_out
from ..auth import require_roles
from ..database_v2 import get_db_v2
from ..models_v2 import (Attendance, AuditLog, Class, ClassSession, Course, CourseSection, Enrollment, Grade,
                         Lecturer, Student, User)
from ..services_v2 import current_semester, setting_float, summarize, today

router = APIRouter(tags=["Giảng viên"])
staff = require_roles("lecturer", "admin")

ENROLLMENT_LOADERS = (
    selectinload(Enrollment.grades),
    selectinload(Enrollment.attendance),
    selectinload(Enrollment.section).selectinload(CourseSection.course).selectinload(Course.components),
    selectinload(Enrollment.student).selectinload(Student.class_),
)


def _flags(s, ban_ratio: float) -> list[str]:
    """Dấu hiệu cần chú ý theo luật đơn giản (tầng ② của Agent). Dự báo của mô hình AI nằm ở trường "ai"."""
    flags = []
    if s.absence_of_total() > ban_ratio:
        flags.append("Vắng quá ngưỡng cấm thi")
    elif s.absences / s.total_sessions >= ban_ratio * 0.75:  # vd 3/15 buổi khi ngưỡng cấm thi là 20%
        flags.append("Vắng nhiều")
    if s.process_score is not None and s.process_score < 4:
        flags.append("Điểm quá trình thấp")
    if s.exam_unreachable:
        flags.append("Không thể qua dù thi 10")
    return flags


@router.get("/teaching/sections", summary="Lớp học phần (giảng viên: lớp mình dạy; quản trị: tất cả)")
def my_sections(semester_id: int | None = None, user: User = Depends(staff), db: Session = Depends(get_db_v2)):
    semester_id = semester_id or current_semester(db).id
    query = (
        select(CourseSection).where(CourseSection.semester_id == semester_id)
        .options(selectinload(CourseSection.course).selectinload(Course.components),
                 selectinload(CourseSection.lecturer).selectinload(Lecturer.user),
                 selectinload(CourseSection.enrollments).selectinload(Enrollment.grades),
                 selectinload(CourseSection.enrollments).selectinload(Enrollment.attendance))
        .order_by(CourseSection.code)
    )
    if user.role == "lecturer":
        query = query.where(CourseSection.lecturer_id == user.lecturer.id)
    ban_ratio = setting_float(db, "absence_ban_ratio", 0.2)

    secs = db.scalars(query).all()
    preds = latest_predictions(db, [e.id for sec in secs for e in sec.enrollments])
    sections = []
    for sec in secs:
        n = len(sec.enrollments)
        entered = {c.code: sum(1 for e in sec.enrollments if any(g.component_id == c.id for g in e.grades))
                   for c in sec.course.components}
        over = sum(1 for e in sec.enrollments
                   if sum(a.status in ("absent", "excused") for a in e.attendance) / sec.total_sessions > ban_ratio)
        recorded = max((len(e.attendance) for e in sec.enrollments), default=0)
        sections.append({
            "id": sec.id, "code": sec.code, "course_code": sec.course.code, "course_name": sec.course.name,
            "credits": sec.course.credits, "room": sec.room,
            "lecturer": sec.lecturer.user.full_name if sec.lecturer else None,
            "n_students": n, "sessions_recorded": recorded, "total_sessions": sec.total_sessions,
            "components_entered": [{"code": code, "entered": cnt, "of": n} for code, cnt in entered.items()],
            "n_over_absence": over,
            # AI Agent: số sinh viên cần chú ý (luật hoặc AI) và số do AI phát hiện mà luật chưa thấy
            "n_flagged": sum(1 for e in sec.enrollments if (p := preds.get(e.id)) and p.flag_source != "none"),
            "n_ai_only": sum(1 for e in sec.enrollments if (p := preds.get(e.id)) and p.flag_source == "ai"),
        })
    return sections


@router.get("/teaching/sections/{section_id}", summary="Chi tiết lớp học phần: sinh viên, điểm, chuyên cần")
def section_detail(section_id: int, user: User = Depends(staff), db: Session = Depends(get_db_v2)):
    sec = db.get(CourseSection, section_id)
    if sec is None:
        raise HTTPException(404, "Không tìm thấy lớp học phần")
    if user.role == "lecturer" and sec.lecturer_id != user.lecturer.id:
        raise HTTPException(403, "Bạn không phụ trách lớp học phần này")

    ban_ratio = setting_float(db, "absence_ban_ratio", 0.2)
    enrollments = db.scalars(select(Enrollment).where(Enrollment.section_id == sec.id)
                             .options(*ENROLLMENT_LOADERS)).all()
    preds = latest_predictions(db, [e.id for e in enrollments])
    rows = []
    for e in sorted(enrollments, key=lambda e: e.student.student_code):
        s = summarize(e)
        rows.append({
            "enrollment_id": e.id, "student_id": e.student.id, "student_code": e.student.student_code,
            "full_name": e.student.full_name, "class_code": e.student.class_.code, "attempt_no": e.attempt_no, "status": e.status,
            "scores": s.scores, "process_score": s.process_score,
            "min_exam_score": s.min_exam_score, "exam_unreachable": s.exam_unreachable,
            "present": s.present, "late": s.late, "excused": s.excused, "absent": s.absent,
            "recorded": s.recorded, "absence_rate": s.absence_rate,
            "final_score": e.final_score, "letter_grade": e.letter_grade,
            "flags": _flags(s, ban_ratio),
            "ai": prediction_out(preds.get(e.id)),
        })
    return {
        "section": {"id": sec.id, "code": sec.code, "course_code": sec.course.code, "course_name": sec.course.name,
                    "credits": sec.course.credits, "semester": sec.semester.name, "room": sec.room,
                    "total_sessions": sec.total_sessions,
                    "lecturer": sec.lecturer.user.full_name if sec.lecturer else None},
        "components": [{"code": c.code, "name": c.name, "weight": c.weight, "is_exam": c.is_exam}
                       for c in sec.course.components],
        "ban_ratio": ban_ratio,
        "editable": sec.semester_id == current_semester(db).id,
        "students": rows,
    }


@router.get("/advising/students", summary="Sinh viên lớp chủ nhiệm (CVHT): tình hình học kỳ hiện tại")
def advising_students(user: User = Depends(staff), db: Session = Depends(get_db_v2)):
    query = select(Class).options(selectinload(Class.students)).order_by(Class.code)
    if user.role == "lecturer":
        query = query.where(Class.advisor_id == user.lecturer.id)
    classes = db.scalars(query).all()
    if not classes:
        raise HTTPException(404, "Bạn chưa được phân công làm cố vấn học tập lớp nào")

    semester = current_semester(db)
    ban_ratio = setting_float(db, "absence_ban_ratio", 0.2)
    student_ids = [s.id for c in classes for s in c.students]
    enrollments = db.scalars(select(Enrollment).where(Enrollment.student_id.in_(student_ids))
                             .options(*ENROLLMENT_LOADERS,
                                      selectinload(Enrollment.section).selectinload(CourseSection.semester))).all()
    preds = latest_predictions(db, [e.id for e in enrollments])
    by_student: dict[int, list[Enrollment]] = {}
    for e in enrollments:
        by_student.setdefault(e.student_id, []).append(e)

    rows = []
    for c in classes:
        for st in sorted(c.students, key=lambda s: s.student_code):
            mine = by_student.get(st.id, [])
            current = [e for e in mine if e.section.semester_id == semester.id]
            best: dict[str, Enrollment] = {}
            for e in mine:
                code = e.section.course.code
                if e.final_score is not None and (code not in best or e.final_score > best[code].final_score):
                    best[code] = e
            passed = [e for e in best.values() if e.passed]
            credits = sum(e.section.course.credits for e in passed)
            summaries = [(e, summarize(e)) for e in current]
            attention = [f"{e.section.course.code}: {', '.join(f)}" for e, s in summaries if (f := _flags(s, ban_ratio))]
            rates = [s.absence_rate for _, s in summaries if s.absence_rate is not None]
            mine_preds = [(e, preds[e.id]) for e in current if e.id in preds]
            worst = max(mine_preds, key=lambda x: x[1].risk_probability, default=None)
            rows.append({
                "student_id": st.id, "student_code": st.student_code, "full_name": st.full_name, "class_code": c.code,
                "gpa4": round(sum(e.grade_point * e.section.course.credits for e in passed) / credits, 2)
                if credits else None,
                "credits_passed": credits,
                "failed_courses": sorted(code for code, e in best.items() if not e.passed),
                "current_courses": len(current),
                "avg_absence_rate": round(sum(rates) / len(rates), 3) if rates else None,
                "attention": attention,
                # AI Agent: môn có nguy cơ trượt cao nhất và số môn AI cảnh báo
                "ai_worst": {**prediction_out(worst[1]), "course_code": worst[0].section.course.code,
                             "course_name": worst[0].section.course.name} if worst else None,
                "ai_flagged_courses": sorted(e.section.course.code for e, p in mine_preds if p.risk_level != "low"),
                "ai_only_courses": sorted(e.section.course.code for e, p in mine_preds if p.flag_source == "ai"),
            })
    return {"semester": semester.name, "classes": [c.code for c in classes], "students": rows}


# ------------------------------------------------------------------ nhập điểm, điểm danh (giảng viên phụ trách)
class GradeItem(BaseModel):
    enrollment_id: int
    component: str = Field(max_length=10)
    score: float | None = Field(default=None, ge=0, le=10)  # None = xóa đầu điểm đã nhập


class GradesIn(BaseModel):
    items: list[GradeItem] = Field(max_length=3000)


class AttendanceItem(BaseModel):
    enrollment_id: int
    status: str = Field(pattern="^(present|late|excused|absent)$")


class AttendanceIn(BaseModel):
    items: list[AttendanceItem] = Field(max_length=500)


def _own_section(db: Session, user: User, section_id: int) -> CourseSection:
    sec = db.get(CourseSection, section_id)
    if sec is None:
        raise HTTPException(404, "Không tìm thấy lớp học phần")
    if user.role == "lecturer" and sec.lecturer_id != user.lecturer.id:
        raise HTTPException(403, "Bạn không phụ trách lớp học phần này")
    return sec


def _editable_section(db: Session, user: User, section_id: int) -> CourseSection:
    """Chỉ giảng viên phụ trách (hoặc quản trị) được nhập, và chỉ lớp của học kỳ hiện tại."""
    sec = _own_section(db, user, section_id)
    if sec.semester_id != current_semester(db).id:
        raise HTTPException(400, "Chỉ nhập điểm, điểm danh cho lớp của học kỳ hiện tại")
    return sec


def _grade_scale(db: Session) -> list[tuple[str, float, float, bool]]:
    rows = db.execute(text("SELECT letter, min_score, point, passed FROM grade_scale ORDER BY min_score DESC")).all()
    return [(r.letter, float(r.min_score), float(r.point), bool(r.passed)) for r in rows]


def _finalize(e: Enrollment, components: list, scale: list) -> None:
    """Có điểm thi thì tính TBCHP, điểm chữ, điểm 4 (đầu điểm chưa nhập tính 0); xóa điểm thi thì bỏ kết quả."""
    scores = {g.component_id: g.score for g in e.grades}
    exam = next((c for c in components if c.is_exam), None)
    if exam is not None and exam.id in scores:
        final = round(sum(c.weight * scores.get(c.id, 0.0) for c in components) + 1e-9, 1)
        letter, _, point, passed = next(x for x in scale if final >= x[1])
        e.final_score, e.letter_grade, e.grade_point, e.passed = final, letter, point, passed
        e.status, e.completed_at = "completed", e.completed_at or datetime.now()
    elif e.status == "completed":
        e.final_score = e.letter_grade = e.grade_point = e.passed = e.completed_at = None
        e.status = "studying"


@router.put("/teaching/sections/{section_id}/grades", summary="Nhập / sửa điểm (ghi nhật ký từng thay đổi)")
def save_grades(section_id: int, data: GradesIn, request: Request, user: User = Depends(staff),
                db: Session = Depends(get_db_v2)):
    sec = _editable_section(db, user, section_id)
    components = sec.course.components
    by_code = {c.code: c for c in components}
    enrollments = {e.id: e for e in db.scalars(select(Enrollment).where(Enrollment.section_id == sec.id)
                                                .options(selectinload(Enrollment.grades),
                                                         selectinload(Enrollment.student)))}
    ip = request.client.host if request.client else None
    now = datetime.now()
    touched: set[int] = set()
    for item in data.items:
        e = enrollments.get(item.enrollment_id)
        comp = by_code.get(item.component)
        if e is None or comp is None:
            raise HTTPException(400, "Sinh viên hoặc đầu điểm không thuộc lớp học phần này")
        if e.status == "withdrawn":
            raise HTTPException(400, f"{e.student.student_code} đã rút môn, không nhập điểm được")
        score = None if item.score is None else round(item.score + 1e-9, 1)
        grade = next((g for g in e.grades if g.component_id == comp.id), None)
        old = grade.score if grade else None
        if old == score:
            continue
        if score is None:
            e.grades.remove(grade)
            db.delete(grade)
            action = "grade.delete"
        elif grade is None:
            e.grades.append(Grade(enrollment_id=e.id, component_id=comp.id, score=score, entered_by=user.id,
                                  entered_at=now))
            action = "grade.create"
        else:
            grade.score, grade.entered_by = score, user.id
            action = "grade.update"
        db.add(AuditLog(user_id=user.id, action=action, entity="enrollments", entity_id=e.id,
                        old_value={"score": old},
                        new_value={"section_id": sec.id, "student_code": e.student.student_code,
                                   "component": comp.code, "score": score},
                        ip_address=ip, created_at=now))
        touched.add(e.id)
    db.flush()
    scale = _grade_scale(db)
    for eid in touched:
        _finalize(enrollments[eid], components, scale)
    db.commit()
    # Agent tự chạy lại sau ít phút (scheduler thấy điểm mới) để cập nhật dự báo và cảnh báo
    return {"changed": len(touched), "detail": section_detail(section_id, user, db)}


@router.get("/teaching/sections/{section_id}/grade-log", summary="Nhật ký sửa điểm của lớp học phần")
def grade_log(section_id: int, user: User = Depends(staff), db: Session = Depends(get_db_v2)):
    sec = _own_section(db, user, section_id)
    rows = db.execute(
        select(AuditLog, User.full_name).outerjoin(User, User.id == AuditLog.user_id)
        .where(AuditLog.action.like("grade.%"),
               func.json_extract(AuditLog.new_value, "$.section_id") == sec.id)
        .order_by(AuditLog.id.desc()).limit(200)).all()
    labels = {"grade.create": "Nhập", "grade.update": "Sửa", "grade.delete": "Xóa"}
    return [{"at": a.created_at.isoformat(timespec="minutes"), "by": name, "action": labels[a.action],
             "student_code": a.new_value["student_code"], "component": a.new_value["component"],
             "old": (a.old_value or {}).get("score"), "new": a.new_value["score"]} for a, name in rows]


@router.get("/teaching/sections/{section_id}/sessions", summary="Các buổi học và số sinh viên đã điểm danh")
def sessions(section_id: int, user: User = Depends(staff), db: Session = Depends(get_db_v2)):
    sec = _own_section(db, user, section_id)
    counts = dict(db.execute(select(Attendance.session_id, func.count()).join(ClassSession)
                             .where(ClassSession.section_id == sec.id).group_by(Attendance.session_id)).all())
    n = db.scalar(select(func.count()).select_from(Enrollment).where(Enrollment.section_id == sec.id,
                                                                      Enrollment.status != "withdrawn"))
    rows = db.scalars(select(ClassSession).where(ClassSession.section_id == sec.id)
                      .order_by(ClassSession.session_no)).all()
    return {"n_students": n, "editable": sec.semester_id == current_semester(db).id,
            "sessions": [{"id": x.id, "no": x.session_no, "date": x.session_date.isoformat(), "topic": x.topic,
                          "recorded": counts.get(x.id, 0), "upcoming": x.session_date > today()} for x in rows]}


def _session_of(db: Session, sec: CourseSection, session_id: int) -> ClassSession:
    sess = db.get(ClassSession, session_id)
    if sess is None or sess.section_id != sec.id:
        raise HTTPException(404, "Không tìm thấy buổi học")
    return sess


@router.get("/teaching/sections/{section_id}/sessions/{session_id}", summary="Điểm danh một buổi")
def session_attendance(section_id: int, session_id: int, user: User = Depends(staff),
                       db: Session = Depends(get_db_v2)):
    sec = _own_section(db, user, section_id)
    sess = _session_of(db, sec, session_id)
    enrollments = db.scalars(select(Enrollment).where(Enrollment.section_id == sec.id, Enrollment.status != "withdrawn")
                             .options(selectinload(Enrollment.student).selectinload(Student.class_),
                                      selectinload(Enrollment.attendance))).all()
    rows = []
    for e in sorted(enrollments, key=lambda e: e.student.student_code):
        status = next((a.status for a in e.attendance if a.session_id == sess.id), None)
        absences = sum(a.status in ("absent", "excused") for a in e.attendance)
        rows.append({"enrollment_id": e.id, "student_code": e.student.student_code, "full_name": e.student.full_name,
                     "class_code": e.student.class_.code, "status": status, "absences": absences})
    return {"session": {"id": sess.id, "no": sess.session_no, "date": sess.session_date.isoformat(),
                        "topic": sess.topic, "upcoming": sess.session_date > today()},
            "total_sessions": sec.total_sessions, "ban_ratio": setting_float(db, "absence_ban_ratio", 0.2),
            "students": rows}


@router.put("/teaching/sections/{section_id}/sessions/{session_id}", summary="Lưu điểm danh một buổi")
def save_attendance(section_id: int, session_id: int, data: AttendanceIn, request: Request,
                    user: User = Depends(staff), db: Session = Depends(get_db_v2)):
    sec = _editable_section(db, user, section_id)
    sess = _session_of(db, sec, session_id)
    if sess.session_date > today():
        raise HTTPException(400, "Chưa tới ngày học buổi này")
    enrollments = {e.id: e for e in db.scalars(select(Enrollment).where(Enrollment.section_id == sec.id)
                                                .options(selectinload(Enrollment.attendance),
                                                         selectinload(Enrollment.student)))}
    now = datetime.now()
    changed = []
    for item in data.items:
        e = enrollments.get(item.enrollment_id)
        if e is None:
            raise HTTPException(400, "Sinh viên không thuộc lớp học phần này")
        record = next((a for a in e.attendance if a.session_id == sess.id), None)
        if record is None:
            db.add(Attendance(session_id=sess.id, enrollment_id=e.id, status=item.status, recorded_by=user.id,
                              recorded_at=now))
        elif record.status != item.status:
            changed.append({"student_code": e.student.student_code, "old": record.status, "new": item.status})
            record.status, record.recorded_by, record.recorded_at = item.status, user.id, now
    db.add(AuditLog(user_id=user.id, action="attendance.save", entity="class_sessions", entity_id=sess.id,
                    new_value={"section_id": sec.id, "session_no": sess.session_no, "n": len(data.items),
                               "changed": changed},
                    ip_address=request.client.host if request.client else None, created_at=now))
    db.commit()
    return session_attendance(section_id, session_id, user, db)
