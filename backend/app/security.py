"""Mật khẩu và token đăng nhập.

Mật khẩu: băm PBKDF2-SHA256 bằng thư viện chuẩn của Python. Định dạng lưu trong users.password_hash:
    pbkdf2_sha256$<số vòng>$<salt hex>$<hash hex>
Không bao giờ lưu mật khẩu gốc.

Token: JWT ký bằng HS256 với khóa JWT_SECRET trong backend/.env. Token chứa id người dùng, vai trò, hạn dùng.
"""

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone

import jwt

from .config import settings

ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 200_000
JWT_ALGORITHM = "HS256"

if settings.jwt_secret:
    _JWT_SECRET = settings.jwt_secret
else:
    # Chưa cấu hình: dùng khóa ngẫu nhiên tạm thời. Mỗi lần backend khởi động lại, mọi người phải đăng nhập lại.
    _JWT_SECRET = secrets.token_urlsafe(48)
    logging.getLogger("uvicorn.error").warning(
        "Chưa có JWT_SECRET trong backend/.env: đang dùng khóa tạm. Chạy start.bat để tự tạo khóa cố định."
    )


def hash_password(password: str, iterations: int = ITERATIONS) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations)
    return f"{ALGORITHM}${iterations}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt, expected = stored.split("$")
        if algorithm != ALGORITHM:
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iterations))
    except (ValueError, TypeError):
        return False
    # So sánh thời gian hằng để không lộ thông tin qua thời gian phản hồi
    return hmac.compare_digest(digest.hex(), expected)


# Băm sẵn một mật khẩu giả để khi tên đăng nhập không tồn tại vẫn tốn thời gian như khi sai mật khẩu
# (không cho kẻ dò biết tài khoản nào có thật)
DUMMY_HASH = hash_password(secrets.token_hex(8))


def create_access_token(user_id: int, role: str) -> tuple[str, int]:
    """Trả về (token, số giây còn hiệu lực)."""
    expires_in = settings.jwt_expire_minutes * 60
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "role": role, "iat": now, "exp": now + timedelta(seconds=expires_in)}
    return jwt.encode(payload, _JWT_SECRET, algorithm=JWT_ALGORITHM), expires_in


def decode_access_token(token: str) -> dict:
    """Giải mã và kiểm tra chữ ký, hạn dùng. Lỗi thì ném jwt.PyJWTError."""
    return jwt.decode(token, _JWT_SECRET, algorithms=[JWT_ALGORITHM], options={"require": ["sub", "exp"]})
