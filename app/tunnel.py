"""Encrypted + authenticated tunnel from the phone to the PC gateway.

OpenRGB's SDK server speaks plain, unauthenticated TCP.  Instead of exposing it on
the Wi-Fi, the PC runs `rgb_gateway.py` (TLS + per-device secret).  This module:

  1. checks the PC address is a private LAN address (never the public internet),
  2. opens TLS to the gateway and PINS its certificate fingerprint (from the pairing code),
  3. authenticates with the per-device secret,
  4. opens a single-use listener on 127.0.0.1:<random port> that the OpenRGB client
     connects to; bytes are piped through the TLS connection.

Pure Python (no Kivy) so it can be tested on a PC.
"""
import hashlib
import hmac
import ipaddress
import select
import socket
import ssl
import threading

MAGIC = b"RGBP1"
CONNECT_TIMEOUT = 6.0
AUTH_TIMEOUT = 6.0
LOCAL_ACCEPT_TIMEOUT = 10.0
IDLE_TIMEOUT = 1800.0


class TunnelError(Exception):
    """Message is meant to be shown to the user."""


def is_lan_ip(text):
    ip = ipaddress.ip_address(text)
    if ip.is_multicast or ip.is_unspecified:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local


def resolve_lan(host):
    """Resolve host and make sure EVERY address is on the local network."""
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError:
        raise TunnelError("PC ka address nahi mila: %s" % host)
    addrs = []
    for fam, _t, _p, _c, sa in infos:
        a = sa[0].split("%")[0]
        if not is_lan_ip(a):
            raise TunnelError("Ye address ghar ke network ka nahi hai (public IP mana hai)")
        if fam == socket.AF_INET:
            addrs.append(a)
    if not addrs:
        raise TunnelError("IPv4 address chahiye (jaise 192.168.1.8)")
    return addrs[0]


def _readline(sock, limit=16):
    buf = b""
    while len(buf) < limit:
        ch = sock.recv(1)
        if not ch:
            break
        buf += ch
        if ch == b"\n":
            break
    return buf.strip()


def connect_and_auth(host, port, pair, timeout=CONNECT_TIMEOUT):
    """TLS connect, verify pinned certificate, authenticate. Returns a connected SSLSocket."""
    ip = resolve_lan(host)
    try:
        raw = socket.create_connection((ip, port), timeout=timeout)
    except OSError:
        raise TunnelError("Gateway se connect nahi hua. PC par RGB Gateway chal raha hai? "
                          "(IP/port/firewall check karo)")
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.check_hostname = False          # self-signed: we pin the fingerprint instead
    ctx.verify_mode = ssl.CERT_NONE
    try:
        s = ctx.wrap_socket(raw)
    except (ssl.SSLError, OSError):
        raw.close()
        raise TunnelError("Secure connection fail hua (ye RGB Gateway nahi lagta)")
    try:
        der = s.getpeercert(binary_form=True) or b""
        fp = hashlib.sha256(der).hexdigest()[:32]
        if not hmac.compare_digest(fp, pair["fp"]):
            raise TunnelError("Gateway ka certificate pairing code se match nahi karta! "
                              "Koi aur device PC ban raha ho sakta hai. Naya pairing code lo.")
        s.settimeout(AUTH_TIMEOUT)
        s.sendall(MAGIC + b"\n" + pair["name"].encode() + b"\n" + pair["secret"].encode() + b"\n")
        reply = _readline(s)
        if reply == b"OK":
            s.settimeout(None)
            return s
        if reply == b"LOCKED":
            raise TunnelError("Gateway ne is device ko kuch der ke liye rok diya (bahut galat try)")
        if reply == b"DOWN":
            raise TunnelError("OpenRGB server band hai. PC par OpenRGB mein SDK Server start karo")
        raise TunnelError("Pairing code galat ya revoke ho chuka hai")
    except TunnelError:
        s.close()
        raise
    except (OSError, ssl.SSLError):
        s.close()
        raise TunnelError("Gateway se jawab nahi aaya")


def pipe(a, b, idle=IDLE_TIMEOUT):
    """Single-threaded bidirectional copy between two (SSL) sockets until either closes."""
    try:
        while True:
            r, _, _ = select.select([a, b], [], [], idle)
            if not r:
                return                                  # idle timeout
            for s in r:
                dst = b if s is a else a
                data = s.recv(65536)
                if not data:
                    return
                dst.sendall(data)
                while isinstance(s, ssl.SSLSocket) and s.pending():
                    more = s.recv(s.pending())
                    if not more:
                        return
                    dst.sendall(more)
    except (OSError, ssl.SSLError, ValueError):
        return
    finally:
        for s in (a, b):
            try:
                s.close()
            except OSError:
                pass


def open_tunnel(host, port, pair):
    """Authenticate to the gateway, then return the local 127.0.0.1 port to connect OpenRGB to.

    The local listener accepts exactly ONE connection and is then closed, so other apps on
    the phone cannot piggy-back on it later; the port is random each time.
    """
    remote = connect_and_auth(host, port, pair)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(LOCAL_ACCEPT_TIMEOUT)
    except OSError:
        remote.close()
        listener.close()
        raise TunnelError("Phone par local port nahi khul paya")
    local_port = listener.getsockname()[1]

    def serve():
        try:
            conn, peer = listener.accept()
        except OSError:
            remote.close()
            return
        finally:
            listener.close()
        if peer[0] != "127.0.0.1":
            conn.close()
            remote.close()
            return
        pipe(conn, remote)

    threading.Thread(target=serve, daemon=True).start()
    return local_port
