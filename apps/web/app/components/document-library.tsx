"use client";

/**
 * Document Library component - displays uploaded documents with delete actions
 */

import { useState, useEffect } from "react";
import { apiListDocuments, apiDeleteDocument } from "../lib/api";
import type { DocumentView } from "../lib/types";

export function DocumentLibrary() {
  const [documents, setDocuments] = useState<DocumentView[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const loadDocuments = async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await apiListDocuments(1, 50);
      setDocuments(response.documents);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không thể tải danh sách tài liệu");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let active = true;
    void apiListDocuments(1, 50)
      .then((response) => {
        if (active) setDocuments(response.documents);
      })
      .catch((err: unknown) => {
        if (active) {
          setError(err instanceof Error ? err.message : "Không thể tải danh sách tài liệu");
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const handleDelete = async (documentId: string, sourceName: string) => {
    if (!confirm(`Xóa tài liệu "${sourceName}"?`)) return;

    try {
      setDeletingId(documentId);
      await apiDeleteDocument(documentId);
      setDocuments((prev) => prev.filter((doc) => doc.id !== documentId));
    } catch (err) {
      alert(err instanceof Error ? err.message : "Không thể xóa tài liệu");
    } finally {
      setDeletingId(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center p-8 text-sm text-slate-400">
        Đang tải...
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4">
        <div className="text-sm text-rose-400 mb-3">{error}</div>
        <button
          onClick={() => void loadDocuments()}
          className="text-xs px-3 py-1.5 bg-[#28433b]/40 hover:bg-[#28433b]/60 rounded-lg transition-colors"
        >
          Thử lại
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-[#28433b]/60 shrink-0">
        <h2 className="text-sm font-bold text-white">Thư Mục File</h2>
        <button
          onClick={() => void loadDocuments()}
          className="text-xs px-2.5 py-1 bg-[#28433b]/40 hover:bg-[#28433b]/60 rounded transition-colors"
          title="Làm mới"
        >
          ↻
        </button>
      </div>

      {/* Document List */}
      <div className="flex-1 overflow-y-auto">
        {documents.length === 0 ? (
          <div className="flex items-center justify-center p-8 text-sm text-slate-500">
            Chưa có tài liệu nào
          </div>
        ) : (
          <div className="divide-y divide-[#28433b]/30">
            {documents.map((doc) => (
              <div
                key={doc.id}
                className="p-4 hover:bg-[#0d1916]/40 transition-colors group"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-white truncate mb-1">
                      📄 {doc.source_name}
                    </div>
                    <div className="text-xs text-slate-500">
                      {new Date(doc.created_at).toLocaleString("vi-VN")}
                    </div>
                    <div className="text-xs text-slate-400 mt-1">
                      {(doc.size_bytes / 1024).toFixed(1)} KB • {doc.state}
                    </div>
                  </div>
                  <button
                    onClick={() => void handleDelete(doc.id, doc.source_name)}
                    disabled={deletingId === doc.id}
                    className="shrink-0 text-xs px-2.5 py-1 text-rose-400 hover:bg-rose-500/10 rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    title="Xóa"
                  >
                    {deletingId === doc.id ? "..." : "Xóa"}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Footer stats */}
      {documents.length > 0 && (
        <div className="p-3 border-t border-[#28433b]/60 shrink-0">
          <div className="text-xs text-slate-500">
            Tổng: {documents.length} tài liệu
          </div>
        </div>
      )}
    </div>
  );
}
