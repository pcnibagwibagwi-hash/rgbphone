"""PIN / recovery-code / lockout / pairing logic for RGB Phone.

Pure Python (no Kivy) so it can be unit-tested on a PC.

Threat model: someone who borrows your unlocked-by-Android phone and opens the app,
or malware/people who can read the app's files.  Android's own screen lock is the
outer layer; this module is the inner "app lock".
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time

ITERATIONS = 600_000          # PBKDF2-HMAC-SHA256 (OWASP 2023 minimum for SHA-256)
LEGACY_ITERATIONS = 100_000   # config files written by app v1.x
MIN_PIN_LEN = 6
MAX_PIN_LEN = 12
FREE_ATTEMPTS = 5             # the 5th wrong try starts the lockout
LOCK_BASE = 30                # seconds
LOCK_MAX = 3600               # 1 hour cap
RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no I, O, 0, 1
RECOVERY_LEN = 20             # 20 chars * 5 bits = 100 bits
DEFAULT_GATEWAY_PORT = 6743

_WEAK_PINS = {
    "123456", "654321", "111111", "000000", "121212", "112233", "123123",
    "123321", "159753", "696969", "202020", "010101", "123456789", "12345678",
    "1234567", "0123456", "1234567890", "987654", "7777777", "88888888",
}


# ----------------------------------------------------------------- hashing ---
def hash_secret(secret, iterations=ITERATIONS):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"),
                                 bytes.fromhex(salt), iterations).hex()
    return {"salt": salt, "iter": iterations, "hash": digest}


def verify_secret(record, secret):
    """Constant-time check of `secret` against a hash_secret() record."""
    try:
        iterations = int(record.get("iter", LEGACY_ITERATIONS))
        if not (10_000 <= iterations <= 5_000_000):
            return False
        digest = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"),
                                     bytes.fromhex(record["salt"]), iterations).hex()
        return hmac.compare_digest(digest, record["hash"])
    except (KeyError, ValueError, TypeError, AttributeError):
        return False


# ------------------------------------------------------------- PIN policy ---
def validate_pin(pin):
    """Return None if the PIN is acceptable, otherwise a short message."""
    if not isinstance(pin, str) or not pin.isascii() or not pin.isdigit():
        return "PIN sirf digits ka ho"
    if len(pin) < MIN_PIN_LEN:
        return "PIN kam se kam %d digits ka ho" % MIN_PIN_LEN
    if len(pin) > MAX_PIN_LEN:
        return "PIN zyada se zyada %d digits ka ho" % MAX_PIN_LEN
    if len(set(pin)) == 1:
        return "PIN mein sab digits same nahi ho sakte"
    diffs = {int(b) - int(a) for a, b in zip(pin, pin[1:])}
    if diffs in ({1}, {-1}):
        return "PIN 123456 jaisa seedha sequence nahi ho sakta"
    if pin in _WEAK_PINS:
        return "Ye PIN bahut aam hai, koi aur chuno"
    return None


# ------------------------------------------------------------ config file ---
def load_cfg(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        if not isinstance(cfg, dict):
            return {}
    except Exception:
        return {}
    return migrate(cfg)


_SAVE_LOCK = threading.Lock()   # the UI thread and the connection thread can both save


def save_cfg(path, cfg):
    """Atomic write, owner-only permissions (safe to call from several threads)."""
    with _SAVE_LOCK:
        folder = os.path.dirname(path)
        os.makedirs(folder, exist_ok=True)
        tmp = path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def migrate(cfg):
    """Upgrade a config written by app v1 (single weak hash, no pairing)."""
    if "pin" not in cfg and "hash" in cfg and "salt" in cfg:
        cfg["pin"] = {"salt": cfg.pop("salt"), "iter": LEGACY_ITERATIONS,
                      "hash": cfg.pop("hash")}
    cfg.setdefault("fails", 0)
    cfg.setdefault("lock_until", 0.0)
    cfg.setdefault("port", DEFAULT_GATEWAY_PORT)
    cfg["v"] = 2
    return cfg


def is_configured(cfg):
    return bool(cfg.get("pin"))


def needs_pairing(cfg):
    return not cfg.get("pair") or not cfg.get("host")


# --------------------------------------------------------------- lockout ---
def lock_remaining(cfg, now=None):
    now = time.time() if now is None else now
    left = float(cfg.get("lock_until", 0.0)) - now
    return int(min(max(left, 0.0), LOCK_MAX) + 0.999) if left > 0 else 0


def attempts_left(cfg):
    return max(0, FREE_ATTEMPTS - int(cfg.get("fails", 0)))


def _register_failure(cfg, now):
    cfg["fails"] = int(cfg.get("fails", 0)) + 1
    if cfg["fails"] >= FREE_ATTEMPTS:
        delay = min(LOCK_BASE * (2 ** (cfg["fails"] - FREE_ATTEMPTS)), LOCK_MAX)
        cfg["lock_until"] = now + delay


def guarded_check(cfg, path, record, candidate, now=None):
    """Check `candidate` against `record` with brute-force protection.

    The attempt is counted and saved BEFORE it is verified, so killing the app
    mid-attempt does not give a free guess.  Returns (ok, message).
    PIN and recovery code share one counter.
    """
    now = time.time() if now is None else now
    left = lock_remaining(cfg, now)
    if left:
        return False, "Bahut galat try. %d second baad dobara try karo" % left
    _register_failure(cfg, now)
    save_cfg(path, cfg)
    if record and verify_secret(record, candidate):
        cfg["fails"] = 0
        cfg["lock_until"] = 0.0
        save_cfg(path, cfg)
        return True, ""
    left = lock_remaining(cfg, now)
    if left:
        return False, "Galat. App %d second ke liye lock ho gayi" % left
    return False, "Galat. %d try baaki" % attempts_left(cfg)


# --------------------------------------------------------------- recovery ---
def new_recovery_code():
    return "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(RECOVERY_LEN))


def format_recovery(code):
    return "-".join(code[i:i + 4] for i in range(0, len(code), 4))


def normalize_recovery(text):
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


# ------------------------------------------------------- high-level ops ---
def create_pin(cfg, path, pin):
    """Set a (new) PIN and a fresh recovery code. Returns the recovery code (show once)."""
    problem = validate_pin(pin)
    if problem:
        raise ValueError(problem)
    code = new_recovery_code()
    cfg["pin"] = hash_secret(pin)
    cfg["recovery"] = hash_secret(code)
    cfg["fails"] = 0
    cfg["lock_until"] = 0.0
    save_cfg(path, cfg)
    return code


def unlock(cfg, path, pin, now=None):
    ok, msg = guarded_check(cfg, path, cfg.get("pin"), pin, now)
    if ok and int(cfg["pin"].get("iter", LEGACY_ITERATIONS)) < ITERATIONS:
        cfg["pin"] = hash_secret(pin)      # silently upgrade an old weak hash
        save_cfg(path, cfg)
    return ok, msg


def change_pin(cfg, path, current_pin, new_pin, now=None):
    """Changing the PIN REQUIRES the current PIN."""
    problem = validate_pin(new_pin)
    if problem:
        return False, problem, None
    ok, msg = guarded_check(cfg, path, cfg.get("pin"), current_pin, now)
    if not ok:
        return False, msg, None
    cfg["pin"] = hash_secret(new_pin)
    save_cfg(path, cfg)
    return True, "", None


def reset_pin_with_recovery(cfg, path, recovery_text, new_pin, now=None):
    """Forgot-PIN path: needs the recovery code that was shown at setup.
    Returns (ok, message, new_recovery_code)."""
    problem = validate_pin(new_pin)
    if problem:
        return False, problem, None
    if not cfg.get("recovery"):
        return False, "Recovery code set nahi hai. Android Settings se app data clear karo", None
    ok, msg = guarded_check(cfg, path, cfg["recovery"], normalize_recovery(recovery_text), now)
    if not ok:
        return False, msg, None
    code = create_pin(cfg, path, new_pin)   # also rotates the recovery code
    return True, "", code


def rotate_recovery(cfg, path, current_pin, now=None):
    """Make a new recovery code (old one stops working). Needs the current PIN.
    Returns (ok, message, new_code)."""
    ok, msg = guarded_check(cfg, path, cfg.get("pin"), current_pin, now)
    if not ok:
        return False, msg, None
    code = new_recovery_code()
    cfg["recovery"] = hash_secret(code)
    save_cfg(path, cfg)
    return True, "", code


# ---------------------------------------------------------------- pairing ---
_PAIR_RE = re.compile(r"^RGB1\.([0-9a-f]{32})\.([A-Za-z0-9_-]{1,24})\.([A-Z2-7]{32})$")


def parse_pairing_code(text):
    """'RGB1.<cert-fingerprint>.<device-name>.<secret>'  ->  dict, or None if invalid."""
    m = _PAIR_RE.match(re.sub(r"\s+", "", text or ""))
    if not m:
        return None
    return {"fp": m.group(1), "name": m.group(2), "secret": m.group(3)}


# ------------------------------------------------- simple shared password ---
# "Simple mode": the PC has ONE short shared password (set with set_password.bat);
# the phone only needs the PC's IP + that password.  The app sends it under the fixed
# device name "app".  The PC's certificate is remembered on first connect (trust on first use).
SIMPLE_DEVICE_NAME = "app"
PASSWORD_MIN = 6
PASSWORD_MAX = 24
_PASSWORD_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def validate_password(pw):
    """Return None if OK, otherwise a short message (same rules as the PC side)."""
    pw = pw or ""
    if len(pw) < PASSWORD_MIN or len(pw) > PASSWORD_MAX:
        return "Password %d se %d akshar ka ho" % (PASSWORD_MIN, PASSWORD_MAX)
    if not _PASSWORD_RE.match(pw):
        return "Password mein sirf akshar (a-z, A-Z), number, - aur _ ho; space nahi"
    return None


def make_simple_pair(password):
    """Pair record for simple mode.  fp is None until the first successful connect."""
    return {"fp": None, "name": SIMPLE_DEVICE_NAME, "secret": password}


_HOST_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")


def validate_host(host):
    host = (host or "").strip()
    if not host or len(host) > 253 or not _HOST_RE.match(host):
        return "PC ka IP/naam sahi likho (jaise 192.168.1.8)"
    return None


def validate_port(text):
    try:
        port = int(text)
    except (TypeError, ValueError):
        return None
    return port if 1024 <= port <= 65535 else None
