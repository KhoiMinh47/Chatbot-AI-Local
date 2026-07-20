import { axiosClient, axiosClientFile, redirectIfUnauthorized } from './axiosClient';
import { buildApiUrl } from './apiBase';

/**
 * Lấy danh sách template hợp đồng.
 * GET /api/v1/contracts/load-template
 * Response: { status: 200, result: ["template_name1", ...] }
 */
export async function loadTemplateHome() {
  const res = await axiosClient.get('/api/v1/contracts/load-template');
  // result giờ là [{id, name}] — trả nguyên để component tự xử lý
  return res.data.result;
}



/**
 * Upload danh sách file template hợp đồng (.docx).
 * POST /api/v1/contracts/upload-multiple-templates
 */
export async function uploadMultipleTemplates(files, onProgress) {
  const formData = new FormData();
  for (let i = 0; i < files.length; i++) {
    formData.append('files', files[i]);
  }
  const res = await axiosClientFile.post('/api/v1/contracts/upload-multiple-templates', formData, {
    onUploadProgress: (progressEvent) => {
      if (onProgress) {
        const percentCompleted = Math.round((progressEvent.loaded * 100) / progressEvent.total);
        onProgress(percentCompleted);
      }
    }
  });
  return res.data;
}

async function createContractStream(endpoint, payload, onEvent) {
  const res = await fetch(buildApiUrl(endpoint), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(payload),
  });

  // Kiểm tra 401/403 trước khi đọc stream — fetch() không qua axiosClient interceptor
  if (res.status === 401 || res.status === 403) {
    redirectIfUnauthorized(res);
    return { session_id: payload.session_id, path_name: '', download_url: '', summary: '' };
  }

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`HTTP ${res.status}: ${text}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let result = { session_id: payload.session_id, path_name: '', download_url: '', summary: '' };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split('\n\n');
    buffer = parts.pop();
    for (const part of parts) {
      const line = part.trim();
      if (!line.startsWith('data:')) continue;
      try {
        const ev = JSON.parse(line.slice(5).trim());
        if (onEvent) onEvent(ev);
        if (ev.session_id) result.session_id = ev.session_id;
        if (ev.mess) result.summary += ev.mess;
        if (ev.end && ev.path_name) {
          result.path_name = ev.path_name;
          result.download_url = ev.download_url || '';
        }
      } catch (_) { }
    }
  }
  return result;
}

/**
 * Tạo hợp đồng nhanh (không cần template).
 */
export async function createContractFast(sessionId, input, modelName, onEvent) {
  const payload = { session_id: sessionId, user_input: input };
  if (modelName) payload.model_name = modelName;
  return createContractStream('/api/v1/contracts/create-contract-fast', payload, onEvent);
}

/**
 * Tạo hợp đồng theo template.
 */
export async function createContractTemplated(sessionId, templateId, input, modelName, onEvent) {
  const payload = { session_id: sessionId, template_id: templateId, user_input: input };
  if (modelName) payload.model_name = modelName;
  return createContractStream('/api/v1/contracts/create-contract-templated', payload, onEvent);
}

/**
 * Tạo hợp đồng theo luồng tư duy.
 */
export async function createContractReasoning(sessionId, input, modelName, onEvent) {
  const payload = { session_id: sessionId, user_input: input };
  if (modelName) payload.model_name = modelName;
  return createContractStream('/api/v1/contracts/create-contract-reasoning', payload, onEvent);
}

/**
 * Wrapper createFile: chuyển user_input vào.
 */
export async function createFile(userInput, sessionId, modelName, onEvent) {
  return createContractFast(sessionId, userInput, modelName, onEvent);
}



/**
 * Lấy danh sách session hợp đồng.
 * GET /api/v1/contracts/session
 * Response: { status: 200, result: [{ id, name, created_at }, ...] }
 */
export async function loadSession() {
  const res = await axiosClient.get('/api/v1/rags/sesion');
  return res.data.result;
}

/**
 * Xóa session và toàn bộ contract + history liên quan.
 * DELETE /api/v1/contracts/session/{id}
 */
export async function deleteSession(id) {
  const res = await axiosClient.delete(`/api/v1/rags/sesion/${id}`);
  return res.data;
}

/**
 * Đổi tên session hợp đồng.
 * PUT /api/v1/contracts/session/rename
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
 * Lấy lịch sử chat contract theo session.
 * POST /api/v1/contracts/history
 * Body: { session_id }
 * Response: { status: 200, result: [{ id, role, mess }, ...] }
 */
export async function loadHistory(sessionId) {
  if (sessionId === -1) return [];
  const res = await axiosClient.post('/api/v1/rags/history', {
    session_id: sessionId,
  });
  return res.data.result;
}

/**
 * Xóa template hợp đồng theo ID.
 * DELETE /api/v1/contracts/delete-template/{id}
 */
export async function deleteTemplate(templateId) {
  const res = await axiosClient.delete(`/api/v1/contracts/delete-template/${templateId}`);
  return res.data;
}

/**
 * Download hợp đồng đã tạo.
 * GET /api/v1/contracts/download-contract/{filename}
 */
export async function downloadContract(filename) {
  const res = await axiosClient.get(`/api/v1/contracts/download-contract/${filename}`, {
    responseType: 'blob',
  });
  const url = window.URL.createObjectURL(new Blob([res.data]));
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  window.URL.revokeObjectURL(url);
}

/**
 * Ghim template vào session contract.
 * POST /api/v1/contracts/session/path
 */
export async function pinContractPath(sessionId, filePath) {
  const res = await axiosClient.post('/api/v1/contracts/session/path', {
    session_id: sessionId,
    file_path: filePath
  });
  return res.data;
}

/**
 * Gỡ ghim template khỏi session contract.
 * DELETE /api/v1/contracts/session/path
 */
export async function unpinContractPath(sessionId, filePath) {
  const res = await axiosClient.delete('/api/v1/contracts/session/path', {
    data: {
      session_id: sessionId,
      file_path: filePath
    }
  });
  return res.data;
}

/**
 * Lấy danh sách hợp đồng đã tạo.
 * GET /api/v1/contracts/load-contract
 */
export async function loadContract() {
  const res = await axiosClient.get('/api/v1/contracts/load-contract');
  return res.data.result;
}

/**
 * Xóa hợp đồng đã tạo.
 * DELETE /api/v1/contracts/delete-contract/{id}
 */
export async function deleteContract(contractId) {
  const res = await axiosClient.delete(`/api/v1/contracts/delete-contract/${contractId}`);
  return res.data;
}
