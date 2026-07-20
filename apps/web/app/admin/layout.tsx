"use client";

/**
 * Phase 9 Admin layout container shell.
 *
 * Enforces admin authorization gates, shows loading spinner during mount checks,
 * renders a 403 Forbidden view if unprivileged, and provides a sidebar navigation
 * for administrative subsections.
 */

import { useEffect } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { useAuth } from "../lib/auth-context";

export default function AdminLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const router = useRouter();
  const pathname = usePathname();
  const { user, isLoading, isAuthenticated } = useAuth();

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.replace("/login");
    }
  }, [isLoading, isAuthenticated, router]);

  if (isLoading) {
    return (
      <div className="grid min-h-screen place-items-center bg-[#07100e] text-[#f4f7f5]">
        <div className="flex flex-col items-center gap-4">
          <span
            aria-hidden="true"
            className="size-10 animate-spin rounded-full border-2 border-emerald-300 border-t-transparent"
          />
          <p className="text-sm font-semibold text-slate-400">
            Đang xác minh quyền quản trị...
          </p>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) return null;

  // Authorization Check: Must be admin role
  if (user?.role !== "admin") {
    return (
      <div className="grid min-h-screen place-items-center bg-[#07100e] px-6 text-center text-[#f4f7f5]">
        <main className="max-w-md rounded-2xl border border-rose-500/20 bg-rose-500/5 p-8 shadow-xl">
          <span
            className="mx-auto mb-6 flex size-12 items-center justify-center rounded-full bg-rose-500/10 text-xl font-bold text-rose-400"
            aria-hidden="true"
          >
            !
          </span>
          <h1 className="text-2xl font-bold tracking-tight text-white">
            Truy cập bị từ chối
          </h1>
          <p className="mt-4 text-sm leading-6 text-slate-300">
            Tài khoản của bạn (<strong className="text-white">{user?.email}</strong>)
            không có quyền quản trị hệ thống. Vui lòng quay lại khu vực làm việc thông thường.
          </p>
          <div className="mt-8 border-t border-white/10 pt-6">
            <Link
              href="/chat"
              className="inline-flex min-h-11 items-center justify-center rounded-full bg-emerald-200 px-6 font-bold text-emerald-950 hover:bg-emerald-100 transition-colors"
            >
              Quay lại Chatbot
            </Link>
          </div>
        </main>
      </div>
    );
  }

  const menuItems = [
    { name: "Tổng quan & Health", path: "/admin", icon: "📊" },
    { name: "Thành viên", path: "/admin/users", icon: "👥" },
    { name: "Quản lý tài liệu", path: "/admin/documents", icon: "📁" },
    { name: "Lịch sử Audit logs", path: "/admin/audit-logs", icon: "📜" },
  ];

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[#07100e] text-[#f4f7f5]">
      {/* Admin Sidebar */}
      <aside className="w-64 border-r border-[#28433b] bg-[#07100e] flex flex-col shrink-0">
        <div className="flex h-16 items-center justify-between border-b border-[#28433b] px-4">
          <div className="flex items-center gap-2">
            <span className="grid size-8 place-items-center rounded-lg border border-amber-300/40 bg-amber-300/10 text-xs font-black text-amber-200">
              A
            </span>
            <span className="font-bold text-sm tracking-tight text-white">
              Admin Workspace
            </span>
          </div>
        </div>

        {/* Navigation list */}
        <nav className="flex-1 overflow-y-auto p-3 space-y-1.5" aria-label="Menu quản lý">
          {menuItems.map((item) => {
            const isActive = pathname === item.path;
            return (
              <Link
                key={item.path}
                href={item.path}
                className={`flex items-center gap-3 rounded-xl px-4 py-2.5 text-sm font-semibold transition-colors ${
                  isActive
                    ? "bg-emerald-300/10 text-emerald-300 border border-emerald-300/25"
                    : "text-slate-400 hover:bg-white/5 hover:text-white"
                }`}
              >
                <span>{item.icon}</span>
                <span>{item.name}</span>
              </Link>
            );
          })}
        </nav>

        {/* Return to Chat footer button */}
        <div className="p-4 border-t border-[#28433b] bg-[#0d1916]">
          <Link
            href="/chat"
            className="flex min-h-10 w-full items-center justify-center rounded-xl bg-emerald-200 px-4 text-xs font-bold text-emerald-950 hover:bg-emerald-100 transition-colors"
          >
            ← Quay lại Chatbot
          </Link>
        </div>
      </aside>

      {/* Main admin panels content view */}
      <div className="flex-1 flex flex-col h-full overflow-hidden">
        {children}
      </div>
    </div>
  );
}
