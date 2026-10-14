# Giải pháp Backup toàn diện và hiệu quả cho doanh nghiệp

> Đồ án chuyên ngành — Chuyên ngành Mạng máy tính — Trường Đại học Công nghệ TP.HCM (HUTECH)
> Phát triển tiếp từ đồ án cơ sở của Đỗ Hồng Anh Duy (MSSV 2380603083, lớp 23DTHC3, GVHD Nguyễn Văn Cẩn).

Hệ thống sao lưu và khôi phục mô hình **server – agent** cho doanh nghiệp nhỏ. Ngoài file người dùng, hệ thống còn sao lưu
và khôi phục **cấu hình mạng và hệ thống Windows** (IPv4/IPv6, tường lửa, route, hosts, SMB share, portproxy, Defender,
SQL Server, Registry) — phần thường bị bỏ qua nhưng tốn thời gian nhất khi dựng lại máy chủ.

Bản hiện tại là **1.5 (v1 tối ưu)**, nền cho bản v2 (chia mẩu + khử trùng lặp, xem [`docs/repo-format.md`](docs/repo-format.md)).
Bản đồ án cơ sở gốc giữ ở tag `v1-goc` (dùng để đo so sánh: `python bench\bench_v1.py --ref v1-goc`).

---

## Mô hình triển khai

```
 Laptop (chỉ điều khiển)                     PC ở nhà (xử lý mọi thứ)
 ┌──────────────────────┐   Tailscale      ┌────────────────────────────────────────────┐
 │ Trình duyệt          │ ───────────────► │ server  : web điều khiển + REST API + kho    │
 │ http://100.x.y.z:5000│   (WireGuard)    │ agent   : sao lưu/khôi phục dữ liệu & cấu hình│
 └──────────────────────┘                  │           SQL Server, SMB share, IIS...      │
                                           └────────────────────────────────────────────┘
```

- **PC**: chạy `server` và `agent`. Kho file backup nằm trên PC (bản sao bất biến lên cloud ở tuần 5).
- **Laptop**: không cài gì, chỉ mở trình duyệt tới IP Tailscale của PC. Giao diện chạy offline (không CDN, không font ngoài).
- Agent có thể chạy thêm trên máy khác: đặt `SERVER_URL` trỏ về PC.

## Cài đặt (trên PC)

Yêu cầu: Windows 10/11 hoặc Windows Server, **Python 3.11**.

```bat
install.bat
```

`install.bat` tạo môi trường `.venv` và cài đúng phiên bản trong `requirements.txt` (máy không có Internet: chạy
`download_wheels.bat` ở máy có mạng rồi chép thư mục `wheels\` sang).

## Chạy

1. **Server** — `server\start_server.bat` (hoặc `.venv\Scripts\python -m server`).
   Lần đầu, mật khẩu `admin` được sinh ngẫu nhiên, in ra cửa sổ và lưu ở `instance\admin_password.txt`.
   Đăng nhập, đổi mật khẩu ở **Cài đặt**, rồi xoá file đó.
2. **Agent** — trên web vào **Cài đặt → Kết nối agent → Chép cấu hình**, dán vào `agent\agent_config.txt`,
   rồi chạy `agent\start_agent.bat` **bằng quyền Administrator** (khôi phục IP/tường lửa cần quyền này).
3. **Từ laptop** — mở `http://<IP Tailscale của PC>:5000`.

Biến môi trường tuỳ chọn (đặt trên PC):

| Biến | Ý nghĩa | Mặc định |
|---|---|---|
| `BACKUP_HOST` / `BACKUP_PORT` | Địa chỉ nghe của server | `0.0.0.0` / `5000` |
| `BACKUP_ADMIN_PASSWORD` | Mật khẩu admin lần khởi tạo đầu | sinh ngẫu nhiên |
| `BACKUP_SECRET_KEY` | Khoá phiên đăng nhập | sinh ngẫu nhiên, lưu `instance\secret_key` |
| `BACKUP_COOKIE_SECURE=1` | Bật khi truy cập qua HTTPS (vd sau Caddy) | tắt |
| `BACKUP_STORAGE_DIR`, `BACKUP_DB`, `BACKUP_WORK_DIR` | Đổi chỗ lưu kho / CSDL / file tạm | trong thư mục repo |

Tường lửa: chỉ mở cổng 5000 trên card Tailscale, không mở ra Internet.

## Bản 1.5 khác gì bản gốc

| | v1 gốc (`v1-goc`) | 1.5 |
|---|---|---|
| Đọc dữ liệu | băm 1 lượt + nén 1 lượt + đọc lại tar + đọc lại `.bkup` | **1 lượt** (băm, nén, mã hoá cùng lúc) |
| Gửi lên server | multipart, nạp cả file vào RAM | stream chunked, RAM cố định ~16 MB, không file tạm |
| Nén | gzip mức 6 (1 luồng) | zstd mức 3 (đa luồng) |
| Mã hoá | AES-256-CBC, **không xác thực** | AES-256-GCM theo đoạn 1 MiB: sửa/cắt file → phát hiện |
| Chụp cấu hình hệ thống | ~8 tiến trình PowerShell, 41 s (đo trên laptop) | 1 tiến trình, 8,4 s, xuất UTF-8 |
| Khôi phục | luôn xoá file thừa, băm lại mọi file | xoá file thừa là tuỳ chọn; so nhanh theo size+mtime; chạy thử; khôi phục ra thư mục khác |
| Mật khẩu | SHA-256 + salt | scrypt (tài khoản cũ tự nâng cấp khi đăng nhập) |
| API | token user A lấy được job + khoá mã hoá của user B; có lệnh xoá file backup | job tách theo user; **không có lệnh xoá**, không ghi đè |
| Web | Bootstrap qua CDN, tải lại trang | SPA không cần build, chạy offline, tiến độ trực tiếp, CSRF, giới hạn đăng nhập sai |

Số đo trên cùng bộ dữ liệu 500 MB (`bench/results/v1.csv`, laptop Ryzen 7 3750H):
bản gốc 53,9 s / 62,2 s / 71,4 s, bản 1.5 7,5 s / 9,2 s / 21,0 s (full / sau 5% thay đổi / sau 5% nữa).
Cả hai vẫn gửi lại toàn bộ mỗi lần (~324 MB) — giảm phần này là việc của v2.

Tương thích: file `.bkup` cũ (CBC + gzip) vẫn khôi phục được; CSDL cũ tự nâng cấp khi server khởi động.
Nếu dùng lại CSDL cũ, tài khoản mặc định `admin/admin123`, `user1/user123` vẫn còn — **đổi mật khẩu ngay**.

## Kiểm thử và đo đạc

```bat
.venv\Scripts\python -m pytest -q
.venv\Scripts\python bench\bench_v1.py                 rem đo bản hiện tại (500 MB, 3 lần)
.venv\Scripts\python bench\bench_v1.py --ref v1-goc    rem đo bản đồ án cơ sở gốc
```

Chi tiết: [`bench/README.md`](bench/README.md). Thử VSS trên PC: [`docs/vss-test.md`](docs/vss-test.md).
Thử khôi phục cấu hình mạng: thư mục [`test-scripts/`](test-scripts/) (`check_all.bat` → sao lưu → `doi_all.bat` → khôi phục → `check_all.bat`).

## Cấu trúc thư mục

```
backup-system/
├── server/            server.py (app + API), scheduler.py, static/ (CSS/JS giao diện), templates/app.html
├── agent/             agent.py (vòng poll), backup_logic.py, restore_logic.py, system_state.py,
│                      network_advanced.py, sql_registry.py, folder_browser.py, remote_storage.py, winexec.py
├── shared/            config.py, database.py, encryption_utils.py, snapshot.py, log.py, text.py
├── bench/             make_dataset.py, bench_v1.py, results/*.csv
├── tests/             pytest
├── docs/              repo-format.md (hợp đồng kho v2), vss-test.md, PRODUCT.md, lich-su/
├── scripts/           vss_test.ps1
├── test-scripts/      .bat đổi/kiểm tra cấu hình mạng để thử khôi phục
├── install.bat, download_wheels.bat, requirements.txt
```

## Hạn chế và hướng phát triển

- Mỗi lần vẫn là bản đầy đủ → v2: chia mẩu FastCDC, chỉ gửi mẩu mới, khoá mã hoá giữ ở client.
- Kho nằm trên chính PC → tuần 5: bản sao bất biến (Object Lock) lên cloud.
- Server dùng HTTP trong Tailscale (đã mã hoá bởi WireGuard) → tuần 3: Caddy mTLS.

*Đồ án phục vụ mục đích học tập.*
