Create Contract

/api/v1/contracts/upload-template
Upload file template hợp đồng (.docx) lên server.

/api/v1/contracts/upload-multiple-templates
Upload nhiều file template hợp đồng (.docx) cùng lúc.

/api/v1/contracts/create-contract-templated
Luồng 1: Tạo hợp đồng với SSE streaming dựa trên Template.

/api/v1/contracts/create-contract-fast
Luồng 2: LLM tạo hợp đồng siêu nhanh không cần template.

/api/v1/contracts/create-contract-reasoning
Luồng 3: Multi-Agent AI tạo hợp đồng chặt chẽ qua cơ chế kiểm duyệt.

/api/v1/contracts/download-contract/{filename}
Download file hợp đồng đã tạo theo tên file.

/api/v1/contracts/load-template
Lấy danh sách tất cả template hợp đồng đã upload.

/api/v1/contracts/load-contract
Lấy danh sách tất cả hợp đồng đã tạo.

/api/v1/contracts/delete-template/{id}
Xóa template hợp đồng theo ID. Lưu ý: Khi xóa template, nếu có hợp đồng nào đang sử dụng template này thì sẽ bị xóa cùng.

/api/v1/contracts/delete-contract/{id}
Xóa hợp đồng theo ID.

/api/v1/contracts/history
Lấy lịch sử chat theo session.

/api/v1/contracts/session
Lấy danh sách session. Truyền user_id để lọc theo user.

/api/v1/contracts/session/{id}
Xóa session và toàn bộ contract + history liên quan.

RAG Services

/api/v1/rags/rag-contract
Truy vấn RAG - tìm kiếm tài liệu liên quan và tạo câu trả lời.
Input: request (rag_input_request): Chứa query, id_user, session_id. db (Session): Database session (inject qua Depends).
Output: dict: Kết quả truy vấn (status, session, mess).

/api/v1/rags/rag-contract-fast
Truy vấn RAG Contract Fast — SSE streaming.
Trả về Server-Sent Events stream, mỗi event là JSON: {"user_id", "session_id", "title", "mess", "end"}

/api/v1/rags/test-upload
Endpoint trả về trang HTML để test upload nhiều file.

/api/v1/rags/test-rag-contract-fast
Endpoint trả về trang HTML để test SSE streaming của rag-contract-fast.

/api/v1/rags/rag-upload
Upload danh sách file tài liệu vào hệ thống RAG để index.
Input: files (list[UploadFile]): Danh sách file tài liệu (PDF, DOCX, ...). Mặc định là mảng rỗng để chặn lỗi 422 từ FastAPI.
Output: dict: Kết quả upload. Trả về status 400 nếu không có file nào được đính kèm.

/api/v1/rags/file
Lấy danh sách tất cả file tài liệu đã upload.
Output: dict: Danh sách file (status, result).

/api/v1/rags/file
Xóa một file tài liệu đã upload (Postgres, Qdrant, MinIO).
Input: path (str): Tên file cần xóa.

/api/v1/rags/sesion
Lấy danh sách tất cả session RAG.
Input: db (Session): Database session (inject qua Depends).
Output: dict: Danh sách session (status, result).

/api/v1/rags/sesion/{id}
Xóa session RAG và toàn bộ lịch sử liên quan.
Input: id (int): ID session cần xóa. db (Session): Database session (inject qua Depends).
Output: dict: Kết quả xóa (status, result).

/api/v1/rags/session/pin/{id}
Ghim một session RAG.

/api/v1/rags/session/pin/{id}
Bỏ ghim một session RAG.

/api/v1/rags/session/path
Thêm một file_path vào session.

/api/v1/rags/session/path
Xóa một file_path khỏi session.

/api/v1/rags/session/rename
Đổi tên session RAG

/api/v1/rags/history
Lấy lịch sử chat RAG theo session.
Input: request (history_reques): Chứa session_id và user_id. db (Session): Database session (inject qua Depends).
Output: dict: Danh sách tin nhắn trong session (status, result).