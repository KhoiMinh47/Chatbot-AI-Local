"use client";
/* eslint-disable react-hooks/set-state-in-effect */

/**
 * Phase 9 Administrative document management page.
 *
 * Provides a paginated overview of all uploaded knowledge documents, showing their current
 * ingestion processing states (completed, failed, etc.) and error details.
 */

import { useEffect, useState } from "react";
import { apiAdminGetDocuments } from "../../lib/api";
import type { AdminDocument } from "../../lib/types";

export default function AdminDocumentsOverview() {
  const [documents, setDocuments] = useState<AdminDocument[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [isLoading, setIsLoading] = useState(true);

  const loadDocuments = async (targetPage: number) => {
    try {
      const resp = await apiAdminGetDocuments(targetPage);
      setDocuments(resp.documents);
      setTotal(resp.total);
    } catch {
      /* handle err */
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void loadDocuments(page);
  }, [page]);

  return (
    <main className="flex-1 overflow-y-auto p-6 md:p-8 space-y-6" id="main-content">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-white">Kho tài liệu hệ thống</h1>
        <p className="text-sm text-slate-400 mt-1">
          Giám sát trạng thái xử lý trích xuất thông tin (ingestion) của tài liệu tải lên bởi người dùng.
        </p>
      </div>

      {isLoading ? (
        <div className="flex min-h-[300px] items-center justify-center text-slate-400 text-sm font-semibold">
          <span aria-hidden="true" className="size-5 animate-spin rounded-full border-2 border-emerald-300 border-t-transparent mr-2" />
          Đang tải danh sách tài liệu...
        </div>
      ) : (
        <div className="space-y-4">
          <div className="overflow-x-auto rounded-xl border border-[#28433b]/60 bg-[#0d1916]/20">
            <table className="w-full border-collapse text-left text-sm text-slate-300">
              <thead className="bg-[#0d1916] text-white">
                <tr>
                  <th className="px-5 py-3 font-semibold border-b border-[#28433b]/60">Tên tài liệu</th>
                  <th className="px-5 py-3 font-semibold border-b border-[#28433b]/60">Định dạng (Mime)</th>
                  <th className="px-5 py-3 font-semibold border-b border-[#28433b]/60">Ngày tải lên</th>
                  <th className="px-5 py-3 font-semibold border-b border-[#28433b]/60">Trạng thái (State)</th>
                </tr>
              </thead>
              <tbody>
                {documents.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="px-5 py-8 text-center text-slate-500 italic">
                      Chưa có tài liệu nào được tải lên hệ thống.
                    </td>
                  </tr>
                ) : (
                  documents.map((doc, idx) => {
                    const isFailed = doc.state === "failed";
                    const isSuccess = doc.state === "completed" || doc.state === "indexed";
                    return (
                      <tr key={doc.id} className={idx % 2 === 0 ? "bg-white/5" : "bg-transparent"}>
                        <td className="px-5 py-3.5 font-semibold text-white break-all">{doc.source_name}</td>
                        <td className="px-5 py-3.5 text-xs font-mono">{doc.mime_type}</td>
                        <td className="px-5 py-3.5 text-slate-400 text-xs">
                          {new Date(doc.created_at).toLocaleString("vi-VN", {
                            year: "numeric",
                            month: "numeric",
                            day: "numeric",
                            hour: "2-digit",
                            minute: "2-digit",
                          })}
                        </td>
                        <td className="px-5 py-3.5">
                          {isSuccess && (
                            <span className="text-[11px] font-bold text-emerald-300 bg-emerald-300/10 border border-emerald-300/20 px-2.5 py-0.5 rounded">
                              Thành công
                            </span>
                          )}
                          {isFailed && (
                            <div className="flex flex-col gap-1">
                              <span className="text-[11px] font-bold text-rose-400 bg-rose-500/10 border border-rose-500/20 px-2.5 py-0.5 rounded w-fit">
                                Lỗi trích xuất
                              </span>
                              {doc.error_code && (
                                <span className="text-[10px] text-rose-300 font-mono">
                                  Mã: {doc.error_code}
                                </span>
                              )}
                            </div>
                          )}
                          {!isSuccess && !isFailed && (
                            <span className="text-[11px] font-bold text-amber-300 bg-amber-300/10 border border-amber-300/20 px-2.5 py-0.5 rounded animate-pulse">
                              Đang xử lý ({doc.state})
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination controls */}
          <div className="flex items-center justify-between text-xs text-slate-400">
            <span>Tổng cộng: {total} tài liệu</span>
            <div className="flex gap-2">
              <button
                type="button"
                disabled={page <= 1}
                onClick={() => setPage((p) => p - 1)}
                className="min-h-9 rounded-xl border border-[#28433b]/60 bg-transparent px-4 text-xs font-bold text-slate-300 hover:text-white disabled:cursor-not-allowed disabled:opacity-40 transition-colors"
              >
                Trang trước
              </button>
              <button
                type="button"
                disabled={documents.length < 50}
                onClick={() => setPage((p) => p + 1)}
                className="min-h-9 rounded-xl border border-[#28433b]/60 bg-transparent px-4 text-xs font-bold text-slate-300 hover:text-white disabled:cursor-not-allowed disabled:opacity-40 transition-colors"
              >
                Trang sau
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
