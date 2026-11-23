"""Ánh xạ các bảng của database/schema_v2.sql sang lớp Python (SQLAlchemy ORM).

Bảng được tạo bằng schema_v2.sql, file này chỉ mô tả lại để truy vấn. Mô tả từng bảng: docs/csdl-v2.md.
Bảng interventions (ghi nhận can thiệp) chưa ánh xạ: làm cùng chức năng giảng viên ghi nhận can thiệp.
"""

from datetime import date, datetime

from sqlalchemy import JSON, BigInteger, Enum, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database_v2 import BaseV2

Score = Numeric(3, 1, asdecimal=False)


class User(BaseV2):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(100))
    email_verified_at: Mapped[datetime | None]  # NULL = chưa xác nhận, không gửi email
    role: Mapped[str] = mapped_column(Enum("admin", "lecturer", "student"))
    is_active: Mapped[bool] = mapped_column(default=True)
    last_login_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)

    lecturer: Mapped["Lecturer | None"] = relationship(back_populates="user")
    student: Mapped["Student | None"] = relationship(back_populates="user")


class AuditLog(BaseV2):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(50))
    entity: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[int | None] = mapped_column(BigInteger)
    old_value: Mapped[dict | None] = mapped_column(JSON)
    new_value: Mapped[dict | None] = mapped_column(JSON)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)


class Setting(BaseV2):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(255))


class Lecturer(BaseV2):
    __tablename__ = "lecturers"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    lecturer_code: Mapped[str] = mapped_column(String(20), unique=True)
    department_id: Mapped[int]
    title: Mapped[str | None] = mapped_column(String(20))

    user: Mapped[User] = relationship(back_populates="lecturer")
    advised_classes: Mapped[list["Class"]] = relationship(back_populates="advisor")


class Semester(BaseV2):
    __tablename__ = "semesters"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    start_date: Mapped[date]
    end_date: Mapped[date]
    is_current: Mapped[bool] = mapped_column(default=False)


class Class(BaseV2):
    """Lớp hành chính."""

    __tablename__ = "classes"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    major_id: Mapped[int]
    cohort: Mapped[int]
    advisor_id: Mapped[int | None] = mapped_column(ForeignKey("lecturers.id"))

    advisor: Mapped[Lecturer | None] = relationship(back_populates="advised_classes")
    students: Mapped[list["Student"]] = relationship(back_populates="class_")


class Student(BaseV2):
    __tablename__ = "students"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), unique=True)
    student_code: Mapped[str] = mapped_column(String(20), unique=True)
    full_name: Mapped[str] = mapped_column(String(100))
    gender: Mapped[str | None] = mapped_column(Enum("M", "F"))
    date_of_birth: Mapped[date | None]
    email: Mapped[str | None] = mapped_column(String(100))
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"))
    status: Mapped[str] = mapped_column(Enum("studying", "reserved", "dropped", "graduated"))

    user: Mapped[User | None] = relationship(back_populates="student")
    class_: Mapped[Class] = relationship(back_populates="students")
    enrollments: Mapped[list["Enrollment"]] = relationship(back_populates="student")


class Course(BaseV2):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(150))
    credits: Mapped[int]
    course_group: Mapped[str] = mapped_column(Enum("general", "english", "major"))

    components: Mapped[list["CourseComponent"]] = relationship(
        back_populates="course", order_by="CourseComponent.sort_order"
    )


class CourseComponent(BaseV2):
    """Đầu điểm của môn (CC, KT1, KT2, KT3, THI) và trọng số."""

    __tablename__ = "course_components"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    code: Mapped[str] = mapped_column(String(10))
    name: Mapped[str] = mapped_column(String(50))
    weight: Mapped[float] = mapped_column(Numeric(4, 3, asdecimal=False))
    is_exam: Mapped[bool]
    sort_order: Mapped[int]

    course: Mapped[Course] = relationship(back_populates="components")


class CourseSection(BaseV2):
    """Lớp học phần."""

    __tablename__ = "course_sections"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    semester_id: Mapped[int] = mapped_column(ForeignKey("semesters.id"))
    lecturer_id: Mapped[int | None] = mapped_column(ForeignKey("lecturers.id"))
    room: Mapped[str | None] = mapped_column(String(20))
    total_sessions: Mapped[int]

    course: Mapped[Course] = relationship()
    semester: Mapped[Semester] = relationship()
    lecturer: Mapped[Lecturer | None] = relationship()
    enrollments: Mapped[list["Enrollment"]] = relationship(back_populates="section")
    sessions: Mapped[list["ClassSession"]] = relationship(order_by="ClassSession.session_no")
    assessments: Mapped[list["SectionAssessment"]] = relationship()


class SectionAssessment(BaseV2):
    __tablename__ = "section_assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    section_id: Mapped[int] = mapped_column(ForeignKey("course_sections.id"))
    component_id: Mapped[int] = mapped_column(ForeignKey("course_components.id"))
    planned_date: Mapped[date]


class Enrollment(BaseV2):
    __tablename__ = "enrollments"

    id: Mapped[int] = mapped_column(primary_key=True)
    section_id: Mapped[int] = mapped_column(ForeignKey("course_sections.id"))
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"))
    attempt_no: Mapped[int]
    status: Mapped[str] = mapped_column(Enum("studying", "withdrawn", "banned_exam", "completed"))
    final_score: Mapped[float | None] = mapped_column(Score)
    letter_grade: Mapped[str | None] = mapped_column(String(2))
    grade_point: Mapped[float | None] = mapped_column(Numeric(2, 1, asdecimal=False))
    passed: Mapped[bool | None]
    completed_at: Mapped[datetime | None]

    section: Mapped[CourseSection] = relationship(back_populates="enrollments")
    student: Mapped[Student] = relationship(back_populates="enrollments")
    grades: Mapped[list["Grade"]] = relationship(back_populates="enrollment")
    attendance: Mapped[list["Attendance"]] = relationship(back_populates="enrollment")


class Grade(BaseV2):
    __tablename__ = "grades"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    enrollment_id: Mapped[int] = mapped_column(ForeignKey("enrollments.id"))
    component_id: Mapped[int] = mapped_column(ForeignKey("course_components.id"))
    score: Mapped[float] = mapped_column(Score)
    entered_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    entered_at: Mapped[datetime] = mapped_column(default=datetime.now)

    enrollment: Mapped[Enrollment] = relationship(back_populates="grades")
    component: Mapped[CourseComponent] = relationship()


class ClassSession(BaseV2):
    __tablename__ = "class_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    section_id: Mapped[int] = mapped_column(ForeignKey("course_sections.id"))
    session_no: Mapped[int]
    session_date: Mapped[date]
    topic: Mapped[str | None] = mapped_column(String(150))


class Attendance(BaseV2):
    __tablename__ = "attendance"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("class_sessions.id"))
    enrollment_id: Mapped[int] = mapped_column(ForeignKey("enrollments.id"))
    status: Mapped[str] = mapped_column(Enum("present", "late", "excused", "absent"))
    recorded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    recorded_at: Mapped[datetime] = mapped_column(default=datetime.now)

    enrollment: Mapped[Enrollment] = relationship(back_populates="attendance")
    session: Mapped[ClassSession] = relationship()


# ---------------------------------------------------------------- AI Agent
class AgentRun(BaseV2):
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    trigger_type: Mapped[str] = mapped_column(Enum("schedule", "grade_update", "manual", "replay"))
    semester_id: Mapped[int | None]
    as_of: Mapped[datetime | None]
    started_by: Mapped[int | None]
    started_at: Mapped[datetime] = mapped_column(default=datetime.now)
    finished_at: Mapped[datetime | None]
    status: Mapped[str] = mapped_column(Enum("running", "success", "failed"), default="running")
    n_predictions: Mapped[int] = mapped_column(default=0)
    n_alerts: Mapped[int] = mapped_column(default=0)
    stats: Mapped[dict | None] = mapped_column(JSON)
    message: Mapped[str | None]


class Prediction(BaseV2):
    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("agent_runs.id"))
    enrollment_id: Mapped[int] = mapped_column(ForeignKey("enrollments.id"))
    checkpoint: Mapped[str] = mapped_column(Enum("M0", "M1", "M2"))
    model_name: Mapped[str] = mapped_column(String(50))
    model_version: Mapped[str | None] = mapped_column(String(30))
    risk_probability: Mapped[float] = mapped_column(Numeric(5, 4, asdecimal=False))
    risk_level: Mapped[str] = mapped_column(Enum("low", "medium", "high"))
    flag_source: Mapped[str] = mapped_column(Enum("none", "rule", "ai", "both"), default="none")
    rule_flags: Mapped[list | None] = mapped_column(JSON)
    top_factors: Mapped[list | None] = mapped_column(JSON)
    min_exam_score: Mapped[float | None] = mapped_column(Score)
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)

    enrollment: Mapped[Enrollment] = relationship()


class Alert(BaseV2):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    prediction_id: Mapped[int | None] = mapped_column(ForeignKey("predictions.id"))
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"))
    enrollment_id: Mapped[int | None] = mapped_column(ForeignKey("enrollments.id"))
    recipient_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    audience: Mapped[str] = mapped_column(Enum("lecturer", "advisor", "student"))
    channel: Mapped[str] = mapped_column(Enum("in_app", "email"), default="in_app")
    level: Mapped[str] = mapped_column(Enum("info", "warning", "danger"))
    title: Mapped[str] = mapped_column(String(200))
    message: Mapped[str]
    status: Mapped[str] = mapped_column(Enum("pending", "sent", "read", "failed"), default="pending")
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)
    sent_at: Mapped[datetime | None]
    read_at: Mapped[datetime | None]

    prediction: Mapped[Prediction | None] = relationship()


class EmailVerification(BaseV2):
    __tablename__ = "email_verifications"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    email: Mapped[str] = mapped_column(String(100))
    code_hash: Mapped[str] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(default=0)
    expires_at: Mapped[datetime]
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)


class EmailLog(BaseV2):
    __tablename__ = "email_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    to_email: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(Enum("verify", "alert", "test"))
    audience: Mapped[str | None] = mapped_column(Enum("lecturer", "advisor", "student"))
    run_id: Mapped[int | None] = mapped_column(ForeignKey("agent_runs.id"))
    n_alerts: Mapped[int] = mapped_column(default=0)
    subject: Mapped[str] = mapped_column(String(255))
    body: Mapped[str]
    status: Mapped[str] = mapped_column(Enum("sent", "outbox", "failed"))
    error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)

    user: Mapped[User | None] = relationship()
