"""Make YOUR OWN Android signing key (run once, on your PC).

    pip install cryptography
    python tools/make_keystore.py

It writes rgbphone-release.p12 (KEEP SAFE, never upload to GitHub files) and prints the 4 values
to paste into GitHub -> Settings -> Secrets and variables -> Actions.
If you lose this key you cannot update the app later (you would have to uninstall and reinstall).
"""
import base64
import datetime
import getpass
import os
import secrets
import sys

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

OUT = "rgbphone-release.p12"
ALIAS = "rgbphone"


def main():
    if os.path.exists(OUT):
        sys.exit("%s pehle se hai. Usse mat badlo; ye tumhari asli key hai." % OUT)
    password = secrets.token_urlsafe(24)          # random, same for store and key
    key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "RGB Phone"),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, getpass.getuser()[:60] or "me")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=365 * 30))
            .sign(key, hashes.SHA256()))
    data = pkcs12.serialize_key_and_certificates(
        ALIAS.encode(), key, cert, None, serialization.BestAvailableEncryption(password.encode()))
    fd = os.open(OUT, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    print("Bann gaya: %s  (isko backup karo: pendrive / password manager)\n" % os.path.abspath(OUT))
    print("GitHub Secrets (4 alag secrets banao):")
    print("  KEYSTORE_PASSWORD =", password)
    print("  KEY_PASSWORD      =", password)
    print("  KEY_ALIAS         =", ALIAS)
    print("  KEYSTORE_B64      = (neeche wali lambi line)\n")
    print(base64.b64encode(data).decode())


if __name__ == "__main__":
    main()
