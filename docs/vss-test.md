# Thử VSS trên PC — đọc file Word đang mở

> **TÔI PHẢI TỰ CHẠY** trên PC (máy đóng vai máy chủ công ty), PowerShell **64-bit**, quyền **Administrator**.
> Script: [`scripts/vss_test.ps1`](../scripts/vss_test.ps1). Kết quả phải là ảnh chụp thật, không điền tay.

## Vì sao cần thử

Agent v2 sẽ backup cả file **đang mở** (Word, Excel, file CSDL `.mdf`, hộp thư `.pst`…). Đọc trực tiếp các file đó
có thể lỗi vì bị khoá, hoặc đọc ra bản đang ghi dở. VSS chụp "ảnh tức thời" cả ổ đĩa và cho đọc bản chụp đó.
Phải biết ngay từ tuần 1 là VSS chạy được trên PC; nếu không chạy được thì phải đổi kế hoạch.

Windows 10/11 bản client **không có** `vssadmin create shadow` (lệnh này chỉ có trên Windows Server), nên script dùng WMI
`Win32_ShadowCopy.Create`.

## Các bước

1. Copy repo sang PC (hoặc `git pull`).
2. Tạo file Word thử, ví dụ `C:\Users\<tên>\Documents\vss_test.docx`, gõ vài dòng, **Save**, và **để nguyên Word đang mở file đó**.
   Gõ thêm vài chữ nhưng **không** Save. Bản chụp phải ra bản đã Save, không có chữ chưa lưu.
3. Mở **Windows PowerShell (x64)** bằng *Run as administrator*.
4. Chạy:

   ```powershell
   cd <đường dẫn repo>
   powershell -ExecutionPolicy Bypass -File scripts\vss_test.ps1 `
       -FilePath "C:\Users\<tên>\Documents\vss_test.docx" `
       -CopyTo "$env:USERPROFILE\Desktop\vss_copy.docx"
   ```

5. Mở `vss_copy.docx` trên Desktop bằng Word. Nội dung phải giống bản đã Save, không có chữ chưa lưu.
6. Chụp màn hình cửa sổ PowerShell và cửa sổ Word của bản copy, dán vào mục *Kết quả* bên dưới.
7. Kiểm tra không còn shadow copy rác (danh sách phải trống, hoặc chỉ còn các bản của System Restore có từ trước):

   ```powershell
   vssadmin list shadows
   ```

## Script làm gì

| Bước | Việc | Ghi chú |
|---|---|---|
| 0 | Kiểm tra quyền Admin, PowerShell 64-bit, file nằm trên ổ cần chụp | PowerShell 32-bit gọi `Create` sẽ lỗi |
| 1 | Thử đọc file **trực tiếp** (đối chứng) | Word thường vẫn cho đọc chung; file khoá độc quyền (`.mdf`, `.pst`) sẽ lỗi |
| 2 | `Win32_ShadowCopy.Create(Volume='C:\', Context='ClientAccessible')` | In `ShadowID`, `DeviceObject`, thời gian tạo |
| 3 | `mklink /d C:\vss_mount_test \\?\GLOBALROOT\Device\HarddiskVolumeShadowCopyN\` | Phải có dấu `\` ở cuối |
| 4 | Đọc file qua bản chụp, in SHA-256, kích thước, thời gian đọc | Tuỳ chọn `-CopyTo` để mở thử bằng Word |
| 5 | **Luôn** gỡ link (`rmdir`, không `/s`) và xoá shadow copy, kể cả khi lỗi | Không để lại bản chụp chiếm chỗ |

## Lỗi hay gặp

| Thông báo | Cách xử lý |
|---|---|
| `Can chay PowerShell bang quyen Administrator` | Mở lại PowerShell bằng *Run as administrator* |
| `Win32_ShadowCopy.Create tra ve 6: Insufficient storage` | Tăng vùng shadow storage: `vssadmin resize shadowstorage /for=C: /on=C: /maxsize=10%` |
| `... tra ve 9: Another shadow copy operation is in progress` | Đợi 1 phút (Windows Backup/System Restore đang chạy) rồi chạy lại |
| `... tra ve 1: Access denied` | Chưa phải Admin, hoặc phần mềm bảo mật chặn; kiểm tra service *Volume Shadow Copy* (`Get-Service VSS`) |
| `mklink loi` | Thư mục `-MountPath` đã tồn tại, hoặc không phải Admin |
| Shadow copy vẫn còn sau khi chạy | `vssadmin delete shadows /shadow={ShadowID}` (ID in trong log) |

## Kết quả (dán ảnh thật vào đây)

- Ngày chạy: `____`  · Máy: `____`  · Windows: `____`
- Đọc trực tiếp file đang mở: ☐ được ☐ lỗi: `____`
- Tạo shadow copy mất: `____ s`
- SHA-256 qua VSS: `____`
- Mở bản copy bằng Word: ☐ mở được, đúng bản đã Save ☐ lỗi: `____`
- `vssadmin list shadows` sau khi chạy: ☐ không còn bản chụp của script

**Ảnh 1 — cửa sổ PowerShell:**

<!-- Kéo ảnh vào đây, ví dụ: ![vss powershell](img/vss-powershell.png) -->

**Ảnh 2 — Word mở bản copy:**

<!-- ![vss word](img/vss-word.png) -->
