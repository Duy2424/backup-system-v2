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

- Bench **tự bật server** ở tiến trình riêng (127.0.0.1, cổng ngẫu nhiên, DB và kho nằm trong `bench\work\<nhãn>-<giờ>\`).
  Không cần tự chạy `server.py`, không đụng tới `backup_system.db` hay `storage\` thật.
- Mặc định: 500 MB, seed 2026, 3 lần (full → mutate 5% → mutate 5%), ghi vào `bench\results\v1.csv`.
- Hai phiên bản, cột `phien_ban` trong CSV:
  - `v1-toiuu`: mã nguồn hiện tại (bản 1.5) — `bench\bench_v1.py`
  - `v1-goc`: bản đồ án cơ sở gốc — `bench\bench_v1.py --ref v1-goc` (tự tạo git worktree của tag `v1-goc`
    trong `bench\work\ref-v1-goc\`, không đụng tới mã nguồn đang làm).
- Byte gửi được đếm bằng WSGI middleware ở phía server (đúng cả với upload chunked không có `Content-Length`).
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

## 3. Đo v2 — `bench_v2.py`

```powershell
.venv\Scripts\python.exe bench\bench_v2.py
```

- Cùng bộ dữ liệu, cùng chuỗi full → mutate 5% → mutate 5% như `bench_v1.py`, kho v2 **local** (`core.repo_local`).
- `byte_gui` = tổng byte pack mới + snapshot, tức đúng lượng sẽ gửi qua mạng ở tuần 3.
- Sau lần cuối: khôi phục snapshot ra thư mục mới và so `digest` với dữ liệu nguồn (dừng nếu khác).
  Dòng `mo_ta = "khôi phục lần 3"` trong CSV ghi thời gian khôi phục.
- Ghi `bench\results\v2.csv`, rồi in bảng so với các dòng cùng seed + size trong `v1.csv`.

**Lưu ý khi đo để đưa vào báo cáo:** đóng bớt ứng dụng nặng, cắm sạc, không chạy việc khác cùng lúc.
Dữ liệu vừa sinh nằm sẵn trong cache RAM của Windows (cache nóng), điều kiện này giống nhau cho v1 và v2.

## 4. Quét cấu hình v2 (tuần 7) — `sweep_v2.py`

```powershell
.venv\Scripts\python.exe bench\sweep_v2.py                                   # 200MB, avg 256K..4M x zstd 0/1/3/9
.venv\Scripts\python.exe bench\sweep_v2.py --size 500MB --avg 512,1024,2048 --levels 1,3
```

- Mỗi tổ hợp **kích thước mẩu trung bình × mức nén** dùng một kho mới và một bản sao mới của cùng bộ dữ liệu,
  chạy full → mutate 5% → mutate 5%. Mẩu: `min = avg/2`, `max = avg×8` (tỉ lệ như mặc định 512K/1M/8M).
  Mức nén `0` = không nén.
- Mức nén được ghi vào `config` của kho (`compression.level`) và áp dụng mỗi khi mở kho, nên đổi cấu hình
  không cần sửa mã nguồn: `init_repo(..., zstd_level=N)`.
- Ghi `bench\results\v2_sweep.csv`, cột `phien_ban` dạng `v2 avg=1024K zstd=3`. Cuối cùng in bảng: thời gian full,
  thời gian trung bình 2 lần tăng dần, byte gửi lần 2+3, dung lượng kho cuối, tỉ lệ = dữ liệu logic của 3 snapshot
  chia dung lượng kho.

## 5. So với restic — `bench_restic.py` (TÔI PHẢI TỰ CHẠY)

Script **không tự tải restic**. Tự tải bản chính thức ở <https://github.com/restic/restic/releases>
(file `restic_<phiên bản>_windows_amd64.zip`, kiểm tra với `SHA256SUMS`), giải nén rồi:

```powershell
.venv\Scripts\python.exe bench\bench_restic.py --restic D:\tools\restic.exe
```

- Cùng seed/size/kịch bản 3 lần như `bench_v2.py`; kho restic local với mặc định của restic (repo v2, nén zstd
  `auto`, pack 16 MiB); cache restic để trong thư mục làm việc rồi xoá cùng.
- `byte_gui` = `data_added_packed` trong summary `--json` (restic ≥ 0.17; bản cũ hơn dùng `data_added`, ghi rõ
  trong `ghi_chu`). `byte_doc` = byte **tiến trình restic** đọc (bộ đếm IO của Windows).
- Khôi phục snapshot cuối và so `digest`. Ghi `bench\results\restic.csv`.
- Không tìm thấy restic → dừng với mã 3, không ghi dòng nào.
