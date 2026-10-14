# Tuần 3 — Chạy thật laptop → kho trên PC qua Tailscale

> **TÔI PHẢI TỰ CHẠY.** Số đo phải lấy từ lần chạy thật này, không dùng số của bench local.
> Cần: API kho của **Người B** đã chạy trên PC, đứng sau Caddy mTLS, theo `docs/repo-format.md` (§10.1 + §10.2).
> Code client đã có sẵn: `python -m core ... --repo https://...`. Stub trong `tests/stub_repo_server.py` **chỉ để test**.

## 0. Chuẩn bị (một lần)

- [ ] Hai máy cùng tailnet: `tailscale status` thấy nhau. Ghi IP Tailscale của PC: `100.____.____.____`
- [ ] B gửi 3 file mTLS cho laptop, chép vào `C:\backup-certs\`:
      `client.pem`, `client.key` (chứng chỉ client của laptop), `ca.pem` (CA để xác minh Caddy)
- [ ] Trên laptop: `cd <repo>` → `install.bat`
- [ ] Bộ dữ liệu mẫu (cùng seed với bench để so được):
  ```bat
  .venv\Scripts\python bench\make_dataset.py --out D:\bench-data\du_lieu --size 500MB --seed 2026
  ```
- [ ] Đặt biến cho phiên CMD (đường dẫn theo máy của bạn):
  ```bat
  set KHO=https://100.x.y.z:8443
  set TLS=--cert C:\backup-certs\client.pem --key C:\backup-certs\client.key --ca C:\backup-certs\ca.pem
  set BACKUP_V2_PASSWORD=<mật khẩu kho - ghi ra giấy, cất két>
  ```

## 1. Init kho

```bat
.venv\Scripts\python -m core init --repo %KHO% %TLS%
```
- [ ] Kiểm tra trên PC: thư mục kho có `config` và `keys\<64 hex>`.
- [ ] Thử sai chứng chỉ (bỏ `%TLS%`) → phải báo lỗi TLS/mTLS. Chụp màn hình.

## 2. Backup lần đầu (full)

```bat
.venv\Scripts\python -m core backup --repo %KHO% %TLS% D:\bench-data\du_lieu --log-file D:\bench-data\lan1.log -v
```
- [ ] Ghi: thời gian (dòng cuối), "gửi … MB", số pack mới.

## 3. Mutate 5% rồi backup lần 2

```bat
.venv\Scripts\python bench\make_dataset.py --out D:\bench-data\du_lieu --mutate 5 --round 1 --seed 2026
.venv\Scripts\python -m core backup --repo %KHO% %TLS% D:\bench-data\du_lieu --log-file D:\bench-data\lan2.log -v
```
- [ ] Ghi: thời gian, "mẩu mới x/y", "gửi … MB". Kỳ vọng gửi ~35 MB thay vì ~325 MB như v1.

## 4. Rút dây mạng giữa chừng

```bat
.venv\Scripts\python bench\make_dataset.py --out D:\bench-data\du_lieu --mutate 5 --round 2 --seed 2026
.venv\Scripts\python -m core backup --repo %KHO% %TLS% D:\bench-data\du_lieu --log-file D:\bench-data\lan3.log -v
```
- [ ] Khi log hiện vài dòng `Gửi pack …`: tắt Wi-Fi / `tailscale down` (hoặc rút dây). Client thử lại 6 lần (1, 2, 4… giây) rồi báo lỗi.
- [ ] `snapshots` **không** có snapshot mới (chưa ai thấy bản dở dang):
  ```bat
  .venv\Scripts\python -m core snapshots --repo %KHO% %TLS%
  ```
- [ ] Bật lại mạng, chạy **lại đúng lệnh backup**. Log: chỉ gửi các mẩu còn thiếu, không gửi lại pack đã lên.
      Ghi "gửi … MB" của lần chạy lại (phải nhỏ hơn lần 2).

## 5. Giới hạn tốc độ giờ hành chính (tuỳ chọn, cho K7 tuần 7)

```bat
.venv\Scripts\python -m core backup --repo %KHO% %TLS% D:\bench-data\du_lieu --limit 2MB/s -v
.venv\Scripts\python -m core backup --repo %KHO% %TLS% D:\bench-data\du_lieu --limit-schedule config\gioi_han_toc_do.json -v
```
- [ ] Đo tốc độ thực (Task Manager → Ethernet/Wi-Fi) trong giờ 08:00–17:30 thứ 2–6: ≈ 2 MB/s.

## 6. Khôi phục + kiểm tra

```bat
.venv\Scripts\python -m core restore --repo %KHO% %TLS% latest --target D:\bench-data\khoi_phuc
.venv\Scripts\python bench\make_dataset.py --out D:\bench-data\khoi_phuc\du_lieu --digest
.venv\Scripts\python bench\make_dataset.py --out D:\bench-data\du_lieu --digest
.venv\Scripts\python -m core check --repo %KHO% %TLS%
```
- [ ] Hai `digest` giống nhau. `check` in "Kho toàn vẹn".

## 7. Ghi CSV

Mỗi lần chạy, thêm một dòng vào `bench\results\v2_mang.csv` (cùng cột với `bench/common.py`):
`thoi_gian, phien_ban=v2-mang, lan_chay, giay, byte_doc, byte_gui, dung_luong_kho, may, kich_thuoc_du_lieu, so_file, mo_ta, ghi_chu`.
Lấy `giay` / `byte_gui` từ dòng tổng kết của lệnh backup. Lấy `dung_luong_kho` trên PC:
`(Get-ChildItem <thư mục kho> -Recurse -File | Measure-Object Length -Sum).Sum`.
Trong `ghi_chu` ghi rõ: Wi-Fi hay dây, tốc độ iperf3 đo ở tuần 1, có rút mạng không.

## 8. SQL Server trên PC (3e)

PowerShell **Administrator** trên PC có SQL Server Express:
```powershell
powershell -ExecutionPolicy Bypass -File scripts\sql\register_tasks.ps1 -Database ShopDB -Instance "localhost\SQLEXPRESS" -OutDir D:\SQLBackup
```
- [ ] Task Scheduler → `\BackupSystem\`: có 3 task Full (CN 01:00), Diff (T2–T7 01:30), Log (15 phút).
- [ ] Chờ ít nhất 1 Full + 1 Diff (hoặc chạy tay task Diff) + vài Log. Xem `D:\SQLBackup\sql_backup.log` và
      thư mục `D:\SQLBackup\ShopDB\` có `*_FULL_*.bak`, `*_DIFF_*.bak`, `*_LOG_*.trn`.
- [ ] Đưa `D:\SQLBackup` vào backup v2: `python -m core backup --repo ... D:\SQLBackup`.
- [ ] Chụp màn hình Task Scheduler + thư mục backup.

## Cần thống nhất với B trước khi chạy

- [ ] Đường dẫn gốc API (`BASE`) và cổng Caddy, ví dụ `https://100.x.y.z:8443`.
- [ ] Các lệnh §10.2 (`GET /snapshots`, `POST /chunks/locate`, `GET/PUT /config`, `/keys`): **bắt buộc** cho `init`, `snapshots`, `restore`.
- [ ] Mã lỗi khi đĩa đầy (`507`) và giới hạn kích thước (`413`), client đang làm đúng theo §10.
- [ ] Caddy cho phép body tới 64 MiB (pack) và 256 MiB (snapshot); timeout đọc ≥ 120 s.
