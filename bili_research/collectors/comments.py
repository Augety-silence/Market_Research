"""视频评论采集（主评论 + 可选楼中楼预览）。"""

from __future__ import annotations

import hashlib

from ..core.client import Client
from ..core.errors import CrawlError


def mask_user(name: str) -> str:
    """默认脱敏：保留首尾字符。"""
    if not name:
        return "匿名用户"
    if len(name) <= 2:
        return name[0] + "*"
    return name[0] + "*" * (len(name) - 2) + name[-1]


def user_id(mid: int | str) -> str:
    """不可逆的稳定 ID，便于去重而不保留原始 UID。"""
    return "u" + hashlib.sha1(str(mid).encode()).hexdigest()[:12]


def fetch_comments(client: Client, aid: int, bvid: str, pages: int = 3,
                   limit: int = 60, sort: int = 2, keep_names: bool = False,
                   include_preview: bool = False) -> list[dict]:
    """按页取主评论；接口按热度/时间排序，不保证能取到全部。"""
    rows: list[dict] = []
    seen: set[str] = set()
    for page in range(1, max(1, pages) + 1):
        data = client.get_json(
            "/x/v2/reply",
            {"type": 1, "oid": aid, "pn": page, "ps": 20, "sort": sort},
            referer=f"https://www.bilibili.com/video/{bvid}/",
        )
        replies = data.get("replies") or []
        if not replies:
            break
        for reply in replies:
            rid = str(reply.get("rpid"))
            if rid in seen:
                continue
            seen.add(rid)
            member = reply.get("member") or {}
            name = member.get("uname") or ""
            row = {
                "评论ID": rid,
                "用户": name if keep_names else mask_user(name),
                "用户ID": user_id(member.get("mid", "")),
                "正文": (reply.get("content") or {}).get("message", "").strip(),
                "点赞": reply.get("like", 0),
                "回复数": reply.get("rcount", 0),
                "时间": reply.get("ctime", 0),
                "是否楼中楼": False,
                "根评论ID": "",
            }
            rows.append(row)
            if include_preview:
                for sub in ((reply.get("replies") or [])[:3]):
                    rows.append({
                        "评论ID": str(sub.get("rpid")),
                        "用户": (sub.get("member") or {}).get("uname", "") if keep_names
                        else mask_user((sub.get("member") or {}).get("uname", "")),
                        "用户ID": user_id((sub.get("member") or {}).get("mid", "")),
                        "正文": (sub.get("content") or {}).get("message", "").strip(),
                        "点赞": sub.get("like", 0),
                        "回复数": 0,
                        "时间": sub.get("ctime", 0),
                        "是否楼中楼": True,
                        "根评论ID": rid,
                    })
            if limit and len(rows) >= limit:
                return rows[:limit]
        if data.get("page", {}).get("count", 0) <= page * 20:
            break
    if not rows:
        raise CrawlError("没有取到评论：评论区可能已关闭、需要登录，或视频无评论。")
    return rows[:limit] if limit else rows
