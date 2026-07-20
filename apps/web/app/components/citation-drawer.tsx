"use client";

/**
 * Phase 8 citation drawer preview widget.
 *
 * Appears as a sliding panel displaying matching metadata (page provenance, score,
 * document source file name) and snippet preview content for verification.
 */

import type { Citation } from "../lib/types";

interface CitationDrawerProps {
  citation: Citation | null;
  onClose: () => void;
}

export function CitationDrawer({ citation, onClose }: CitationDrawerProps) {
  if (!citation) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/60 backdrop-blur-sm transition-opacity">
      {/* Click outside to close */}
      <div className="flex-1" onClick={onClose} aria-hidden="true" />

      {/* Drawer panel */}
      <aside
        className="animate-slide-in flex h-full w-full max-w-md flex-col border-l border-[#28433b] bg-[#07100e] p-6 text-[#f4f7f5] shadow-2xl"
        role="dialog"
        aria-labelledby="drawer-title"
      >
        <div className="mb-6 flex items-center justify-between border-b border-[#28433b] pb-4">
          <h2
            id="drawer-title"
            className="flex items-center gap-2 text-lg font-bold text-white"
          >
            <span className="rounded border border-emerald-300/25 bg-emerald-300/10 px-2 py-0.5 text-xs text-emerald-300">
              {citation.citation_id}
            </span>
            Nguồn trích dẫn
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Đóng panel trích dẫn"
            className="rounded p-1 text-slate-400 transition-colors hover:bg-white/5 hover:text-white focus:outline-none"
          >
            ✕
          </button>
        </div>

        <div className="flex-1 space-y-6 overflow-y-auto pr-2">
          {/* Document metadata */}
          <div className="space-y-4">
            <div>
              <p className="text-[10px] font-bold tracking-wider text-slate-400 uppercase">
                Tên tài liệu
              </p>
              <p className="mt-1 text-sm font-semibold break-all text-white">
                {citation.source_name}
              </p>
            </div>

            <div className="grid grid-cols-2 gap-4">
              {citation.page !== null && (
                <div>
                  <p className="text-[10px] font-bold tracking-wider text-slate-400 uppercase">
                    Trang
                  </p>
                  <p className="mt-1 text-sm font-semibold text-white">
                    {citation.page}
                  </p>
                </div>
              )}
              {citation.slide !== null && (
                <div>
                  <p className="text-[10px] font-bold tracking-wider text-slate-400 uppercase">
                    Slide
                  </p>
                  <p className="mt-1 text-sm font-semibold text-white">
                    {citation.slide}
                  </p>
                </div>
              )}
              {citation.sheet !== null && (
                <div>
                  <p className="text-[10px] font-bold tracking-wider text-slate-400 uppercase">
                    Sheet
                  </p>
                  <p className="mt-1 text-sm font-semibold text-white">
                    {citation.sheet}
                  </p>
                </div>
              )}
              {citation.cell_range !== null && (
                <div>
                  <p className="text-[10px] font-bold tracking-wider text-slate-400 uppercase">
                    Ô dữ liệu
                  </p>
                  <p className="mt-1 text-sm font-semibold text-white">
                    {citation.cell_range}
                  </p>
                </div>
              )}
              {citation.line_start !== null && (
                <div>
                  <p className="text-[10px] font-bold tracking-wider text-slate-400 uppercase">
                    Dòng
                  </p>
                  <p className="mt-1 text-sm font-semibold text-white">
                    {citation.line_start}
                    {citation.line_end !== null &&
                    citation.line_end !== citation.line_start
                      ? `–${citation.line_end}`
                      : ""}
                  </p>
                </div>
              )}
              <div>
                <p className="text-[10px] font-bold tracking-wider text-slate-400 uppercase">
                  Rerank Score
                </p>
                <p className="mt-1 text-sm font-semibold text-emerald-300">
                  {(citation.score * 100).toFixed(1)}%
                </p>
              </div>
              <div>
                <p className="text-[10px] font-bold tracking-wider text-slate-400 uppercase">
                  Xác thực
                </p>
                <p className="mt-1 text-sm font-semibold text-emerald-300">
                  {citation.verified ? "Đã xác thực" : "Chưa xác thực"}
                </p>
              </div>
            </div>

            {citation.section_path.length > 0 && (
              <div>
                <p className="text-[10px] font-bold tracking-wider text-slate-400 uppercase">
                  Mục lục
                </p>
                <p className="mt-1 text-xs text-slate-300 italic">
                  {citation.section_path.join(" > ")}
                </p>
              </div>
            )}
          </div>

          <hr className="border-[#28433b]/60" />

          {/* Context content snippet */}
          <div>
            <p className="mb-3 text-[10px] font-bold tracking-wider text-slate-400 uppercase">
              Nội dung đối khớp
            </p>
            <div className="rounded-xl border border-[#28433b]/40 bg-[#0d1916] p-4 text-sm leading-6 font-normal text-slate-300">
              {citation.text}
            </div>
          </div>
        </div>
      </aside>

      <style jsx global>{`
        @keyframes slide-in {
          from {
            transform: translateX(100%);
          }
          to {
            transform: translateX(0);
          }
        }
        .animate-slide-in {
          animation: slide-in 200ms cubic-bezier(0.16, 1, 0.3, 1) forwards;
        }
      `}</style>
    </div>
  );
}
