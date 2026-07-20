"use client";
/* eslint-disable react-hooks/set-state-in-effect */

/**
 * Phase 8 email verification target.
 *
 * Reads query parameter `token` and calls `apiVerifyEmail` to mark the account
 * as verified, displaying error, pending, and success screens.
 */

import { useEffect, useState, useTransition, Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { apiVerifyEmail } from "../lib/api";

type VerificationStatus = "pending" | "success" | "error";

function VerifyEmailContent() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token");

  const [status, setStatus] = useState<VerificationStatus>("pending");
  const [errorMsg, setErrorMsg] = useState("Đang xác thực liên kết...");
  const [, startTransition] = useTransition();

  useEffect(() => {
    if (!token) {
      setStatus("error");
      setErrorMsg("Mã xác thực không hợp lệ hoặc thiếu.");
      return;
    }

    let active = true;
    startTransition(async () => {
      try {
        await apiVerifyEmail(token);
        if (active) setStatus("success");
      } catch (err) {
        if (active) {
          setStatus("error");
          setErrorMsg(
            err instanceof Error
              ? err.message
              : "Liên kết xác thực đã hết hạn hoặc không hợp lệ."
          );
        }
      }
    });

    return () => {
      active = false;
    };
  }, [token]);

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-md flex-col justify-center px-5 py-12">
      <main
        className="rounded-2xl border border-[#28433b] bg-[#0d1916] p-8 text-center"
        id="main-content"
      >
        {status === "pending" && (
          <>
            <span
              aria-hidden="true"
              className="mx-auto mb-6 flex size-12 animate-spin items-center justify-center rounded-full border-2 border-emerald-300 border-t-transparent"
            />
            <h1 className="text-2xl font-bold tracking-tight text-white">
              Đang xác thực tài khoản
            </h1>
            <p className="mt-4 text-sm text-slate-300">
              Vui lòng giữ trình duyệt mở, chúng tôi đang liên kết thông tin xác
              thực của bạn.
            </p>
          </>
        )}

        {status === "success" && (
          <>
            <span
              aria-hidden="true"
              className="mx-auto mb-6 flex size-12 items-center justify-center rounded-full bg-emerald-500/10 text-xl font-bold text-emerald-300"
            >
              ✓
            </span>
            <h1 className="text-2xl font-bold tracking-tight text-white">
              Xác thực thành công!
            </h1>
            <p className="mt-4 text-sm text-slate-300">
              Tài khoản tổ chức của bạn đã được kích hoạt. Bây giờ bạn có thể
              đăng nhập vào không gian làm việc.
            </p>
            <div className="mt-8 border-t border-white/10 pt-6">
              <Link
                href="/login"
                className="inline-flex min-h-11 items-center justify-center rounded-full bg-emerald-200 px-6 font-bold text-emerald-950 hover:bg-emerald-100 transition-colors"
              >
                Đăng nhập ngay
              </Link>
            </div>
          </>
        )}

        {status === "error" && (
          <>
            <span
              aria-hidden="true"
              className="mx-auto mb-6 flex size-12 items-center justify-center rounded-full bg-rose-500/10 text-xl font-bold text-rose-400"
            >
              !
            </span>
            <h1 className="text-2xl font-bold tracking-tight text-white">
              Lỗi xác thực email
            </h1>
            <p className="mt-4 text-sm text-rose-300">{errorMsg}</p>
            <div className="mt-8 border-t border-white/10 pt-6 flex flex-col gap-3">
              <Link
                href="/register"
                className="inline-flex min-h-11 items-center justify-center rounded-full bg-[#0d1916] border border-[#28433b] px-6 font-semibold text-emerald-100 hover:bg-white/5 transition-colors"
              >
                Đăng ký tài khoản mới
              </Link>
              <Link
                href="/login"
                className="inline-flex min-h-11 items-center justify-center rounded-full bg-emerald-200 px-6 font-bold text-emerald-950 hover:bg-emerald-100 transition-colors"
              >
                Quay lại đăng nhập
              </Link>
            </div>
          </>
        )}
      </main>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense fallback={
      <div className="grid min-h-screen place-items-center bg-[#07100e] text-[#f4f7f5]">
        <div className="flex flex-col items-center gap-4">
          <span className="size-10 animate-spin rounded-full border-2 border-emerald-300 border-t-transparent" />
          <p className="text-sm font-semibold text-slate-400">Đang tải...</p>
        </div>
      </div>
    }>
      <VerifyEmailContent />
    </Suspense>
  );
}
