"use client";

/**
 * Phase 8 interactive login page.
 *
 * Connects with `useAuth` to submit credentials, handle unverified status,
 * validation errors, and redirects to `/chat` on success.
 */

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { useAuth } from "../lib/auth-context";
import { ApiError } from "../lib/types";

export default function LoginPage() {
  const router = useRouter();
  const { login } = useAuth();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setErrorMsg(null);

    if (!email.trim() || !password) {
      setErrorMsg("Vui lòng điền đầy đủ email và mật khẩu.");
      return;
    }

    setIsSubmitting(true);
    try {
      await login(email.trim(), password);
      router.push("/chat");
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.code === "ACCOUNT_NOT_VERIFIED") {
          setErrorMsg("Tài khoản của bạn chưa được xác thực email.");
        } else {
          setErrorMsg(err.message || "Email hoặc mật khẩu không chính xác.");
        }
      } else {
        setErrorMsg("Đã xảy ra lỗi kết nối. Vui lòng thử lại sau.");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

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
            Local-first knowledge
          </p>
          <p className="mt-6 text-5xl leading-tight font-semibold tracking-[-0.045em] text-balance">
            Truy cập tri thức của đội ngũ trong một không gian riêng tư.
          </p>
        </div>

        <p className="hidden text-sm text-slate-400 lg:block">
          NTC Local Knowledge
        </p>
      </aside>

      <main
        className="flex items-center py-12 lg:py-10 lg:pl-20"
        id="main-content"
      >
        <section aria-labelledby="login-title" className="w-full max-w-md">
          <p className="text-sm font-bold tracking-[0.16em] text-emerald-200 uppercase">
            Chào mừng trở lại
          </p>
          <h1
            className="mt-4 text-4xl font-semibold tracking-[-0.04em]"
            id="login-title"
          >
            Đăng nhập
          </h1>
          <p className="mt-4 leading-7 text-slate-400">
            Dùng tài khoản tổ chức để tiếp tục vào không gian tri thức nội bộ.
          </p>

          <form
            aria-describedby="login-status"
            className="mt-10"
            onSubmit={handleSubmit}
            noValidate
          >
            <fieldset disabled={isSubmitting} className="space-y-5 border-0 p-0">
              <legend className="sr-only">Thông tin đăng nhập</legend>

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

              <div>
                <div className="mb-2 flex items-center justify-between">
                  <label
                    className="block text-sm font-semibold text-slate-200"
                    htmlFor="password"
                  >
                    Mật khẩu
                  </label>
                  <Link
                    href="/forgot-password"
                    className="text-xs font-semibold text-emerald-300 hover:text-emerald-200 focus-visible:outline-none"
                  >
                    Quên mật khẩu?
                  </Link>
                </div>
                <input
                  autoComplete="current-password"
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
                  "Đăng nhập"
                )}
              </button>
            </fieldset>
          </form>

          <p className="mt-8 text-center text-sm text-slate-400">
            Chưa có tài khoản?{" "}
            <Link
              href="/register"
              className="font-semibold text-emerald-300 hover:text-emerald-200"
            >
              Đăng ký ngay
            </Link>
          </p>
        </section>
      </main>
    </div>
  );
}
