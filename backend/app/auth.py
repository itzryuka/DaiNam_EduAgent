"""Xác thực người gọi API và kiểm tra vai trò.

Dùng trong router:
    @router.get("/abc")
    def abc(user: User = Depends(require_roles("admin", "lecturer"))): ...

hoặc chặn cả router:  app.include_router(r, dependencies=[Depends(require_roles("admin"))])

Vai trò: admin (quản trị hệ thống), lecturer (giảng viên, có thể kiêm CVHT), student (sinh viên).
"""

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .database_v2 import get_db_v2
from .models_v2 import User
from .security import decode_access_token

ROLE_LABELS = {"admin": "Quản trị hệ thống", "lecturer": "Giảng viên", "student": "Sinh viên"}

_bearer = HTTPBearer(auto_error=False, description="Token nhận được từ POST /api/auth/login")


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db_v2),
) -> User:
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED, "Chưa đăng nhập hoặc phiên đăng nhập đã hết hạn",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized
    try:
        payload = decode_access_token(credentials.credentials)
        user = db.get(User, int(payload["sub"]))
    except (jwt.PyJWTError, ValueError):
        raise unauthorized from None
    if user is None or not user.is_active:
        raise unauthorized
    return user


def require_roles(*roles: str):
    """Dependency: chỉ cho các vai trò được liệt kê."""

    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Tài khoản của bạn không có quyền dùng chức năng này")
        return user

    return checker
