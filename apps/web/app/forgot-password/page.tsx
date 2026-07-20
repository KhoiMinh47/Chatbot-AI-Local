"use client";

/**
 * Phase 8 forgot password flow.
 *
 * Safe implementation that always returns success to prevent user email
 * enumeration attacks (anti-enumeration).
 */

import { useState, type FormEvent } from "react";
import Link from "next/link";

import { apiForgotPassword } from "../lib/api";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [success, setSuccess] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();

    if (!email.trim()) return;

    setIsSubmitting(true);
    try {
      // Safe call, API returns 204 regardless of email presence to avoid enumeration
      await apiForgotPassword(email.trim());
    } finally {
      setIsSubmitting(false);
      setSuccess(true);
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
              Đã gửi yêu cầu khôi phục
            </h1>
            <p className="mt-4 text-sm leading-6 text-slate-300">
              Nếu địa chỉ email <strong className="text-white">{email}</strong>{" "}
              tồn tại trong hệ thống, bạn sẽ nhận được một hướng dẫn khôi phục
              mật khẩu trong vài phút tới.
            </p>
            <div className="mt-8 border-t border-white/10 pt-6">
              <Link
                href="/login"
                className="inline-flex min-h-11 items-center justify-center rounded-full bg-emerald-200 px-6 font-bold text-emerald-950 hover:bg-emerald-100 transition-colors"
              >
                Quay lại đăng nhập
              </Link>
            </div>
          </div>
        ) : (
          <section aria-labelledby="forgot-title">
            <h1
              className="text-2xl font-bold tracking-tight text-white"
              id="forgot-title"
            >
              Quên mật khẩu
            </h1>
            <p className="mt-3 text-sm text-slate-400">
              Nhập email tổ chức của bạn, chúng tôi sẽ gửi liên kết khôi phục
              mật khẩu.
            </p>

            <form className="mt-8" onSubmit={handleSubmit}>
              <fieldset disabled={isSubmitting} className="space-y-5 border-0 p-0">
                <legend className="sr-only">Thông tin khôi phục mật khẩu</legend>

                <div>
                  <label
                    className="mb-2 block text-sm font-semibold text-slate-200"
                    htmlFor="email"
                  >
                    Email
                  </label>
                  <input
                    autoComplete="email"
                    className="min-h-12 w-full rounded-xl border border-white/15 bg-white/5 px-4 text-white focus:border-emerald-300 focus:outline-none disabled:cursor-not-allowed disabled:opacity-60"
                    id="email"
                    name="email"
                    placeholder="ten@congty.vn"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                  />
                </div>

                <button
                  className="min-h-12 w-full rounded-xl bg-emerald-200 px-5 font-bold text-emerald-950 hover:bg-emerald-100 disabled:cursor-not-allowed disabled:opacity-60 flex items-center justify-center transition-colors"
                  type="submit"
                >
                  {isSubmitting ? (
                    <span className="inline-block size-5 animate-spin rounded-full border-2 border-emerald-950 border-t-transparent" />
                  ) : (
                    "Gửi yêu cầu"
                  )}
                </button>
              </fieldset>
            </form>

            <div className="mt-6 text-center">
              <Link
                href="/login"
                className="text-sm font-semibold text-emerald-300 hover:text-emerald-200"
              >
                Quay lại đăng nhập
              </Link>
            </div>
          </section>
        )}
      </main>
    </div>
  );
}
