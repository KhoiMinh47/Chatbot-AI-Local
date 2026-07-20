# Token Management Report

> Cập nhật: 20/07/2026 — các giá trị dưới đây là giới hạn của pipeline hiện tại.

## Cách hiểu các giới hạn token

| Thuật ngữ           | Ý nghĩa ngắn gọn |
|---------------------|------------------|
| Context window      | Tổng token tối đa model/NIM nhận trong một request. |
| Context tối đa      | Token tối đa dành cho prompt, câu hỏi, history và tài liệu. |
| Output tối đa       | Token tối đa model được phép sinh ra khi trả lời. |
| Safety reserve      | Token chừa lại cho system prompt, template và khoảng an toàn. |

```text
context đã dùng + output tối đa + safety reserve < context window
```

## 1. Model và tokenizer

| Thành phần              | Giá trị                              |
|-------------------------|--------------------------------------|
| LLM                     | `nvidia/nemotron-nano-9b-v2`         |
| NIM context capability  | `131,072 tokens`                     |
| Tokenizer               | `nemotron-nano-9b-v2`                |
| Cách đếm token          | Exact tokenizer + chat template     |
| Approximation           | Không dùng khi chạy RAG              |

## 2. Token budget theo chế độ

| Chế độ                       | Context window | Context tối đa | Output tối đa | Safety reserve |
|------------------------------|----------------|----------------|---------------|----------------|
| Fast                         | `32,768`       | `8,192`        | `768`         | `1,536`        |
| Fast + tài liệu chi tiết     | `32,768`       | `8,192`        | `1,024`       | `1,536`        |
| Reasoning thông thường       | `32,768`       | `16,384`       | `1,024`       | `2,048`        |
| Reasoning + tóm tắt          | `32,768`       | `24,000`       | `1,536`       | `2,048`        |
| Reasoning + nhiều file       | `65,536`       | `32,768`       | `2,048`       | `4,096`        |

## 3. Giới hạn retrieval và history

| Thành phần                    | Fast             | Reasoning        |
|-------------------------------|------------------|------------------|
| Số subquery tối đa            | `1`              | `3`              |
| Candidate mỗi query           | `12`             | `10`             |
| Tổng candidate tối đa         | `12`             | `30`             |
| Số chunk đưa vào context      | `6`              | `12`             |
| Chunk size                    | `256 tokens`     | `256 tokens`     |
| Chunk overlap                 | `10%`            | `10%`            |
| Conversation history tối đa   | `12,000 tokens`  | `12,000 tokens`  |
| Số lượt history tối đa        | `16 turns`       | `16 turns`       |

Riêng chế độ Reasoning + tóm tắt: tối đa `48 candidates/query`, tổng `144 candidates`.

Với Reasoning nhiều file, mỗi file được truy vấn trong scope riêng; không dùng chung một
subquery cho tất cả file.

## 4. Quy tắc sử dụng token

```text
prompt tokens + output reserve + safety reserve < context window
```

- `prompt tokens`: system prompt, câu hỏi, history và context tài liệu.
- `context tối đa`: giới hạn token dành cho phần dữ liệu đưa vào model.
- `output tối đa`: số token tối đa model được phép sinh.
- `safety reserve`: phần dự phòng cho instruction, template và giới hạn an toàn.
- Context thực tế được đếm bằng tokenizer chính xác trước khi gọi model.

## 5. Lưu ý

- `LLM_CONTEXT_WINDOW=4,096` trong bảng cũ của README không còn phản ánh runtime hiện tại.
- Context window của application thấp hơn capability tối đa của NIM để giữ thời gian phản hồi,
  bộ nhớ và độ ổn định.
- Reasoning hiện dùng retrieval/planning sâu hơn; model-side hidden thinking bị tắt để tránh
  request bị treo mà không trả về nội dung.
