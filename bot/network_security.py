"""Fail-closed network address validation for future media workers.

DNS validation alone is NOT sufficient against rebinding: every connection must
also pin the validated IP and revalidate redirects. Downloads remain disabled.
"""
import ipaddress
import socket
import re
from urllib.parse import urlsplit


class UnsafeNetworkTarget(ValueError):
    pass


def validate_public_https_target(url: str, *, allowed_hosts: set[str] | None = None) -> tuple[str, ...]:
    """Validate literal URL and currently resolved public addresses.

    The caller must pin these addresses for the actual connection; checking
    DNS here and reconnecting by hostname would be vulnerable to DNS rebinding.
    """
    if not isinstance(url, str) or len(url) > 2048 or any(
        ord(ch) < 33 or ord(ch) == 127 for ch in url
    ):
        raise UnsafeNetworkTarget("Некорректный URL")
    try:
        parts = urlsplit(url)
        host = parts.hostname
        if (
            parts.scheme != "https" or not host or not host.isascii()
            or parts.username or parts.password or parts.fragment
            or parts.port not in (None, 443)
            or chr(92) in url or "%" in parts.netloc or "@" in parts.netloc
            or not parts.path.startswith("/")
        ):
            raise UnsafeNetworkTarget("Недопустимый HTTPS-адрес")
        if (not re.fullmatch(r"[A-Za-z0-9-]+(?:\\.[A-Za-z0-9-]+)+", host)
                or any(label.startswith("-") or label.endswith("-") or len(label) > 63
                       for label in host.split("."))):
            raise UnsafeNetworkTarget("Недопустимое доменное имя")
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
            if (not address.is_global or
                    (isinstance(address, ipaddress.IPv6Address) and
                     address.ipv4_mapped is not None and
                     not address.ipv4_mapped.is_global)):
                raise UnsafeNetworkTarget("Локальный или зарезервированный IP")
            addresses.add(str(address))
        return tuple(sorted(addresses))
    except (ValueError, OSError, UnicodeError) as exc:
        if isinstance(exc, UnsafeNetworkTarget):
            raise
        raise UnsafeNetworkTarget("Невозможно безопасно проверить адрес") from exc


def validate_redirect_chain(urls: list[str], *, allowed_hosts: set[str] | None = None,
                            max_redirects: int = 5) -> list[tuple[str, ...]]:
    """Validate every hop; do not automatically trust redirect destinations.

    This policy does not perform HTTP requests or pin IPs. A future transport
    must enforce the policy on actual socket connections.
    """
    if not urls or len(urls) > max_redirects + 1:
        raise UnsafeNetworkTarget("Недопустимое число перенаправлений")
    return [
        validate_public_https_target(url, allowed_hosts=allowed_hosts)
        for url in urls
    ]
