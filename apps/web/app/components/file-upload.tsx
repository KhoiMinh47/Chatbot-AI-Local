"use client";

/**
 * Phase 8 Document upload and ingestion tracking widget.
 *
 * Implements Drag-and-Drop file picker, file size validation, calls upload API,
 * and polls the background ingestion parser job status over WebSocket-like long polling.
 */

import { useState, useRef, type DragEvent, type ChangeEvent } from "react";
import { apiUploadDocument, apiWaitForJob } from "../lib/api";

interface FileUploadProps {
  onUploadSuccess: (docId: string, docName: string) => void;
  disabled?: boolean | undefined;
  onBusyChange?: (busy: boolean) => void;
}

interface UploadingFile {
  name: string;
  progress: number;
  status: string;
  error?: string;
  warning?: string;
}

export function FileUpload({ onUploadSuccess, disabled, onBusyChange }: FileUploadProps) {
  const [uploading, setUploading] = useState<UploadingFile | null>(null);
  const [isDragActive, setIsDragActive] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const processFile = async (file: File) => {
    onBusyChange?.(true);
    // Validate file extension
    const allowedExtensions = [".pdf", ".docx", ".pptx", ".csv", ".txt", ".md"];
    const fileExtension = file.name
      .slice(file.name.lastIndexOf("."))
      .toLowerCase();

    if (!allowedExtensions.includes(fileExtension)) {
      setUploading({
        name: file.name,
        progress: 0,
        status: "Lỗi định dạng",
        error:
          "Định dạng không hỗ trợ. Chỉ nhận PDF, DOCX, PPTX, CSV, TXT, MD.",
      });
      return;
    }

    // Validate size (e.g. max 500MB)
    const maxSize = 500 * 1024 * 1024;
    if (file.size > maxSize) {
      setUploading({
        name: file.name,
        progress: 0,
        status: "Lỗi dung lượng",
        error: "Kích thước tệp vượt quá giới hạn 500MB.",
      });
      return;
    }

    setUploading({
      name: file.name,
      progress: 10,
      status: "Đang tải lên máy chủ...",
    });

    try {
      const receipt = await apiUploadDocument(file);
      setUploading({
        name: file.name,
        progress: 40,
        status: "Đang trích xuất nội dung (ingestion)...",
      });

      const finalStatus = await apiWaitForJob(receipt.job_id, (status) => {
        if (status.state !== "failed" && status.state !== "completed") {
          setUploading({
            name: file.name,
            progress: 40 + Math.round((status.progress_percent || 0) * 0.5),
            status: status.progress_message || "Đang trích xuất nội dung...",
          });
        }
      });
      if (finalStatus.state === "failed") {
        setUploading({
          name: file.name,
          progress: 100,
          status: "Lỗi phân tích",
          error: finalStatus.error_message || "Không thể phân tích tài liệu.",
        });
        onBusyChange?.(false);
        return;
      }
      onUploadSuccess(receipt.document_id, file.name);
      if (finalStatus.parse_quality_status === "needs_review") {
        const coverage =
          finalStatus.parse_coverage_ratio == null
            ? "không xác định"
            : `${Math.round(finalStatus.parse_coverage_ratio * 100)}%`;
        setUploading({
          name: file.name,
          progress: 100,
          status: "Đã tải lên – cần kiểm tra",
          warning: `Độ phủ parser: ${coverage}. ${(
            finalStatus.parse_warnings ?? []
          ).join(", ")}`,
        });
      } else {
        setUploading(null);
      }
      onBusyChange?.(false);
    } catch (err) {
      setUploading({
        name: file.name,
        progress: 100,
        status: "Lỗi tải lên",
        error:
          err instanceof Error ? err.message : "Đã xảy ra lỗi khi tải lên.",
      });
      onBusyChange?.(false);
    }
  };

  const handleDrag = (e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setIsDragActive(true);
    } else if (e.type === "dragleave") {
      setIsDragActive(false);
    }
  };

  const handleDrop = (e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragActive(false);

    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      void processFile(e.dataTransfer.files[0]);
    }
  };

  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    e.preventDefault();
    if (e.target.files && e.target.files[0]) {
      void processFile(e.target.files[0]);
    }
  };

  return (
    <div className="w-full">
      {uploading ? (
        <div className="rounded-xl border border-[#28433b] bg-[#0d1916]/80 p-4">
          <div className="mb-2 flex items-center justify-between text-xs font-semibold">
            <span
              className="max-w-[200px] truncate text-white"
              title={uploading.name}
            >
              {uploading.name}
            </span>
            <span
              className={
                uploading.error
                  ? "text-rose-400"
                  : uploading.warning
                    ? "text-amber-300"
                    : "text-emerald-300"
              }
            >
              {uploading.status}
            </span>
          </div>

          <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/5">
            <div
              className={`h-full rounded-full transition-all duration-300 ${
                uploading.error
                  ? "bg-rose-500"
                  : uploading.warning
                    ? "bg-amber-400"
                    : "bg-emerald-300"
              }`}
              style={{ width: `${uploading.progress}%` }}
            />
          </div>

          {uploading.error && (
            <div className="mt-2.5 flex items-center justify-between gap-4">
              <p className="flex-1 text-[11px] leading-normal text-rose-300">
                {uploading.error}
              </p>
              <button
                type="button"
                onClick={() => setUploading(null)}
                className="shrink-0 text-[11px] font-bold text-slate-400 hover:text-white focus:outline-none"
              >
                Đóng
              </button>
            </div>
          )}
          {uploading.warning && (
            <div className="mt-2.5 flex items-center justify-between gap-4">
              <p className="flex-1 text-[11px] leading-normal text-amber-200">
                {uploading.warning}
              </p>
              <button
                type="button"
                onClick={() => setUploading(null)}
                className="shrink-0 text-[11px] font-bold text-slate-400 hover:text-white focus:outline-none"
              >
                Đóng
              </button>
            </div>
          )}
        </div>
      ) : (
        <div
          onDragEnter={handleDrag}
          onDragOver={handleDrag}
          onDragLeave={handleDrag}
          onDrop={handleDrop}
          onClick={() => !disabled && fileInputRef.current?.click()}
          className={`flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed p-4 text-center transition-colors ${
            disabled ? "cursor-not-allowed border-[#28433b]/40 opacity-40" : ""
          } ${
            isDragActive
              ? "border-emerald-300 bg-emerald-300/5 text-emerald-100"
              : "border-[#28433b]/80 bg-transparent text-slate-400 hover:border-emerald-300/40 hover:text-slate-300"
          }`}
        >
          <input
            ref={fileInputRef}
            type="file"
            onChange={handleFileChange}
            disabled={disabled}
            className="hidden"
            accept=".pdf,.docx,.pptx,.csv,.txt,.md"
          />
          <span className="mb-1.5 text-xl" aria-hidden="true">
            📁
          </span>
          <p className="mb-1 text-xs font-bold">
            Kéo thả tài liệu hoặc nhấp để chọn tệp
          </p>
          <p className="text-[10px] text-slate-500">
            PDF, DOCX, PPTX, CSV, TXT, MD (tối đa 500MB)
          </p>
        </div>
      )}
    </div>
  );
}
