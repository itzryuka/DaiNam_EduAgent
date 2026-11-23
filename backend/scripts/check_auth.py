"""Kiểm tra API đăng nhập và phân quyền trên backend đang chạy (http://127.0.0.1:8000).

Chạy sau mỗi lần sửa backend:  python backend/scripts/check_auth.py
Cần: backend đang chạy (start.bat), CSDL eduagent_v2 có dữ liệu demo (database/seed_demo_v2.py).
Lưu ý: bước cuối cố tình nhập sai mật khẩu gv011 5 lần, tài khoản đó bị tạm khóa 5 phút (trong bộ nhớ backend).
"""

import json
import sys
import time
import urllib.error
import urllib.request

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "database"))
sys.path.insert(0, str(ROOT / "backend"))
from seed_demo_v2 import DEMO_PASSWORD  # noqa: E402

BASE = "http://127.0.0.1:8000/api"


def call(method, path, body=None, token=None):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json",
                                          **({"Authorization": f"Bearer {token}"} if token else {})})
    try:
        # Chạy Agent (POST /agent/run) mất khoảng 6–10 giây trên dữ liệu demo; để dư thời gian cho máy chậm
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read()
            return r.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


for _ in range(40):
    try:
        if call("GET", "/health")[0] == 200:
            break
    except Exception:
        time.sleep(0.5)

results = []


def check(name, cond, extra=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))


def login(username, password=DEMO_PASSWORD):
    return call("POST", "/auth/login", {"username": username, "password": password})


st, _ = call("GET", "/dashboard")
check("Chưa đăng nhập -> 401", st == 401, st)
st, body = login("gv001", "sai-mat-khau")
check("Sai mật khẩu -> 401", st == 401, body)
st, body = login("khong-ton-tai")
check("Sai tên đăng nhập -> 401 (cùng thông báo)", st == 401, body)

tokens = {}
for user in ("admin", "gv003", "1871020001"):
    st, body = login(user)
    check(f"Đăng nhập {user}", st == 200, f"{body['user']['role_label'] if st == 200 else body}")
    tokens[user] = body["access_token"] if st == 200 else None

admin, lec, stu = tokens["admin"], tokens["gv003"], tokens["1871020001"]
st, me = call("GET", "/auth/me", token=lec)
check("GV003 là CVHT", st == 200 and me["advised_classes"], me.get("advised_classes"))

# Sinh viên
st, body = call("GET", "/me/results", token=stu)
check("SV xem kết quả của mình", st == 200, f"{len(body['semesters'])} kỳ, TBC tích lũy {body['cumulative']['gpa4']}"
      if st == 200 else body)
st, body = call("GET", "/me/attendance", token=stu)
check("SV xem điểm danh", st == 200, f"{len(body['courses'])} môn" if st == 200 else body)
for path in ("/dashboard", "/manage/students", "/teaching/sections", "/admin/users", "/advising/students",
             "/experiments/latest"):
    st, _ = call("GET", path, token=stu)
    check(f"SV bị chặn {path}", st == 403, st)

# Giảng viên
st, secs = call("GET", "/teaching/sections", token=lec)
check("GV xem lớp mình dạy", st == 200 and len(secs) > 0, f"{len(secs)} lớp" if st == 200 else secs)
st, detail = call("GET", f"/teaching/sections/{secs[0]['id']}", token=lec)
flagged = sum(1 for r in detail["students"] if r["flags"]) if st == 200 else 0
check("GV xem chi tiết lớp", st == 200, f"{len(detail['students'])} SV, {flagged} cần chú ý" if st == 200 else detail)
st, all_secs = call("GET", "/teaching/sections", token=admin)
other = next(s for s in all_secs if s["id"] not in {x["id"] for x in secs})
st, _ = call("GET", f"/teaching/sections/{other['id']}", token=lec)
other_sec = other["id"]
check("GV bị chặn lớp người khác", st == 403, st)
st, adv = call("GET", "/advising/students", token=lec)
check("CVHT xem lớp chủ nhiệm", st == 200, f"{adv['classes']}, {len(adv['students'])} SV" if st == 200 else adv)
st, _ = call("GET", "/admin/users", token=lec)
check("GV bị chặn trang quản trị", st == 403, st)
st, _ = call("GET", "/experiments/latest", token=lec)
check("GV xem kết quả train mô hình", st in (200, 404), st)
# API của bản prototype (CSDL eduagent) đã gỡ ở giai đoạn 5
for path in ("/stats/overview", "/students", "/classes"):
    st, _ = call("GET", path, token=admin)
    check(f"API prototype đã gỡ: {path}", st in (404, 405), st)
st, health = call("GET", "/health")
check("/api/health chỉ dùng CSDL v2", st == 200 and health["database"] == "ok" and "database_v2" not in health,
      health)

# Quản trị
st, users = call("GET", "/admin/users?role=lecturer", token=admin)
check("Admin xem tài khoản", st == 200, f"{users['total']} GV, đếm {users['counts']}" if st == 200 else users)
target = next(u for u in users["items"] if u["username"] == "gv012")
st, _ = call("PATCH", f"/admin/users/{target['id']}", {"is_active": False}, token=admin)
st2, body = login("gv012")
check("Khóa tài khoản -> không đăng nhập được", st == 200 and st2 == 403, body)
call("PATCH", f"/admin/users/{target['id']}", {"is_active": True}, token=admin)
st, _ = login("gv012")
check("Mở khóa -> đăng nhập lại được", st == 200, st)
st, me_admin = call("GET", "/auth/me", token=admin)
st, body = call("PATCH", f"/admin/users/{me_admin['id']}", {"is_active": False}, token=admin)
check("Admin không tự khóa mình", st == 400, body)

# Token giả / hỏng
st, _ = call("GET", "/auth/me", token=admin[:-4] + "abcd")
check("Token bị sửa -> 401", st == 401, st)

# AI Agent
for path in ("/agent/overview", "/agent/predictions", "/agent/backtest", "/agent/runs"):
    st, _ = call("GET", path, token=stu)
    check(f"SV bị chặn {path}", st == 403, st)
st, _ = call("POST", "/agent/run", token=lec)
check("GV không được tự chạy Agent", st == 403, st)
st, preds = call("GET", "/agent/predictions?only_flagged=false&limit=2000", token=lec)
mine = {s["id"] for s in secs}
advised = set(me["advised_classes"]) if isinstance(me["advised_classes"][0], str) else \
    {c["code"] for c in me["advised_classes"]}
outside = [p for p in preds["items"] if p["section_id"] not in mine and p["class_code"] not in advised] if st == 200 else [1]
check("GV chỉ thấy dự báo lớp mình dạy / lớp chủ nhiệm", st == 200 and not outside,
      f"{len(preds['items'])} lượt, ngoài phạm vi {len(outside)}" if st == 200 else st)
st, overview = call("GET", "/agent/overview", token=admin)
check("Admin xem tổng quan Agent", st == 200 and overview["run"], overview.get("run", {}).get("message") if st == 200 else st)
st, run = call("POST", "/agent/run", token=admin)
check("Admin chạy Agent", st == 200 and run["status"] == "success", run.get("message") if st == 200 else run)
student_with_alerts = "1771020073"  # sinh viên demo có lời nhắc từ Agent
st, body = login(student_with_alerts)
stu2 = body["access_token"] if st == 200 else stu
st, mine_alerts = call("GET", "/alerts/mine", token=stu2)
leak = [a for a in mine_alerts["items"] if "khả năng trượt" in a["message"]] if st == 200 else []
check("SV xem lời nhắc của mình, không lộ xác suất", st == 200 and not leak,
      f"{len(mine_alerts['items'])} lời nhắc" if st == 200 else st)
if st == 200 and mine_alerts["items"]:
    st2, _ = call("POST", f"/alerts/{mine_alerts['items'][0]['id']}/read", token=lec)
    check("Không đánh dấu được cảnh báo của người khác", st2 == 404, st2)

# Liên kết email, lịch sử email
st, acc = call("GET", "/account", token=stu)
check("SV xem tài khoản của mình", st == 200 and acc["user"]["username"] == "1871020001", st)
st, body = call("POST", "/account/email/request", {"email": "khong-hop-le"}, token=stu)
check("Email sai định dạng -> 400", st == 400, body)
other = call("GET", "/admin/users?email=linked&role=student", token=admin)[1]["items"]
other = next((u for u in other if u["username"] != "1871020001"), None)
if other:
    st, body = call("POST", "/account/email/request", {"email": other["email"]}, token=stu)
    check("Email đã thuộc tài khoản khác -> 409", st == 409, body)
st, sent = call("POST", "/account/email/request", {"email": f"1871020001.{int(time.time())}@example.edu.vn"}, token=stu)
check("Gửi mã xác nhận (hoặc bị giới hạn 1 phút/lần)", st in (200, 429), sent)
if st == 200 and sent.get("dev_code"):
    wrong = "000000" if sent["dev_code"] != "000000" else "111111"
    st, body = call("POST", "/account/email/verify", {"code": wrong}, token=stu)
    check("Nhập sai mã -> 400", st == 400, body)
    st, body = call("POST", "/account/email/verify", {"code": sent["dev_code"]}, token=stu)
    check("Nhập đúng mã -> đã liên kết", st == 200 and body["email_verified"], body)
st, mails = call("GET", "/emails?limit=200", token=stu)
check("SV chỉ thấy email gửi tới mình", st == 200 and all(m["user"]["username"] == "1871020001" for m in mails["items"]),
      f"{mails['total']} email" if st == 200 else st)
check("Lịch sử email không lộ mã xác nhận", st == 200 and all(
    m["kind"] != "verify" or not any(c.isdigit() for c in m["subject"] + m["body"].split("là:")[-1][:12])
    for m in mails["items"]))
st, _ = call("GET", "/emails/config", token=lec)
check("GV bị chặn cấu hình email", st == 403, st)
st, conf = call("GET", "/emails/config", token=admin)
check("Admin xem cấu hình email", st == 200, conf.get("mail", {}).get("mode") if st == 200 else conf)
st, conf2 = call("PUT", "/emails/config", {"audiences": conf["audiences"], "agent_auto": conf["agent"]["auto"]}, token=admin)
check("Admin lưu cấu hình email", st == 200 and conf2["audiences"] == conf["audiences"], st)
st, body = call("PATCH", f"/admin/users/{target['id']}", {"email": "sai@@"}, token=admin)
check("Admin gán email sai định dạng -> 400", st == 400, body)

# Quản lý sinh viên (giai đoạn 3). Không tạo sinh viên thật: chỉ thử trùng mã, quyền, import chạy thử.
st, _ = call("GET", "/manage/students", token=stu)
check("SV bị chặn quản lý sinh viên", st == 403, st)
st, opts = call("GET", "/manage/options", token=admin)
check("Admin xem danh mục lớp", st == 200 and opts["can_edit"] and opts["classes"], st)
st, lst = call("GET", "/manage/students?limit=5", token=admin)
check("Admin xem danh sách sinh viên", st == 200 and lst["total"] > 0, f"{lst['total']} SV, {lst['counts']}" if st == 200 else lst)
st, lec_list = call("GET", "/manage/students?limit=500", token=lec)
check("CVHT chỉ thấy sinh viên lớp chủ nhiệm", st == 200 and all(r["class_code"] in advised for r in lec_list["items"]),
      f"{lec_list['total']} SV" if st == 200 else st)
st, prof = call("GET", f"/manage/students/{lst['items'][0]['id']}", token=admin)
check("Admin xem hồ sơ sinh viên", st == 200 and "results" in prof, st)
# GV xem được hồ sơ SV lớp chủ nhiệm hoặc SV từng học lớp mình dạy (kỳ nào cũng được); còn lại bị chặn
taught = {r["student_id"] for sec in secs for r in call("GET", f"/teaching/sections/{sec['id']}", token=lec)[1]["students"]}
others = [r for r in call("GET", "/manage/students?limit=500", token=admin)[1]["items"]
          if r["class_code"] not in advised and r["id"] not in taught][:60]
codes = [call("GET", f"/manage/students/{r['id']}", token=lec)[0] for r in others]
check("GV bị chặn hồ sơ sinh viên chưa từng dạy", codes.count(403) > 0 and set(codes) <= {200, 403},
      f"{codes.count(403)} chặn, {codes.count(200)} từng dạy kỳ trước")
existing = lst["items"][0]
new_row = {"student_code": existing["student_code"], "full_name": "Thử Trùng Mã", "class_id": existing["class_id"]}
st, _ = call("POST", "/manage/students", new_row, token=lec)
check("GV không được thêm sinh viên", st == 403, st)
st, body = call("POST", "/manage/students", new_row, token=admin)
check("Thêm sinh viên trùng mã -> 409", st == 409, body)
st, body = call("PATCH", f"/manage/students/{existing['id']}", {"status": "bay-mau"}, token=admin)
check("Trạng thái không hợp lệ -> 422", st == 422, st)
st, imp = call("POST", "/manage/students/import", {"dry_run": True, "rows": [
    {"Mã SV": existing["student_code"], "Họ tên": existing["full_name"], "Lớp": existing["class_code"]},
    {"Mã SV": "9999999999", "Họ tên": "Sinh Viên Thử", "Lớp": existing["class_code"]},
    {"Mã SV": "9999999998", "Họ tên": "Lớp Sai", "Lớp": "KHONG-CO-LOP"},
    {"Mã SV": "SVTHU9997", "Họ tên": "Mã Có Chữ", "Lớp": existing["class_code"]}]}, token=admin)
check("Import chạy thử phân loại đúng dòng (mã có chữ cái bị từ chối)",
      st == 200 and imp["summary"]["create"] == 1 and imp["summary"]["error"] == 2
      and not imp["credentials"], imp.get("summary") if st == 200 else imp)
st, body = call("POST", "/manage/students/import", {"dry_run": False, "rows": [
    {"Mã SV": "9999999998", "Họ tên": "Lớp Sai", "Lớp": "KHONG-CO-LOP"}]}, token=admin)
check("Import có dòng lỗi -> 400, không ghi gì", st == 400, body)

# Nhập điểm, điểm danh trên web (giai đoạn 3). Sửa rồi trả lại như cũ (nhật ký vẫn ghi lại).
sec_id = secs[0]["id"]
st, detail = call("GET", f"/teaching/sections/{sec_id}", token=lec)
row = next(r for r in detail["students"] if r["status"] != "withdrawn")
comp = next(c["code"] for c in detail["components"] if not c["is_exam"])
old = row["scores"].get(comp)
new = 7.5 if old != 7.5 else 8.0
st, body = call("PUT", f"/teaching/sections/{sec_id}/grades",
                {"items": [{"enrollment_id": row["enrollment_id"], "component": comp, "score": new}]}, token=lec)
check("GV nhập điểm lớp mình", st == 200 and body["changed"] == 1, body if st != 200 else f"{comp}: {old} -> {new}")
st, log = call("GET", f"/teaching/sections/{sec_id}/grade-log", token=lec)
check("Nhật ký sửa điểm ghi lại lần sửa", st == 200 and log and log[0]["new"] == new
      and log[0]["student_code"] == row["student_code"], log[:1] if st == 200 else st)
st, _ = call("PUT", f"/teaching/sections/{sec_id}/grades",
             {"items": [{"enrollment_id": row["enrollment_id"], "component": comp, "score": old}]}, token=lec)
check("Trả điểm về như cũ", st == 200, st)
st, body = call("PUT", f"/teaching/sections/{sec_id}/grades",
                {"items": [{"enrollment_id": row["enrollment_id"], "component": comp, "score": 11}]}, token=lec)
check("Điểm ngoài 0–10 -> 422", st == 422, st)
st, _ = call("PUT", f"/teaching/sections/{other_sec}/grades",
             {"items": [{"enrollment_id": row["enrollment_id"], "component": comp, "score": 5}]}, token=lec)
check("GV không nhập điểm lớp người khác", st == 403, st)
st, _ = call("PUT", f"/teaching/sections/{sec_id}/grades",
             {"items": [{"enrollment_id": row["enrollment_id"], "component": comp, "score": 5}]}, token=stu)
check("SV không nhập điểm được", st == 403, st)
st, sess = call("GET", f"/teaching/sections/{sec_id}/sessions", token=lec)
done = [x for x in sess["sessions"] if x["recorded"] and not x["upcoming"]] if st == 200 else []
future = [x for x in sess["sessions"] if x["upcoming"]] if st == 200 else []
check("GV xem danh sách buổi học", st == 200 and sess["sessions"], f"{len(done)} buổi đã điểm danh" if st == 200 else st)
if done:
    st, att = call("GET", f"/teaching/sections/{sec_id}/sessions/{done[-1]['id']}", token=lec)
    first = att["students"][0]
    flip = "late" if first["status"] != "late" else "present"
    st, body = call("PUT", f"/teaching/sections/{sec_id}/sessions/{done[-1]['id']}",
                    {"items": [{"enrollment_id": first["enrollment_id"], "status": flip}]}, token=lec)
    saved = next((x["status"] for x in body["students"] if x["enrollment_id"] == first["enrollment_id"]), None) \
        if st == 200 else None
    check("GV sửa điểm danh một buổi", st == 200 and saved == flip, st)
    if first["status"]:
        call("PUT", f"/teaching/sections/{sec_id}/sessions/{done[-1]['id']}",
             {"items": [{"enrollment_id": first["enrollment_id"], "status": first["status"]}]}, token=lec)
if future:
    st, _ = call("PUT", f"/teaching/sections/{sec_id}/sessions/{future[0]['id']}",
                 {"items": [{"enrollment_id": row["enrollment_id"], "status": "present"}]}, token=lec)
    check("Không điểm danh trước buổi học chưa tới -> 400", st == 400, st)

# Tổng quan trên CSDL v2 (giai đoạn 4): số liệu khớp với trang Sinh viên, giảng viên chỉ thấy phạm vi của mình
st, _ = call("GET", "/dashboard", token=stu)
check("SV bị chặn trang Tổng quan", st == 403, st)
st, dash = call("GET", "/dashboard", token=admin)
check("Admin xem Tổng quan toàn trường", st == 200 and dash["scope"] == "Toàn trường",
      f"{dash['cards']['students']} SV, {dash['cards']['flagged_students']} cần chú ý" if st == 200 else dash)
if st == 200:
    by_risk = {k: call("GET", f"/manage/students?risk={k}&limit=1", token=admin)[1]["total"] for k in ("flagged", "high", "ai")}
    c = dash["cards"]
    check("Số cần chú ý / nguy cơ cao / AI khớp trang Sinh viên",
          (c["flagged_students"], c["high_students"], c["ai_students"]) == (by_risk["flagged"], by_risk["high"], by_risk["ai"]),
          f"{(c['flagged_students'], c['high_students'], c['ai_students'])} vs {tuple(by_risk.values())}")
    check("Biểu đồ theo lớp cộng đủ số sinh viên",
          sum(r["total"] for r in dash["risk_by_class"]) == c["students"]
          and all(r["high"] + r["ai"] + r["rule"] + r["none"] == r["total"] for r in dash["risk_by_class"]))
    check("Xếp loại cộng không vượt số sinh viên", sum(r["n"] for r in dash["ranks"]) <= c["students"])
st, dash_lec = call("GET", "/dashboard", token=lec)
taught_codes = {r["student_code"] for sec in secs for r in call("GET", f"/teaching/sections/{sec['id']}", token=lec)[1]["students"]}
check("GV xem Tổng quan trong phạm vi của mình",
      st == 200 and dash_lec["cards"]["students"] < dash["cards"]["students"]
      and all(t["class_code"] in advised or t["student_code"] in taught_codes for t in dash_lec["top_students"]),
      f"{dash_lec['cards']['students']} SV" if st == 200 else st)

# Chống dò mật khẩu
for _ in range(5):
    login("gv011", "sai")
st, body = login("gv011")
check("Sai 5 lần -> tạm khóa (429) kể cả khi nhập đúng", st == 429, body)

print(f"\n{sum(results)}/{len(results)} kiểm tra đạt")
