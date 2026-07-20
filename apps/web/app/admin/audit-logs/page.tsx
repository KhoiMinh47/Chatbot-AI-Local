"use client";
/* eslint-disable react-hooks/set-state-in-effect */

/**
 * Phase 9 System Audit Trail page.
 *
 * Displays security and admin events (such as user role adjustments, login trials, password updates)
 * and displays actors, targets, and correlation timestamps in a clean logs panel.
 */

import { useEffect, useState } from "react";
import { apiAdminGetAuditLogs } from "../../lib/api";
import type { AuditLog } from "../../lib/types";

export default function AdminAuditLogsTimeline() {
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [page, setPage] = useState(1);
  const [isLoading, setIsLoading] = useState(true);

  const loadLogs = async (targetPage: number) => {
    try {
      const list = await apiAdminGetAuditLogs(targetPage);
      setLogs(list);
    } catch {
      /* handle err */
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void loadLogs(page);
  }, [page]);

  return (
    <main className="flex-1 overflow-y-auto p-6 md:p-8 space-y-6" id="main-content">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-white">Nhật ký hệ thống (Audit logs)</h1>
        <p className="text-sm text-slate-400 mt-1">
          Lịch sử ghi vết toàn bộ hoạt động quan trọng, thay đổi quyền hạn và thao tác tài liệu của hệ thống.
        </p>
      </div>

      {isLoading ? (
        <div className="flex min-h-[300px] items-center justify-center text-slate-400 text-sm font-semibold">
          <span aria-hidden="true" className="size-5 animate-spin rounded-full border-2 border-emerald-300 border-t-transparent mr-2" />
          Đang tải nhật ký kiểm toán...
        </div>
      ) : (
        <div className="space-y-4">
          <div className="overflow-x-auto rounded-xl border border-[#28433b]/60 bg-[#0d1916]/20">
            <table className="w-full border-collapse text-left text-sm text-slate-300">
              <thead className="bg-[#0d1916] text-white">
                <tr>
                  <th className="px-5 py-3 font-semibold border-b border-[#28433b]/60">Thời gian</th>
                  <th className="px-5 py-3 font-semibold border-b border-[#28433b]/60">Thao tác (Action)</th>
                  <th className="px-5 py-3 font-semibold border-b border-[#28433b]/60">Người thực hiện (Actor)</th>
                  <th className="px-5 py-3 font-semibold border-b border-[#28433b]/60">Loại đối tượng</th>
                  <th className="px-5 py-3 font-semibold border-b border-[#28433b]/60">ID đối tượng</th>
                </tr>
              </thead>
              <tbody>
                {logs.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-5 py-8 text-center text-slate-500 italic">
                      Chưa có sự kiện hệ thống nào được ghi nhận.
                    </td>
                  </tr>
                ) : (
                  logs.map((log, idx) => (
                    <tr key={log.id} className={idx % 2 === 0 ? "bg-white/5" : "bg-transparent"}>
                      <td className="px-5 py-3.5 text-slate-400 text-xs whitespace-nowrap">
                        {new Date(log.created_at).toLocaleString("vi-VN", {
                          year: "numeric",
                          month: "numeric",
                          day: "numeric",
                          hour: "2-digit",
                          minute: "2-digit",
                          second: "2-digit",
                        })}
                      </td>
                      <td className="px-5 py-3.5 font-bold text-emerald-300 font-mono text-xs">{log.action}</td>
                      <td className="px-5 py-3.5 font-mono text-xs text-white truncate max-w-[120px]" title={log.actor_id}>
                        {log.actor_id}
                      </td>
                      <td className="px-5 py-3.5 text-slate-400 text-xs">
                        {log.target_type ? (
                          <span className="bg-slate-400/10 border border-slate-400/20 px-2 py-0.5 rounded text-slate-300">
                            {log.target_type}
                          </span>
                        ) : (
                          "-"
                        )}
                      </td>
                      <td className="px-5 py-3.5 font-mono text-xs text-slate-500 truncate max-w-[150px]" title={log.target_id || ""}>
                        {log.target_id || "-"}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination controls */}
          <div className="flex justify-end gap-2">
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
              disabled={logs.length < 100}
              onClick={() => setPage((p) => p + 1)}
              className="min-h-9 rounded-xl border border-[#28433b]/60 bg-transparent px-4 text-xs font-bold text-slate-300 hover:text-white disabled:cursor-not-allowed disabled:opacity-40 transition-colors"
            >
              Trang sau
            </button>
          </div>
        </div>
      )}
    </main>
  );
}
