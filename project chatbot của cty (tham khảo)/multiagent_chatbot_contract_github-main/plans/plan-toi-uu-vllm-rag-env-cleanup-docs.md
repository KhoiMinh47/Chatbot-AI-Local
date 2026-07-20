# Plan: Tối ưu vLLM, RAG, Env, Cleanup và Tài liệu

- Created: 2026-05-23 17:53
- Updated: 2026-05-23 18:38
- Status: closed
- Related log: logs/tasks/2026/2026-05-23-toi-uu-vllm-rag-env-cleanup-docs.md

## Goal

Giảm VRAM vLLM tạm thời, chuẩn hóa env về thư mục gốc, giới hạn ngân sách token cho pipeline RAG mà không đổi luồng xử lý, dọn source/cache theo hướng tối thiểu nhưng vẫn đủ vận hành, và cập nhật tài liệu/log/README bằng tiếng Việt có dấu.

## Scope

- In:
  - Đưa vLLM về `LLM_CONTEXT_WINDOW=65536` và thử `GPU_MEMORY_UTIL=0.30`.
  - Thêm cấu hình env cho RAG: input budget khoảng `50000` token, output budget `10000` token.
  - Chỉ chỉnh số lượng/budget trong pipeline RAG hiện có, không đổi thứ tự node, không đổi cách chọn path/rerank/search.
  - Chuyển backend, embedding, parse-data, prometheus-collector sang đọc env từ thư mục gốc; frontend vẫn dùng env riêng của frontend.
  - Đồng bộ `.env.example` đầy đủ key nhưng không chứa secret thật.
  - Dọn folder/file/cache sinh tự động hoặc thừa sau khi phân loại an toàn.
  - Kiểm tra dung lượng cache, phân loại cache đang dùng và cache có thể xóa.
  - Tái cấu trúc `docs/`, `logs/`, `plans/`, cập nhật `README.md`, tạo ảnh chụp và GIF banner dùng web thật.
  - Test lại bằng HTTP, Docker/tmux, frontend qua nginx/Cloudflare tunnel, có screenshot và response thật.
- Out:
  - Không đổi model chính nếu `google/gemma-4-E4B-it` vẫn chạy ổn trong ngân sách mới.
  - Không xóa dữ liệu runtime quan trọng như database/cache model/backup khi chưa có xác nhận.
  - Không push nếu chưa có yêu cầu riêng.

## Skills

- `plan-skill`: chia phase, status, evidence, điều kiện đóng task.
- `backend-skill`: chỉnh cấu hình backend/RAG đúng pipeline hiện có.
- `documentation-skill`: gom, tóm tắt, sắp xếp docs.
- `logging-skill`: ghi log phiên làm việc, log test, log cleanup.
- `readme-style`: README dạng landing page kỹ thuật, có banner, flow, repo map.
- `push-code-skill`: kiểm CI/CD, `.gitignore`, env example, version, commit/push nếu được yêu cầu.

## Findings ban đầu

- `.env` hiện vẫn là `GPU_MEMORY_UTIL=0.65`, `LLM_CONTEXT_WINDOW=128000`, `LLM_MAX_TOKENS=128000`.
- vLLM thực tế đang chạy với `--gpu-memory-utilization 0.65` và `--max-model-len 128000`; GPU 48GB nên process vLLM giữ khoảng `31GB`.
- `backend/main.py`, `embedding/main.py`, `parse-data/main.py` đang load root env rồi override bằng `.env` trong từng service.
- Các env lẻ hiện có: `backend/.env`, `embedding/.env`, `parse-data/.env`, `prometheus-collector/.env`; frontend có `frontend/.env.local`.
- Pipeline RAG hiện có các hằng số trực tiếp trong `backend/agent_chatbot/node/util/rag_query_util.py`: `MAX_FILE_CONTEXT=70000`, `MAX_HISTORY_CONTEXT=30000`, `MAX_TOKEN_OUTPUT=4000`, `_TOKEN_BUDGET=70000`, `_AVG_TOKENS_PER_CHUNK=600`.
- Cache lớn hiện thấy: `cache/huggingface` khoảng `33G`, `cache/bge` khoảng `20G`, `cache/marker` khoảng `3.3G`, `frontend/.next` khoảng `142M`, `frontend/node_modules` khoảng `577M`, `embedding/venv` khoảng `7.1G`, `parse-data/venv` khoảng `7.9G`.
- Các thư mục `cache/minio`, `cache/pgdata`, `cache/qdrant_storage`, `cache/redis_data`, `cache/prometheus_data` đang là volume dữ liệu service, không được xóa như cache rác nếu chưa backup/xác nhận.
- Audit mount hiện tại cho thấy `cache/huggingface` đang được `vllm_gemma4` dùng; trong đó chỉ `models--google--gemma-4-E4B-it` khớp model hiện chạy. `cache/bge` và `cache/marker` chưa thấy compose/container hiện tại dùng trực tiếp.
- Worktree đang có nhiều thay đổi chưa commit, bao gồm thay đổi trong `.codex/skills`, `.env.example`, RAG util, compose, frontend và một số file `.github` bị đánh dấu delete. Khi thực hiện phải bảo toàn thay đổi hiện có, không revert ngầm.

## Feasibility

- `LLM_CONTEXT_WINDOW=65536` là khả thi cho RAG nếu RAG input giữ khoảng `50000` token và output `10000` token, còn lại dành cho system prompt/template/safety margin.
- `GPU_MEMORY_UTIL=0.30` và `0.35` đã thử nhưng chưa đủ KV cache cho 64k. Fallback đang triển khai là `GPU_MEMORY_UTIL=0.37`, giữ `LLM_CONTEXT_WINDOW=65536`.
- Vì đã dùng `--kv-cache-dtype fp8`, khả năng chạy 64k ở mức thấp hơn 0.65 tốt hơn so với BF16 KV cache, nhưng vẫn cần xác nhận bằng log vLLM và request thật.

## Proposed env keys

- `GPU_MEMORY_UTIL=0.37`
- `LLM_CONTEXT_WINDOW=65536`
- `RAG_INPUT_TOKEN_BUDGET=50000`
- `RAG_OUTPUT_TOKEN_BUDGET=10000`
- `RAG_HISTORY_TOKEN_BUDGET`
- `RAG_FILE_CONTEXT_TOKEN_BUDGET`
- `RAG_SELECTED_PATH_TOKEN_BUDGET`
- `RAG_AVG_TOKENS_PER_CHUNK=600`
- `RAG_CHARS_PER_TOKEN=2.5`
- `CODE_TMUX_SESSION=rag-chat-code`
- `BACKEND_TMUX_WINDOW=backend`
- `FRONTEND_TMUX_WINDOW=frontend`
- `PARSER_TMUX_WINDOW=parse-data`
- `EMBEDDING_TMUX_WINDOW=embedding`
- `PROMETHEUS_COLLECTOR_TMUX_WINDOW=prometheus-collector`

## Phases

| Phase | Goal | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Chốt baseline và bảo vệ worktree | done | `git status`, snapshot env, `nvidia-smi`, `docker inspect vllm_gemma4` |
| 2 | Chuẩn hóa env gốc | done | `.env`, `.env.all`, `.env.example`, không còn service env override |
| 3 | Giảm vLLM về 64k và 0.37 | done | `/v1/models` trả `max_model_len=65536`, vLLM còn khoảng `18544MiB` |
| 4 | Cấu hình budget RAG bằng env | done | RAG util đọc env, pipeline node/path giữ nguyên, log budget rõ ràng |
| 5 | Dọn source và cache có kiểm soát | done | Giữ model đang chạy và volume dữ liệu; xóa cache cũ, root `.next`, `__pycache__` |
| 6 | Cấu trúc lại docs/logs/plans | done | `docs/README.md`, `logs/README.md`, `plans/README.md`, tài liệu tiếng Việt |
| 7 | README và banner | done | README mới, screenshot, GIF khoảng 30 giây trong `docs/assets` |
| 8 | Test kỹ | done | Backend docs, parse, embedding, vLLM, nginx, web chat có response |
| 9 | Kiểm CI/CD và chuẩn bị push | done | Tạo lại CI tối thiểu; release workflow cũ đang bị delete từ worktree trước task |

## Detailed execution plan

1. Baseline:
   - Ghi lại cấu hình hiện tại của root env và service env.
   - Ghi lại VRAM/process trước khi đổi.
   - Kiểm tra worktree để không đè thay đổi chưa rõ nguồn.
2. Env:
   - Di chuyển key còn thiếu từ env service vào `.env` và `.env.example`.
   - Sửa entrypoint service chỉ load `.env.all` và `.env` từ project root.
   - Sau khi test, xóa `backend/.env`, `embedding/.env`, `parse-data/.env`, `prometheus-collector/.env`.
   - Giữ `frontend/.env.local` vì frontend được phép có env riêng.
3. vLLM:
   - Đã thử env root `GPU_MEMORY_UTIL=0.30`, `LLM_CONTEXT_WINDOW=65536`.
   - Do `0.30` và `0.35` fail KV cache, đang thử fallback `GPU_MEMORY_UTIL=0.37`.
   - Restart đúng service/container, ưu tiên qua script/tmux hiện có.
4. RAG:
   - Không đổi flow pipeline.
   - Thay hằng số hard-code bằng env fallback cùng giá trị mục tiêu.
   - Giữ cách kiểm soát theo path: `_TOKEN_BUDGET`, `_AVG_TOKENS_PER_CHUNK`, `max_chunks_per_path`.
   - Chỉ bổ sung logging budget để biết query đang dùng bao nhiêu context/output.
5. Cleanup source và cache:
   - Chạy báo cáo dung lượng trước/sau cho cache và artifact build.
   - Xóa an toàn các artifact sinh tự động: `__pycache__`, `.pytest_cache`, `.next` root nếu không dùng, cache build, log runtime cũ đã được gom.
   - Không xóa các volume dữ liệu: `cache/pgdata`, `cache/qdrant_storage`, `cache/minio`, `cache/redis_data`, `cache/prometheus_data` nếu chưa backup/xác nhận vì có thể chứa dữ liệu production/local.
   - Trong `cache/huggingface`, giữ model đang chạy `models--google--gemma-4-E4B-it`; chỉ xóa model cũ `Qwen3-VL-8B-Instruct-FP8` và `khazarai/Qwen3-4B...` nếu xác nhận không cần đổi nhanh.
   - Có thể đưa `cache/bge` và `cache/marker` vào danh sách xóa ứng viên vì chưa thấy service hiện tại mount/reference, nhưng phải test embedding/parse-data sau khi xóa.
   - Với venv/node_modules: chỉ xóa nếu xác nhận service chạy bằng Docker hoặc chấp nhận cài lại dependency; nếu vẫn chạy tmux bằng code thì giữ venv cần thiết.
   - Giữ `.codex/skills`.
   - Rà lại `.github/workflows` vì hiện worktree đang có delete; theo `push-code-skill`, CI/CD phải được khôi phục hoặc thay thế trước khi đóng task.
6. Documentation/logs/plans:
   - Tổ chức `docs/` theo nhóm: `overview`, `architecture`, `configuration`, `deployment`, `pipeline`, `operations`, `testing`, `reports/archive`.
   - Tổ chức `logs/`: `tasks/YYYY`, `testing/YYYY`, `cleanup/YYYY`, có `logs/README.md`.
   - Tổ chức `plans/`: `active`, `completed`, `archive`, có `plans/README.md`; di chuyển plan cũ có ghi chú redirect nếu cần.
   - Tất cả nội dung viết tiếng Việt có dấu.
7. Frontend verification và banner:
   - Chạy qua nginx port đang dùng cho Cloudflare tunnel.
   - Dùng Playwright mở chat, gửi câu hỏi RAG ngắn, chụp ảnh có response.
   - Quay màn hình thao tác web 30-60 giây, 24fps, xuất GIF tối ưu dung lượng làm banner GitHub.

## Verification

- `docker compose --env-file .env -f docker-compose.yml config` không lỗi.
- vLLM `/v1/models` trả model đúng.
- `nvidia-smi` cho thấy vLLM giảm rõ so với khoảng `31GB`.
- Backend health/API chính trả OK.
- Embedding `/embed` và `/rerank` trả dữ liệu hợp lệ.
- Parse-data health hoặc endpoint parse smoke test chạy được.
- RAG chat qua HTTP trả response, input/output budget trong log đúng env.
- Frontend qua nginx hiển thị được, gửi chat có response.
- Có screenshot và GIF banner.
- Test/lint phù hợp chạy xong hoặc ghi rõ blocker.

## Close criteria

- Env tập trung tại root, env service lẻ đã xóa sau khi verify.
- vLLM chạy được ở 64k và mức VRAM mới, hoặc có fallback được ghi rõ.
- Pipeline RAG giữ nguyên luồng, chỉ thay budget bằng env.
- Source sạch hơn, `.gitignore` chặn artifact sinh tự động.
- Docs/logs/plans/README tiếng Việt có dấu, có cấu trúc rõ.
- Có evidence test: command summary, screenshot, web response, GIF.
- CI/CD được rà soát theo `push-code-skill`.
- Không có thay đổi user chưa rõ nguồn bị revert.

## Close summary

- Hoàn thành gom env về root, chỉ frontend giữ env riêng.
- vLLM chạy ổn với `LLM_CONTEXT_WINDOW=65536`, `GPU_MEMORY_UTIL=0.37`; mức `0.30` và `0.35` đã thử nhưng fail KV cache.
- RAG đọc token budget từ env: input `50000`, output `10000`, path budget giữ theo pipeline hiện có.
- Cache project root đã dọn còn model Gemma đang chạy và volume dữ liệu service.
- Docs/logs/plans/README đã cập nhật bằng tiếng Việt có dấu; có screenshot và GIF banner.
- CI tối thiểu `.github/workflows/ci.yml` đã được tạo lại. Hai release workflow cũ vẫn đang ở trạng thái delete trong worktree và không được tự phục hồi vì là thay đổi có sẵn trước task.
