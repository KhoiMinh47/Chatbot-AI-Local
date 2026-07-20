"use client";

/**
 * Phase 9 Admin dashboard overview.
 *
 * Renders statistical cards, active system models config info, live service connection health check tables,
 * and highlighted action buttons linking to deep-dive Grafana monitoring dashboards.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiAdminGetStats, apiAdminGetConfig, apiAdminGetServices } from "../lib/api";
import type { AdminStats, AdminConfig, ServiceHealth } from "../lib/types";

export default function AdminDashboardOverview() {
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [config, setConfig] = useState<AdminConfig | null>(null);
  const [services, setServices] = useState<ServiceHealth | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let active = true;
    async function loadData() {
      try {
        const [s, c, h] = await Promise.all([
          apiAdminGetStats(),
          apiAdminGetConfig(),
          apiAdminGetServices(),
        ]);
        if (active) {
          setStats(s);
          setConfig(c);
          setServices(h);
        }
      } catch {
        /* fail silently */
      } finally {
        if (active) setIsLoading(false);
      }
    }
    void loadData();
    return () => {
      active = false;
    };
  }, []);

  if (isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center bg-[#07100e] text-slate-400 text-sm font-semibold">
        <span aria-hidden="true" className="size-6 animate-spin rounded-full border-2 border-emerald-300 border-t-transparent mr-3" />
        Đang tải thông tin hệ thống...
      </div>
    );
  }

  return (
    <main className="flex-1 overflow-y-auto p-6 md:p-8 space-y-8" id="main-content">
      {/* Header title */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-white">Tổng quan hệ thống</h1>
        <p className="text-sm text-slate-400 mt-1">
          Giám sát trạng thái hoạt động, thông số cấu hình và tài nguyên của RAG Chatbot.
        </p>
      </div>

      {/* Stats Quick Cards */}
      <section className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3" aria-labelledby="stats-heading">
        <h2 id="stats-heading" className="sr-only">Thống kê nhanh</h2>
        <div className="rounded-xl border border-[#28433b]/40 bg-[#0d1916]/40 p-5">
          <p className="text-xs font-bold uppercase tracking-wider text-slate-400">Thành viên đăng ký</p>
          <p className="mt-2 text-3xl font-black text-white">{stats?.users_count ?? 0}</p>
        </div>
        <div className="rounded-xl border border-[#28433b]/40 bg-[#0d1916]/40 p-5">
          <p className="text-xs font-bold uppercase tracking-wider text-slate-400">Tài liệu đã tải lên</p>
          <p className="mt-2 text-3xl font-black text-white">{stats?.documents_count ?? 0}</p>
        </div>
        <div className="rounded-xl border border-emerald-500/25 bg-emerald-500/5 p-5 flex flex-col justify-between">
          <div>
            <p className="text-xs font-bold uppercase tracking-wider text-emerald-300">Biểu đồ giám sát GPU</p>
            <p className="mt-2 text-xs text-slate-300">Theo dõi chi tiết hiệu suất GPU, nhiệt độ, điện năng sử dụng qua DCGM.</p>
          </div>
          <Link
            href="/grafana/d/ntc-gpu-overview/ntc-gpu-overview?orgId=1&refresh=5s"
            target="_blank"
            className="mt-4 inline-flex min-h-9 w-fit items-center justify-center rounded-xl bg-emerald-200 px-4 text-xs font-bold text-emerald-950 hover:bg-emerald-100 transition-colors"
          >
            Mở Grafana Dashboard ↗
          </Link>
        </div>
      </section>

      {/* Services Health */}
      <section className="space-y-4">
        <h2 className="text-lg font-bold text-white flex items-center gap-2">
          <span>Trạng thái kết nối (Service Health)</span>
          <span className={`inline-block size-2.5 rounded-full ${services?.ready ? "bg-emerald-400" : "bg-rose-500 animate-pulse"}`} />
        </h2>
        <div className="overflow-x-auto rounded-xl border border-[#28433b]/60 bg-[#0d1916]/20">
          <table className="w-full border-collapse text-left text-sm text-slate-300">
            <thead className="bg-[#0d1916] text-white">
              <tr>
                <th className="px-5 py-3 font-semibold border-b border-[#28433b]/60">Dịch vụ</th>
                <th className="px-5 py-3 font-semibold border-b border-[#28433b]/60">Bắt buộc hoạt động</th>
                <th className="px-5 py-3 font-semibold border-b border-[#28433b]/60">Trạng thái</th>
              </tr>
            </thead>
            <tbody>
              {services?.dependencies.map((dep, idx) => {
                const isOk = dep.status === "ok";
                return (
                  <tr key={dep.name} className={idx % 2 === 0 ? "bg-white/5" : "bg-transparent"}>
                    <td className="px-5 py-3.5 font-semibold text-white">{dep.name}</td>
                    <td className="px-5 py-3.5">
                      {dep.required_for_readiness ? (
                        <span className="text-xs font-semibold text-amber-300 bg-amber-300/10 border border-amber-300/20 px-2 py-0.5 rounded">Bắt buộc</span>
                      ) : (
                        <span className="text-xs text-slate-500">Tùy chọn</span>
                      )}
                    </td>
                    <td className="px-5 py-3.5">
                      <span className={`inline-flex items-center gap-1.5 font-bold ${isOk ? "text-emerald-300" : "text-rose-400"}`}>
                        <span className={`size-2 rounded-full ${isOk ? "bg-emerald-400" : "bg-rose-500"}`} />
                        {isOk ? "Hoạt động" : "Mất kết nối"}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      {/* Model & System Config */}
      <section className="space-y-4">
        <h2 className="text-lg font-bold text-white">Cấu hình Active Model & Prompt</h2>
        <div className="grid gap-5 md:grid-cols-2">
          {/* Models */}
          <div className="rounded-xl border border-[#28433b]/40 bg-[#0d1916]/40 p-5 space-y-4">
            <h3 className="text-sm font-bold text-white border-b border-[#28433b]/40 pb-2">Active NIM Models</h3>
            <div className="space-y-3.5 text-sm">
              <div>
                <p className="text-[10px] font-bold text-slate-400 uppercase">LLM Generation Model</p>
                <p className="text-white font-semibold mt-0.5">{config?.llm_model || "Không sử dụng"}</p>
                {config?.llm_model_version && <p className="text-xs text-slate-500">Phiên bản: {config.llm_model_version}</p>}
              </div>
              <div>
                <p className="text-[10px] font-bold text-slate-400 uppercase">Embedding Vector Model</p>
                <p className="text-white font-semibold mt-0.5">{config?.embed_model || "Không sử dụng"}</p>
                {config?.embed_model_version && <p className="text-xs text-slate-500">Phiên bản: {config.embed_model_version}</p>}
              </div>
              {config?.rerank_model && (
                <div>
                  <p className="text-[10px] font-bold text-slate-400 uppercase">Reranking Model</p>
                  <p className="text-white font-semibold mt-0.5">{config.rerank_model}</p>
                  <p className="text-xs text-slate-500">Phiên bản: {config.rerank_model_version}</p>
                </div>
              )}
            </div>
          </div>

          {/* Prompts info */}
          <div className="rounded-xl border border-[#28433b]/40 bg-[#0d1916]/40 p-5 space-y-4">
            <h3 className="text-sm font-bold text-white border-b border-[#28433b]/40 pb-2">Prompt Fingerprints</h3>
            <div className="space-y-3.5 text-sm">
              <div>
                <p className="text-[10px] font-bold text-slate-400 uppercase">Prompt Version ID</p>
                <p className="text-white font-mono font-semibold mt-0.5">{config?.prompt_version || "-"}</p>
              </div>
              <div>
                <p className="text-[10px] font-bold text-slate-400 uppercase">Prompt Content SHA-256</p>
                <p className="text-emerald-300 font-mono text-xs break-all mt-1 bg-[#07100e] p-2 rounded border border-[#28433b]/30">
                  {config?.prompt_sha256 || "-"}
                </p>
              </div>
              <div>
                <p className="text-[10px] font-bold text-slate-400 uppercase">LangGraph Workflow Version</p>
                <p className="text-white font-mono font-semibold mt-0.5">{config?.graph_version || "-"}</p>
              </div>
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}
