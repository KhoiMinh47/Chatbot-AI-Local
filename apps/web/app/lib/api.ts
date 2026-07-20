/**
 * Phase 8 API client — all backend calls go through the nginx reverse proxy.
 *
 * Token storage uses localStorage so refresh-on-mount works after page reload.
 * The client never knows internal service URLs; every request targets `/api/v1/...`
 * which nginx proxies to the FastAPI backend.
 */

import type {
  Conversation,
  ChatStreamEvent,
  DocumentUploadReceipt,
  JobStatus,
  TokenPair,
  User,
} from "./types";
import { ApiError } from "./types";

const TOKEN_KEY = "ntc_access_token";
const REFRESH_KEY = "ntc_refresh_token";

// ---------------------------------------------------------------- token store

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(REFRESH_KEY);
}

export function storeTokens(pair: TokenPair): void {
  localStorage.setItem(TOKEN_KEY, pair.access_token);
  localStorage.setItem(REFRESH_KEY, pair.refresh_token);
}

export function clearTokens(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_KEY);
}

// ------------------------------------------------------------ fetch helpers

async function parseErrorBody(response: Response): Promise<ApiError> {
  try {
    const body: unknown = await response.json();
    if (typeof body === "object" && body !== null && "detail" in body) {
      const detail = (body as Record<string, unknown>).detail;
      if (typeof detail === "string") {
        return new ApiError(response.status, {
          code: `HTTP_${response.status}`,
          message: detail,
        });
      }
      if (
        typeof detail === "object" &&
        detail !== null &&
        "message" in detail &&
        typeof (detail as Record<string, unknown>).message === "string"
      ) {
        const value = detail as Record<string, unknown>;
        return new ApiError(response.status, {
          code: typeof value.code === "string" ? value.code : `HTTP_${response.status}`,
          message: value.message as string,
        });
      }
    }
  } catch {
    /* response was not JSON */
  }
  return new ApiError(response.status, {
    code: "UNKNOWN",
    message: response.statusText || "Request failed",
  });
}

async function apiFetch<T>(
  path: string,
  init?: RequestInit & { skipAuth?: boolean },
): Promise<T> {
  const headers = new Headers(init?.headers);

  if (!init?.skipAuth) {
    const token = getAccessToken();
    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
    }
  }
  if (!headers.has("Content-Type") && init?.body && typeof init.body === "string") {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(path, { ...init, headers });
  if (response.status === 401 && !init?.skipAuth && getRefreshToken()) {
    try {
      const pair = await apiRefreshTokens();
      const retryHeaders = new Headers(init?.headers);
      retryHeaders.set("Authorization", `Bearer ${pair.access_token}`);
      if (!retryHeaders.has("Content-Type") && init?.body && typeof init.body === "string") {
        retryHeaders.set("Content-Type", "application/json");
      }
      const retry = await fetch(path, { ...init, headers: retryHeaders });
      if (retry.ok) {
        if (retry.status === 204) return undefined as T;
        return (await retry.json()) as T;
      }
    } catch {
      clearTokens();
    }
  }
  if (!response.ok) {
    throw await parseErrorBody(response);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

// ------------------------------------------------------------------- auth

export async function apiLogin(email: string, password: string): Promise<TokenPair> {
  const pair = await apiFetch<TokenPair>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
    skipAuth: true,
  });
  storeTokens(pair);
  return pair;
}

export async function apiRegister(
  email: string,
  password: string,
  displayName: string,
): Promise<User> {
  return apiFetch<User>("/api/v1/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password, display_name: displayName }),
    skipAuth: true,
  });
}

export async function apiVerifyEmail(token: string): Promise<User> {
  return apiFetch<User>("/api/v1/auth/verify-email", {
    method: "POST",
    body: JSON.stringify({ token }),
    skipAuth: true,
  });
}

export async function apiForgotPassword(email: string): Promise<void> {
  return apiFetch<void>("/api/v1/auth/forgot-password", {
    method: "POST",
    body: JSON.stringify({ email }),
    skipAuth: true,
  });
}

export async function apiResetPassword(token: string, newPassword: string): Promise<void> {
  return apiFetch<void>("/api/v1/auth/reset-password", {
    method: "POST",
    body: JSON.stringify({ token, new_password: newPassword }),
    skipAuth: true,
  });
}

export async function apiRefreshTokens(): Promise<TokenPair> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) throw new ApiError(401, { code: "NO_REFRESH", message: "No refresh token" });
  const pair = await apiFetch<TokenPair>("/api/v1/auth/refresh", {
    method: "POST",
    body: JSON.stringify({ refresh_token: refreshToken }),
    skipAuth: true,
  });
  storeTokens(pair);
  return pair;
}

export async function apiLogout(): Promise<void> {
  try {
    await apiFetch<void>("/api/v1/auth/logout", { method: "POST" });
  } finally {
    clearTokens();
  }
}

export async function apiGetMe(): Promise<User> {
  return apiFetch<User>("/api/v1/auth/me");
}

// ------------------------------------------------------------- conversations

export async function apiListConversations(
  page = 1,
  pageSize = 50,
): Promise<Conversation[]> {
  return apiFetch<Conversation[]>(
    `/api/v1/conversations?page=${page}&page_size=${pageSize}`,
  );
}

export async function apiCreateConversation(
  title: string,
  mode: "fast" | "reasoning" = "fast",
): Promise<Conversation> {
  return apiFetch<Conversation>("/api/v1/conversations", {
    method: "POST",
    body: JSON.stringify({ title, mode }),
  });
}

export async function apiGetConversation(id: string): Promise<Conversation> {
  return apiFetch<Conversation>(`/api/v1/conversations/${id}`);
}

export async function apiPatchConversation(
  id: string,
  patch: { title?: string; mode?: string },
): Promise<Conversation> {
  return apiFetch<Conversation>(`/api/v1/conversations/${id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export async function apiDeleteConversation(id: string): Promise<void> {
  return apiFetch<void>(`/api/v1/conversations/${id}`, { method: "DELETE" });
}

export interface MessageRecord {
  id: string;
  conversation_id: string;
  role: "user" | "assistant";
  content: string | null;
  created_at: string;
}

export async function apiListMessages(
  conversationId: string,
  limit = 50,
): Promise<MessageRecord[]> {
  return apiFetch<MessageRecord[]>(
    `/api/v1/conversations/${conversationId}/messages?limit=${limit}`,
  );
}

// ------------------------------------------------------------------ chat SSE

export interface ChatStreamOptions {
  conversationId: string;
  question: string;
  language?: string;
  selectedDocumentIds?: string[];
  responseDepth?: "concise" | "normal" | "detailed";
  onEvent: (event: ChatStreamEvent) => void;
  onError: (error: Error) => void;
  onDone: () => void;
  signal?: AbortSignal;
}

export async function apiChatStream(options: ChatStreamOptions): Promise<void> {
  const token = getAccessToken();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const response = await fetch("/api/v1/chat/stream", {
    method: "POST",
    headers,
    body: JSON.stringify({
      conversation_id: options.conversationId,
      question: options.question,
      language: options.language ?? "vi",
      selected_document_ids: options.selectedDocumentIds ?? [],
      response_depth: options.responseDepth ?? "detailed",
    }),
    signal: options.signal ?? null,
  });

  if (!response.ok) {
    const err = await parseErrorBody(response);
    options.onError(err);
    options.onDone();
    return;
  }

  const reader = response.body?.getReader();
  if (!reader) {
    options.onError(new Error("No response body"));
    options.onDone();
    return;
  }

  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split(/\r?\n/);
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed.startsWith("data: ")) continue;
        const jsonStr = trimmed.slice(6);
        try {
          const event = JSON.parse(jsonStr) as ChatStreamEvent;
          options.onEvent(event);
          if (event.event_type === "done" || event.event_type === "error") {
            options.onDone();
            return;
          }
        } catch {
          /* skip malformed SSE */
        }
      }
    }
    options.onDone();
  } catch (err) {
    if ((err as Error).name === "AbortError") {
      options.onDone();
    } else {
      options.onError(err as Error);
      options.onDone();
    }
  }
}

// ----------------------------------------------------------------- feedback

export async function apiSubmitFeedback(
  messageId: string,
  rating: "thumbs_up" | "thumbs_down",
  reason?: string,
): Promise<void> {
  return apiFetch<void>(`/api/v1/messages/${messageId}/feedback`, {
    method: "POST",
    body: JSON.stringify({ rating, reason: reason ?? null }),
  });
}

// ---------------------------------------------------------------- documents

export async function apiUploadDocument(file: File): Promise<DocumentUploadReceipt> {
  const token = getAccessToken();
  const headers: Record<string, string> = {};
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const formData = new FormData();
  formData.append("file", file);

  // Use AbortController for long timeout (10 minutes for large files)
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 10 * 60 * 1000);

  try {
    const response = await fetch("/documents/upload", {
      method: "POST",
      headers,
      body: formData,
      signal: controller.signal,
    });
    clearTimeout(timeoutId);
    if (!response.ok) throw await parseErrorBody(response);
    return (await response.json()) as DocumentUploadReceipt;
  } catch (error) {
    clearTimeout(timeoutId);
    if (error instanceof Error && error.name === "AbortError") {
      throw new Error("Upload timeout: file upload took too long");
    }
    throw error;
  }
}

export async function apiGetJobStatus(jobId: string): Promise<JobStatus> {
  return apiFetch<JobStatus>(`/documents/jobs/${jobId}`);
}

export async function apiWaitForJob(
  jobId: string,
  onProgress?: (status: JobStatus) => void,
  options: { intervalMs?: number; timeoutMs?: number } = {},
): Promise<JobStatus> {
  const intervalMs = options.intervalMs ?? 2000;
  const timeoutMs = options.timeoutMs ?? 10 * 60 * 1000;
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    const status = await apiGetJobStatus(jobId);
    onProgress?.(status);
    if (["completed", "success", "failed"].includes(status.state)) return status;
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }

  throw new Error("Hết thời gian chờ xử lý tài liệu. Hãy kiểm tra lại thư viện tài liệu.");
}

export async function apiListDocuments(page = 1, pageSize = 50): Promise<{
  documents: import("./types").DocumentView[];
  total: number;
  page: number;
  page_size: number;
}> {
  return apiFetch(`/documents?page=${page}&page_size=${pageSize}`);
}

export async function apiDeleteDocument(documentId: string): Promise<void> {
  return apiFetch(`/documents/${documentId}`, { method: "DELETE" });
}

// -------------------------------------------------------------------- admin

export async function apiAdminGetStats(): Promise<import("./types").AdminStats> {
  return apiFetch<import("./types").AdminStats>("/api/v1/admin/stats");
}

export async function apiAdminGetConfig(): Promise<import("./types").AdminConfig> {
  return apiFetch<import("./types").AdminConfig>("/api/v1/admin/config");
}

export async function apiAdminGetServices(): Promise<import("./types").ServiceHealth> {
  return apiFetch<import("./types").ServiceHealth>("/api/v1/admin/services");
}

export async function apiAdminListUsers(page = 1, pageSize = 50): Promise<import("./types").AdminUser[]> {
  return apiFetch<import("./types").AdminUser[]>(`/api/v1/admin/users?page=${page}&page_size=${pageSize}`);
}

export async function apiAdminPatchUser(
  userId: string,
  patch: { role?: "user" | "admin"; display_name?: string }
): Promise<import("./types").AdminUser> {
  return apiFetch<import("./types").AdminUser>(`/api/v1/admin/users/${userId}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export async function apiAdminGetAuditLogs(page = 1, pageSize = 100): Promise<import("./types").AuditLog[]> {
  return apiFetch<import("./types").AuditLog[]>(`/api/v1/admin/audit-logs?page=${page}&page_size=${pageSize}`);
}

export async function apiAdminGetDocuments(page = 1, pageSize = 50): Promise<import("./types").AdminDocumentsResponse> {
  return apiFetch<import("./types").AdminDocumentsResponse>(`/api/v1/admin/documents?page=${page}&page_size=${pageSize}`);
}
