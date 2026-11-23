"""Tính đặc trưng M0/M1/M2 từ CSDL v2 (cấu trúc Trường Đại học Đại Nam) về lược đồ chung (ml/common_schema.py).

Dùng cho cả hai việc:
  - Huấn luyện: mọi lượt học (enrollment) của các học kỳ đã kết thúc, cắt đúng tại ngày của từng mốc.
  - AI Agent (backend/app/agent.py): các lượt học của học kỳ hiện tại, cắt tại thời điểm Agent chạy.

Mốc cắt của một lớp học phần:
  M0 = ngày bắt đầu học kỳ (chỉ có lịch sử học tập các kỳ trước)
  M1 = lúc giảng viên nhập xong điểm KT1 (khoảng tuần 6-8)
  M2 = lúc giảng viên nhập xong điểm KT2 (khoảng tuần 11-13), trước khi thi
Chỉ dùng đầu điểm có entered_at <= mốc và buổi điểm danh có ngày <= mốc, để mô hình không "nhìn thấy tương lai".

Nhãn fail = 1 nếu bị cấm thi hoặc TBCHP < 4.0; lượt học chưa kết thúc có nhãn rỗng.

Chạy:  python ml/adapters/dainam.py            (xuất ml/data/processed/dainam_M0.csv ... để xem / train)
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ML_DIR = Path(__file__).resolve().parents[1]
ROOT = ML_DIR.parent
sys.path.insert(0, str(ML_DIR))

from common_schema import BASE_FEATURES, CHECKPOINTS, PROCESS_FEATURES, TARGET, TREND_FEATURES  # noqa: E402

DEFAULT_OUT = ML_DIR / "data" / "processed"
CHECKPOINT_COMPONENT = {"M1": "KT1", "M2": "KT2"}
KT_CODES = ("KT1", "KT2", "KT3")
RECENT_SESSIONS = 2  # "2 tuần gần nhất": mỗi tuần một buổi

# Đặc trưng chỉ dữ liệu Đại Nam có (OULAD không có): lịch sử học tập và tình hình các môn khác cùng kỳ
DAINAM_FEATURES = {
    "M0": ["prior_gpa", "has_history", "prior_fail_count"],
    "M1": ["prior_gpa", "has_history", "prior_fail_count", "absence_ratio", "sem_kt_mean_others", "sem_att_rate"],
    "M2": ["prior_gpa", "has_history", "prior_fail_count", "absence_ratio", "sem_kt_mean_others", "sem_att_rate"],
}
FEATURE_SETS = {
    "core": {"M0": BASE_FEATURES, "M1": BASE_FEATURES + PROCESS_FEATURES, "M2": BASE_FEATURES + PROCESS_FEATURES},
    "extended": {"M0": BASE_FEATURES, "M1": BASE_FEATURES + PROCESS_FEATURES + TREND_FEATURES,
                 "M2": BASE_FEATURES + PROCESS_FEATURES + TREND_FEATURES},
}
FEATURE_SETS["dainam"] = {cp: FEATURE_SETS["extended"][cp] + DAINAM_FEATURES[cp] for cp in CHECKPOINTS}

META = ["enrollment_id", "student_id", "section_id", "semester_id", "semester_code", "course_code",
        "cutoff", "kt1", "kt2"]

# Tên tiếng Việt và cách hiện giá trị, dùng để giải thích lý do cảnh báo
FEATURE_INFO = {
    "prev_attempts": ("Số lần đã học môn này trước đây", "int"),
    "credit_load": ("Số tín chỉ đăng ký kỳ này", "int"),
    "course_fail_rate": ("Tỷ lệ trượt của môn ở các kỳ trước", "pct"),
    "engagement": ("Mức đi học so với lớp (xếp hạng)", "pct"),
    "process_score": ("Điểm kiểm tra đến hiện tại", "score10"),
    "submission_rate": ("Tỷ lệ bài kiểm tra có làm", "pct"),
    "score_trend": ("Điểm KT2 so với KT1", "trend10"),
    "recent_engagement": ("Đi học 2 buổi gần nhất so với lớp", "pct"),
    "inactive_days": ("Số buổi vắng liên tiếp gần nhất", "int"),
    "late_rate": ("Tỷ lệ buổi đi muộn", "pct"),
    "prior_gpa": ("Điểm TBC tích lũy các kỳ trước", "gpa"),
    "has_history": ("Đã có kết quả học kỳ trước", "bool"),
    "prior_fail_count": ("Số môn đang nợ (trượt chưa qua)", "int"),
    "absence_ratio": ("Số buổi vắng / tổng số buổi", "pct"),
    "sem_kt_mean_others": ("Điểm kiểm tra các môn khác cùng kỳ", "score"),
    "sem_att_rate": ("Tỷ lệ đi học tất cả các môn kỳ này", "pct"),
}


def format_value(feature: str, value) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "chưa có"
    kind = FEATURE_INFO.get(feature, ("", "num"))[1]
    if kind == "pct":
        return f"{value * 100:.0f}%"
    if kind == "score10":
        return f"{value * 10:.1f}/10"
    if kind == "trend10":
        return f"{value * 10:+.1f} điểm"
    if kind == "score":
        return f"{value:.1f}/10"
    if kind == "gpa":
        return f"{value:.2f}/4"
    if kind == "bool":
        return "có" if value else "chưa"
    if kind == "int":
        return f"{value:.0f}"
    return f"{value:.2f}"


# ------------------------------------------------------------------ đọc CSDL
def load_tables(engine) -> dict[str, pd.DataFrame]:
    q = {
        "semesters": "SELECT id AS semester_id, code AS semester_code, start_date, end_date, is_current FROM semesters",
        "sections": """SELECT cs.id AS section_id, cs.semester_id, cs.total_sessions, c.code AS course_code,
                              c.credits FROM course_sections cs JOIN courses c ON c.id = cs.course_id""",
        "enrollments": """SELECT id AS enrollment_id, section_id, student_id, attempt_no, status, final_score,
                                 grade_point, passed, completed_at FROM enrollments""",
        "grades": """SELECT g.enrollment_id, cc.code AS component, cc.weight, g.score, g.entered_at
                     FROM grades g JOIN course_components cc ON cc.id = g.component_id""",
        "attendance": """SELECT a.enrollment_id, s.session_no, s.session_date, a.status
                         FROM attendance a JOIN class_sessions s ON s.id = a.session_id""",
        "components": """SELECT cs.id AS section_id, cc.code AS component, cc.weight, cc.is_exam
                         FROM course_sections cs JOIN course_components cc ON cc.course_id = cs.course_id""",
        "settings": "SELECT `key`, `value` FROM settings",
    }
    with engine.connect() as conn:
        t = {name: pd.read_sql(sql, conn) for name, sql in q.items()}
    t["grades"]["entered_at"] = pd.to_datetime(t["grades"]["entered_at"])
    t["attendance"]["session_date"] = pd.to_datetime(t["attendance"]["session_date"])
    t["enrollments"]["completed_at"] = pd.to_datetime(t["enrollments"]["completed_at"])
    for col in ("start_date", "end_date"):
        t["semesters"][col] = pd.to_datetime(t["semesters"][col])
    for col in ("final_score", "grade_point"):
        t["enrollments"][col] = t["enrollments"][col].astype(float)
    t["grades"]["score"] = t["grades"]["score"].astype(float)
    t["grades"]["weight"] = t["grades"]["weight"].astype(float)
    t["components"]["weight"] = t["components"]["weight"].astype(float)
    # Ghép sẵn thông tin lớp học phần + học kỳ vào từng lượt học
    t["enr"] = (t["enrollments"].merge(t["sections"], on="section_id")
                .merge(t["semesters"][["semester_id", "semester_code", "start_date"]], on="semester_id"))
    t["enr"]["fail"] = np.where(t["enr"]["status"].eq("banned_exam"), 1.0,
                                np.where(t["enr"]["passed"].isna(), np.nan, 1.0 - t["enr"]["passed"].fillna(0)))
    return t


def setting(t: dict, key: str, default: float) -> float:
    row = t["settings"].loc[t["settings"]["key"] == key, "value"]
    try:
        return float(row.iloc[0])
    except (IndexError, ValueError):
        return default


def checkpoint_cutoffs(t: dict) -> pd.DataFrame:
    """Thời điểm cắt M0/M1/M2 của từng lớp học phần (NaT nếu chưa tới)."""
    g = t["grades"].merge(t["enrollments"][["enrollment_id", "section_id"]], on="enrollment_id")
    out = t["sections"][["section_id", "semester_id"]].merge(
        t["semesters"][["semester_id", "start_date"]], on="semester_id")
    out = out.rename(columns={"start_date": "M0"}).set_index("section_id")
    for cp, comp in CHECKPOINT_COMPONENT.items():
        # Cả lớp được nhập cùng đợt; lấy lúc nhập muộn nhất để chắc chắn đã đủ điểm cả lớp
        out[cp] = g[g["component"] == comp].groupby("section_id")["entered_at"].max()
    return out[["M0", "M1", "M2"]]


# ------------------------------------------------------------------ đặc trưng
def _history(t: dict, rows: pd.DataFrame) -> pd.DataFrame:
    """Lịch sử học tập trước ngày bắt đầu học kỳ của từng lượt học."""
    done = t["enr"].dropna(subset=["completed_at"])
    out = []
    for (student_id, start), grp in rows.groupby(["student_id", "start_date"]):
        past = done[(done["student_id"] == student_id) & (done["completed_at"] < start)]
        if past.empty:
            gpa, fails = np.nan, 0
        else:
            best = past.sort_values("final_score").groupby("course_code").tail(1)  # lần học tốt nhất mỗi môn
            passed = best[best["passed"] == 1]
            gpa = (passed["grade_point"] * passed["credits"]).sum() / passed["credits"].sum() \
                if len(passed) else 0.0
            fails = int((best["passed"] != 1).sum())
        out.append({"student_id": student_id, "start_date": start, "prior_gpa": gpa,
                    "has_history": int(not past.empty), "prior_fail_count": fails})
    return rows[["enrollment_id", "student_id", "start_date"]].merge(
        pd.DataFrame(out), on=["student_id", "start_date"], how="left").set_index("enrollment_id")


def _course_fail_rate(t: dict, rows: pd.DataFrame) -> pd.Series:
    done = t["enr"].dropna(subset=["fail", "completed_at"])
    rates = {}
    for (course, start), _ in rows.groupby(["course_code", "start_date"]):
        before = done[done["completed_at"] < start]
        past = before[before["course_code"] == course]
        # Môn chưa từng mở trước đây: lấy tỷ lệ trượt chung của mọi môn
        rates[(course, start)] = past["fail"].mean() if len(past) else (before["fail"].mean() if len(before)
                                                                        else np.nan)
    return rows.apply(lambda r: rates[(r["course_code"], r["start_date"])], axis=1).set_axis(rows["enrollment_id"])


def _progress_features(cp: str, df: pd.DataFrame, att: pd.DataFrame, grades: pd.DataFrame) -> pd.DataFrame:
    """Điểm danh và điểm kiểm tra tới ngày cắt của từng lượt học, tính cho cả bảng một lần (merge + groupby).

    df: các lượt học đã có ngày cắt (index enrollment_id; cột student_id, semester_id, cutoff, total_sessions).
    att, grades: điểm danh và điểm KT của mọi môn trong kỳ của các sinh viên này (đã kèm student_id, semester_id).
    """
    out = pd.DataFrame(index=df.index)
    if df.empty:
        return out
    tg = df[["student_id", "semester_id", "cutoff", "total_sessions"]].rename_axis("enrollment_id").reset_index()

    # Điểm danh của chính môn này, tới mốc, theo thứ tự buổi học
    a = att.merge(tg[["enrollment_id", "cutoff"]], on="enrollment_id")
    a = a[a["session_date"] <= a["cutoff"]].sort_values(["enrollment_id", "session_no"])
    present = a["status"].isin(["present", "late"])
    by_enr = a["enrollment_id"]
    out["att_rate"] = present.groupby(by_enr).mean()
    recent = a.groupby("enrollment_id").tail(RECENT_SESSIONS)
    out["recent_att"] = recent["status"].isin(["present", "late"]).groupby(recent["enrollment_id"]).mean()
    out["absence_ratio"] = (~present).groupby(by_enr).sum().reindex(df.index, fill_value=0) / df["total_sessions"]
    out["late_rate"] = a["status"].eq("late").groupby(by_enr).mean().reindex(df.index).fillna(0.0)
    # Số buổi vắng liên tiếp tính ngược từ buổi gần nhất
    absent_rev = (~present).iloc[::-1].astype(int)
    streak = absent_rev.groupby(by_enr.iloc[::-1]).cumprod().groupby(by_enr.iloc[::-1]).sum()
    out["inactive_days"] = streak.reindex(df.index, fill_value=0).astype(int)

    # Điểm kiểm tra của chính môn này, tới mốc
    g = grades.merge(tg[["enrollment_id", "cutoff"]], on="enrollment_id")
    g = g[g["entered_at"] <= g["cutoff"]]
    kt = g.groupby(["enrollment_id", "component"])["score"].last().unstack()
    out["kt1"] = kt["KT1"] if "KT1" in kt else np.nan
    out["kt2"] = kt["KT2"] if "KT2" in kt else np.nan
    weighted = (g["score"] * g["weight"]).groupby(g["enrollment_id"]).sum()
    out["process_score"] = weighted / (10 * g["weight"].groupby(g["enrollment_id"]).sum())
    out["submission_rate"] = (g["score"] > 0).groupby(g["enrollment_id"]).mean()
    out["score_trend"] = (np.where(out["kt2"].notna(), (out["kt2"] - out["kt1"]) / 10, 0.0) if cp == "M2" else 0.0)

    # Các môn khác cùng kỳ của sinh viên: điểm KT trung bình, và tỷ lệ đi học mọi môn (kể cả môn này)
    others = tg.merge(grades[["enrollment_id", "student_id", "semester_id", "entered_at", "score"]]
                      .rename(columns={"enrollment_id": "other_id"}), on=["student_id", "semester_id"])
    others = others[(others["other_id"] != others["enrollment_id"]) & (others["entered_at"] <= others["cutoff"])]
    out["sem_kt_mean_others"] = others.groupby("enrollment_id")["score"].mean()
    sem_att = tg.merge(att[["student_id", "semester_id", "session_date", "status"]], on=["student_id", "semester_id"])
    sem_att = sem_att[sem_att["session_date"] <= sem_att["cutoff"]]
    out["sem_att_rate"] = sem_att["status"].isin(["present", "late"]).groupby(sem_att["enrollment_id"]).mean()
    return out


def build_features(t: dict, cp: str, rows: pd.DataFrame, cutoff: pd.Series) -> pd.DataFrame:
    """Đặc trưng tại mốc `cp` cho các lượt học `rows` (dòng của t["enr"]), cắt tại `cutoff` (theo enrollment_id)."""
    rows = rows.copy()
    rows["cutoff"] = rows["enrollment_id"].map(cutoff)
    ban_ratio = setting(t, "absence_ban_ratio", 0.2)
    df = rows.set_index("enrollment_id")[["student_id", "section_id", "semester_id", "semester_code",
                                          "course_code", "cutoff", "attempt_no", "credits", "total_sessions",
                                          "fail", "start_date"]].copy()

    hist = _history(t, rows)
    df[["prior_gpa", "has_history", "prior_fail_count"]] = hist[["prior_gpa", "has_history", "prior_fail_count"]]
    df["prev_attempts"] = df["attempt_no"] - 1
    df["course_fail_rate"] = _course_fail_rate(t, rows)
    load = t["enr"].groupby(["student_id", "semester_id"])["credits"].sum()
    df["credit_load"] = [load.get((s, m), 0) for s, m in zip(df["student_id"], df["semester_id"])]

    # Điểm danh tới mốc (của mọi môn trong kỳ của các sinh viên này, để tính cả tình hình các môn khác)
    sem_enr = t["enr"][t["enr"]["semester_id"].isin(df["semester_id"].unique())
                       & t["enr"]["student_id"].isin(df["student_id"].unique())]
    att = t["attendance"].merge(sem_enr[["enrollment_id", "student_id", "semester_id"]], on="enrollment_id")
    grades = t["grades"].merge(sem_enr[["enrollment_id", "student_id", "semester_id"]], on="enrollment_id")
    grades = grades[grades["component"].isin(KT_CODES)]

    # Đầu kỳ (M0) hoặc lớp chưa tới mốc: chưa có điểm, điểm danh -> giá trị mặc định
    has_cut = df["cutoff"].notna() if cp != "M0" else pd.Series(False, index=df.index)
    defaults = pd.DataFrame(
        dict(engagement=0.5, process_score=np.nan, submission_rate=np.nan, score_trend=0.0, recent_engagement=0.5,
             inactive_days=0, late_rate=0.0, absence_ratio=0.0, sem_kt_mean_others=np.nan, sem_att_rate=np.nan,
             att_rate=np.nan, kt1=np.nan, kt2=np.nan),
        index=df.index[~has_cut])
    feats = pd.concat([defaults, _progress_features(cp, df[has_cut], att, grades)])
    feats.index.name = "enrollment_id"
    df = df.join(feats)
    if cp != "M0":
        # Xếp hạng phần trăm trong lớp học phần: 1 = đi học đều nhất lớp
        df["engagement"] = df.groupby("section_id")["att_rate"].rank(pct=True).fillna(0.5)
        df["recent_engagement"] = df.groupby("section_id")["recent_att"].rank(pct=True).fillna(0.5)

    # Quy tắc đơn giản mà giảng viên tự nhìn bảng điểm cũng làm được (baseline để so với AI)
    if cp == "M0":
        # Đầu kỳ: đang học lại môn này, hoặc đang nợ từ 2 môn trở lên
        df["rule_flag"] = ((df["prev_attempts"] > 0) | (df["prior_fail_count"] >= 2)).astype(int)
    else:
        df["rule_flag"] = ((df["absence_ratio"] >= ban_ratio * 0.75) | (df["process_score"] < 0.4)).astype(int)
    df[TARGET] = df["fail"]
    df["checkpoint"] = cp
    return df.reset_index()


def training_frames(t: dict) -> dict[str, pd.DataFrame]:
    """Đặc trưng tại đúng ngày cắt của từng mốc, cho mọi lượt học đã có kết quả."""
    cut = checkpoint_cutoffs(t)
    done = t["enr"].dropna(subset=["fail"])
    frames = {}
    for cp in CHECKPOINTS:
        rows = done[done["section_id"].map(cut[cp]).notna()]
        cutoff = rows.set_index("enrollment_id")["section_id"].map(cut[cp])
        frames[cp] = build_features(t, cp, rows, cutoff)
    return frames


def current_checkpoint(cut_row: pd.Series, as_of: datetime) -> str:
    reached = [cp for cp in CHECKPOINTS if pd.notna(cut_row[cp]) and cut_row[cp] <= as_of]
    return reached[-1] if reached else "M0"


def explain(pipeline, X: pd.DataFrame, reference: dict[str, float], top: int = 3) -> list[list[dict]]:
    """Lý do của từng dự báo: thay lần lượt từng đặc trưng bằng giá trị "thường gặp" (trung vị lúc train);
    đặc trưng nào làm xác suất trượt giảm nhiều nhất khi được "bình thường hóa" thì đó là lý do chính.
    Cách này (occlusion) dùng được cho mọi mô hình, không cần thư viện SHAP.
    """
    base = pipeline.predict_proba(X)[:, 1]
    features = list(X.columns)
    swapped = pd.concat([X.assign(**{f: reference[f]}) for f in features], ignore_index=True)
    proba = pipeline.predict_proba(swapped)[:, 1].reshape(len(features), len(X))
    result = []
    for i in range(len(X)):
        deltas = base[i] - proba[:, i]  # > 0: đặc trưng này đang đẩy nguy cơ lên
        order = np.argsort(-deltas)[:top]
        result.append([{
            "feature": features[j], "label": FEATURE_INFO.get(features[j], (features[j],))[0],
            "value": format_value(features[j], X.iloc[i, j]),
            "typical": format_value(features[j], reference[features[j]]),
            "impact": round(float(deltas[j]), 3),
        } for j in order if deltas[j] > 0.01])
    return result


def engine_v2():
    sys.path.insert(0, str(ROOT / "backend"))
    from sqlalchemy import create_engine

    from app.config import settings  # noqa: E402
    return create_engine(settings.database_url_v2)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    t = load_tables(engine_v2())
    args.out.mkdir(parents=True, exist_ok=True)
    for cp, df in training_frames(t).items():
        path = args.out / f"dainam_{cp}.csv"
        df.to_csv(path, index=False)
        by_sem = df.groupby("semester_code")[TARGET].agg(["size", "mean"]).round(3)
        print(f"{cp}: {len(df)} lượt học -> {path.name}; tỷ lệ trượt theo kỳ:\n{by_sem.to_string()}\n")


if __name__ == "__main__":
    main()
