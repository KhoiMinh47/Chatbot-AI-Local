# Chatbot NextJS Contract - NTC AI Assistant

Ứng dụng frontend chatbot thông minh hỗ trợ quản lý hợp đồng, tra cứu tài liệu RAG và đối chiếu điều lệ — Xây dựng trên nền tảng **Next.js 16.1.6** và **React 19.2.3**.

---

## 📋 Mục lục
- [Kiến trúc Tổng thể](#-kiến-trúc-tổng-thể)
- [Cấu trúc Thư mục](#-cấu-trúc-thư-mục)
- [Cài đặt & Khởi chạy](#-cài-đặt--khởi-chạy)
- [Tính năng chính & UI](#-tính-năng-chính--ui)
- [Bảng Quản Trị & Giám Sát](#-bảng-quản-trị--giám-sát)

---

## 🏛️ Kiến trúc Tổng thể

Ứng dụng được thiết kế theo mô hình **Modern Single Page Application (SPA)**, tối ưu hóa cho trải nghiệm thời gian thực và xử lý dữ liệu lớn.

### 1. Kiến trúc Hệ thống
- **Frontend (Next.js - App Router):** Sử dụng Client Side Rendering (CSR) kết hợp với React Hooks để quản lý trạng thái phức tạp.
- **Tầng dịch vụ (Services Layer):** Các dịch vụ chuyên biệt (`authService`, `ragService`, `contractService`) được tách biệt hoàn toàn để quản lý API và Mock data.
- **Real-time Monitoring:** Tích hợp trực tiếp với Prometheus thông qua Backend để cung cấp chỉ số hệ thống Native (CPU, GPU, RAM, VRAM).

### 2. UI Patterns & UX (Double-wrapper Pattern)
Trang Chat chính (`/src/app/chat/page.js`) áp dụng các kỹ thuật tối ưu hóa:
- **Unified Sidebar:** Quản lý lịch sử hội thoại, thư mục tài liệu và hồ sơ người dùng trong một không gian linh hoạt (thu gọn/mở rộng).
- **Double-wrapper (Scroll Optimization):**
  - **Lớp ngoài (`.chatScrollWrapper`):** Đảm bảo thanh cuộn luôn bám sát mép phải màn hình, tối ưu UX trên màn hình rộng.
  - **Lớp trong (`.chatContainer`):** Giới hạn bề rộng văn bản (`max-width: 1200px`) để tăng khả năng tập trung khi đọc tin nhắn dài.
- **SSE (Server-Sent Events):** Sử dụng SSE để theo dõi tiến trình chuyển đổi Model vLLM và streaming phản hồi từ AI.

---

## 📁 Cấu trúc Thư mục

```text
frontend/
├── public/                 # Tài nguyên tĩnh (Logo, Icons)
├── src/
│   ├── app/                # App Router (Chat, Auth, Layouts)
│   ├── components/         # Components tái sử dụng (BotMessage, ChatInput, Modals)
│   ├── services/           # API Services (Auth, RAG, Contract)
│   ├── styles/             # Modular CSS & Global themes
│   └── utils/              # Tiện ích bổ trợ (Placeholder, Formatters)
├── package.json            # Cấu hình phụ thuộc (Next 16, React 19, Axios, Socket.io)
└── next.config.mjs         # Cấu hình Next.js (Optimization, Env vars)
```

---

## 🚀 Cài đặt & Khởi chạy

**Yêu cầu:** Node.js 18+ hoặc Docker.

**Cách 1: Chạy trực tiếp qua npm**
```bash
npm install
npm run dev
# Cấu hình NEXT_PUBLIC_API_URL=/ để frontend gọi same-origin qua nginx reverse proxy
```

**Cách 2: Chạy qua Docker Compose**
```bash
docker-compose up -d --build
```
*Production khuyến nghị truy cập qua nginx: `http://localhost:3000`*

---

## ✨ Tính năng chính & UI

### 1. Chế độ Hội thoại (RAG & Contract)
- **Truy vấn Dữ liệu (RAG):** Hỏi đáp dựa trên tập tài liệu PDF/Docx đã upload. Hỗ trợ hiển thị nguồn trích dẫn.
- **Tạo hợp đồng:** Điền thông tin tự động theo Template chuyên nghiệp hoặc tạo tự do qua Prompt thông minh.
- **Đa luồng (Flow Selection):** Chọn lựa giữa Fast (Nhanh), Reasoning (Suy luận) hoặc Templated (Mẫu có sẵn).

### 2. Quản lý Model AI (vLLM Integration)
- **Model Selector:** Tích hợp bộ chọn Model AI ngay tại Navbar (chỉ dành cho Admin).
- **Live Status:** Hiển thị trạng thái tải Model, tiến trình nạp (Progress bar) và nhật ký log thời gian thực qua SSE.
- **GPU Optimization:** Theo dõi hiệu suất sử dụng GPU ngay khi đang thực hiện chuyển đổi Model.

---

## 🛡️ Bảng Quản Trị & Giám Sát (Admin Panel)

Hệ thống cung cấp một bảng điều khiển trung tâm mạnh mẽ:
- **Quản lý Tài khoản (User/Role):** Cấp quyền, kích hoạt/khóa tài khoản, xem lịch sử đăng nhập chi tiết.
- **Native Analytics:** Widget theo dõi thời gian thực (CPU, RAM, Disk, GPU Temp, VRAM Usage, KV Cache).
- **Giám sát Bảo mật (Security Monitor):** Cảnh báo đăng nhập bất thường (VPN, Di chuyển bất khả thi), quản lý thông báo bảo mật.
- **Thiết lập Hệ thống:** Quản lý tham số vLLM và cấu hình chung của ứng dụng.

---
*Dự án được chuẩn hóa theo kiến trúc sản xuất cao cấp, tối ưu cho nhu cầu doanh nghiệp.*
