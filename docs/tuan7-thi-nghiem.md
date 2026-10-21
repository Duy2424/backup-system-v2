# Tuần 7 — Thí nghiệm, chọn cấu hình, diễn tập K6/K7/K8

Kế hoạch tuần 7 (phần Người A): *chạy v1, v2, restic trên cùng dữ liệu; thử các kích thước mẩu và mức nén;
có số so với v1 và restic; chọn cấu hình tốt nhất*; diễn tập K3 (chính), K6, K7 nếu còn giờ.

Kế hoạch chỉ ghi "E1–E4" mà không định nghĩa từng mục. Dưới đây là **đề xuất** cách chia
(cả nhóm chốt lại trước khi đưa vào báo cáo):

| Mục | Đo gì | Nguồn số liệu | Script |
|---|---|---|---|
| E1 | Thời gian sao lưu full + 2 lần tăng dần | `v1.csv`, `v2.csv`, `restic.csv` | `bench_v1.py`, `bench_v2.py`, `bench_restic.py` |
| E2 | Byte gửi lên kho mỗi lần tăng dần (hiệu quả khử trùng lặp) | như E1 | như E1 |
| E3 | Dung lượng kho sau 3 lần, thời gian khôi phục + so digest | như E1 | như E1 |
| E4 | Kích thước mẩu × mức nén zstd → thời gian, byte gửi, dung lượng kho | `v2_sweep.csv` | `sweep_v2.py` |
| E6 | Băng thông mạng giữa 2 máy qua Tailscale (iperf3) | — | Người B / tự chạy |

Mọi CSV nằm trong `bench/results/`, cùng bộ cột (`bench/common.py`). Cột `ghi_chu` có `nguon=sac` hoặc
`nguon=pinNN%`: **chỉ so thời gian giữa các dòng cùng nguồn** (chạy pin thì Windows hạ xung CPU).

## 1. Quét kích thước mẩu × mức nén (E4)

```powershell
.venv\Scripts\python.exe bench\sweep_v2.py
```

Mỗi tổ hợp: kho mới + bản sao mới của cùng bộ dữ liệu 200 MB (seed 2026), full → mutate 5% → mutate 5%.
Mẩu `min = avg/2`, `max = avg×8`. Mức nén `0` = không nén. Mức nén được lưu trong `config` của kho
(`compression.level`) và áp dụng mỗi lần mở kho.

**Một lỗi đo đã gặp và đã sửa:** file vừa `copytree` lần đầu đọc chậm gấp ~6 lần
(31,8 s so với 5,2 s cho cùng 200 MB, nhiều khả năng do trình diệt virus quét file mới).
`sweep_v2.py` vì vậy đọc làm nóng bản sao một lượt trước khi bấm giờ, cùng điều kiện "cache nóng" như
`bench_v2.py`. Các dòng đo trước khi sửa đã bỏ, không đưa vào CSV.

### Kết quả (laptop Duy2424, 21/10/2026, **chạy pin 44% → 23%**, 200 MB, 2.082 file)

"tăng" = trung bình 2 lần sau mutate 5%; "tỉ lệ" = dữ liệu logic của 3 snapshot / dung lượng kho.

| avg mẩu | zstd | full (s) | tăng (s) | gửi lần 2+3 | kho cuối | tỉ lệ |
|---|---|---|---|---|---|---|
| 256K | 0 | 8,68 | 3,41 | 27,7 MiB | 224,9 MiB | 2,67× |
| 256K | 1 | 4,21 | 2,93 | 16,6 MiB | 145,6 MiB | 4,13× |
| 256K | 3 | 5,40 | 2,52 | 16,6 MiB | 145,9 MiB | 4,12× |
| 256K | 9 | 10,33 | 2,80 | 16,5 MiB | 144,8 MiB | 4,15× |
| 512K | 0 | 5,10 | 3,16 | 28,9 MiB | 226,2 MiB | 2,66× |
| 512K | 1 | 4,85 | 3,11 | 17,5 MiB | 146,5 MiB | 4,11× |
| 512K | 3 | 4,42 | 2,69 | 17,5 MiB | 146,5 MiB | 4,11× |
| 512K | 9 | 8,47 | 3,30 | 17,4 MiB | 145,5 MiB | 4,14× |
| 1024K (mặc định hiện tại) | 0 | 4,52 | 2,78 | 39,3 MiB | 236,5 MiB | 2,54× |
| 1024K | 1 | 4,25 | 2,65 | 23,6 MiB | 152,5 MiB | 3,95× |
| **1024K** | **3** | 4,83 | 2,71 | 23,6 MiB | 152,5 MiB | 3,94× |
| 1024K | 9 | 8,31 | 3,05 | 23,4 MiB | 151,4 MiB | 3,97× |
| 2048K | 0 | 4,87 | 3,08 | 56,8 MiB | 254,0 MiB | 2,37× |
| 2048K | 1 | 3,99 | 2,69 | 32,0 MiB | 160,9 MiB | 3,74× |
| 2048K | 3 | 5,01 | 2,99 | 32,1 MiB | 161,0 MiB | 3,74× |
| 2048K | 9 | 8,63 | 3,36 | 31,8 MiB | 159,8 MiB | 3,76× |
| 4096K | 0 | 4,16 | 3,13 | 81,9 MiB | 279,1 MiB | 2,16× |
| 4096K | 1 | 3,90 | 3,11 | 45,9 MiB | 174,8 MiB | 3,44× |
| 4096K | 3 | 5,10 | 3,00 | 46,1 MiB | 175,1 MiB | 3,44× |
| 4096K | 9 | 8,87 | 3,79 | 45,8 MiB | 173,7 MiB | 3,46× |

Số mẩu của bản full: 2.656 (256K), 2.358 (512K), 2.203 (1M), 2.135 (2M), 2.104 (4M). Gần như không đổi vì phần lớn
file nhỏ hơn `min` nên mỗi file là một mẩu.

**Đọc kết quả**

- **Nén:** bật zstd làm kho nhỏ đi khoảng 35% (225 → 146 MiB) và byte gửi nhỏ đi khoảng 40%. Mức 1 và 3 gần như bằng nhau
  (chênh ≤ 0,3 MiB). Mức 9 chỉ nhỏ thêm khoảng 0,7% nhưng full chậm gần gấp đôi ⇒ loại mức 9.
  Giữa mức 1 và 3, chênh thời gian (±0,6 s) nằm trong sai số khi chạy pin ⇒ chưa đủ cơ sở để đổi khỏi mức 3.
- **Kích thước mẩu:** mẩu càng nhỏ, lần tăng dần gửi càng ít: 512K gửi **17,5 MiB**, còn 1M (mặc định) gửi 23,6 MiB
  (ít hơn 26%); kho nhỏ hơn 4%. Từ 512K xuống 256K chỉ lợi thêm 5% (16,6 MiB).
  Thời gian của các cỡ mẩu chênh nhau không rõ (trong sai số).
- **Chi phí của mẩu nhỏ** (tính toán, không phải số đo): với dữ liệu là file lớn (file `.bak` SQL, ảnh máy ảo), mỗi
  1 TB ≈ 2 triệu mẩu ở 512K, hoặc 4 triệu ở 256K. Mỗi mẩu tốn khoảng 67 byte ID trong JSON snapshot ⇒ khoảng 134 MB
  (512K) hoặc 268 MB (256K) trước nén cho mỗi snapshot. Giới hạn snapshot trong hợp đồng là 256 MiB ⇒ 256K quá sát giới hạn.
- **Đề xuất:** `avg 512K (min 256K, max 4M) + zstd 3`. **Chưa đổi mặc định trong mã**, cần chạy lại `bench_v2.py`
  500 MB khi **cắm sạc** để README dùng cùng một cấu hình và cùng điều kiện máy (xem mục "Việc còn lại").

## 2. So với restic (E1–E3) — TÔI PHẢI TỰ CHẠY

Script không tự tải restic. Tải bản chính thức (github.com/restic/restic/releases, kiểm tra `SHA256SUMS`), rồi:

```powershell
.venv\Scripts\python.exe bench\bench_restic.py --restic D:\tools\restic.exe            # 500MB như v1/v2
```

Kết quả ghi `bench/results/restic.csv`; so cùng dòng `seed=2026 size=500MB` trong `v1.csv`, `v2.csv`.
Nên cắm sạc và chạy lại `bench_v2.py` ngay trước/sau đó để cả hai cùng điều kiện máy.

## 3. Diễn tập sự cố — `bench/dien_tap.py`

| Mã | Sự cố | Cách diễn tập | Phải thấy |
|---|---|---|---|
| K6 | Đứt mạng giữa chừng | Lần 1 bị cắt sau ~½ số pack → nối lại → lần 2 | Không có snapshot dở dang; lần 2 chỉ gửi phần còn thiếu; không mẩu nào gửi 2 lần; khôi phục khớp digest |
| K7 | Chiếm băng thông | Gửi với `--limit`, so với không giới hạn | Tốc độ gửi thực ≈ mức đặt (lệch ≤ 10–15 %) |
| K8 | Sửa 1 byte trong kho | Lật 1 bit ở vùng dữ liệu pack / bảng index pack / snapshot trên kho tạm | `check` nhanh và đầy đủ đều báo đúng chỗ; khôi phục từ chối; khôi phục riêng 1 file (đọc Range) cũng từ chối; trả byte lại thì kho sạch |

```powershell
.venv\Scripts\python.exe bench\dien_tap.py k8
.venv\Scripts\python.exe bench\dien_tap.py k6
.venv\Scripts\python.exe bench\dien_tap.py k7 --limit 4MB/s
```

Mặc định K6/K7 dùng **stub kho trên 127.0.0.1** (`tests/stub_repo_server.py`, không phải API thật của Người B);
"đứt mạng" = stub trả 503 cho mọi PUT pack sau N pack. Số đo ghi `bench/results/dien_tap.csv` với
`kho=stub-127.0.0.1` trong `ghi_chu`.

**Bản demo thật (quay video) — TÔI PHẢI TỰ CHẠY**, cần API kho của B đã chạy qua Tailscale và kho đã `init`:

```powershell
# K6: khi script báo, rút dây mạng hoặc `tailscale down`; đợi báo lỗi; cắm lại rồi nhấn Enter
.venv\Scripts\python.exe bench\dien_tap.py k6 --repo https://<IP Tailscale PC>:<cổng> --cert client.pem --key client.key --ca ca.pem --password-file C:\backup-secrets\v2.txt
# K7: trên máy khác chạy `iperf3 -c <IP PC> -t 60` cùng lúc để chiếm băng thông
.venv\Scripts\python.exe bench\dien_tap.py k7 --repo https://<IP Tailscale PC>:<cổng> --cert client.pem --key client.key --ca ca.pem --password-file C:\backup-secrets\v2.txt --limit 2MB/s
```

Với kho thật, script sinh bộ dữ liệu mới (seed theo giờ) để chắc chắn có dữ liệu mới phải gửi, và gắn tag
`dien-tap-k6` / `dien-tap-k7` cho snapshot. K8 chỉ chạy trên kho tạm, script từ chối `--repo`.

### Kết quả trên stub 127.0.0.1 (21/10/2026, chạy pin 15% → 10%; `bench/results/dien_tap.csv`)

**K8 — sửa 1 bit** (30 MB, 311 file):

| Chỗ sửa | check nhanh | check đầy đủ | khôi phục cả snapshot | khôi phục 1 file (Range) | trả byte lại |
|---|---|---|---|---|---|
| pack, vùng dữ liệu | bắt (0,14 s) | bắt (0,22 s) | từ chối | từ chối | kho sạch |
| pack, bảng index | bắt (0,06 s) | bắt (0,24 s) | từ chối | — | kho sạch |
| snapshot | bắt (0,06 s) | bắt (0,24 s) | từ chối | — | kho sạch |

Thông báo chỉ đúng pack/snapshot bị hỏng (`pack deb93e12c784: SHA-256 không khớp tên`). Khôi phục một file chỉ đọc
đúng mẩu qua Range, nên không đi qua bước kiểm SHA-256 cả pack; nhưng GCM của từng mẩu vẫn bắt được lỗi.

**K6 — đứt mạng** (100 MB, 1.020 file, pack 4 MiB):

| Lần | Thời gian | Gửi | Ghi chú |
|---|---|---|---|
| Đối chứng (không đứt) | 3,79 s | 63,2 MiB | 19 pack |
| Lần 1: đứt sau 9 pack | 6,29 s (gồm 3 lần tự thử lại) | 30,6 MiB | kho có **0 snapshot**, không ai thấy bản dở dang |
| Lần 2: sau khi nối lại | 2,46 s | 32,5 MiB | 82/1.078 mẩu mới; **0 mẩu gửi 2 lần**; tổng 2 lần / đối chứng = **1,000** |
| Khôi phục kiểm chứng | 24,5 s | — | digest khớp (stub dùng server dev của werkzeug, không đại diện cho tốc độ thật) |

**K7 — giới hạn băng thông** (40 MB, mỗi lần dùng dữ liệu khác nhau để phải gửi hết):

| Lần | Thời gian | Gửi | Trung bình cả lần chạy | Lúc đang PUT |
|---|---|---|---|---|
| Không giới hạn | 1,41 s | 27,0 MiB | 19,2 MiB/s | 45,5 MiB/s |
| Giới hạn 4 MB/s | 7,04 s | 28,0 MiB | **4,0 MiB/s (lệch −0,4%)** | 4,7 MiB/s |

Token bucket cho dồn tối đa 1 giây khi client đang bận chia mẩu, nên lúc PUT có thể nhanh hơn mức đặt khoảng 15%.
Tuy vậy, tính trung bình trên toàn lần chạy thì không vượt mức đặt.

## 4. Việc còn lại

- [ ] **Cắm sạc**, chạy lại `bench_v2.py` (500 MB) và `sweep_v2.py --size 500MB --avg 512,1024 --levels 1,3` để so
  thời gian giữa mức 1 và 3, rồi chốt có đổi mặc định sang 512K không (sửa `ChunkerParams`, `cli init`,
  `docs/repo-format.md` §2, README).
- [ ] Tải restic, chạy `bench_restic.py` (500 MB) — TÔI PHẢI TỰ CHẠY.
- [ ] Demo K6/K7 trên kho thật qua Tailscale + quay video — TÔI PHẢI TỰ CHẠY (cần API kho của B).
- [ ] E6 (iperf3) — B / tự chạy.
- [ ] K3 (xoá nhầm, khôi phục PITR SQL) đã có checklist trong `docs/tuan3-chay-that.md` §9 — TÔI PHẢI TỰ CHẠY trên PC.
- Đã viết sẵn cho tuần 8: `dien_tap.py k5` (xoá/ghi đè phải bị từ chối) — chạy trên stub đã có test; chạy với kho
  thật chỉ tấn công pack/snapshot của bộ dữ liệu thăm dò, không đụng config/key file.
