"""Train mô hình dự báo trượt môn trên CSDL v2 (cấu trúc Đại Nam) cho AI Agent, theo 3 mốc M0/M1/M2.

Cùng quy trình với ml/train_checkpoints.py (OULAD):
  1. Chia theo thời gian: train = các kỳ cũ, validation = kỳ áp chót, test = kỳ gần nhất đã kết thúc.
  2. Chọn mô hình và bộ đặc trưng (core / extended / dainam) theo PR-AUC trên validation.
  3. Chọn ngưỡng cảnh báo trên validation để AI có precision không thấp hơn quy tắc (cảnh báo không "ồn" hơn).
  4. "Chạy lại" kỳ test: train lại trên train + validation, dự báo kỳ test như thể đang ở mốc đó, so với
     kết quả thật và với quy tắc. Đây là số liệu trang AI Agent hiển thị.
  5. Train lần cuối trên mọi kỳ đã kết thúc, lưu mô hình cho Agent dùng ở học kỳ hiện tại.

LƯU Ý khi báo cáo: dữ liệu demo do database/seed_demo_v2.py sinh ra, nên số liệu ở đây chỉ chứng minh quy trình
chạy đúng. Bằng chứng về độ chính xác là kết quả trên dữ liệu thật công khai OULAD (ml/train_checkpoints.py).

Chạy:  python ml/train_dainam.py
Kết quả: ml/models/dainam/model_M0.joblib ..., ml/models/dainam/results.json
"""

import json
import sys
import time
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_recall_curve
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

ML_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ML_DIR))
sys.path.insert(0, str(ML_DIR / "adapters"))

from common_schema import CHECKPOINT_LABELS, CHECKPOINTS, TARGET  # noqa: E402
from dainam import FEATURE_SETS, engine_v2, load_tables, training_frames  # noqa: E402
from train_checkpoints import matched_thresholds, scores  # noqa: E402

OUT_DIR = ML_DIR / "models" / "dainam"
SEED = 42
DAINAM_LABELS = {"M0": "Đầu kỳ", "M1": "Sau khi có điểm KT1", "M2": "Sau khi có điểm KT2, trước khi thi"}
HIGH_PRECISION = 0.75  # mức "nguy cơ cao": trên validation, cứ 4 SV bị xếp mức này thì ít nhất 3 SV trượt thật


def build_models() -> dict[str, Pipeline]:
    impute = ("impute", SimpleImputer(strategy="median"))
    return {
        "logistic_regression": Pipeline([impute, ("scaler", StandardScaler()),
                                         ("model", LogisticRegression(class_weight="balanced", max_iter=2000))]),
        "random_forest": Pipeline([impute, ("model", RandomForestClassifier(
            n_estimators=300, class_weight="balanced", min_samples_leaf=5, random_state=SEED, n_jobs=-1))]),
        "gradient_boosting": Pipeline([impute, ("model", HistGradientBoostingClassifier(
            class_weight="balanced", max_iter=200, learning_rate=0.05, random_state=SEED))]),
    }


def high_threshold(y, proba, alert: float) -> float:
    precision, _, thresholds = precision_recall_curve(y, proba)
    ok = np.where(precision[:-1] >= HIGH_PRECISION)[0]
    return float(max(thresholds[ok[0]], alert)) if len(ok) else float(min(alert + 0.2, 0.95))


def weeks_before_exam(df: pd.DataFrame, t: dict) -> float:
    """Số tuần từ lúc cảnh báo (ngày cắt của mốc) tới kỳ thi; ngày thi = ngày có kết quả trừ 10 ngày."""
    done = t["enr"].set_index("enrollment_id")["completed_at"]
    gap = (df["enrollment_id"].map(done) - pd.Timedelta(days=10) - pd.to_datetime(df["cutoff"])).dt.days / 7
    return round(float(gap.median()), 1)


def run_checkpoint(cp: str, df: pd.DataFrame, terms: list[str], t: dict) -> dict:
    test_term, val_term = terms[-1], terms[-2]
    train, val, test = (df[df["semester_code"].isin(terms[:-2])], df[df["semester_code"] == val_term],
                        df[df["semester_code"] == test_term])

    # 1-2. Chọn mô hình + bộ đặc trưng trên validation
    candidates = []
    for set_name, sets in FEATURE_SETS.items():
        features = sets[cp]
        for name, pipe in build_models().items():
            pipe.fit(train[features], train[TARGET])
            proba = pipe.predict_proba(val[features])[:, 1]
            s = scores(val[TARGET], (proba >= 0.5).astype(int), proba)
            candidates.append({"feature_set": set_name, "model": name, "val": s, "proba": proba, "pipe": pipe})
    best = max(candidates, key=lambda c: c["val"]["pr_auc"])
    features = FEATURE_SETS[best["feature_set"]][cp]

    # 3. Ngưỡng cảnh báo: precision không thấp hơn quy tắc; nếu không đạt được thì lấy ngưỡng cùng recall
    rule_val = scores(val[TARGET], val["rule_flag"])
    thr = matched_thresholds(val[TARGET], best["proba"], rule_val["precision"], rule_val["recall"])
    alert = thr["same_precision"] or thr["same_recall"] or 0.5
    high = high_threshold(val[TARGET], best["proba"], alert)

    # 4. Chạy lại kỳ test như thể đang ở mốc cp
    pipe = build_models()[best["model"]].fit(pd.concat([train, val])[features], pd.concat([train, val])[TARGET])
    proba = pipe.predict_proba(test[features])[:, 1]
    ai = (proba >= alert).astype(int)
    rule = test["rule_flag"].to_numpy()
    y = test[TARGET].to_numpy().astype(int)
    ai_scores, rule_scores = scores(y, ai, proba), scores(y, rule)
    backtest = {
        "semester": test_term, "n": int(len(test)), "n_failed": int(y.sum()),
        "rule": rule_scores, "ai": ai_scores,
        "ai_only_caught": int(((ai == 1) & (rule == 0) & (y == 1)).sum()),  # quy tắc bỏ sót, AI bắt được
        "rule_only_caught": int(((ai == 0) & (rule == 1) & (y == 1)).sum()),
        "both_caught": int(((ai == 1) & (rule == 1) & (y == 1)).sum()),
        "missed_by_both": int(((ai == 0) & (rule == 0) & (y == 1)).sum()),
        "agent_caught": int((((ai == 1) | (rule == 1)) & (y == 1)).sum()),  # Agent = luật + AI
        "agent_flagged": int(((ai == 1) | (rule == 1)).sum()),
        "weeks_before_exam": weeks_before_exam(test, t) if cp != "M0" else None,
        "rows": [{"enrollment_id": int(e), "proba": round(float(p), 4), "ai": int(a), "rule": int(r), "fail": int(f)}
                 for e, p, a, r, f in zip(test["enrollment_id"], proba, ai, rule, y)],
    }

    # 5. Mô hình cuối cho Agent: train trên mọi kỳ đã kết thúc
    final = build_models()[best["model"]].fit(df[features], df[TARGET])
    reference = {f: float(df[f].median()) if df[f].notna().any() else 0.0 for f in features}
    trained_at = datetime.now().isoformat(timespec="seconds")
    joblib.dump({"pipeline": final, "features": features, "feature_set": best["feature_set"],
                 "model_name": best["model"], "checkpoint": cp, "thresholds": {"alert": alert, "high": high},
                 "reference": reference, "trained_at": trained_at, "train_terms": terms},
                OUT_DIR / f"model_{cp}.joblib")

    return {
        "label": DAINAM_LABELS[cp], "oulad_label": CHECKPOINT_LABELS[cp],
        "split": {"train": terms[:-2], "val": val_term, "test": test_term},
        "chosen": {"model": best["model"], "feature_set": best["feature_set"], "features": features},
        "thresholds": {"alert": round(alert, 4), "high": round(high, 4), **{k: v and round(v, 4) for k, v in thr.items()}},
        "candidates": [{"feature_set": c["feature_set"], "model": c["model"], "val_pr_auc": c["val"]["pr_auc"],
                        "val_roc_auc": c["val"]["roc_auc"]} for c in candidates],
        "rule_val": rule_val, "backtest": backtest, "trained_at": trained_at,
    }


def main() -> None:
    start = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    t = load_tables(engine_v2())
    frames = training_frames(t)
    terms = sorted(frames["M0"]["semester_code"].unique())
    if len(terms) < 3:
        sys.exit("Cần ít nhất 3 học kỳ đã kết thúc (train / validation / test).")
    print(f"Đặc trưng xong sau {time.time() - start:.0f} giây. Học kỳ: {terms}")

    results = {"trained_at": datetime.now().isoformat(timespec="seconds"), "data": "demo (database/seed_demo_v2.py)",
               "checkpoints": {}}
    for cp in CHECKPOINTS:
        r = run_checkpoint(cp, frames[cp], terms, t)
        results["checkpoints"][cp] = r
        b = r["backtest"]
        print(f"\n[{cp}] {r['label']}: {r['chosen']['model']} / {r['chosen']['feature_set']}, "
              f"val PR-AUC {max(c['val_pr_auc'] for c in r['candidates']):.3f}, "
              f"ngưỡng cảnh báo {r['thresholds']['alert']:.2f}, cao {r['thresholds']['high']:.2f}")
        print(f"  Chạy lại kỳ {b['semester']}: {b['n_failed']}/{b['n']} lượt trượt thật")
        print(f"  Quy tắc: bắt {b['rule']['caught']}, báo nhầm {b['rule']['false_alarms']}")
        print(f"  AI     : bắt {b['ai']['caught']}, báo nhầm {b['ai']['false_alarms']}, PR-AUC {b['ai']['pr_auc']:.3f}")
        print(f"  AI bắt được mà quy tắc bỏ sót: {b['ai_only_caught']}; Agent (luật + AI) bắt {b['agent_caught']}"
              + (f"; trước khi thi khoảng {b['weeks_before_exam']} tuần" if b["weeks_before_exam"] else ""))
    (OUT_DIR / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nĐã lưu vào {OUT_DIR} sau {time.time() - start:.0f} giây")


if __name__ == "__main__":
    main()
