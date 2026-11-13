"""B 站 WBI 签名。

2023 年起 ``/x/player/wbi/v2``、``/x/v2/reply/wbi/main`` 等接口要求
``w_rid`` + ``wts`` 参数：把参数按 key 排序拼成 query，追加从
``nav`` 接口拿到的 mixin key 后取 MD5。
"""

from __future__ import annotations

import hashlib
import time
import urllib.parse

MIXIN_KEY_ENC_TAB = (
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
)


def mixin_key(img_key: str, sub_key: str) -> str:
    """把 img_url / sub_url 的文件名按固定表重排，取前 32 位。"""
    raw = img_key + sub_key
    return "".join(raw[i] for i in MIXIN_KEY_ENC_TAB)[:32]


def _sanitize(value: str) -> str:
    """WBI 规定参数值里不能带 !'()* 这些字符。"""
    return "".join(ch for ch in str(value) if ch not in "!'()*")


def sign(params: dict, key: str, timestamp: int | None = None) -> str:
    """返回带 wts / w_rid 的 query string（已 URL 编码）。"""
    items = {k: _sanitize(v) for k, v in params.items() if v is not None}
    items["wts"] = str(int(time.time()) if timestamp is None else timestamp)
    query = urllib.parse.urlencode(sorted(items.items()), quote_via=urllib.parse.quote)
    w_rid = hashlib.md5((query + key).encode("utf-8")).hexdigest()
    return f"{query}&w_rid={w_rid}"


def keys_from_nav(nav_data: dict) -> str:
    """从 ``/x/web-interface/nav`` 的 data.wbi_img 里取出 mixin key。"""
    try:
        img_url = nav_data["wbi_img"]["img_url"]
        sub_url = nav_data["wbi_img"]["sub_url"]
    except (KeyError, TypeError) as exc:  # pragma: no cover - 结构异常
        raise ValueError("nav 接口未返回 wbi_img，无法签名") from exc
    img_key = img_url.rsplit("/", 1)[-1].split(".")[0]
    sub_key = sub_url.rsplit("/", 1)[-1].split(".")[0]
    return mixin_key(img_key, sub_key)
