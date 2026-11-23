"""Cho AI Agent tự chạy, không cần quản trị bấm nút.

Một luồng nền:
  0. Ngay khi giảng viên lưu điểm / điểm danh (request_run): chờ vài giây để gộp các lần lưu liên tiếp rồi chạy,
     nên sinh viên vừa bị cảnh báo nhận email sau khoảng 10-20 giây.
  Mỗi phút kiểm tra thêm:
  1. Theo lịch (cài đặt agent_schedule, vd "weekly:MON:07:00"): đến giờ mà tuần này chưa chạy thì chạy.
  2. Khi có dữ liệu mới (cài đặt agent_poll_minutes): giảng viên vừa nhập điểm / điểm danh sau lần chạy gần nhất
     thì chạy với lý do "grade_update". Agent chỉ báo cho các trường hợp mới hoặc xấu đi, nên chạy nhiều không spam.
Tắt bằng cài đặt agent_auto = 0. Chưa có lần chạy nào (chưa bootstrap) thì bỏ qua: start.py sẽ khởi tạo.
"""

import logging
import threading
import time
from datetime import datetime, timedelta

from sqlalchemy import select, text

from .agent import AgentError, models_ready, run_agent, warm_up
from .database_v2 import SessionV2
from .models_v2 import AgentRun, Setting

log = logging.getLogger("eduagent.scheduler")
DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
TICK_SECONDS = 60
DEBOUNCE_SECONDS = 5  # gộp nhiều lần lưu liên tiếp (vd lưu điểm từng sinh viên) thành một lần chạy
_stop = threading.Event()
_wake = threading.Event()  # đánh thức luồng nền sớm
_pending = threading.Event()  # có dữ liệu mới cần chạy Agent ngay
_state = {"last_poll": None, "last_check": None, "last_auto_run": None}


def _setting(db, key: str, default: str) -> str:
    row = db.get(Setting, key)
    return row.value if row else default


def last_due(spec: str, now: datetime) -> datetime | None:
    """Thời điểm đến hạn gần nhất (<= now) của lịch dạng 'weekly:MON:07:00' hoặc 'daily:07:00'."""
    parts = spec.split(":")
    try:
        if parts[0] == "weekly":
            day, hour, minute = DAYS.index(parts[1].upper()), int(parts[2]), int(parts[3])
            due = (now - timedelta(days=(now.weekday() - day) % 7)).replace(hour=hour, minute=minute,
                                                                              second=0, microsecond=0)
            return due if due <= now else due - timedelta(days=7)
        if parts[0] == "daily":
            due = now.replace(hour=int(parts[1]), minute=int(parts[2]), second=0, microsecond=0)
            return due if due <= now else due - timedelta(days=1)
    except (ValueError, IndexError):
        log.warning("Cài đặt agent_schedule không hợp lệ: %s", spec)
    return None


def latest_data_change(db) -> datetime | None:
    row = db.execute(text("SELECT (SELECT MAX(updated_at) FROM grades), (SELECT MAX(recorded_at) FROM attendance)")).one()
    values = [v for v in row if v is not None]
    return max(values) if values else None


def tick(now: datetime | None = None) -> str | None:
    """Một lượt kiểm tra. Trả về lý do đã chạy ('schedule' / 'grade_update') hoặc None."""
    now = now or datetime.now()
    _state["last_check"] = now
    with SessionV2() as db:
        if _setting(db, "agent_auto", "1") != "1" or not models_ready():
            return None
        last = db.scalar(select(AgentRun).where(AgentRun.status == "success", AgentRun.trigger_type != "replay")
                         .order_by(AgentRun.started_at.desc()))
        if last is None:
            return None
        trigger = None
        due = last_due(_setting(db, "agent_schedule", "weekly:MON:07:00"), now)
        if due is not None:
            done = db.scalar(select(AgentRun.id).where(AgentRun.trigger_type == "schedule",
                                                       AgentRun.started_at >= due).limit(1))
            if done is None and last.started_at < due:
                trigger = "schedule"
        if trigger is None:
            minutes = float(_setting(db, "agent_poll_minutes", "15") or 15)
            if _state["last_poll"] is None or now - _state["last_poll"] >= timedelta(minutes=minutes):
                _state["last_poll"] = now
                changed = latest_data_change(db)
                if changed is not None and changed > last.started_at:
                    trigger = "grade_update"
        if trigger is None:
            return None
        try:
            run = run_agent(db, trigger)
            _state["last_auto_run"] = now
            log.info("Agent tự chạy (%s): %s", trigger, run.message)
        except AgentError as exc:
            log.warning("Agent tự chạy (%s) không thành công: %s", trigger, exc)
        return trigger


def request_run() -> None:
    """Gọi sau khi lưu điểm / điểm danh: Agent chạy sau vài giây thay vì chờ lượt kiểm tra 15 phút."""
    _pending.set()
    _wake.set()


def run_for_new_data() -> str | None:
    """Chạy Agent vì có điểm / điểm danh mới (lý do grade_update). Agent đang chạy thì để lượt sau thử lại."""
    with SessionV2() as db:
        if _setting(db, "agent_auto", "1") != "1" or not models_ready():
            return None
        if db.scalar(select(AgentRun.id).where(AgentRun.status == "success").limit(1)) is None:
            return None  # chưa bootstrap
        try:
            run = run_agent(db, "grade_update")
        except AgentError as exc:
            if "đang chạy" in str(exc):
                _pending.set()
            log.warning("Agent chạy ngay khi có điểm mới không thành công: %s", exc)
            return None
        _state["last_auto_run"] = datetime.now()
        log.info("Agent chạy ngay khi có điểm / điểm danh mới: %s", run.message)
        return "grade_update"


def _loop() -> None:
    while not _stop.is_set():
        _wake.wait(TICK_SECONDS)
        _wake.clear()
        if _stop.is_set():
            break
        try:
            if _pending.is_set():
                time.sleep(DEBOUNCE_SECONDS)
                _wake.clear()
                _pending.clear()
                run_for_new_data()
            tick()
        except Exception:  # lỗi CSDL tạm thời: thử lại lượt sau
            log.exception("Lịch chạy Agent gặp lỗi")


def start() -> None:
    _stop.clear()
    threading.Thread(target=_loop, name="agent-scheduler", daemon=True).start()
    # Nạp sẵn mô hình để lần chạy Agent đầu tiên sau khi bật backend không phải chờ
    threading.Thread(target=warm_up, name="agent-warm-up", daemon=True).start()


def stop() -> None:
    _stop.set()
    _wake.set()


def status() -> dict:
    with SessionV2() as db:
        return {"auto": _setting(db, "agent_auto", "1") == "1",
                "schedule": _setting(db, "agent_schedule", "weekly:MON:07:00"),
                "poll_minutes": float(_setting(db, "agent_poll_minutes", "15") or 15),
                "last_check": _state["last_check"].isoformat(timespec="minutes") if _state["last_check"] else None,
                "last_data_change": (c.isoformat(timespec="minutes") if (c := latest_data_change(db)) else None)}
