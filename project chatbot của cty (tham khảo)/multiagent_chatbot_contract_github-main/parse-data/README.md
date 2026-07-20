# Parse-Data Service

API parse đa định dạng (PDF, Docx, PPTX, Excel, Ảnh, HTML...) sang markdown sử dụng **Docling** (IBM) với GPU acceleration (CUDA). Hỗ trợ chạy không block event loop bằng `asyncio.to_thread` chuẩn F8.

---

## 📁 Cây thư mục

```
parse-data/
├── main.py                        # Entry point - FastAPI app, CORS, health check
├── requirements.txt               # Danh sách thư viện
├── src/
│   ├── config/
│   │   └── docling_config.py      # Cấu hình Docling + GPU (AUTO detect CUDA/CPU)
│   ├── model/
│   │   └── response_model.py      # Response models chuẩn (status, result, description)
│   ├── router/
│   │   └── parse_router.py        # Endpoint POST /parse (validate + xử lý đa định dạng)
│   └── service/
│       └── parse_service.py       # Logic parse: lưu tạm → convert (chạy background thread tránh block main event loop) → xóa tạm
└── README.md
```

---

## 📦 Thư viện sử dụng

| Thư viện | Mô tả |
|---|---|
| `fastapi` | Web framework chính |
| `uvicorn` | ASGI server |
| `python-multipart` | Hỗ trợ upload file multipart |
| `docling` | Parse PDF sang markdown (IBM) - tự kéo torch, transformers |

---

## 🔗 API Endpoints

Base URL: `http://localhost:8005/api/v1`

| Method | Endpoint | Mô tả |
|---|---|---|
| GET | `/health` | Kiểm tra server hoạt động |
| POST | `/api/v1/parse` | Parse tài liệu đa định dạng sang markdown (tối đa 10 file) |

### POST `/api/v1/parse`

**Request:** `multipart/form-data` với field `files` (tối đa 10 file, ví dụ: .pdf, .docx, .png)

```bash
curl -X POST http://localhost:8005/api/v1/parse \
  -F "files=@file1.pdf" \
  -F "files=@file2.pdf"
```

**Response thành công:**
```json
{
  "status": 200,
  "result": [
    { "file_name": "file1.pdf", "content": "# Nội dung markdown..." },
    { "file_name": "file2.pdf", "content": "# Nội dung markdown..." }
  ],
  "description": ""
}
```

**Response lỗi:**
```json
{
  "status": 400,
  "result": "",
  "description": "Định dạng file không được hỗ trợ. Các file lỗi: file.exe"
}
```

---

## 🚀 Cách chạy

### 1. Yêu cầu

- **Python** >= 3.10
- **GPU NVIDIA** (khuyến nghị) hoặc CPU

### 2. Cài thư viện

```bash
cd parse-data
pip install -r requirements.txt
```

> ⚠️ Nếu muốn chạy GPU, cài `torch` với CUDA trước:
> ```bash
> pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
> ```

### 3. Chạy server

```bash
cd parse-data
python main.py
```

Server chạy tại: **http://localhost:8005**

Swagger UI: **http://localhost:8005/docs**
