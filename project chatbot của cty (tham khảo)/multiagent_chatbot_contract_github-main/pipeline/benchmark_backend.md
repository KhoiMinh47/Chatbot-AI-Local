# Benchmark Backend (FastAPI)

## 1. Mục tiêu
Đánh giá hiệu năng backend FastAPI (API RAG, contract, upload, history) trong môi trường production thực tế.

## 2. Thông tin môi trường
- Máy chủ: (điền cấu hình thực tế: CPU, RAM, OS, network)
- Backend: FastAPI, Uvicorn, Qdrant, Redis, PostgreSQL, MinIO
- vLLM: (ghi rõ version, endpoint)
- Network: nội bộ/docker compose

## 3. Phương pháp benchmark
- Tool: `locust`, `wrk`, `vegeta`, `hey`, custom script
- Kịch bản:
    - Đo latency/p99/p50 cho từng API (rag, contract, upload, history)
    - Đo throughput (req/s)
    - Đo memory/CPU usage
    - Đo hiệu năng khi concurrent user (1, 5, 10, 20, 50)
    - Đo riêng các API nặng (rag, contract) và nhẹ (history, session)
- Payload mẫu: lấy từ production log thực tế, đủ các loại truy vấn

## 4. Câu lệnh benchmark mẫu
```bash
# 1. Đo throughput với wrk
wrk -t4 -c16 -d60s --latency http://localhost:9000/rag/query -s wrk_rag_script.lua

# 2. Đo với locust
locust -f locustfile.py --host=http://localhost:9000

# 3. Đo với vegeta
cat payloads.txt | vegeta attack -duration=60s -rate=20 | tee results.bin | vegeta report
```

## 5. Kết quả benchmark (mẫu)
| API      | Users | p50 Latency (ms) | p99 Latency (ms) | Throughput (req/s) | CPU (%) | RAM (GB) |
|----------|-------|------------------|------------------|--------------------|---------|----------|
| /rag     | 1     | 1800             | 2500             | 0.7                | 40      | 1.2      |
| /rag     | 10    | 2200             | 3200             | 4.5                | 85      | 1.5      |
| /contract| 1     | 900              | 1200             | 1.1                | 30      | 1.1      |
| /upload  | 5     | 400              | 700              | 8.2                | 60      | 1.3      |

## 6. Đánh giá
- API /rag có latency cao nhất do gọi LLM.
- /contract nhanh hơn nếu dùng template, chậm nếu sinh LLM.
- /upload, /history rất nhanh, bottleneck chủ yếu ở I/O.
- Khi concurrent >10, CPU backend sẽ là bottleneck nếu không scale.

## 7. Khuyến nghị
- Tối ưu batch request cho /rag.
- Scale-out backend nếu concurrent lớn.
- Theo dõi RAM/CPU, tránh overload.
- Tách riêng worker xử lý upload nếu cần.
