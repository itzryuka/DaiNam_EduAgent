# Chạy EduAgent trên Render + TiDB Cloud (miễn phí)

- **Render** chạy trang web và backend (FastAPI).
- **TiDB Cloud** giữ cơ sở dữ liệu. TiDB nói chuyện giống MySQL nên code không phải đổi.

Vì cơ sở dữ liệu nằm ở TiDB, dữ liệu **không mất** khi máy chủ Render ngủ, khởi động lại hay deploy lại.

> Render không có MySQL miễn phí, còn máy chủ web miễn phí thì xoá hết tệp mỗi lần khởi động lại.
> Vì vậy cơ sở dữ liệu phải đặt ở nơi khác. OmniStock chọn cách chạy MariaDB ngay trong máy chủ web,
> nên dữ liệu quay về bản mẫu mỗi lần khởi động. EduAgent dùng TiDB để giữ được dữ liệu.

## Bước 1. Tạo cơ sở dữ liệu trên TiDB Cloud

1. Vào https://tidbcloud.com, đăng ký tài khoản (có thể dùng tài khoản GitHub).
2. Tạo cluster loại **Starter** (miễn phí), khu vực **Singapore (ap-southeast-1)**, cho gần Render.
3. Mở cluster, bấm **Connect**:
   - Connection type: **Public**, Connect with: **General**.
   - Bấm **Generate Password** (hoặc Reset Password). Mật khẩu chỉ hiện **một lần**, bạn lưu lại ở chỗ an toàn.
   - Ghi lại 3 thông tin: **HOST** (dạng `gateway01.ap-southeast-1.prod.aws.tidbcloud.com`),
     **PORT** (`4000`) và **USERNAME** (dạng `xxxxxxxx.root`).

Không cần tự tạo bảng hay import file SQL: lúc deploy, Render tự làm.

## Bước 2. Tạo web service trên Render

1. Vào https://render.com, đăng nhập bằng GitHub (tài khoản `itzryuka`).
2. Bấm **New > Blueprint**, chọn repo `DaiNam_EduAgent`. Render đọc file `render.yaml` và tự điền cấu hình.
3. Render hỏi giá trị cho 3 biến, bạn điền thông tin lấy ở bước 1:

   | Biến | Giá trị |
   |---|---|
   | `DB_HOST` | HOST của TiDB |
   | `DB_USER` | USERNAME của TiDB (có cả phần `.root`) |
   | `DB_PASSWORD` | mật khẩu TiDB |

   Các biến khác đã có sẵn trong `render.yaml`:
   - `DB_PORT=4000`, `DB_SSL=true` (bắt buộc kết nối mã hoá với TiDB), `DB_NAME_V2=eduagent_v2`;
   - `JWT_SECRET`: Render tự sinh chuỗi ngẫu nhiên.
4. Bấm **Apply**. Lần build đầu mất khoảng 5–10 phút:
   - cài thư viện;
   - tạo bảng trong TiDB và sinh dữ liệu demo;
   - train mô hình Agent 3 mốc và mô hình thử nghiệm;
   - chạy Agent lần đầu.

   Theo dõi ở tab **Logs**: các dòng bắt đầu bằng `[deploy_setup]` cho biết đang ở bước nào.
5. Xong, trang chạy ở địa chỉ dạng `https://dainam-eduagent.onrender.com`. Đăng nhập bằng tài khoản demo
   (`admin`, `gv001`..., mã sinh viên `1771020001`...). Mật khẩu chung nằm ở `DEMO_PASSWORD` trong `database/seed_demo_v2.py`.

Mỗi lần đẩy code mới lên nhánh `main`, Render tự deploy lại. Khi deploy lại:
- dữ liệu cũ trong TiDB được **giữ nguyên**, chỉ bảng còn thiếu mới được tạo;
- mô hình được train lại trên các học kỳ đã kết thúc.

## Gửi email thật (không bắt buộc)

Chưa cấu hình thì email chỉ được lưu tạm trên máy chủ và sẽ mất khi máy chủ khởi động lại.
Muốn gửi thật qua Gmail, vào Render > service > **Environment** và thêm các biến:

```
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=dia-chi-gmail-cua-nhom
SMTP_PASSWORD=mat-khau-ung-dung-16-ky-tu
```

Mật khẩu ứng dụng lấy ở Tài khoản Google > Bảo mật > Mật khẩu ứng dụng (xem README mục "Gửi email cảnh báo").
Đường link trong email tự lấy theo địa chỉ trang trên Render.

## Giới hạn của gói miễn phí

- **Trang ngủ sau 15 phút** không ai truy cập. Lần mở tiếp theo phải chờ khoảng 1 phút để máy chủ thức dậy.
- **Agent tự chạy theo lịch chỉ hoạt động khi trang đang thức.** Admin vẫn bấm "Chạy Agent" thủ công được bất cứ lúc nào.
- **TiDB miễn phí** có khoảng 5 GiB và giới hạn lượt truy vấn mỗi tháng, thừa cho bản demo.
  Mỗi lần chạy Agent thêm khoảng 1.000 dòng dự báo.
- **Ai đọc repo cũng biết mật khẩu demo**, nên ai cũng đăng nhập được. Chỉ dùng dữ liệu demo,
  **tuyệt đối không nhập dữ liệu thật của sinh viên** lên bản này (Nghị định 13/2023 về dữ liệu cá nhân).

## Khi có lỗi

| Hiện tượng trong Logs | Cách xử lý |
|---|---|
| `Access denied for user` | Sai `DB_USER` hoặc `DB_PASSWORD`. Nhớ ghi đủ phần `xxxxxxxx.root`. |
| `SSL is required` hoặc lỗi chứng chỉ | Kiểm tra `DB_SSL=true` |
| `Can't connect to MySQL server` | Sai `DB_HOST` hoặc `DB_PORT` (phải là 4000) |
| Hết bộ nhớ (out of memory) | Gói free có 512 MB RAM. Báo nhóm để giảm bớt phần nạp sẵn mô hình. |

Muốn làm lại từ đầu với dữ liệu demo mới: xoá database `eduagent_v2` trong TiDB Cloud
(SQL Editor: `DROP DATABASE eduagent_v2;`), rồi ở Render bấm **Manual Deploy > Deploy latest commit**.

## Chạy thử quy trình này trên máy

Script deploy chạy được với MariaDB của XAMPP. Đặt tên CSDL khác để không đụng dữ liệu đang dùng:

```powershell
$env:DB_NAME_V2="eduagent_thu"; $env:MODELS_DIR="$env:TEMP\eduagent_models"; .venv\Scripts\python.exe backend\scripts\deploy_setup.py
```
