# Benchmark vLLM Server

## 1. Mục tiêu
Đánh giá hiệu năng inference của vLLM server trong môi trường production thực tế.

## 2. Thông tin môi trường
- Máy chủ: (điền cấu hình thực tế: CPU, RAM, GPU, OS, driver)
- vLLM version: (ghi rõ commit/tag)
- Model: (tên, kích thước, tokenizer)
- Backend: FastAPI, Qdrant, Redis, PostgreSQL, MinIO
- Network: nội bộ/docker compose

## 3. Phương pháp benchmark
- Tool: `lm_eval_harness`, `vllm/bench_inference.py`, custom HTTP loadgen (locust, wrk, vegeta)
- Kịch bản:
    - Đo latency/p99/p50 cho từng loại prompt (ngắn, dài, multi-turn)
    - Đo throughput (req/s, token/s)
    - Đo memory/VRAM usage
    - Đo thời gian warmup, cold start
    - Đo hiệu năng khi concurrent user (1, 5, 10, 20, 50)
- Prompt mẫu: lấy từ production log thực tế, đủ các loại truy vấn

## 4. Câu lệnh benchmark mẫu
```bash
# 1. Đo throughput với wrk
wrk -t4 -c16 -d60s --latency http://localhost:8000/generate -s wrk_vllm_script.lua

# 2. Đo bằng lm_eval_harness
python -m lm_eval --model vllm --model_args="..." --tasks=arc_easy,hellaswag,...

# 3. Đo bằng script vllm
python vllm/bench_inference.py --model ... --tokenizer ... --prompt_file prompts.txt --num-requests 1000
```

## 5. Kết quả benchmark (mẫu)
| Users | p50 Latency (ms) | p99 Latency (ms) | Throughput (req/s) | Token/s | VRAM (GB) |
|-------|------------------|------------------|--------------------|---------|-----------|
| 1     | 1200             | 1800             | 0.8                | 120     | 12        |
| 5     | 1400             | 2200             | 2.5                | 350     | 13        |
| 20    | 2100             | 3500             | 6.2                | 900     | 14        |

## 6. Đánh giá
- Độ trễ thấp nhất khi batch size tối ưu, prompt ngắn.
- Qua 10 user concurrent, latency tăng mạnh do GPU full load.
- Token/s ổn định, VRAM tăng nhẹ theo batch.
- Cold start ~15s, warmup ~2s.

## 7. Khuyến nghị
- Đặt batch size phù hợp GPU.
- Tối ưu prompt, tránh prompt quá dài.
- Theo dõi VRAM, tránh OOM.
- Có thể scale-out nhiều instance nếu cần.
