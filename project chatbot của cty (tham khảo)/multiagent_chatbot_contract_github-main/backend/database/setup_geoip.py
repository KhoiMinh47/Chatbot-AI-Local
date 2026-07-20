"""
Module GeoIP Singleton Service.

Sử dụng thư viện geoip2 + maxminddb (Mode.MEMORY) để đọc file
GeoLite2-City.mmdb và GeoLite2-ASN.mmdb vào RAM.

Tính năng:
    - Singleton Pattern: File .mmdb chỉ load vào RAM 1 lần khi khởi động.
    - Hot-reload: Kiểm tra mtime của file .mmdb, tự reload khi file thay đổi.
    - Lookup: Tra cứu IP → country, city, lat/lng, ASN, ISP, datacenter detection.
    - Thread-safe: geoip2.database.Reader an toàn cho concurrent reads.

Yêu cầu:
    - Đặt file GeoLite2-City.mmdb và GeoLite2-ASN.mmdb vào thư mục GEOIP_DIR.
    - Đăng ký tài khoản MaxMind (miễn phí) để tải GeoLite2 databases.
"""

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import geoip2.database
import maxminddb

logger = logging.getLogger(__name__)

# Thư mục chứa file .mmdb
GEOIP_DIR = Path(os.getenv("GEOIP_DIR", "database/geoip"))

# Tên file mặc định
CITY_DB_FILE = "GeoLite2-City.mmdb"
ASN_DB_FILE = "GeoLite2-ASN.mmdb"

# Interval kiểm tra hot-reload (giây) — tránh check mtime mỗi request
HOT_RELOAD_CHECK_INTERVAL = 300  # 5 phút

# Danh sách ASN thuộc các datacenter lớn và VPN providers
# Nguồn: các cloud provider và VPN provider phổ biến
DATACENTER_ASNS = frozenset({
    # Amazon AWS
    14618, 16509, 8987,
    # Google Cloud
    15169, 396982,
    # Microsoft Azure
    8075, 8068, 8069,
    # DigitalOcean
    14061,
    # Linode (Akamai)
    63949,
    # OVH
    16276,
    # Hetzner
    24940,
    # Vultr
    20473,
    # Cloudflare
    13335,
    # Oracle Cloud
    31898,
    # Alibaba Cloud
    45102,
    # Tencent Cloud
    132203,
    # Scaleway
    12876,
    # UpCloud
    202053,
    # Contabo
    40021,
    # ColoCrossing
    36352,
    # QuadraNet
    8100,
    # Choopa (Vultr parent)
    20473,
    # LeaseWeb
    60781,
    # Psychz Networks
    40676,
    # M247 (NordVPN, CyberGhost, Surfshark, ExpressVPN)
    9009,
    # DataCamp / Datacamp Limited (NordVPN datacenter)
    212238,
    # Akamai / Cogent
    174,
    # NordVPN dedicated ASN
    206728,
    # Proton AG / ProtonVPN
    62597, 56987,
    # PureVPN / GZ Systems
    35478,
    # IPVanish / StackPath
    33588,
    # Windscribe
    206092,
    # Mullvad VPN
    39351,
    # IVPN
    136787,
    # Private Internet Access / Kape Technologies
    18978, 207155,
    # TorGuard
    198605,
    # HideMyAss / Avast
    26101,
    # CyberGhost (via M247, Leaseweb, Datacamp)
    64267,
    # HostRoyale / Hostwinds
    54290, 64318,
    # GreenCloudVPS
    134835,
    # Frantech / BuyVM
    53667,
    # 1984 Hosting (Iceland)
    44925,
    # Sharktech
    27176,
    # ServerMania
    32489,
    # Tzulo
    21640,
})

# Từ khóa trong tên ASN organization → datacenter/VPN
DATACENTER_KEYWORDS = frozenset({
    "amazon", "aws", "google", "microsoft", "azure", "digitalocean",
    "linode", "akamai", "ovh", "hetzner", "vultr", "cloudflare",
    "oracle", "alibaba", "tencent", "scaleway", "upcloud", "contabo",
    "colocrossing", "quadranet", "choopa", "leaseweb", "psychz",
    "m247", "datacamp", "hosting", "datacenter", "data center",
    "server", "vps", "vpn", "proxy", "nord", "express", "surfshark",
    "mullvad", "private internet access", "cyberghost", "proton",
    "protonvpn", "purevpn", "ipvanish", "torguard", "windscribe",
    "ghostnet", "ivpn", "hideip", "hide.me", "hotspot shield",
    "tunnel", "pia vpn", "kape", "zenmate", "astrill", "strongvpn",
    "perfect privacy", "securevpn", "hidemyass", "hma", "avast",
    "buyvm", "frantech", "sharktech", "servermania",
})


@dataclass
class GeoIPResult:
    """Kết quả tra cứu GeoIP cho một IP address."""

    ip: str = ""
    country: str | None = None
    city: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    isp: str | None = None
    asn: int | None = None
    as_org: str | None = None
    is_vpn_or_datacenter: bool = False


class GeoIPService:
    """
    Singleton service tra cứu GeoIP từ file .mmdb local.

    Chiến lược:
        - Load file vào RAM bằng maxminddb.MODE_MEMORY.
        - Kiểm tra mtime mỗi HOT_RELOAD_CHECK_INTERVAL giây, reload nếu file mới.
        - Lookup trả về GeoIPResult dataclass.

    Sử dụng:
        geoip_service = GeoIPService()
        await geoip_service.initialize()   # gọi khi startup
        result = geoip_service.lookup("8.8.8.8")
    """

    def __init__(self):
        self._city_reader: geoip2.database.Reader | None = None
        self._asn_reader: geoip2.database.Reader | None = None
        self._city_mtime: float = 0
        self._asn_mtime: float = 0
        self._last_check: float = 0

    def initialize(self):
        """
        Load file .mmdb vào RAM.

        Gọi 1 lần khi app startup (sync, vì I/O file không cần async).
        Nếu file không tồn tại, log warning và tiếp tục (graceful degradation).
        """

        city_path = GEOIP_DIR / CITY_DB_FILE
        asn_path = GEOIP_DIR / ASN_DB_FILE

        if city_path.is_file():
            self._city_reader = geoip2.database.Reader(
                str(city_path), mode=maxminddb.MODE_MEMORY,
            )
            self._city_mtime = city_path.stat().st_mtime
            logger.info("[GEOIP] Loaded %s (%.1f MB)", CITY_DB_FILE,
                        city_path.stat().st_size / 1024 / 1024)
        else:
            logger.warning("[GEOIP] File không tồn tại: %s", city_path)

        if asn_path.is_file():
            self._asn_reader = geoip2.database.Reader(
                str(asn_path), mode=maxminddb.MODE_MEMORY,
            )
            self._asn_mtime = asn_path.stat().st_mtime
            logger.info("[GEOIP] Loaded %s (%.1f MB)", ASN_DB_FILE,
                        asn_path.stat().st_size / 1024 / 1024)
        else:
            logger.warning("[GEOIP] File không tồn tại: %s", asn_path)

        self._last_check = time.monotonic()

    def _check_hot_reload(self):
        """
        Kiểm tra và hot-reload file .mmdb nếu mtime thay đổi.

        Chỉ kiểm tra mỗi HOT_RELOAD_CHECK_INTERVAL giây để tránh
        gọi stat() mỗi request.
        """

        now = time.monotonic()
        if now - self._last_check < HOT_RELOAD_CHECK_INTERVAL:
            return

        self._last_check = now

        city_path = GEOIP_DIR / CITY_DB_FILE
        asn_path = GEOIP_DIR / ASN_DB_FILE

        if city_path.is_file():
            mtime = city_path.stat().st_mtime
            if mtime != self._city_mtime:
                old_reader = self._city_reader
                self._city_reader = geoip2.database.Reader(
                    str(city_path), mode=maxminddb.MODE_MEMORY,
                )
                self._city_mtime = mtime
                if old_reader:
                    old_reader.close()
                logger.info("[GEOIP] Hot-reloaded %s", CITY_DB_FILE)

        if asn_path.is_file():
            mtime = asn_path.stat().st_mtime
            if mtime != self._asn_mtime:
                old_reader = self._asn_reader
                self._asn_reader = geoip2.database.Reader(
                    str(asn_path), mode=maxminddb.MODE_MEMORY,
                )
                self._asn_mtime = mtime
                if old_reader:
                    old_reader.close()
                logger.info("[GEOIP] Hot-reloaded %s", ASN_DB_FILE)

    def lookup(self, ip: str) -> GeoIPResult:
        """
        Tra cứu thông tin GeoIP + ASN cho một IP address.

        Input:
            ip (str): IPv4 hoặc IPv6 address.

        Output:
            GeoIPResult: Kết quả tra cứu (fields có thể None nếu DB thiếu).
        """

        self._check_hot_reload()

        result = GeoIPResult(ip=ip)

        # --- City lookup ---
        if self._city_reader:
            try:
                city_resp = self._city_reader.city(ip)
                result.country = city_resp.country.iso_code
                result.city = city_resp.city.name
                result.latitude = city_resp.location.latitude
                result.longitude = city_resp.location.longitude
            except Exception:
                pass  # IP không có trong DB → giữ None

        # --- ASN lookup ---
        if self._asn_reader:
            try:
                asn_resp = self._asn_reader.asn(ip)
                result.asn = asn_resp.autonomous_system_number
                result.as_org = asn_resp.autonomous_system_organization
                result.isp = asn_resp.autonomous_system_organization
            except Exception:
                pass

        # --- Phát hiện VPN/Datacenter ---
        result.is_vpn_or_datacenter = self._is_datacenter(
            result.asn, result.as_org,
        )

        return result

    @staticmethod
    def _is_datacenter(asn: int | None, as_org: str | None) -> bool:
        """
        Kiểm tra ASN có thuộc datacenter/VPN không.

        Thuật toán:
            1. Check ASN number trong danh sách DATACENTER_ASNS.
            2. Check tên organization chứa từ khóa DATACENTER_KEYWORDS.

        Input:
            asn (int | None): ASN number.
            as_org (str | None): Tên tổ chức ASN.

        Output:
            bool: True nếu là datacenter/VPN.
        """

        if asn and asn in DATACENTER_ASNS:
            return True

        if as_org:
            org_lower = as_org.lower()
            for keyword in DATACENTER_KEYWORDS:
                if keyword in org_lower:
                    return True

        return False

    def close(self):
        """Giải phóng tài nguyên reader."""

        if self._city_reader:
            self._city_reader.close()
            self._city_reader = None
        if self._asn_reader:
            self._asn_reader.close()
            self._asn_reader = None

        logger.info("[GEOIP] Readers closed")


# Singleton instance
geoip_service = GeoIPService()
