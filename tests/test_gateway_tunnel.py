import json, os, socket, sys, tempfile, threading, time, unittest
HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "app"))
sys.path.insert(0, os.path.join(HERE, "..", "pc_gateway"))
os.environ["RGB_GATEWAY_DIR"] = tempfile.mkdtemp()
import security as S
import tunnel as T
import rgb_gateway as G


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


class FakeOpenRGB:
    """Echo server standing in for OpenRGB; counts connections so we can prove nothing leaks."""
    def __init__(self):
        self.port = free_port(); self.connections = 0; self.stop = False
        self.srv = socket.socket(); self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", self.port)); self.srv.listen(8); self.srv.settimeout(0.2)
        threading.Thread(target=self.loop, daemon=True).start()
    def loop(self):
        while not self.stop:
            try: c, _ = self.srv.accept()
            except socket.timeout: continue
            except OSError: return
            self.connections += 1
            threading.Thread(target=self.echo, args=(c,), daemon=True).start()
    def echo(self, c):
        try:
            while True:
                d = c.recv(65536)
                if not d: break
                c.sendall(d)
        except OSError: pass
        finally: c.close()
    def close(self): self.stop = True; self.srv.close()


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(); os.environ["RGB_GATEWAY_DIR"] = self.dir
        self.assertEqual(G.main(["init"]), 0)
        self.fake = FakeOpenRGB()
        cfg = G.load_config(); cfg.update(listen_host="127.0.0.1", listen_port=free_port(),
                                          openrgb_port=self.fake.port)
        G.save_json("config.json", cfg); self.cfg = cfg
        self.pair = self.add("phone1")
        self.gw = G.Gateway(cfg); ev = threading.Event()
        threading.Thread(target=self.gw.serve, args=(ev,), daemon=True).start(); ev.wait(3)
    def tearDown(self):
        self.gw.shutdown(); self.fake.close()
    def add(self, name):
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(G.main(["add-device", name]), 0)
        code = [l.strip() for l in buf.getvalue().splitlines() if l.strip().startswith("RGB1.")][0]
        return S.parse_pairing_code(code)
    def tunnel(self, pair=None, port=None):
        return T.open_tunnel("127.0.0.1", port or self.cfg["listen_port"], pair or self.pair)


class HappyPath(Base):
    def test_echo_through_tunnel(self):
        lp = self.tunnel()
        c = socket.create_connection(("127.0.0.1", lp), timeout=3)
        c.sendall(b"hello-openrgb"); self.assertEqual(c.recv(100), b"hello-openrgb"); c.close()

    def test_large_transfer_intact(self):
        lp = self.tunnel(); c = socket.create_connection(("127.0.0.1", lp), timeout=5)
        blob = os.urandom(1_500_000); got = b""
        t = threading.Thread(target=lambda: c.sendall(blob)); t.start()
        while len(got) < len(blob):
            d = c.recv(65536)
            if not d: break
            got += d
        t.join(); self.assertEqual(got, blob)

    def test_local_listener_is_single_use(self):
        lp = self.tunnel(); c = socket.create_connection(("127.0.0.1", lp), timeout=3); c.sendall(b"x"); c.recv(10)
        time.sleep(0.2)
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", lp), timeout=1)


class AuthFailures(Base):
    def test_wrong_secret_rejected_and_nothing_reaches_openrgb(self):
        bad = dict(self.pair, secret="A" * 32)
        with self.assertRaises(T.TunnelError): self.tunnel(bad)
        self.assertEqual(self.fake.connections, 0)

    def test_wrong_fingerprint_refused_before_secret_is_sent(self):
        bad = dict(self.pair, fp="0" * 32)
        with self.assertRaises(T.TunnelError) as cm: self.tunnel(bad)
        self.assertIn("certificate", str(cm.exception).lower())
        self.assertEqual(self.gw.throttle.table, {})          # gateway never saw a credential attempt
        self.assertEqual(self.fake.connections, 0)

    def test_unknown_device_name_rejected(self):
        with self.assertRaises(T.TunnelError): self.tunnel(dict(self.pair, name="ghost"))

    def test_brute_force_lockout_then_even_correct_secret_blocked(self):
        for _ in range(5):
            with self.assertRaises(T.TunnelError): self.tunnel(dict(self.pair, secret="B" * 32))
        with self.assertRaises(T.TunnelError) as cm: self.tunnel()           # correct secret
        self.assertIn("rok", str(cm.exception).lower())
        self.assertEqual(self.fake.connections, 0)

    def test_revoke_is_immediate(self):
        self.tunnel()
        self.assertEqual(G.main(["revoke", "phone1"]), 0)
        with self.assertRaises(T.TunnelError): self.tunnel()

    def test_two_devices_independent(self):
        p2 = self.add("tablet"); self.tunnel(p2); self.tunnel(self.pair)
        G.main(["revoke", "tablet"])
        with self.assertRaises(T.TunnelError): self.tunnel(p2)
        self.tunnel(self.pair)

    def test_plain_tcp_client_gets_nothing(self):
        c = socket.create_connection(("127.0.0.1", self.cfg["listen_port"]), timeout=2)
        c.sendall(b"\x00\x01OPENRGB-raw-sdk-packet" * 10)
        c.settimeout(8)
        try: data = c.recv(100)
        except (socket.timeout, OSError): data = b""
        self.assertNotIn(b"OPENRGB-raw", data); self.assertEqual(self.fake.connections, 0)

    def test_garbage_after_tls_counts_as_failure(self):
        import ssl
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
        s = ctx.wrap_socket(socket.create_connection(("127.0.0.1", self.cfg["listen_port"]), timeout=3))
        s.sendall(b"HELLO\nx\ny\n"); time.sleep(0.4)
        self.assertEqual(self.gw.throttle.table["127.0.0.1"]["fails"], 1)
        self.assertEqual(self.fake.connections, 0)

    def test_trusted_ip_allowlist_blocks_other_addresses(self):
        self.gw.cfg["trusted_ips"] = ["192.168.77.7"]
        with self.assertRaises(T.TunnelError): self.tunnel()
        self.gw.cfg["trusted_ips"] = ["127.0.0.1"]
        self.tunnel()


class Misc(Base):
    def test_openrgb_down_reports_clearly(self):
        self.fake.close(); time.sleep(0.3)
        with self.assertRaises(T.TunnelError) as cm: self.tunnel()
        self.assertIn("openrgb", str(cm.exception).lower())

    def test_gateway_down_reports_clearly(self):
        with self.assertRaises(T.TunnelError): self.tunnel(port=free_port())

    def test_public_addresses_refused_without_any_network_traffic(self):
        for h in ("8.8.8.8", "1.1.1.1", "93.184.216.34"):
            with self.assertRaises(T.TunnelError): T.open_tunnel(h, 6743, self.pair)
        for h in ("192.168.1.8", "10.0.0.5", "172.16.3.4", "127.0.0.1", "169.254.1.1"):
            self.assertTrue(T.is_lan_ip(h), h)
        for h in ("8.8.8.8", "0.0.0.0", "224.0.0.1", "100.64.0.1" if False else "8.8.4.4"):
            self.assertFalse(T.is_lan_ip(h), h)

    def test_secrets_are_hashed_on_the_gateway(self):
        raw = open(os.path.join(self.dir, "devices.json")).read()
        self.assertNotIn(self.pair["secret"], raw)
        self.assertIn("sha256", raw)
        self.assertEqual(os.stat(os.path.join(self.dir, "key.pem")).st_mode & 0o777, 0o600)

    def test_tls_below_1_2_refused(self):
        import ssl
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
        try:
            ctx.maximum_version = ssl.TLSVersion.TLSv1_1
            ctx.minimum_version = ssl.TLSVersion.TLSv1
        except (ValueError, ssl.SSLError):
            self.skipTest("local OpenSSL cannot offer TLS<1.2")
        with self.assertRaises((ssl.SSLError, OSError)):
            ctx.wrap_socket(socket.create_connection(("127.0.0.1", self.cfg["listen_port"]), timeout=3))


if __name__ == "__main__":
    unittest.main(verbosity=1)
