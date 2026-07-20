"use client";
import { useEffect, useRef } from "react";
import { buildApiUrl } from "../services/apiBase";

const SSE_URL = buildApiUrl('/api/v1/auth/notifications/sse');

export default function NotificationListener({ onAlert }) {
    // Dùng ref để luôn giữ reference mới nhất của onAlert
    // mà không cần đưa vào dependency array của useEffect bên dưới.
    // Mục đích: SSE connection chỉ được tạo 1 lần duy nhất,
    // tránh spam reconnect mỗi khi parent component re-render.
    const onAlertRef = useRef(onAlert);
    useEffect(() => {
        onAlertRef.current = onAlert;
    }, [onAlert]);

    useEffect(() => {
        const eventSource = new EventSource(SSE_URL, {
            withCredentials: true, // gửi cookie JWT
        });

        // Lắng nghe named event "security_alert" từ server
        eventSource.addEventListener("security_alert", (event) => {
            try {
                const alert = JSON.parse(event.data);
                if (onAlertRef.current) {
                    onAlertRef.current(alert);
                }
            } catch (err) {
                console.error("Error parsing SSE data:", err);
            }
        });

        // Lắng nghe event "error" từ server (vd: quá nhiều connections)
        eventSource.addEventListener("error", (event) => {
            if (event.data) {
                try {
                    const err = JSON.parse(event.data);
                    console.warn("SSE server error:", err.error);
                } catch {}
            }
        });

        eventSource.onerror = () => {
            // EventSource tự reconnect theo retry: hint từ server (30 phút)
        };

        return () => {
            eventSource.close();
        };
    }, []); // Không có dependency → chỉ tạo 1 EventSource duy nhất

    return null; // Không render gì
}
