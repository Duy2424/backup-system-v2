# Tuần 2–3 (Người B) — API kho thật, Caddy mTLS, cấm xoá, tường lửa

Phần "kho" trong kế hoạch tuần 2 (API kho, không có lệnh xoá) và tuần 3 (mTLS kiểu gọn bằng Caddy;
firewall mặc định chặn; `icacls` cấm tài khoản kho xoá file; chạy kho thành dịch vụ). Code: `kho/`, script: `deploy/kho/`.

## Kiến trúc trên PC

```
 laptop / agent ──(Tailscale 100.x)──► :8443 Caddy ──mTLS──► 127.0.0.1:8080  python -m kho  ──► D:\kho-v2\
                                        │ bắt buộc chứng chỉ client                          │ chỉ THÊM file
                                        │ (allow-list clients.caddy)                         │ icacls deny Delete
                                        └ header X-Client-Subject ────────────────────────► ghi log ai gọi
```

Ba lớp chống xoá/ghi đè:

| Lớp | Ở đâu | Chặn gì |
|---|---|---|
| API | `kho/app.py` | Không có `DELETE`; `PUT` trùng id bỏ qua; mọi method khác → 405 |
| NTFS | `cai_dat_kho.ps1` | Tài khoản chạy kho (`LOCAL SERVICE`) bị deny `Delete` trên `packs\ snapshots\ keys\ config` |
| Mạng | Caddy + `tuong_lua.ps1` | Chỉ máy có chứng chỉ client hợp lệ, chỉ qua cổng 8443 trên card Tailscale |

## Cài trên PC (một lần, PowerShell quyền Administrator)

```powershell
cd D:\backup-system-v2
install.bat                                                           # .venv + thư viện
powershell -ExecutionPolicy Bypass -File deploy\kho\cai_dat_kho.ps1 -KhoDir D:\kho-v2
```

`cai_dat_kho.ps1` tạo thư mục kho, đặt quyền NTFS, đăng ký Scheduled Task `\BackupSystem\BackupKho`
(chạy lúc khởi động bằng `NT AUTHORITY\LOCAL SERVICE`, tự khởi động lại), rồi gọi `http://127.0.0.1:8080/health`.
Có `nssm.exe` thì thêm `-UseNssm` để cài thành Windows Service thật. Gỡ: `-Uninstall`.

Khởi tạo kho (mật khẩu kho **chỉ** người quản trị giữ, server web không bao giờ biết):

```powershell
.venv\Scripts\python -m core init --repo http://127.0.0.1:8080
```

## mTLS bằng Caddy

1. Tải `caddy.exe` bản chính thức (caddyserver.com/download), đặt vào `D:\tools\caddy.exe`.
2. Cấp chứng chỉ (openssl có sẵn trong Git for Windows):
   ```powershell
   powershell -ExecutionPolicy Bypass -File deploy\kho\make_certs.ps1 -InitCA
   powershell -ExecutionPolicy Bypass -File deploy\kho\make_certs.ps1 -Server -San "IP:100.x.y.z,DNS:pc-kho"   # IP Tailscale của PC
   powershell -ExecutionPolicy Bypass -File deploy\kho\make_certs.ps1 -Client laptop-duy
   ```
   Chép `laptop-duy.crt`, `laptop-duy.key`, `ca.crt` (trong `deploy\kho\certs\clients\`) sang laptop, ví dụ `C:\backup-certs\`.
3. Chạy Caddy thành dịch vụ nền cùng kho:
   ```powershell
   powershell -ExecutionPolicy Bypass -File deploy\kho\cai_dat_kho.ps1 -KhoDir D:\kho-v2 -CaddyExe D:\tools\caddy.exe
   ```
   (hoặc thử tay: `cd deploy\kho; D:\tools\caddy.exe run --config Caddyfile`)
4. Tường lửa: `powershell -ExecutionPolicy Bypass -File deploy\kho\tuong_lua.ps1` — mặc định chặn mọi kết nối vào,
   chỉ mở 8443 (kho) và 5000 (web) trên card `Tailscale`.

**Thu hồi một máy:** `make_certs.ps1 -Revoke laptop-cu` rồi khởi động lại task `BackupKhoCaddy`
(hoặc bỏ `admin off` trong Caddyfile và dùng `caddy reload`). Chứng chỉ cũ chuyển vào `certs\revoked\`.

## Từ laptop

```bat
set KHO=https://100.x.y.z:8443
set TLS=--cert C:\backup-certs\laptop-duy.crt --key C:\backup-certs\laptop-duy.key --ca C:\backup-certs\ca.crt
.venv\Scripts\python -m core snapshots --repo %KHO% %TLS%
.venv\Scripts\python -m core backup    --repo %KHO% %TLS% D:\DuLieu
.venv\Scripts\python -m core snapshots --repo %KHO%            rem KHÔNG có chứng chỉ -> phải báo lỗi TLS (chụp màn hình)
```

Agent chạy job từ web bằng kho này: trong `agent\agent_config.txt` đặt `ENGINE=v2`, `V2_REPO=https://100.x.y.z:8443`,
`V2_CERT/V2_KEY/V2_CA` trỏ tới 3 file trên, `V2_PASSWORD_FILE` trỏ tới file mật khẩu kho (chỉ ở máy agent).

## Kiểm chứng (đưa vào báo cáo)

- `python -m pytest -q tests\test_kho_api.py tests\test_deploy_kho.py` — 4 lệnh chính, mã lỗi theo hợp đồng, Range,
  **K5 chạy thẳng vào kho thật** (DELETE/PUT ghi đè/POST/PATCH/MOVE đều bị từ chối, dữ liệu nguyên vẹn),
  và mTLS thật bằng chứng chỉ do `make_certs.ps1` cấp (không có chứng chỉ → bị từ chối).
- Trên PC: `icacls D:\kho-v2\packs` phải có dòng `NT AUTHORITY\LOCAL SERVICE:(OI)(CI)(DENY)(D,DC)`.
- Log kho `D:\kho-v2\logs\kho.log` ghi từng lệnh kèm subject chứng chỉ, ví dụ `CN=laptop-duy,O=Backup System PUT /packs/… -> 201`.
- `GET /health`, `GET /stats` (thêm ở tuần 4 cho trang tổng quan): số pack/snapshot, dung lượng trên đĩa, số lệnh bị từ chối.

## Những điểm [CẦN B CHỐT] trong `docs/repo-format.md` — đã chốt

| Mục | Quyết định |
|---|---|
| §10.1 bốn lệnh chính + mã lỗi | Đúng như hợp đồng; thân lỗi `{"error","message"}` (client đọc `message`) |
| §10.2 lệnh đọc bổ sung | Làm đủ (`GET /snapshots`, `/snapshots/<id>`, `POST /chunks/locate`, `GET|PUT /config`, `GET /keys`, `GET|PUT /keys/<id>`) |
| Giới hạn | 10 000 ID/lần, pack ≤ 64 MiB, snapshot ≤ 256 MiB, config/key ≤ 1 MiB |
| Ghi tạm → đổi tên, index sau đổi tên, quét bổ sung khi khởi động | Dùng `core.repo_local.LocalRepo` (hard link, không ghi đè); khởi động đọc footer + bảng ID mọi pack |
| Header `X-Client-Subject` | Có, Caddy chuyển subject chứng chỉ, kho ghi log |
| Dọn bản hết hạn (§13) | `python -m core prune --apply` chạy **cục bộ trên PC** bằng tài khoản quản trị, trong giờ bảo trì, sau khi dừng task `BackupKho`; API vẫn không có lệnh xoá |
| Thêm mới | `GET /health`, `GET /stats` chỉ đọc (phục vụ trang tổng quan tuần 4) |
