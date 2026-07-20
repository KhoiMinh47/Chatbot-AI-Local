import { axiosClient, axiosClientFile, redirectIfUnauthorized } from './axiosClient';
import { buildApiUrl } from './apiBase';

/**
 * Lấy danh sách file tài liệu đã upload.
 * GET /api/v1/rags/file
 * Response: { status: 200, result: ["file1.pdf", "file2.docx", ...] }
 */
export async function loadFile() {
  const res = await axiosClient.get('/api/v1/rags/file');
  return res.data.result;
}

/**
 * Xóa một file tài liệu đã upload.
 * DELETE /api/v1/rags/file?path=...
 */
export async function deleteFile(path) {
  const res = await axiosClient.delete(`/api/v1/rags/file?path=${encodeURIComponent(path)}`);
  return res.data;
}

/**
 * Lấy danh sách session RAG.
// ...existing code...

/**
 * Đính kèm file vào session.
 * POST /api/v1/rags/session/path
 * Body: session_id, path
 */
export async function attachFileToSession(sessionId, path) {
  const params = new URLSearchParams();
  params.append('session_id', sessionId);
  params.append('path', path);
  const res = await axiosClient.post('/api/v1/rags/session/path', params, {
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
      'accept': 'application/json'
    }
  });
  return res.data;
}

/**
 * Gỡ file khỏi session.
 * DELETE /api/v1/rags/session/path
 * Body: session_id, path
 */
export async function detachFileFromSession(sessionId, path) {
  const params = new URLSearchParams();
  params.append('session_id', sessionId);
  params.append('path', path);
  const res = await axiosClient.delete('/api/v1/rags/session/path', {
    data: params,
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
      'accept': 'application/json'
    }
  });
  return res.data;
}

/**
 * Tạo một session RAG mới với tên cho trước.
 * POST /api/v1/rags/session
 * Body: { name: string }
 */
export async function createSession(name) {
  const res = await axiosClient.post('/api/v1/rags/session', {
    name: name
  });
  return res.data;
}

/**
 * GET /api/v1/rags/sesion
 * Response: { status: 200, result: [1, 2, 3, ...] }
 */
export async function loadSession() {
  const res = await axiosClient.get('/api/v1/rags/sesion');
  // Kết quả RAG hiện tại trả về list ID hoặc list object tùy version backend
  return res.data.result;
}

/**
 * Xóa session RAG và toàn bộ lịch sử liên quan.
 * DELETE /api/v1/rags/sesion/{id}
 * Response: { status: 200, result: "ok" }
 */
export async function deleteSession(id) {
  const res = await axiosClient.delete(`/api/v1/rags/sesion/${id}`);
  return res.data;
}

/**
 * Đổi tên session RAG.
 * PUT /api/v1/rags/session/rename
 * Body: { session_id: int, new_name: string }
 */
export async function renameSession(id, newName) {
  const res = await axiosClient.put(`/api/v1/rags/session/rename`, {
    session_id: id,
    new_name: newName
  });
  return res.data;
}

/**
 * Ghim session RAG.
 * POST /api/v1/rags/session/pin/{id}
 */
export async function pinSession(id) {
  const res = await axiosClient.post(`/api/v1/rags/session/pin/${id}`);
  return res.data;
}

/**
 * Bỏ ghim session RAG.
 * DELETE /api/v1/rags/session/pin/{id}
 */
export async function unpinSession(id) {
  const res = await axiosClient.delete(`/api/v1/rags/session/pin/${id}`);
  return res.data;
}

/**
 * Lấy lịch sử chat RAG theo session.
 * POST /api/v1/rags/history
 * Body: { session_id: int }
 * Response: { status: 200, result: [{ id, user_id, session_id, role, mess }, ...] }
 */
export async function loadHistory(sessionId) {
  if (!sessionId || sessionId === -1) return [];
  const res = await axiosClient.post('/api/v1/rags/history', {
    session_id: Number(sessionId),
  });
  return res.data.result;
}

/**
 * Gửi câu hỏi RAG (sử dụng endpoint rag-contract-fast).
 * POST /api/v1/rags/rag-contract-fast
 * Body: { session_id: int, user_input: string, model_name: string }
 * Response: { status: 200, result: [false, "assistant response text"] }
 */
export async function sendQuery(sessionId, input) {
  const res = await axiosClient.post('/api/v1/rags/rag-contract-fast', {
    session_id: sessionId,
    user_input: input,
  });
  return res.data;
}

/**
 * Lấy danh sách các model vLLM khả dụng từ backend.
 * GET /api/v1/rags/models
 * Response: { status: 200, models: ["model1", "model2", ...] }
 */
export async function getRagModels() {
  const res = await axiosClient.get('/api/v1/rags/models');
  return res.data;
}

/**
 * Gửi câu hỏi RAG dạng luồng (Server-Sent Events).
 * POST /api/v1/rags/stream
 * Body: { session_id: int, user_input: string, model_name: string }
 */
export async function sendQueryStream(sessionId, input, modelName, queryFlow = "fast", onMessage) {
  // Backward compatible: nếu tham số thứ 4 là callback cũ, tự động gán về fast.
  if (typeof queryFlow === 'function' && onMessage === undefined) {
    onMessage = queryFlow;
    queryFlow = "fast";
  }

  try {
    const response = await fetch(buildApiUrl('/api/v1/rags/rag-contract-fast'), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      credentials: 'include',
      body: JSON.stringify({
        session_id: sessionId,
        user_input: input,
        model_name: modelName || "Qwen/Qwen2.5-VL-7B-Instruct-FP8",
        query_flow: queryFlow || "fast",
      }),
    });

    // Kiểm tra 401/403 trước khi đọc stream — fetch() không qua axiosClient interceptor
    if (response.status === 401 || response.status === 403) {
      redirectIfUnauthorized(response);
      return; // navigation đã được khởi động, dừng xử lý
    }

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    if (!response.body) {
      throw new Error("ReadableStream not yet supported in this browser.");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // SSE blocks are separated by double newlines \n\n
      let boundary = buffer.indexOf('\n\n');
      while (boundary !== -1) {
        const chunk = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2); // Remove processed chunk

        // Process lines within this chunk
        const lines = chunk.split('\n');
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const dataStr = line.substring(6).trim();
            if (dataStr && dataStr !== '[DONE]') {
              try {
                const parsedData = JSON.parse(dataStr);
                onMessage(parsedData);
              } catch (err) {
                console.error("Lỗi parse JSON stream:", err, dataStr);
              }
            }
          }
        }
        boundary = buffer.indexOf('\n\n');
      }
    }

    // Process any remaining buffer if connection closes without trailing \n\n
    if (buffer.trim().length > 0) {
      const lines = buffer.split('\n');
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const dataStr = line.substring(6).trim();
          if (dataStr && dataStr !== '[DONE]') {
            try {
              const parsedData = JSON.parse(dataStr);
              onMessage(parsedData);
            } catch (err) { }
          }
        }
      }
    }

  } catch (error) {
    console.error("Lỗi gọi stream API:", error);
    throw error;
  }
}

/**
 * Upload file tài liệu vào hệ thống RAG.
 * POST /api/v1/rags/rag-upload
 * Body: FormData with files
 * Response: { status: 200, result: ... }
 */
export async function uploadFile(file, sessionId = 0, onProgress) {
  const formData = new FormData();
  formData.append('files', file);
  formData.append('session_id', String(sessionId));
  const res = await axiosClientFile.post('/api/v1/rags/rag-upload', formData, {
    onUploadProgress: (progressEvent) => {
      if (onProgress) {
        const percentCompleted = Math.round((progressEvent.loaded * 100) / progressEvent.total);
        onProgress(percentCompleted);
      }
    }
  });
  return res.data;
}
