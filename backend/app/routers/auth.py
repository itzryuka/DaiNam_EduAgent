"""Đăng nhập, thông tin tài khoản đang dùng, đổi mật khẩu."""

import time
from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import ROLE_LABELS, get_current_user
from ..database_v2 import get_db_v2
from ..models_v2 import AuditLog, User
from ..security import DUMMY_HASH, create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["Đăng nhập"])

# Chống dò mật khẩu: sai MAX_FAILURES lần liên tiếp thì khóa tên đăng nhập đó LOCK_SECONDS giây.
# Lưu trong bộ nhớ, mất khi khởi động lại backend; đủ cho quy mô đề tài.
MAX_FAILURES = 5
LOCK_SECONDS = 300
_failures: dict[str, list[float]] = defaultdict(list)


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    id: int
    username: str
    full_name: str
    email: str | None
    email_verified: bool = False  # chỉ email đã xác nhận mới nhận email cảnh báo
    role: str
    role_label: str
    lecturer_id: int | None = None
    student_id: int | None = None
    student_code: str | None = None
    advised_classes: list[str] = []  # lớp hành chính mà giảng viên làm CVHT


class LoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class ChangePasswordIn(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


def user_out(user: User) -> UserOut:
    out = UserOut(id=user.id, username=user.username, full_name=user.full_name, email=user.email,
                  email_verified=user.email_verified_at is not None, role=user.role, role_label=ROLE_LABELS[user.role])
    if user.lecturer:
        out.lecturer_id = user.lecturer.id
        out.advised_classes = [c.code for c in user.lecturer.advised_classes]
        if out.advised_classes:
            out.role_label += " · CVHT"
    if user.student:
        out.student_id = user.student.id
        out.student_code = user.student.student_code
    return out


def _check_locked(key: str) -> None:
    recent = [t for t in _failures[key] if time.time() - t < LOCK_SECONDS]
    _failures[key] = recent
    if len(recent) >= MAX_FAILURES:
        wait = int(LOCK_SECONDS - (time.time() - recent[0])) // 60 + 1
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            f"Sai mật khẩu quá {MAX_FAILURES} lần. Thử lại sau khoảng {wait} phút.")


@router.post("/login", response_model=LoginOut, summary="Đăng nhập, nhận token")
def login(data: LoginIn, request: Request, db: Session = Depends(get_db_v2)):
    key = data.username.strip().lower()
    _check_locked(key)

    user = db.scalar(select(User).where(User.username == data.username.strip()))
    # Luôn kiểm tra một mã băm để thời gian phản hồi như nhau dù tài khoản có tồn tại hay không
    valid = verify_password(data.password, user.password_hash if user else DUMMY_HASH)
    if not user or not valid:
        _failures[key].append(time.time())
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sai tên đăng nhập hoặc mật khẩu")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tài khoản đã bị khóa. Liên hệ quản trị hệ thống.")

    _failures.pop(key, None)
    user.last_login_at = datetime.now()
    db.add(AuditLog(user_id=user.id, action="auth.login", entity="users", entity_id=user.id,
                    ip_address=request.client.host if request.client else None))
    db.commit()
    token, expires_in = create_access_token(user.id, user.role)
    return LoginOut(access_token=token, expires_in=expires_in, user=user_out(user))


@router.get("/me", response_model=UserOut, summary="Tài khoản đang đăng nhập")
def me(user: User = Depends(get_current_user)):
    return user_out(user)


@router.post("/change-password", status_code=204, summary="Đổi mật khẩu")
def change_password(data: ChangePasswordIn, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db_v2)):
    if not verify_password(data.old_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Mật khẩu hiện tại không đúng")
    if data.old_password == data.new_password:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Mật khẩu mới phải khác mật khẩu cũ")
    user.password_hash = hash_password(data.new_password)
    db.add(AuditLog(user_id=user.id, action="auth.change_password", entity="users", entity_id=user.id))
    db.commit()
