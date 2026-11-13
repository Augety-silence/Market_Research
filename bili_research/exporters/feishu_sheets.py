"""把采集结果写入飞书电子表格（依赖 lark-cli，可选能力）。

工作簿约定见 docs/features/feishu-sheets.md：
- ``汇总-视频清单``：所有视频一行一条；
- ``>>>供给侧`` / ``>>>需求侧``：分区表；
- ``<标题>-<BV号>``：每个视频一张子表，正文是字幕逐段表；
- ``评论-供给侧`` / ``评论-需求侧``：评论一行一条（由评论模块写入）。
"""

from __future__ import annotations

import json
import re
import subprocess
import uuid
from datetime import date
from pathlib import Path

from ..collectors.subtitles import char_count

SECTION_PREFIX = ">>>"
SUMMARY_SHEET = "汇总-视频清单"
COMMENT_SHEETS = {"商家推广": "评论-供给侧", "需求侧科普": "评论-需求侧"}
COMMENT_ORDER = ("评论-供给侧", "评论-需求侧")

VIDEO_COLUMNS = ["序号", "分组", "BV号", "标题", "UP主", "时长(秒)", "播放",
                 "评论数", "字幕段数", "字数", "覆盖率", "来源"]
SUBTITLE_COLUMNS = ["序号", "开始(秒)", "结束(秒)", "正文"]
COMMENT_COLUMNS = ["BV号", "标题", "药物", "分组", "评论ID", "根评论ID", "用户", "时间",
                   "点赞", "回复数", "是否楼中楼", "正文"]

_ILLEGAL = re.compile(r'[\\/?*\[\]:]')


def sheet_title(title: str, bvid: str, limit: int = 24) -> str:
    """``<标题>-<BV号>``；去掉表格不允许的字符，标题过长时截断。"""
    clean = _ILLEGAL.sub(" ", title or "").strip()
    clean = re.sub(r"\s+", " ", clean)[:limit].strip()
    return f"{clean or '未命名'}-{bvid}"


class FeishuSheets:
    """薄封装：所有写操作都通过 lark-cli 完成。"""

    def __init__(self, url: str, command: str = "lark-cli"):
        self.url = url
        self.command = command
        self._sheets: dict[str, dict] = {}

    # ---- 基础调用 -------------------------------------------------
    def _run(self, *args: str) -> dict:
        proc = subprocess.run(
            [self.command, "sheets", *args, "--format", "json"],
            capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"lark-cli 调用失败：{proc.stderr.strip()[:300]}")
        payload = json.loads(proc.stdout)
        if not payload.get("ok"):
            raise RuntimeError(f"飞书接口报错：{payload.get('error')}")
        return payload.get("data") or {}

    def info(self, refresh: bool = False) -> dict[str, dict]:
        if refresh or not self._sheets:
            data = self._run("+workbook-info", "--url", self.url)
            self._sheets = {s["sheet_name"]: s for s in data.get("sheets", [])}
        return self._sheets

    def ensure_sheet(self, name: str, index: int | None = None,
                     rows: int = 200, cols: int = 20) -> str:
        sheets = self.info()
        if name in sheets:
            return sheets[name]["sheet_id"]
        args = ["+sheet-create", "--url", self.url, "--title", name,
                "--row-count", str(max(rows, 200)), "--col-count", str(cols)]
        if index is not None:
            args += ["--index", str(index)]
        data = self._run(*args)
        sheet_id = data.get("sheet_id") or data.get("sheet", {}).get("sheet_id", "")
        self.info(refresh=True)
        return sheet_id

    def write_table(self, name: str, rows: list[list], header: list[str],
                    index: int | None = None, start_row: int = 1) -> None:
        """把 header + rows 写进子表指定行起，数值保持数值类型。"""
        cols = len(header)
        self.ensure_sheet(name, index=index, rows=len(rows) + start_row + 9, cols=cols + 2)
        sheet = self.info().get(name, {})
        need = start_row + len(rows) + 5
        if sheet.get("row_count", 0) < need:
            # 单次插入太多行会被拒，按 5000 行一批追加
            missing = need - sheet["row_count"]
            while missing > 0:
                step = min(5000, missing)
                self._run("+dim-insert", "--url", self.url, "--sheet-id", sheet["sheet_id"],
                          "--position", str(max(1, sheet["row_count"])),
                          "--count", str(step))
                sheet = self.info(refresh=True).get(name, {})
                missing -= step
            self.info(refresh=True)
        last_col = chr(ord("A") + cols - 1)
        payload = [[{"value": h} for h in header]]
        payload += [[{"value": v} for v in row] for row in rows]
        # 一次写太多会被网关截断，按 800 行切片写
        for offset in range(0, len(payload), 800):
            chunk = payload[offset:offset + 800]
            first = start_row + offset
            cell_range = f"A{first}:{last_col}{first + len(chunk) - 1}"
            # lark-cli 只接受当前目录下的相对路径，所以落在 cwd 的临时文件里
            path = Path.cwd() / f".bili_payload_{uuid.uuid4().hex}.json"
            path.write_text(json.dumps(chunk, ensure_ascii=False), encoding="utf-8")
            try:
                self._run("+cells-set", "--url", self.url, "--sheet-name", name,
                          "--range", cell_range, "--cells", f"@./{path.name}")
            finally:
                path.unlink(missing_ok=True)
        self.info(refresh=True)

    def write_info(self, name: str, pairs: list[tuple[str, object]]) -> None:
        """在 A 列起写一个两列的信息块（字段 / 值）。"""
        cells = [[{"value": k}, {"value": v}] for k, v in pairs]
        path = Path.cwd() / f".bili_payload_{uuid.uuid4().hex}.json"
        path.write_text(json.dumps(cells, ensure_ascii=False), encoding="utf-8")
        try:
            self._run("+cells-set", "--url", self.url, "--sheet-name", name,
                      "--range", f"A1:B{len(cells)}", "--cells", f"@./{path.name}")
        finally:
            path.unlink(missing_ok=True)

    def clear(self, name: str) -> None:
        """清空子表内容（只清值，不动行列结构与样式）。"""
        sheet = self.info().get(name)
        if not sheet:
            return
        self._run("+cells-clear", "--url", self.url, "--sheet-id", sheet["sheet_id"],
                  "--range", f"A1:Z{max(200, sheet.get('row_count', 200))}",
                  "--scope", "content", "--yes")

    def reorder(self, names: list[str]) -> None:
        """按给定顺序重排子表；未列出的子表保持原有相对顺序排在后面。"""
        current = [s["sheet_name"] for s in
                   sorted(self.info(refresh=True).values(), key=lambda s: s["index"])]
        target = [n for n in names if n in current] + [n for n in current if n not in names]
        for position, name in enumerate(target):
            if current[position] != name:
                self._run("+sheet-move", "--url", self.url, "--sheet-name", name,
                          "--index", str(position))
                current.remove(name)
                current.insert(position, name)
        self.info(refresh=True)


def _group_key(group: str) -> str:
    return "需求侧科普" if "需求" in group else "商家推广"


def video_rows(rows: list[dict]) -> list[list]:
    out = []
    for i, r in enumerate(rows, 1):
        out.append([i, r.get("分组", ""), r.get("BV号", ""), r.get("标题", ""),
                    r.get("UP主", ""), r.get("时长秒", 0), r.get("播放", 0),
                    r.get("评论", 0), r.get("字幕段数", 0), r.get("字数", 0),
                    r.get("覆盖率", ""), r.get("来源", "")])
    return out


def subtitle_rows(segments: list[dict]) -> list[list]:
    def num(value):
        return value if isinstance(value, (int, float)) else ""

    return [[i, num(seg.get("from")), num(seg.get("to")), seg.get("content", "")]
            for i, seg in enumerate(segments, 1)]


def video_info(data: dict, row: dict, collected_on: str = "") -> list[tuple[str, object]]:
    """视频子表顶部的信息块：字段 / 值。"""
    return [
        ("标题", data.get("title", row.get("标题", ""))),
        ("BV号", data.get("bvid", row.get("BV号", ""))),
        ("UP主", data.get("owner", row.get("UP主", ""))),
        ("时长(秒)", data.get("duration", row.get("时长秒", 0))),
        ("播放", data.get("view", row.get("播放", 0))),
        ("评论数", data.get("reply", row.get("评论", 0))),
        ("字幕段数", len(data.get("segments") or [])),
        ("字数", row.get("字数", "")),
        ("覆盖率", row.get("覆盖率", "")),
        ("来源", row.get("来源", "") or ("音频转写" if row.get("状态") == "asr" else "AI字幕")),
        ("采集日期", collected_on),
    ]


def comment_rows(rows: list[dict]) -> list[list]:
    def flag(value) -> str:
        return "是" if str(value).lower() in ("1", "true", "是") else "否"

    return [[r.get("BV号", ""), r.get("标题", ""), r.get("药物", ""), r.get("分组", ""),
             r.get("评论ID", ""), r.get("根评论ID", ""), r.get("用户", ""),
             r.get("时间文本") or r.get("时间", ""), r.get("点赞", 0),
             r.get("回复数", 0), flag(r.get("是否楼中楼")), r.get("正文", "")]
            for r in rows]


def export_workbook(url: str, corpus: Path, index_rows: list[dict],
                    comments: list[dict] | None = None, collected_on: str = "",
                    command: str = "lark-cli", only_comments: bool = False) -> dict:
    """按约定把一份语料目录推到飞书工作簿。

    返回统计：创建/更新的子表数量，便于调用方校验。
    """
    collected_on = collected_on or date.today().isoformat()
    book = FeishuSheets(url, command=command)
    created = 0
    order: list[str] = []
    if not only_comments:
        book.ensure_sheet(SUMMARY_SHEET, index=0)
        book.write_table(SUMMARY_SHEET, video_rows(index_rows), VIDEO_COLUMNS, index=0)
        created = 1
        order = [SUMMARY_SHEET]
    for group in (() if only_comments else ("商家推广", "需求侧科普")):
        section = f"{SECTION_PREFIX}{'供给侧' if group == '商家推广' else '需求侧'}"
        book.ensure_sheet(section)
        order.append(section)
        for row in [r for r in index_rows if _group_key(r.get("分组", "")) == group]:
            source = corpus / row["文件"]
            if not source.exists():
                continue
            data = json.loads(source.read_text(encoding="utf-8"))
            name = sheet_title(data.get("title", row.get("标题", "")), data["bvid"])
            segments = data.get("segments") or []
            book.ensure_sheet(name)
            book.clear(name)
            book.write_info(name, video_info(data, row, collected_on))
            book.write_table(name, subtitle_rows(segments), SUBTITLE_COLUMNS,
                             start_row=len(video_info(data, row, collected_on)) + 3)
            order.append(name)
            created += 1

    if comments:
        buckets: dict[str, list[dict]] = {}
        seen: set[tuple[str, str]] = set()
        for row in comments:
            key = (str(row.get("BV号", "")), str(row.get("评论ID", "")))
            if key in seen:  # 多次采集/分片合并且目录里同时有合并文件时兜底去重
                continue
            seen.add(key)
            sheet = COMMENT_SHEETS[_group_key(row.get("分组", ""))]
            buckets.setdefault(sheet, []).append(row)
        for name in COMMENT_ORDER:
            subset = buckets.get(name)
            if subset:
                book.ensure_sheet(name)
                book.clear(name)
                book.write_table(name, comment_rows(subset), COMMENT_COLUMNS)
                created += 1
                order.append(name)
    if not only_comments:
        book.reorder(order)
    return {"sheets": created, "videos": len(index_rows)}
