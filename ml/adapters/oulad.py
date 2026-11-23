"""Quy đổi dữ liệu OULAD về lược đồ đặc trưng chung (ml/common_schema.py) tại 3 mốc M0, M1, M2.

- Mỗi dòng: một sinh viên trong một lượt mở môn (code_module + code_presentation).
- Nhãn fail = 1 nếu final_result = "Fail"; Pass và Distinction = 0; Withdrawn (rút môn) bị loại.
- Chỉ dùng thông tin có trước ngày cắt của mốc (cột date = số ngày tính từ khi môn bắt đầu),
  để mô hình không "nhìn thấy tương lai".

Mốc cắt cho từng lượt mở môn (chỉ xét bài kiểm tra trong kỳ, không xét bài thi):
  M0 = ngày 0 (bắt đầu môn)
  M1 = ngày đến hạn của bài kiểm tra làm tổng trọng số đã đến hạn đạt >= 40%
       (tương tự Đại Nam khi đã có CC + KT1)
  M2 = ngày đến hạn của bài kiểm tra cuối cùng (đủ điểm quá trình, trước khi thi)

Chạy:  python ml/adapters/oulad.py
Kết quả: ml/data/processed/oulad_M0.csv, oulad_M1.csv, oulad_M2.csv
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ML_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ML_DIR))

from common_schema import ALL_FEATURES, CHECKPOINTS, META, TARGET  # noqa: E402

DEFAULT_DATA = ML_DIR / "data" / "public" / "oulad"
DEFAULT_OUT = ML_DIR / "data" / "processed"

# Thứ tự thời gian các lượt mở môn: B bắt đầu tháng 2, J bắt đầu tháng 10
TERM_ORDER = ["2013B", "2013J", "2014B", "2014J"]
M1_WEIGHT_SHARE = 0.4
RECENT_DAYS = 14
MAX_INACTIVE_DAYS = 60
KEYS = ["code_module", "code_presentation"]


def read(data_dir: Path, name: str, **kwargs) -> pd.DataFrame:
    # OULAD ghi giá trị thiếu bằng dấu "?"
    return pd.read_csv(data_dir / f"{name}.csv", na_values="?", **kwargs)


def presentation_id(df: pd.DataFrame) -> pd.Series:
    return df["code_module"].astype(str) + "_" + df["code_presentation"].astype(str)


def checkpoint_days(graded: pd.DataFrame) -> pd.DataFrame:
    """Ngày cắt của từng mốc cho mỗi lượt mở môn. `graded` là các bài kiểm tra không phải bài thi."""
    rows = []
    for pres, g in graded.dropna(subset=["date"]).groupby("pres"):
        g = g.sort_values("date")
        dates, weights = g["date"].to_numpy(), g["weight"].to_numpy()
        # Lượt mở môn có tổng trọng số = 0 thì tính theo số bài
        share = np.cumsum(weights) / weights.sum() if weights.sum() > 0 else np.arange(1, len(g) + 1) / len(g)
        rows.append({"pres": pres, "M0": 0, "M1": dates[np.argmax(share >= M1_WEIGHT_SHARE)], "M2": dates[-1]})
    return pd.DataFrame(rows).set_index("pres")


def course_fail_rates(base: pd.DataFrame) -> pd.Series:
    """Tỷ lệ trượt của môn ở các lượt mở TRƯỚC đó (không dùng kết quả của chính kỳ đang dự báo).

    Môn chưa có lịch sử: dùng tỷ lệ trượt chung của mọi môn ở các kỳ trước. Riêng kỳ đầu tiên (2013B)
    không có kỳ nào trước nên dùng tỷ lệ của chính nó; kỳ này chỉ nằm trong tập train nên không làm sai
    kết quả trên tập test.
    """
    stats = base.groupby(KEYS)[TARGET].agg(["sum", "count"]).reset_index()
    stats["order"] = stats["code_presentation"].map(TERM_ORDER.index)
    rates = {}
    for r in stats.itertuples(index=False):
        earlier = stats[stats["order"] < r.order]
        same_course = earlier[earlier["code_module"] == r.code_module]
        source = same_course if len(same_course) else earlier
        rate = source["sum"].sum() / source["count"].sum() if len(source) else r.sum / r.count
        rates[f"{r.code_module}_{r.code_presentation}"] = rate
    return pd.Series(rates)


def engagement(vle: pd.DataFrame, base: pd.DataFrame, cutoff: pd.Series) -> pd.DataFrame:
    """Mức tham gia học tập đến ngày cắt.

    engagement:        tổng lượt click đến ngày cắt, xếp hạng phần trăm trong cùng lượt mở môn
    recent_engagement: như trên nhưng chỉ tính RECENT_DAYS ngày gần nhất
    inactive_days:     số ngày từ lần hoạt động cuối đến ngày cắt (chưa hoạt động lần nào = tối đa)
    """
    vle_cutoff = vle["pres"].map(cutoff).astype(float)
    window = vle[vle["date"] <= vle_cutoff].assign(cutoff=vle_cutoff)
    recent = window["date"] > window["cutoff"] - RECENT_DAYS
    keys = ["pres", "id_student"]
    stats = pd.DataFrame({
        "clicks": window.groupby(keys, observed=True)["sum_click"].sum(),
        "recent_clicks": window[recent].groupby(keys, observed=True)["sum_click"].sum(),
        "last_active": window.groupby(keys, observed=True)["date"].max(),
    })

    out = base[keys].join(stats, on=keys)
    out[["clicks", "recent_clicks"]] = out[["clicks", "recent_clicks"]].fillna(0)
    by_pres = out.groupby("pres")
    return pd.DataFrame({
        "engagement": by_pres["clicks"].rank(pct=True),
        "recent_engagement": by_pres["recent_clicks"].rank(pct=True),
        "inactive_days": (out["pres"].map(cutoff) - out["last_active"]).clip(0, MAX_INACTIVE_DAYS)
        .fillna(MAX_INACTIVE_DAYS),
    }, index=base.index)


def process_features(base: pd.DataFrame, graded: pd.DataFrame, submissions: pd.DataFrame,
                     cutoff: pd.Series) -> pd.DataFrame:
    """Đặc trưng từ bài kiểm tra đã đến hạn tính đến ngày cắt.

    process_score:   điểm quá trình có trọng số (bài chưa nộp tính 0)
    submission_rate: tỷ lệ bài đã nộp
    score_trend:     điểm bài nộp gần nhất trừ bài nộp đầu tiên (0 nếu mới nộp dưới 2 bài)
    late_rate:       tỷ lệ bài nộp sau hạn trên số bài đã nộp
    """
    keys = ["pres", "id_student"]
    due = graded[graded["date"] <= graded["pres"].map(cutoff)].rename(columns={"date": "due_date"})
    expected = base[keys].merge(due[["pres", "id_assessment", "weight", "due_date"]], on="pres")
    expected = expected.merge(
        submissions[["id_assessment", "id_student", "date_submitted", "score"]],
        on=["id_assessment", "id_student"],
        how="left",
    )
    submitted = expected["date_submitted"].notna() & (expected["date_submitted"] <= expected["pres"].map(cutoff))
    expected["submitted"] = submitted.astype(float)
    expected["late"] = (submitted & (expected["date_submitted"] > expected["due_date"])).astype(float)
    expected["score01"] = np.where(submitted, expected["score"].fillna(0) / 100, 0.0)
    expected["weighted"] = expected["weight"] * expected["score01"]

    g = expected.groupby(keys).agg(
        weight=("weight", "sum"), weighted=("weighted", "sum"), mean_score=("score01", "mean"),
        submission_rate=("submitted", "mean"), n_submitted=("submitted", "sum"), n_late=("late", "sum"),
    )
    g["process_score"] = np.where(g["weight"] > 0, g["weighted"] / g["weight"].where(g["weight"] > 0, 1), g["mean_score"])
    g["late_rate"] = np.where(g["n_submitted"] > 0, g["n_late"] / g["n_submitted"].where(g["n_submitted"] > 0, 1), 0.0)

    done = expected[submitted].sort_values("due_date").groupby(keys)["score01"].agg(["first", "last", "count"])
    g = g.join(done)
    g["score_trend"] = np.where(g["count"] >= 2, g["last"] - g["first"], 0.0)
    return g[["process_score", "submission_rate", "score_trend", "late_rate"]].reset_index()


def build(data_dir: Path) -> dict[str, pd.DataFrame]:
    info = read(data_dir, "studentInfo")
    assessments = read(data_dir, "assessments")
    submissions = read(data_dir, "studentAssessment")
    vle = read(
        data_dir, "studentVle",
        usecols=["code_module", "code_presentation", "id_student", "date", "sum_click"],
        dtype={"code_module": "category", "code_presentation": "category", "id_student": "int32",
               "date": "int16", "sum_click": "int32"},
    )
    vle["pres"] = presentation_id(vle).astype("category")

    base = info[info["final_result"] != "Withdrawn"].copy()
    base[TARGET] = (base["final_result"] == "Fail").astype(int)
    base["pres"] = presentation_id(base)
    base["course_fail_rate"] = base["pres"].map(course_fail_rates(base))

    graded = assessments[assessments["assessment_type"] != "Exam"].copy()
    graded["pres"] = presentation_id(graded)
    cutoffs = checkpoint_days(graded)

    tables = {}
    for cp in CHECKPOINTS:
        cutoff = cutoffs[cp]
        df = base.copy()
        df = df.join(engagement(vle, df, cutoff))
        if cp != "M0":
            process_cols = ["process_score", "submission_rate", "score_trend", "late_rate"]
            df = df.merge(process_features(df, graded, submissions, cutoff), on=["pres", "id_student"], how="left")
            df[process_cols] = df[process_cols].fillna(0)
        df["cutoff_day"] = df["pres"].map(cutoff)
        df = df.rename(columns={
            "code_module": "course", "code_presentation": "term", "id_student": "student_id",
            "num_of_prev_attempts": "prev_attempts", "studied_credits": "credit_load",
        })
        df["source"] = "oulad"
        tables[cp] = df[META + ["cutoff_day"] + ALL_FEATURES[cp] + [TARGET]]
    return tables


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    if not (args.data / "studentInfo.csv").exists():
        raise SystemExit("Chưa có dữ liệu OULAD. Chạy trước: python ml/scripts/download_oulad.py")

    args.out.mkdir(parents=True, exist_ok=True)
    for cp, df in build(args.data).items():
        path = args.out / f"oulad_{cp}.csv"
        df.to_csv(path, index=False)
        print(f"{cp}: {len(df)} dòng, tỷ lệ trượt {df[TARGET].mean():.1%}, "
              f"ngày cắt trung bình {df['cutoff_day'].mean():.0f} -> {path.name}")
        print(df.groupby(TARGET)[ALL_FEATURES[cp]].mean().round(3).rename(index={0: "  đạt", 1: "  trượt"}).to_string())


if __name__ == "__main__":
    main()
