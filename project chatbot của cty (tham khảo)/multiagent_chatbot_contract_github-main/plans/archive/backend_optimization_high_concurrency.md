# Đề xuất Tối ưu hoá Backend RAG Chatbot cho Mức độ Production (High Concurrency)

Hiện tại, hệ thống của bạn đang gặp phải nút thắt cổ chai (bottleneck) ở lớp Database do thiết kế giữ kết nối đồng bộ mở trong thời gian dài (trong suốt quá trình sinh text của LLM). Để hệ thống có thể chịu tải càng nhiều càng tốt (hàng trăm đến hàng nghìn request đồng thời), dưới đây là lộ trình tối ưu được đề xuất:

## 1. Tối ưu Sinh mệnh (Lifecycle) của Database Session

Vấn đề lớn nhất là cấu trúc controller đang sử dụng `Depends(get_db)` làm tham số Dependency của FastAPI. Thiết kế này sẽ giữ kết nối Database cho đến khi request HTTP kết thúc (có thể lên tới chục giây nếu đang chờ vLLM sinh text liên tục qua Event Source/Streaming).

**Cách giải quyết:**

*   **Không inject DB Session ở mức Controller:** Rút đối tượng Session ra khỏi request mapping. Hãy mở kết nối trong nội bộ các hàm service.
*   **Tiêu chí Micro-transaction:** Chỉ mở kết nối khi tải lịch sử (History) và lúc tạo session trên postgres. Giải phóng connection (pool close) NGAY LẬP TỨC. Sau đó, mới tiến hành gọi sang Qdrant / vLLM. Quá trình xử lý SSE / Prompting hoàn toàn không dính dáng liên kết đến session của db. Ngay sau khi vLLM xong luồng, một hàm async chạy chìm (background task) sẽ lại mở ra 1 connection ngắn hạn (vài mili-giây) để Save nội dung đoạn Chat vào lịch sử.

## 2. Sử dụng PgBouncer (Connection Pooler)

Bản thân PostgreSQL mặc định không được thiết kế để xử lý hàng nghìn kết nối trực tiếp đang idle/cạnh tranh (đó là lý do cấu hình mặc định là `max_connections = 100`).

*   **Thêm container PgBouncer trung gian:** Đặt PgBouncer đứng giữa Backend FastAPI và PostgreSQL.
*   **Chế độ tối ưu (Pool Mode = Transaction):** PgBouncer sẽ duy trì một số lượng ít ỏi các kết nối thật sự với Postgres (vd 50) nhưng cho phép cấp phát hàng ngàn kết nối ảo cho ứng dụng (FastAPI). FastAPI cấu hình `pool_size` cực hạn cũng không khiến Postgres đuối sức vì Bouncer sẽ điều tiết.

## 3. Asynchronous Task Queue / Event-Driven (Tuỳ chọn Nâng cao)

Để đảm bảo nhồi Request vào bao nhiêu ứng dụng cũng không sập lỗi HTTP 50x:

*   **Áp dụng cấu trúc Message Broker:** (như Redis Queue / Celery hoặc RabbitMQ).
*   **Tiến trình:** Frontend gửi câu hỏi -> Backend gán một UUID Request vào Queue và trả kết quả `202 Accepted` ngay lập tức. Cứ mỗi message rớt vào Queue, Worker xử lý RAG độc lập sẽ lấy ra tìm tài liệu, gọi LLM, rồi đùn ngược thông tin vào kênh Pub/Sub của Websocket / SSE đến Client. Lớp API (FastAPI) lúc nãy sẽ giống chiếc "cửa cuốn" cực nhẹ không bao giờ bị nghẽn ở khâu sinh nội dung (độ trễ siêu thấp).
