# bench/ — đo đạc v1 / v2

Mọi số đo ghi ra CSV trong `bench/results/` (cột xem `bench/common.py`), để tuần 9 vẽ biểu đồ.
Dữ liệu mẫu và thư mục làm việc (`bench/data/`, `bench/work/`) không đưa lên git; sinh lại được từ seed.

## Chuẩn bị (một lần)

```powershell
py -3.11 -m venv .venv          # hoặc đường dẫn python 3.11 đầy đủ
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 1. Bộ dữ liệu mẫu tất định — `make_dataset.py`

```powershell
.venv\Scripts\python.exe bench\make_dataset.py --out bench\data\ds --size 500MB --seed 2026
.venv\Scripts\python.exe bench\make_dataset.py --out bench\data\ds --mutate 5 --round 1   # "1 ngày làm việc"
.venv\Scripts\python.exe bench\make_dataset.py --out bench\data\ds --digest               # in hash kiểm chứng
```

Cùng `--seed` + `--size` thì ra cùng `digest` trên mọi máy (đã có test). Ghi `digest` vào báo cáo để chứng minh
v1, v2, restic chạy trên cùng dữ liệu.

## 2. Đo nền v1 — `bench_v1.py`

```powershell
.venv\Scripts\python.exe bench\bench_v1.py
```

- Bench **tự bật server v1** ở tiến trình riêng (127.0.0.1, cổng ngẫu nhiên, DB và kho nằm trong `bench\work\v1-<giờ>\`).
  Không cần tự chạy `server.py`, không đụng tới `backup_system.db` hay `storage\` thật.
- Mặc định: 500 MB, seed 2026, 3 lần (full → mutate 5% → mutate 5%), ghi vào `bench\results\v1.csv`.
- Đo qua mạng thật (vd server v1 đặt trên PC, nối bằng Tailscale): bật `server\start_server.bat` trên PC,
  lấy token của user ở trang Admin, rồi chạy

  ```powershell
  .venv\Scripts\python.exe bench\bench_v1.py --server-url http://100.x.y.z:5000 --token <token>
  ```

- Mặc định bỏ qua bước chụp system state của v1 (PowerShell/netsh) để chỉ so phần dữ liệu file với v2.
  Muốn đo cả bước đó thì thêm `--with-system-state`.
- Bench dừng hẳn nếu v1 backup thiếu file so với dữ liệu nguồn (bộ lọc exclude của v1 so khớp chuỗi con,
  vd tên có "ac" bị loại). Dữ liệu mẫu đã được đặt tên để tránh lỗi này, và có test kiểm tra.

Ý nghĩa cột: `giay` = thời gian `perform_backup`; `byte_doc` = byte tiến trình agent đọc (bộ đếm IO của
Windows, gồm cả file tạm tar.gz/.bkup của v1); `byte_gui` = tổng `Content-Length` các request gửi lên server;
`dung_luong_kho` = dung lượng thư mục kho sau lần chạy.

**Lưu ý khi đo để đưa vào báo cáo:** đóng bớt ứng dụng nặng, cắm sạc, không chạy việc khác cùng lúc.
Dữ liệu vừa sinh nằm sẵn trong cache RAM của Windows (cache nóng), điều kiện này giống nhau cho v1 và v2.
