"""Điểm khởi động backend.

Chạy (từ thư mục gốc dự án):
    .venv\\Scripts\\activate
    uvicorn app.main:app --reload --app-dir backend

Rồi mở http://127.0.0.1:8000 (giao diện) và http://127.0.0.1:8000/docs (thử API).
"""

import json
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from .auth import require_roles
from .config import settings
from .database_v2 import engine_v2, migrate_v2
from . import scheduler
from .routers import account, admin, agent, auth, dashboard, emails, experiments, manage, me, teaching



@asynccontextmanager
async def lifespan(_: FastAPI):
    scheduler.start()  # Agent tự chạy theo lịch và khi có điểm / điểm danh mới (backend/app/scheduler.py)
    yield
    scheduler.stop()


app = FastAPI(
    lifespan=lifespan,
    title="EduAgent API",
    description="Hệ thống cảnh báo sớm sinh viên có nguy cơ học tập yếu",
    version="0.1.0",
)

migrate_v2()  # thêm các cột mới vào CSDL v2 đã có (an toàn khi chạy lại)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def no_stale_frontend(request: Request, call_next):
    """Bắt trình duyệt hỏi lại server mỗi lần tải HTML/JS/CSS (vẫn dùng ETag nên file không đổi thì không tải lại).
    Tránh lỗi trình duyệt giữ bản api.js cũ trong khi layout.js đã là bản mới sau mỗi lần cập nhật."""
    response = await call_next(request)
    if not request.url.path.startswith("/api"):
        response.headers.setdefault("Cache-Control", "no-cache")
    return response


@app.exception_handler(OperationalError)
def database_unavailable(request: Request, exc: OperationalError):
    return JSONResponse(
        status_code=503,
        content={"detail": "Không kết nối được MySQL. Kiểm tra XAMPP đã bật MySQL và file backend/.env."},
    )


@app.get("/api/health", tags=["Hệ thống"], summary="Kiểm tra CSDL và mô hình của AI Agent")
def health():
    try:
        with engine_v2.connect() as conn:
            conn.execute(text("SELECT 1"))
        database = "ok"
    except OperationalError:
        database = "không kết nối được"

    # Mô hình của AI Agent (ml/train_dainam.py): mỗi mốc M0/M1/M2 một mô hình
    results = settings.models_dir / "dainam" / "results.json"
    if results.exists():
        r = json.loads(results.read_text(encoding="utf-8"))
        model_info = {"name": "Mô hình Agent (Đại Nam)", "trained_at": r.get("trained_at"),
                      "checkpoints": sorted(r.get("checkpoints", {}))}
    else:
        model_info = {"error": "Chưa có mô hình cho Agent. Chạy: python ml/train_dainam.py"}

    return {"database": database, "database_name": settings.db_name_v2, "model": model_info}


# Không cần đăng nhập: /api/health, /api/auth/login
app.include_router(auth.router, prefix="/api")
# Theo vai trò (kiểm tra trong từng router)
app.include_router(me.router, prefix="/api")
app.include_router(account.router, prefix="/api")
app.include_router(emails.router, prefix="/api")
app.include_router(manage.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(teaching.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(agent.router, prefix="/api")
# Kết quả train mô hình (đọc file trong ml/models, không dùng CSDL): chỉ quản trị và giảng viên
app.include_router(experiments.router, prefix="/api", dependencies=[Depends(require_roles("admin", "lecturer"))])

# Phục vụ giao diện HTML tại "/". Phải đặt SAU các route /api.
app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend")
