'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import Image from 'next/image';
import styles from '../../styles/VerifyEmail.module.css';
import { verifyEmailToken } from '../../services/authService';

const STATUS = {
  VERIFYING: 'verifying',
  SUCCESS: 'success',
  ALREADY: 'already',
  ERROR: 'error',
};

export default function VerifyEmailPage() {
  const [status, setStatus] = useState(STATUS.VERIFYING);
  const [message, setMessage] = useState('Đang xác thực email...');

  useEffect(() => {
    const hash = window.location.hash || '';
    const hashParams = new URLSearchParams(hash.startsWith('#') ? hash.slice(1) : hash);
    const token = hashParams.get('vt');

    // Xóa token khỏi thanh địa chỉ ngay sau khi đọc để giảm rủi ro lộ token.
    window.history.replaceState({}, document.title, window.location.pathname);

    const run = async () => {
      if (!token) {
        setStatus(STATUS.ERROR);
        setMessage('Link xác thực không hợp lệ hoặc thiếu token.');
        return;
      }

      try {
        const result = await verifyEmailToken(token);
        const code = result?.code;

        if (code === 'VERIFIED') {
          setStatus(STATUS.SUCCESS);
          setMessage(result?.message || 'Xác thực email thành công!');
          return;
        }

        if (code === 'ALREADY_VERIFIED') {
          setStatus(STATUS.ALREADY);
          setMessage(result?.message || 'Email đã được xác thực trước đó.');
          return;
        }

        setStatus(STATUS.ERROR);
        setMessage('Không thể xác thực email. Vui lòng thử lại.');
      } catch (error) {
        const detail = error?.response?.data?.detail;
        setStatus(STATUS.ERROR);
        setMessage(detail || 'Không thể xác thực email. Vui lòng thử lại.');
      }
    };

    run();
  }, []);

  const icon = useMemo(() => {
    if (status === STATUS.VERIFYING) return '...';
    if (status === STATUS.SUCCESS || status === STATUS.ALREADY) return '✓';
    return '✕';
  }, [status]);

  const title = useMemo(() => {
    if (status === STATUS.VERIFYING) return 'Đang xác thực email';
    if (status === STATUS.SUCCESS) return 'Xác thực thành công';
    if (status === STATUS.ALREADY) return 'Email đã xác thực';
    return 'Xác thực thất bại';
  }, [status]);

  return (
    <div className={styles.container}>
      <div className={styles.card}>
        <div className={styles.topBar} />

        <div className={styles.header}>
          <Image src="/snowflake.png" alt="NTC" width={40} height={40} className={styles.logo} />
          <div className={styles.brand}>
            <span>ChatBot </span>
            <span className={styles.brandAccent}>NTC</span>
          </div>
        </div>

        <div className={styles.divider} />

        <div className={styles.content}>
          <div
            className={[
              styles.iconCircle,
              status === STATUS.ERROR ? styles.iconError : styles.iconSuccess,
            ].join(' ')}
          >
            {icon}
          </div>
          <h1 className={styles.title}>{title}</h1>
          <p className={styles.message}>{message}</p>
        </div>

        <div className={styles.actions}>
          <Link href="/signin" className={styles.primaryBtn}>
            Đi đến trang đăng nhập
          </Link>
        </div>
      </div>
    </div>
  );
}
