"""Quản trị hệ thống: danh sách tài khoản, khóa / mở khóa, gán email. Chỉ vai trò admin."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from .. import mailer
from ..auth import ROLE_LABELS, require_roles
from ..database_v2 import get_db_v2
from ..models_v2 import AuditLog, Lecturer, Student, User

router = APIRouter(prefix="/admin", tags=["Quản trị"])
admin_only = require_roles("admin")


class UserUpdate(BaseModel):
    is_active: bool | None = None
    # Email do nhà trường cấp, quản trị nhập thay người dùng: coi như đã xác nhận. Chuỗi rỗng = gỡ liên kết.
    email: str | None = None


def _row(u: User) -> dict:
    detail = None
    if u.student:
        detail = f"Lớp {u.student.class_.code}"
    elif u.lecturer:
        advised = ", ".join(c.code for c in u.lecturer.advised_classes)
        detail = f"{u.lecturer.lecturer_code}" + (f" · CVHT {advised}" if advised else "")
    return {"id": u.id, "username": u.username, "full_name": u.full_name, "email": u.email,
            "email_verified": u.email_verified_at is not None, "role": u.role,
            "role_label": ROLE_LABELS[u.role], "is_active": u.is_active, "detail": detail,
            "last_login_at": u.last_login_at.isoformat(timespec="minutes") if u.last_login_at else None}


@router.get("/users", summary="Danh sách tài khoản")
def list_users(
    role: str | None = Query(default=None, pattern="^(admin|lecturer|student)$"),
    q: str | None = Query(default=None, max_length=100, description="Tìm theo tên đăng nhập hoặc họ tên"),
    email: str | None = Query(default=None, pattern="^(linked|unlinked)$", description="Lọc theo đã liên kết email"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: User = Depends(admin_only),
    db: Session = Depends(get_db_v2),
):
    query = select(User)
    if role:
        query = query.where(User.role == role)
    if q:
        like = f"%{q.strip()}%"
        query = query.where(or_(User.username.like(like), User.full_name.like(like)))
    if email == "linked":
        query = query.where(User.email_verified_at.is_not(None))
    elif email == "unlinked":
        query = query.where(User.email_verified_at.is_(None))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    counts = dict(db.execute(select(User.role, func.count()).group_by(User.role)).all())
    unlinked = db.scalar(select(func.count()).select_from(User).where(User.email_verified_at.is_(None)))
    users = db.scalars(
        query.options(selectinload(User.student).selectinload(Student.class_),
                      selectinload(User.lecturer).selectinload(Lecturer.advised_classes))
        .order_by(User.role, User.username).limit(limit).offset(offset)
    ).all()
    return {"total": total, "counts": counts, "unlinked": unlinked, "items": [_row(u) for u in users]}


@router.patch("/users/{user_id}", summary="Khóa / mở khóa tài khoản, gán email")
def update_user(user_id: int, data: UserUpdate, request: Request, admin: User = Depends(admin_only),
                db: Session = Depends(get_db_v2)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "Không tìm thấy tài khoản")
    ip = request.client.host if request.client else None
    if data.email is not None:
        _set_email(db, user, data.email.strip().lower(), admin.id, ip)
    if data.is_active is None:
        db.commit()
        return _row(user)
    if user.id == admin.id and not data.is_active:
        raise HTTPException(400, "Không thể tự khóa tài khoản của chính mình")
    if user.is_active != data.is_active:
        db.add(AuditLog(user_id=admin.id, action="user.unlock" if data.is_active else "user.lock",
                        entity="users", entity_id=user.id, old_value={"is_active": user.is_active},
                        new_value={"is_active": data.is_active},
                        ip_address=request.client.host if request.client else None, created_at=datetime.now()))
        user.is_active = data.is_active
        db.commit()
    return _row(user)


def _set_email(db: Session, user: User, email: str, admin_id: int, ip: str | None) -> None:
    old = {"email": user.email, "verified": user.email_verified_at is not None}
    if not email:
        user.email_verified_at = None
    else:
        if not mailer.EMAIL_RE.match(email):
            raise HTTPException(400, "Địa chỉ email không hợp lệ")
        taken = db.scalar(select(func.count()).select_from(User).where(
            func.lower(User.email) == email, User.id != user.id, User.email_verified_at.is_not(None)))
        if taken:
            raise HTTPException(409, "Email này đã liên kết với một tài khoản khác")
        if user.email != email or user.email_verified_at is None:
            user.email, user.email_verified_at = email, datetime.now()
    db.add(AuditLog(user_id=admin_id, action="user.set_email", entity="users", entity_id=user.id, old_value=old,
                    new_value={"email": user.email, "verified": user.email_verified_at is not None},
                    ip_address=ip, created_at=datetime.now()))
