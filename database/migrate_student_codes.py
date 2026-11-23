"""Đổi mã sinh viên demo cũ (SV170001) sang mã 10 chữ số giống Đại Nam (1771020001), GIỮ NGUYÊN mọi dữ liệu.

    python database/migrate_student_codes.py           # xem trước sẽ đổi những gì
    python database/migrate_student_codes.py --apply   # đổi thật

Dùng cho máy đã sinh dữ liệu demo trước khi đổi cách đặt mã. Mã mới giống hệt khi chạy lại seed_demo_v2.py:
khóa + mã ngành rút gọn (CNTT 7102, KHMT 7101) + số thứ tự trong khóa và ngành.
Đổi tên đăng nhập (users.username), mã sinh viên (students.student_code) và email demo dạng sv170001@example.edu.vn.
Mã cũ còn nằm trong chữ đã lưu từ trước (tiêu đề / nội dung cảnh báo, email đã gửi, nhật ký sửa điểm) cũng được
thay bằng mã mới, để mọi nơi chỉ còn mã toàn số.
Chạy lại nhiều lần vẫn an toàn: chỉ đổi các mã còn dạng cũ.
"""

import argparse
import re
import sys
from pathlib import Path

import pymysql

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "database"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.config import settings  # noqa: E402
from seed_demo_v2 import STUDENT_CODE_MAJOR  # noqa: E402

OLD = re.compile(r"^SV(\d{2})(\d{4})$")
OLD_IN_TEXT = re.compile(r"\b[Ss][Vv](\d{2})(\d{4})\b")  # SV170005 trong tiêu đề, sv170005@... trong email
# Các cột chữ có thể còn mã cũ (dữ liệu lịch sử)
HISTORY_COLUMNS = [("alerts", "title"), ("alerts", "message"), ("email_logs", "to_email"), ("email_logs", "subject"),
                   ("email_logs", "body"), ("audit_logs", "old_value"), ("audit_logs", "new_value")]
MAJOR_BY_CODE = {"7480201": "CNTT", "7480101": "KHMT"}  # mã ngành trong bảng majors -> tên rút gọn


def history_mapping(cur, exact: dict[str, str]) -> dict[str, str]:
    """Mã cũ -> mã mới. Lúc đổi mã thì lấy đúng bảng vừa đổi; máy đã đổi từ trước thì suy lại: mã cũ SVkkNNNN là
    sinh viên thứ NNNN (theo thứ tự tạo) của khóa kk, đúng như cách seed cũ đánh số."""
    mapping, pos = {}, {}
    cur.execute("SELECT student_code FROM students ORDER BY id")
    for (code,) in cur.fetchall():
        if code.isdigit():
            cohort = code[:2]
            pos[cohort] = pos.get(cohort, 0) + 1
            mapping[f"SV{cohort}{pos[cohort]:04d}"] = code
    mapping.update(exact)
    return mapping


def fix_history(cur, mapping: dict[str, str], apply: bool) -> int:
    """Thay mã cũ trong các cột chữ lịch sử. Trả về số ô đã (hoặc sẽ) đổi."""
    def swap(m: re.Match) -> str:
        new = mapping.get(f"SV{m[1]}{m[2]}")
        return new if new else m[0]

    total = 0
    for table, column in HISTORY_COLUMNS:
        cur.execute(f"SELECT id, CAST(`{column}` AS CHAR) FROM `{table}` "
                    f"WHERE LOWER(CAST(`{column}` AS CHAR)) REGEXP 'sv[0-9]{{6}}'")
        rows = [(rid, text, OLD_IN_TEXT.sub(swap, text)) for rid, text in cur.fetchall()]
        rows = [r for r in rows if r[2] != r[1]]
        if rows:
            print(f"  {table}.{column}: {len(rows)} dòng")
            total += len(rows)
            if apply:
                cur.executemany(f"UPDATE `{table}` SET `{column}` = %s WHERE id = %s", [(new, rid) for rid, _, new in rows])
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="đổi thật (mặc định chỉ xem trước)")
    args = parser.parse_args()

    conn = pymysql.connect(**settings.pymysql_kwargs(settings.db_name_v2), autocommit=False)
    with conn, conn.cursor() as cur:
        cur.execute("""SELECT s.id, s.user_id, s.student_code, s.email, m.code
                       FROM students s JOIN classes c ON c.id = s.class_id JOIN majors m ON m.id = c.major_id
                       WHERE s.student_code LIKE 'SV%%' ORDER BY s.id""")
        rows = [r for r in cur.fetchall() if OLD.match(r[2])]
        if not rows:
            print("Mã sinh viên và tên đăng nhập đã toàn số.")
            n = fix_history(cur, history_mapping(cur, {}), args.apply)
            if not n:
                print("Lịch sử (cảnh báo, email, nhật ký) cũng không còn mã dạng cũ. Không cần đổi gì.")
            elif args.apply:
                conn.commit()
                print(f"Đã thay mã cũ trong {n} dòng lịch sử.")
            else:
                print(f"Sẽ thay mã cũ trong {n} dòng lịch sử. Thêm --apply để đổi thật.")
            return
        # Cấp lại số thứ tự trong từng (khóa, ngành) theo thứ tự mã cũ, giống seed_demo_v2.py
        rows.sort(key=lambda r: (int(OLD.match(r[2])[1]), int(OLD.match(r[2])[2])))
        seq, changes = {}, []
        for sid, user_id, old, email, major_code in rows:
            cohort = OLD.match(old)[1]
            major = MAJOR_BY_CODE.get(major_code, "CNTT")
            seq[(cohort, major)] = n = seq.get((cohort, major), 0) + 1
            changes.append((sid, user_id, old, f"{cohort}{STUDENT_CODE_MAJOR[major]}{n:04d}", email))

        print(f"Sẽ đổi {len(changes)} mã sinh viên, ví dụ:")
        for _, _, old, new, _ in changes[:3] + changes[-2:]:
            print(f"  {old} -> {new}")
        if not args.apply:
            print("\nChưa đổi gì. Thêm --apply để đổi thật.")
            return

        for sid, user_id, old, new, email in changes:
            cur.execute("UPDATE students SET student_code = %s WHERE id = %s", (new, sid))
            cur.execute("UPDATE users SET username = %s WHERE id = %s AND username = %s", (new, user_id, old))
            demo_email = f"{old.lower()}@example.edu.vn"
            new_email = f"{new}@example.edu.vn"
            cur.execute("UPDATE students SET email = %s WHERE id = %s AND email = %s", (new_email, sid, demo_email))
            cur.execute("UPDATE users SET email = %s WHERE id = %s AND email = %s", (new_email, user_id, demo_email))
        print("Thay mã cũ trong lịch sử:")
        n = fix_history(cur, history_mapping(cur, {old: new for _, _, old, new, _ in changes}), True)
        conn.commit()
        print(f"Đã thay mã cũ trong {n} dòng lịch sử.")
        print(f"\nĐã đổi {len(changes)} mã sinh viên. Đăng nhập sinh viên bằng mã mới, mật khẩu không đổi.")


if __name__ == "__main__":
    main()
