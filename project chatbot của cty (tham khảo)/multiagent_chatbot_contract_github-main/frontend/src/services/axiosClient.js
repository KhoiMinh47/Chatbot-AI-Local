import axios from 'axios';
import { API_BASE } from './apiBase';

const baseURL = API_BASE || '/';

export const axiosClient = axios.create({
  baseURL,
  timeout: 400000,
  headers: {
    'Content-Type': 'application/json',
  },
  withCredentials: true, // BẮT BUỘC cho JWT httponly cookie
});

export const axiosClientFile = axios.create({
  baseURL,
  timeout: 500000,
  headers: {
    'Content-Type': 'multipart/form-data',
  },
  withCredentials: true, // BẮT BUỘC cho JWT httponly cookie
});

export const axiosPublicClient = axios.create({
  baseURL,
  timeout: 400000,
  headers: {
    'Content-Type': 'application/json',
  },
  withCredentials: false,
});

const isPublicRoute = () => {
  if (typeof window === 'undefined') return false;
  const path = window.location.pathname || '';
  return (
    path.includes('/signin') ||
    path.includes('/signup') ||
    path.includes('/forgot-password') ||
    path.includes('/verify-email')
  );
};

// Interceptor: tự động redirect về /signin khi nhận 401
const handle401 = (error) => {
  if (
    error.response?.status === 401 &&
    typeof window !== 'undefined' &&
    !isPublicRoute()
  ) {
    // Lấy lý do từ backend (VPN, session kicked, hết hạn, ...)
    const detail = error.response?.data?.detail || 'Phiên đăng nhập đã hết hạn.';

    localStorage.removeItem('userName');
    localStorage.removeItem('userId');
    localStorage.removeItem('userRoles');

    // Truyền lý do qua URL để trang signin hiển thị thông báo
    const msg = encodeURIComponent(detail);
    window.location.href = `/signin?reason=${msg}`;
  }
  return Promise.reject(error);
};

axiosClient.interceptors.response.use((res) => res, handle401);
axiosClientFile.interceptors.response.use((res) => res, handle401);

/**
 * Dùng cho native fetch() calls: kiểm tra status 401/403 và redirect về signin.
 * Gọi NGAY SAU khi nhận response từ fetch(), TRƯỚC khi đọc body.
 * Returns true nếu đã redirect (caller nên dừng xử lý tiếp).
 */
export function redirectIfUnauthorized(response) {
  if (
    (response.status === 401 || response.status === 403) &&
    typeof window !== 'undefined' &&
    !isPublicRoute()
  ) {
    localStorage.removeItem('userName');
    localStorage.removeItem('userId');
    localStorage.removeItem('userRoles');
    // Đọc detail từ body nếu có thể (best-effort)
    response.json().catch(() => ({})).then((body) => {
      const detail = body?.detail || 'Phiên đăng nhập đã hết hạn.';
      window.location.href = `/signin?reason=${encodeURIComponent(detail)}`;
    });
    return true;
  }
  return false;
}
