"""把采集结果落盘：原始 JSON、SRT、带标点正文与总表。"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from ..collectors.subtitles import char_count

INDEX_FIELDS = [
    "序号", "分组", "BV号", "标题", "UP主", "播放", "评论", "时长秒",
    "字幕段数", "字数", "覆盖率", "状态", "来源", "文件",
]


def unit_name(group: str, bvid: str) -> str:
    safe_group = (group or "未分组").replace("/", "_").strip()
    return f"{safe_group}__{bvid}"


def save_unit(outdir: Path, meta: dict, segments: list[dict], paras: list[str],
              coverage: float, status: str, source: str = "AI字幕") -> dict:
    outdir.mkdir(parents=True, exist_ok=True)
    stem = unit_name(meta.get("group", ""), meta["bvid"])
    raw = {
        "bvid": meta["bvid"],
        "aid": meta["aid"],
        "cid": meta["cid"],
        "title": meta["title"],
        "owner": meta["owner"],
        "duration": meta["duration"],
        "view": meta.get("view", 0),
        "reply": meta.get("reply", 0),
        "status": status,
        "source": source,
        "coverage": coverage,
        "segments": segments,
    }
    (outdir / f"{stem}.json").write_text(
        json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
    if segments:
        from ..collectors.subtitles import to_srt
        (outdir / f"{stem}.srt").write_text(to_srt(segments), encoding="utf-8")
        text = "\n\n".join(paras)
        (outdir / f"{stem}.txt").write_text(text, encoding="utf-8")
        chars = char_count(text)
    else:
        text, chars = "", 0
    return {
        "分组": meta.get("group", ""),
        "BV号": meta["bvid"],
        "标题": meta["title"],
        "UP主": meta["owner"],
        "播放": meta.get("view", 0),
        "评论": meta.get("reply", 0),
        "时长秒": meta["duration"],
        "字幕段数": len(segments),
        "字数": chars,
        "覆盖率": coverage if segments else "",
        "状态": status,
        "来源": source if segments else "",
        "文件": f"{stem}.json",
    }


def write_index(outdir: Path, rows: list[dict]) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    ordered = []
    for i, row in enumerate(rows, 1):
        item = {"序号": i}
        item.update({k: row.get(k, "") for k in INDEX_FIELDS if k != "序号"})
        ordered.append(item)
    with (outdir / "index.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=INDEX_FIELDS)
        writer.writeheader()
        writer.writerows(ordered)
    (outdir / "index.json").write_text(
        json.dumps(ordered, ensure_ascii=False, indent=1), encoding="utf-8")
