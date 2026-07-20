"""
Middleware giám sát IP — phát hiện bất thường và tự động force logout.

Logic:
    1. Đọc JWT từ cookie, extract login_ip.
    2. Fast-path: current IP == login_ip → bỏ qua, không overhead.
    3. Nếu IP thay đổi:
        a. GeoIP lookup IP mới.
        b. Check VPN/datacenter → nếu True → anomaly ngay.
        c. Impossible travel: so khoảng cách GeoIP (IP cũ vs mới)
           với thời gian kể từ iat, nếu >900 km/h → anomaly.
    4. Khi phát hiện anomaly:
        - Deactivate account (is_active=False).
        - Ghi AdminNotification vào PostgreSQL.
        - Publish JSON alert lên Redis channel:notifications (SSE).
        - Xóa cookie access_token (force logout).
        - Trả 401.

Chiến lược hiệu suất:
    - Middleware chỉ chạy trên route /api/v1/ (skip static, docs, ...).
    - Fast-path IP match → overhead gần = 0.
    - Haversine + GeoIP chỉ chạy khi IP thực sự khác.
"""

import json
import ipaddress
import logging
import math
import os
import time
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from auth import decode_token
from database.setup_geoip import geoip_service
from database.setup_redis import redis_service
from database.setup_postgres import SessionLocal
from database.table.table_postgres import Account, AdminNotification

logger = logging.getLogger(__name__)

# Tốc độ di chuyển tối đa hợp lý (km/h) — máy bay thương mại
MAX_TRAVEL_SPEED_KMH = 900

# Redis pub/sub channel cho admin notifications
NOTIFICATION_CHANNEL = "channel:notifications"

# Cooldown dedup: cùng account + cùng alert_type + cùng IP → chỉ notify 1 lần trong window này
ANOMALY_COOLDOWN_TTL = 300  # giây (5 phút)

# Bán kính Trái Đất (km)
EARTH_RADIUS_KM = 6371.0

# IPs/CIDR của reverse proxy tin cậy — chỉ trust X-Forwarded-For khi peer IP match cấu hình này.
# Hỗ trợ cả IP đơn lẻ và CIDR:
#   TRUSTED_PROXY_IPS=127.0.0.1,::1,172.16.0.0/12
_TRUSTED_PROXY_RULES = []
for _raw in os.getenv("TRUSTED_PROXY_IPS", "127.0.0.1,::1").split(","):
    _raw = _raw.strip()
    if not _raw:
        continue
    try:
        if "/" in _raw:
            _TRUSTED_PROXY_RULES.append(ipaddress.ip_network(_raw, strict=False))
        else:
            _TRUSTED_PROXY_RULES.append(ipaddress.ip_address(_raw))
    except ValueError:
        logger.warning("Ignore invalid TRUSTED_PROXY_IPS entry: %s", _raw)


def _is_trusted_proxy_ip(peer_ip: str | None) -> bool:
    if not peer_ip:
        return False
    try:
        ip_obj = ipaddress.ip_address(peer_ip)
    except ValueError:
        return False

    for rule in _TRUSTED_PROXY_RULES:
        if isinstance(rule, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
            if ip_obj == rule:
                return True
        else:
            if ip_obj in rule:
                return True
    return False


def _extract_client_ip(request: Request) -> str:
    """
    Trích xuất IP thực từ request.

    Chỉ tin tưởng X-Forwarded-For khi request đến từ trusted proxy —
    tránh tấn công IP spoofing qua việc giả mạo header X-Forwarded-For.
    """
    peer_ip = request.client.host if request.client else None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and _is_trusted_proxy_ip(peer_ip):
        return forwarded.split(",")[0].strip()
    return peer_ip or "unknown"


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Tính khoảng cách giữa 2 tọa độ (km) bằng công thức Haversine.

    Input:
        lat1, lon1: Tọa độ điểm 1 (độ).
        lat2, lon2: Tọa độ điểm 2 (độ).

    Output:
        float: Khoảng cách (km).
    """
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


class IPMonitorMiddleware(BaseHTTPMiddleware):
    """
    ASGI middleware giám sát thay đổi IP giữa các request.

    Chỉ kiểm tra các request tới /api/v1/ có chứa access_token cookie.
    """

    async def dispatch(self, request: Request, call_next):
        """Safety wrapper: bất kỳ exception nào trong middleware đều không block request."""
        try:
            return await self._dispatch_inner(request, call_next)
        except Exception as e:
            logger.error("[IP_MONITOR] Unhandled exception in middleware: %s", e, exc_info=True)
            # Khi middleware lỗi: nếu IP đã thay đổi → fail-closed (an toàn hơn)
            # Nếu IP giữ nguyên → fail-open (tránh block user hợp lệ khi infra lỗi)
            try:
                token = request.cookies.get("access_token")
                if token:
                    payload = decode_token(token)
                    if payload.get("purpose") == "access":
                        current_ip = _extract_client_ip(request)
                        login_ip = payload.get("login_ip")
                        if login_ip and current_ip not in (login_ip, "unknown"):
                            try:
                                is_private = ipaddress.ip_address(current_ip).is_private
                            except (ValueError, TypeError):
                                is_private = False
                            if not is_private:
                                logger.warning(
                                    "[IP_MONITOR] Fail-closed do exception khi IP thay đổi: %s → %s",
                                    login_ip, current_ip,
                                )
                                resp = JSONResponse(
                                    status_code=401,
                                    content={"detail": "Không thể xác minh phiên đăng nhập. Vui lòng đăng nhập lại."},
                                )
                                resp.delete_cookie("access_token", path="/")
                                return resp
            except Exception:
                pass
            return await call_next(request)

    async def _dispatch_inner(self, request: Request, call_next):
        # Chỉ giám sát API routes
        if not request.url.path.startswith("/api/v1/"):
            return await call_next(request)

        # Bỏ qua login/register/verify (chưa có token)
        skip_paths = {
            "/api/v1/auth/login",
            "/api/v1/auth/register",
            "/api/v1/auth/verify-email",
            "/api/v1/auth/verify-email/confirm",
            "/api/v1/auth/forgot-password",
        }
        if request.url.path in skip_paths:
            return await call_next(request)

        # Đọc JWT từ cookie
        token = request.cookies.get("access_token")
        if not token:
            return await call_next(request)

        try:
            payload = decode_token(token)
        except Exception:
            # Token invalid/expired → để auth middleware xử lý
            return await call_next(request)

        # Chỉ check access token
        if payload.get("purpose") != "access":
            return await call_next(request)

        login_ip = payload.get("login_ip")
        if not login_ip:
            return await call_next(request)

        account_id = payload["sub"]
        jwt_ver = payload.get("session_ver")

        # === FAST-PATH: IP không đổi → check session version ===
        current_ip = _extract_client_ip(request)
        if current_ip == login_ip or current_ip == "unknown":
            return await self._check_session_ver(request, call_next, account_id, jwt_ver)

        # Private IP (LAN) → không thể GeoIP lookup → chỉ check session_ver
        try:
            if ipaddress.ip_address(current_ip).is_private:
                return await self._check_session_ver(request, call_next, account_id, jwt_ver)
        except (ValueError, TypeError):
            pass

        # === IP thay đổi → kiểm tra anomaly ===
        anomaly = await self._check_anomaly(
            account_id=account_id,
            login_ip=login_ip,
            current_ip=current_ip,
            token_iat=payload.get("iat"),
        )

        if anomaly:
            return await self._handle_anomaly(
                account_id=account_id,
                anomaly=anomaly,
            )

        # IP thay đổi bình thường (không phải VPN/impossible travel) → vẫn check session_ver
        return await self._check_session_ver(request, call_next, account_id, jwt_ver)

    async def _check_session_ver(self, request, call_next, account_id: int, jwt_ver):
        """
        Kiểm tra session version, kick session cũ khi có login mới.

        Được gọi ở TẤT CẢ nhánh (IP match, IP private, IP đổi bình thường)
        để đảm bảo single active session luôn được enforce.
        """
        if jwt_ver is not None and redis_service.client:
            try:
                redis_ver = await redis_service.client.get(f"session_ver:{account_id}")
                if redis_ver is not None and int(redis_ver) != int(jwt_ver):
                    response = JSONResponse(
                        status_code=401,
                        content={"detail": "Phiên đăng nhập đã hết hạn do đăng nhập từ thiết bị khác."},
                    )
                    response.delete_cookie("access_token", path="/")
                    logger.info(
                        "[IP_MONITOR] Session kicked — account_id=%s | jwt_ver=%s | redis_ver=%s",
                        account_id, jwt_ver, redis_ver,
                    )
                    return response
            except Exception as e:
                logger.warning("[IP_MONITOR] Không thể check session_ver: %s", e)
        return await call_next(request)

    async def _check_anomaly(
        self,
        account_id: int,
        login_ip: str,
        current_ip: str,
        token_iat: int | float | None,
    ) -> dict | None:
        """
        Kiểm tra xem sự thay đổi IP có bất thường không.

        Returns:
            dict với alert_type, severity, title, detail nếu anomaly.
            None nếu bình thường.
        """

        try:
            new_geo = geoip_service.lookup(current_ip)
        except Exception as e:
            logger.warning("[IP_MONITOR] GeoIP lookup thất bại cho %s: %s", current_ip, e)
            # Không thể xác minh IP thay đổi → fail-closed (block để an toàn)
            return {
                "alert_type": "ip_change_unverified",
                "severity": "high",
                "title": f"IP thay đổi không xác minh được: {current_ip}",
                "detail": json.dumps({
                    "current_ip": current_ip,
                    "login_ip": login_ip,
                    "reason": "GeoIP lookup thất bại",
                }, ensure_ascii=False),
                "ip_address": current_ip,
                "country": None,
            }

        # --- Check 0: IP thay đổi sang IP hoàn toàn không xác định (ASN DB không tải hoặc IP lạ) ---
        # Nếu ASN reader không load được thì mọi VPN IP đều trả asn=None, as_org=None
        # → phải flag như suspicious thay vì bỏ qua
        if new_geo.asn is None and new_geo.country is None:
            return {
                "alert_type": "ip_change_unknown",
                "severity": "high",
                "title": f"IP thay đổi sang địa chỉ không xác minh: {current_ip}",
                "detail": json.dumps({
                    "current_ip": current_ip,
                    "login_ip": login_ip,
                    "reason": "Không tìm thấy thông tin GeoIP/ASN cho IP mới",
                }, ensure_ascii=False),
                "ip_address": current_ip,
                "country": None,
            }

        # --- Check 1: VPN / Datacenter ---
        if new_geo.is_vpn_or_datacenter:
            return {
                "alert_type": "vpn_detected",
                "severity": "high",
                "title": f"Phát hiện VPN/Datacenter: {current_ip}",
                "detail": json.dumps({
                    "current_ip": current_ip,
                    "login_ip": login_ip,
                    "asn": new_geo.asn,
                    "as_org": new_geo.as_org,
                    "country": new_geo.country,
                    "city": new_geo.city,
                }, ensure_ascii=False),
                "ip_address": current_ip,
                "country": new_geo.country,
            }

        # --- Check 2: Impossible Travel ---
        if token_iat and new_geo.latitude is not None:
            old_geo = geoip_service.lookup(login_ip)
            if old_geo.latitude is not None:
                distance_km = _haversine(
                    old_geo.latitude, old_geo.longitude,
                    new_geo.latitude, new_geo.longitude,
                )

                elapsed_hours = (time.time() - token_iat) / 3600
                if elapsed_hours < 0.01:
                    elapsed_hours = 0.01  # tránh chia 0

                speed_kmh = distance_km / elapsed_hours

                if speed_kmh > MAX_TRAVEL_SPEED_KMH and distance_km > 100:
                    return {
                        "alert_type": "impossible_travel",
                        "severity": "critical",
                        "title": (
                            f"Impossible travel: {old_geo.city or old_geo.country}"
                            f" → {new_geo.city or new_geo.country}"
                        ),
                        "detail": json.dumps({
                            "login_ip": login_ip,
                            "login_location": f"{old_geo.city}, {old_geo.country}",
                            "current_ip": current_ip,
                            "current_location": f"{new_geo.city}, {new_geo.country}",
                            "distance_km": round(distance_km, 1),
                            "elapsed_hours": round(elapsed_hours, 2),
                            "speed_kmh": round(speed_kmh, 1),
                        }, ensure_ascii=False),
                        "ip_address": current_ip,
                        "country": new_geo.country,
                    }

        return None

    async def _handle_anomaly(self, account_id: int, anomaly: dict) -> JSONResponse:
        """
        Xử lý khi phát hiện anomaly: force logout + lưu notification + publish Redis.
        Không deactivate account tự động — admin xem xét thủ công qua notification.

        Dedup qua Redis NX: cùng account + alert_type + IP chỉ tạo 1 notification
        trong ANOMALY_COOLDOWN_TTL giây để tránh spam khi user bật VPN liên tục.
        """

        # === DEDUP CHECK: atomic SET NX — tránh spam notification ===
        should_notify = True
        if redis_service.client:
            try:
                dedup_key = (
                    f"anomaly_cooldown:{account_id}"
                    f":{anomaly['alert_type']}"
                    f":{anomaly.get('ip_address', 'unknown')}"
                )
                # SET NX: trả True nếu set thành công (key chưa tồn tại)
                acquired = await redis_service.client.set(
                    dedup_key, "1", nx=True, ex=ANOMALY_COOLDOWN_TTL
                )
                if not acquired:
                    # Đã notify gần đây → chỉ kick session, không tạo notification mới
                    should_notify = False
                    logger.debug(
                        "[IP_MONITOR] Anomaly suppressed (cooldown) — account_id=%s | type=%s | IP=%s",
                        account_id, anomaly["alert_type"], anomaly.get("ip_address"),
                    )
            except Exception as e:
                logger.warning("[IP_MONITOR] Không thể check dedup key: %s", e)
                # Nếu Redis lỗi → vẫn notify để không bỏ sót cảnh báo

        if should_notify:
            notification_id = None
            # 1. Lưu notification vào DB (wrapped để không block force-logout khi DB lỗi)
            try:
                async with SessionLocal() as db:
                    notification = AdminNotification(
                        account_id=account_id,
                        alert_type=anomaly["alert_type"],
                        severity=anomaly["severity"],
                        title=anomaly["title"],
                        detail=anomaly.get("detail"),
                        ip_address=anomaly.get("ip_address"),
                        country=anomaly.get("country"),
                    )
                    db.add(notification)
                    await db.commit()
                    await db.refresh(notification)
                    notification_id = notification.id
            except Exception as e:
                logger.error("[IP_MONITOR] Không thể lưu notification vào DB: %s", e)

            logger.warning(
                "[IP_MONITOR] Anomaly detected — account_id=%s | type=%s | IP=%s",
                account_id, anomaly["alert_type"], anomaly.get("ip_address"),
            )

            # 2. Publish lên Redis channel cho SSE (chỉ khi lưu DB thành công)
            if notification_id and redis_service.client:
                try:
                    alert_payload = json.dumps({
                        "id": notification_id,
                        "account_id": account_id,
                        "alert_type": anomaly["alert_type"],
                        "severity": anomaly["severity"],
                        "title": anomaly["title"],
                        "detail": anomaly.get("detail"),
                        "ip_address": anomaly.get("ip_address"),
                        "country": anomaly.get("country"),
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }, ensure_ascii=False)
                    await redis_service.client.publish(NOTIFICATION_CHANNEL, alert_payload)
                except Exception as e:
                    logger.warning("[IP_MONITOR] Không thể publish alert: %s", e)

        # 3. Luôn trả 401 + xóa cookie + INCR session_ver (kick vĩnh viễn, không cho dùng lại sau khi tắt VPN)
        # INCR session_ver đảm bảo: dù cookie chưa bị xóa hoặc VPN tắt, session_ver JWT sẽ không còn khớp → mọi request đều bị kick
        if redis_service.client:
            try:
                redis_key = f"session_ver:{account_id}"
                await redis_service.client.incr(redis_key)
                logger.info(
                    "[IP_MONITOR] session_ver incremented — account_id=%s (token permanently invalidated)",
                    account_id,
                )
            except Exception as e:
                logger.warning("[IP_MONITOR] Không thể INCR session_ver: %s", e)

        response = JSONResponse(
            status_code=401,
            content={
                "detail": "Phiên đăng nhập bị chấm dứt do phát hiện hoạt động bất thường.",
            },
        )
        response.delete_cookie("access_token", path="/")

        return response
