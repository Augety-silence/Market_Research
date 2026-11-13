import os
import tempfile
import unittest
from pathlib import Path

from bili_research.core.client import read_cookie


class CookieTest(unittest.TestCase):
    def test_single_line_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cookie.txt"
            path.write_text("SESSDATA=abc; bili_jct=def\n", encoding="utf-8")
            self.assertEqual(read_cookie(str(path)), "SESSDATA=abc; bili_jct=def")

    def test_netscape_file(self):
        line = ".bilibili.com\tTRUE\t/\tFALSE\t0\tSESSDATA\tabc"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cookies.txt"
            path.write_text("# Netscape\n" + line + "\n", encoding="utf-8")
            self.assertEqual(read_cookie(str(path)), "SESSDATA=abc")

    def test_env_fallback(self):
        os.environ["BILI_COOKIE"] = "SESSDATA=xyz"
        try:
            self.assertEqual(read_cookie(None), "SESSDATA=xyz")
        finally:
            os.environ.pop("BILI_COOKIE", None)


if __name__ == "__main__":
    unittest.main()
