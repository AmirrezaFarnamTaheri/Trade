"""Probe the venue one layer at a time and print the first layer that fails. Standard library only.

Run: `python scripts/venue_probe.py`. Exit 0 only when a public REST call returns HTTP 200.
"""
from __future__ import annotations

import ipaddress
import socket
import ssl
import sys

HOST = "api.wallex.ir"
# 198.18.0.0/15 is reserved for benchmarking; a local VPN in fake-IP mode answers DNS from it.
FAKE_IP = ipaddress.ip_network("198.18.0.0/15")


def probe(host: str = HOST, timeout: float = 10) -> tuple[str, str]:
    """Return (layer, detail); layer is OK or the first of DNS, TCP, TLS, HTTP that failed."""
    try:
        address = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)[0][4][0]
    except OSError as error:
        return "DNS", repr(error)
    note = f"{address} (fake-IP range: a local VPN or TUN proxy intercepts this host)" if ipaddress.ip_address(address) in FAKE_IP else address
    try:
        raw = socket.create_connection((address, 443), timeout)
    except OSError as error:
        return "TCP", f"{note}: {error!r}"
    with raw:
        try:
            tls = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
        except OSError as error:
            return "TLS", f"{note}: {error!r}"
        try:
            tls.sendall(f"GET /v1/markets HTTP/1.1\r\nHost: {host}\r\nUser-Agent: TradingGYM-probe\r\nConnection: close\r\n\r\n".encode())
            status = tls.recv(64).split(b"\r\n")[0].decode("ascii", "replace")
        except OSError as error:
            return "HTTP", f"{note}: {error!r}"
    return ("OK" if " 200" in status else "HTTP"), f"{note}: {status}"


if __name__ == "__main__":
    layer, detail = probe()
    print(layer, detail)
    sys.exit(0 if layer == "OK" else 1)
