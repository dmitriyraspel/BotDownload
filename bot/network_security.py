"""Fail-closed network address validation for future media workers.

DNS validation alone is NOT sufficient against rebinding: every connection must
also pin the validated IP and revalidate redirects. Downloads remain disabled.
"""
import ipaddress
import socket
from urllib.parse import urlsplit


class UnsafeNetworkTarget(ValueError):
    pass


def validate_public_https_target(url: str, *, allowed_hosts: set[str] | None = None) -> tuple[str, ...]:
    """Validate literal URL and currently resolved public addresses.

    The caller must pin these addresses for the actual connection; checking
    DNS here and reconnecting by hostname would be vulnerable to DNS rebinding.
    """
    if not isinstance(url, str) or len(url) > 2048 or any(
        ord(ch) < 33 or ch == "\\x7f" for ch in url
    ):
        raise UnsafeNetworkTarget("Некорректный URL")
    try:
        parts = urlsplit(url)
        host = parts.hostname
        if (
            parts.scheme != "https" or not host or not host.isascii()
            or parts.username or parts.password or parts.fragment
            or parts.port not in (None, 443)
            or "\\\\" in url or "%" in parts.netloc or "@" in parts.netloc
            or not parts.path.startswith("/")
        ):
            raise UnsafeNetworkTarget("Недопустимый HTTPS-адрес")
        if allowed_hosts is not None and host.lower() not in allowed_hosts:
            raise UnsafeNetworkTarget("Домен не разрешён")
        # Block literal IP hosts; approved providers use DNS hostnames.
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise UnsafeNetworkTarget("IP-адрес вместо домена")
        results = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        if not results:
            raise UnsafeNetworkTarget("DNS не вернул адреса")
        addresses = set()
        for result in results:
            address = ipaddress.ip_address(result[4][0])
            if not address.is_global:
                raise UnsafeNetworkTarget("Локальный или зарезервированный IP")
            addresses.add(str(address))
        return tuple(sorted(addresses))
    except (ValueError, OSError, UnicodeError) as exc:
        if isinstance(exc, UnsafeNetworkTarget):
            raise
        raise UnsafeNetworkTarget("Невозможно безопасно проверить адрес") from exc
