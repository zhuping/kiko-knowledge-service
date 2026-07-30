from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from app.core.config import settings
from app.core.errors import ApiError
from app.models import ClientApp


def validate_media_urls(urls: list[str], client_app: ClientApp) -> None:
    allowed = {host.lower() for host in (client_app.allowed_media_hosts_json or [])}
    if settings.configured_media_hosts:
        allowed &= settings.configured_media_hosts
    for value in urls:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not host or parsed.username or parsed.password:
            raise ApiError(400, "MEDIA_NOT_ALLOWED", "媒体地址必须是 HTTPS")
        if parsed.port not in {None, 443}:
            raise ApiError(400, "MEDIA_NOT_ALLOWED", "媒体地址端口不允许")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if (
            host == "localhost"
            or address
            and (
                address.is_private
                or address.is_loopback
                or address.is_link_local
                or address.is_reserved
            )
        ):
            raise ApiError(400, "MEDIA_NOT_ALLOWED", "媒体地址不允许访问内网")
        if host not in allowed:
            raise ApiError(400, "MEDIA_NOT_ALLOWED", "媒体地址不在调用方白名单")
