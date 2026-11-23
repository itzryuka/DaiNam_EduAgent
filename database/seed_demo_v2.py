"""Sinh dữ liệu DEMO cho CSDL v2 (database/schema_v2.sql), theo cấu trúc đào tạo của Đại Nam.

Toàn bộ là dữ liệu GIẢ: họ tên ghép ngẫu nhiên, mã sinh viên 10 chữ số dạng 1871020001, email @example.edu.vn,
mã môn học chỉ để minh họa. Dùng để chạy thử giao diện, API và AI Agent. KHÔNG dùng để train mô hình
báo cáo trong đề tài (mô hình train trên OULAD, sau này trên dữ liệu thật của Đại Nam).

Mô phỏng:
  - 3 khóa (K17, K18, K19), 6 lớp hành chính, khoảng 240 sinh viên, 12 giảng viên (6 người kiêm CVHT)
  - 5 học kỳ, từ HK1 2024-2025 đến HK1 2026-2027 (kỳ hiện tại, đang diễn ra)
  - Mỗi lớp học phần 15 buổi, điểm danh từng buổi; đầu điểm CC, KT1, KT2, (KT3), Thi theo trọng số từng môn
  - Kỳ hiện tại chỉ có dữ liệu đến hôm nay: điểm danh các buổi đã qua, KT1 đã nhập, KT2 tùy lớp
  - Mỗi sinh viên có "năng lực" và "độ chăm chỉ" ẩn; một số sinh viên sa sút giữa kỳ (đi học ít dần,
    KT2 thấp hơn KT1) để AI Agent có tín hiệu xu hướng mà phát hiện
  - Sinh viên trượt môn có thể học lại ở kỳ sau (attempt_no = 2)

Chạy:  python database/seed_demo_v2.py            (CSDL eduagent_v2 phải đã import schema_v2.sql)
       python database/seed_demo_v2.py --reset    (xóa dữ liệu cũ rồi sinh lại)
Mọi tài khoản demo dùng chung mật khẩu DEMO_PASSWORD bên dưới; tên đăng nhập: admin, gv001.., mã sinh viên (1771020001..)
"""

import argparse
import math
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

import numpy as np
import pymysql

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import settings  # noqa: E402
from app.security import hash_password  # noqa: E402

DB_NAME = settings.db_name_v2
DEMO_PASSWORD = "DaiNam@2026"
SEED = 2026
WEEKS = 15
STUDENTS_PER_CLASS = 40
# Mã sinh viên giả, 10 chữ số giống thẻ SV Đại Nam: khóa (2) + mã ngành rút gọn (4) + số thứ tự (4),
# vd 1771020001 = khóa 17, ngành CNTT, sinh viên thứ 1. Không phải mã thật của ai.
STUDENT_CODE_MAJOR = {"CNTT": "7102", "KHMT": "7101"}
ABSENCE_BAN_RATIO = 0.20  # [cần xác nhận] vắng quá 20% số buổi thì cấm thi

SEMESTERS = [  # (mã, tên, ngày bắt đầu). Kết thúc = bắt đầu + 15 tuần học + 2 tuần thi
    ("2024-2025.1", "Học kỳ 1 năm học 2024-2025", date(2024, 9, 9)),
    ("2024-2025.2", "Học kỳ 2 năm học 2024-2025", date(2025, 2, 17)),
    ("2025-2026.1", "Học kỳ 1 năm học 2025-2026", date(2025, 9, 8)),
    ("2025-2026.2", "Học kỳ 2 năm học 2025-2026", date(2026, 2, 16)),
    ("2026-2027.1", "Học kỳ 1 năm học 2026-2027", date(2026, 9, 7)),
]
COHORTS = {17: 2023, 18: 2024, 19: 2025}  # khóa -> năm nhập học

COMPONENT_SCHEMES = {  # (mã, tên, trọng số, là bài thi) [cần xác nhận trọng số]
    "standard": [("CC", "Chuyên cần", 0.10, 0), ("KT1", "Kiểm tra 1", 0.15, 0), ("KT2", "Kiểm tra 2", 0.15, 0),
                 ("THI", "Thi kết thúc học phần", 0.60, 1)],
    "soft": [("CC", "Chuyên cần", 0.10, 0), ("KT1", "Kiểm tra 1", 0.20, 0), ("KT2", "Kiểm tra 2", 0.20, 0),
             ("THI", "Thi kết thúc học phần", 0.50, 1)],
    "kt3": [("CC", "Chuyên cần", 0.10, 0), ("KT1", "Kiểm tra 1", 0.10, 0), ("KT2", "Kiểm tra 2", 0.10, 0),
            ("KT3", "Kiểm tra 3", 0.10, 0), ("THI", "Thi kết thúc học phần", 0.60, 1)],
}
# Tuần dự kiến của từng đầu điểm [cần xác nhận]; THI sau tuần học
COMPONENT_WEEKS = {"KT1": (5, 7), "KT2": (10, 12), "KT3": (13, 13), "CC": (15, 15), "THI": (17, 17)}

# (mã minh họa, tên, tín chỉ, nhóm, độ khó, học kỳ thứ mấy trong chương trình, kiểu đầu điểm)
COURSES = [
    ("DNU1001", "Triết học Mác - Lênin", 3, "general", 0.2, 1, "standard"),
    ("ENG1001", "Tiếng Anh 1", 3, "english", 0.3, 1, "standard"),
    ("FIT1001", "Nhập môn Công nghệ thông tin", 3, "major", -0.3, 1, "standard"),
    ("FIT1002", "Toán rời rạc", 3, "major", 0.6, 1, "standard"),
    ("DNU1003", "Kỹ năng mềm", 2, "general", -0.6, 1, "soft"),
    ("DNU1002", "Kinh tế chính trị Mác - Lênin", 2, "general", 0.2, 2, "standard"),
    ("ENG1002", "Tiếng Anh 2", 3, "english", 0.3, 2, "standard"),
    ("FIT1003", "Lập trình C", 3, "major", 0.5, 2, "standard"),
    ("FIT1004", "Đại số tuyến tính", 3, "major", 0.5, 2, "standard"),
    ("ENG2001", "Tiếng Anh 3", 3, "english", 0.3, 3, "standard"),
    ("FIT2001", "Cấu trúc dữ liệu và giải thuật", 3, "major", 0.7, 3, "standard"),
    ("FIT2002", "Cơ sở dữ liệu", 3, "major", 0.3, 3, "standard"),
    ("FIT2003", "Kiến trúc máy tính", 3, "major", 0.4, 3, "standard"),
    ("DNU2001", "Chủ nghĩa xã hội khoa học", 2, "general", 0.1, 4, "standard"),
    ("FIT2004", "Lập trình hướng đối tượng", 3, "major", 0.5, 4, "standard"),
    ("FIT2005", "Mạng máy tính", 3, "major", 0.4, 4, "standard"),
    ("FIT2006", "Xác suất thống kê", 3, "major", 0.6, 4, "standard"),
    ("DNU3001", "Tư tưởng Hồ Chí Minh", 2, "general", 0.1, 5, "standard"),
    ("FIT3001", "Lập trình Web", 3, "major", 0.2, 5, "standard"),
    ("FIT3002", "Hệ điều hành", 3, "major", 0.5, 5, "standard"),
    ("FIT3003", "Phân tích và thiết kế hệ thống", 3, "major", 0.3, 5, "standard"),
    ("FIT3004", "Trí tuệ nhân tạo", 3, "major", 0.5, 6, "standard"),
    ("FIT3005", "Công nghệ phần mềm", 3, "major", 0.3, 6, "standard"),
    ("FIT3006", "An toàn thông tin", 3, "major", 0.4, 6, "standard"),
    ("FIT4001", "Học máy", 3, "major", 0.6, 7, "kt3"),
    ("FIT4002", "Phát triển ứng dụng di động", 3, "major", 0.3, 7, "standard"),
    ("FIT4003", "Điện toán đám mây", 3, "major", 0.3, 7, "standard"),
]

HO = ["Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Phan", "Vũ", "Đặng", "Bùi", "Đỗ", "Hồ", "Ngô", "Dương", "Lý", "Đinh"]
HO_P = [0.30, 0.11, 0.09, 0.07, 0.06, 0.05, 0.05, 0.04, 0.04, 0.04, 0.03, 0.03, 0.03, 0.03, 0.03]
DEM = {"M": ["Văn", "Đức", "Minh", "Quang", "Hữu", "Thành", "Công", "Tuấn", "Hoàng", "Gia", "Ngọc", "Xuân"],
       "F": ["Thị", "Thu", "Ngọc", "Thanh", "Phương", "Mai", "Khánh", "Hồng", "Minh", "Bảo"]}
TEN = {"M": ["Anh", "Bảo", "Cường", "Dũng", "Duy", "Đạt", "Hiếu", "Hùng", "Huy", "Khoa", "Long", "Mạnh", "Nam",
             "Phong", "Phúc", "Quân", "Sơn", "Tài", "Thắng", "Trung", "Tùng", "Việt", "Vinh", "Hải", "Lâm", "Khải"],
       "F": ["Anh", "Chi", "Dung", "Giang", "Hà", "Hạnh", "Hằng", "Hoa", "Hương", "Lan", "Linh", "Ly", "Mai", "My",
             "Ngân", "Nhung", "Phương", "Quỳnh", "Thảo", "Trang", "Vy", "Yến", "Hiền", "Diệp"]}
LETTERS = [("A+", 9.0, 4.0), ("A", 8.5, 3.7), ("B+", 8.0, 3.5), ("B", 7.0, 3.0), ("C+", 6.5, 2.5), ("C", 5.5, 2.0),
           ("D+", 5.0, 1.5), ("D", 4.0, 1.0), ("F", 0.0, 0.0)]


def sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def letter_of(score: float) -> tuple[str, float]:
    return next((letter, point) for letter, minimum, point in LETTERS if score >= minimum)


@dataclass
class Student:
    id: int
    code: str
    class_id: int
    cohort: int
    ability: float
    diligence: float
    shocks: list[float] = field(default_factory=list)


class Generator:
    def __init__(self, today: date, rng: np.random.Generator):
        self.today = today
        self.rng = rng
        self.rows: dict[str, list[tuple]] = {}
        self.ids: dict[str, int] = {}

    def add(self, table: str, row: tuple) -> int:
        """Thêm một dòng với id tự cấp (id luôn là cột đầu tiên)."""
        new_id = self.ids.get(table, 0) + 1
        self.ids[table] = new_id
        self.rows.setdefault(table, []).append((new_id, *row))
        return new_id

    def name(self, gender: str) -> str:
        return f"{self.rng.choice(HO, p=HO_P)} {self.rng.choice(DEM[gender])} {self.rng.choice(TEN[gender])}"

    def at(self, day: date, hour_from: int = 8, hour_to: int = 22) -> datetime:
        return datetime.combine(day, time(int(self.rng.integers(hour_from, hour_to)), int(self.rng.integers(0, 60))))

    # ------------------------------------------------------------ danh mục
    def build_catalog(self) -> None:
        rng = self.rng
        lecturer_hash, student_hash, admin_hash = (hash_password(DEMO_PASSWORD) for _ in range(3))
        self.add("users", ("admin", admin_hash, "Quản trị hệ thống", "admin@example.edu.vn", "admin"))

        dept = self.add("departments", ("FIT", "Khoa Công nghệ thông tin"))
        self.add("departments", ("DNU", "Khối kiến thức chung"))
        self.add("departments", ("ENG", "Khoa Ngoại ngữ"))
        majors = {"CNTT": self.add("majors", (dept, "7480201", "Công nghệ thông tin")),
                  "KHMT": self.add("majors", (dept, "7480101", "Khoa học máy tính"))}

        self.lecturers = []  # (lecturer_id, user_id)
        for i in range(1, 13):
            gender = "M" if rng.random() < 0.6 else "F"
            code = f"GV{i:03d}"
            user_id = self.add("users", (code.lower(), lecturer_hash, self.name(gender),
                                         f"{code.lower()}@example.edu.vn", "lecturer"))
            title = rng.choice(["ThS", "ThS", "ThS", "TS", "TS", "PGS.TS"])
            self.lecturers.append((self.add("lecturers", (user_id, code, dept, title, None)), user_id))

        self.semesters = []
        for pos, (code, name, start) in enumerate(SEMESTERS):
            end = start + timedelta(weeks=WEEKS + 2) - timedelta(days=1)
            is_current = int(start <= self.today <= end or (pos == len(SEMESTERS) - 1 and self.today > end))
            self.semesters.append((self.add("semesters", (code, name, start, end, is_current)), start, end))

        self.courses = {}
        for code, name, credits, group, diff, idx, scheme in COURSES:
            dept_id = {"FIT": 1, "DNU": 2, "ENG": 3}[code[:3]]
            cid = self.add("courses", (code, name, credits, dept_id, group))
            comps = []
            for order, (ccode, cname, weight, is_exam) in enumerate(COMPONENT_SCHEMES[scheme], start=1):
                comps.append((self.add("course_components", (cid, ccode, cname, weight, is_exam, order)), ccode,
                              weight))
            self.courses[code] = {"id": cid, "diff": diff, "idx": idx, "credits": credits, "components": comps}

        self.classes = {}  # class_id -> (cohort, lecturer cvht)
        self.student_seq = {}  # (khóa, ngành) -> số thứ tự sinh viên đã cấp mã
        self.students: list[Student] = []
        advisor_iter = iter(self.lecturers)
        for cohort in COHORTS:
            for n in (1, 2):
                major = majors["KHMT"] if (cohort == 19 and n == 2) else majors["CNTT"]
                prefix = "KHMT" if major == majors["KHMT"] else "CNTT"
                advisor = next(advisor_iter)[0]
                class_id = self.add("classes", (f"{prefix} {cohort}-{n:02d}", major, cohort, advisor))
                self.classes[class_id] = cohort
                for _ in range(STUDENTS_PER_CLASS):
                    self.add_student(class_id, cohort, prefix, student_hash)

    def add_student(self, class_id: int, cohort: int, major: str, password_hash: str) -> None:
        rng = self.rng
        self.student_seq[(cohort, major)] = seq = self.student_seq.get((cohort, major), 0) + 1
        code = f"{cohort}{STUDENT_CODE_MAJOR[major]}{seq:04d}"
        gender = "M" if rng.random() < 0.75 else "F"
        full_name = self.name(gender)
        birth = date(COHORTS[cohort] - 18, 1, 1) + timedelta(days=int(rng.integers(0, 365)))
        email = f"{code.lower()}@example.edu.vn"
        user_id = self.add("users", (code, password_hash, full_name, email, "student"))
        sid = self.add("students", (user_id, code, full_name, gender, birth, email, class_id, "studying"))
        ability = float(rng.normal())
        diligence = float(0.4 * ability + math.sqrt(1 - 0.16) * rng.normal())
        shocks = [float(rng.normal(0, 0.5)) for _ in SEMESTERS]
        self.students.append(Student(sid, code, class_id, cohort, ability, diligence, shocks))

    # ------------------------------------------------------------ học kỳ
    def build_semesters(self) -> None:
        failed: dict[tuple[int, str], int] = {}  # (student_id, mã môn) -> số lần đã học, chờ học lại
        section_no = 0
        for pos, (sem_id, start, end) in enumerate(self.semesters):
            sections_by_course: dict[str, list[int]] = {}
            enrollments = []  # (student, section_id, course_code, attempt)
            for cohort, year in COHORTS.items():
                idx = pos - (year - 2024) * 2 + 1  # học kỳ thứ mấy của khóa này
                cohort_classes = [c for c, k in self.classes.items() if k == cohort]
                for code, course in self.courses.items():
                    if course["idx"] != idx:
                        continue
                    for class_id in cohort_classes:
                        section_no += 1
                        lecturer_id, lecturer_user = self.lecturers[int(self.rng.integers(len(self.lecturers)))]
                        sec_code = f"{code}-{SEMESTERS[pos][0]}-{len(sections_by_course.get(code, [])) + 1:02d}"
                        section_id = self.add("course_sections", (sec_code, course["id"], sem_id, lecturer_id,
                                                                  f"A{int(self.rng.integers(101, 510))}", WEEKS))
                        self.section_meta[section_id] = {"lecturer_user": lecturer_user, "weekday": section_no % 5,
                                                         "start": start, "course": code, "pos": pos}
                        sections_by_course.setdefault(code, []).append(section_id)
                        for st in self.students:
                            if st.class_id == class_id:
                                enrollments.append((st, section_id, code, 1))

            # Học lại môn đã trượt nếu kỳ này có lớp mở môn đó
            for (sid, code), attempts in list(failed.items()):
                if code in sections_by_course and self.rng.random() < 0.7:
                    st = next(s for s in self.students if s.id == sid)
                    section_id = int(self.rng.choice(sections_by_course[code]))
                    if not any(e[0].id == sid and e[1] == section_id for e in enrollments):
                        enrollments.append((st, section_id, code, attempts + 1))
                        del failed[(sid, code)]

            for section_id in {e[1] for e in enrollments}:
                self.build_sessions_and_schedule(section_id)
            for st, section_id, code, attempt in enrollments:
                passed = self.simulate(st, section_id, code, attempt, pos)
                if passed is False:
                    failed[(st.id, code)] = attempt

    def build_sessions_and_schedule(self, section_id: int) -> None:
        meta = self.section_meta[section_id]
        first_day = meta["start"] + timedelta(days=meta["weekday"])
        meta["sessions"] = []
        for k in range(1, WEEKS + 1):
            day = first_day + timedelta(weeks=k - 1)
            meta["sessions"].append((self.add("class_sessions", (section_id, k, day, f"Buổi {k}")), day))
        meta["planned"], meta["entered"] = {}, {}
        for comp_id, ccode, _ in self.courses[meta["course"]]["components"]:
            lo, hi = COMPONENT_WEEKS[ccode]
            week = int(self.rng.integers(lo, hi + 1))
            planned = first_day + timedelta(weeks=week - 1)
            meta["planned"][ccode] = (planned, week)
            # Giảng viên nhập điểm cả lớp cùng lúc, vài ngày sau buổi kiểm tra
            meta["entered"][ccode] = planned + timedelta(days=int(self.rng.integers(2, 9)))
            self.add("section_assessments", (section_id, comp_id, planned))

    def simulate(self, st: Student, section_id: int, code: str, attempt: int, pos: int) -> bool | None:
        """Sinh điểm danh, điểm thành phần và kết quả. Trả về passed (None nếu môn chưa kết thúc)."""
        rng, meta, course = self.rng, self.section_meta[section_id], self.courses[code]
        ability = st.ability + (0.25 if attempt > 1 else 0)
        dil, shock, diff = st.diligence, st.shocks[pos], course["diff"]
        declining = rng.random() < sigmoid(-2.6 - 0.7 * dil - 0.8 * shock)
        decline_week = int(rng.integers(5, 10))
        enrollment_id = self.add("enrollments", (section_id, st.id, attempt, "studying", None, None, None, None, None))

        # Điểm danh từng buổi (kỳ hiện tại: chỉ các buổi đã qua)
        counts = {"present": 0, "late": 0, "excused": 0, "absent": 0}
        for k, (session_id, day) in enumerate(meta["sessions"], start=1):
            if day > self.today:
                break
            logit = 3.9 + 0.9 * dil + 0.4 * shock - 0.3 * diff - (2.3 if declining and k >= decline_week else 0)
            if rng.random() < sigmoid(logit):
                status = "late" if rng.random() < 0.08 else "present"
            else:
                status = "excused" if rng.random() < 0.25 else "absent"
            counts[status] += 1
            self.add("attendance", (session_id, enrollment_id, status, meta["lecturer_user"], self.at(day, 7, 18)))

        # Điểm thành phần, nhập vài ngày sau ngày kiểm tra
        scores, kt_scores = {}, []
        for comp_id, ccode, weight in course["components"]:
            planned, week = meta["planned"][ccode]
            entered = meta["entered"][ccode]
            if entered > self.today:
                continue
            if ccode == "CC":
                score = 10 * (counts["present"] + 0.5 * counts["late"] + 0.5 * counts["excused"]) / WEEKS
            elif ccode == "THI":
                if (counts["absent"] + counts["excused"]) / WEEKS > ABSENCE_BAN_RATIO:
                    scores["THI"] = None  # bị cấm thi
                    continue
                process = np.mean(kt_scores) if kt_scores else 5.0
                mu = 6.3 + 1.4 * ability + 0.4 * dil - 1.2 * diff + 0.25 * (process - 6) + 0.3 * shock
                score = rng.normal(mu - (1.0 if declining else 0), 1.6)
            else:
                late_part = declining and week >= decline_week
                missed = rng.random() < sigmoid(-3.6 - 1.0 * dil + (2.2 if late_part else 0))
                mu = 6.8 + 1.2 * ability + 0.5 * dil - 1.0 * diff + 0.4 * shock - (2.0 if late_part else 0)
                score = 0.0 if missed else rng.normal(mu, 1.3)
                kt_scores.append(score)
            score = float(np.clip(round(score * 2) / 2 if ccode != "CC" else round(score, 1), 0, 10))
            scores[ccode] = score
            self.add("grades", (enrollment_id, comp_id, score, meta["lecturer_user"], self.at(entered),
                                self.at(entered)))

        if "THI" not in scores:
            return None  # chưa thi: kỳ đang diễn ra
        weights = {ccode: w for _, ccode, w in course["components"]}
        final = round(sum(weights[c] * (s or 0) for c, s in scores.items()), 1)
        letter, point = letter_of(final)
        status = "banned_exam" if scores["THI"] is None else "completed"
        completed = datetime.combine(meta["planned"]["THI"][0] + timedelta(days=10), time(9))
        e = self.rows["enrollments"][enrollment_id - 1]
        self.rows["enrollments"][enrollment_id - 1] = (e[0], e[1], e[2], e[3], status, final, letter, point,
                                                       int(final >= 4.0), completed)
        return final >= 4.0

    def generate(self) -> dict[str, list[tuple]]:
        self.section_meta = {}
        self.build_catalog()
        self.build_semesters()
        return self.rows


COLUMNS = {  # thứ tự chèn (theo khóa ngoại) và tên cột
    "users": "id, username, password_hash, full_name, email, role",
    "departments": "id, code, name",
    "majors": "id, department_id, code, name",
    "lecturers": "id, user_id, lecturer_code, department_id, title, phone",
    "semesters": "id, code, name, start_date, end_date, is_current",
    "classes": "id, code, major_id, cohort, advisor_id",
    "students": "id, user_id, student_code, full_name, gender, date_of_birth, email, class_id, status",
    "courses": "id, code, name, credits, department_id, course_group",
    "course_components": "id, course_id, code, name, weight, is_exam, sort_order",
    "course_sections": "id, code, course_id, semester_id, lecturer_id, room, total_sessions",
    "class_sessions": "id, section_id, session_no, session_date, topic",
    "section_assessments": "id, section_id, component_id, planned_date",
    "enrollments": "id, section_id, student_id, attempt_no, status, final_score, letter_grade, grade_point, "
                   "passed, completed_at",
    "attendance": "id, session_id, enrollment_id, status, recorded_by, recorded_at",
    "grades": "id, enrollment_id, component_id, score, entered_by, entered_at, updated_at",
}
# Bảng xóa khi --reset (giữ grade_scale và settings)
RESET_TABLES = ["interventions", "alerts", "predictions", "agent_runs", "audit_logs", *reversed(COLUMNS)]


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reset", action="store_true", help="xóa dữ liệu cũ trong eduagent_v2 rồi sinh lại")
    parser.add_argument("--today", type=date.fromisoformat, default=date.today(),
                        help="ngày 'hôm nay' của kỳ hiện tại, vd 2026-11-16")
    args = parser.parse_args()

    conn = pymysql.connect(**settings.pymysql_kwargs(DB_NAME), autocommit=False)
    with conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM users")
        if cur.fetchone()[0] and not args.reset:
            raise SystemExit(f"{DB_NAME} đã có dữ liệu. Thêm --reset để xóa và sinh lại.")
        cur.execute("SET FOREIGN_KEY_CHECKS = 0")
        for table in RESET_TABLES:
            cur.execute(f"TRUNCATE TABLE {table}")
        cur.execute("SET FOREIGN_KEY_CHECKS = 1")

        rows = Generator(args.today, np.random.default_rng(SEED)).generate()
        for table, columns in COLUMNS.items():
            data = rows.get(table, [])
            placeholders = ", ".join(["%s"] * len(columns.split(",")))
            sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
            for i in range(0, len(data), 5000):
                cur.executemany(sql, data[i:i + 5000])
        conn.commit()

        print(f"Đã sinh dữ liệu demo vào {DB_NAME} (hôm nay = {args.today}):")
        for table in COLUMNS:
            print(f"  {table:<20} {len(rows.get(table, [])):>7} dòng")
        cur.execute("""SELECT s.code, COUNT(*), AVG(e.passed = 0), AVG(e.status = 'banned_exam')
                       FROM enrollments e JOIN course_sections cs ON cs.id = e.section_id
                       JOIN semesters s ON s.id = cs.semester_id
                       GROUP BY s.code ORDER BY s.code""")
        print("\n  Học kỳ        Lượt học   Tỷ lệ trượt   Cấm thi")
        for code, n, fail, banned in cur.fetchall():
            fail_txt = f"{float(fail):.1%}" if fail is not None else "chưa thi"
            banned_txt = f"{float(banned):.1%}" if fail is not None else ""
            print(f"  {code:<13} {n:>8}   {fail_txt:>11}   {banned_txt:>7}")
        print(f"\nTài khoản demo: admin, gv001..gv012, mã sinh viên 1771020001...; mật khẩu chung: xem DEMO_PASSWORD trong {Path(__file__).name}")


if __name__ == "__main__":
    main()
