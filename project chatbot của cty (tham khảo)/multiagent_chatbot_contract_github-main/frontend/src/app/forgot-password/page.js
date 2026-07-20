'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import styles from '../../styles/Auth.module.css';
import { forgotPassword } from '../../services/authService';

export default function ForgotPassword() {
  const [email, setEmail] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setSuccess('');
    setIsLoading(true);

    try {
      await forgotPassword(email);
      setSuccess('Nếu tài khoản tồn tại, mật khẩu mới đã được gửi đến email của bạn. Vui lòng kiểm tra hộp thư.');
    } catch (err) {
      const detail = err.response?.data?.detail;
      setError(detail || 'Có lỗi xảy ra. Vui lòng thử lại sau.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className={styles.authContainer}>
      <div className={styles.authCard}>
        <div className={styles.authLogo}>
          <div className={styles.logoOrb}>
            <img src="/snowflake.png" alt="NTC Logo" className={styles.logoImage} />
          </div>
        </div>

        <h1 className={styles.authTitle}>Reset your password</h1>
        <p className={styles.authSubtitle}>Enter your registered email. We will issue a temporary password for secure sign-in.</p>

        {error && <div className={styles.errorMessage}>{error}</div>}
        {success && <div className={styles.successMessage}>{success}</div>}

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
              disabled={isLoading || !!success}
            />
          </div>

          <button type="submit" className={styles.submitButton} disabled={isLoading || !!success}>
            {isLoading ? 'Đang gửi...' : 'Gửi mật khẩu mới'}
          </button>
        </form>

        <div className={styles.authFooter}>
          Remember your password? <Link href="/signin" className={styles.linkBtn}>Sign in</Link>
        </div>
      </div>
    </div>
  );
}
