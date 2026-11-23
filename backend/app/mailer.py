"""Gửi email và ghi nhật ký email_logs.

- Đã cấu hình SMTP_HOST trong backend/.env: gửi thật qua SMTP (Gmail, Outlook, máy chủ mail của trường).
- Chưa cấu hình: chế độ thử, mỗi thư lưu thành một file .eml trong backend/outbox (mở được bằng Outlook /
  Thunderbird). Thư mục này có dữ liệu sinh viên nên đã nằm trong .gitignore.
- MAIL_REDIRECT_TO: khi thử nghiệm với tài khoản thật, chuyển mọi thư tới một hộp thư của nhóm.
"""

import re
import smtplib
import ssl
from dataclasses import dataclass, field
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from sqlalchemy.orm import Session

from .config import settings
from .models_v2 import EmailLog

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


@dataclass
class Mail:
    to: str
    subject: str
    text: str
    html: str | None = None
    # Ghi nhật ký
    kind: str = "alert"
    user_id: int | None = None
    audience: str | None = None
    run_id: int | None = None
    n_alerts: int = 0
    log_text: str | None = None  # nội dung lưu vào nhật ký nếu khác thư thật (vd che mã xác nhận)
    result: dict = field(default_factory=dict)


def mode() -> str:
    # Có SMTP_USER mà chưa dán mật khẩu (vd mới điền sẵn Gmail của nhóm) thì vẫn lưu outbox, không gửi rồi báo lỗi
    if settings.smtp_host and (settings.smtp_password or not settings.smtp_user):
        return "smtp"
    return "outbox"


def status() -> dict:
    """Cấu hình gửi email hiện tại, để trang quản trị hiển thị (không lộ mật khẩu)."""
    return {"mode": mode(), "host": settings.smtp_host or None, "sender": _sender(),
            "redirect_to": settings.mail_redirect_to or None,
            "outbox_dir": str(settings.outbox_dir) if mode() == "outbox" else None}


def mask_email(email: str) -> str:
    name, _, domain = email.partition("@")
    return (name[:2] + "***" if len(name) > 2 else name[:1] + "***") + "@" + domain


DEMO_DOMAINS = ("example.edu.vn", "example.com", "example.org", "example.net")
DEMO_TLDS = (".invalid", ".test", ".example", ".localhost")


def is_demo_address(email: str) -> bool:
    """Email của dữ liệu demo (seed_demo_v2.py dùng @example.edu.vn) hoặc tên miền dành riêng cho thử nghiệm."""
    domain = email.rsplit("@", 1)[-1].strip().lower()
    return domain in DEMO_DOMAINS or domain.endswith(DEMO_TLDS)


def _sender() -> str:
    return settings.mail_from or settings.smtp_user or "eduagent@localhost"


def _build(mail: Mail, to: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((settings.mail_from_name, _sender()))
    msg["To"] = to
    subject = mail.subject if to == mail.to else f"[Thử, gửi cho {mail.to}] {mail.subject}"
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="eduagent.local")
    msg.set_content(mail.text)
    if mail.html:
        msg.add_alternative(mail.html, subtype="html")
    return msg


def _send_smtp(messages: list[tuple[Mail, EmailMessage]]) -> None:
    context = ssl.create_default_context()
    try:
        if settings.smtp_ssl:
            server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=context, timeout=20)
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20)
            server.starttls(context=context)
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password)
    except (OSError, smtplib.SMTPException) as exc:
        for mail, _ in messages:
            mail.result = {"status": "failed", "error": f"Không kết nối được máy chủ SMTP: {exc}"}
        return
    with server:
        for mail, msg in messages:
            try:
                server.send_message(msg)
                mail.result = {"status": "sent"}
            except smtplib.SMTPException as exc:
                mail.result = {"status": "failed", "error": str(exc)}


def _save_outbox(messages: list[tuple[Mail, EmailMessage]]) -> None:
    settings.outbox_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for i, (mail, msg) in enumerate(messages, 1):
        safe = re.sub(r"[^A-Za-z0-9@._-]", "_", msg["To"])
        path = settings.outbox_dir / f"{stamp}-{i:04d}-{mail.kind}-{safe}.eml"
        path.write_bytes(msg.as_bytes())
        mail.result = {"status": "outbox", "file": path.name}


def deliver(db: Session, mails: list[Mail]) -> list[Mail]:
    """Gửi một loạt thư (một kết nối SMTP) rồi ghi nhật ký. Không commit: người gọi tự commit."""
    if not mails:
        return mails
    messages = []
    for mail in mails:
        to = settings.mail_redirect_to or mail.to
        messages.append((mail, _build(mail, to)))
    if mode() == "smtp":
        # Địa chỉ của dữ liệu demo / kiểm thử không có hộp thư thật: lưu outbox, không gửi (tránh thư báo lỗi)
        real = [(m, msg) for m, msg in messages if not is_demo_address(msg["To"])]
        demo = [(m, msg) for m, msg in messages if is_demo_address(msg["To"])]
        if real:
            _send_smtp(real)
        if demo:
            _save_outbox(demo)
    else:
        _save_outbox(messages)
    for mail, msg in messages:
        db.add(EmailLog(user_id=mail.user_id, to_email=msg["To"], kind=mail.kind, audience=mail.audience,
                        run_id=mail.run_id, n_alerts=mail.n_alerts, subject=str(msg["Subject"])[:255],
                        body=mail.log_text or mail.text, status=mail.result["status"],
                        error=(mail.result.get("error") or "")[:500] or None, created_at=datetime.now()))
    return mails
