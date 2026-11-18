#!/usr/bin/env python3
"""RGB Gateway - the secure front door for OpenRGB on your PC.

OpenRGB's SDK server has NO password and NO encryption, so it must never be reachable
from the Wi-Fi.  This gateway is what the phone talks to instead:

  phone --TLS (pinned cert) + per-device secret--> gateway --localhost--> OpenRGB (127.0.0.1:6742)

Commands:
  python rgb_gateway.py init                 one-time: create the certificate
  python rgb_gateway.py add-device NAME      create a pairing code for one phone
  python rgb_gateway.py list                 show paired devices / settings
  python rgb_gateway.py revoke NAME          remove a phone (takes effect immediately)
  python rgb_gateway.py allow-ip IP          optional: ONLY accept these phone IPs
  python rgb_gateway.py remove-ip IP
  python rgb_gateway.py run                  start the gateway

Needs:  pip install cryptography   (only for `init`)
"""
import argparse
import hashlib
import hmac
import ipaddress
import json
import logging
import logging.handlers
import os
import re
import secrets
import select
import socket
import ssl
import subprocess
import sys
import threading
import time

MAGIC = b"RGBP1"
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,24}$")
AUTH_TIMEOUT = 6.0
IDLE_TIMEOUT = 1800.0
FAIL_FREE = 5
FAIL_BASE = 60
FAIL_MAX = 3600

DEFAULT_CONFIG = {
    "listen_host": "0.0.0.0",
    "listen_port": 6743,
    "openrgb_host": "127.0.0.1",
    "openrgb_port": 6742,
    "max_sessions": 4,
    "trusted_ips": [],
}


def data_dir():
    d = os.environ.get("RGB_GATEWAY_DIR")
    if d:
        return d
    if os.name == "nt":
        return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "RGBGateway")
    return os.path.join(os.path.expanduser("~"), ".rgb_gateway")


def path(name):
    return os.path.join(data_dir(), name)


def restrict(p):
    """Owner-only permissions."""
    try:
        if os.name == "nt":
            user = os.environ.get("USERNAME")
            if user:
                subprocess.run(["icacls", p, "/inheritance:r", "/grant:r", "%s:F" % user],
                               capture_output=True, check=False)
        else:
            os.chmod(p, 0o600)
    except OSError:
        pass


def write_private(p, data, mode="w"):
    tmp = p + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, mode) as f:
        f.write(data)
    os.replace(tmp, p)
    restrict(p)


def load_json(name, default):
    try:
        with open(path(name), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default() if callable(default) else default


def save_json(name, obj):
    write_private(path(name), json.dumps(obj, indent=2))


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(load_json("config.json", {}))
    return cfg


def fingerprint_of_der(der):
    return hashlib.sha256(der).hexdigest()[:32]


def cert_fingerprint():
    with open(path("cert.pem"), "r") as f:
        der = ssl.PEM_cert_to_DER_cert(f.read())
    return fingerprint_of_der(der)


# -------------------------------------------------------------- networking ---
def is_lan_ip(text):
    try:
        ip = ipaddress.ip_address(text.split("%")[0])
    except ValueError:
        return False
    if ip.is_multicast or ip.is_unspecified:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local


class Throttle:
    """Per-source-IP lockout after repeated failed authentication."""

    def __init__(self, clock=time.time):
        self.clock = clock
        self.lock = threading.Lock()
        self.table = {}

    def blocked(self, ip):
        with self.lock:
            e = self.table.get(ip)
            if not e:
                return 0
            left = e["until"] - self.clock()
            return int(left) + 1 if left > 0 else 0

    def failure(self, ip):
        with self.lock:
            if len(self.table) > 2048:
                self.table.clear()
            e = self.table.setdefault(ip, {"fails": 0, "until": 0.0})
            e["fails"] += 1
            if e["fails"] >= FAIL_FREE:
                e["until"] = self.clock() + min(FAIL_BASE * 2 ** (e["fails"] - FAIL_FREE), FAIL_MAX)
            return e["fails"]

    def success(self, ip):
        with self.lock:
            self.table.pop(ip, None)


def readline(sock, limit=80):
    buf = b""
    while len(buf) < limit:
        ch = sock.recv(1)
        if not ch:
            break
        buf += ch
        if ch == b"\n":
            return buf.strip()
    return None            # too long / closed


def pipe(a, b, idle=IDLE_TIMEOUT):
    try:
        while True:
            r, _, _ = select.select([a, b], [], [], idle)
            if not r:
                return
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


def check_device(name, secret):
    """Constant-time-ish check against devices.json (re-read each time so `revoke` is instant)."""
    devices = load_json("devices.json", {})
    entry = devices.get(name) if NAME_RE.match(name or "") else None
    stored = entry.get("sha256", "") if isinstance(entry, dict) else "0" * 64
    calc = hashlib.sha256((secret or "").encode()).hexdigest()
    return bool(entry) and hmac.compare_digest(calc, stored)


class Gateway:
    def __init__(self, cfg, throttle=None, log=None):
        self.cfg = cfg
        self.throttle = throttle or Throttle()
        self.log = log or logging.getLogger("rgb_gateway")
        self.sessions = threading.BoundedSemaphore(int(cfg["max_sessions"]))
        self.handshakes = threading.BoundedSemaphore(32)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(path("cert.pem"), path("key.pem"))
        self.ctx = ctx
        self.stop = threading.Event()
        self.sock = None

    def allowed_ip(self, ip):
        trusted = self.cfg.get("trusted_ips") or []
        if trusted:
            return ip in trusted
        return is_lan_ip(ip)

    def serve(self, ready=None):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((self.cfg["listen_host"], int(self.cfg["listen_port"])))
        s.listen(16)
        s.settimeout(1.0)
        self.sock = s
        self.log.info("Gateway listening on %s:%s", *s.getsockname())
        if ready:
            ready.set()
        while not self.stop.is_set():
            try:
                conn, addr = s.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            if not self.handshakes.acquire(blocking=False):
                conn.close()
                continue
            threading.Thread(target=self._handle, args=(conn, addr[0]), daemon=True).start()
        s.close()

    def shutdown(self):
        self.stop.set()

    def _handle(self, conn, ip):
        try:
            self._session(conn, ip)
        except Exception as e:                      # never let one client kill the gateway
            self.log.debug("session error from %s: %r", ip, e)
        finally:
            try:
                conn.close()
            except OSError:
                pass
            self.handshakes.release()

    def _session(self, conn, ip):
        if not self.allowed_ip(ip):
            self.log.warning("REJECT %s (not a trusted local address)", ip)
            return
        conn.settimeout(AUTH_TIMEOUT)
        try:
            tls = self.ctx.wrap_socket(conn, server_side=True)
        except (ssl.SSLError, OSError):
            return
        try:
            # read the whole hello first (closing with unread data would reset the connection
            # and the client would never see our reply)
            magic, name, secret = readline(tls), readline(tls), readline(tls)
            wait = self.throttle.blocked(ip)
            if wait:
                tls.sendall(b"LOCKED\n")
                self.log.warning("LOCKED %s for %ss more", ip, wait)
                return
            if magic != MAGIC or name is None or secret is None:
                self.throttle.failure(ip)
                self.log.warning("BAD HELLO from %s", ip)
                return
            name_s, secret_s = name.decode("ascii", "ignore"), secret.decode("ascii", "ignore")
            if not check_device(name_s, secret_s):
                n = self.throttle.failure(ip)
                tls.sendall(b"NO\n")
                self.log.warning("AUTH FAIL from %s (device '%s', fail #%d)", ip, name_s[:24], n)
                return
            self.throttle.success(ip)
            if not self.sessions.acquire(blocking=False):
                tls.sendall(b"NO\n")
                return
            try:
                try:
                    up = socket.create_connection(
                        (self.cfg["openrgb_host"], int(self.cfg["openrgb_port"])), timeout=3)
                except OSError:
                    tls.sendall(b"DOWN\n")
                    self.log.warning("OpenRGB server not reachable")
                    return
                tls.sendall(b"OK\n")
                tls.settimeout(None)
                self.log.info("SESSION open: device '%s' from %s", name_s, ip)
                pipe(tls, up)
                self.log.info("SESSION closed: device '%s'", name_s)
            finally:
                self.sessions.release()
        finally:
            try:
                tls.close()
            except OSError:
                pass


# ------------------------------------------------------------------- CLI ---
def cmd_init(args):
    os.makedirs(data_dir(), exist_ok=True)
    if os.path.exists(path("cert.pem")) and not args.force:
        print("Certificate already exists. Fingerprint:", cert_fingerprint())
        print("(use --force only if you want to re-pair every phone)")
        return 0
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
        import datetime
    except ImportError:
        print("ERROR: run  pip install cryptography  first")
        return 1
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "RGB Gateway")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=3650))
            .sign(key, hashes.SHA256()))
    write_private(path("key.pem"), key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()).decode())
    write_private(path("cert.pem"), cert.public_bytes(serialization.Encoding.PEM).decode())
    if not os.path.exists(path("config.json")):
        save_json("config.json", DEFAULT_CONFIG)
    if not os.path.exists(path("devices.json")):
        save_json("devices.json", {})
    print("Certificate created.  Fingerprint:", cert_fingerprint())
    print("Data folder:", data_dir())
    print("Next:  python rgb_gateway.py add-device myphone")
    return 0


def cmd_add(args):
    if not os.path.exists(path("cert.pem")):
        print("Run  python rgb_gateway.py init  first")
        return 1
    name = args.name
    if not NAME_RE.match(name):
        print("Name: 1-24 letters/digits/-/_ only")
        return 1
    devices = load_json("devices.json", {})
    if name in devices:
        print("A device named '%s' already exists. Revoke it first." % name)
        return 1
    import base64
    secret = base64.b32encode(secrets.token_bytes(20)).decode()          # 32 chars, 160 bits
    devices[name] = {"sha256": hashlib.sha256(secret.encode()).hexdigest(),
                     "created": int(time.time())}
    save_json("devices.json", devices)
    code = "RGB1.%s.%s.%s" % (cert_fingerprint(), name, secret)
    print("\nPairing code for '%s' (shown ONCE, the gateway stores only a hash):\n" % name)
    print("  " + code + "\n")
    print("Type/paste it into the phone app. Delete any chat/note you copied it into.")
    return 0


def cmd_list(_args):
    cfg = load_config()
    devices = load_json("devices.json", {})
    print("Listening:", cfg["listen_host"], cfg["listen_port"], "-> OpenRGB",
          cfg["openrgb_host"], cfg["openrgb_port"])
    print("Trusted IPs:", cfg["trusted_ips"] or "(any private LAN address)")
    print("Paired devices:", ", ".join(devices) or "(none)")
    return 0


def cmd_revoke(args):
    devices = load_json("devices.json", {})
    if devices.pop(args.name, None) is None:
        print("No such device")
        return 1
    save_json("devices.json", devices)
    print("Revoked '%s'. It can no longer connect." % args.name)
    return 0


def cmd_ip(args, add):
    try:
        ip = str(ipaddress.ip_address(args.ip))
    except ValueError:
        print("Not a valid IP")
        return 1
    cfg = load_json("config.json", dict(DEFAULT_CONFIG))
    cur = [x for x in cfg.get("trusted_ips", []) if x != ip]
    if add:
        if not is_lan_ip(ip):
            print("Only local-network addresses allowed")
            return 1
        cur.append(ip)
    cfg["trusted_ips"] = cur
    save_json("config.json", cfg)
    print("Trusted IPs now:", cur or "(any private LAN address)")
    return 0


def cmd_run(_args):
    if not os.path.exists(path("cert.pem")):
        print("Run  python rgb_gateway.py init  first")
        return 1
    log = logging.getLogger("rgb_gateway")
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = logging.handlers.RotatingFileHandler(path("gateway.log"), maxBytes=500_000, backupCount=3)
    sh = logging.StreamHandler()
    for h in (fh, sh):
        h.setFormatter(fmt)
        log.addHandler(h)
    cfg = load_config()
    gw = Gateway(cfg, log=log)
    print("RGB Gateway is running. Keep this window open. Ctrl+C to stop.")
    print("Certificate fingerprint:", cert_fingerprint())
    try:
        gw.serve()
    except KeyboardInterrupt:
        gw.shutdown()
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Secure gateway between the phone app and OpenRGB")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("init"); s.add_argument("--force", action="store_true"); s.set_defaults(f=cmd_init)
    s = sub.add_parser("add-device"); s.add_argument("name"); s.set_defaults(f=cmd_add)
    s = sub.add_parser("list"); s.set_defaults(f=cmd_list)
    s = sub.add_parser("revoke"); s.add_argument("name"); s.set_defaults(f=cmd_revoke)
    s = sub.add_parser("allow-ip"); s.add_argument("ip"); s.set_defaults(f=lambda a: cmd_ip(a, True))
    s = sub.add_parser("remove-ip"); s.add_argument("ip"); s.set_defaults(f=lambda a: cmd_ip(a, False))
    s = sub.add_parser("run"); s.set_defaults(f=cmd_run)
    args = p.parse_args(argv)
    return args.f(args)


if __name__ == "__main__":
    sys.exit(main())
