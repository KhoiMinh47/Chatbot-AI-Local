"use client";

/**
 * Phase 8 Messages timeline.
 *
 * Renders user questions and assistant answers using `Markdown` for formatting
 * and rendering clickable citations. Includes copy actions and rating controls
 * that invoke `apiSubmitFeedback`.
 */

import { useEffect, useState } from "react";
import { Markdown } from "../lib/markdown";
import { apiSubmitFeedback } from "../lib/api";
import type { ChatMessage } from "../lib/types";

interface MessageListProps {
  messages: ChatMessage[];
  isStreaming: boolean;
  onStop: () => void;
  onCitationClick: (citationId: string) => void;
}

export function formatWorkedDuration(durationMs: number): string {
  const totalSeconds = Math.max(0, Math.floor(durationMs / 1_000));
  const hours = Math.floor(totalSeconds / 3_600);
  const minutes = Math.floor((totalSeconds % 3_600) / 60);
  const seconds = totalSeconds % 60;

  if (hours > 0) return `${hours}h ${minutes}m ${seconds}s`;
  if (minutes > 0) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

function WorkProgress({ message }: { message: ChatMessage }) {
  const [fallbackStartedAtMs] = useState(() => Date.now());
  const [nowMs, setNowMs] = useState(() => Date.now());
  const isActive = message.isStreaming === true;

  useEffect(() => {
    if (!isActive) return undefined;
    const intervalId = window.setInterval(() => setNowMs(Date.now()), 1_000);
    return () => window.clearInterval(intervalId);
  }, [isActive]);

  const startedAtMs = message.startedAtMs ?? fallbackStartedAtMs;
  const endMs = message.completedAtMs ?? nowMs;
  const duration = formatWorkedDuration(endMs - startedAtMs);

  return (
    <div
      className={`flex w-fit max-w-full items-center gap-2 rounded-lg border px-3 py-2 text-xs font-semibold ${
        isActive
          ? "border-emerald-300/30 bg-emerald-300/10 text-emerald-200"
          : "border-[#28433b]/50 bg-[#07100e]/40 text-slate-400"
      }`}
      aria-live={isActive ? "polite" : undefined}
    >
      {isActive && (
        <span
          className="size-1.5 shrink-0 rounded-full bg-emerald-300 animate-pulse"
          aria-hidden="true"
        />
      )}
      <span>
        {isActive
          ? `${message.progressLabel ?? "Đang xử lý..."} · ${duration}`
          : `Worked ${duration}`}
      </span>
    </div>
  );
}

export function MessageList({
  messages,
  isStreaming,
  onStop,
  onCitationClick,
}: MessageListProps) {
  const [ratedMessages, setRatedMessages] = useState<Record<string, "thumbs_up" | "thumbs_down">>({});
  const [feedbackReasonId, setFeedbackReasonId] = useState<string | null>(null);
  const [feedbackReason, setFeedbackReason] = useState("");

  const handleCopy = async (id: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      alert("Đã sao chép câu trả lời vào bộ nhớ tạm.");
    } catch {
      /* clipboard write failure */
    }
  };

  const handleRate = async (messageId: string, rating: "thumbs_up" | "thumbs_down") => {
    try {
      await apiSubmitFeedback(messageId, rating);
      setRatedMessages((prev) => ({ ...prev, [messageId]: rating }));
      if (rating === "thumbs_down") {
        setFeedbackReasonId(messageId);
        setFeedbackReason("");
      }
    } catch {
      /* fail silently or print log */
    }
  };

  const submitDetailedFeedback = async (messageId: string) => {
    if (!feedbackReason.trim()) {
      setFeedbackReasonId(null);
      return;
    }
    try {
      await apiSubmitFeedback(messageId, "thumbs_down", feedbackReason.trim());
    } finally {
      setFeedbackReasonId(null);
    }
  };

  return (
    <div className="flex-1 overflow-y-auto px-4 py-8 space-y-6">
      {messages.length === 0 ? (
        <div className="flex h-full flex-col items-center justify-center text-center">
          <span className="text-4xl mb-4" aria-hidden="true">👋</span>
          <h2 className="text-xl font-bold text-white mb-2">
            Không gian tri thức cục bộ NTC
          </h2>
          <p className="max-w-md text-sm leading-6 text-slate-400 text-balance">
            Đặt câu hỏi dựa trên các tài liệu nội bộ được tải lên. Dữ liệu của
            bạn luôn được lưu giữ an toàn bên trong hạ tầng tổ chức.
          </p>
        </div>
      ) : (
        <div className="max-w-3xl mx-auto space-y-6">
          {messages.map((msg) => {
            const isUser = msg.role === "user";
            const currentRating = ratedMessages[msg.id];

            return (
              <div
                key={msg.id}
                className={`flex gap-4 p-4 rounded-2xl border transition-colors ${
                  isUser
                    ? "bg-[#0d1916]/20 border-white/5 justify-end ml-12"
                    : "bg-[#0d1916]/60 border-[#28433b]/40 mr-12"
                }`}
              >
                {/* Avatar indicator */}
                {!isUser && (
                  <span
                    aria-hidden="true"
                    className="grid size-8 place-items-center rounded-lg border border-emerald-300/40 bg-emerald-300/10 text-xs font-black text-emerald-300 shrink-0"
                  >
                    AI
                  </span>
                )}

                <div className="flex-1 overflow-hidden space-y-3">
                  {!isUser && <WorkProgress message={msg} />}

                  {/* Message body */}
                  {isUser ? (
                    <p className="text-sm leading-6 text-white whitespace-pre-wrap text-right font-medium">
                      {msg.content}
                    </p>
                  ) : (
                    <div className="text-sm prose prose-invert max-w-none">
                      <Markdown
                        content={msg.content}
                        onCitationClick={(citationId) => {
                          const citation = msg.citations?.find(
                            (c) => c.citation_id === citationId
                          );
                          if (citation) onCitationClick(citationId);
                        }}
                      />
                    </div>
                  )}

                  {/* Actions footer for Assistant message */}
                  {!isUser && !msg.isStreaming && msg.content && (
                    <div className="flex items-center justify-between border-t border-[#28433b]/20 pt-2.5 mt-2">
                      <div className="flex items-center gap-4">
                        {/* Copy button */}
                        <button
                          type="button"
                          onClick={() => handleCopy(msg.id, msg.content)}
                          className="text-xs text-slate-400 hover:text-white focus:outline-none"
                          title="Sao chép nội dung câu trả lời"
                        >
                          📋 Sao chép
                        </button>
                      </div>

                      {/* Feedback rating */}
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => handleRate(msg.id, "thumbs_up")}
                          aria-label="Thích câu trả lời này"
                          className={`p-1 rounded text-sm hover:bg-white/5 transition-colors focus:outline-none ${
                            currentRating === "thumbs_up" ? "text-emerald-300" : "text-slate-400"
                          }`}
                        >
                          👍
                        </button>
                        <button
                          type="button"
                          onClick={() => handleRate(msg.id, "thumbs_down")}
                          aria-label="Không thích câu trả lời này"
                          className={`p-1 rounded text-sm hover:bg-white/5 transition-colors focus:outline-none ${
                            currentRating === "thumbs_down" ? "text-rose-400" : "text-slate-400"
                          }`}
                        >
                          👎
                        </button>
                      </div>
                    </div>
                  )}

                  {/* Rating detailed feedback input */}
                  {feedbackReasonId === msg.id && (
                    <div className="mt-3 rounded-lg border border-[#28433b] bg-[#07100e] p-3 space-y-2">
                      <label htmlFor={`feedback-input-${msg.id}`} className="block text-[11px] font-bold text-slate-400 uppercase">
                        Tại sao câu trả lời này chưa tốt?
                      </label>
                      <textarea
                        id={`feedback-input-${msg.id}`}
                        rows={2}
                        value={feedbackReason}
                        onChange={(e) => setFeedbackReason(e.target.value)}
                        placeholder="Hãy góp ý lý do (ví dụ: thông tin sai, thiếu nguồn,...)"
                        className="w-full text-xs text-white bg-transparent border-0 focus:outline-none focus:ring-0 placeholder-slate-600 leading-normal"
                      />
                      <div className="flex justify-end gap-2 pt-1 border-t border-[#28433b]/40">
                        <button
                          type="button"
                          onClick={() => setFeedbackReasonId(null)}
                          className="text-[10px] font-bold text-slate-400 hover:text-white px-2 py-1"
                        >
                          Bỏ qua
                        </button>
                        <button
                          type="button"
                          onClick={() => submitDetailedFeedback(msg.id)}
                          className="text-[10px] font-bold text-emerald-950 bg-emerald-200 hover:bg-emerald-100 px-2 py-1 rounded"
                        >
                          Gửi góp ý
                        </button>
                      </div>
                    </div>
                  )}
                </div>

                {isUser && (
                  <span
                    aria-hidden="true"
                    className="grid size-8 place-items-center rounded-lg border border-slate-700 bg-slate-800 text-xs font-black text-slate-300 shrink-0"
                  >
                    U
                  </span>
                )}
              </div>
            );
          })}

          {/* Stop streaming floating button */}
          {isStreaming && (
            <div className="flex justify-center pt-2">
              <button
                type="button"
                onClick={onStop}
                className="flex items-center gap-2 rounded-full border border-rose-500/20 bg-rose-500/5 px-4 py-2 text-xs font-bold text-rose-300 hover:bg-rose-500/10 transition-colors shadow-lg"
              >
                <span className="size-2 rounded bg-rose-400" aria-hidden="true" />
                Dừng tạo câu trả lời
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
