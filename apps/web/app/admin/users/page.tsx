"use client";
/* eslint-disable react-hooks/set-state-in-effect */

/**
 * Phase 9 Admin User Management panel.
 *
 * Lists all registered users inside the tenant space, displays email verification status,
 * and allows promoting/demoting accounts between User/Admin roles dynamically.
 */

import { useEffect, useState, useTransition } from "react";
import { apiAdminListUsers, apiAdminPatchUser } from "../../lib/api";
import type { AdminUser } from "../../lib/types";

export default function AdminUsersManagement() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [search, setSearch] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [, startTransition] = useTransition();

  const loadUsers = async (targetPage: number) => {
    try {
      const list = await apiAdminListUsers(targetPage);
      setUsers(list);
    } catch {
      /* handle err */
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void loadUsers(page);
  }, [page]);

  const handleRoleChange = (userId: string, newRole: "user" | "admin") => {
    if (!confirm(`Bạn có chắc chắn muốn thay đổi quyền hạn của tài khoản này thành ${newRole}?`)) {
      return;
    }
    startTransition(async () => {
      try {
        const updated = await apiAdminPatchUser(userId, { role: newRole });
        setUsers((prev) =>
          prev.map((u) => (u.id === userId ? { ...u, role: updated.role } : u))
        );
      } catch (err) {
        alert(err instanceof Error ? err.message : "Không thể thay đổi vai trò người dùng.");
      }
    });
  };

  const filteredUsers = users.filter(
    (u) =>
      u.email.toLowerCase().includes(search.toLowerCase()) ||
      u.display_name.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <main className="flex-1 overflow-y-auto p-6 md:p-8 space-y-6" id="main-content">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">Quản lý thành viên</h1>
          <p className="text-sm text-slate-400 mt-1">
            Danh sách người dùng đăng ký trong tổ chức, phân quyền hoạt động và kích hoạt tài khoản.
          </p>
        </div>

        {/* Search input */}
        <input
          type="text"
          placeholder="Tìm kiếm theo email, tên..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="min-h-10 rounded-xl border border-[#28433b]/60 bg-[#0d1916]/40 px-4 text-sm text-white placeholder-slate-500 focus:border-emerald-300 focus:outline-none w-full sm:max-w-xs"
        />
      </div>

      {isLoading ? (
        <div className="flex min-h-[300px] items-center justify-center text-slate-400 text-sm font-semibold">
          <span aria-hidden="true" className="size-5 animate-spin rounded-full border-2 border-emerald-300 border-t-transparent mr-2" />
          Đang tải danh sách thành viên...
        </div>
      ) : (
        <div className="space-y-4">
          <div className="overflow-x-auto rounded-xl border border-[#28433b]/60 bg-[#0d1916]/20">
            <table className="w-full border-collapse text-left text-sm text-slate-300">
              <thead className="bg-[#0d1916] text-white">
                <tr>
                  <th className="px-5 py-3 font-semibold border-b border-[#28433b]/60">Họ tên</th>
                  <th className="px-5 py-3 font-semibold border-b border-[#28433b]/60">Email</th>
                  <th className="px-5 py-3 font-semibold border-b border-[#28433b]/60">Xác thực Email</th>
                  <th className="px-5 py-3 font-semibold border-b border-[#28433b]/60">Ngày đăng ký</th>
                  <th className="px-5 py-3 font-semibold border-b border-[#28433b]/60">Quyền hạn (Role)</th>
                </tr>
              </thead>
              <tbody>
                {filteredUsers.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-5 py-8 text-center text-slate-500 italic">
                      Không tìm thấy thành viên nào khớp với từ khóa tìm kiếm.
                    </td>
                  </tr>
                ) : (
                  filteredUsers.map((u, idx) => (
                    <tr key={u.id} className={idx % 2 === 0 ? "bg-white/5" : "bg-transparent"}>
                      <td className="px-5 py-3.5 font-semibold text-white">{u.display_name}</td>
                      <td className="px-5 py-3.5 break-all">{u.email}</td>
                      <td className="px-5 py-3.5">
                        {u.is_verified ? (
                          <span className="text-[11px] font-bold text-emerald-300 bg-emerald-300/10 border border-emerald-300/20 px-2 py-0.5 rounded">Xác minh</span>
                        ) : (
                          <span className="text-[11px] font-bold text-slate-400 bg-slate-400/10 border border-slate-400/20 px-2 py-0.5 rounded">Chờ kích hoạt</span>
                        )}
                      </td>
                      <td className="px-5 py-3.5 text-slate-400 text-xs">
                        {new Date(u.created_at).toLocaleDateString("vi-VN", {
                          year: "numeric",
                          month: "long",
                          day: "numeric",
                        })}
                      </td>
                      <td className="px-5 py-3.5">
                        <select
                          value={u.role}
                          onChange={(e) => handleRoleChange(u.id, e.target.value as "user" | "admin")}
                          className="min-h-8 rounded-lg border border-[#28433b]/60 bg-[#0d1916] px-2 py-1 text-xs text-white focus:outline-none"
                        >
                          <option value="user">User</option>
                          <option value="admin">Admin</option>
                        </select>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination controls */}
          <div className="flex justify-end gap-2.5">
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
              disabled={users.length < 50}
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
