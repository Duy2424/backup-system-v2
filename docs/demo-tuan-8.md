# Kịch bản demo tuần 8 (05/12/2026) — chạy trên MỘT máy

Mục tiêu: trong 10–12 phút cho thầy thấy trọn vòng **sao lưu → khôi phục**, ba lớp chống xoá, cổng chặn ransomware và
thông báo. Mọi thứ chạy trên một laptop, không cần Internet (trừ Telegram, tuỳ chọn).

## Chuẩn bị (trước buổi, 5 phút)

```powershell
cd D:\backup-system-v2
powershell -ExecutionPolicy Bypass -File deploy\demo\chuan_bi_demo.ps1 -Reset      # .venv, D:\DemoBackup\{kho,DuLieu,server,secrets}
deploy\demo\demo_1_may.bat                                                          # 3 cửa sổ: KHO, SERVER, AGENT + trình duyệt
```

- Đăng nhập `admin / demo12345` (đổi bằng `-AdminPassword`). Chọn giao diện **Sáng** (máy chiếu).
- Mở sẵn Explorer tại `D:\DemoBackup\DuLieu` và một cửa sổ PowerShell tại `D:\backup-system-v2`.
- Tuỳ chọn Telegram: Cài đặt → Thông báo Telegram → dán token (BotFather), nhắn `/id` cho bot lấy chat ID → **Gửi tin thử**.
- Tập chạy toàn bộ ít nhất 2 lần. Nếu lỗi giữa buổi: mọi bước đều có lệnh dòng lệnh tương đương bên dưới.

## Diễn (theo thứ tự)

| # | Phút | Làm gì | Thầy thấy gì |
|---|---|---|---|
| 1 | 1 | Mở **Tổng quan** khi chưa có gì | RPO **Quá hạn** (đỏ) "Chưa có bản sao lưu"; Agent xanh; Kho đang chạy, 0 snapshot |
| 2 | 2 | **Sao lưu** → Chỉ dữ liệu → Thêm thư mục `D:\DemoBackup\DuLieu` → Bắt đầu | Thanh tiến độ; xong: RPO **Đạt mục tiêu**, bảng Snapshot (file, dữ liệu, gửi lên), Thông báo "Sao lưu xong" |
| 3 | 1 | Bấm **Sao lưu ngay** lần 2 (không đổi gì) | Mẩu mới 0/…, gửi lên vài KB; "khử trùng lặp 2,0×" ở ô Kho |
| 4 | 1 | Sửa 1 file `.txt` trong `DuLieu\du_lieu_mau\van_ban`, Sao lưu lần 3 | Chỉ gửi phần đổi (vài chục KB) |
| 5 | 2 | **K3 xoá nhầm**: trong Explorer xoá hẳn thư mục `du_lieu_mau\tai_lieu`. Web: Bản sao lưu → chọn bản mới nhất → **Chạy thử** (xem số file sẽ ghi) → **Khôi phục…** | Thư mục quay lại trong Explorer; Thông báo "Khôi phục xong" |
| 6 | 1,5 | **K5 xoá backup bị từ chối**: PowerShell `./.venv/Scripts/python bench/dien_tap.py k5 --repo http://127.0.0.1:8080 --password-file D:\DemoBackup\secrets\kho.txt` | 7 dòng `TU CHOI` (DELETE/PUT ghi đè/POST/PATCH/MOVE), dữ liệu nguyên vẹn; Cài đặt → Kho: "Lệnh xoá bị từ chối: 7" |
| 7 | 2,5 | **K1 ransomware**: `powershell -ExecutionPolicy Bypass -File deploy\demo\gia_ransomware.ps1 -Data D:\DemoBackup\DuLieu` → web bấm **Sao lưu ngay** | Job **Thất bại: BẤT THƯỢNG – đã dừng, không gửi gì lên kho** (lý do: file mồi, % file nghi mã hoá); Thông báo đỏ (+ Telegram); kho vẫn 3 snapshot sạch |
| 8 | 1 | Khôi phục bản tốt cuối: Bản sao lưu → bản #3 → tick **Xoá file không có trong bản sao lưu** → Khôi phục | `.locked`, `HUONG_DAN_CHUOC.txt` biến mất, file mồi sạch; Sao lưu lại → xanh |
| 9 | 1 | Cài đặt → Kho v2 → **Khôi phục thử ngay** và **Kiểm tra toàn vẹn** | Thông báo "Khôi phục thử: OK 20/20 file khớp SHA-256", "Kiểm tra kho: toàn vẹn" |
| 10 | 0,5 | (có Telegram) bấm nút **Sự cố** trên điện thoại cho một thông báo | Web hiện "Sự cố · Tên" ngay, nút trên Telegram biến mất |
| 11 | 1 | **K2** (nếu còn giờ): `python bench/dien_tap.py k2` | Bảng: máy mới chỉ tải SQLBackup + ChiaSe (vài MB trong tổng), bỏ qua Web; in lệnh `RESTORE … STOPAT` + `New-SmbShare` |
| 12 | 1 | Slide 1 trang: 3 lớp chống xoá (API không có DELETE / NTFS deny / mTLS + firewall), cloud Object Lock 30 ngày | `docs/tuan3-kho-mtls.md`, `docs/tuan5-cloud-object-lock.md` |

## Nếu hỏng giữa buổi

| Sự cố | Cách xử lý |
|---|---|
| Agent "chưa kết nối" | Nhìn cửa sổ AGENT; chạy lại `demo_1_may.bat` (3 cửa sổ, kho khởi động trước) |
| Kho không kết nối | Cửa sổ KHO: `python -m kho --kho D:\DemoBackup\kho`; `http://127.0.0.1:8080/health` |
| Web lỗi 500 / đăng nhập | Cửa sổ SERVER có log; mật khẩu admin đặt lại bằng `chuan_bi_demo.ps1 -Reset` (mất dữ liệu demo) |
| Không có máy chiếu màu tốt | Giao diện đã kèm chữ "Đạt / Sắp quá hạn / Quá hạn", không chỉ dựa màu |
| Telegram không gửi | Bỏ bước 10; Thông báo trên web vẫn đầy đủ |

## Lệnh dòng lệnh tương đương (dự phòng)

```bat
set PW=D:\DemoBackup\secrets\kho.txt
.venv\Scripts\python -m core snapshots --repo http://127.0.0.1:8080 --password-file %PW%
.venv\Scripts\python -m core backup    --repo http://127.0.0.1:8080 --password-file %PW% D:\DemoBackup\DuLieu
.venv\Scripts\python -m core restore   --repo http://127.0.0.1:8080 --password-file %PW% latest --target D:\DemoBackup\KhoiPhuc --include DuLieu/du_lieu_mau/tai_lieu
.venv\Scripts\python -m core verify    --repo http://127.0.0.1:8080 --password-file %PW% --notify-url "http://127.0.0.1:5000/api/notify?token=<AGENT_TOKEN>"
.venv\Scripts\python -m core check     --repo http://127.0.0.1:8080 --password-file %PW%
.venv\Scripts\python bench\dien_tap.py k1
curl -X DELETE http://127.0.0.1:8080/snapshots/0000000000000000000000000000000000000000000000000000000000000000      rem -> 405
```

## Số liệu mang vào báo cáo

Mỗi lần chạy `dien_tap.py` ghi dòng vào `bench\results\dien_tap.csv` (K1: thời gian phát hiện + khôi phục; K2: byte tải một phần so với
tổng; K5: mã trả về từng lệnh). Chụp màn hình: Tổng quan trước/sau, Thông báo đỏ K1, kết quả K5, `icacls D:\kho-v2\packs`
(trên PC thật), tin Telegram có nút.
