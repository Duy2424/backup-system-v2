# Tuần 5 (Người B) — Bản sao bất biến lên cloud (Object Lock)

Kế hoạch: *mỗi ngày dùng rclone đẩy một bản lưu riêng lên bucket Object Lock, khoá 30 ngày; bản cũ tự hết hạn rồi tự xoá*
và *thử xoá bản đang bị khoá, phải bị từ chối, chụp lại*. Script: `deploy/cloud/`.

Ý tưởng: kho v2 chỉ gồm file đặt tên theo SHA-256 (pack, snapshot, key, config) và **không bao giờ đổi nội dung**,
nên chỉ cần `rclone copy` (không `sync`, không xoá) với `--immutable`. Mỗi file lên cloud tự bị khoá 30 ngày theo
*default retention* của bucket; hết hạn thì lifecycle của bucket tự xoá. Không phải viết logic gia hạn khoá hay dọn dẹp.

## Chuẩn bị tài khoản (một lần)

**Backblaze B2** (rẻ, 10 GB miễn phí, cần thẻ quốc tế để kích hoạt Object Lock):

1. Tạo bucket **Private**, tick **Enable Object Lock** ngay khi tạo (không bật được sau).
2. Bucket Settings → *Default Retention*: **Compliance, 30 ngày**. Lifecycle: *Keep only the last version* để file hết khoá tự dọn.
3. App Keys → *Add a New Application Key*: chỉ cho bucket này, capabilities `listBuckets, listFiles, readFiles, writeFiles`
   (**bỏ `deleteFiles`**): kể cả key bị lộ cũng không xoá được; Object Lock là lớp cuối.
4. Trên PC: cài rclone (rclone.org/downloads), chép `deploy\cloud\rclone.conf.example` thành `%APPDATA%\rclone\rclone.conf`,
   điền `account` = keyID, `key` = applicationKey. Thử: `rclone lsd b2kho:`.

**AWS S3**: bucket bật *Versioning* + *Object Lock*, default retention COMPLIANCE 30 ngày; IAM user chỉ có
`s3:PutObject, s3:GetObject, s3:ListBucket` (không `DeleteObject*`). Remote `[s3kho]` trong file mẫu.

**Chưa có thẻ, cần demo ngay**: MinIO chạy trên PC (một file `minio.exe`), bucket `--with-lock`, retention COMPLIANCE 30 ngày
(lệnh trong `rclone.conf.example`, remote `[miniokho]`, `-Backend S3`). Cơ chế Object Lock giống S3.

## Đẩy lên hằng ngày

```powershell
# chạy tay một lần để xem log
powershell -ExecutionPolicy Bypass -File deploy\cloud\day_len_cloud.ps1 -KhoDir D:\kho-v2 -Remote b2kho:ten-bucket/kho
# đăng ký lịch 02:30 mỗi ngày (PowerShell quyền Administrator), báo kết quả lên web + Telegram
powershell -ExecutionPolicy Bypass -File deploy\cloud\day_len_cloud.ps1 -KhoDir D:\kho-v2 -Remote b2kho:ten-bucket/kho -Register `
    -NotifyUrl "http://127.0.0.1:5000/api/notify?token=<AGENT_TOKEN>"
```

Script làm: `rclone copy --immutable --checksum` (bỏ `tmp\ logs\ locks\`) → `rclone check --one-way` (so hash mọi file) →
in JSON kết quả, ghi log `D:\kho-v2\logs\cloud_<thời gian>.log`, POST tới `/api/notify` (mục Thông báo + Telegram).
Lưu ý khi `python -m core prune --apply` xoá pack cục bộ: cloud **không** xoá theo (copy không xoá); file hết khoá 30 ngày
thì bucket tự dọn. Trong 30 ngày đó cloud vẫn giữ đủ để dựng lại.

## Thử xoá bản đang bị khoá (bắt buộc chụp màn hình)

```powershell
powershell -ExecutionPolicy Bypass -File deploy\cloud\thu_xoa_bi_tu_choi.ps1 -Remote b2kho:ten-bucket/kho -Report D:\kho-v2\logs\k5_cloud.json
```

Script lấy một pack trên cloud, **xoá hẳn** (`--b2-hard-delete`; S3: `--s3-versions`), mong đợi rclone báo lỗi
(`file is locked` / `AccessDenied`) và file vẫn còn → in `KET LUAN: TU CHOI`. Chụp màn hình + file JSON đưa vào báo cáo
(kịch bản K5 phần cloud; K5 phần API kho xem `bench\dien_tap.py k5`).

Lưu ý đọc kết quả: lệnh xoá *không* kèm version (B2 "hide", S3 "delete marker") có thể thành công nhưng chỉ *ẩn* file,
phiên bản bị khoá vẫn còn và khôi phục được; không phải lỗ hổng. Script vì vậy luôn xoá kiểu *hard delete*.

## K4 (nếu còn giờ, tuần 8): dựng lại từ cloud

```powershell
rclone copy b2kho:ten-bucket/kho D:\kho-tu-cloud --checksum --transfers 8
.venv\Scripts\python -m core check     --repo D:\kho-tu-cloud                 # kho toàn vẹn?
.venv\Scripts\python -m core snapshots --repo D:\kho-tu-cloud
.venv\Scripts\python -m core restore   --repo D:\kho-tu-cloud latest --target E:\KhoiPhuc
```

Cần mật khẩu kho (chỉ người quản trị giữ): cloud chỉ thấy pack đã mã hoá, không đọc được nội dung.

## Kiểm chứng tự động

`python -m pytest -q tests\test_tuan5_cloud.py`: script sinh đúng `rclone copy ... --immutable` (không `sync`, không `delete`),
loại trừ `tmp/ logs/ locks/`, có `check --one-way`, đăng ký đúng task hằng ngày; bài thử xoá dùng *hard delete* đúng theo backend.
