"""Trang của sinh viên: kết quả học tập toàn khóa, điểm danh học kỳ hiện tại.

Sinh viên chỉ xem được dữ liệu của chính mình (lấy theo tài khoản đăng nhập, không nhận mã SV từ ngoài).
Không trả về xác suất trượt cho sinh viên (nguyên tắc thiết kế mục 6).
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..auth import require_roles
from ..database_v2 import get_db_v2
from ..models_v2 import ClassSession, Course, CourseSection, Enrollment, Lecturer, Student, User
from ..services_v2 import current_semester, setting_float, summarize, today

router = APIRouter(prefix="/me", tags=["Sinh viên"])

# Nạp sẵn dữ liệu liên quan trong vài truy vấn, tránh mỗi môn một truy vấn
LOADERS = (
    selectinload(Enrollment.section).selectinload(CourseSection.course).selectinload(Course.components),
    selectinload(Enrollment.section).selectinload(CourseSection.semester),
    selectinload(Enrollment.section).selectinload(CourseSection.lecturer).selectinload(Lecturer.user),
    selectinload(Enrollment.grades),
    selectinload(Enrollment.attendance),
)


def _student_id(user: User) -> int:
    if not user.student:
        raise HTTPException(404, "Tài khoản này chưa gắn với hồ sơ sinh viên")
    return user.student.id


@router.get("/results", summary="Kết quả học tập toàn khóa")
def results(user: User = Depends(require_roles("student")), db: Session = Depends(get_db_v2)):
    _student_id(user)
    return student_results(db, user.student)


def student_results(db: Session, s: Student) -> dict:
    """Bảng điểm toàn khóa và tổng kết từng học kỳ của một sinh viên (trang sinh viên và trang quản lý dùng chung)."""
    enrollments = db.scalars(select(Enrollment).where(Enrollment.student_id == s.id).options(*LOADERS)).all()

    semesters: dict[int, dict] = {}
    for e in sorted(enrollments, key=lambda e: (e.section.semester.start_date, e.section.course.code)):
        sec, course = e.section, e.section.course
        sem = semesters.setdefault(sec.semester.id, {
            "code": sec.semester.code, "name": sec.semester.name, "is_current": sec.semester.is_current,
            "courses": [],
        })
        summary = summarize(e)
        sem["courses"].append({
            "enrollment_id": e.id, "section_id": sec.id,
            "section_code": sec.code, "course_code": course.code, "course_name": course.name,
            "credits": course.credits, "attempt_no": e.attempt_no, "status": e.status,
            "components": [{"code": c.code, "name": c.name, "weight": c.weight} for c in course.components],
            "scores": summary.scores,
            # Môn đang học, đã đủ điểm kiểm tra: điểm thi tối thiểu cần đạt để qua môn
            "min_exam_score": summary.min_exam_score, "exam_unreachable": summary.exam_unreachable,
            "present": summary.present, "late": summary.late, "excused": summary.excused, "absent": summary.absent,
            "recorded": summary.recorded, "total_sessions": summary.total_sessions,
            "final_score": e.final_score, "letter_grade": e.letter_grade, "grade_point": e.grade_point,
            "passed": e.passed,
        })

    summaries = semester_summaries(list(semesters.values()), s.class_.cohort)
    for sem, summary in zip(semesters.values(), summaries):
        sem["summary"] = summary
        sem["gpa4"] = summary["gpa4"] if summary else None  # giữ trường cũ cho các trang đang dùng

    last = next((x for x in reversed(summaries) if x), None)
    return {
        "student": {"code": s.student_code, "full_name": s.full_name, "class_code": s.class_.code,
                    "cohort": s.class_.cohort},
        # Tổng kết toàn khóa = tổng kết tích lũy của học kỳ gần nhất đã có điểm
        "cumulative": {
            "gpa10": last["cum_gpa10"] if last else None, "gpa4": last["cum_gpa4"] if last else None,
            "rank": last["cum_rank"] if last else None,
            "credits_passed": last["cum_credits"] if last else 0,
            "credits_owed": last["owed_credits"] if last else 0,
            "failed_not_retaken": last["owed_courses"] if last else [],
            "semesters_done": sum(1 for x in summaries if x),
            "warning": last["warning"] if last else None,
        },
        "semesters": list(semesters.values()),
    }


# Xếp loại học lực theo điểm trung bình thang 4 (Thông tư 08/2021/TT-BGDĐT, Điều 10) [cần xác nhận quy chế Đại Nam]
RANKS = [(3.6, "Xuất sắc"), (3.2, "Giỏi"), (2.5, "Khá"), (2.0, "Trung bình"), (1.0, "Yếu"), (0.0, "Kém")]
# Cảnh báo học tập: ĐTB tích lũy tối thiểu theo năm học (năm 1, 2, 3, từ năm 4) và số tín chỉ nợ tối đa
WARN_CUM_GPA = [1.2, 1.4, 1.6, 1.8]
WARN_OWED_CREDITS = 24


def rank_of(gpa4: float | None) -> str | None:
    return None if gpa4 is None else next(label for low, label in RANKS if gpa4 >= low)


def _mean(items: list[dict], key: str) -> float | None:
    credits = sum(c["credits"] for c in items)
    return round(sum(c[key] * c["credits"] for c in items) / credits, 2) if credits else None


def semester_summaries(semesters: list[dict], cohort: int) -> list[dict | None]:
    """Tổng kết từng học kỳ như cổng thông tin sinh viên: điểm trung bình học kỳ và tích lũy (hệ 10, hệ 4),
    tín chỉ đăng ký / đạt / tích lũy, xếp loại, cảnh báo học tập. Học kỳ chưa có điểm tổng kết: None.

    - ĐTB học kỳ: mọi học phần có điểm tổng kết trong kỳ, kể cả học phần chưa đạt.
    - ĐTB tích lũy: mỗi học phần lấy lần học có điểm cao nhất, chỉ tính học phần đã đạt. [cần xác nhận]
    """
    best: dict[str, dict] = {}
    out = []
    for pos, sem in enumerate(semesters):
        done = [c for c in sem["courses"] if c["final_score"] is not None]
        for c in done:
            if c["course_code"] not in best or c["final_score"] > best[c["course_code"]]["final_score"]:
                best[c["course_code"]] = c
        if not done:
            out.append(None)
            continue
        passed_best = [c for c in best.values() if c["passed"]]
        owed = sorted(code for code, c in best.items() if not c["passed"])
        owed_credits = sum(best[code]["credits"] for code in owed)
        gpa4, cum_gpa4 = _mean(done, "grade_point"), _mean(passed_best, "grade_point")
        year = max(1, int(sem["code"][:4]) - (2006 + cohort) + 1)  # khóa 17 nhập học 2023 [cần xác nhận]
        reasons = []
        first_semester = pos == 0 and year == 1
        if gpa4 is not None and gpa4 < (0.8 if first_semester else 1.0):
            reasons.append(f"ĐTB học kỳ dưới {0.8 if first_semester else 1.0}")
        min_cum = WARN_CUM_GPA[min(year, 4) - 1]
        if cum_gpa4 is not None and cum_gpa4 < min_cum:
            reasons.append(f"ĐTB tích lũy dưới {min_cum} (năm thứ {year})")
        if owed_credits > WARN_OWED_CREDITS:
            reasons.append(f"Nợ {owed_credits} tín chỉ (quá {WARN_OWED_CREDITS})")
        out.append({
            "gpa10": _mean(done, "final_score"), "gpa4": gpa4, "rank": rank_of(gpa4),
            "cum_gpa10": _mean(passed_best, "final_score"), "cum_gpa4": cum_gpa4, "cum_rank": rank_of(cum_gpa4),
            "credits_registered": sum(c["credits"] for c in sem["courses"]),
            "credits_passed": sum(c["credits"] for c in done if c["passed"]),
            "credits_failed": sum(c["credits"] for c in done if not c["passed"]),
            "cum_credits": sum(c["credits"] for c in passed_best),
            "owed_courses": owed, "owed_credits": owed_credits, "year": year,
            "warning": {"is_warned": bool(reasons), "reasons": reasons},
        })
    return out


@router.get("/attendance", summary="Điểm danh các môn học kỳ hiện tại")
def attendance(user: User = Depends(require_roles("student")), db: Session = Depends(get_db_v2)):
    semester = current_semester(db)
    ban_ratio = setting_float(db, "absence_ban_ratio", 0.2)
    enrollments = db.scalars(
        select(Enrollment).join(Enrollment.section)
        .where(Enrollment.student_id == _student_id(user), CourseSection.semester_id == semester.id)
        .options(*LOADERS, selectinload(Enrollment.section).selectinload(CourseSection.sessions))
    ).all()

    courses = []
    for e in sorted(enrollments, key=lambda e: e.section.course.code):
        s = summarize(e)
        status_by_session = {a.session_id: a.status for a in e.attendance}
        sessions: list[ClassSession] = e.section.sessions
        lecturer = e.section.lecturer
        courses.append({
            "section_code": e.section.code, "course_code": e.section.course.code,
            "course_name": e.section.course.name,
            "lecturer": f"{lecturer.title or ''} {lecturer.user.full_name}".strip() if lecturer else None,
            "total_sessions": s.total_sessions, "recorded": s.recorded,
            "present": s.present, "late": s.late, "excused": s.excused, "absent": s.absent,
            # Số buổi còn được vắng trước khi chạm ngưỡng cấm thi
            "absences_allowed": int(ban_ratio * s.total_sessions),
            "sessions": [{"no": x.session_no, "date": x.session_date.isoformat(),
                          "status": status_by_session.get(x.id), "upcoming": x.session_date > today()}
                         for x in sessions],
        })
    return {"semester": semester.name, "ban_ratio": ban_ratio, "courses": courses}
