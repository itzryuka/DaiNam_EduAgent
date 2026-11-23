"""So sánh mô hình dự báo trượt môn tại các mốc M0, M1, M2 (lược đồ đặc trưng chung).

Chia dữ liệu theo THỜI GIAN, giống cách hệ thống được dùng thật: học từ các kỳ trước, dự báo kỳ sau.
  - test       = kỳ mới nhất (--test-term), chỉ dùng để báo cáo kết quả cuối
  - validation = kỳ ngay trước đó (--val-term), dùng để CHỌN mô hình (theo PR-AUC), chọn bộ đặc trưng
                 và chọn ngưỡng cảnh báo
  - train      = các kỳ còn lại; sau khi chọn xong, train lại trên train + validation

Mỗi mốc so 2 bộ đặc trưng (common_schema.FEATURE_SETS): "core" và "extended" (thêm xu hướng gần đây).

So với quy tắc đơn giản (baseline) một cách CÔNG BẰNG: mô hình và quy tắc thường đứng ở hai điểm khác
nhau (một bên bắt nhiều hơn nhưng báo nhầm nhiều hơn), nên so F1 ở ngưỡng 0.5 dễ gây hiểu lầm.
Ta chọn ngưỡng của mô hình trên kỳ validation sao cho:
  (a) độ chính xác (precision) bằng quy tắc -> so xem mô hình bắt thêm được bao nhiêu SV trượt
  (b) độ phủ (recall) bằng quy tắc          -> so xem mô hình bớt được bao nhiêu cảnh báo nhầm
rồi áp ngưỡng đó lên kỳ test. Kỳ test không tham gia vào bất kỳ lựa chọn nào.

Chạy:  python ml/adapters/oulad.py         (tạo dữ liệu đặc trưng, làm một lần)
       python ml/train_checkpoints.py
Kết quả: ml/models/oulad/M0.joblib, M1.joblib, M2.joblib và ml/models/oulad/results.json
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC
from sklearn.tree import DecisionTreeClassifier

ML_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ML_DIR))

from common_schema import CHECKPOINT_LABELS, CHECKPOINTS, FEATURE_SETS, TARGET  # noqa: E402

SEED = 42


def build_models(include_svm: bool = True) -> dict[str, Pipeline]:
    # class_weight="balanced": lớp "trượt" là thiểu số, tăng trọng số để mô hình không bỏ qua nó
    classifiers = {
        "logistic_regression": LogisticRegression(class_weight="balanced", max_iter=1000),
        "decision_tree": DecisionTreeClassifier(class_weight="balanced", max_depth=6, random_state=SEED),
        "random_forest": RandomForestClassifier(
            n_estimators=300, class_weight="balanced", min_samples_leaf=5, random_state=SEED, n_jobs=-1
        ),
        "gradient_boosting": HistGradientBoostingClassifier(class_weight="balanced", random_state=SEED),
    }
    if include_svm:
        # SVC không tự ra xác suất; CalibratedClassifierCV hiệu chỉnh điểm số thành xác suất 0..1
        classifiers["svm"] = CalibratedClassifierCV(SVC(class_weight="balanced", random_state=SEED), cv=3,
                                                    ensemble=False)
    return {name: Pipeline([("scaler", StandardScaler()), ("model", clf)]) for name, clf in classifiers.items()}


def baseline_predict(cp: str, X: pd.DataFrame) -> np.ndarray:
    """Quy tắc đơn giản mà giảng viên có thể tự áp dụng, không cần AI."""
    if cp == "M0":
        # Đầu kỳ: từng học lại môn này, hoặc gần như không vào hệ thống học tập trước khi học
        return ((X["prev_attempts"] > 0) | (X["engagement"] < 0.25)).astype(int).to_numpy()
    # Đã có điểm: điểm quá trình dưới 40% (ngưỡng đạt của OULAD) hoặc nộp chưa được nửa số bài
    return ((X["process_score"] < 0.4) | (X["submission_rate"] < 0.5)).astype(int).to_numpy()


def scores(y_true, y_pred, y_proba=None) -> dict[str, float]:
    y_true, y_pred = np.asarray(y_true), np.asarray(y_pred)
    result = {
        "accuracy": accuracy_score(y_true, y_pred),
        "precision": precision_score(y_true, y_pred, zero_division=0),
        "recall": recall_score(y_true, y_pred, zero_division=0),
        "f1": f1_score(y_true, y_pred, zero_division=0),
    }
    if y_proba is not None:
        result["pr_auc"] = average_precision_score(y_true, y_proba)
        result["roc_auc"] = roc_auc_score(y_true, y_proba)
    result = {k: round(float(v), 4) for k, v in result.items()}
    # Số đếm cụ thể, dễ giải thích hơn tỷ lệ: bắt đúng bao nhiêu SV trượt, cảnh báo nhầm bao nhiêu SV đạt
    result["caught"] = int(((y_pred == 1) & (y_true == 1)).sum())
    result["false_alarms"] = int(((y_pred == 1) & (y_true == 0)).sum())
    result["flagged"] = int((y_pred == 1).sum())
    return result


def matched_thresholds(y_val, proba_val, target_precision: float, target_recall: float) -> dict[str, float | None]:
    """Ngưỡng trên validation để mô hình đứng ngang quy tắc về precision hoặc về recall."""
    precision, recall, thresholds = precision_recall_curve(y_val, proba_val)
    precision, recall = precision[:-1], recall[:-1]  # phần tử cuối không ứng với ngưỡng nào
    # (a) Ngưỡng nhỏ nhất (bắt được nhiều nhất) mà precision vẫn >= quy tắc
    ok_p = np.where(precision >= target_precision)[0]
    # (b) Ngưỡng lớn nhất (ít cảnh báo nhất) mà recall vẫn >= quy tắc
    ok_r = np.where(recall >= target_recall)[0]
    return {
        "same_precision": float(thresholds[ok_p[0]]) if len(ok_p) else None,
        "same_recall": float(thresholds[ok_r[-1]]) if len(ok_r) else None,
    }


def fair_comparison(cp: str, features: list[str], val: pd.DataFrame, test: pd.DataFrame,
                    proba_val: np.ndarray, proba_test: np.ndarray) -> dict:
    base_val = scores(val[TARGET], baseline_predict(cp, val[features]))
    base_test = scores(test[TARGET], baseline_predict(cp, test[features]))
    thr = matched_thresholds(val[TARGET], proba_val, base_val["precision"], base_val["recall"])

    result = {"baseline_val": base_val, "baseline_test": base_test, "thresholds": thr}
    for key, t in thr.items():
        if t is None:
            result[key] = None
            continue
        model_test = scores(test[TARGET], (proba_test >= t).astype(int))
        result[key] = {
            "threshold": round(t, 4),
            "test": model_test,
            "extra_caught": model_test["caught"] - base_test["caught"],
            "fewer_false_alarms": base_test["false_alarms"] - model_test["false_alarms"],
            # Ngưỡng chọn trên kỳ validation nên sang kỳ test không còn khớp đúng; chỉ khẳng định mô hình
            # hơn quy tắc khi vừa bắt không ít hơn vừa báo nhầm không nhiều hơn
            "beats_baseline": bool(model_test["caught"] >= base_test["caught"]
                                   and model_test["false_alarms"] <= base_test["false_alarms"]),
        }
    return result


def run_feature_set(cp: str, features: list[str], train_all: pd.DataFrame, inner: pd.DataFrame,
                    val: pd.DataFrame, test: pd.DataFrame, include_svm: bool) -> tuple[dict, Pipeline]:
    models, val_probas, test_probas = {}, {}, {}
    for name, pipeline in build_models(include_svm).items():
        start = time.perf_counter()
        pipeline.fit(inner[features], inner[TARGET])
        val_probas[name] = pipeline.predict_proba(val[features])[:, 1]
        val_pr_auc = average_precision_score(val[TARGET], val_probas[name])

        pipeline.fit(train_all[features], train_all[TARGET])
        test_probas[name] = pipeline.predict_proba(test[features])[:, 1]
        models[name] = {
            "val_pr_auc": round(float(val_pr_auc), 4),
            "test": scores(test[TARGET], (test_probas[name] >= 0.5).astype(int), test_probas[name]),
            "fit_seconds": round(time.perf_counter() - start, 1),
            "_pipeline": pipeline,
        }

    best = max(models, key=lambda n: models[n]["val_pr_auc"])
    best_pipeline = models[best]["_pipeline"]
    importance = permutation_importance(
        best_pipeline, test[features], test[TARGET], scoring="average_precision", n_repeats=5, random_state=SEED
    )
    result = {
        "features": features,
        "models": {n: {k: v for k, v in m.items() if k != "_pipeline"} for n, m in models.items()},
        "best_model": best,
        "fair_comparison": fair_comparison(cp, features, val, test, val_probas[best], test_probas[best]),
        "feature_importance": dict(
            sorted(zip(features, importance.importances_mean.round(4).tolist()), key=lambda kv: kv[1], reverse=True)
        ),
    }
    return result, best_pipeline


def run_checkpoint(cp: str, df: pd.DataFrame, val_term: str, test_term: str,
                   include_svm: bool) -> tuple[dict, Pipeline]:
    train_all = df[df["term"] != test_term]
    test = df[df["term"] == test_term]
    inner, val = train_all[train_all["term"] != val_term], train_all[train_all["term"] == val_term]
    if test.empty or val.empty:
        raise SystemExit(f"Không có dữ liệu cho kỳ test {test_term} hoặc kỳ validation {val_term}")

    feature_sets, pipelines, seen = {}, {}, []
    for set_name, by_cp in FEATURE_SETS.items():
        features = by_cp[cp]
        if features in seen:  # M0: hai bộ giống hệt nhau, không train lại
            continue
        missing = [f for f in features if f not in df.columns]
        if missing:
            print(f"  [{cp}] bỏ qua bộ {set_name}: thiếu cột {missing}")
            continue
        seen.append(features)
        feature_sets[set_name], pipelines[set_name] = run_feature_set(
            cp, features, train_all, inner, val, test, include_svm
        )

    # Bộ đặc trưng dùng triển khai: chọn theo PR-AUC trên validation (không nhìn kỳ test)
    def val_score(s: str) -> float:
        r = feature_sets[s]
        return r["models"][r["best_model"]]["val_pr_auc"]

    deploy = max(feature_sets, key=val_score)
    result = {
        "label": CHECKPOINT_LABELS[cp],
        "mean_cutoff_day": round(float(df["cutoff_day"].mean()), 1) if "cutoff_day" in df else None,
        "n_train": len(train_all),
        "n_test": len(test),
        "test_fail_rate": round(float(test[TARGET].mean()), 4),
        "feature_sets": feature_sets,
        "deploy_feature_set": deploy,
    }
    return result, pipelines[deploy]


def print_checkpoint(cp: str, r: dict) -> None:
    print(f"\n=== {cp} - {r['label']} (train {r['n_train']}, test {r['n_test']}, "
          f"tỷ lệ trượt test {r['test_fail_rate']:.1%}) ===")
    for set_name, fs in r["feature_sets"].items():
        fair = fs["fair_comparison"]
        print(f"\n-- Bộ đặc trưng: {set_name} ({len(fs['features'])} đặc trưng) --")
        rows = {"baseline (quy tắc)": {**{k: fair["baseline_test"][k] for k in ("recall", "precision", "f1",
                                                                                "accuracy")},
                                       "val_pr_auc": np.nan, "pr_auc": np.nan, "roc_auc": np.nan}}
        rows.update({n: {**m["test"], "val_pr_auc": m["val_pr_auc"]} for n, m in fs["models"].items()})
        table = pd.DataFrame(rows).T[["val_pr_auc", "recall", "precision", "f1", "pr_auc", "roc_auc", "accuracy"]]
        print(table.astype(float).round(3).to_string())

        b = fair["baseline_test"]
        print(f"Chọn: {fs['best_model']} | So công bằng với quy tắc (quy tắc bắt {b['caught']} SV trượt, "
              f"báo nhầm {b['false_alarms']}):")
        labels = {"same_precision": "ngưỡng cùng precision (validation)",
                  "same_recall": "ngưỡng cùng recall (validation)   "}
        for key, label in labels.items():
            m = fair[key]
            if not m:
                continue
            t = m["test"]
            verdict = "HƠN quy tắc" if m["beats_baseline"] else "đánh đổi"
            print(f"  {label} {m['threshold']:.2f}: bắt {t['caught']} ({m['extra_caught']:+d}), "
                  f"báo nhầm {t['false_alarms']} ({-m['fewer_false_alarms']:+d}) | "
                  f"P {b['precision']:.3f}->{t['precision']:.3f}, R {b['recall']:.3f}->{t['recall']:.3f} | {verdict}")
        print("  Đặc trưng quan trọng: "
              + ", ".join(f"{k} {v:.3f}" for k, v in list(fs["feature_importance"].items())[:5]))
    print(f"Bộ đặc trưng triển khai (theo validation): {r['deploy_feature_set']}")


def summary_table(run: dict) -> pd.DataFrame:
    rows = {}
    for cp, r in run["checkpoints"].items():
        for set_name, fs in r["feature_sets"].items():
            best = fs["models"][fs["best_model"]]
            fair = fs["fair_comparison"]
            row = {
                "mô hình": fs["best_model"],
                "val_pr_auc": best["val_pr_auc"],
                "pr_auc": best["test"]["pr_auc"],
                "f1@0.5": best["test"]["f1"],
                "f1 quy tắc": fair["baseline_test"]["f1"],
            }
            for key, short in (("same_precision", "cùng P"), ("same_recall", "cùng R")):
                m = fair[key]
                row[f"{short}: bắt/nhầm"] = (f"{m['extra_caught']:+d}/{-m['fewer_false_alarms']:+d}"
                                             + (" ✓" if m["beats_baseline"] else "")) if m else None
            rows[f"{cp} {set_name}"] = row
    return pd.DataFrame(rows).T


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", default="oulad", help="tiền tố file đặc trưng, vd oulad -> oulad_M1.csv")
    parser.add_argument("--data-dir", type=Path, default=ML_DIR / "data" / "processed")
    parser.add_argument("--val-term", default="2014B")
    parser.add_argument("--test-term", default="2014J")
    parser.add_argument("--no-svm", action="store_true", help="bỏ SVM (chậm nhất) để chạy nhanh")
    parser.add_argument("--note", default="", help="ghi chú cho lần chạy")
    args = parser.parse_args()

    out_dir = ML_DIR / "models" / args.source
    out_dir.mkdir(parents=True, exist_ok=True)
    run = {
        "source": args.source,
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "note": args.note,
        "split": {"val_term": args.val_term, "test_term": args.test_term},
        "selection_metric": "val_pr_auc",
        "checkpoints": {},
    }

    for cp in CHECKPOINTS:
        path = args.data_dir / f"{args.source}_{cp}.csv"
        if not path.exists():
            raise SystemExit(f"Không thấy {path}. Chạy trước adapter, vd: python ml/adapters/{args.source}.py")
        result, pipeline = run_checkpoint(cp, pd.read_csv(path), args.val_term, args.test_term, not args.no_svm)
        run["checkpoints"][cp] = result
        print_checkpoint(cp, result)

        deployed = result["feature_sets"][result["deploy_feature_set"]]
        joblib.dump(
            {"pipeline": pipeline, "model_name": deployed["best_model"], "checkpoint": cp,
             "feature_set": result["deploy_feature_set"], "features": deployed["features"],
             "metrics": deployed["models"][deployed["best_model"]]["test"],
             "thresholds": deployed["fair_comparison"]["thresholds"],
             "trained_at": run["trained_at"], "source": args.source},
            out_dir / f"{cp}.joblib",
        )

    (out_dir / "results.json").write_text(json.dumps(run, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n=== Tóm tắt trên kỳ test ===")
    print(summary_table(run).to_string())
    print(f"\nĐã lưu mô hình và kết quả vào {out_dir}")


if __name__ == "__main__":
    main()
