import unittest

from bili_research.wbi import mixin_key, sign


class WbiTest(unittest.TestCase):
    def test_mixin_key_is_32_chars(self):
        raw = "0123456789abcdef" * 4
        key = mixin_key(raw, raw)
        self.assertEqual(len(key), 32)

    def test_sign_is_stable_for_fixed_timestamp(self):
        key = "abcdefghijklmnopqrstuvwxyz012345"
        a = sign({"aid": 1, "cid": 2}, key, timestamp=1700000000)
        b = sign({"aid": 1, "cid": 2}, key, timestamp=1700000000)
        self.assertEqual(a, b)
        self.assertIn("wts=1700000000", a)
        self.assertIn("w_rid=", a)

    def test_sanitizes_special_chars(self):
        key = "k" * 32
        query = sign({"keyword": "a!'()*b"}, key, timestamp=1)
        self.assertIn("keyword=ab", query)


if __name__ == "__main__":
    unittest.main()
