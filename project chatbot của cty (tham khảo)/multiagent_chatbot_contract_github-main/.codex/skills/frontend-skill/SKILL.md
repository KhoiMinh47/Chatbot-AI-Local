---
name: frontend-skill
description: 'Những quy tắt bắt buộc khi viết code frontend.'
argument-hint: 'tuân thủ các quy tắc đã đề ra.'
user-invocable: true
---
# Frontend Skill
Những quy tắt bắt buộc khi viết code frontend:

## Cấu trúc thư mục
- `src/`: Chứa mã nguồn chính của ứng dụng.
  - `components/`: Chứa các thành phần giao diện người dùng (UI components).
  - `pages/`: Chứa các trang (pages) của ứng dụng.
  - `services/`: Chứa các service thực hiện các tác vụ cụ thể, như gọi API, xử lý dữ liệu, v.v.
  - `utils/`: Chứa các tiện ích chung được sử dụng trong toàn bộ ứng dụng.
- `assets/`: Chứa các tài nguyên như hình ảnh, font chữ, v.v.
- `styles/`: Chứa các tệp CSS hoặc các tệp định kiểu (stylesheets) khác.
- `tests/`: Chứa các bài kiểm tra (test) cho ứng dụng.
- `docs/`: Chứa tài liệu kỹ thuật liên quan đến ứng dụng.
- `logs/`: Chứa các tệp log của ứng dụng.
- `public/`: Chứa các tệp tĩnh (static files) như index.html, favicon, v.v.

## Quy tắc đặt tên
- Tên biến, hàm, lớp nên rõ ràng và mô tả chính xác chức năng của chúng.
- Sử dụng camelCase cho tên biến và hàm, PascalCase cho tên lớp.
- Tránh sử dụng tên viết tắt không rõ ràng.
- Sử dụng tiền tố `is`, `has`, `can` cho các biến boolean để tăng tính rõ ràng.
- Sử dụng tiền tố `handle` cho các hàm xử lý sự kiện (event handlers) để dễ dàng nhận biết chức năng của chúng.

## Quy tắc viết code
- Viết code sạch sẽ, dễ đọc và dễ bảo trì.
- Tuân thủ các nguyên tắc SOLID và các mẫu thiết kế (design patterns)
- Viết các bài kiểm tra (tests) để đảm bảo chất lượng code.
- Sử dụng các công cụ kiểm tra chất lượng code (linters) để duy trì tiêu chuẩn mã nguồn.
- Đảm bảo mã nguồn được kiểm tra và review trước khi merge vào nhánh chính.
- Sử dụng hệ thống quản lý phiên bản (version control) như Git để theo dõi lịch sử thay đổi của mã nguồn.
- Đảm bảo mã nguồn được tối ưu hóa về hiệu suất và bảo mật.
- Sử dụng các công cụ giám sát và logging để theo dõi hoạt động của ứng dụng và phát hiện lỗi kịp thời.
- Cập nhật tài liệu kỹ thuật liên quan đến mã nguồn và các thay đổi quan trọng.
- Đảm bảo mã nguồn tuân thủ các tiêu chuẩn và quy định của ngành, như GDPR, HIPAA, v.v. nếu áp dụng.
- Thường xuyên refactor mã nguồn để cải thiện chất lượng và hiệu suất của ứng dụng.
- Sử dụng các công cụ và kỹ thuật tối ưu hóa hiệu suất, như lazy loading, code splitting, v.v. để cải thiện trải nghiệm người dùng.
- Đảm bảo mã nguồn tuân thủ các tiêu chuẩn về truy cập (accessibility) để đảm bảo ứng dụng có thể sử dụng được cho tất cả người dùng, bao gồm cả những người có khuyết tật.
- Sử dụng các công cụ và kỹ thuật tối ưu hóa SEO để cải thiện khả năng hiển thị của ứng dụng trên các công cụ tìm kiếm.
- Đảm bảo mã nguồn tuân thủ các tiêu chuẩn về bảo mật, như tránh lưu trữ thông tin nhạy cảm trong mã nguồn, sử dụng HTTPS, v.v. để bảo vệ dữ liệu người dùng và ứng dụng khỏi các mối đe dọa bảo mật.
- Sử dụng các công cụ và kỹ thuật tối ưu hóa trải nghiệm người dùng (UX) để tạo ra giao diện người dùng thân thiện và dễ sử dụng, như responsive design, animation, v.v.
- Đảm bảo mã nguồn tuân thủ các tiêu chuẩn về tương thích trình duyệt (browser compatibility) để đảm bảo ứng dụng hoạt động tốt trên tất cả các trình duyệt phổ biến.

## Kiến truc và thiết kế
- Sử dụng kiến trúc component-based để tạo ra các thành phần giao diện người dùng có thể tái sử dụng và dễ bảo trì.
- Thiết kế giao diện người dùng rõ ràng và dễ sử dụng, tuân thủ các nguyên tắc thiết kế (design principles) như consistency, feedback, v.v.
- Sử dụng các mẫu thiết kế (design patterns) phù hợp để giải quyết các vấn đề phổ biến trong phát triển frontend, như Container/Presentational, Higher-Order Components, v.v.
- Đảm bảo ứng dụng có khả năng mở rộng và dễ dàng bảo trì trong tương lai.
- Sử dụng các công nghệ và framework phù hợp với yêu cầu của dự án.
- Đảm bảo ứng dụng có khả năng chịu lỗi và phục hồi nhanh chóng khi gặp sự cố.
- Sử dụng các công cụ giám sát và logging để theo dõi hoạt động của ứng dụng và phát hiện lỗi kịp thời.
- Cập nhật tài liệu kỹ thuật liên quan đến kiến trúc và thiết kế của ứng dụng.
- Luôn có cơ chế claenup, dọn dẹp logs, dữ liệu tạm thời để tránh tình trạng đầy ổ cứng và giảm hiệu suất của ứng dụng.
