"""带限速、重试和登录态的 HTTP 客户端（仅标准库）。"""

from __future__ import annotations

import json
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .errors import CrawlError, LoginRequired, RiskControl
from .wbi import keys_from_nav, sign

API = "https://api.bilibili.com"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def read_cookie(path: str | None = None) -> str:
    """读取 Cookie：优先命令行文件，其次环境变量 BILI_COOKIE。

    支持两种文件格式：
    1. 单行 ``SESSDATA=xxx; bili_jct=yyy``；
    2. 浏览器导出的 Netscape cookies.txt（只取 .bilibili.com 域）。
    ``path`` 传 ``-`` 时从标准输入读取，便于接密钥管理或管道。
    """
    if path == "-":
        raw = sys.stdin.read().strip()
    elif path:
        raw = Path(path).expanduser().read_text(encoding="utf-8").strip()
    else:
        raw = (os.environ.get("BILI_COOKIE") or "").strip()
    if not raw:
        return ""
    if "\n" in raw and "\t" in raw:  # Netscape cookies.txt
        pairs = []
        for line in raw.splitlines():
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 7 and "bilibili.com" in parts[0]:
                pairs.append(f"{parts[5]}={parts[6]}")
        return "; ".join(pairs)
    if "\n" in raw:
        raise CrawlError("Cookie 文件应为单行，或使用浏览器导出的 cookies.txt。")
    return raw.removeprefix("Cookie:").strip()


class Client:
    """所有请求都走这里：统一 UA/Referer、限速、错误归类和 WBI 签名。"""

    def __init__(self, cookie: str = "", interval: float = 2.5, timeout: int = 20):
        self.cookie = cookie.strip()
        self.interval = max(1.0, float(interval))
        self.timeout = timeout
        self._last = 0.0
        self._wbi_key: str | None = None
        self._logged_in: bool | None = None
        self._buvid_ready = False

    # ---- 基础请求 -------------------------------------------------
    def _wait(self) -> None:
        elapsed = time.monotonic() - self._last
        delay = self.interval - elapsed
        if delay > 0:
            time.sleep(delay + random.uniform(0, 0.3))

    def _open(self, url: str, referer: str = "https://www.bilibili.com/") -> bytes:
        headers = {
            "User-Agent": UA,
            "Referer": referer,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        if self.cookie:
            headers["Cookie"] = self.cookie
        request = urllib.request.Request(url, headers=headers)
        self._wait()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (412, 429):
                raise RiskControl(
                    f"HTTP {exc.code}：访问受限，已停止。请降低频率或稍后再试。"
                ) from None
            raise CrawlError(f"HTTP {exc.code}：请求失败（{url.split('?')[0]}）。") from None
        except urllib.error.URLError as exc:
            raise CrawlError(f"网络错误：{exc.reason}") from None
        finally:
            self._last = time.monotonic()

    def get_json(self, path: str, params: dict | None = None, signed: bool = False,
                 referer: str = "https://www.bilibili.com/") -> dict:
        self._ensure_buvid()
        if path.startswith("http"):
            url = path
        elif signed:
            query = sign(params or {}, self.wbi_key())
            url = f"{API}{path}?{query}"
        else:
            query = urllib.parse.urlencode(params or {})
            url = f"{API}{path}?{query}" if query else f"{API}{path}"
        payload = json.loads(self._open(url, referer).decode("utf-8"))
        code = payload.get("code")
        if code == 0:
            return payload.get("data") or {}
        if code in (-101, -400, -403):
            raise LoginRequired(
                f"接口返回 {code}：需要登录或 Cookie 已失效，请更新 Cookie 后重试。"
            )
        if code in (-352, -412, -509):
            raise RiskControl(f"接口返回 {code}：触发风控，已停止，请降低频率。")
        raise CrawlError(f"接口返回 {code}：{payload.get('message', '未知错误')}")

    # ---- 登录态与签名 ---------------------------------------------
    def _ensure_buvid(self) -> None:
        """匿名请求也建议带 buvid3/buvid4，否则部分接口直接返回 -101。"""
        if self._buvid_ready:
            return
        self._buvid_ready = True
        if "buvid3=" in self.cookie:
            return
        try:
            payload = json.loads(
                self._open(f"{API}/x/frontend/finger/spi").decode("utf-8"))
            data = payload.get("data") or {}
            b3, b4 = data.get("b_3"), data.get("b_4")
            if b3:
                extra = f"buvid3={b3}"
                if b4:
                    extra += f"; buvid4={b4}"
                self.cookie = f"{self.cookie}; {extra}" if self.cookie else extra
        except (CrawlError, ValueError):
            pass

    def is_logged_in(self) -> bool:
        if self._logged_in is None:
            # 未登录时 nav 返回 -101，但 data 里仍带 wbi_img，
            # 而 WBI 签名是匿名也能算的，所以这里直接读原始响应。
            self._ensure_buvid()
            payload = json.loads(
                self._open(f"{API}/x/web-interface/nav").decode("utf-8"))
            data = payload.get("data") or {}
            self._logged_in = bool(data.get("isLogin"))
            try:
                self._wbi_key = keys_from_nav(data)
            except ValueError:
                self._wbi_key = None
        return self._logged_in

    def wbi_key(self) -> str:
        if self._wbi_key is None:
            self.is_logged_in()
        assert self._wbi_key
        return self._wbi_key

    def require_login(self) -> None:
        if not self.is_logged_in():
            raise LoginRequired(
                "未检测到登录态：B 站 AI 字幕接口匿名调用会返回空列表。"
                "请用 --cookie-file 提供 Cookie，或设置环境变量 BILI_COOKIE。"
            )

    def download(self, url: str, referer: str) -> bytes:
        """下载字幕 JSON / 音轨等静态资源（带签名，不需要 Cookie）。"""
        if url.startswith("//"):
            url = "https:" + url
        return self._open(url, referer=referer)
