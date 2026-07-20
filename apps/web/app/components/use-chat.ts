"use client";

/**
 * Phase 8 custom hook for chat streaming and conversation management.
 *
 * Implements Optimistic UI updates, SSE streaming parser, generation cancellation,
 * and conversational turns management matching Phase 6 state machine.
 * Phase 9: Loads persisted message history from server on conversation switch.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { apiChatStream, apiListMessages } from "../lib/api";
import { createClientId } from "../lib/client-id";
import type { Citation, ChatMessage, ChatStreamEvent } from "../lib/types";

export function useChat(conversationId: string | null) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const abortControllerRef = useRef<AbortController | null>(null);
  const skipHistoryConversationRef = useRef<string | null>(null);

  // Load message history when conversation changes
  useEffect(() => {
    if (!conversationId) {
      setMessages([]);
      return;
    }
    if (skipHistoryConversationRef.current === conversationId) {
      skipHistoryConversationRef.current = null;
      return;
    }
    let cancelled = false;
    apiListMessages(conversationId)
      .then((records) => {
        if (cancelled) return;
        const loaded: ChatMessage[] = records
          .filter((r) => r.content)
          .map((r) => ({
            id: r.id,
            role: r.role,
            content: r.content ?? "",
          }));
        setMessages(loaded);
      })
      .catch(() => {
        // Silently fail — new conversation or no messages
        if (!cancelled) setMessages([]);
      });
    return () => {
      cancelled = true;
    };
  }, [conversationId]);

  const startStreaming = useCallback(
    async (
      question: string,
      mode: "fast" | "reasoning",
      selectedDocumentIds: string[] = [],
      conversationIdOverride?: string,
    ) => {
      const targetConversationId = conversationIdOverride ?? conversationId;
      if (!targetConversationId) return;

      // Cancel any active stream
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }

      const userMsgId = createClientId();
      const assistantMsgId = createClientId();

      const userMessage: ChatMessage = {
        id: userMsgId,
        role: "user",
        content: question,
      };

      const assistantMessage: ChatMessage = {
        id: assistantMsgId,
        role: "assistant",
        content: "",
        citations: [],
        isStreaming: true,
        progressLabel: "Đang gửi câu hỏi...",
        startedAtMs: Date.now(),
      };

      setMessages((prev) => [...prev, userMessage, assistantMessage]);
      setIsStreaming(true);

      const controller = new AbortController();
      abortControllerRef.current = controller;

      let answerBuffer = "";
      let activeCitations: Citation[] = [];

      try {
        await apiChatStream({
          conversationId: targetConversationId,
          question,
          language: "vi",
          selectedDocumentIds,
          signal: controller.signal,
          onEvent: (event: ChatStreamEvent) => {
            switch (event.event_type) {
              case "status": {
                const phase = (event.data.phase as string) || "processing";
                const labels: Record<string, string> = {
                  validated: "Đang chuẩn bị câu hỏi...",
                  memory_loaded: "Đang đọc ngữ cảnh hội thoại...",
                  query_classified: "Đang phân tích câu hỏi...",
                  planning: "Đang phân tích câu hỏi...",
                  searching: "Đang tìm kiếm trong tài liệu...",
                  retrieval: "Đang tìm kiếm trong tài liệu...",
                  generating: "Đang tạo câu trả lời...",
                  generation: "Đang tạo câu trả lời...",
                  validating: "Đang kiểm tra nguồn trích dẫn...",
                  processing: "Đang xử lý...",
                };
                setMessages((prev) =>
                  prev.map((msg) =>
                    msg.id === assistantMsgId
                      ? {
                          ...msg,
                          progressLabel: labels[phase] ?? "Đang xử lý...",
                        }
                      : msg,
                  ),
                );
                break;
              }
              case "retrieval_summary": {
                const contextCount = event.data.context_count;
                const progressLabel =
                  typeof contextCount === "number"
                    ? `Đã chọn ${contextCount} đoạn ngữ cảnh. Đang chuẩn bị trả lời...`
                    : "Đã tìm thấy dữ liệu. Đang chuẩn bị trả lời...";
                setMessages((prev) =>
                  prev.map((msg) =>
                    msg.id === assistantMsgId
                      ? { ...msg, progressLabel }
                      : msg,
                  ),
                );
                break;
              }
              case "token": {
                const token = (event.data.text as string) || "";
                answerBuffer += token;
                setMessages((prev) =>
                  prev.map((msg) =>
                    msg.id === assistantMsgId
                      ? { ...msg, content: answerBuffer }
                      : msg,
                  ),
                );
                break;
              }
              case "citation": {
                const citation: Citation = {
                  citation_id: (event.data.citation_id as string) || "",
                  document_id: (event.data.document_id as string) || "",
                  version_id: (event.data.version_id as string) || "",
                  chunk_id: (event.data.chunk_id as string) || "",
                  source_name: (event.data.source_name as string) || "",
                  page:
                    typeof event.data.page === "number"
                      ? event.data.page
                      : null,
                  slide:
                    typeof event.data.slide === "number"
                      ? event.data.slide
                      : null,
                  sheet:
                    typeof event.data.sheet === "string"
                      ? event.data.sheet
                      : null,
                  cell_range:
                    typeof event.data.cell_range === "string"
                      ? event.data.cell_range
                      : null,
                  line_start:
                    typeof event.data.line_start === "number"
                      ? event.data.line_start
                      : null,
                  line_end:
                    typeof event.data.line_end === "number"
                      ? event.data.line_end
                      : null,
                  section_path: Array.isArray(event.data.section_path)
                    ? (event.data.section_path as string[])
                    : [],
                  text: (event.data.excerpt as string) || "",
                  score:
                    typeof event.data.score === "number" ? event.data.score : 0,
                  verified: event.data.verified === true,
                };
                activeCitations = [
                  ...activeCitations.filter(
                    (item) => item.citation_id !== citation.citation_id,
                  ),
                  citation,
                ];
                setMessages((prev) =>
                  prev.map((msg) =>
                    msg.id === assistantMsgId
                      ? { ...msg, citations: activeCitations }
                      : msg,
                  ),
                );
                break;
              }
              case "sources": {
                const rawSources = event.data.sources as Record<
                  string,
                  unknown
                >[];
                if (Array.isArray(rawSources)) {
                  activeCitations = rawSources.map((s) => ({
                    citation_id: (s.citation_id as string) || "",
                    document_id: (s.document_id as string) || "",
                    version_id: (s.version_id as string) || "",
                    chunk_id: (s.chunk_id as string) || "",
                    source_name: (s.source_name as string) || "",
                    page: typeof s.page === "number" ? s.page : null,
                    slide: typeof s.slide === "number" ? s.slide : null,
                    sheet: typeof s.sheet === "string" ? s.sheet : null,
                    cell_range:
                      typeof s.cell_range === "string" ? s.cell_range : null,
                    line_start:
                      typeof s.line_start === "number" ? s.line_start : null,
                    line_end:
                      typeof s.line_end === "number" ? s.line_end : null,
                    section_path: Array.isArray(s.section_path)
                      ? (s.section_path as string[])
                      : [],
                    text: (s.text as string) || "",
                    score: typeof s.score === "number" ? s.score : 0,
                    verified: s.verified === true,
                  }));
                  setMessages((prev) =>
                    prev.map((msg) =>
                      msg.id === assistantMsgId
                        ? { ...msg, citations: activeCitations }
                        : msg,
                    ),
                  );
                }
                break;
              }
              case "insufficient_evidence": {
                answerBuffer =
                  "Tôi chưa tìm thấy đủ bằng chứng trong các tài liệu mà bạn được phép truy cập để trả lời câu hỏi này.";
                setMessages((prev) =>
                  prev.map((msg) =>
                    msg.id === assistantMsgId
                      ? { ...msg, content: answerBuffer }
                      : msg,
                  ),
                );
                break;
              }
              case "error": {
                const errMsg =
                  (event.data.message as string) ||
                  "Đã xảy ra lỗi khi tạo câu trả lời.";
                answerBuffer = `[Lỗi hệ thống]: ${errMsg}`;
                setMessages((prev) =>
                  prev.map((msg) =>
                    msg.id === assistantMsgId
                      ? { ...msg, content: answerBuffer }
                      : msg,
                  ),
                );
                break;
              }
              default:
                break;
            }
          },
          onError: (err) => {
            if (err.name === "AbortError") return;
            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === assistantMsgId
                  ? {
                      ...msg,
                      content: `[Lỗi hệ thống]: Không thể kết nối với dịch vụ RAG. Chi tiết: ${err.message}`,
                    }
                  : msg,
              ),
            );
          },
          onDone: () => {
            const completedAtMs = Date.now();
            setIsStreaming(false);
            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === assistantMsgId
                  ? {
                      ...msg,
                      isStreaming: false,
                      progressLabel: undefined,
                      completedAtMs: msg.completedAtMs ?? completedAtMs,
                    }
                  : msg,
              ),
            );
            abortControllerRef.current = null;
          },
        });
      } catch (err) {
        if ((err as Error).name === "AbortError") return;
        const completedAtMs = Date.now();
        setIsStreaming(false);
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === assistantMsgId
              ? {
                  ...msg,
                  content: `[Lỗi kết nối]: ${(err as Error).message}`,
                  isStreaming: false,
                  progressLabel: undefined,
                  completedAtMs,
                }
              : msg,
          ),
        );
      }
    },
    [conversationId],
  );

  const stopStreaming = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      const completedAtMs = Date.now();
      setIsStreaming(false);
      setMessages((prev) =>
        prev.map((msg) =>
          msg.isStreaming
            ? {
                ...msg,
                isStreaming: false,
                progressLabel: undefined,
                completedAtMs,
              }
            : msg,
        ),
      );
      abortControllerRef.current = null;
    }
  }, []);

  const prepareConversation = useCallback((nextConversationId: string) => {
    skipHistoryConversationRef.current = nextConversationId;
    setMessages([]);
  }, []);

  return {
    messages,
    setMessages,
    isStreaming,
    startStreaming,
    stopStreaming,
    prepareConversation,
  };
}
