'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import styles from '../../styles/Auth.module.css';
import { login } from '../../services/authService';

export default function Signin() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [sessionMsg, setSessionMsg] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [logoTilt, setLogoTilt] = useState({ x: 0, y: 0 });
  const router = useRouter();
  const searchParams = useSearchParams();

  useEffect(() => {
    const reason = searchParams.get('reason');
    if (reason) {
      setSessionMsg(decodeURIComponent(reason));
    }
  }, [searchParams]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setIsLoading(true);

    try {
      const data = await login(email, password);
      const account = data.account;

      localStorage.setItem('userName', account.name || email.split('@')[0]);
      localStorage.setItem('userId', account.id);
      localStorage.setItem('userEmail', account.email);
      if (account.roles) localStorage.setItem('userRoles', JSON.stringify(account.roles));

      router.push('/chat');
    } catch (err) {
      const status = err.response?.status;
      const detail = err.response?.data?.detail;

      if (detail) setError(detail);
      else if (status === 401) setError('Email hoặc mật khẩu không đúng.');
      else if (status === 403) setError('Tài khoản chưa được kích hoạt.');
      else setError('Không thể kết nối đến máy chủ. Vui lòng thử lại.');
    } finally {
      setIsLoading(false);
    }
  };

  const onLogoMove = (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const px = (e.clientX - rect.left) / rect.width;
    const py = (e.clientY - rect.top) / rect.height;
    setLogoTilt({ x: (py - 0.5) * -10, y: (px - 0.5) * 10 });
  };

  return (
    <div className={styles.authContainer}>
      <div className={styles.authCard}>
        <div className={styles.authLogo}>
          <div
            className={styles.logoOrb}
            onMouseMove={onLogoMove}
            onMouseLeave={() => setLogoTilt({ x: 0, y: 0 })}
            style={{ transform: `perspective(640px) rotateX(${logoTilt.x}deg) rotateY(${logoTilt.y}deg)` }}
          >
            <img src="/snowflake.png" alt="NTC Logo" className={styles.logoImage} />
          </div>
        </div>

        <h1 className={styles.authTitle}>Sign in to NTC AI</h1>
        <p className={styles.authSubtitle}>Secure gateway to your RAG and contract workspace.</p>

        {sessionMsg && <div className={`${styles.errorMessage} ${styles.warnMessage}`}>{sessionMsg}</div>}
        {error && <div className={styles.errorMessage}>{error}</div>}

        <form className={styles.authForm} onSubmit={handleSubmit}>
          <div className={styles.inputGroup}>
            <label className={styles.inputLabel}>Email</label>
            <input
              type="email"
              className={styles.authInput}
              placeholder="you@company.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              disabled={isLoading}
            />
          </div>

          <div className={styles.inputGroup}>
            <label className={styles.inputLabel}>Password</label>
            <div className={styles.inputWrapper}>
              <input
                type={showPassword ? 'text' : 'password'}
                className={styles.authInput}
                placeholder="Enter your password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                disabled={isLoading}
              />
              <button
                type="button"
                className={styles.eyeButton}
                onClick={() => setShowPassword(!showPassword)}
                aria-label="Toggle password"
              >
                {showPassword ? (
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path><line x1="1" y1="1" x2="23" y2="23"></line></svg>
                ) : (
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>
                )}
              </button>
            </div>
          </div>

          <button type="submit" className={styles.submitButton} disabled={isLoading}>
            {isLoading ? 'Đang đăng nhập...' : 'Sign In'}
          </button>

          <div className={styles.forgotWrapper}>
            <Link href="/forgot-password" className={styles.forgotLink}>Forgot password?</Link>
          </div>
        </form>

        <div className={styles.authFooter}>
          Don&apos;t have an account? <Link href="/signup" className={styles.linkBtn}>Sign up</Link>
        </div>
      </div>
    </div>
  );
}
