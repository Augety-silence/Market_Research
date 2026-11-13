"""视频元信息、字幕轨、音轨地址。"""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from ..core.client import Client
from ..core.errors import CrawlError
from .subtitles import coverage  # noqa: F401  (对外保持 video.coverage 可用)

BVID_RE = re.compile(r"(BV[0-9A-Za-z]{10})")


def extract_bvid(value: str) -> str:
    """从 BV 号或视频链接里取 BV 号（不支持 b23.tv 短链）。"""
    match = BVID_RE.search(value.strip())
    if not match:
        raise CrawlError("请输入 BV 号或包含 BV 号的视频链接（不支持 b23.tv 短链）。")
    return match.group(1)


def get_view(client: Client, bvid: str) -> dict:
    return client.get_json("/x/web-interface/view", {"bvid": bvid},
                           referer=f"https://www.bilibili.com/video/{bvid}/")


def video_meta(view: dict) -> dict:
    pages = view.get("pages") or []
    first = pages[0] if pages else {}
    return {
        "bvid": view.get("bvid"),
        "aid": view.get("aid"),
        "cid": first.get("cid"),
        "title": (view.get("title") or "").strip(),
        "owner": (view.get("owner") or {}).get("name", ""),
        "duration": int(first.get("duration") or view.get("duration") or 0),
        "view": view.get("stat", {}).get("view", 0),
        "reply": view.get("stat", {}).get("reply", 0),
        "pubdate": view.get("pubdate", 0),
        "desc": (view.get("desc") or "").strip(),
        "pages": [{"cid": p.get("cid"), "page": p.get("page"), "part": p.get("part"),
                   "duration": p.get("duration")} for p in pages],
    }


def subtitle_tracks(client: Client, bvid: str, aid: int, cid: int) -> list[dict]:
    """返回播放器可见的字幕轨列表（需要登录态，否则通常为空）。"""
    data = client.get_json(
        "/x/player/wbi/v2",
        {"aid": aid, "cid": cid, "bvid": bvid},
        signed=True,
        referer=f"https://www.bilibili.com/video/{bvid}/",
    )
    return ((data.get("subtitle") or {}).get("subtitles") or [])


def pick_chinese(tracks: list[dict]) -> dict | None:
    """优先 AI 中文轨（ai-zh），其次任意 zh 轨。"""
    def score(track: dict) -> tuple:
        lan = str(track.get("lan") or "").lower()
        doc = str(track.get("lan_doc") or "")
        ai = 1 if "ai" in lan else 0
        zh = 1 if (lan.startswith("zh") or "中文" in doc) else 0
        return (zh, ai)

    candidates = [t for t in tracks if score(t)[0] == 1]
    if not candidates:
        return None
    return max(candidates, key=score)


def track_url_ok(url: str, aid: int, cid: int) -> bool:
    """校验字幕地址属于当前视频，过滤反爬返回的串片数据。"""
    path = urlparse("https:" + url if url.startswith("//") else url).path
    return f"/{aid}" in path and f"/{cid}" in path


def fetch_subtitle(client: Client, url: str, bvid: str) -> list[dict]:
    raw = client.download(url, referer=f"https://www.bilibili.com/video/{bvid}/")
    data = json.loads(raw.decode("utf-8"))
    body = data.get("body")
    if not isinstance(body, list):
        raise CrawlError("字幕 JSON 结构异常，未找到 body 数组。")
    segments = []
    for item in body:
        content = (item.get("content") or "").strip()
        if not content:
            continue
        segments.append({
            "from": round(float(item.get("from") or 0), 2),
            "to": round(float(item.get("to") or 0), 2),
            "content": content,
        })
    return segments


def audio_url(client: Client, bvid: str, cid: int, quality: int = 30216) -> str:
    """取 DASH 音轨地址；quality 30216=64k，30232=132k，30280=192k。"""
    data = client.get_json(
        "/x/player/playurl",
        {"bvid": bvid, "cid": cid, "fnval": 16, "fourk": 0},
        referer=f"https://www.bilibili.com/video/{bvid}/",
    )
    audios = ((data.get("dash") or {}).get("audio") or [])
    if not audios:
        raise CrawlError("未取到音轨：该视频可能为付费/充电专属内容。")
    audios.sort(key=lambda a: abs(a.get("id", 0) - quality))
    return audios[0]["baseUrl"]
