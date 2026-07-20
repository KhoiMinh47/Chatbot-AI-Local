# Log kiểm thử: vLLM, RAG budget và Web UI

- Thời gian: 2026-05-23 18:34
- Plan liên quan: `plans/plan-toi-uu-vllm-rag-env-cleanup-docs.md`

## Mục tiêu

Xác nhận hệ thống vẫn hoạt động sau khi gom env, giảm vLLM còn 64k/0.37, dọn cache và restart service code bằng tmux.

## Kiểm thử đã chạy

- `docker compose --env-file .env -f docker-compose.yml config`
- `docker compose --env-file .env.all -f docker-compose.all.yml config`
- `docker compose --env-file .env.example -f docker-compose.yml config`
- `python3 -m py_compile` cho entrypoint service và RAG util.
- `npm run lint` trong `frontend` đạt với 24 warning hiện hữu.
- HTTP smoke:
  - Backend docs: `http://127.0.0.1:9000/docs`
  - Parse-data docs: `http://127.0.0.1:8005/docs`
  - Embedding docs: `http://127.0.0.1:8006/docs`
  - Prometheus collector root: `http://127.0.0.1:9005/`
  - vLLM models: `http://127.0.0.1:8007/v1/models`
  - Nginx frontend: `http://127.0.0.1:3000/`
- API inference:
  - Embedding `/api/v1/embed` trả vector.
  - vLLM `/v1/chat/completions` trả câu: `Có, hệ thống đang hoạt động.`
- Web UI:
  - Đăng nhập qua Nginx.
  - Gửi câu hỏi trên trang chat.
  - Trang web trả response và đã chụp ảnh.

## Evidence

- Screenshot: `docs/assets/rag-chat-web-response.png`
- GIF banner: `docs/assets/rag-chat-demo.gif`
- vLLM log: `max_model_len=65536`, `GPU_MEMORY_UTIL=0.37`, KV cache khả dụng khoảng `1.25 GiB`.

## Kết luận

Smoke test đạt. Mức `0.37` là mức tiết kiệm thấp nhất đã xác nhận chạy được với context 64k trong phiên này.
