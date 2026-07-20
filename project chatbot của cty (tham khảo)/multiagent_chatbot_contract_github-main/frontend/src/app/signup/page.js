'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import styles from '../../styles/Auth.module.css';
import { register } from '../../services/authService';

export default function Signup() {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [logoSpin, setLogoSpin] = useState(false);
  const router = useRouter();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setSuccess('');
    setIsLoading(true);

    try {
      await register(email, password, name);
      setSuccess('Đăng ký thành công! Vui lòng kiểm tra email để xác thực tài khoản.');
      setTimeout(() => router.push('/signin'), 3000);
    } catch (err) {
      const detail = err.response?.data?.detail;
      setError(detail || 'Đăng ký thất bại. Vui lòng thử lại sau.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className={styles.authContainer}>
      <div className={styles.authCard}>
        <div className={styles.authLogo}>
          <div
            className={styles.logoOrb}
            onMouseEnter={() => setLogoSpin(true)}
            onMouseLeave={() => setLogoSpin(false)}
            style={{ transform: logoSpin ? 'rotate(8deg) scale(1.04)' : 'rotate(0deg) scale(1)' }}
          >
            <img src="/snowflake.png" alt="NTC Logo" className={styles.logoImage} />
          </div>
        </div>

        <h1 className={styles.authTitle}>Create your NTC account</h1>
        <p className={styles.authSubtitle}>Start with a modern AI workspace for legal and RAG operations.</p>

        {error && <div className={styles.errorMessage}>{error}</div>}
        {success && <div className={styles.successMessage}>{success}</div>}

        <form className={styles.authForm} onSubmit={handleSubmit}>
          <div className={styles.inputGroup}>
            <label className={styles.inputLabel}>Name</label>
            <input
              type="text"
              className={styles.authInput}
              placeholder="Your full name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              disabled={isLoading || !!success}
            />
          </div>

          <div className={styles.inputGroup}>
            <label className={styles.inputLabel}>Email</label>
            <input
              type="email"
              className={styles.authInput}
              placeholder="you@company.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              disabled={isLoading || !!success}
            />
          </div>

          <div className={styles.inputGroup}>
            <label className={styles.inputLabel}>Password</label>
            <div className={styles.inputWrapper}>
              <input
                type={showPassword ? 'text' : 'password'}
                className={styles.authInput}
                placeholder="Create a strong password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                disabled={isLoading || !!success}
              />
              <button type="button" className={styles.eyeButton} onClick={() => setShowPassword(!showPassword)}>
                {showPassword ? (
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path><line x1="1" y1="1" x2="23" y2="23"></line></svg>
                ) : (
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>
                )}
              </button>
            </div>
          </div>

          <button type="submit" className={styles.submitButton} disabled={isLoading || !!success}>
            {isLoading ? 'Đang tạo tài khoản...' : 'Create Account'}
          </button>
        </form>

        <div className={styles.authFooter}>
          Already have an account? <Link href="/signin" className={styles.linkBtn}>Sign in</Link>
        </div>
      </div>
    </div>
  );
}
