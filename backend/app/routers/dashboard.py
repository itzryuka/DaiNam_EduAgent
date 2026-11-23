"""Trang Tổng quan trên CSDL v2: số liệu học kỳ hiện tại (nguy cơ theo lần chạy AI Agent gần nhất, chuyên cần)
và kết quả học tập qua các học kỳ (ĐTB, cảnh báo học tập, xếp loại).

Phạm vi dữ liệu:
- Quản trị: toàn trường (sinh viên đang học).
- Giảng viên: sinh viên lớp mình chủ nhiệm và sinh viên trong lớp học phần mình dạy kỳ này
  (giống phạm vi trang AI Agent).
"""

from collections import Counter, defaultdict
from math import floor

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import require_roles
from ..database_v2 import get_db_v2
from ..models_v2 import (AgentRun, Attendance, Class, ClassSession, Course, CourseSection, Enrollment, Prediction,
                         Semester, Student, User)
from ..services_v2 import current_semester, setting_float, today
from .me import RANKS, WARN_OWED_CREDITS, semester_summaries

router = APIRouter(prefix="/dashboard", tags=["Tổng quan"])
staff = require_roles("admin", "lecturer")


def _scope(db: Session, user: User, semester: Semester) -> tuple[set[int], set[int], str]:
    """(id sinh viên, id lượt đăng ký học kỳ hiện tại, mô tả phạm vi)."""
    current = (select(Enrollment.id, Enrollment.student_id).join(CourseSection)
               .where(CourseSection.semester_id == semester.id, Enrollment.status != "withdrawn"))
    if user.role == "admin":
        students = set(db.scalars(select(Student.id).where(Student.status == "studying")))
        enrollments = {r.id for r in db.execute(current) if r.student_id in students}
        return students, enrollments, "Toàn trường"
    lec = user.lecturer
    if lec is None:
        return set(), set(), "Không có dữ liệu"
    advised = set(db.scalars(select(Student.id).join(Class).where(Class.advisor_id == lec.id)))
    rows = db.execute(current.where((CourseSection.lecturer_id == lec.id) |
                                    Enrollment.student_id.in_(advised or {-1}))).all()
    taught = db.execute(current.where(CourseSection.lecturer_id == lec.id)).all()
    return advised | {r.student_id for r in taught}, {r.id for r in rows}, "Lớp bạn dạy và lớp chủ nhiệm"


def _history(db: Session, students: dict[int, dict]) -> tuple[list[dict], dict]:
    """Tổng kết từng học kỳ cho mọi sinh viên trong phạm vi (cùng cách tính với trang Kết quả học tập),
    gộp lại theo học kỳ. Trả (xu hướng theo học kỳ, tình trạng mới nhất của từng sinh viên)."""
    if not students:
        return [], {}
    rows = db.execute(
        select(Enrollment.student_id, Semester.id, Semester.code, Semester.name, Course.code, Course.credits,
               Enrollment.final_score, Enrollment.grade_point, Enrollment.passed)
        .join(CourseSection, CourseSection.id == Enrollment.section_id)
        .join(Course, Course.id == CourseSection.course_id)
        .join(Semester, Semester.id == CourseSection.semester_id)
        .where(Enrollment.student_id.in_(students))
        .order_by(Semester.start_date, Course.code)).all()
    per_student: dict[int, dict[int, dict]] = defaultdict(dict)
    sem_names: dict[str, str] = {}
    for sid, sem_id, code, name, course_code, credits, final, gp, passed in rows:
        sem_names[code] = name
        sem = per_student[sid].setdefault(sem_id, {"code": code, "name": name, "courses": []})
        sem["courses"].append({"course_code": course_code, "credits": credits, "final_score": final,
                               "grade_point": gp, "passed": passed})

    by_sem: dict[str, list[dict]] = defaultdict(list)
    latest: dict[int, dict] = {}
    for sid, sems in per_student.items():
        sem_list = list(sems.values())
        for sem, summary in zip(sem_list, semester_summaries(sem_list, students[sid]["cohort"])):
            if summary:
                by_sem[sem["code"]].append(summary)
                latest[sid] = {**summary, "semester": sem["name"]}

    trend = []
    for code in sorted(by_sem):
        items = by_sem[code]
        gpas = [x["gpa4"] for x in items if x["gpa4"] is not None]
        passed = sum(x["credits_passed"] for x in items)
        failed = sum(x["credits_failed"] for x in items)
        trend.append({
            "code": code, "name": sem_names[code], "n_students": len(items),
            "gpa4": round(sum(gpas) / len(gpas), 2) if gpas else None,
            "pass_rate": round(passed / (passed + failed), 3) if passed + failed else None,
            "warned": sum(x["warning"]["is_warned"] for x in items),
            "weak": sum(1 for g in gpas if g < 2.0),
        })
    return trend, latest


def _reason_group(reason: str) -> str:
    """Gộp lý do cảnh báo học tập (ngưỡng khác nhau theo năm học) thành 3 nhóm."""
    if reason.startswith("ĐTB học kỳ"):
        return "ĐTB học kỳ quá thấp"
    if reason.startswith("ĐTB tích lũy"):
        return "ĐTB tích lũy dưới mức tối thiểu"
    return f"Nợ quá {WARN_OWED_CREDITS} tín chỉ"


def _risk(db: Session, enrollment_ids: set[int], run_id: int | None) -> list[tuple]:
    if not run_id or not enrollment_ids:
        return []
    return db.execute(
        select(Prediction, Enrollment.student_id, Course.code, Course.name)
        .join(Enrollment, Enrollment.id == Prediction.enrollment_id)
        .join(CourseSection, CourseSection.id == Enrollment.section_id)
        .join(Course, Course.id == CourseSection.course_id)
        .where(Prediction.run_id == run_id, Prediction.enrollment_id.in_(enrollment_ids))).all()


def _attendance(db: Session, semester: Semester, enrollment_ids: set[int]) -> tuple[list[dict], dict]:
    if not enrollment_ids:
        return [], {"absent_rate": None, "late_rate": None, "over_limit": 0, "recorded": 0}
    rows = db.execute(
        select(ClassSession.session_date, Attendance.status, func.count())
        .join(Attendance, Attendance.session_id == ClassSession.id)
        .where(Attendance.enrollment_id.in_(enrollment_ids))
        .group_by(ClassSession.session_date, Attendance.status)).all()
    weeks: dict[int, Counter] = defaultdict(Counter)
    for day, status, n in rows:
        weeks[(day - semester.start_date).days // 7 + 1][status] += n
    by_week = []
    for week in sorted(weeks):
        c = weeks[week]
        total = sum(c.values())
        by_week.append({"week": week, "recorded": total,
                        "absent_rate": round((c["absent"] + c["excused"]) / total, 3),
                        "late_rate": round(c["late"] / total, 3)})
    total = Counter()
    for c in weeks.values():
        total.update(c)
    n = sum(total.values())

    # Sinh viên vắng quá ngưỡng cấm thi ở ít nhất một môn (vắng có phép cũng tính, như trang Lớp học phần)
    ban_ratio = setting_float(db, "absence_ban_ratio", 0.2)
    per_enrollment = db.execute(
        select(Enrollment.student_id, CourseSection.total_sessions, func.count())
        .join(Attendance, Attendance.enrollment_id == Enrollment.id)
        .join(CourseSection, CourseSection.id == Enrollment.section_id)
        .where(Enrollment.id.in_(enrollment_ids), Attendance.status.in_(("absent", "excused")))
        .group_by(Enrollment.id, Enrollment.student_id, CourseSection.total_sessions)).all()
    over = {sid for sid, sessions, absences in per_enrollment if absences > floor(ban_ratio * sessions)}
    return by_week, {"absent_rate": round((total["absent"] + total["excused"]) / n, 3) if n else None,
                     "late_rate": round(total["late"] / n, 3) if n else None,
                     "over_limit": len(over), "recorded": n}


@router.get("", summary="Số liệu trang Tổng quan (học kỳ hiện tại và các học kỳ đã qua)")
def dashboard(user: User = Depends(staff), db: Session = Depends(get_db_v2)):
    semester = current_semester(db)
    student_ids, enrollment_ids, scope = _scope(db, user, semester)
    students = {r.id: {"code": r.student_code, "name": r.full_name, "class_code": r.code, "cohort": r.cohort}
                for r in db.execute(select(Student.id, Student.student_code, Student.full_name, Class.code,
                                           Class.cohort).join(Class).where(Student.id.in_(student_ids or {-1})))}
    n_sections = db.scalar(select(func.count(func.distinct(Enrollment.section_id)))
                           .where(Enrollment.id.in_(enrollment_ids or {-1})))

    run = db.scalars(select(AgentRun).where(AgentRun.semester_id == semester.id, AgentRun.status == "success")
                     .order_by(AgentRun.as_of.desc(), AgentRun.id.desc())).first()
    preds = _risk(db, enrollment_ids, run.id if run else None)

    # Mỗi sinh viên một nhóm (loại trừ nhau, để vẽ cột chồng): nguy cơ cao > chỉ AI phát hiện > luật quy chế > bình thường
    per_student: dict[int, dict] = {}
    by_course: dict[str, dict] = {}
    for p, sid, course_code, course_name in preds:
        s = per_student.setdefault(sid, {"high": False, "sources": set(), "flagged": 0, "worst": None})
        s["high"] |= p.risk_level == "high"
        if p.flag_source != "none":
            s["sources"].add(p.flag_source)
            s["flagged"] += 1
        if s["worst"] is None or p.risk_probability > s["worst"]["proba"]:
            s["worst"] = {"proba": p.risk_probability, "level": p.risk_level, "source": p.flag_source,
                          "course": course_code, "checkpoint": p.checkpoint}
        c = by_course.setdefault(course_code, {"code": course_code, "name": course_name, "n": 0, "flagged": 0,
                                               "ai": 0, "proba_sum": 0.0})
        c["n"] += 1
        c["flagged"] += p.flag_source != "none"
        c["ai"] += p.flag_source == "ai"
        c["proba_sum"] += p.risk_probability

    def group(sid: int) -> str:
        s = per_student.get(sid)
        if not s or not s["sources"]:
            return "high" if s and s["high"] else "none"
        if s["high"]:
            return "high"
        return "ai" if s["sources"] == {"ai"} else "rule"

    by_class: dict[str, Counter] = defaultdict(Counter)
    for sid, info in students.items():
        by_class[info["class_code"]][group(sid)] += 1

    flagged_students = [sid for sid, s in per_student.items() if s["sources"]]
    courses = sorted((c for c in by_course.values() if c["n"] >= 5),
                     key=lambda c: (-c["flagged"] / c["n"], -c["flagged"]))[:8]
    top = sorted((sid for sid in flagged_students if sid in students),
                 key=lambda sid: -per_student[sid]["worst"]["proba"])[:10]

    trend, latest = _history(db, students)
    warned = [sid for sid, x in latest.items() if x["warning"]["is_warned"]]
    reasons = Counter(_reason_group(r) for sid in warned for r in latest[sid]["warning"]["reasons"])
    ranks = Counter(x["cum_rank"] for x in latest.values() if x["cum_rank"])
    weeks, attendance = _attendance(db, semester, enrollment_ids)

    week_now = max(1, (today() - semester.start_date).days // 7 + 1)
    return {
        "scope": scope,
        "semester": {"code": semester.code, "name": semester.name, "week": week_now,
                     "total_weeks": (semester.end_date - semester.start_date).days // 7 + 1},
        "run": {"id": run.id, "as_of": run.as_of.isoformat(timespec="minutes") if run.as_of else None,
                "finished_at": run.finished_at.isoformat(timespec="minutes") if run.finished_at else None,
                "trigger": run.trigger_type} if run else None,
        "cards": {
            "students": len(students), "sections": n_sections or 0, "enrollments": len(enrollment_ids),
            "predicted_students": len(per_student),
            "flagged_students": len(flagged_students),
            "ai_students": sum(1 for s in per_student.values() if "ai" in s["sources"]),
            "high_students": sum(1 for s in per_student.values() if s["high"]),
            "warned_students": len(warned), "warning_reasons": reasons.most_common(),
            "attendance": attendance,
        },
        "risk_by_class": [{"class_code": code, "total": sum(c.values()), "high": c["high"], "ai": c["ai"],
                           "rule": c["rule"], "none": c["none"]} for code, c in sorted(by_class.items())],
        "risk_by_course": [{"code": c["code"], "name": c["name"], "n": c["n"], "flagged": c["flagged"],
                            "ai": c["ai"], "rate": round(c["flagged"] / c["n"], 3),
                            "avg_proba": round(c["proba_sum"] / c["n"], 3)} for c in courses],
        "semesters": trend,
        "ranks": [{"rank": label, "n": ranks.get(label, 0)} for _, label in RANKS],
        "attendance_by_week": weeks,
        "top_students": [{"id": sid, "student_code": students[sid]["code"], "full_name": students[sid]["name"],
                          "class_code": students[sid]["class_code"], "flagged": per_student[sid]["flagged"],
                          **per_student[sid]["worst"]} for sid in top],
    }
