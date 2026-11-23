"""Huấn luyện và so sánh 4 mô hình phân lớp dự báo sinh viên có nguy cơ học yếu.

Mô hình tốt nhất (theo F1 kiểm định chéo 5 lần trên tập train) được lưu vào ml/models/best_model.joblib
để backend nạp lên và dự báo. Kết quả lần chạy được ghi ra ml/models/metrics.json và
nối thêm vào ml/models/history.jsonl. Trang "So sánh mô hình" trên web đọc hai file này.

Chạy:  python ml/train.py
       python ml/train.py --note "thử bỏ cột lms_logins_per_week"
       python ml/train.py --data ml/data/processed/du_lieu_that.csv
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

import joblib
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import RandomForestClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import cross_val_score, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC
from sklearn.tree import DecisionTreeClassifier

ML_DIR = Path(__file__).resolve().parent
DEFAULT_DATA = ML_DIR / "data" / "synthetic" / "students_synthetic.csv"
DEFAULT_OUT_DIR = ML_DIR / "models"

# Chỉ dùng thông tin đã có ở GIỮA học kỳ. Không thêm semester_gpa hay điểm thi cuối kỳ
# vào đây: đó là kết quả cần dự báo (data leakage).
FEATURES = [
    "gpa_prev",
    "attendance_rate",
    "midterm_avg",
    "failed_courses_prev",
    "credits_registered",
    "assignment_submission_rate",
    "lms_logins_per_week",
]
TARGET = "at_risk"
TEST_SIZE = 0.2


def build_models(seed: int) -> dict[str, Pipeline]:
    # class_weight="balanced": sinh viên học yếu là thiểu số, cần tăng trọng số cho lớp này
    # để mô hình không "lười" đoán tất cả là không học yếu.
    classifiers = {
        "logistic_regression": LogisticRegression(class_weight="balanced", max_iter=1000),
        "decision_tree": DecisionTreeClassifier(class_weight="balanced", max_depth=6, random_state=seed),
        "random_forest": RandomForestClassifier(
            n_estimators=300, class_weight="balanced", min_samples_leaf=3, random_state=seed, n_jobs=-1
        ),
        # SVC không tự ra xác suất; CalibratedClassifierCV hiệu chỉnh điểm số thành xác suất 0..1
        "svm": CalibratedClassifierCV(SVC(class_weight="balanced", random_state=seed), ensemble=False),
    }
    return {name: Pipeline([("scaler", StandardScaler()), ("model", clf)]) for name, clf in classifiers.items()}


def evaluate(pipeline: Pipeline, X_test: pd.DataFrame, y_test: pd.Series) -> dict:
    y_pred = pipeline.predict(X_test)
    y_proba = pipeline.predict_proba(X_test)[:, 1]
    tn, fp, fn, tp = confusion_matrix(y_test, y_pred, labels=[0, 1]).ravel()
    return {
        "accuracy": accuracy_score(y_test, y_pred),
        "precision": precision_score(y_test, y_pred, zero_division=0),
        "recall": recall_score(y_test, y_pred, zero_division=0),
        "f1": f1_score(y_test, y_pred, zero_division=0),
        "roc_auc": roc_auc_score(y_test, y_proba),
        # tp: học yếu, đoán đúng | fn: học yếu nhưng bỏ sót | fp: cảnh báo nhầm | tn: bình thường, đoán đúng
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
    }


def feature_importance(pipeline: Pipeline, X_test: pd.DataFrame, y_test: pd.Series, seed: int) -> dict[str, float]:
    """Mức giảm F1 khi xáo trộn ngẫu nhiên từng đặc trưng. Càng lớn thì đặc trưng càng quan trọng.
    Cách này dùng được cho mọi loại mô hình."""
    result = permutation_importance(pipeline, X_test, y_test, scoring="f1", n_repeats=10, random_state=seed)
    importance = dict(zip(X_test.columns, result.importances_mean.round(4).tolist()))
    return dict(sorted(importance.items(), key=lambda kv: kv[1], reverse=True))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--note", default="", help="ghi chú cho lần chạy, hiện trong lịch sử thí nghiệm")
    args = parser.parse_args()

    if not args.data.exists():
        raise SystemExit(f"Không thấy file dữ liệu {args.data}. Chạy trước: python ml/scripts/generate_synthetic_data.py")

    df = pd.read_csv(args.data)
    X, y = df[FEATURES], df[TARGET]
    print(f"Dữ liệu: {len(df)} dòng, tỷ lệ học yếu {y.mean():.1%}")

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=TEST_SIZE, stratify=y, random_state=args.seed
    )

    results: dict[str, dict] = {}
    fitted: dict[str, Pipeline] = {}
    for name, pipeline in build_models(args.seed).items():
        cv_f1 = cross_val_score(pipeline, X_train, y_train, cv=5, scoring="f1").mean()
        pipeline.fit(X_train, y_train)
        results[name] = {"cv_f1": cv_f1, **evaluate(pipeline, X_test, y_test)}
        fitted[name] = pipeline

    # Chọn mô hình theo F1 kiểm định chéo (cv_f1) chứ không theo tập kiểm tra: tập kiểm tra nhỏ nên
    # kết quả dao động, và nếu dùng nó để chọn thì nó không còn khách quan để báo cáo kết quả cuối.
    table = pd.DataFrame(results).T.drop(columns="confusion_matrix").astype(float).sort_values("cv_f1", ascending=False)
    print("\nKết quả (cv_f1: kiểm định chéo trên tập train; các cột còn lại: trên tập kiểm tra):")
    print(table.round(3).to_string())

    best_name = table.index[0]
    print(f"\nMô hình tốt nhất: {best_name}")

    trained_at = datetime.now().isoformat(timespec="seconds")
    run = {
        "trained_at": trained_at,
        "note": args.note,
        "data": {
            "file": args.data.name,
            "rows": len(df),
            "at_risk_rate": float(y.mean()),
            "test_size": TEST_SIZE,
            "features": FEATURES,
        },
        "selection_metric": "cv_f1",
        "best_model": best_name,
        "results": results,
        "feature_importance": feature_importance(fitted[best_name], X_test, y_test, args.seed),
    }

    args.out_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "pipeline": fitted[best_name],
            "model_name": best_name,
            "features": FEATURES,
            "metrics": {k: v for k, v in results[best_name].items() if k != "confusion_matrix"},
            "trained_at": trained_at,
        },
        args.out_dir / "best_model.joblib",
    )
    (args.out_dir / "metrics.json").write_text(json.dumps(run, indent=2, ensure_ascii=False), encoding="utf-8")
    with open(args.out_dir / "history.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(run, ensure_ascii=False) + "\n")

    print(f"Đã lưu mô hình -> {args.out_dir / 'best_model.joblib'}")
    print("Xem kết quả trên web: http://127.0.0.1:8000/models.html")


if __name__ == "__main__":
    main()
