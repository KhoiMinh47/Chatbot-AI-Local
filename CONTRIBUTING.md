# Contributing

Tài liệu này áp dụng cho repository scaffold ở Phase 1. Không thêm Docker
Compose, database, NIM runtime hoặc chức năng RAG trước khi phase tương ứng được
phê duyệt.

## Chuẩn bị môi trường

Yêu cầu cục bộ:

- CPython `>=3.14,<3.15`, bản standard-GIL theo ADR 0002.
- `uv` để lock và chạy Python workspace.
- Node.js và `pnpm` theo version được khai báo trong repository.
- GNU Make và Bash cho command contract.
- ShellCheck, curl, jq và `setsid` (util-linux) cho lint/live smoke.

Khởi tạo dependency bằng:

```bash
make bootstrap
```

Không dùng Python hệ thống 3.12 của host cho ứng dụng. Không chỉnh trực tiếp
lockfile; thay dependency input rồi tạo lại lock bằng package manager tương ứng.

## Quy trình thay đổi

1. Xác định phase, acceptance criteria và file nằm trong scope.
2. Thay đổi nhỏ, có test tương ứng và không trộn refactor không liên quan.
3. Chạy `make check` trước khi gửi review.
4. Cập nhật README, ADR hoặc tài liệu kiến trúc khi contract thay đổi.
5. Ghi rõ lệnh đã chạy, kết quả và known limitation trong phần bàn giao.

`make check` là quality gate CPU của Phase 1: lint, format check, type check,
unit smoke tests và scaffold smoke. GPU/NIM test không thuộc lệnh này.

## Quy tắc kiến trúc

- Domain không import FastAPI, SQLAlchemy, Qdrant hoặc NVIDIA NIM SDK.
- Application chứa use case và port/interface, chỉ phụ thuộc domain.
- Infrastructure triển khai adapter; API chỉ validate rồi gọi application.
- Worker dùng shared contract, không import trực tiếp HTTP layer của API.
- Mọi truy cập AI sau này phải đi qua client interface, không rải URL trong
  business logic.
- Config được đọc một lần qua typed settings; không đọc environment rải rác.

Phase 1 chỉ tạo skeleton để kiểm tra dependency direction. Chưa có production
adapter hay data service.

## Test

- Unit test chạy một module cô lập, không cần network hay service bên ngoài.
- Integration test kiểm tra ranh giới thật giữa từ hai thành phần trở lên và có
  thể cần service. Phase 1 chưa dựng các service của Phase 2 nên không giả lập
  một integration pass.
- Test phải có Unicode tiếng Việt khi có logic xử lý text.
- Không dùng model response giả trong production path. Test double chỉ được đặt
  trong test và phải thể hiện rõ contract đang mô phỏng.

## Secret và dữ liệu nhạy cảm

- Chỉ commit `.env.example` với giá trị không bí mật.
- Không commit `.env`, token, cookie, private key, model weight, NIM cache hoặc
  nội dung tài liệu người dùng.
- Không đưa secret vào command line, log, exception hoặc fixture.
- Tên biến bắt đầu bằng `NEXT_PUBLIC_` là dữ liệu công khai trong browser và
  tuyệt đối không được chứa credential.

Nếu phát hiện secret đã được commit, ngừng sử dụng và rotate credential đó;
chỉ xóa khỏi lịch sử là chưa đủ.
