import json, os, sys, tempfile, time, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
import security as S


class PinTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.path = os.path.join(self.d, "config.json")
        self.cfg = S.migrate({"host": "192.168.1.8"})
        self.code = S.create_pin(self.cfg, self.path, "483920")

    def test_policy(self):
        for bad in ("1234", "111111", "123456", "654321", "12345a", "", "0000000", "1" * 13):
            self.assertIsNotNone(S.validate_pin(bad), bad)
        for good in ("483920", "905173", "20481739"):
            self.assertIsNone(S.validate_pin(good), good)

    def test_unlock_ok_and_wrong(self):
        ok, _ = S.unlock(self.cfg, self.path, "483920")
        self.assertTrue(ok)
        ok, msg = S.unlock(self.cfg, self.path, "111222")
        self.assertFalse(ok)
        self.assertEqual(self.cfg["fails"], 1)

    def test_lockout_and_backoff(self):
        t = 1000.0
        for i in range(4):
            ok, msg = S.unlock(self.cfg, self.path, "000111", now=t)
            self.assertFalse(ok)
            self.assertEqual(S.lock_remaining(self.cfg, t), 0)
        ok, msg = S.unlock(self.cfg, self.path, "000111", now=t)      # 5th wrong -> 30 s
        self.assertEqual(S.lock_remaining(self.cfg, t), 30)
        # while locked even the CORRECT pin is refused and not counted
        ok, msg = S.unlock(self.cfg, self.path, "483920", now=t + 5)
        self.assertFalse(ok)
        self.assertEqual(self.cfg["fails"], 5)
        # after the lock expires the 6th wrong doubles the delay
        ok, _ = S.unlock(self.cfg, self.path, "000111", now=t + 31)
        self.assertEqual(S.lock_remaining(self.cfg, t + 31), 60)
        # cap at one hour
        cfg = S.migrate({"fails": 40, "pin": self.cfg["pin"]})
        S._register_failure(cfg, 0)
        self.assertEqual(cfg["lock_until"], S.LOCK_MAX)
        # correct pin after expiry resets everything
        ok, _ = S.unlock(self.cfg, self.path, "483920", now=t + 31 + 61)
        self.assertTrue(ok)
        self.assertEqual((self.cfg["fails"], self.cfg["lock_until"]), (0, 0.0))

    def test_counter_survives_restart(self):
        for _ in range(3):
            S.unlock(self.cfg, self.path, "000111")
        reloaded = S.load_cfg(self.path)
        self.assertEqual(reloaded["fails"], 3)          # persisted -> kill/restart gives no free guesses

    def test_clock_rollback_cannot_extend_beyond_cap(self):
        self.cfg["lock_until"] = time.time() + 10 ** 7
        self.assertLessEqual(S.lock_remaining(self.cfg), S.LOCK_MAX)

    def test_change_pin_requires_current(self):
        ok, msg, _ = S.change_pin(self.cfg, self.path, "999000", "270518")
        self.assertFalse(ok)
        self.assertTrue(S.unlock(self.cfg, self.path, "483920")[0])      # unchanged
        ok, msg, _ = S.change_pin(self.cfg, self.path, "483920", "270518")
        self.assertTrue(ok)
        self.assertTrue(S.unlock(self.cfg, self.path, "270518")[0])
        self.assertFalse(S.unlock(self.cfg, self.path, "483920")[0])

    def test_change_pin_wrong_current_counts_toward_lockout(self):
        for _ in range(5):
            S.change_pin(self.cfg, self.path, "000111", "270518")
        self.assertGreater(S.lock_remaining(self.cfg), 0)

    def test_no_reset_without_recovery_code(self):
        ok, msg, code = S.reset_pin_with_recovery(self.cfg, self.path, "", "270518")
        self.assertFalse(ok)
        ok, msg, code = S.reset_pin_with_recovery(self.cfg, self.path, "AAAA-AAAA-AAAA-AAAA-AAAA", "270518")
        self.assertFalse(ok)
        self.assertTrue(S.unlock(self.cfg, self.path, "483920")[0])      # old PIN still valid

    def test_recovery_flow_rotates_code(self):
        shown = S.format_recovery(self.code).lower()                      # typed with dashes, lower-case
        ok, msg, new_code = S.reset_pin_with_recovery(self.cfg, self.path, shown, "270518")
        self.assertTrue(ok, msg)
        self.assertNotEqual(new_code, self.code)
        self.assertTrue(S.unlock(self.cfg, self.path, "270518")[0])
        ok, _, _ = S.reset_pin_with_recovery(self.cfg, self.path, self.code, "519273")   # old code dead
        self.assertFalse(ok)

    def test_recovery_attempts_are_throttled_too(self):
        for _ in range(5):
            S.reset_pin_with_recovery(self.cfg, self.path, "WRONGCODEWRONGCODE12", "270518")
        self.assertGreater(S.lock_remaining(self.cfg), 0)
        ok, msg, _ = S.reset_pin_with_recovery(self.cfg, self.path, self.code, "270518")
        self.assertFalse(ok)                                              # even the right code is blocked

    def test_legacy_v1_config_migrates_and_upgrades(self):
        import hashlib, secrets
        salt = secrets.token_hex(16)
        legacy = {"host": "192.168.1.8", "salt": salt,
                  "hash": hashlib.pbkdf2_hmac("sha256", b"1234", bytes.fromhex(salt), 100_000).hex()}
        p = os.path.join(self.d, "legacy.json")
        json.dump(legacy, open(p, "w"))
        cfg = S.load_cfg(p)
        self.assertEqual(cfg["pin"]["iter"], 100_000)
        self.assertTrue(S.needs_pairing(cfg))
        ok, _ = S.unlock(cfg, p, "1234")
        self.assertTrue(ok)
        self.assertEqual(cfg["pin"]["iter"], S.ITERATIONS)                # silently upgraded

    def test_rotate_recovery_needs_pin(self):
        ok, _, c = S.rotate_recovery(self.cfg, self.path, "000111")
        self.assertFalse(ok)
        ok, _, c = S.rotate_recovery(self.cfg, self.path, "483920")
        self.assertTrue(ok)
        self.assertFalse(S.reset_pin_with_recovery(self.cfg, self.path, self.code, "270518")[0])
        self.assertTrue(S.reset_pin_with_recovery(self.cfg, self.path, c, "270518")[0])

    def test_config_file_private_and_atomic(self):
        mode = os.stat(self.path).st_mode & 0o777
        self.assertEqual(mode, 0o600)
        self.assertFalse(os.path.exists(self.path + ".tmp"))
        raw = open(self.path).read()
        self.assertNotIn("483920", raw)                                   # only hashes on disk
        self.assertNotIn(self.code, raw)

    def test_pairing_code_parser(self):
        good = "RGB1." + "a" * 32 + ".phone1." + "A" * 32
        p = S.parse_pairing_code("  " + good[:20] + "\n" + good[20:] + " ")
        self.assertEqual(p["name"], "phone1")
        for bad in ("", "RGB2." + good[5:], good[:-1], good.replace("phone1", "ph one!"), good + "x"):
            self.assertIsNone(S.parse_pairing_code(bad), bad)

    def test_host_and_port_validation(self):
        self.assertIsNone(S.validate_host("192.168.1.8"))
        self.assertIsNotNone(S.validate_host("bad host;rm"))
        self.assertEqual(S.validate_port("6743"), 6743)
        self.assertIsNone(S.validate_port("80"))
        self.assertIsNone(S.validate_port("abc"))


if __name__ == "__main__":
    unittest.main()
