"""视频评论采集（主评论 + 可选楼中楼预览）。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from ..core.client import Client
from ..core.errors import CrawlError
from .video import extract_bvid, get_view, video_meta


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


def format_time(ts: int | float) -> str:
    """Unix 时间戳转本地可读时间；缺值时返回空串。"""
    if not ts:
        return ""
    return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M")


def fetch_comments(client: Client, aid: int, bvid: str, pages: int = 3,
                   limit: int = 60, sort: int = 2, keep_names: bool = False,
                   include_preview: bool = False, group: str = "未分组",
                   title: str = "") -> list[dict]:
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
                "分组": group,
                "BV号": bvid,
                "标题": title,
                "评论ID": rid,
                "用户": name if keep_names else mask_user(name),
                "用户ID": user_id(member.get("mid", "")),
                "正文": (reply.get("content") or {}).get("message", "").strip(),
                "点赞": reply.get("like", 0),
                "回复数": reply.get("rcount", 0),
                "时间": reply.get("ctime", 0),
                "时间文本": format_time(reply.get("ctime", 0)),
                "是否楼中楼": False,
                "根评论ID": "",
            }
            rows.append(row)
            if include_preview:
                for sub in ((reply.get("replies") or [])[:3]):
                    rows.append({
                        "分组": group,
                        "BV号": bvid,
                        "标题": title,
                        "评论ID": str(sub.get("rpid")),
                        "用户": (sub.get("member") or {}).get("uname", "") if keep_names
                        else mask_user((sub.get("member") or {}).get("uname", "")),
                        "用户ID": user_id((sub.get("member") or {}).get("mid", "")),
                        "正文": (sub.get("content") or {}).get("message", "").strip(),
                        "点赞": sub.get("like", 0),
                        "回复数": 0,
                        "时间": sub.get("ctime", 0),
                        "时间文本": format_time(sub.get("ctime", 0)),
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


def collect_for_video(client: Client, video: str, group: str = "未分组",
                      pages: int = 3, limit: int = 60, sort: int = 2,
                      keep_names: bool = False,
                      include_preview: bool = False) -> tuple[dict, list[dict]]:
    """单条视频：取元信息 + 评论，评论行补上分组/BV号/标题，便于跨视频汇总。"""
    bvid = extract_bvid(video)
    meta = video_meta(get_view(client, bvid))
    meta["group"] = group
    rows = fetch_comments(client, meta["aid"], bvid, pages=pages, limit=limit,
                          sort=sort, keep_names=keep_names,
                          include_preview=include_preview, group=group,
                          title=meta["title"])
    return meta, rows


def fetch_all_comments(client: Client, aid: int, bvid: str, title: str = "",
                       group: str = "未分组", max_sub_pages: int = 8,
                       keep_names: bool = False,
                       progress=None) -> list[dict]:
    """全量：主评论走 WBI 游标翻到底，楼中楼按 root 分页补齐。

    网易云式的 ``pn`` 翻页在 B 站主评论接口上大约 2000 条就翻不动了，
    所以这里用 ``/x/v2/reply/wbi/main`` 的 ``pagination_str`` 游标；
    楼中楼用 ``/x/v2/reply/reply``，每个根评论最多取 ``max_sub_pages`` 页。
    该接口需要登录态，匿名会只返回 3 条并标记结束。
    """
    rows: list[dict] = []
    seen: set[str] = set()
    offset = ""
    page = 0

    def add(reply: dict, root: str, is_sub: bool) -> None:
        rid = str(reply.get("rpid"))
        if rid in seen:
            return
        seen.add(rid)
        member = reply.get("member") or {}
        name = member.get("uname") or ""
        rows.append({
            "分组": group,
            "BV号": bvid,
            "标题": title,
            "评论ID": rid,
            "根评论ID": root,
            "用户": name if keep_names else mask_user(name),
            "用户ID": user_id(member.get("mid", "")),
            "正文": (reply.get("content") or {}).get("message", "").strip(),
            "点赞": reply.get("like", 0),
            "回复数": reply.get("rcount", 0),
            "时间": reply.get("ctime", 0),
            "时间文本": format_time(reply.get("ctime", 0)),
            "是否楼中楼": is_sub,
        })

    roots: list[tuple[str, int]] = []
    while True:
        params = {"oid": aid, "type": 1, "mode": 3, "ps": 20, "plat": 1,
                  "web_location": 1315875}
        if offset:
            params["pagination_str"] = json.dumps({"offset": offset}, separators=(",", ":"))
        data = client.get_json("/x/v2/reply/wbi/main", params, signed=True,
                               referer=f"https://www.bilibili.com/video/{bvid}/")
        replies = data.get("replies") or []
        for reply in replies:
            add(reply, "0", False)
            if (reply.get("rcount") or 0) > 0:
                roots.append((str(reply.get("rpid")), int(reply.get("rcount"))))
        cursor = data.get("cursor") or {}
        page += 1
        if progress:
            progress(f"主评论 第{page}页 累计{len(rows)}条")
        nxt = (cursor.get("pagination_reply") or {}).get("next_offset")
        if not replies or cursor.get("is_end") or not nxt:
            break
        offset = nxt

    for index, (root, rcount) in enumerate(roots, 1):
        pages = min(max(1, -(-rcount // 20)), max_sub_pages)
        for pn in range(1, pages + 1):
            data = client.get_json(
                "/x/v2/reply/reply",
                {"oid": aid, "type": 1, "root": root, "pn": pn, "ps": 20},
                referer=f"https://www.bilibili.com/video/{bvid}/")
            sub_replies = data.get("replies") or []
            for sub in sub_replies:
                add(sub, root, True)
            if not sub_replies:
                break
        if progress and index % 20 == 0:
            progress(f"楼中楼 {index}/{len(roots)} 累计{len(rows)}条")

    if not rows:
        raise CrawlError("没有取到评论：评论区可能已关闭、需要登录，或视频无评论。")
    return rows
