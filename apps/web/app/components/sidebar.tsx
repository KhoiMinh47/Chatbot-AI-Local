"use client";

/**
 * Phase 8 Sidebar conversation panel with integrated Document Library.
 */

import { useState, useEffect, useRef, type ReactNode } from "react";
import { useAuth } from "../lib/auth-context";
import {
  apiCreateConversation,
  apiDeleteConversation,
  apiListConversations,
  apiPatchConversation,
  apiListDocuments,
  apiDeleteDocument,
  apiUploadDocument,
  apiWaitForJob,
} from "../lib/api";
import type { Conversation, DocumentView } from "../lib/types";

interface SidebarProps {
  activeId: string | null;
  onSelect: (id: string | null) => void;
  refreshToken?: number;
}

type SidebarIconName = "brand" | "compose" | "folder" | "history" | "panel";

function SidebarIcon({ name }: { name: SidebarIconName }) {
  if (name === "brand") {
    return <span className="text-xs font-black tracking-tighter">N</span>;
  }

  const paths: Record<Exclude<SidebarIconName, "brand">, ReactNode> = {
    compose: <path d="M12 20h9M16.5 3.5a2.12 2.12 0 0 1 3 3L8 18l-4 1 1-4Z" />,
    folder: <path d="M3 6.5A1.5 1.5 0 0 1 4.5 5H9l2 2h8.5A1.5 1.5 0 0 1 21 8.5v9a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5Z" />,
    history: <path d="M21 12a9 9 0 1 1-3-6.7M21 4v6h-6M12 7v5l3 2" />,
    panel: <path d="M4 5.5A1.5 1.5 0 0 1 5.5 4h13A1.5 1.5 0 0 1 20 5.5v13a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 18.5ZM9 4v16" />,
  };

  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="size-5 shrink-0"
    >
      {paths[name]}
    </svg>
  );
}

export function Sidebar({ activeId, onSelect, refreshToken = 0 }: SidebarProps) {
  const { logout, user } = useAuth();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [collapsed, setCollapsed] = useState(false);
  const [showHistory, setShowHistory] = useState(true);
  const [isCreating, setIsCreating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const editInputRef = useRef<HTMLInputElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Document library state
  const [showDocuments, setShowDocuments] = useState(true);
  const [documents, setDocuments] = useState<DocumentView[]>([]);
  const [loadingDocs, setLoadingDocs] = useState(false);
  const [uploadingFile, setUploadingFile] = useState<string | null>(null);
  const [deletingDocId, setDeletingDocId] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const list = await apiListConversations();
        if (active) setConversations(list);
      } catch {
        /* fail silently */
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, [refreshToken]);

  const loadDocuments = async () => {
    try {
      setLoadingDocs(true);
      const response = await apiListDocuments(1, 50);
      setDocuments(response.documents);
    } catch {
      /* silent fail */
    } finally {
      setLoadingDocs(false);
    }
  };

  useEffect(() => {
    if (!showDocuments) return;
    let active = true;
    void apiListDocuments(1, 50)
      .then((response) => {
        if (active) setDocuments(response.documents);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [showDocuments]);

  useEffect(() => {
    if (editingId && editInputRef.current) {
      editInputRef.current.focus();
      editInputRef.current.select();
    }
  }, [editingId]);

  const handleCreate = async () => {
    setIsCreating(true);
    try {
      const conv = await apiCreateConversation("Cuộc hội thoại mới", "fast");
      setConversations((prev) => [conv, ...prev]);
      onSelect(conv.id);
    } catch {
      /* handle err */
    } finally {
      setIsCreating(false);
    }
  };

  const handleRename = async (id: string) => {
    if (!editTitle.trim()) {
      setEditingId(null);
      return;
    }
    try {
      const updated = await apiPatchConversation(id, { title: editTitle.trim() });
      setConversations((prev) =>
        prev.map((c) => (c.id === id ? { ...c, title: updated.title } : c))
      );
    } catch {
      /* handle err */
    } finally {
      setEditingId(null);
    }
  };

  const handleDelete = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm("Bạn có chắc chắn muốn xóa cuộc hội thoại này?")) return;
    try {
      await apiDeleteConversation(id);
      setConversations((prev) => prev.filter((c) => c.id !== id));
      if (activeId === id) {
        onSelect(null);
      }
    } catch {
      /* handle err */
    }
  };

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const maxSize = 500 * 1024 * 1024;
    if (file.size > maxSize) {
      alert("File quá lớn! Giới hạn 500MB");
      return;
    }

    setUploadingFile(file.name);
    try {
      const receipt = await apiUploadDocument(file);
      const status = await apiWaitForJob(receipt.job_id);
      if (status.state === "failed") {
        throw new Error(status.error_message || "Không thể phân tích tài liệu");
      }
      await loadDocuments();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Lỗi upload file");
    } finally {
      setUploadingFile(null);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    }
  };

  const handleDeleteDocument = async (docId: string, name: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm(`Xóa "${name}"?`)) return;
    setDeletingDocId(docId);
    try {
      await apiDeleteDocument(docId);
      setDocuments((prev) => prev.filter((d) => d.id !== docId));
    } catch (err) {
      alert(err instanceof Error ? err.message : "Không thể xóa");
    } finally {
      setDeletingDocId(null);
    }
  };

  return (
    <aside
      className={`flex h-full flex-col border-r border-[#28433b] bg-[#07100e] text-[#f4f7f5] shrink-0 transition-[width] duration-200 ${
        collapsed ? "w-[72px]" : "w-80"
      }`}
    >
      <div className={`flex h-16 items-center border-b border-[#28433b] ${collapsed ? "justify-center px-2" : "justify-between px-4"}`}>
        <div className="flex items-center gap-2.5">
          <span className="grid size-8 place-items-center rounded-lg border border-emerald-300/40 bg-emerald-300/10 text-xs font-black text-emerald-200">
            <SidebarIcon name="brand" />
          </span>
          {!collapsed && (
            <span className="font-semibold text-sm tracking-tight text-white">
              NTC AI Assistant
            </span>
          )}
        </div>
        {!collapsed && (
          <button
            type="button"
            onClick={() => setCollapsed(true)}
            aria-label="Thu gọn thanh bên"
            title="Thu gọn thanh bên"
            className="grid size-9 place-items-center rounded-lg text-slate-400 hover:bg-white/5 hover:text-white"
          >
            <SidebarIcon name="panel" />
          </button>
        )}
      </div>

      <div className={`order-1 ${collapsed ? "p-3" : "p-3.5"}`}>
        <button
          type="button"
          onClick={() => {
            if (collapsed) setCollapsed(false);
            void handleCreate();
          }}
          disabled={isCreating}
          aria-label="Tạo cuộc trò chuyện mới"
          title="Cuộc trò chuyện mới"
          className={`flex min-h-11 w-full items-center justify-center gap-2 rounded-xl border border-emerald-300/25 bg-emerald-300/5 text-sm font-bold text-emerald-200 hover:bg-emerald-300/10 disabled:cursor-not-allowed disabled:opacity-50 transition-colors ${collapsed ? "px-0" : "px-4"}`}
        >
          {isCreating ? (
            <span className="inline-block size-4 animate-spin rounded-full border-2 border-emerald-200 border-t-transparent" />
          ) : (
            <SidebarIcon name="compose" />
          )}
          {!collapsed && <span>Cuộc trò chuyện mới</span>}
        </button>
      </div>

      <nav className={`order-3 flex-1 overflow-y-auto py-1 space-y-1 ${collapsed ? "px-3" : "px-2"}`} aria-label="Lịch sử trò chuyện">
        <button
          type="button"
          onClick={() => {
            if (collapsed) {
              setCollapsed(false);
              setShowHistory(true);
            } else {
              setShowHistory((value) => !value);
            }
          }}
          aria-expanded={!collapsed && showHistory}
          title="Lịch sử chat"
          className={`flex min-h-11 w-full items-center rounded-lg text-slate-400 hover:bg-white/5 hover:text-white ${collapsed ? "justify-center" : "justify-between px-3"}`}
        >
          <span className="flex items-center gap-2 text-xs font-bold uppercase tracking-wide">
            <SidebarIcon name="history" />
            {!collapsed && "Lịch sử chat"}
          </span>
          {!collapsed && <span className="text-[10px]">{showHistory ? "▲" : "▼"}</span>}
        </button>

        {!collapsed && showHistory && (conversations.length === 0 ? (
          <p className="mt-12 text-center text-xs text-slate-400 px-4">
            Chưa có hội thoại nào. Hãy bấm nút phía trên để bắt đầu hỏi đáp.
          </p>
        ) : (
          conversations.map((conv) => {
            const isActive = conv.id === activeId;
            const isEditing = conv.id === editingId;

            return (
              <div
                key={conv.id}
                onClick={() => !isEditing && onSelect(conv.id)}
                className={`group relative flex min-h-11 items-center justify-between gap-2 rounded-lg px-3 py-2 text-sm transition-colors cursor-pointer ${
                  isActive
                    ? "bg-emerald-300/10 text-emerald-100 border border-emerald-300/20"
                    : "text-slate-300 hover:bg-white/5 hover:text-white"
                }`}
              >
                <div className="flex-1 overflow-hidden pr-8">
                  {isEditing ? (
                    <input
                      ref={editInputRef}
                      type="text"
                      value={editTitle}
                      onChange={(e) => setEditTitle(e.target.value)}
                      onBlur={() => handleRename(conv.id)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") handleRename(conv.id);
                        if (e.key === "Escape") setEditingId(null);
                      }}
                      className="w-full bg-transparent text-white focus:outline-none border-b border-emerald-300/60 font-medium"
                    />
                  ) : (
                    <span className="block truncate font-medium">{conv.title}</span>
                  )}
                </div>

                {!isEditing && (
                  <div className="absolute right-2 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button
                      type="button"
                      aria-label="Đổi tên hội thoại"
                      onClick={(e) => {
                        e.stopPropagation();
                        setEditingId(conv.id);
                        setEditTitle(conv.title);
                      }}
                      className="p-1 text-slate-400 hover:text-white rounded"
                    >
                      ✎
                    </button>
                    <button
                      type="button"
                      aria-label="Xóa hội thoại"
                      onClick={(e) => handleDelete(conv.id, e)}
                      className="p-1 text-slate-400 hover:text-rose-400 rounded"
                    >
                      🗑
                    </button>
                  </div>
                )}
              </div>
            );
          })
        ))}
      </nav>

      <div className={`order-2 bg-[#0d1916] ${collapsed ? "mx-3 rounded-xl" : "border-y border-[#28433b]"}`}>
        <button
          type="button"
          onClick={() => {
            if (collapsed) {
              setCollapsed(false);
              setShowDocuments(true);
            } else {
              setShowDocuments(!showDocuments);
            }
          }}
          aria-expanded={!collapsed && showDocuments}
          title="Thư mục file"
          className={`flex min-h-11 w-full items-center hover:bg-white/5 transition-colors ${collapsed ? "justify-center rounded-xl" : "justify-between p-3"}`}
        >
          <div className="flex items-center gap-2">
            <SidebarIcon name="folder" />
            {!collapsed && <span className="text-sm font-bold text-white">Thư mục File</span>}
            {!collapsed && documents.length > 0 && (
              <span className="text-xs text-slate-400">({documents.length})</span>
            )}
          </div>
          {!collapsed && <span className={`text-slate-400 transition-transform ${showDocuments ? "rotate-180" : ""}`}>
            ▼
          </span>}
        </button>

        {!collapsed && showDocuments && (
          <div className="px-2 pb-3 space-y-2 max-h-64 overflow-y-auto">
            <div className="px-2">
              <input
                ref={fileInputRef}
                type="file"
                onChange={handleFileSelect}
                accept=".pdf,.docx,.pptx,.csv,.txt"
                className="hidden"
              />
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={!!uploadingFile}
                className="w-full px-3 py-2 text-xs font-medium rounded-lg border border-dashed border-emerald-300/30 bg-emerald-300/5 text-emerald-200 hover:bg-emerald-300/10 disabled:opacity-50 transition-colors"
              >
                {uploadingFile ? `Đang tải ${uploadingFile}...` : "⬆ Tải file lên"}
              </button>
            </div>

            {loadingDocs ? (
              <p className="px-2 py-4 text-xs text-center text-slate-400">Đang tải...</p>
            ) : documents.length === 0 ? (
              <p className="px-2 py-4 text-xs text-center text-slate-400">Chưa có file nào</p>
            ) : (
              <div className="space-y-1">
                {documents.map((doc) => (
                  <div
                    key={doc.id}
                    className="group flex items-center justify-between gap-2 px-2 py-1.5 rounded hover:bg-white/5 transition-colors"
                  >
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-medium text-white truncate">
                        📄 {doc.source_name}
                      </p>
                      <p className="text-[10px] text-slate-500">
                        {(doc.size_bytes / 1024).toFixed(1)} KB
                      </p>
                    </div>
                    <button
                      onClick={(e) => handleDeleteDocument(doc.id, doc.source_name, e)}
                      disabled={deletingDocId === doc.id}
                      className="opacity-0 group-hover:opacity-100 p-1 text-xs text-rose-400 hover:text-rose-300 disabled:opacity-50 transition-opacity"
                      title="Xóa"
                    >
                      🗑
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      <div className={`order-4 border-t border-[#28433b] bg-[#0d1916] ${collapsed ? "p-3" : "p-4"}`}>
        <div className={`flex items-center gap-3 ${collapsed ? "flex-col" : "justify-between"}`}>
          <button
            type="button"
            onClick={() => collapsed && setCollapsed(false)}
            aria-label={collapsed ? "Mở rộng thanh bên" : "Thông tin tài khoản"}
            title={collapsed ? "Mở rộng thanh bên" : user?.display_name || "Tài khoản"}
            className="grid size-9 shrink-0 place-items-center rounded-full border border-emerald-300/25 bg-emerald-300/10 text-sm font-black text-emerald-200"
          >
            {(user?.display_name || user?.email || "N").charAt(0).toUpperCase()}
          </button>
          {!collapsed && <div className="flex-1 overflow-hidden">
            <p className="truncate text-sm font-semibold text-white">
              {user?.display_name || "Thành viên NTC"}
            </p>
            <p className="truncate text-xs text-slate-400">
              {user?.email || ""}
            </p>
          </div>}
          {!collapsed && <button
            type="button"
            onClick={logout}
            className="rounded-lg border border-rose-500/25 bg-rose-500/5 px-2.5 py-1.5 text-xs font-bold text-rose-300 hover:bg-rose-500/10 transition-colors"
          >
            Đăng xuất
          </button>}
        </div>
      </div>
    </aside>
  );
}
