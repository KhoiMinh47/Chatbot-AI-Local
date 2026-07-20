"use client";
import { useEffect } from "react";
import { usePathname } from "next/navigation";
import { heartbeatPing } from "../services/authService";

// Ping mỗi 30s khi tab đang active (foreground).
// Browser throttle background tabs xuống ~60s nên TTL backend phải >> 60s.
const HEARTBEAT_INTERVAL = 30_000;

export default function HeartbeatProvider({ children }) {
    const pathname = usePathname();

    useEffect(() => {
        const isPublicPage =
            pathname?.includes('/signin') ||
            pathname?.includes('/signup') ||
            pathname?.includes('/forgot-password') ||
            pathname?.includes('/verify-email');

        if (isPublicPage) {
            return () => {};
        }

        const ping = () => {
            heartbeatPing().catch((err) => {
                const status = err?.response?.status;
                if (
                    (status === 401 || status === 403) &&
                    typeof window !== 'undefined' &&
                    !window.location.pathname.includes('/signin') &&
                    !window.location.pathname.includes('/signup')
                ) {
                    const detail = err?.response?.data?.detail || 'Phiên đăng nhập đã hết hạn.';
                    localStorage.removeItem('userName');
                    localStorage.removeItem('userId');
                    localStorage.removeItem('userRoles');
                    window.location.href = `/signin?reason=${encodeURIComponent(detail)}`;
                } else {
                    console.warn('Heartbeat ping failed:', err?.message || err);
                }
            });
        };

        // Ping ngay khi mount
        ping();

        const timer = setInterval(ping, HEARTBEAT_INTERVAL);

        // Khi user quay lại tab (Page Visibility API):
        // Re-ping ngay lập tức để cập nhật trạng thái online,
        // vì setInterval bị throttle khi tab ở background.
        const handleVisibilityChange = () => {
            if (document.visibilityState === 'visible') {
                ping();
            }
        };
        document.addEventListener('visibilitychange', handleVisibilityChange);

        return () => {
            clearInterval(timer);
            document.removeEventListener('visibilitychange', handleVisibilityChange);
        };
    }, [pathname]);

    return <>{children}</>;
}
