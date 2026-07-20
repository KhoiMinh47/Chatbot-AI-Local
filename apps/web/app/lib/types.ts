/**
 * Phase 8 shared TypeScript types.
 *
 * Every type mirrors an API response schema from Phase 7. Field names use the
 * exact JSON keys so `fetch().json()` produces these shapes without mapping.
 */

// ------------------------------------------------------------------ auth

export interface User {
  id: string;
  tenant_id: string;
  email: string;
  display_name: string;
  role: "user" | "admin";
  is_verified: boolean;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

// -------------------------------------------------------------- conversations

export interface Conversation {
  id: string;
  tenant_id: string;
  user_id: string;
  title: string;
  mode: "fast" | "reasoning";
  created_at: string;
  updated_at: string;
}

// ----------------------------------------------------------------- messages

export interface ChatStreamEvent {
  event_type:
    | "status"
    | "retrieval_summary"
    | "retrieval_start"
    | "retrieval_done"
    | "generation_start"
    | "token"
    | "citation"
    | "sources"
    | "usage"
    | "done"
    | "error"
    | "insufficient_evidence";
  request_id: string;
  sequence: number;
  data: Record<string, unknown>;
}

export interface Citation {
  citation_id: string;
  document_id: string;
  version_id: string;
  chunk_id: string;
  source_name: string;
  page: number | null;
  slide: number | null;
  sheet: string | null;
  cell_range: string | null;
  line_start: number | null;
  line_end: number | null;
  section_path: string[];
  text: string;
  score: number;
  verified: boolean;
}

// ----------------------------------------------------------------- documents

export interface DocumentView {
  id: string;
  tenant_id: string;
  owner_id: string;
  source_name: string;
  mime_type: string;
  size_bytes: number;
  language: string | null;
  state: string;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  indexed_at: string | null;
}

export interface DocumentUploadReceipt {
  document_id: string;
  version_id: string;
  job_id: string;
  duplicate: boolean;
  message: string;
}

export interface JobStatus {
  job_id: string;
  document_id: string;
  version_id: string;
  state: string;
  progress_percent: number;
  progress_message: string | null;
  error_code: string | null;
  error_message: string | null;
  retry_count: number;
  completed_at: string | null;
  parse_quality_status?: "ready" | "needs_review" | null;
  parse_coverage_ratio?: number | null;
  parse_warnings?: string[];
}

// -------------------------------------------------------------------- errors

export interface ApiErrorDetail {
  code: string;
  message: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, detail: ApiErrorDetail) {
    super(detail.message);
    this.name = "ApiError";
    this.status = status;
    this.code = detail.code;
  }
}

// ---------------------------------------------------------- chat message (UI)

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  isStreaming?: boolean;
  progressLabel?: string | undefined;
  startedAtMs?: number;
  completedAtMs?: number;
}

// ------------------------------------------------------------------ admin

export interface AdminStats {
  users_count: number;
  documents_count: number;
}

export interface AdminConfig {
  nim_clients_enabled: boolean;
  llm_model: string | null;
  llm_model_version: string | null;
  embed_model: string | null;
  embed_model_version: string | null;
  rerank_model: string | null;
  rerank_model_version: string | null;
  prompt_version: string;
  prompt_sha256: string;
  graph_version: string;
}

export interface DependencyStatus {
  name: string;
  status: string;
  required_for_readiness: boolean;
}

export interface ServiceHealth {
  ready: boolean;
  dependencies: DependencyStatus[];
}

export interface AuditLog {
  id: string;
  actor_id: string;
  action: string;
  target_type: string | null;
  target_id: string | null;
  created_at: string;
}

export interface AdminUser {
  id: string;
  tenant_id: string;
  email: string;
  display_name: string;
  role: "user" | "admin";
  is_verified: boolean;
  created_at: string;
}

export interface AdminDocument {
  id: string;
  source_name: string;
  mime_type: string;
  state: string;
  error_code: string | null;
  created_at: string;
}

export interface AdminDocumentsResponse {
  documents: AdminDocument[];
  total: number;
}
