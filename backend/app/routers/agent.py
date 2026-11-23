"""API của AI Agent: chạy Agent, nhật ký các lần chạy, danh sách sinh viên cần chú ý, kiểm chứng trên kỳ cũ, cảnh báo."""

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from ..agent import CHECKPOINT_LABELS, MODEL_DIR, AgentError, models_ready, run_agent
from ..auth import get_current_user, require_roles
from ..database_v2 import get_db_v2
from ..models_v2 import AgentRun, Alert, Class, Course, CourseSection, Enrollment, Lecturer, Prediction, Student, User
from ..services_v2 import current_semester

router = APIRouter(tags=["AI Agent"])
staff = require_roles("lecturer", "admin")
TRIGGER_LABELS = {"schedule": "Theo lịch", "grade_update": "Có điểm mới", "manual": "Chạy tay", "replay": "Chạy lại"}


def _run_out(run: AgentRun) -> dict:
    return {"id": run.id, "trigger": run.trigger_type, "trigger_label": TRIGGER_LABELS[run.trigger_type],
            "as_of": run.as_of, "started_at": run.started_at, "finished_at": run.finished_at, "status": run.status,
            "n_predictions": run.n_predictions, "n_alerts": run.n_alerts, "message": run.message, "stats": run.stats}


def _latest_run(db: Session) -> AgentRun | None:
    semester = current_semester(db)
    return db.scalar(select(AgentRun).where(AgentRun.semester_id == semester.id, AgentRun.status == "success")
                     .order_by(AgentRun.as_of.desc(), AgentRun.id.desc()))


@router.post("/agent/run", summary="Chạy Agent ngay (quản trị)")
def run_now(user: User = Depends(require_roles("admin")), db: Session = Depends(get_db_v2)):
    try:
        run = run_agent(db, "manual", started_by=user.id)
    except AgentError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _run_out(run)


@router.get("/agent/runs", summary="Nhật ký các lần Agent chạy")
def runs(limit: int = 15, user: User = Depends(staff), db: Session = Depends(get_db_v2)):
    rows = db.scalars(select(AgentRun).order_by(AgentRun.id.desc()).limit(min(limit, 100))).all()
    return [_run_out(r) for r in rows]


@router.get("/agent/overview", summary="Lần chạy gần nhất của Agent (số liệu 5 tầng)")
def overview(user: User = Depends(staff), db: Session = Depends(get_db_v2)):
    run = _latest_run(db)
    return {"models_ready": models_ready(), "semester": current_semester(db).name,
            "run": _run_out(run) if run else None, "can_run": user.role == "admin"}


def _scope(query, user: User):
    """Giảng viên chỉ thấy sinh viên lớp học phần mình dạy và lớp hành chính mình làm CVHT."""
    if user.role == "lecturer":
        query = query.where(or_(CourseSection.lecturer_id == user.lecturer.id, Class.advisor_id == user.lecturer.id))
    return query


@router.get("/agent/predictions", summary="Sinh viên × môn theo lần chạy gần nhất (lọc theo nguồn, mức)")
def predictions(source: str | None = None, level: str | None = None, section_id: int | None = None,
                only_flagged: bool = True, q: str | None = None, limit: int = 300,
                user: User = Depends(staff), db: Session = Depends(get_db_v2)):
    run = _latest_run(db)
    if run is None:
        return {"run": None, "items": [], "counts": {}}
    base = (select(Prediction, Enrollment, Student, CourseSection, Course, Class)
            .join(Enrollment, Enrollment.id == Prediction.enrollment_id)
            .join(Student, Student.id == Enrollment.student_id)
            .join(CourseSection, CourseSection.id == Enrollment.section_id)
            .join(Course, Course.id == CourseSection.course_id)
            .join(Class, Class.id == Student.class_id)
            .where(Prediction.run_id == run.id))
    base = _scope(base, user)
    if section_id:
        base = base.where(CourseSection.id == section_id)
    if q:
        like = f"%{q.strip()}%"
        base = base.where(or_(Student.student_code.like(like), Student.full_name.like(like),
                              Course.code.like(like), Course.name.like(like)))

    counts = {"all": 0, "ai": 0, "both": 0, "rule": 0, "none": 0}
    for src, n in db.execute(base.with_only_columns(Prediction.flag_source, func.count())
                             .group_by(Prediction.flag_source)).all():
        counts[src] = n
        counts["all"] += n

    query = base
    if source:
        query = query.where(Prediction.flag_source.in_(source.split(",")))
    elif only_flagged:
        query = query.where(Prediction.flag_source != "none")
    if level:
        query = query.where(Prediction.risk_level.in_(level.split(",")))
    rows = db.execute(query.order_by(Prediction.risk_probability.desc()).limit(min(limit, 2000))).all()

    # Diễn biến: xác suất ở các lần chạy trước của cùng lượt học (vd đầu kỳ -> hiện tại)
    ids = [p.enrollment_id for p, *_ in rows]
    history: dict[int, list] = {}
    if ids:
        for eid, cp, prob, at in db.execute(
                select(Prediction.enrollment_id, Prediction.checkpoint, Prediction.risk_probability,
                       Prediction.created_at).where(Prediction.enrollment_id.in_(ids))
                .order_by(Prediction.created_at)).all():
            history.setdefault(eid, []).append({"checkpoint": cp, "proba": prob, "at": at})

    lecturers = {lec.id: lec.user.full_name for lec in db.scalars(select(Lecturer).options(
        selectinload(Lecturer.user))).all()}
    items = [{
        "prediction_id": p.id, "enrollment_id": e.id, "student_code": st.student_code, "full_name": st.full_name,
        "class_code": cl.code, "section_id": sec.id, "section_code": sec.code, "course_code": c.code,
        "course_name": c.name, "lecturer": lecturers.get(sec.lecturer_id),
        "checkpoint": p.checkpoint, "checkpoint_label": CHECKPOINT_LABELS[p.checkpoint],
        "proba": p.risk_probability, "level": p.risk_level, "source": p.flag_source,
        "rule_flags": p.rule_flags or [], "factors": p.top_factors or [], "attempt_no": e.attempt_no,
        "history": history.get(e.id, []),
    } for p, e, st, sec, c, cl in rows]
    return {"run": _run_out(run), "items": items, "counts": counts}


@router.get("/agent/backtest", summary="Kiểm chứng: chạy lại Agent trên học kỳ gần nhất đã biết kết quả")
def backtest(user: User = Depends(staff), db: Session = Depends(get_db_v2)):
    path = MODEL_DIR / "results.json"
    if not path.exists():
        raise HTTPException(404, "Chưa train mô hình Agent. Chạy: python ml/train_dainam.py")
    results = json.loads(path.read_text(encoding="utf-8"))
    out = {"trained_at": results["trained_at"], "data": results["data"], "checkpoints": {}}
    for cp, r in results["checkpoints"].items():
        b = dict(r["backtest"])
        rows = b.pop("rows")
        # Ví dụ: sinh viên AI cảnh báo đúng mà luật bỏ sót (trượt thật, luật không bắt)
        examples = sorted((x for x in rows if x["ai"] and not x["rule"] and x["fail"]), key=lambda x: -x["proba"])[:8]
        info = {}
        if examples:
            for e, st, c in db.execute(
                    select(Enrollment, Student, Course).join(Student, Student.id == Enrollment.student_id)
                    .join(CourseSection, CourseSection.id == Enrollment.section_id)
                    .join(Course, Course.id == CourseSection.course_id)
                    .where(Enrollment.id.in_([x["enrollment_id"] for x in examples]))).all():
                info[e.id] = {"student_code": st.student_code, "full_name": st.full_name, "course_code": c.code,
                              "course_name": c.name, "final_score": e.final_score, "status": e.status}
        b["examples"] = [{**x, **info.get(x["enrollment_id"], {})} for x in examples]
        out["checkpoints"][cp] = {"label": r["label"], "chosen": r["chosen"], "thresholds": r["thresholds"],
                                  "split": r["split"], "backtest": b,
                                  "best_val_pr_auc": max(c["val_pr_auc"] for c in r["candidates"])}
    return out


# ------------------------------------------------------------------ cảnh báo của người đang đăng nhập
@router.get("/alerts/mine", summary="Cảnh báo gửi tới tài khoản đang đăng nhập")
def my_alerts(limit: int = 30, unread_only: bool = False, user: User = Depends(get_current_user),
              db: Session = Depends(get_db_v2)):
    query = select(Alert).where(Alert.recipient_user_id == user.id)
    if unread_only:
        query = query.where(Alert.read_at.is_(None))
    unread = db.scalar(select(func.count()).select_from(Alert)
                       .where(Alert.recipient_user_id == user.id, Alert.read_at.is_(None)))
    rows = db.scalars(query.order_by(Alert.created_at.desc(), Alert.id.desc()).limit(min(limit, 200))).all()
    return {"unread": unread, "items": [{
        "id": a.id, "level": a.level, "audience": a.audience, "title": a.title, "message": a.message,
        "created_at": a.created_at, "read": a.read_at is not None, "enrollment_id": a.enrollment_id,
    } for a in rows]}


@router.post("/alerts/{alert_id}/read", summary="Đánh dấu đã đọc")
def mark_read(alert_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db_v2)):
    alert = db.get(Alert, alert_id)
    if alert is None or alert.recipient_user_id != user.id:
        raise HTTPException(404, "Không tìm thấy cảnh báo")
    if alert.read_at is None:
        alert.read_at, alert.status = datetime.now(), "read"
        db.commit()
    return {"ok": True}


@router.post("/alerts/read-all", summary="Đánh dấu tất cả đã đọc")
def mark_all_read(user: User = Depends(get_current_user), db: Session = Depends(get_db_v2)):
    for alert in db.scalars(select(Alert).where(Alert.recipient_user_id == user.id, Alert.read_at.is_(None))):
        alert.read_at, alert.status = datetime.now(), "read"
    db.commit()
    return {"ok": True}
