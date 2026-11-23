# EduAgent: Hệ thống cảnh báo sớm sinh viên có nguy cơ học tập yếu

Đề tài NCKH sinh viên, Khoa CNTT, Trường Đại học Đại Nam, năm học 2026–2027.
Người hướng dẫn: ThS. Phạm Văn Tiệp.

| Thành viên | Phụ trách | Thư mục chính |
|---|---|---|
| Nguyễn Đăng Quang | Dữ liệu, mô hình học máy | `ml/` |
| Nguyễn Thị Tuyết | CSDL, giao diện, dashboard | `database/`, `frontend/` |
| Đỗ Trung Kiên | Backend API, tích hợp mô hình, gửi cảnh báo | `backend/` |

## Kiến trúc

```
[Trình duyệt: HTML/CSS/JS + Font Awesome + Chart.js]
            │  fetch() gọi /api/...
            ▼
[Backend Python: FastAPI] ──► [MySQL (XAMPP): CSDL eduagent_v2]
            │
            └──► [AI Agent: mô hình M0/M1/M2 trong ml/models/dainam/]
```

## Cấu trúc thư mục

```
EduAgent/
├── start.bat, start.py         # chạy toàn bộ hệ thống bằng một file, báo tình trạng
├── ml/                         # Quang
│   ├── data/raw/               # dữ liệu thật (KHÔNG commit)
│   ├── data/synthetic/         # dữ liệu giả lập (sinh bằng script)
│   ├── notebooks/              # Jupyter: khám phá dữ liệu, thử nghiệm
│   ├── scripts/generate_synthetic_data.py
│   ├── adapters/               # oulad.py, dainam.py: quy đổi dữ liệu về lược đồ đặc trưng chung
│   ├── train_checkpoints.py    # mô hình chính M0/M1/M2 trên OULAD, so công bằng với quy tắc
│   ├── train_dainam.py         # mô hình cho AI Agent trên CSDL v2 + kiểm chứng trên kỳ cũ
│   ├── train.py                # thử nghiệm: train + so sánh 4 mô hình trên dữ liệu giả lập (trang So sánh mô hình)
│   └── models/                 # metrics.json, oulad/, dainam/ (không commit)
├── database/                   # Tuyết
│   ├── schema_v2.sql           # CSDL 'eduagent_v2' theo cấu trúc Đại Nam (docs/csdl-v2.md)
│   └── seed_demo_v2.py         # sinh dữ liệu demo cho CSDL v2
├── backend/                    # Kiên
│   ├── app/main.py             # khởi động FastAPI
│   ├── app/agent.py            # AI Agent: quan sát -> luật -> mô hình -> báo cáo -> theo dõi
│   ├── app/scheduler.py        # Agent tự chạy: theo lịch và khi có điểm / điểm danh mới
│   ├── app/notifier.py, mailer.py  # email cảnh báo sau mỗi lần chạy; gửi SMTP hoặc lưu backend/outbox
│   ├── app/auth.py             # xác thực token, require_roles(...)
│   ├── app/security.py         # băm mật khẩu, tạo / kiểm tra JWT
│   ├── app/models_v2.py        # ánh xạ bảng CSDL
│   ├── app/services_v2.py      # nghiệp vụ dùng chung (học kỳ hiện tại, tổng hợp điểm, chuyên cần)
│   ├── app/routers/            # auth, account, me (SV), teaching (GV/CVHT), manage, dashboard, agent, emails, admin
│   ├── scripts/run_agent.py    # chạy Agent từ dòng lệnh
│   └── scripts/check_auth.py   # kiểm thử API và phân quyền (backend phải đang chạy)
├── frontend/                   # Tuyết
│   ├── js/layout.js            # thanh bên + thanh điều hướng dùng chung (sửa menu ở đây)
│   ├── css/style.css           # giao diện chung, cùng phong cách OmniStock
│   └── *.html                  # index (Tổng quan), agent, alerts, emails, account, teaching, advising,
│                               # manage-students, student, my-*, users, models...
├── archive/prototype.zip       # code bản prototype đã gỡ ở giai đoạn 5 (không commit)
└── docs/                       # kế hoạch, thiết kế, CSDL, từ điển dữ liệu
```

## Chạy nhanh: một file

Cần: Python 3.12 trở lên, XAMPP (có MySQL). Nhấp đúp **`start.bat`** ở thư mục gốc. Script sẽ:

1. Tạo `.venv` và cài thư viện nếu chưa có
2. Chép `backend/.env` từ `.env.example` nếu chưa có
3. Tự bật MySQL của XAMPP nếu chưa chạy (dò `C:\xampp`, `D:\xampp`, `D:\Program\XAMPP`...; máy khác thì ghi `XAMPP_DIR` trong `backend/.env`)
4. Import `database/schema_v2.sql` nếu chưa có CSDL `eduagent_v2`, sinh dữ liệu demo nếu CSDL trống
   (`seed_demo_v2.py`). Tài khoản demo: `admin`, `gv001`…, `SV170001`…,
   mật khẩu chung là `DEMO_PASSWORD` trong `database/seed_demo_v2.py`
5. Train mô hình thử nghiệm (dữ liệu giả lập) nếu thiếu, báo tình trạng dữ liệu và mô hình OULAD
6. AI Agent: train mô hình Agent trên CSDL v2 nếu thiếu (khoảng 30 giây), chạy Agent lần đầu nếu kỳ này chưa chạy
7. Chạy backend ở http://127.0.0.1:8000, mở trình duyệt; nhấn Ctrl+C để dừng

Mỗi bước in `[ OK ]`, `[SỬA ]` (đã tự sửa), `[ !! ]` (lưu ý) hoặc `[LỖI ]` kèm cách xử lý.

```powershell
start.bat --check    # chỉ kiểm tra tình trạng, không chạy web
start.bat --train    # train lại mô hình OULAD và mô hình Agent trước khi chạy (vài phút)
start.bat --port 8001
```

## Cài đặt thủ công (Windows)

Cần: Python 3.12 trở lên, Git, XAMPP (bật **MySQL**), VS Code.

```powershell
# 1. Tạo môi trường ảo và cài thư viện (chạy ở thư mục gốc dự án)
python -m venv .venv
.venv\Scripts\activate
pip install -r ml\requirements.txt -r backend\requirements.txt

# 2. Tải dữ liệu công khai OULAD (khoảng 450 MB, chỉ cần làm một lần)
python ml\scripts\download_oulad.py

#    Mô hình chính: dự báo trượt môn theo mốc M0/M1/M2 trên OULAD
#    (so 2 bộ đặc trưng core/extended và so công bằng với quy tắc; thêm --no-svm để chạy nhanh hơn)
python ml\adapters\oulad.py
python ml\train_checkpoints.py

#    Thử nghiệm 4 mô hình trên dữ liệu giả lập (trang So sánh mô hình)
python ml\scripts\generate_synthetic_data.py
python ml\train.py

# 3. Tạo CSDL: import database\schema_v2.sql trong phpMyAdmin
#    (http://localhost/phpmyadmin > Import), hoặc dùng lệnh:
#    D:\Program\XAMPP\mysql\bin\mysql.exe -u root < database\schema_v2.sql

# 4. Cấu hình kết nối MySQL
copy backend\.env.example backend\.env
#    sửa DB_PASSWORD trong backend\.env nếu MySQL có mật khẩu

# 5. Sinh dữ liệu demo, train mô hình Agent, chạy Agent lần đầu
python database\seed_demo_v2.py
python ml\train_dainam.py
python backend\scripts\run_agent.py --bootstrap

# 6. Chạy backend
uvicorn app.main:app --reload --app-dir backend
```

Mở trình duyệt:
- Giao diện: http://127.0.0.1:8000
- Tài liệu và thử API: http://127.0.0.1:8000/docs
- Kiểm tra CSDL và mô hình: http://127.0.0.1:8000/api/health

> Làm giao diện bằng **Live Server** (cổng 5500) cũng được, nhưng backend vẫn phải chạy ở cổng 8000.

## AI Agent

Agent giám sát học kỳ hiện tại trên CSDL v2 và cảnh báo sớm sinh viên có nguy cơ trượt môn
(thiết kế: [docs/thiet-ke-he-thong.md, mục 6](docs/thiet-ke-he-thong.md#6-ai-agent)). Mỗi lần chạy đi qua 5 tầng:

1. **Quan sát**: mỗi lớp học phần đang ở mốc nào (M0 đầu kỳ, M1 có KT1, M2 có KT2), có bao nhiêu điểm / điểm danh mới
2. **Luật quy chế**: vắng nhiều, vắng quá ngưỡng cấm thi, điểm quá trình thấp; đầu kỳ: đang học lại, nợ nhiều môn
3. **Mô hình AI**: xác suất trượt và lý do chính cho từng sinh viên × môn
4. **Báo cáo**: cảnh báo cho giảng viên bộ môn, CVHT; lời nhắc cho sinh viên (không hiện xác suất)
5. **Theo dõi**: so với lần chạy trước, ai cải thiện, ai xấu đi

Trang **AI Agent** (admin, giảng viên) tách riêng nhóm **"AI phát hiện sớm"**: sinh viên chưa vi phạm luật nào nhưng
AI dự báo có nguy cơ. Đây là phần truy vấn CSDL thông thường không làm được. Trang này cũng có mục **kiểm chứng**: cho
Agent chạy lại học kỳ gần nhất đã biết kết quả rồi so với luật.

```powershell
python ml\train_dainam.py                     # train lại mô hình Agent (khi dữ liệu CSDL v2 thay đổi)
python backend\scripts\run_agent.py            # chạy Agent ngay (hoặc nút "Chạy Agent ngay" trên web, tài khoản admin)
python backend\scripts\run_agent.py --reset    # xóa kết quả Agent cũ rồi chạy lại từ đầu kỳ
```

> Số liệu kiểm chứng trên trang AI Agent tính trên **dữ liệu demo** nên chỉ chứng minh quy trình chạy đúng.
> Độ chính xác trên dữ liệu thật: phần OULAD ở trang **So sánh mô hình**.

**Tự chạy** (`backend/app/scheduler.py`, khi backend đang bật): theo lịch `agent_schedule` (mặc định 7:00 thứ 2 hằng
tuần) và mỗi `agent_poll_minutes` phút (mặc định 15) kiểm tra có điểm / điểm danh mới sau lần chạy trước thì chạy với lý
do "Có điểm mới". Agent chỉ báo khi sinh viên mới cần chú ý hoặc xấu đi nên chạy nhiều không gửi trùng.
Bật / tắt ở trang **Lịch sử gửi email** (admin).

## Gửi email cảnh báo

Mỗi cảnh báo gửi tới **sinh viên** (lời nhắc, không có xác suất) và **CVHT / giáo viên chủ nhiệm** (kèm lý do);
giảng viên bộ môn nhận khi admin bật. Sau mỗi lần Agent chạy, mỗi người nhận **một email tổng hợp**.

- **Mỗi tài khoản phải liên kết email**: trang **Tài khoản của tôi** (bấm tên ở góc phải): nhập email, nhận mã 6 số,
  nhập mã. Chưa liên kết thì mọi trang hiện nhắc nhở và người đó không nhận email. Admin có thể gán email nhà trường
  cấp ở trang **Tài khoản & phân quyền** (coi như đã xác nhận).
- **Chưa cấu hình SMTP** (mặc định): chế độ thử, thư lưu thành file `.eml` trong `backend/outbox/` (mở bằng
  Outlook / Thunderbird), mã xác nhận hiện ngay trên trang. Thư mục này có dữ liệu sinh viên, đã nằm trong `.gitignore`.
- **Gửi thật bằng Gmail**: bật xác minh 2 bước cho tài khoản Google, tạo **Mật khẩu ứng dụng** (Tài khoản Google >
  Bảo mật > Mật khẩu ứng dụng), rồi **tự** điền vào `backend/.env` (không gửi mật khẩu cho ai, không commit):

  ```
  SMTP_HOST=smtp.gmail.com
  SMTP_PORT=587
  SMTP_USER=dia-chi-gmail-cua-nhom
  SMTP_PASSWORD=mat-khau-ung-dung-16-ky-tu
  MAIL_REDIRECT_TO=hop-thu-thu-nghiem-cua-nhom   # khi thử: mọi thư chuyển về đây, bỏ trống khi dùng thật
  ```

  Khởi động lại backend, vào **Tài khoản của tôi** bấm **Gửi thư thử**. Gmail giới hạn khoảng 500 thư / ngày.
- Lịch sử mọi email (đã gửi / chế độ thử / lỗi) ở trang **Lịch sử gửi email**; trang AI Agent ghi số email của từng lần chạy.

## Đăng nhập và phân quyền

Mọi trang (trừ `login.html`) và mọi API (trừ `/api/health`, `/api/auth/login`) đều cần đăng nhập.
Token JWT ký bằng `JWT_SECRET` trong `backend/.env` (`start.bat` tự tạo), hết hạn sau 8 giờ.

| Vai trò | Tài khoản demo | Trang chính |
|---|---|---|
| Quản trị hệ thống | `admin` | Tổng quan (toàn trường), Lớp học phần, Lớp hành chính, Sinh viên (thêm, sửa, import Excel), Tài khoản & phân quyền |
| Giảng viên (có thể kiêm CVHT) | `gv001` … `gv012` (gv001–gv006 là CVHT) | Tổng quan (lớp mình), Lớp học phần của tôi (nhập điểm, điểm danh, nhật ký sửa điểm), Lớp chủ nhiệm, Sinh viên lớp chủ nhiệm |
| Sinh viên | `SV170001`, `SV180001`, `SV190001`… | Kết quả học tập, Điểm danh |

Mật khẩu chung của tài khoản demo: hằng `DEMO_PASSWORD` trong `database/seed_demo_v2.py` (chỉ dùng trên máy cá nhân).
Sai mật khẩu 5 lần liên tiếp thì tên đăng nhập bị tạm khóa 5 phút. Kiểm tra toàn bộ phân quyền:
`python backend/scripts/check_auth.py` (backend phải đang chạy).

Thêm vai trò cho một trang: khai báo `<body data-roles="admin,lecturer">`; thêm vào menu: sửa `MENU` trong
`frontend/js/layout.js` (thuộc tính `roles`). Chặn API theo vai trò: `Depends(require_roles(...))` trong `backend/app/auth.py`.

## API hiện có

| Phương thức | Đường dẫn | Ai dùng được | Mô tả |
|---|---|---|---|
| POST | `/api/auth/login` | Mọi người | Đăng nhập, nhận token |
| GET | `/api/auth/me` | Đã đăng nhập | Tài khoản đang dùng |
| POST | `/api/auth/change-password` | Đã đăng nhập | Đổi mật khẩu |
| GET | `/api/account` | Đã đăng nhập | Tài khoản, trạng thái liên kết email |
| POST | `/api/account/email/request`, `/api/account/email/verify` | Đã đăng nhập | Liên kết email: gửi mã 6 số, nhập mã |
| POST | `/api/account/email/test` | Đã đăng nhập | Gửi thư thử tới email đã liên kết |
| GET | `/api/emails` | Đã đăng nhập (admin thấy tất cả) | Lịch sử email |
| GET, PUT | `/api/emails/config` | Admin | Ai nhận email cảnh báo, bật / tắt Agent tự chạy, chế độ gửi |
| GET | `/api/me/results` | Sinh viên | Kết quả học tập toàn khóa (của chính mình) |
| GET | `/api/me/attendance` | Sinh viên | Điểm danh học kỳ hiện tại |
| GET | `/api/teaching/sections` | GV (lớp mình dạy), admin | Lớp học phần học kỳ hiện tại |
| GET | `/api/teaching/sections/{id}` | GV phụ trách, admin | Sinh viên, điểm thành phần, chuyên cần, điểm thi tối thiểu |
| GET | `/api/advising/students` | CVHT (lớp mình), admin | Sinh viên lớp hành chính |
| PUT | `/api/teaching/sections/{id}/grades` | GV phụ trách, admin | Nhập / sửa / xóa điểm thành phần (học kỳ hiện tại); có điểm thi thì tự tính TBCHP, điểm chữ |
| GET | `/api/teaching/sections/{id}/grade-log` | GV phụ trách, admin | Nhật ký nhập, sửa, xóa điểm của lớp |
| GET | `/api/teaching/sections/{id}/sessions` | GV phụ trách, admin | Các buổi học, số sinh viên đã điểm danh |
| GET, PUT | `/api/teaching/sections/{id}/sessions/{sid}` | GV phụ trách, admin | Điểm danh một buổi (không điểm danh trước ngày học) |
| GET | `/api/dashboard` | Admin (toàn trường), GV (lớp mình dạy và lớp chủ nhiệm) | Số liệu trang Tổng quan: nguy cơ theo lớp, theo môn, ĐTB và cảnh báo học tập qua các học kỳ, xếp loại, tỷ lệ vắng theo tuần |
| GET | `/api/manage/options` | GV, admin | Lớp hành chính, trạng thái (cho bộ lọc) |
| GET | `/api/manage/students` | Admin (tất cả), CVHT (lớp mình) | Danh sách sinh viên: lọc lớp, trạng thái, nguy cơ; ĐTB, tín chỉ, môn nợ |
| GET | `/api/manage/students/{id}` | Admin, CVHT, GV từng dạy SV đó | Hồ sơ: thông tin, kết quả học tập, học kỳ hiện tại kèm nguy cơ AI, cảnh báo |
| POST | `/api/manage/students` | Admin | Thêm sinh viên, tạo tài khoản, trả mật khẩu tạm một lần |
| PATCH | `/api/manage/students/{id}` | Admin | Sửa thông tin, đổi lớp, trạng thái học tập, khóa / mở tài khoản |
| POST | `/api/manage/students/{id}/reset-password` | Admin | Đặt lại mật khẩu tạm |
| POST | `/api/manage/students/import` | Admin | Import danh sách (`dry_run` = chạy thử); còn dòng lỗi thì không ghi gì |
| GET | `/api/admin/users` | Admin | Danh sách tài khoản |
| GET | `/api/admin/users?email=unlinked` | Admin | Lọc tài khoản chưa liên kết email |
| PATCH | `/api/admin/users/{id}` | Admin | Khóa / mở khóa tài khoản, gán email nhà trường cấp |
| GET | `/api/agent/overview` | GV, admin | Lần chạy gần nhất của Agent (số liệu 5 tầng) |
| POST | `/api/agent/run` | Admin | Chạy Agent ngay |
| GET | `/api/agent/runs` | GV, admin | Nhật ký các lần chạy |
| GET | `/api/agent/predictions?source=ai` | GV (lớp mình dạy / chủ nhiệm), admin | Sinh viên × môn cần chú ý (`source`: ai, both, rule), lý do, diễn biến |
| GET | `/api/agent/backtest` | GV, admin | Kiểm chứng trên học kỳ cũ đã biết kết quả |
| GET | `/api/alerts/mine` | Đã đăng nhập | Cảnh báo / lời nhắc gửi tới mình |
| POST | `/api/alerts/{id}/read`, `/api/alerts/read-all` | Đã đăng nhập | Đánh dấu đã đọc |

Không cần đăng nhập: `GET /api/health` (tình trạng CSDL và mô hình của AI Agent).
Kết quả train mô hình (đọc file trong `ml/models`, không dùng CSDL), chỉ dành cho admin và giảng viên:

| Phương thức | Đường dẫn | Mô tả |
|---|---|---|
| GET | `/api/experiments/latest` | Kết quả lần train gần nhất (đọc `ml/models/metrics.json`) |
| GET | `/api/experiments/history` | Lịch sử các lần train (đọc `ml/models/history.jsonl`) |
| GET | `/api/experiments/oulad` | Mô hình chính M0/M1/M2 trên OULAD, so công bằng với quy tắc |

## Thử nghiệm mô hình

Mỗi lần chạy `python ml\train.py --note "mô tả thay đổi"`, kết quả 4 mô hình được ghi vào lịch sử.
Trang **So sánh mô hình** (http://127.0.0.1:8000/models.html) hiển thị biểu đồ chỉ số, bảng kết quả,
ma trận nhầm lẫn, đặc trưng quan trọng và lịch sử các lần train. Trang này không cần MySQL.

Mô hình được chọn theo **F1 kiểm định chéo 5 lần** trên tập train; tập kiểm tra (20%) chỉ dùng để báo cáo.

## Quy ước làm việc với Git

- Nhánh `main` luôn chạy được. Mỗi người làm trên nhánh riêng, ví dụ `quang/train-model`, `tuyet/dashboard`, `kien/email-alert`, rồi tạo Pull Request để nhóm xem trước khi gộp.
- **Không commit** file `backend/.env` (mật khẩu) và dữ liệu thật của sinh viên. `.gitignore` đã chặn sẵn.
- Sửa bảng trong `database/schema_v2.sql` thì sửa luôn `backend/app/models_v2.py` cho khớp, và thêm câu lệnh
  vào `MIGRATIONS` trong `backend/app/database_v2.py` để máy đã có CSDL tự cập nhật.

**Thiết kế hệ thống (bản mới nhất): [docs/thiet-ke-he-thong.md](docs/thiet-ke-he-thong.md).**
Kế hoạch và tiến độ: [docs/ke-hoach.md](docs/ke-hoach.md). CSDL: [docs/csdl-v2.md](docs/csdl-v2.md).
Đặc trưng của mô hình thử nghiệm: [docs/tu-dien-du-lieu.md](docs/tu-dien-du-lieu.md).

> Bản prototype đầu tiên (CSDL `eduagent`, trang Sinh viên / Dự báo thử cũ) đã gỡ khỏi code ở giai đoạn 5.
> Code cũ được nén trong `archive/prototype.zip` (chỉ có trên máy đã gỡ); CSDL `eduagent` vẫn nằm trong MySQL,
> xóa bằng phpMyAdmin khi không cần.
