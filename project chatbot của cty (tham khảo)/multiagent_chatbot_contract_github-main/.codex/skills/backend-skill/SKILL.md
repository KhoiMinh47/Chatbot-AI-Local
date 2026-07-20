---
name: backend-skill
description: 'Những quy tắt bắt buộc khi viết code backend.'
argument-hint: 'tuân thủ các quy tắc đã đề ra.'
user-invocable: true
---
# Backend Skill
Những quy tắt bắt buộc khi viết code backend:

## Cấu trúc thư mục
- `src/`: Chứa mã nguồn chính của ứng dụng.
  - `controllers/`: Chứa các controller xử lý logic nghiệp vụ.
  - `models/`: Chứa các model đại diện cho dữ liệu và tương tác với cơ sở dữ liệu.
  - `routes/`: Chứa các định tuyến (routes) của ứng dụng.
  - `services/`: Chứa các service thực hiện các tác vụ cụ thể, như gọi API, xử lý dữ liệu, v.v.
  - `utils/`: Chứa các tiện ích chung được sử dụng trong toàn bộ ứng dụng.
- `config/`: Chứa các tệp cấu hình, như cấu hình cơ sở dữ liệu, cấu hình môi trường, v.v.
- `tests/`: Chứa các bài kiểm tra (test) cho ứng dụng.
- `docs/`: Chứa tài liệu kỹ thuật liên quan đến ứng dụng.
- `logs/`: Chứa các tệp log của ứng dụng.

## Quy tắc đặt tên
- Tên biến, hàm, lớp nên rõ ràng và mô tả chính xác chức năng của chúng.
- Sử dụng camelCase cho tên biến và hàm, PascalCase cho tên lớp.
- Tránh sử dụng tên viết tắt không rõ ràng.

## Quy tắc viết code
- Viết code sạch sẽ, dễ đọc và dễ bảo trì.
- Tuân thủ các nguyên tắc SOLID và các mẫu thiết kế (design patterns) khi cần thiết.
- Viết các bài kiểm tra (tests) để đảm bảo chất lượng code.
- Sử dụng các công cụ kiểm tra chất lượng code (linters) để duy trì tiêu chuẩn mã nguồn.
- Đảm bảo mã nguồn được kiểm tra và review trước khi merge vào nhánh chính.
- Sử dụng hệ thống quản lý phiên bản (version control) như Git để theo dõi lịch sử thay đổi của mã nguồn.
- Đảm bảo mã nguồn được tối ưu hóa về hiệu suất và bảo mật.
- Sử dụng các công cụ giám sát và logging để theo dõi hoạt động của ứng dụng và phát hiện lỗi kịp thời.
- Cập nhật tài liệu kỹ thuật liên quan đến mã nguồn và các thay đổi quan trọng.
- Đảm bảo mã nguồn tuân thủ các tiêu chuẩn và quy định của ngành, như GDPR, HIPAA, v.v. nếu áp dụng.
- Thường xuyên refactor mã nguồn để cải thiện chất lượng và hiệu suất của ứng dụng.

## Kiến truc và thiết kế
- Sử dụng kiến trúc microservices hoặc monolithic tùy thuộc vào quy mô và yêu cầu của dự án.
- Thiết kế API rõ ràng và dễ sử dụng, tuân thủ các nguyên tắc RESTful hoặc GraphQL nếu cần thiết.
- Sử dụng các mẫu thiết kế (design patterns) phù hợp để giải quyết các vấn đề phổ biến trong phát triển backend, như Singleton, Factory, Repository, v.v.
- Đảm bảo ứng dụng có khả năng mở rộng và dễ dàng bảo trì trong tương lai.
- Sử dụng các công nghệ và framework phù hợp với yêu cầu của dự án.
- Đảm bảo ứng dụng có khả năng chịu lỗi và phục hồi nhanh chóng khi gặp sự cố.
- Sử dụng các công cụ giám sát và logging để theo dõi hoạt động của ứng dụng và phát hiện lỗi kịp thời.
- Cập nhật tài liệu kỹ thuật liên quan đến kiến trúc và thiết kế của ứng dụng.
- Luôn có cơ chế claenup, dọn dẹp logs, dữ liệu tạm thời để tránh tình trạng đầy ổ cứng và giảm hiệu suất của ứng dụng.
