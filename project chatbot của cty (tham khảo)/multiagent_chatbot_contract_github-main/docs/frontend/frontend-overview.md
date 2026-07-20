# Tổng quan frontend

Cập nhật lần cuối: 2026-05-13

## 1. Vai trò

Frontend cung cấp giao diện thao tác cho người dùng cuối và admin:

- Chat với AI theo nhiều flow.
- Quản lý file tài liệu và session.
- Theo dõi trạng thái vận hành và thiết lập hệ thống.

## 2. Công nghệ

- Next.js 16.
- React 19.
- ESLint cho chất lượng code.
- Axios cho gọi API backend.

## 3. Cấu trúc chính

- `frontend/src/app/`: pages và layout theo App Router.
- `frontend/src/components/`: UI components tái sử dụng.
- `frontend/src/services/`: lớp gọi API.
- `frontend/src/styles/`: CSS modules và global styles.

## 4. Luồng giao tiếp với backend

1. User thao tác trên trang chat/admin.
2. Service layer gọi API tương ứng.
3. Hiển thị response thường hoặc stream (SSE) theo flow.
4. Cập nhật UI state và thông báo lỗi/thành công.

## 5. Quy ước phát triển

- Tách logic API ra service, không đặt trực tiếp trong component lớn.
- Giữ tên component rõ nghĩa theo nghiệp vụ.
- Đảm bảo UI responsive cho desktop/mobile.
