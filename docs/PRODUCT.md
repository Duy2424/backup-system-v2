# Product

## Register

product

## Users

Quản trị viên hệ thống của một doanh nghiệp nhỏ (trong đồ án: sinh viên Duy và bạn cùng nhóm). Họ ngồi ở **laptop**, mở trình duyệt
tới máy chủ backup là **PC ở nhà** (qua Tailscale) để điều khiển: xem tình trạng, chạy sao lưu, khôi phục, đặt lịch, quản lý người dùng.
Laptop chỉ điều khiển, không chứa dữ liệu. Không dùng trên điện thoại.

Bối cảnh thứ hai quan trọng không kém: **demo trước hội đồng** (bảo vệ đồ án, IT Got Talent), màn hình laptop được **chiếu lên máy chiếu**
trong phòng sáng đèn. Người xem ở cuối phòng phải đọc được trạng thái và tiến độ.

## Product Purpose

Giao diện điều khiển của hệ thống backup: biến các thao tác vốn phải gõ lệnh (sao lưu file + cấu hình mạng Windows, khôi phục, lập lịch)
thành vài cú bấm rõ ràng, và luôn trả lời được ba câu hỏi: *Agent có đang chạy không? Lần sao lưu gần nhất có thành công không?
Nếu mất dữ liệu bây giờ thì khôi phục thế nào?*

Thành công = người quản trị không bao giờ phải đoán trạng thái, và khôi phục (thao tác căng thẳng nhất) cảm thấy an toàn, có chạy thử trước.

## Brand Personality

Gọn gàng, đáng tin, bình tĩnh. Giọng văn tiếng Việt có dấu, ngắn, nói thẳng việc gì đang xảy ra ("Đang sao lưu 312/540 MB"),
không khoa trương. Tham chiếu: Windows Settings và Synology DSM (điều hướng bên trái, bảng số liệu rõ, trạng thái xanh/vàng/đỏ dễ hiểu).
Giữ màu navy của bản v1 làm màu nhận diện.

## Anti-references

- Dashboard SaaS kiểu "hero metric": số to, gradient, 4 thẻ giống hệt nhau.
- Giao diện "enterprise" dày đặc kiểu Veeam/Acronis.
- Bootstrap mặc định (bản v1): navbar xanh đậm, card bóng đổ, nút màu cam lạc tông.
- Hiệu ứng trang trí: glassmorphism, chữ gradient, animation khi tải trang.

## Design Principles

1. **Trạng thái trước, thao tác sau.** Màn hình đầu tiên trả lời "mọi thứ có ổn không" trước khi mời bấm nút.
2. **Khôi phục phải an toàn.** Luôn có "chạy thử" để so sánh trước khi ghi; thao tác phá huỷ (xoá file thừa) mặc định tắt và phải nói rõ hậu quả.
3. **Đọc được từ cuối phòng.** Tương phản cao, tiến độ to rõ, không dựa vào màu nhạt hay chữ nhỏ để truyền thông tin quan trọng.
4. **Không bắt người dùng chờ.** Phản hồi tức thì, cập nhật tiến độ trực tiếp, không tải lại trang.
5. **Chạy được trong mạng nội bộ.** Không phụ thuộc CDN hay font tải từ Internet.

## Accessibility & Inclusion

WCAG 2.2 AA: tương phản chữ ≥ 4.5:1, không truyền trạng thái chỉ bằng màu (luôn kèm chữ/biểu tượng), điều khiển được bằng bàn phím
(focus rõ), tôn trọng `prefers-reduced-motion`. Mặc định nền sáng (máy chiếu); có chế độ tối tuỳ chọn.
