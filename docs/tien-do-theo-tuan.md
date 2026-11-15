# Tiến độ theo tuần — đối chiếu kế hoạch ↔ phiếu theo dõi ↔ code

Ba nguồn phải khớp nhau:

| Nguồn | Ở đâu | Dùng để |
|---|---|---|
| Kế hoạch 10 tuần (A = lõi dữ liệu, B = mạng/bảo mật/vận hành) | `Ke-hoach-DACN-DACS-v2.xlsx` | biết tuần nào làm gì |
| Phiếu theo dõi tiến độ (GVHD ký từng tuần) | `2_Phieu_theo_doi_tien_do_DACN.doc`, tuần 1 = 17/10/2026, tuần 8 = **05/12/2026** (mốc đánh giá %) | ghi mỗi tuần 3 dòng |
| Code | commit `tuanN: …` trong repo này | chứng minh |

Mỗi tuần dưới đây ghi: việc theo kế hoạch → file/commit → lệnh kiểm chứng (chạy được ngay trên 1 máy).

## Tuần 1 (17/10) — Đo nền, nối máy, thiết kế kho

| Việc | Code / tài liệu | Kiểm chứng |
|---|---|---|
| A: đo tốc độ v1 trên bộ dữ liệu mẫu 3 lần | `bench/bench_v1.py`, `bench/results/v1.csv` | `python bench\bench_v1.py --ref v1-goc` |
| A: viết `repo-format.md` (pack, mẩu, snapshot) | `docs/repo-format.md` | đọc |
| A: thử VSS trên PC | `scripts/vss_test.ps1`, `docs/vss-test.md` | PowerShell admin |
| B: Tailscale 3 máy, tài khoản cloud, iperf3 | việc vận hành (ghi số đo vào `docs/tuan7-thi-nghiem.md` E6) | `tailscale status`, `iperf3 -c <IP PC>` |

## Tuần 2 (24/10) — Lõi cắt–mã hoá, dịch vụ trên PC, API kho

| Việc | Code | Kiểm chứng |
|---|---|---|
| A: FastCDC + AES-GCM + pack + 6 test bắt buộc | `core/` | `python -m pytest -s tests\test_core_required.py` |
| B: cài SQL Server Express, IIS, SMB share, dữ liệu mẫu | việc vận hành trên PC; dữ liệu mẫu: `bench\make_dataset.py` | `python bench\make_dataset.py --out D:\DuLieu --size 500MB` |
| B: script tạo tải giả | `bench\make_dataset.py --mutate 5 --round N` (3 mức: `--size`/`--mutate`) | như trên |
| **B: API kho, 4 lệnh, không có lệnh xoá** | `kho/app.py`, `kho/__main__.py`, `kho/start_kho.bat` | `python -m pytest tests\test_kho_api.py` |

## Tuần 3 (31/10) — Backup thật qua WAN, mTLS, firewall

| Việc | Code | Kiểm chứng |
|---|---|---|
| A: agent chỉ gửi mẩu thiếu, đứt mạng thì gửi tiếp | `core/repo_http.py`, `core/repository.py` | `tests\test_tuan3_http.py` |
| A: giới hạn tốc độ (token bucket, giờ hành chính) | `core/ratelimit.py`, `config/gioi_han_toc_do.json` | `tests\test_tuan3_ratelimit.py` |
| A: lịch backup SQL Server Full/Diff/Log | `scripts/sql/*.ps1`, `*.sql` | `tests\test_tuan3_sql.py` |
| **B: Caddy mTLS kiểu gọn, cấp/thu hồi chứng chỉ** | `deploy/kho/Caddyfile`, `deploy/kho/make_certs.ps1` | `tests\test_deploy_kho.py` (mTLS thật bằng openssl) |
| **B: firewall mặc định chặn, icacls cấm xoá, chạy kho thành dịch vụ** | `deploy/kho/tuong_lua.ps1`, `deploy/kho/cai_dat_kho.ps1` | `-PrintOnly`; trên PC: `icacls D:\kho-v2\packs` |
| Hướng dẫn B | `docs/tuan3-kho-mtls.md`, checklist A `docs/tuan3-chay-that.md` | |

## Tuần 4 (07/11) — Khôi phục, web quản trị (mốc giữa kỳ)

| Việc | Code | Kiểm chứng |
|---|---|---|
| A: khôi phục từng file (chỉ tải đúng mẩu, so SHA-256) | `core/repository.py` (`restore --include`, `_RangeFetcher`) | `tests\test_tuan4_restore_file.py` |
| A: khôi phục CSDL về một thời điểm | `scripts/sql/restore_pitr.ps1` | `tests\test_tuan3_sql.py::test_khoi_phuc_ve_thoi_diem_chon_dung_file` |
| A: áp cấu hình mạng lên máy khác | `agent/netplan.py` | `tests\test_tuan4_netplan.py` |
| **B: trang web: danh sách máy, snapshot, RPO xanh/vàng/đỏ, tỉ lệ dedup** | `server/monitor.py`, `server/static/js/views_v2.js`, `server/server.py` (`/api/ui/overview`, `/api/ui/kho`) | `tests\test_tuan4_tong_quan.py`; mở web → Tổng quan |
| Demo: xoá 1 thư mục rồi khôi phục | web: Bản sao lưu → Chạy thử → Khôi phục | `docs/demo-tuan-8.md` mục K3 |

## Tuần 5 (14/11) — Lưu giữ, dọn dẹp, cloud bất biến

| Việc | Code | Kiểm chứng |
|---|---|---|
| A: tự xoá bản hết hạn (24 giờ / 7 ngày / 4 tuần / 3 tháng, chạy thử trước) | `core/prune.py` | `tests\test_tuan5_prune.py`; `python -m core prune --repo D:\kho-v2` |
| **B: rclone đẩy lên bucket Object Lock 30 ngày, hằng ngày** | `deploy/cloud/day_len_cloud.ps1`, `rclone.conf.example` | `tests\test_tuan5_cloud.py`; trên PC có tài khoản: `-Register` |
| **B: thử xoá bản đang khoá → bị từ chối, chụp lại** | `deploy/cloud/thu_xoa_bi_tu_choi.ps1` | chạy với bucket thật (B2/S3/MinIO) |
| Hướng dẫn | `docs/tuan5-cloud-object-lock.md` | |

## Tuần 6 (21/11) — Cổng chặn bất thường, Telegram, tự kiểm tra

| Việc | Code | Kiểm chứng |
|---|---|---|
| A+B: cổng chặn bất thường (tỉ lệ file đổi, entropy, file mồi) | `core/anomaly.py`; agent báo "BẤT THƯỜNG" → sự kiện đỏ | `tests\test_tuan6.py`; demo K1 |
| A: tự khôi phục thử mỗi tuần, so hash | `core/cli.py verify`, job `verify` từ web/lịch (`agent/agent.py`, `server/scheduler.py`) | Cài đặt → Khôi phục thử ngay; Lịch → Việc: Khôi phục thử |
| **B: bot Telegram, nút Bình thường / Sự cố** | `server/notify.py`, `server/static/js/views_v2.js` (Thông báo, Cài đặt Telegram), `/api/notify` | `tests\test_tuan6_telegram.py`; Cài đặt → Gửi tin thử |
| B: RPO đổi màu → báo | `server/monitor.py::RpoMonitor` | `tests\test_tuan6_telegram.py::test_rpo_monitor_bao_khi_doi_mau` |
| Báo kết quả CSDL/cloud lên web | `scripts/sql/verify_sql_restore.ps1 -NotifyUrl`, `deploy/cloud/day_len_cloud.ps1 -NotifyUrl` | |

## Tuần 7 (28/11) — Thí nghiệm, siết bảo mật, K3/K6/K7

| Việc | Code | Kiểm chứng |
|---|---|---|
| A: E1–E4 (v1, v2, restic; kích thước mẩu × mức nén) | `bench/bench_v2.py`, `bench/sweep_v2.py`, `bench/bench_restic.py`, `bench/results/*.csv` | `docs/tuan7-thi-nghiem.md` (còn: chạy restic khi có `restic.exe`) |
| B: siết bảo mật, E6 | `deploy/kho/tuong_lua.ps1`; nmap/Wireshark/iperf3 là việc đo trên máy thật | ghi số vào `docs/tuan7-thi-nghiem.md` |
| K6 đứt mạng, K7 chiếm băng thông, K8 sửa 1 byte | `bench/dien_tap.py k6/k7/k8` | `tests\test_dien_tap.py` |
| K3 xoá nhầm → PITR | `scripts/sql/restore_pitr.ps1`, web khôi phục thư mục | `docs/tuan3-chay-that.md` §9 |

## Tuần 8 (05/12) — Diễn tập sự cố lớn, đóng gói, DEMO

| Việc | Code | Kiểm chứng |
|---|---|---|
| **K1 khôi phục sau ransomware** | `bench/dien_tap.py k1`; demo sống: `deploy/demo/gia_ransomware.ps1` + web | `tests\test_dien_tap.py::test_k1_*` |
| **K2 dựng lại CHỈ CSDL + thư mục chia sẻ trên máy khác** | `bench/dien_tap.py k2 [--sql-dir --sql-instance] [--share]` | `tests\test_dien_tap.py::test_k2_*` |
| **K5 xoá backup phải bị từ chối** | `bench/dien_tap.py k5 --repo http://127.0.0.1:8080` (kho thật) | `tests\test_kho_api.py::test_dien_tap_k5_vao_kho_that_*` |
| K4 dựng lại từ cloud, K8 sửa 1 byte (nếu còn giờ) | `docs/tuan5-cloud-object-lock.md` §K4; `dien_tap.py k8` | |
| **Đóng gói bộ cài** | `install.bat`, `deploy/kho/cai_dat_kho.ps1`, `deploy/agent/cai_dat_agent.ps1`, `deploy/demo/chuan_bi_demo.ps1` + `demo_1_may.bat` | chạy trên máy demo |
| Kịch bản demo cho thầy | `docs/demo-tuan-8.md` | tập trước ít nhất 2 lần |

## Tuần 9–10 — Số liệu, runbook, slide (chưa làm, ngoài phạm vi tuần 8)

CSV đã có trong `bench/results/` (E1–E4, K6–K8); K1/K2/K5 ghi vào `dien_tap.csv` khi chạy. Runbook mỗi sự cố viết từ các bước
trong `docs/demo-tuan-8.md` và `docs/tuan3-chay-that.md`.

---

## Phiếu theo dõi tiến độ — nội dung đề xuất cho tuần 6, 7, 8

Viết theo đúng giọng các tuần 1–5 đã ghi (3 dòng, bắt đầu bằng gạch ngang):

**Tuần 6 — 21/11/2026**

- Xây dựng cổng chặn bất thường trước khi gửi: so số file thay đổi, độ ngẫu nhiên (entropy), file mồi; kiểm thử với dữ liệu giả ransomware.
- Làm bot Telegram báo kết quả sao lưu và cảnh báo RPO, kèm nút Bình thường / Sự cố để quản trị xác nhận; đồng bộ với trang Thông báo.
- Tự khôi phục thử hằng tuần (vài file và CSDL), so hash, báo kết quả qua web và Telegram.

**Tuần 7 — 28/11/2026**

- Chạy thí nghiệm E1–E4: so v1, v2 và restic trên cùng dữ liệu; thử kích thước mẩu và mức nén để chọn cấu hình.
- Siết bảo mật và đo mạng (E6): tường lửa mặc định chặn, quét cổng, bắt gói xác nhận dữ liệu đã mã hoá, đo tốc độ qua Tailscale.
- Diễn tập K3 (xoá nhầm, khôi phục CSDL về đúng thời điểm), K6 (đứt mạng giữa chừng), K7 (chiếm băng thông).

**Tuần 8 — 05/12/2026**

- Diễn tập K1 (khôi phục sau ransomware), K2 (dựng lại CSDL và thư mục chia sẻ trên máy khác), K5 (xoá backup bị từ chối).
- Hoàn thiện trang tổng quan: RPO xanh/vàng/đỏ, tỉ lệ khử trùng lặp, thông báo; đóng gói bộ cài agent và kho.
- Chạy demo trọn vòng sao lưu – khôi phục trước giảng viên; tổng kết tiến độ.

## Việc còn mở (phải làm trên máy thật, chưa có trong code)

- Chạy thật laptop → PC qua Tailscale với Caddy mTLS (`docs/tuan3-chay-that.md`, `docs/tuan3-kho-mtls.md`): cần Tailscale + `caddy.exe` trên PC.
- Tài khoản cloud Object Lock (B2/AWS cần thẻ) hoặc MinIO cục bộ để chạy `day_len_cloud.ps1` và bài thử xoá.
- Token bot Telegram (BotFather) → dán vào Cài đặt.
- `restic.exe` để chạy `bench_restic.py`; E6 (iperf3, nmap, Wireshark) đo trên 2 máy.
- SQL Server Express trên PC demo (máy phát triển chỉ có LocalDB; các script nhận `-Instance "(localdb)\MSSQLLocalDB"`).
