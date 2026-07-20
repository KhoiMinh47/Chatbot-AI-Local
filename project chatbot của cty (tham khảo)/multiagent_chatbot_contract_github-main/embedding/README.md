# Embedding & Reranking Service

API embedding text và reranking documents sử dụng **Qwen3-Embedding-0.6B** + **bge-reranker-v2-m3**, chạy GPU (CUDA) với fp16.

---

## 📁 Cây thư mục

```
embeding/
├── main.py                            # Entry point FastAPI, port 8006
├── requirements.txt
├── src/
│   ├── config/
│   │   └── model_config.py            # Load 2 model lên GPU (singleton, fp16 + sdpa)
│   ├── model/
│   │   └── request_response_model.py  # Request/Response chuẩn {status, result, description}
│   ├── service/
│   │   ├── embedding_service.py       # Logic embedding: tokenize → inference → normalize L2
│   │   └── rerank_service.py          # Logic rerank: tạo pairs → inference → sort by score
│   └── router/
│       └── embedding_router.py        # 2 endpoints: /embed, /rerank
└── README.md
```

---

## 📦 Thư viện

| Thư viện | Mô tả |
|---|---|
| `fastapi` | Web framework |
| `uvicorn` | ASGI server |
| `torch` | PyTorch (CUDA) |
| `transformers` | Load model HuggingFace |
| `accelerate` | Hỗ trợ load model lên GPU |

---

## 🔗 API Endpoints

Base URL: `http://localhost:8006/api/v1`

### POST `/embed`

Tạo embedding vectors cho danh sách text (tối đa 100).

```bash
curl -X POST http://localhost:8006/api/v1/embed \
  -H "Content-Type: application/json" \
  -d '{"texts": ["Xin chào", "Hello world"]}'
```

Response:
```json
{
  "status": 200,
  "result": [[0.01, -0.02, ...], [0.03, 0.01, ...]],
  "description": ""
}
```

### POST `/rerank`

Xếp hạng documents theo mức độ liên quan với query (tối đa 100 documents).

```bash
curl -X POST http://localhost:8006/api/v1/rerank \
  -H "Content-Type: application/json" \
  -d '{"query": "Thủ đô Việt Nam?", "documents": ["Hà Nội là thủ đô", "Hôm nay trời mưa"]}'
```

Response:
```json
{
  "status": 200,
  "result": [
    {"index": 0, "document": "Hà Nội là thủ đô", "score": 6.44},
    {"index": 1, "document": "Hôm nay trời mưa", "score": -10.99}
  ],
  "description": ""
}
```

---

## 🚀 Cách chạy

### 1. Yêu cầu

- **Python** >= 3.10
- **GPU NVIDIA** với CUDA
- **VRAM** >= 4GB (2 model tổng ~3GB)

### 2. Cài thư viện

```bash
cd embeding
pip install -r requirements.txt
```

### 3. Chạy server

```bash
cd embeding
python main.py
```

> ⏳ Lần đầu chạy sẽ tự download model từ HuggingFace (~3.5GB). Các lần sau load từ cache.

Server chạy tại: **http://localhost:8006**

Swagger UI: **http://localhost:8006/docs**
