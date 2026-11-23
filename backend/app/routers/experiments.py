"""Kết quả train mô hình do ml/train.py ghi ra, phục vụ trang "So sánh mô hình"."""

import json

from fastapi import APIRouter, HTTPException

from ..config import settings

router = APIRouter(prefix="/experiments", tags=["Mô hình AI"])


@router.get("/latest", summary="Kết quả lần train gần nhất")
def latest():
    path = settings.models_dir / "metrics.json"
    if not path.exists():
        raise HTTPException(404, "Chưa có kết quả train. Hãy chạy: python ml/train.py")
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("/history", summary="Lịch sử các lần train, mới nhất trước")
def history():
    path = settings.models_dir / "history.jsonl"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in reversed(lines) if line.strip()]


@router.get("/oulad", summary="Mô hình chính: dự báo trượt môn M0/M1/M2 trên dữ liệu thật OULAD, so công bằng với quy tắc")
def oulad():
    path = settings.models_dir / "oulad" / "results.json"
    if not path.exists():
        raise HTTPException(404, "Chưa train mô hình OULAD. Chạy: python ml/adapters/oulad.py rồi python ml/train_checkpoints.py")
    r = json.loads(path.read_text(encoding="utf-8"))
    checkpoints = {}
    for cp, c in r["checkpoints"].items():
        deploy = c["feature_sets"][c["deploy_feature_set"]]
        fair = deploy["fair_comparison"]
        checkpoints[cp] = {
            "label": c["label"], "mean_cutoff_day": c["mean_cutoff_day"], "n_train": c["n_train"],
            "n_test": c["n_test"], "test_fail_rate": c["test_fail_rate"], "feature_set": c["deploy_feature_set"],
            "features": deploy["features"], "best_model": deploy["best_model"],
            "test": deploy["models"][deploy["best_model"]]["test"],
            "models": {name: {"val_pr_auc": m["val_pr_auc"], "test_pr_auc": m["test"]["pr_auc"]}
                       for name, m in deploy["models"].items()},
            "baseline_test": fair["baseline_test"],
            "same_precision": fair["same_precision"], "same_recall": fair["same_recall"],
            "feature_importance": deploy.get("feature_importance", {}),
        }
    return {"trained_at": r["trained_at"], "split": r["split"], "checkpoints": checkpoints}
