"use client";

/**
 * Phase 8 reset password flow.
 *
 * Verifies the `token` parameter from URL and updates the password using
 * `apiResetPassword`.
 */

import { useState, type FormEvent, Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { apiResetPassword } from "../lib/api";
import { ApiError } from "../lib/types";

function ResetPasswordContent() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token");

  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [success, setSuccess] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setErrorMsg(null);

    if (!token) {
      setErrorMsg("Mã khôi phục không tìm thấy hoặc không hợp lệ.");
      return;
    }
    if (!password || !confirmPassword) {
      setErrorMsg("Vui lòng nhập mật khẩu mới và xác nhận mật khẩu.");
      return;
    }
    if (password !== confirmPassword) {
      setErrorMsg("Mật khẩu xác nhận không khớp.");
      return;
    }
    if (password.length < 8) {
      setErrorMsg("Mật khẩu mới phải dài ít nhất 8 ký tự.");
      return;
    }

    setIsSubmitting(true);
    try {
      await apiResetPassword(token, password);
      setSuccess(true);
    } catch (err) {
      if (err instanceof ApiError) {
        setErrorMsg(err.message || "Mã khôi phục đã hết hạn hoặc không hợp lệ.");
      } else {
        setErrorMsg("Đã xảy ra lỗi hệ thống. Vui lòng thử lại sau.");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-md flex-col justify-center px-5 py-12">
      <main
        className="rounded-2xl border border-[#28433b] bg-[#0d1916] p-8"
        id="main-content"
      >
        {success ? (
          <div className="text-center">
            <span
              aria-hidden="true"
              className="mx-auto mb-6 flex size-12 items-center justify-center rounded-full bg-emerald-500/10 text-xl font-bold text-emerald-300"
            >
              ✓
            </span>
            <h1 className="text-2xl font-bold tracking-tight text-white">
              Đổi mật khẩu thành công
            </h1>
            <p className="mt-4 text-sm leading-6 text-slate-300">
              Mật khẩu của bạn đã được cập nhật. Lịch sử các phiên đăng nhập
              khác của tài khoản này đã được thu hồi vì lý do bảo mật.
            </p>
            <div className="mt-8 border-t border-white/10 pt-6">
              <Link
                href="/login"
                className="inline-flex min-h-11 items-center justify-center rounded-full bg-emerald-200 px-6 font-bold text-emerald-950 hover:bg-emerald-100 transition-colors"
              >
                Đăng nhập ngay
              </Link>
            </div>
          </div>
        ) : (
          <section aria-labelledby="reset-title">
            <h1
              className="text-2xl font-bold tracking-tight text-white"
              id="reset-title"
            >
              Đặt lại mật khẩu
            </h1>
            <p className="mt-3 text-sm text-slate-400">
              Nhập mật khẩu mới cho tài khoản tổ chức của bạn.
            </p>

            <form className="mt-8" onSubmit={handleSubmit} noValidate>
              <fieldset disabled={isSubmitting} className="space-y-5 border-0 p-0">
                <legend className="sr-only">Thông tin mật khẩu mới</legend>

                <div>
                  <label
                    className="mb-2 block text-sm font-semibold text-slate-200"
                    htmlFor="password"
                  >
                    Mật khẩu mới
                  </label>
                  <input
                    autoComplete="new-password"
                    className="min-h-12 w-full rounded-xl border border-white/15 bg-white/5 px-4 text-white focus:border-emerald-300 focus:outline-none disabled:cursor-not-allowed disabled:opacity-60"
                    id="password"
                    name="password"
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                  />
                </div>

                <div>
                  <label
                    className="mb-2 block text-sm font-semibold text-slate-200"
                    htmlFor="confirmPassword"
                  >
                    Xác nhận mật khẩu mới
                  </label>
                  <input
                    autoComplete="new-password"
                    className="min-h-12 w-full rounded-xl border border-white/15 bg-white/5 px-4 text-white focus:border-emerald-300 focus:outline-none disabled:cursor-not-allowed disabled:opacity-60"
                    id="confirmPassword"
                    name="confirmPassword"
                    type="password"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    required
                  />
                </div>

                {errorMsg && (
                  <p
                    className="rounded-xl border border-rose-500/20 bg-rose-500/5 p-4 text-sm leading-6 text-rose-300"
                    role="alert"
                  >
                    {errorMsg}
                  </p>
                )}

                {!token && (
                  <p
                    className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-4 text-sm leading-6 text-amber-300"
                    role="alert"
                  >
                    Lưu ý: Không tìm thấy mã khôi phục trên URL. Nút Đổi mật
                    khẩu sẽ không hoạt động nếu thiếu mã.
                  </p>
                )}

                <button
                  className="min-h-12 w-full rounded-xl bg-emerald-200 px-5 font-bold text-emerald-950 hover:bg-emerald-100 disabled:cursor-not-allowed disabled:opacity-60 flex items-center justify-center transition-colors"
                  type="submit"
                >
                  {isSubmitting ? (
                    <span className="inline-block size-5 animate-spin rounded-full border-2 border-emerald-950 border-t-transparent" />
                  ) : (
                    "Đổi mật khẩu"
                  )}
                </button>
              </fieldset>
            </form>
          </section>
        )}
      </main>
    </div>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={
      <div className="grid min-h-screen place-items-center bg-[#07100e] text-[#f4f7f5]">
        <div className="flex flex-col items-center gap-4">
          <span className="size-10 animate-spin rounded-full border-2 border-emerald-300 border-t-transparent" />
          <p className="text-sm font-semibold text-slate-400">Đang tải...</p>
        </div>
      </div>
    }>
      <ResetPasswordContent />
    </Suspense>
  );
}
