"""Sinh dữ liệu học tập GIẢ LẬP để nhóm làm việc trong lúc chờ dữ liệu thật.

Mỗi dòng là một sinh viên ở thời điểm GIỮA học kỳ. Các đặc trưng đều là thông tin
đã có trước khi thi cuối kỳ. Cột `semester_gpa` là kết quả cuối kỳ, chỉ dùng để tạo
nhãn `at_risk` và tuyệt đối không được dùng làm đầu vào cho mô hình.

Chạy:  python ml/scripts/generate_synthetic_data.py --n 2000
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

ML_DIR = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ML_DIR / "data" / "synthetic" / "students_synthetic.csv"

# Ngưỡng "học yếu": GPA học kỳ dưới 2.0 (thang 4). Cần chốt lại với thầy hướng dẫn.
AT_RISK_GPA = 2.0


def generate(n: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)

    # Hai yếu tố tiềm ẩn (không quan sát được) chi phối các đặc trưng bên dưới
    ability = rng.normal(0, 1, n)
    motivation = rng.normal(0, 1, n)

    gpa_prev = np.clip(2.7 + 0.55 * ability + rng.normal(0, 0.3, n), 0, 4)
    attendance_rate = np.clip(0.85 + 0.08 * motivation + 0.03 * ability + rng.normal(0, 0.06, n), 0, 1)
    midterm_avg = np.clip(6.5 + 1.2 * ability + 0.5 * motivation + rng.normal(0, 1.0, n), 0, 10)
    failed_courses_prev = rng.poisson(np.exp(-0.3 - 0.9 * ability))
    credits_registered = rng.integers(12, 25, n)
    assignment_submission_rate = np.clip(0.8 + 0.12 * motivation + rng.normal(0, 0.08, n), 0, 1)
    lms_logins_per_week = rng.poisson(np.exp(1.4 + 0.35 * motivation))

    semester_gpa = (
        0.55 * gpa_prev
        + 0.18 * (midterm_avg / 10 * 4)
        + 1.2 * (attendance_rate - 0.85)
        + 0.8 * (assignment_submission_rate - 0.8)
        - 0.12 * failed_courses_prev
        - 0.03 * (credits_registered - 18)
        + 0.95  # hằng số chỉnh để tỷ lệ học yếu khoảng 15%, gần với thực tế
        + rng.normal(0, 0.35, n)
    )
    semester_gpa = np.clip(semester_gpa, 0, 4)

    return pd.DataFrame(
        {
            "student_code": [f"SV{i:05d}" for i in range(1, n + 1)],
            "gpa_prev": gpa_prev.round(2),
            "attendance_rate": attendance_rate.round(3),
            "midterm_avg": midterm_avg.round(2),
            "failed_courses_prev": failed_courses_prev,
            "credits_registered": credits_registered,
            "assignment_submission_rate": assignment_submission_rate.round(3),
            "lms_logins_per_week": lms_logins_per_week,
            "semester_gpa": semester_gpa.round(2),
            "at_risk": (semester_gpa < AT_RISK_GPA).astype(int),
        }
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--n", type=int, default=2000, help="số sinh viên cần sinh")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    df = generate(args.n, args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False, encoding="utf-8")

    print(f"Đã sinh {len(df)} sinh viên -> {args.out}")
    print(f"Tỷ lệ học yếu (at_risk = 1): {df['at_risk'].mean():.1%}")


if __name__ == "__main__":
    main()
