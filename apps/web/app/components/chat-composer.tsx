"use client";

/**
 * Phase 8 Chat Composer.
 *
 * Implements message text input (auto-growing textarea), document attachments
 * control (multi-select for RAG context boundaries), ModeSwitch toggle, and handles
 * enter key mapping for submission.
 */

import { useState, type KeyboardEvent, type FormEvent } from "react";
import { ModeSwitch } from "./mode-switch";
import { FileUpload } from "./file-upload";

interface ChatComposerProps {
  onSend: (text: string, mode: "fast" | "reasoning", docIds: string[]) => void;
  disabled?: boolean | undefined;
  mode: "fast" | "reasoning";
  onModeChange: (mode: "fast" | "reasoning") => void;
}

interface AttachedDoc {
  id: string;
  name: string;
}

export function ChatComposer({ onSend, disabled, mode, onModeChange }: ChatComposerProps) {
  const [text, setText] = useState("");
  const [attachedDocs, setAttachedDocs] = useState<AttachedDoc[]>([]);
  const [showUpload, setShowUpload] = useState(false);
  const [uploadBusy, setUploadBusy] = useState(false);

  const handleSubmit = (e?: FormEvent) => {
    e?.preventDefault();
    if (!text.trim() || disabled || uploadBusy) return;

    onSend(
      text.trim(),
      mode,
      attachedDocs.map((doc) => doc.id)
    );
    setText("");
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleAddAttachedDoc = (id: string, name: string) => {
    setAttachedDocs((prev) => {
      if (prev.some((d) => d.id === id)) return prev;
      return [...prev, { id, name }];
    });
    setShowUpload(false);
  };

  const handleRemoveDoc = (id: string) => {
    setAttachedDocs((prev) => prev.filter((doc) => doc.id !== id));
  };

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3 rounded-2xl border border-[#28433b] bg-[#0d1916]/40 p-4">
      {/* File Upload Panel if active */}
      {showUpload && (
        <div className="border-b border-[#28433b]/40 pb-3 mb-2.5">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-bold text-slate-300">Đính kèm tài liệu</span>
            <button
              type="button"
              onClick={() => setShowUpload(false)}
              className="text-xs font-bold text-slate-400 hover:text-white"
            >
              Hủy
            </button>
          </div>
          <FileUpload onUploadSuccess={handleAddAttachedDoc} onBusyChange={setUploadBusy} disabled={disabled} />
        </div>
      )}

      {/* Active Attachments list */}
      {attachedDocs.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-2">
          {attachedDocs.map((doc) => (
            <span
              key={doc.id}
              className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-300/10 border border-emerald-300/20 px-2.5 py-1 text-xs font-semibold text-emerald-200"
            >
              <span className="truncate max-w-[120px]">{doc.name}</span>
              <button
                type="button"
                onClick={() => handleRemoveDoc(doc.id)}
                disabled={disabled}
                aria-label={`Xóa tài liệu đính kèm ${doc.name}`}
                className="text-slate-400 hover:text-rose-400 font-bold focus:outline-none"
              >
                ✕
              </button>
            </span>
          ))}
        </div>
      )}

      {/* Input Text Area */}
      <div className="relative">
        <textarea
          rows={2}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Nhập câu hỏi của bạn tại đây... (Enter để gửi, Shift+Enter để xuống dòng)"
          disabled={disabled || uploadBusy}
          className="w-full resize-none bg-transparent pr-12 text-sm text-white focus:outline-none placeholder-slate-500 leading-6 disabled:cursor-not-allowed disabled:opacity-60"
        />
      </div>

      {/* Controls Footer */}
      <div className="flex items-center justify-between border-t border-[#28433b]/40 pt-3">
        <div className="flex items-center gap-2">
          {/* Attach file action */}
          <button
            type="button"
            disabled={disabled || uploadBusy}
            onClick={() => setShowUpload((prev) => !prev)}
            className="flex size-9 items-center justify-center rounded-xl bg-[#0d1916] border border-[#28433b]/60 text-slate-400 hover:text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none"
            title="Đính kèm tài liệu nguồn cho câu hỏi này"
          >
            📎
          </button>

          {/* Mode switch */}
          <ModeSwitch mode={mode} onChange={onModeChange} disabled={disabled} />
        </div>

        {/* Send button */}
        <button
          type="submit"
          disabled={disabled || uploadBusy || !text.trim()}
          className="flex min-h-9 items-center justify-center rounded-xl bg-emerald-200 px-5 font-bold text-emerald-950 hover:bg-emerald-100 disabled:cursor-not-allowed disabled:opacity-50 transition-colors"
        >
          {uploadBusy ? "Đang xử lý file..." : "Gửi"}
        </button>
      </div>
    </form>
  );
}
