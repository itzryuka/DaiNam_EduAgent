"""Lịch sử gửi email và cấu hình gửi email cảnh báo / Agent tự chạy.

Quản trị xem mọi email; giảng viên, sinh viên chỉ xem email gửi tới chính mình.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .. import mailer, scheduler
from ..auth import get_current_user, require_roles
from ..database_v2 import get_db_v2
from ..models_v2 import AuditLog, EmailLog, Setting, User
from ..notifier import AUDIENCE_LABELS, audiences

router = APIRouter(prefix="/emails", tags=["Email"])
KIND_LABELS = {"verify": "Mã xác nhận", "alert": "Cảnh báo", "test": "Thư thử"}


class ConfigIn(BaseModel):
    audiences: list[str]
    agent_auto: bool


def _row(e: EmailLog, admin: bool) -> dict:
    return {"id": e.id, "created_at": e.created_at.isoformat(timespec="minutes"), "kind": e.kind,
            "kind_label": KIND_LABELS[e.kind], "audience": e.audience,
            "audience_label": AUDIENCE_LABELS.get(e.audience or "", None),
            "to": e.to_email if admin else mailer.mask_email(e.to_email),
            "user": {"username": e.user.username, "full_name": e.user.full_name} if e.user else None,
            "run_id": e.run_id, "n_alerts": e.n_alerts, "subject": e.subject, "body": e.body,
            "status": e.status, "error": e.error}


@router.get("", summary="Lịch sử email đã gửi")
def list_emails(kind: str | None = Query(default=None, pattern="^(verify|alert|test)$"),
                status: str | None = Query(default=None, pattern="^(sent|outbox|failed)$"),
                limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0),
                user: User = Depends(get_current_user), db: Session = Depends(get_db_v2)):
    admin = user.role == "admin"
    query = select(EmailLog)
    if not admin:
        query = query.where(EmailLog.user_id == user.id)
    if kind:
        query = query.where(EmailLog.kind == kind)
    if status:
        query = query.where(EmailLog.status == status)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.options(selectinload(EmailLog.user)).order_by(EmailLog.id.desc())
                      .limit(limit).offset(offset)).all()
    return {"total": total, "items": [_row(e, admin) for e in rows]}


@router.get("/config", summary="Cấu hình gửi email và lịch chạy Agent (quản trị)")
def get_config(_: User = Depends(require_roles("admin")), db: Session = Depends(get_db_v2)):
    linked = dict(db.execute(select(User.role, func.count()).where(User.email_verified_at.is_not(None))
                             .group_by(User.role)).all())
    totals = dict(db.execute(select(User.role, func.count()).group_by(User.role)).all())
    last = db.execute(select(EmailLog.status, func.count()).where(EmailLog.kind == "alert")
                      .group_by(EmailLog.status)).all()
    return {"mail": mailer.status(), "audiences": audiences(db), "audience_labels": AUDIENCE_LABELS,
            "linked": {role: {"linked": linked.get(role, 0), "total": n} for role, n in totals.items()},
            "alert_emails": dict(last), "agent": scheduler.status()}


@router.put("/config", summary="Đổi người nhận email cảnh báo, bật / tắt Agent tự chạy (quản trị)")
def put_config(data: ConfigIn, admin: User = Depends(require_roles("admin")), db: Session = Depends(get_db_v2)):
    bad = [a for a in data.audiences if a not in AUDIENCE_LABELS]
    if bad:
        raise HTTPException(400, f"Người nhận không hợp lệ: {', '.join(bad)}")
    values = {"alert_email_audiences": ",".join(a for a in AUDIENCE_LABELS if a in data.audiences),
              "agent_auto": "1" if data.agent_auto else "0"}
    for key, value in values.items():
        row = db.get(Setting, key)
        old = row.value if row else None
        if row is None:
            db.add(Setting(key=key, value=value))
        else:
            row.value = value
        if old != value:
            db.add(AuditLog(user_id=admin.id, action="settings.update", entity="settings", entity_id=None,
                            old_value={key: old}, new_value={key: value}, created_at=datetime.now()))
    db.commit()
    return get_config(admin, db)
