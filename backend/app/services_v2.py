"""Nghiệp vụ dùng chung trên CSDL v2: học kỳ hiện tại, tổng hợp điểm và chuyên cần của một lượt học."""

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models_v2 import Enrollment, Semester, Setting

PASS_SCORE = 4.0


def current_semester(db: Session) -> Semester | None:
    return db.scalar(select(Semester).where(Semester.is_current.is_(True))) or db.scalar(
        select(Semester).order_by(Semester.start_date.desc())
    )


def setting_float(db: Session, key: str, default: float) -> float:
    row = db.get(Setting, key)
    try:
        return float(row.value) if row else default
    except ValueError:
        return default


@dataclass
class EnrollmentSummary:
    """Tình hình một sinh viên trong một lớp học phần, tính đến hôm nay."""

    scores: dict[str, float] = field(default_factory=dict)  # mã đầu điểm -> điểm đã nhập
    present: int = 0
    late: int = 0
    excused: int = 0
    absent: int = 0
    total_sessions: int = 15
    process_score: float | None = None   # điểm quá trình (thang 10) trên các đầu điểm đã có, chưa gồm thi
    min_exam_score: float | None = None  # điểm thi tối thiểu để TBCHP >= 4.0 (khi đã đủ điểm quá trình)
    exam_unreachable: bool = False       # cần trên 10 điểm thi: không thể qua

    @property
    def recorded(self) -> int:
        return self.present + self.late + self.excused + self.absent

    @property
    def absences(self) -> int:
        return self.absent + self.excused

    @property
    def absence_rate(self) -> float | None:
        """Tỷ lệ vắng trên số buổi đã điểm danh."""
        return round(self.absences / self.recorded, 3) if self.recorded else None

    def absence_of_total(self) -> float:
        """Tỷ lệ vắng trên tổng số buổi của học phần (dùng để xét cấm thi)."""
        return self.absences / self.total_sessions if self.total_sessions else 0.0


def summarize(enrollment: Enrollment) -> EnrollmentSummary:
    """Gom điểm và điểm danh của một lượt học. Cần nạp sẵn enrollment.grades, .attendance, .section.course."""
    section = enrollment.section
    components = section.course.components
    by_id = {c.id: c for c in components}
    s = EnrollmentSummary(total_sessions=section.total_sessions)
    for g in enrollment.grades:
        s.scores[by_id[g.component_id].code] = g.score
    for a in enrollment.attendance:
        setattr(s, a.status, getattr(s, a.status) + 1)

    process = [c for c in components if not c.is_exam]
    entered = [c for c in process if c.code in s.scores]
    if entered:
        weight = sum(c.weight for c in entered)
        s.process_score = round(sum(c.weight * s.scores[c.code] for c in entered) / weight, 2)

    # Điểm thi tối thiểu: chỉ tính khi đã có hết điểm kiểm tra (CC chưa nhập thì tạm tính từ điểm danh)
    exam = next((c for c in components if c.is_exam), None)
    tests_done = all(c.code in s.scores for c in process if c.code != "CC")
    if exam and tests_done and "THI" not in s.scores:
        cc = s.scores.get("CC")
        if cc is None and s.recorded:
            cc = 10 * (s.present + 0.5 * s.late + 0.5 * s.excused) / s.recorded
        weighted = sum(c.weight * (cc if c.code == "CC" else s.scores[c.code]) for c in process if
                       c.code in s.scores or (c.code == "CC" and cc is not None))
        need = (PASS_SCORE - weighted) / exam.weight
        s.exam_unreachable = need > 10
        s.min_exam_score = round(min(max(need, 0.0), 10.0), 1)
    return s


def today() -> date:
    return date.today()
