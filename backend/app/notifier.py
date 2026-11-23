"""Gửi email cảnh báo sau mỗi lần AI Agent chạy.

Mỗi người nhận một email tổng hợp (không phải mỗi cảnh báo một email):
  - Sinh viên: các môn cần chú ý, lời nhắc nên làm gì (không có xác suất trượt).
  - CVHT (giáo viên chủ nhiệm): sinh viên lớp mình cần chú ý, kèm lý do.
  - Giảng viên bộ môn: chỉ khi quản trị bật trong cài đặt alert_email_audiences.
Chỉ gửi tới tài khoản đã liên kết và xác nhận email. Lần chạy lại quá khứ (replay) không gửi.
"""

import html
import logging
from collections import defaultdict

from sqlalchemy import and_, or_, select

from . import mailer
from .config import settings
from .database_v2 import SessionV2
from .models_v2 import AgentRun, Alert, Prediction, Setting, Student, User

log = logging.getLogger("eduagent.notifier")
AUDIENCE_LABELS = {"student": "Sinh viên", "advisor": "CVHT", "lecturer": "Giảng viên"}
FOOTER = ("Email tự động từ Hệ thống cảnh báo sớm EduAgent - Khoa CNTT, Trường Đại học Đại Nam.\n"
          "Cảnh báo là gợi ý để hỗ trợ kịp thời, không phải kết luận hay quyết định kỷ luật.")


def audiences(db) -> list[str]:
    row = db.get(Setting, "alert_email_audiences")
    value = row.value if row else "student,advisor"
    return [a.strip() for a in value.split(",") if a.strip() in AUDIENCE_LABELS]


def _html(greeting: str, intro: str, groups: list[tuple[str, list[str]]], link: str) -> str:
    blocks = "".join(
        f'<div style="margin:12px 0;padding:10px 14px;border-left:4px solid #e8a317;background:#fff8e6">'
        f'<b>{html.escape(head)}</b><ul style="margin:6px 0 0;padding-left:18px">'
        + "".join(f"<li>{html.escape(line)}</li>" for line in lines) + "</ul></div>"
        for head, lines in groups)
    return f"""<div style="font-family:Segoe UI,Arial,sans-serif;font-size:14px;color:#1e293b;max-width:680px">
  <div style="background:#00358f;color:#fff;padding:12px 16px;border-radius:6px 6px 0 0">
    <b>EduAgent</b> · Hệ thống cảnh báo sớm học tập</div>
  <div style="border:1px solid #e2e8f0;border-top:0;padding:16px">
    <p>{html.escape(greeting)}</p><p>{html.escape(intro)}</p>{blocks}
    <p><a href="{link}" style="background:#00358f;color:#fff;padding:8px 14px;border-radius:5px;text-decoration:none">
      Xem chi tiết trên EduAgent</a></p>
    <p style="color:#64748b;font-size:12px">{html.escape(FOOTER).replace(chr(10), "<br>")}</p>
  </div></div>"""


def _text(greeting: str, intro: str, groups: list[tuple[str, list[str]]], link: str) -> str:
    body = "\n\n".join(head + "\n" + "\n".join(f"  - {line}" for line in lines) for head, lines in groups)
    return f"{greeting}\n\n{intro}\n\n{body}\n\nXem chi tiết: {link}\n\n--\n{FOOTER}"


def compose(user: User, audience: str, alerts: list[Alert], students: dict[int, Student],
            advisor_notified: bool) -> mailer.Mail:
    link = f"{settings.app_base_url}/alerts.html"
    greeting = f"Chào {user.full_name},"
    academic = [a for a in alerts if a.enrollment_id is None]  # cảnh báo học tập (học vụ), không theo môn
    courses = [a for a in alerts if a.enrollment_id is not None]
    if audience == "student":
        found = ([f"thuộc diện {academic[0].title[0].lower()}{academic[0].title[1:]}"] if academic else []) \
            + ([f"cần chú ý ở {len(courses)} môn học kỳ này"] if courses else [])
        intro = (f"Hệ thống cảnh báo sớm nhận thấy bạn {' và '.join(found)}. "
                 "Hãy xem lời nhắc dưới đây và chủ động trao đổi với giảng viên hoặc cố vấn học tập.")
        if advisor_notified:
            intro += " Cố vấn học tập (giáo viên chủ nhiệm) của bạn cũng đã nhận được thông báo này."
        groups = [(a.title, [a.message]) for a in academic]
        groups += [(a.title.replace("Lời nhắc học tập: ", "Môn "), [a.message.split(": ", 1)[-1].capitalize()
                    if a.message.startswith("Môn ") else a.message]) for a in courses]
        subject = " và ".join((["Cảnh báo học tập"] if academic else [])
                              + ([f"{len(courses)} môn cần chú ý"] if courses else []))
        subject = f"[EduAgent] {subject}" if academic else f"[EduAgent] Lời nhắc học tập: {subject}"
    else:
        by_student: dict[int, list[Alert]] = defaultdict(list)
        for a in alerts:
            by_student[a.student_id].append(a)
        groups = []
        for sid, items in by_student.items():
            st = students.get(sid)
            head = f"{st.student_code} {st.full_name} (lớp {st.class_.code})" if st else f"Sinh viên #{sid}"
            lines = [f"{a.title.split(' · ', 1)[-1]}. {a.message}" for a in items]
            groups.append((head, lines))
        role = "lớp chủ nhiệm" if audience == "advisor" else "lớp học phần bạn dạy"
        found = ([f"{len(courses)} lượt môn học"] if courses else []) \
            + ([f"{len({a.student_id for a in academic})} sinh viên thuộc diện cảnh báo học tập"] if academic else [])
        intro = (f"AI Agent vừa phát hiện {len(by_student)} sinh viên thuộc {role} cần chú ý "
                 f"({', '.join(found)}). Sinh viên cũng đã nhận lời nhắc (không kèm xác suất).")
        subject = f"[EduAgent] Cảnh báo sớm: {len(by_student)} sinh viên {role} cần chú ý"
        link = f"{settings.app_base_url}/{'advising' if audience == 'advisor' else 'teaching'}.html"
    return mailer.Mail(to=user.email, subject=subject, text=_text(greeting, intro, groups, link),
                       html=_html(greeting, intro, groups, link), kind="alert", user_id=user.id,
                       audience=audience, n_alerts=len(alerts))


def email_run(run_id: int) -> dict:
    """Gửi email cho các cảnh báo mà lần chạy run_id tạo ra, ghi kết quả vào agent_runs.stats['email']."""
    with SessionV2() as db:
        run = db.get(AgentRun, run_id)
        wanted = audiences(db)
        # Cảnh báo theo môn gắn với dự báo của lần chạy; cảnh báo học tập (không gắn dự báo) mang giờ của lần chạy
        this_run = Prediction.run_id == run_id
        if run is not None:
            this_run = or_(this_run, and_(Alert.prediction_id.is_(None), Alert.created_at == run.started_at))
        rows = db.execute(
            select(Alert, User).outerjoin(Prediction, Prediction.id == Alert.prediction_id)
            .join(User, User.id == Alert.recipient_user_id)
            .where(this_run, Alert.audience.in_(wanted))
            .order_by(Alert.recipient_user_id, Alert.id)
        ).all()
        groups: dict[tuple[int, str], list[Alert]] = defaultdict(list)
        users: dict[int, User] = {}
        for alert, user in rows:
            groups[(user.id, alert.audience)].append(alert)
            users[user.id] = user
        student_ids = {a.student_id for items in groups.values() for a in items}
        students = {s.id: s for s in db.scalars(select(Student).where(Student.id.in_(student_ids)))} \
            if student_ids else {}
        # Sinh viên nào có CVHT nhận email lần này (để báo trong thư gửi sinh viên)
        advised = {a.student_id for (uid, aud), items in groups.items() if aud == "advisor" for a in items}

        mails, unlinked = [], set()
        for (uid, audience), items in groups.items():
            user = users[uid]
            if not (user.is_active and user.email and user.email_verified_at):
                unlinked.add(uid)
                continue
            mail = compose(user, audience, items, students, items[0].student_id in advised)
            mail.run_id = run_id
            mails.append(mail)
        mailer.deliver(db, mails)
        count = defaultdict(int)
        for m in mails:
            count[m.result["status"]] += 1
        stats = {"mode": mailer.mode(), "audiences": wanted, "recipients": len(groups), "emails": len(mails),
                 "sent": count["sent"], "outbox": count["outbox"], "failed": count["failed"],
                 "unlinked": len(unlinked)}
        if run is not None:
            run.stats = {**(run.stats or {}), "email": stats}
        db.commit()
        return stats


def email_run_safe(run_id: int) -> None:
    try:
        stats = email_run(run_id)
        log.info("Email cảnh báo lần chạy %s: %s", run_id, stats)
    except Exception:  # gửi email lỗi không được làm hỏng lần chạy Agent
        log.exception("Gửi email cảnh báo lần chạy %s thất bại", run_id)
