"""命令行入口：check / subtitle / batch / comments / audio。"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from .client import Client, read_cookie
from .comments import fetch_comments
from .errors import CrawlError, LoginRequired
from .store import save_unit, write_index
from .subtitles import coverage, punctuate
from .video import (audio_url, extract_bvid, fetch_subtitle, get_view,
                    pick_chinese, subtitle_tracks, track_url_ok, video_meta)


def _client(args) -> Client:
    return Client(read_cookie(getattr(args, "cookie_file", None)),
                  interval=getattr(args, "interval", 2.5))


def _write_comments(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def cmd_check(args) -> int:
    client = _client(args)
    print("登录态：", "已登录" if client.is_logged_in() else "未登录（AI 字幕接口会返回空列表）")
    return 0


def cmd_subtitle(args) -> int:
    client = _client(args)
    bvid = extract_bvid(args.video)
    client.require_login()
    view = get_view(client, bvid)
    meta = video_meta(view)
    meta["group"] = args.group
    cid = meta["cid"]
    tracks = subtitle_tracks(client, bvid, meta["aid"], cid)
    track = pick_chinese(tracks)
    if not track:
        raise CrawlError(f"{bvid} 没有中文 AI 字幕轨（共 {len(tracks)} 条轨道）。")
    url = track.get("subtitle_url") or ""
    if not track_url_ok(url, meta["aid"], cid):
        raise CrawlError("字幕地址与当前视频不匹配，已拒绝（可能是接口串片）。")
    segments = fetch_subtitle(client, url, bvid)
    cov = coverage(segments, meta["duration"])
    if cov < 0.5:
        raise CrawlError(f"字幕只覆盖到 {cov:.0%} 的时长，疑似不完整或串片。")
    paras = punctuate(segments) if not args.no_punctuate else [s["content"] for s in segments]
    row = save_unit(Path(args.out), meta, segments, paras, cov, "ok")
    write_index(Path(args.out), [row])
    print(f"{bvid} {meta['title'][:30]} -> {len(segments)} 段 / {row['字数']} 字，覆盖率 {cov}")
    return 0


def _load_list(path: str) -> list[dict]:
    raw = Path(path).read_text(encoding="utf-8").strip()
    if raw.startswith("["):
        data = json.loads(raw)
        return [{"group": d.get("group", "未分组"), "bvid": extract_bvid(d.get("bvid") or d.get("url", ""))}
                for d in data]
    items = []
    for line in raw.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            items.append({"group": "未分组", "bvid": extract_bvid(line)})
    return items


def cmd_batch(args) -> int:
    client = _client(args)
    out = Path(args.out)
    client.require_login()
    rows: list[dict] = []
    failures = 0
    for item in _load_list(args.list):
        bvid, group = item["bvid"], item["group"]
        try:
            meta = video_meta(get_view(client, bvid))
            meta["group"] = group
            tracks = subtitle_tracks(client, bvid, meta["aid"], meta["cid"])
            track = pick_chinese(tracks)
            if not track or not track.get("subtitle_url"):
                rows.append({"分组": group, "BV号": bvid, "标题": meta["title"],
                             "UP主": meta["owner"], "播放": meta.get("view", 0),
                             "评论": meta.get("reply", 0), "时长秒": meta["duration"],
                             "字幕段数": 0, "字数": 0, "覆盖率": "",
                             "状态": "无字幕轨", "来源": "", "文件": ""})
                print(f"[跳过] {bvid} 无中文 AI 字幕轨")
                continue
            url = track["subtitle_url"]
            if not track_url_ok(url, meta["aid"], meta["cid"]):
                raise CrawlError("字幕地址与视频不匹配，疑似串片")
            segments = fetch_subtitle(client, url, bvid)
            cov = coverage(segments, meta["duration"])
            if cov < 0.5:
                raise CrawlError(f"覆盖率仅 {cov:.0%}，疑似不完整")
            paras = punctuate(segments)
            rows.append(save_unit(out, meta, segments, paras, cov, "ok"))
            print(f"[成功] {bvid} {len(segments)} 段 / {rows[-1]['字数']} 字，覆盖率 {cov}")
        except (CrawlError, LoginRequired) as exc:
            failures += 1
            print(f"[失败] {bvid} {exc}")
            rows.append({"分组": group, "BV号": bvid, "标题": "", "UP主": "",
                         "播放": "", "评论": "", "时长秒": "", "字幕段数": 0,
                         "字数": 0, "覆盖率": "", "状态": f"失败：{exc}",
                         "来源": "", "文件": ""})
        finally:
            write_index(out, rows)
    ok = sum(1 for r in rows if r["状态"] == "ok")
    print(f"\n完成：{ok}/{len(rows)} 条取到字幕，{failures} 条失败。结果目录：{out}")
    return 0 if failures == 0 else 1


def cmd_comments(args) -> int:
    client = _client(args)
    bvid = extract_bvid(args.video)
    view = get_view(client, bvid)
    meta = video_meta(view)
    rows = fetch_comments(client, meta["aid"], bvid, pages=args.pages,
                          limit=args.limit, sort=args.sort,
                          keep_names=args.keep_names,
                          include_preview=args.include_preview)
    out = Path(args.output or f"comments_{bvid}.csv")
    _write_comments(out, rows)
    print(f"{bvid} 采集 {len(rows)} 条评论 -> {out}")
    return 0


def cmd_audio(args) -> int:
    client = _client(args)
    bvid = extract_bvid(args.video)
    meta = video_meta(get_view(client, bvid))
    url = audio_url(client, bvid, meta["cid"], quality=args.quality)
    out = Path(args.output or f"{bvid}.m4s")
    out.write_bytes(client.download(url, referer=f"https://www.bilibili.com/video/{bvid}/"))
    print(f"{bvid} 音轨已保存 -> {out}（可用 ffmpeg 转 mp3 后接入任意 ASR）")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bili_research",
        description="B 站视频字幕 / 评论采集（纯 HTTP，无需浏览器接管）")
    parser.add_argument("--cookie-file", help="Cookie 文件（单行或 Netscape cookies.txt）；"
                                             "也可用环境变量 BILI_COOKIE")
    parser.add_argument("--interval", type=float, default=2.5, help="请求间隔秒数，默认 2.5")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("check", help="检查登录态")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("subtitle", help="采集单条视频字幕")
    p.add_argument("video", help="BV 号或视频链接")
    p.add_argument("--group", default="未分组", help="分组名，用于输出文件前缀")
    p.add_argument("--out", default="corpus", help="输出目录")
    p.add_argument("--no-punctuate", action="store_true", help="不做标点还原")
    p.set_defaults(func=cmd_subtitle)

    p = sub.add_parser("batch", help="批量采集字幕")
    p.add_argument("list", help="视频清单：JSON [{group,bvid}] 或每行一个 BV/链接")
    p.add_argument("--out", default="corpus", help="输出目录")
    p.set_defaults(func=cmd_batch)

    p = sub.add_parser("comments", help="采集视频评论")
    p.add_argument("video", help="BV 号或视频链接")
    p.add_argument("--pages", type=int, default=3, help="最多页数，每页 20 条")
    p.add_argument("--limit", type=int, default=60, help="总条数上限")
    p.add_argument("--sort", type=int, default=2, help="2=热度，0=时间")
    p.add_argument("--keep-names", action="store_true", help="保留原始昵称（默认脱敏）")
    p.add_argument("--include-preview", action="store_true", help="附带楼中楼预览")
    p.add_argument("--output", help="CSV 路径")
    p.set_defaults(func=cmd_comments)

    p = sub.add_parser("audio", help="下载音轨（供无字幕视频做转写）")
    p.add_argument("video", help="BV 号或视频链接")
    p.add_argument("--quality", type=int, default=30216, help="30216/30232/30280")
    p.add_argument("--output", help="输出文件")
    p.set_defaults(func=cmd_audio)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except CrawlError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
