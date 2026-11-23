"""Tài khoản của tôi: liên kết email để nhận cảnh báo, gửi thư thử.

Liên kết email gồm 2 bước: nhập địa chỉ -> hệ thống gửi mã 6 số -> nhập mã. Chỉ email đã xác nhận mới nhận
email cảnh báo (tránh gửi điểm, cảnh báo của sinh viên tới nhầm người).
"""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import mailer
from ..auth import get_current_user
from ..config import settings
from ..database_v2 import get_db_v2
from ..models_v2 import AuditLog, EmailVerification, User
from .auth import UserOut, user_out

router = APIRouter(prefix="/account", tags=["Tài khoản"])

CODE_MINUTES = 10  # mã hết hạn sau 10 phút
RESEND_SECONDS = 60  # mỗi phút gửi tối đa một mã
MAX_ATTEMPTS = 5


class EmailIn(BaseModel):
    email: str = Field(min_length=5, max_length=100)


class CodeIn(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")


def _hash(user_id: int, code: str) -> str:
    return hashlib.sha256(f"{user_id}:{code}:{settings.jwt_secret}".encode()).hexdigest()


@router.get("", summary="Thông tin tài khoản và trạng thái email")
def account(user: User = Depends(get_current_user), db: Session = Depends(get_db_v2)):
    pending = db.get(EmailVerification, user.id)
    return {
        "user": user_out(user),
        "email": user.email, "email_verified": user.email_verified_at is not None,
        "email_verified_at": user.email_verified_at.isoformat(timespec="minutes") if user.email_verified_at else None,
        "pending": {"email": pending.email, "expires_at": pending.expires_at.isoformat(timespec="minutes")}
        if pending and pending.expires_at > datetime.now() else None,
        "mail": {"mode": mailer.mode()},
    }


@router.post("/email/request", summary="Gửi mã xác nhận tới email muốn liên kết")
def request_code(data: EmailIn, user: User = Depends(get_current_user), db: Session = Depends(get_db_v2)):
    email = data.email.strip().lower()
    if not mailer.EMAIL_RE.match(email):
        raise HTTPException(400, "Địa chỉ email không hợp lệ")
    if user.email_verified_at and (user.email or "").lower() == email:
        raise HTTPException(400, "Email này đã được liên kết với tài khoản của bạn")
    taken = db.scalar(select(func.count()).select_from(User).where(
        func.lower(User.email) == email, User.id != user.id, User.email_verified_at.is_not(None)))
    if taken:
        raise HTTPException(409, "Email này đã liên kết với một tài khoản khác")

    pending = db.get(EmailVerification, user.id)
    if pending and (datetime.now() - pending.created_at).total_seconds() < RESEND_SECONDS:
        wait = RESEND_SECONDS - int((datetime.now() - pending.created_at).total_seconds())
        raise HTTPException(429, f"Vừa gửi mã. Chờ {wait} giây rồi gửi lại.")

    code = f"{secrets.randbelow(10**6):06d}"
    now = datetime.now()
    if pending:
        db.delete(pending)
        db.flush()
    db.add(EmailVerification(user_id=user.id, email=email, code_hash=_hash(user.id, code), attempts=0,
                             expires_at=now + timedelta(minutes=CODE_MINUTES), created_at=now))
    text = (f"Chào {user.full_name},\n\n"
            f"Mã xác nhận liên kết email với tài khoản EduAgent ({user.username}) của bạn là: {code}\n"
            f"Mã có hiệu lực trong {CODE_MINUTES} phút.\n\n"
            "Sau khi liên kết, bạn sẽ nhận email khi hệ thống cảnh báo sớm phát hiện vấn đề học tập.\n"
            "Nếu bạn không yêu cầu, hãy bỏ qua email này.\n\n"
            "Hệ thống cảnh báo sớm EduAgent - Trường Đại học Đại Nam")
    mail = mailer.Mail(to=email, subject="[EduAgent] Mã xác nhận liên kết email", text=text, kind="verify",
                       user_id=user.id, log_text=text.replace(code, "******"))
    mailer.deliver(db, [mail])
    if mail.result["status"] == "failed":
        db.rollback()
        raise HTTPException(502, f"Không gửi được email. {mail.result.get('error', '')}")
    db.commit()
    out = {"sent_to": mailer.mask_email(email), "expires_minutes": CODE_MINUTES, "mode": mailer.mode()}
    # Thư không được gửi thật (chưa cấu hình SMTP, hoặc địa chỉ demo @example.edu.vn): hiện mã ngay để dùng thử được
    if mail.result["status"] == "outbox" and not settings.mail_redirect_to:
        out["dev_code"] = code
    return out


@router.post("/email/verify", response_model=UserOut, summary="Nhập mã xác nhận để hoàn tất liên kết")
def verify_code(data: CodeIn, user: User = Depends(get_current_user), db: Session = Depends(get_db_v2)):
    pending = db.get(EmailVerification, user.id)
    if pending is None or pending.expires_at < datetime.now():
        raise HTTPException(400, "Mã đã hết hạn hoặc chưa được gửi. Hãy gửi lại mã.")
    if pending.attempts >= MAX_ATTEMPTS:
        raise HTTPException(400, f"Nhập sai quá {MAX_ATTEMPTS} lần. Hãy gửi lại mã mới.")
    if not hmac.compare_digest(pending.code_hash, _hash(user.id, data.code)):
        pending.attempts += 1
        db.commit()
        left = MAX_ATTEMPTS - pending.attempts
        raise HTTPException(400, f"Mã không đúng. Còn {left} lần thử." if left else "Mã không đúng. Hãy gửi lại mã mới.")
    old = {"email": user.email, "verified": user.email_verified_at is not None}
    user.email, user.email_verified_at = pending.email, datetime.now()
    db.delete(pending)
    db.add(AuditLog(user_id=user.id, action="account.link_email", entity="users", entity_id=user.id,
                    old_value=old, new_value={"email": user.email, "verified": True}))
    db.commit()
    return user_out(user)


@router.post("/email/test", summary="Gửi thư thử tới email đã liên kết")
def send_test(user: User = Depends(get_current_user), db: Session = Depends(get_db_v2)):
    if not (user.email and user.email_verified_at):
        raise HTTPException(400, "Tài khoản chưa liên kết email")
    text = (f"Chào {user.full_name},\n\nĐây là thư thử của hệ thống cảnh báo sớm EduAgent. "
            "Bạn nhận được thư này nghĩa là email cảnh báo sẽ tới được hộp thư của bạn.\n\n"
            f"Xem cảnh báo: {settings.app_base_url}/alerts.html")
    mail = mailer.Mail(to=user.email, subject="[EduAgent] Thư thử", text=text, kind="test", user_id=user.id)
    mailer.deliver(db, [mail])
    db.commit()
    if mail.result["status"] == "failed":
        raise HTTPException(502, f"Không gửi được email. {mail.result.get('error', '')}")
    return {"status": mail.result["status"], "to": mailer.mask_email(settings.mail_redirect_to or user.email)}
