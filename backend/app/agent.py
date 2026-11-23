"""AI Agent: giám sát học kỳ hiện tại và cảnh báo sớm sinh viên có nguy cơ trượt môn (docs/thiet-ke-he-thong.md, mục 6).

Mỗi lần chạy đi qua 5 tầng và ghi lại số liệu từng tầng vào agent_runs.stats (trang AI Agent hiển thị):
  ① Quan sát   xác định mỗi lớp học phần đang ở mốc nào (M0 đầu kỳ, M1 có KT1, M2 có KT2); dữ liệu mới từ lần trước
  ② Luật       các trường hợp chắc chắn theo quy chế: vắng nhiều / quá ngưỡng cấm thi, điểm quá trình thấp,
               đầu kỳ: đang học lại, đang nợ nhiều môn
  ③ Mô hình    xác suất trượt + lý do chính cho từng sinh viên × môn (mô hình train bởi ml/train_dainam.py)
  ④ Báo cáo    tạo cảnh báo cho đúng người: giảng viên bộ môn, CVHT, sinh viên (sinh viên không thấy xác suất)
  ⑤ Theo dõi   so với lần chạy trước: ai cải thiện, ai xấu đi

Agent chỉ đề xuất, không tự xử lý kỷ luật hay sửa điểm.
"""

import sys
import threading
import time
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

import joblib
import pandas as pd
from sqlalchemy import and_, func, insert, select, text
from sqlalchemy.orm import Session

from .config import REPO_ROOT, settings
from .database_v2 import engine_v2
from .models_v2 import AgentRun, Alert, Class, Prediction, Semester, Student
from .services_v2 import current_semester

sys.path.insert(0, str(REPO_ROOT / "ml"))
sys.path.insert(0, str(REPO_ROOT / "ml" / "adapters"))
import dainam  # noqa: E402  (tính đặc trưng: dùng chung với lúc train để không lệch)

MODEL_DIR = settings.models_dir / "dainam"
CHECKPOINTS = ["M0", "M1", "M2"]
CHECKPOINT_LABELS = {"M0": "Đầu kỳ", "M1": "Đã có điểm KT1", "M2": "Đã có điểm KT2"}
LEVEL_RANK = {"low": 0, "medium": 1, "high": 2}
LEVEL_LABELS = {"low": "thấp", "medium": "trung bình", "high": "cao"}
# Yếu tố nêu trong lời nhắc gửi sinh viên (không nêu số môn nợ, độ khó môn... vì sinh viên không đổi được ngay)
STUDENT_ACTIONABLE = {"absence_ratio", "engagement", "recent_engagement", "inactive_days", "process_score",
                      "submission_rate", "score_trend", "late_rate", "sem_kt_mean_others", "sem_att_rate"}


class AgentError(RuntimeError):
    pass


# Một lúc chỉ một lần chạy (quản trị bấm chạy trùng lúc lịch tự chạy)
_running = threading.Lock()
_email_threads: list[threading.Thread] = []


def wait_for_emails(timeout: float = 120) -> None:
    """Chạy từ dòng lệnh: chờ gửi xong email trước khi thoát chương trình."""
    for t in list(_email_threads):
        t.join(timeout)


@lru_cache
def _load_bundle(path: Path, mtime: float) -> dict:
    return joblib.load(path)


def load_bundle(cp: str) -> dict | None:
    path = MODEL_DIR / f"model_{cp}.joblib"
    return _load_bundle(path, path.stat().st_mtime) if path.exists() else None


def warm_up() -> None:
    """Nạp sẵn mô hình 3 mốc vào bộ nhớ (gọi ở luồng nền lúc backend khởi động)."""
    if models_ready():
        for cp in CHECKPOINTS:
            load_bundle(cp)


def models_ready() -> bool:
    return all((MODEL_DIR / f"model_{cp}.joblib").exists() for cp in CHECKPOINTS)


def rule_reasons(cp: str, r: pd.Series, ban_ratio: float) -> list[str]:
    """Lời giải thích cho cột rule_flag của adapter (cùng điều kiện, để trang web và lúc train khớp nhau)."""
    reasons = []
    if cp == "M0":
        if r["prev_attempts"] > 0:
            reasons.append(f"Đang học lại môn này (lần {int(r['attempt_no'])})")
        if r["prior_fail_count"] >= 2:
            reasons.append(f"Đang nợ nhiều môn ({int(r['prior_fail_count'])} môn)")
        return reasons
    absent = round(r["absence_ratio"] * r["total_sessions"])
    if r["absence_ratio"] > ban_ratio:
        reasons.append(f"Vắng quá ngưỡng cấm thi ({absent}/{int(r['total_sessions'])} buổi)")
    elif r["absence_ratio"] >= ban_ratio * 0.75:
        reasons.append(f"Vắng nhiều ({absent}/{int(r['total_sessions'])} buổi)")
    if pd.notna(r["process_score"]) and r["process_score"] < 0.4:
        reasons.append(f"Điểm quá trình thấp ({r['process_score'] * 10:.1f}/10)")
    return reasons


def effective_rank(level: str, source: str) -> int:
    """Mức cần chú ý: AI xếp mức nào thì lấy mức đó; luật bắt mà AI xếp thấp vẫn tính là trung bình."""
    return max(LEVEL_RANK[level], 1 if source in ("rule", "both") else 0)


# ------------------------------------------------------------------ chạy Agent
def run_agent(db: Session, trigger: str = "manual", as_of: datetime | None = None,
              started_by: int | None = None, semester: Semester | None = None) -> AgentRun:
    if not models_ready():
        raise AgentError("Chưa có mô hình cho Agent. Chạy: python ml/train_dainam.py")
    if not _running.acquire(blocking=False):
        raise AgentError("Agent đang chạy, thử lại sau ít giây")
    try:
        run = _run_locked(db, trigger, as_of, started_by, semester)
    finally:
        _running.release()
    # Gửi email cảnh báo ở luồng riêng để trang không phải chờ; chạy lại quá khứ thì không gửi
    if trigger != "replay" and run.status == "success" and run.n_alerts:
        from .notifier import email_run_safe
        thread = threading.Thread(target=email_run_safe, args=(run.id,), daemon=True)
        thread.start()
        _email_threads[:] = [t for t in _email_threads if t.is_alive()] + [thread]
    return run


def _run_locked(db: Session, trigger: str, as_of: datetime | None, started_by: int | None,
                semester: Semester | None) -> AgentRun:
    semester = semester or current_semester(db)
    as_of = as_of or datetime.now()
    stamp = as_of if trigger == "replay" else datetime.now()
    run = AgentRun(trigger_type=trigger, semester_id=semester.id, as_of=as_of, started_by=started_by,
                   started_at=stamp, status="running")
    db.add(run)
    db.commit()
    started = time.time()
    try:
        stats = _run(db, run, semester, as_of, stamp)
        stats["duration_s"] = round(time.time() - started, 1)
        run.stats, run.status, run.finished_at = stats, "success", stamp
        run.n_predictions, run.n_alerts = stats["model"]["predicted"], stats["report"]["alerts"]
        run.message = (f"{stats['model']['predicted']} dự báo, {stats['combined']['flagged']} lượt cần chú ý "
                       f"({stats['combined']['ai']} do AI phát hiện sớm), {stats['report']['alerts']} cảnh báo mới")
        db.commit()
    except Exception as exc:
        db.rollback()
        run = db.get(AgentRun, run.id)
        run.status, run.finished_at, run.message = "failed", datetime.now(), str(exc)[:1000]
        db.commit()
        raise
    return run


def _run(db: Session, run: AgentRun, semester: Semester, as_of: datetime, stamp: datetime) -> dict:
    t = dainam.load_tables(engine_v2)
    ban_ratio = dainam.setting(t, "absence_ban_ratio", 0.2)
    cut = dainam.checkpoint_cutoffs(t)
    enr = t["enr"][(t["enr"]["semester_id"] == semester.id) & (t["enr"]["status"] == "studying")]
    if enr.empty:
        raise AgentError(f"Học kỳ {semester.code} không có sinh viên đang học")

    # ① Quan sát
    section_cp = {sid: dainam.current_checkpoint(cut.loc[sid], as_of) for sid in enr["section_id"].unique()}
    prev_run = db.scalar(select(AgentRun).where(AgentRun.semester_id == semester.id, AgentRun.status == "success",
                                                AgentRun.id != run.id, AgentRun.as_of < as_of)
                         .order_by(AgentRun.as_of.desc()))
    since = prev_run.as_of if prev_run else pd.Timestamp(semester.start_date)
    ids = set(enr["enrollment_id"])
    g, a = t["grades"], t["attendance"]
    observe = {
        "sections": len(section_cp), "enrollments": len(enr),
        "by_checkpoint": {cp: sum(1 for v in section_cp.values() if v == cp) for cp in CHECKPOINTS},
        "new_grades": int(((g["entered_at"] > since) & (g["entered_at"] <= as_of) & g["enrollment_id"].isin(ids)).sum()),
        "new_attendance": int(((a["session_date"] > since) & (a["session_date"] <= as_of)
                               & a["enrollment_id"].isin(ids)).sum()),
        "since": since.isoformat(timespec="minutes") if hasattr(since, "isoformat") else str(since),
    }

    # ②③ Luật + mô hình, theo từng mốc (mỗi mốc một mô hình)
    frames, models = [], {}
    for cp in CHECKPOINTS:
        rows = enr[enr["section_id"].map(section_cp) == cp]
        if rows.empty:
            continue
        b = load_bundle(cp)
        df = dainam.build_features(t, cp, rows, pd.Series(pd.Timestamp(as_of), index=rows["enrollment_id"]))
        X = df[b["features"]]
        df["proba"] = b["pipeline"].predict_proba(X)[:, 1]
        df["factors"] = dainam.explain(b["pipeline"], X, b["reference"])
        thr = b["thresholds"]
        df["level"] = ["high" if p >= thr["high"] else "medium" if p >= thr["alert"] else "low" for p in df["proba"]]
        df["model_name"], df["model_version"] = b["model_name"], b["trained_at"][:16]
        df["reasons"] = [rule_reasons(cp, r, ban_ratio) for _, r in df.iterrows()]
        models[cp] = {"model": b["model_name"], "feature_set": b["feature_set"], "trained_at": b["trained_at"],
                      "alert": round(thr["alert"], 3), "high": round(thr["high"], 3), "n": len(df)}
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    ai = df["level"] != "low"
    rule = df["rule_flag"] == 1
    df["source"] = ["both" if x and y else "ai" if x else "rule" if y else "none" for x, y in zip(ai, rule)]

    reason_counts: dict[str, int] = {}
    for reasons in df["reasons"]:
        for reason in reasons:
            key = reason.split(" (")[0]
            reason_counts[key] = reason_counts.get(key, 0) + 1

    # ⑤ Theo dõi: dự báo gần nhất trước lần chạy này của từng lượt học
    enrollment_ids = [int(e) for e in df["enrollment_id"]]
    latest = (select(Prediction.enrollment_id, func.max(Prediction.created_at).label("at"))
              .where(Prediction.enrollment_id.in_(enrollment_ids), Prediction.created_at < stamp)
              .group_by(Prediction.enrollment_id).subquery())
    prev = {p.enrollment_id: p for p in db.scalars(
        select(Prediction).join(latest, and_(Prediction.enrollment_id == latest.c.enrollment_id,
                                             Prediction.created_at == latest.c.at))
        .order_by(Prediction.id)).all()}
    follow = {"compared": 0, "improved": 0, "worse": 0, "same": 0}
    for _, r in df.iterrows():
        p = prev.get(r["enrollment_id"])
        if p is None:
            continue
        before, now = effective_rank(p.risk_level, p.flag_source), effective_rank(r["level"], r["source"])
        follow["compared"] += 1
        follow["improved" if now < before else "worse" if now > before else "same"] += 1

    db.execute(insert(Prediction), [
        dict(run_id=run.id, enrollment_id=int(r["enrollment_id"]), checkpoint=r["checkpoint"],
             model_name=r["model_name"], model_version=r["model_version"],
             risk_probability=round(float(r["proba"]), 4), risk_level=r["level"], flag_source=r["source"],
             rule_flags=r["reasons"], top_factors=r["factors"], created_at=stamp)
        for _, r in df.iterrows()])
    pred_ids = dict(db.execute(select(Prediction.enrollment_id, Prediction.id)
                               .where(Prediction.run_id == run.id)).all())

    # ④ Báo cáo: chỉ báo khi lượt học mới cần chú ý, mức tăng lên, hoặc sang mốc mới mà vẫn cần chú ý
    people = _people(db, semester.id)
    alerts, audience_counts = [], {"lecturer": 0, "advisor": 0, "student": 0}
    for _, r in df.iterrows():
        if r["source"] == "none":
            continue
        p = prev.get(r["enrollment_id"])
        now = effective_rank(r["level"], r["source"])
        # Mốc lùi lại (vd giảng viên xóa điểm KT2 vừa nhập) không tính là mốc mới
        if p is not None and p.flag_source != "none" \
                and CHECKPOINTS.index(p.checkpoint) >= CHECKPOINTS.index(r["checkpoint"]) \
                and effective_rank(p.risk_level, p.flag_source) >= now:
            continue
        info = people.get(int(r["enrollment_id"]))
        if info is None:
            continue
        for audience, user_id, title, message in _messages(r, info):
            if user_id is None:
                continue
            # Mọi cảnh báo đều tới sinh viên và CVHT (giáo viên chủ nhiệm). Đầu kỳ chưa có điểm môn này nên
            # giảng viên bộ môn chỉ nhận khi nguy cơ cao.
            if r["checkpoint"] == "M0" and audience == "lecturer" and r["level"] != "high":
                continue
            level = "danger" if now == 2 or any(x.startswith("Vắng quá") for x in r["reasons"]) else "warning"
            alerts.append(Alert(prediction_id=pred_ids[int(r["enrollment_id"])], student_id=info["student_id"],
                                enrollment_id=int(r["enrollment_id"]), recipient_user_id=user_id,
                                audience=audience, channel="in_app", level=level, title=title[:200],
                                message=message, status="sent", created_at=stamp, sent_at=stamp))
            audience_counts[audience] += 1
    course_alerts = len(alerts)
    # ④b Cảnh báo học tập (học vụ). Chạy lại quá khứ thì bỏ qua: tổng kết học kỳ tính theo dữ liệu hiện tại
    academic = _academic_alerts(db, people, stamp) if run.trigger_type != "replay" else []
    for a in academic:
        audience_counts[a.audience] += 1
    alerts += academic
    db.add_all(alerts)

    flagged = df[df["source"] != "none"]
    return {
        "semester": semester.code, "as_of": as_of.isoformat(timespec="minutes"),
        "observe": observe,
        "rules": {"flagged": int(rule.sum()), "by_reason": dict(sorted(reason_counts.items(), key=lambda x: -x[1]))},
        "model": {"predicted": len(df), "flagged": int(ai.sum()), "high": int((df["level"] == "high").sum()),
                  "medium": int((df["level"] == "medium").sum()), "models": models},
        "combined": {"flagged": len(flagged), "both": int((df["source"] == "both").sum()),
                     "rule": int((df["source"] == "rule").sum()), "ai": int((df["source"] == "ai").sum()),
                     "students": int(flagged["student_id"].nunique())},
        "report": {"alerts": len(alerts), **audience_counts,
                   "enrollments": len({a.enrollment_id for a in alerts[:course_alerts]}),
                   "academic_students": len({a.student_id for a in academic})},
        "follow": follow,
    }


def _people(db: Session, semester_id: int) -> dict[int, dict]:
    """Ai cần nhận cảnh báo của từng lượt học: giảng viên bộ môn, CVHT của lớp hành chính, chính sinh viên."""
    sql = text("""
        SELECT e.id AS enrollment_id, st.id AS student_id, st.student_code, st.full_name, st.user_id AS student_user,
               c.code AS course_code, c.name AS course_name, lu.id AS lecturer_user, au.id AS advisor_user
        FROM enrollments e
        JOIN students st ON st.id = e.student_id
        JOIN course_sections cs ON cs.id = e.section_id
        JOIN courses c ON c.id = cs.course_id
        LEFT JOIN lecturers l ON l.id = cs.lecturer_id
        LEFT JOIN users lu ON lu.id = l.user_id
        JOIN classes cl ON cl.id = st.class_id
        LEFT JOIN lecturers al ON al.id = cl.advisor_id
        LEFT JOIN users au ON au.id = al.user_id
        WHERE cs.semester_id = :sid""")
    return {row.enrollment_id: dict(row._mapping) for row in db.execute(sql, {"sid": semester_id})}


def _gpa(value: float | None) -> str:
    return "chưa có" if value is None else f"{value:.2f}"


def _academic_alerts(db: Session, people: dict[int, dict], stamp: datetime) -> list[Alert]:
    """Sinh viên mới thuộc diện cảnh báo học tập (ĐTB học kỳ, ĐTB tích lũy thấp, nợ quá số tín chỉ) ở học kỳ có điểm
    tổng kết gần nhất: báo cho sinh viên và CVHT, mỗi học kỳ một lần. Cùng cách tính với trang Kết quả học tập."""
    from .routers.dashboard import _history  # import trong hàm để tránh vòng import (dashboard dùng agent)

    students: dict[int, dict] = {}
    for info in people.values():
        students.setdefault(info["student_id"], info)
    if not students:
        return []
    cohorts = dict(db.execute(select(Student.id, Class.cohort).join(Class, Class.id == Student.class_id)
                              .where(Student.id.in_(students))).all())
    _, latest = _history(db, {sid: {"cohort": cohorts[sid]} for sid in students})
    # Đã báo rồi (cùng sinh viên, người nhận, học kỳ) thì thôi: tiêu đề có tên học kỳ nên dùng làm khóa
    sent = set(db.execute(select(Alert.student_id, Alert.audience, Alert.title)
                          .where(Alert.enrollment_id.is_(None), Alert.prediction_id.is_(None))).all())
    out = []
    for sid, s in latest.items():
        if not s["warning"]["is_warned"]:
            continue
        info, semester, reasons = students[sid], s["semester"], "; ".join(s["warning"]["reasons"])
        staff_msg = (f"Lý do: {reasons}. ĐTB học kỳ {_gpa(s['gpa4'])}, "
                     f"ĐTB tích lũy {_gpa(s['cum_gpa4'])} (hệ 4), đang nợ {s['owed_credits']} tín chỉ. "
                     "Nên gặp sinh viên để lập kế hoạch học tập cho các học kỳ tới.")
        student_msg = (f"Bạn thuộc diện cảnh báo học tập {semester} ({reasons}). Hãy gặp cố vấn học tập (giáo viên "
                       "chủ nhiệm) để lập kế hoạch cải thiện kết quả và đăng ký học lại các môn chưa đạt.")
        for audience, user_id, title, message in (
                ("advisor", info["advisor_user"], f"{info['student_code']} {info['full_name']} · "
                                                  f"Cảnh báo học tập {semester}", staff_msg),
                ("student", info["student_user"], f"Cảnh báo học tập {semester}", student_msg)):
            if user_id is None or (sid, audience, title[:200]) in sent:
                continue
            out.append(Alert(prediction_id=None, student_id=sid, enrollment_id=None, recipient_user_id=user_id,
                             audience=audience, channel="in_app", level="danger", title=title[:200],
                             message=message, status="sent", created_at=stamp, sent_at=stamp))
    return out


def _factor_text(factors: list[dict]) -> str:
    return "; ".join(f"{f['label']}: {f['value']} (thường gặp {f['typical']})" for f in factors)


def _messages(r: pd.Series, info: dict) -> list[tuple[str, int | None, str, str]]:
    who = f"{info['student_code']} {info['full_name']}"
    course = f"{info['course_code']} {info['course_name']}"
    head = f"Mốc {r['checkpoint']} ({CHECKPOINT_LABELS[r['checkpoint']][0].lower()}{CHECKPOINT_LABELS[r['checkpoint']][1:]})."
    parts = [head]
    if r["level"] != "low":
        parts.append(f"AI ước tính khả năng trượt {r['proba']:.0%} (mức {LEVEL_LABELS[r['level']]}).")
        if r["factors"]:
            parts.append("Lý do chính: " + _factor_text(r["factors"]) + ".")
    if r["reasons"]:
        parts.append("Luật quy chế: " + "; ".join(r["reasons"]) + ".")
    if r["source"] == "ai":
        parts.append("Sinh viên chưa vi phạm luật nào: đây là cảnh báo sớm của AI, nên trao đổi trước khi muộn.")
    staff_msg = " ".join(parts)
    label = LEVEL_LABELS[r["level"]] if r["level"] != "low" else "cần chú ý"
    title = f"{who} · {course}: nguy cơ {label}" if r["level"] != "low" else f"{who} · {course}: {r['reasons'][0]}"

    # Sinh viên: lời nhắc, không hiện xác suất; chỉ nêu điều sinh viên tự cải thiện được (đi học, làm bài kiểm tra)
    hints = list(r["reasons"])
    if not hints:
        hints = [f"{f['label'][0].lower()}{f['label'][1:]}: {f['value']}" for f in r["factors"]
                 if f["feature"] in STUDENT_ACTIONABLE][:2] or ["kết quả học tập kỳ này có dấu hiệu đi xuống"]
    student_msg = (f"Môn {course}: hệ thống nhận thấy bạn cần chú ý ({'; '.join(hints)}). "
                   "Hãy đi học đầy đủ, làm đủ bài kiểm tra và trao đổi với giảng viên hoặc cố vấn học tập nếu gặp khó khăn.")
    return [
        ("lecturer", info["lecturer_user"], title, staff_msg),
        ("advisor", info["advisor_user"], title, staff_msg),
        ("student", info["student_user"], f"Lời nhắc học tập: {course}", student_msg),
    ]


def latest_predictions(db: Session, enrollment_ids: list[int]) -> dict[int, Prediction]:
    """Dự báo của lần chạy gần nhất (học kỳ hiện tại) cho các lượt học, để trang giảng viên / CVHT hiển thị."""
    semester = current_semester(db)
    run_id = db.scalar(select(AgentRun.id).where(AgentRun.semester_id == semester.id, AgentRun.status == "success")
                       .order_by(AgentRun.as_of.desc(), AgentRun.id.desc()))
    if run_id is None or not enrollment_ids:
        return {}
    rows = db.scalars(select(Prediction).where(Prediction.run_id == run_id,
                                               Prediction.enrollment_id.in_(enrollment_ids))).all()
    return {p.enrollment_id: p for p in rows}


def prediction_out(p: Prediction | None) -> dict | None:
    if p is None:
        return None
    return {"proba": p.risk_probability, "level": p.risk_level, "source": p.flag_source, "checkpoint": p.checkpoint,
            "factors": p.top_factors or [], "rule_flags": p.rule_flags or []}


def bootstrap(db: Session) -> list[AgentRun]:
    """Lần đầu: chạy lại tại ngày đầu học kỳ (để có mốc so sánh cho tầng ⑤), rồi chạy cho hôm nay."""
    semester = current_semester(db)
    has_run = db.scalar(select(func.count()).select_from(AgentRun)
                        .where(AgentRun.semester_id == semester.id, AgentRun.status == "success"))
    if has_run:
        return []
    start = datetime.combine(semester.start_date, datetime.min.time()) + timedelta(hours=7)
    runs = [run_agent(db, "replay", as_of=start, semester=semester)]
    runs.append(run_agent(db, "schedule", semester=semester))
    return runs
