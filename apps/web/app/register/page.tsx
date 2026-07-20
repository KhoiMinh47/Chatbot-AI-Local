"use client";

/**
 * Phase 8 user registration page.
 *
 * Captures email, password, and display name, call `apiRegister` and displays
 * a check-email state on success.
 */

import { useState, type FormEvent } from "react";
import Link from "next/link";

import { apiRegister } from "../lib/api";
import { ApiError } from "../lib/types";

export default function RegisterPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [success, setSuccess] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setErrorMsg(null);

    if (!email.trim() || !password || !displayName.trim()) {
      setErrorMsg("Vui lòng điền đầy đủ tất cả các trường.");
      return;
    }

    setIsSubmitting(true);
    try {
      await apiRegister(email.trim(), password, displayName.trim());
      setSuccess(true);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.code === "EMAIL_ALREADY_REGISTERED") {
          setErrorMsg("Email này đã được đăng ký sử dụng.");
        } else {
          setErrorMsg(err.message || "Không thể đăng ký tài khoản.");
        }
      } else {
        setErrorMsg("Đã xảy ra lỗi hệ thống. Vui lòng thử lại sau.");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  if (success) {
    return (
      <div className="mx-auto flex min-h-screen w-full max-w-md flex-col justify-center px-5 py-12">
        <div className="rounded-2xl border border-[#28433b] bg-[#0d1916] p-8 text-center">
          <span
            aria-hidden="true"
            className="mx-auto mb-6 flex size-12 items-center justify-center rounded-full bg-emerald-500/10 text-xl font-bold text-emerald-300"
          >
            ✓
          </span>
          <h1 className="text-2xl font-bold tracking-tight text-white">
            Đăng ký thành công
          </h1>
          <p className="mt-4 text-sm leading-6 text-slate-300">
            Một email xác thực đã được gửi đến hộp thư{" "}
            <strong className="text-white">{email}</strong>. Vui lòng kiểm tra
            và click vào liên kết để kích hoạt tài khoản của bạn.
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
      </div>
    );
  }

  return (
    <div className="mx-auto grid min-h-screen w-full max-w-7xl px-5 sm:px-8 lg:grid-cols-2 lg:px-12">
      <aside className="flex flex-col justify-between border-white/10 py-6 lg:border-r lg:py-10 lg:pr-14">
        <Link
          className="w-fit rounded-md text-sm font-semibold text-emerald-100 hover:text-emerald-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300"
          href="/"
        >
          <span aria-hidden="true">← </span>
          Trang chủ
        </Link>

        <div className="hidden max-w-lg lg:block">
          <p className="font-mono text-xs tracking-[0.18em] text-emerald-200 uppercase">
            Create Account
          </p>
          <p className="mt-6 text-5xl leading-tight font-semibold tracking-[-0.045em] text-balance">
            Bắt đầu tổ chức tri thức và hỏi đáp tài liệu an toàn.
          </p>
        </div>

        <p className="hidden text-sm text-slate-400 lg:block">
          NTC Local Knowledge
        </p>
      </aside>

      <main className="flex items-center py-12 lg:py-10 lg:pl-20" id="main-content">
        <section aria-labelledby="register-title" className="w-full max-w-md">
          <p className="text-sm font-bold tracking-[0.16em] text-emerald-200 uppercase">
            Bắt đầu sử dụng
          </p>
          <h1
            className="mt-4 text-4xl font-semibold tracking-[-0.04em]"
            id="register-title"
          >
            Tạo tài khoản
          </h1>
          <p className="mt-4 leading-7 text-slate-400">
            Điền các thông tin sau để đăng ký tài khoản nội bộ.
          </p>

          <form className="mt-10" onSubmit={handleSubmit} noValidate>
            <fieldset disabled={isSubmitting} className="space-y-5 border-0 p-0">
              <legend className="sr-only">Thông tin đăng ký</legend>

              <div>
                <label
                  className="mb-2 block text-sm font-semibold text-slate-200"
                  htmlFor="displayName"
                >
                  Tên hiển thị
                </label>
                <input
                  autoComplete="name"
                  className="min-h-12 w-full rounded-xl border border-white/15 bg-white/5 px-4 text-white focus:border-emerald-300 focus:outline-none disabled:cursor-not-allowed disabled:opacity-60"
                  id="displayName"
                  name="displayName"
                  placeholder="Nguyễn Văn A"
                  type="text"
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  required
                />
              </div>

              <div>
                <label
                  className="mb-2 block text-sm font-semibold text-slate-200"
                  htmlFor="email"
                >
                  Email tổ chức
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

              <div>
                <label
                  className="mb-2 block text-sm font-semibold text-slate-200"
                  htmlFor="password"
                >
                  Mật khẩu
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

              {errorMsg && (
                <p
                  className="rounded-xl border border-rose-500/20 bg-rose-500/5 p-4 text-sm leading-6 text-rose-300"
                  role="alert"
                >
                  {errorMsg}
                </p>
              )}

              <button
                className="min-h-12 w-full rounded-xl bg-emerald-200 px-5 font-bold text-emerald-950 hover:bg-emerald-100 disabled:cursor-not-allowed disabled:opacity-60 flex items-center justify-center transition-colors"
                type="submit"
              >
                {isSubmitting ? (
                  <span className="inline-block size-5 animate-spin rounded-full border-2 border-emerald-950 border-t-transparent" />
                ) : (
                  "Đăng ký"
                )}
              </button>
            </fieldset>
          </form>

          <p className="mt-8 text-center text-sm text-slate-400">
            Đã có tài khoản?{" "}
            <Link
              href="/login"
              className="font-semibold text-emerald-300 hover:text-emerald-200"
            >
              Đăng nhập
            </Link>
          </p>
        </section>
      </main>
    </div>
  );
}
