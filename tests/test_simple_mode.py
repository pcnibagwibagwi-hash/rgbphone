"""Tests for 'simple mode': one short shared password + certificate remembered on first use."""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(__file__))
from test_gateway_tunnel import Base, S, T, G


class PasswordRules(unittest.TestCase):
    def test_validate_password(self):
        for ok in ("lights24", "Abc_12", "a-b-c-d-e-f", "x" * 24):
            self.assertIsNone(S.validate_password(ok), ok)
        for bad in ("", "abc", "12345", "x" * 25, "has space", "pass!word", "हिंदी123", None):
            self.assertIsNotNone(S.validate_password(bad), bad)

    def test_parallel_config_saves_do_not_collide(self):
        import tempfile, threading
        path = os.path.join(tempfile.mkdtemp(), "cfg", "config.json")
        errors = []

        def w(i):
            try:
                for j in range(20):
                    S.save_cfg(path, {"i": i, "j": j})
            except Exception as e:
                errors.append(e)
        ts = [threading.Thread(target=w, args=(i,)) for i in range(8)]
        [t.start() for t in ts]; [t.join() for t in ts]
        self.assertEqual(errors, [])
        self.assertIn("i", S.load_cfg(path))

    def test_make_simple_pair(self):
        p = S.make_simple_pair("lights24")
        self.assertEqual(p, {"fp": None, "name": "app", "secret": "lights24"})


class SimpleMode(Base):
    def setUp(self):
        super().setUp()
        self.assertEqual(G.main(["set-password", "lights24"]), 0)

    def pair_simple(self, pw="lights24"):
        return S.make_simple_pair(pw)

    def test_login_works_and_certificate_is_remembered(self):
        import socket
        pair = self.pair_simple()
        lp = self.tunnel(pair)
        c = socket.create_connection(("127.0.0.1", lp), timeout=3)
        c.sendall(b"hello"); self.assertEqual(c.recv(10), b"hello"); c.close()
        self.assertEqual(pair["seen_fp"], G.cert_fingerprint())     # app stores this as pair["fp"]

    def test_wrong_password_rejected_nothing_reaches_openrgb(self):
        with self.assertRaises(T.TunnelError) as cm:
            self.tunnel(self.pair_simple("wrongpass"))
        self.assertIn("password", str(cm.exception).lower())
        self.assertEqual(self.fake.connections, 0)

    def test_lockout_applies_to_simple_mode_too(self):
        for _ in range(5):
            with self.assertRaises(T.TunnelError):
                self.tunnel(self.pair_simple("wrongpass"))
        with self.assertRaises(T.TunnelError) as cm:
            self.tunnel(self.pair_simple())                           # correct, but locked
        self.assertIn("rok", str(cm.exception).lower())
        self.assertEqual(self.fake.connections, 0)

    def test_remembered_certificate_is_enforced_afterwards(self):
        pair = self.pair_simple(); pair["fp"] = "0" * 32              # PC "changed"
        with self.assertRaises(T.TunnelError) as cm:
            self.tunnel(pair)
        self.assertIn("pehchaan", str(cm.exception).lower())
        self.assertEqual(self.gw.throttle.table, {})                  # password never sent

    def test_password_is_only_stored_hashed(self):
        raw = open(os.path.join(self.dir, "password.json")).read()
        self.assertNotIn("lights24", raw)
        self.assertIn("salt", raw)                                    # salted PBKDF2 record
        self.assertEqual(os.stat(os.path.join(self.dir, "password.json")).st_mode & 0o777, 0o600)

    def test_password_change_applies_immediately(self):
        self.assertEqual(G.main(["set-password", "newpass99"]), 0)
        with self.assertRaises(T.TunnelError):
            self.tunnel(self.pair_simple("lights24"))
        self.gw.throttle.success("127.0.0.1")
        self.tunnel(self.pair_simple("newpass99"))

    def test_cli_rejects_weak_format_and_reserved_name(self):
        for bad in ("short", "has space", "x" * 30):
            self.assertEqual(G.main(["set-password", bad]), 1, bad)
        self.assertEqual(G.main(["add-device", "app"]), 1)

    def test_clear_password_turns_simple_mode_off(self):
        self.assertEqual(G.main(["clear-password"]), 0)
        with self.assertRaises(T.TunnelError):
            self.tunnel(self.pair_simple())

    def test_no_password_set_means_app_name_cannot_login(self):
        os.remove(os.path.join(self.dir, "password.json"))
        with self.assertRaises(T.TunnelError):
            self.tunnel(self.pair_simple("lights24"))

    def test_strict_pairing_code_still_works(self):
        self.tunnel(self.pair)                                        # phone1 from Base


if __name__ == "__main__":
    unittest.main(verbosity=1)
