"""字幕解析、SRT 导出与标点还原。

AI 字幕是按短语切好的裸文本，没有标点。这里用三条信号还原断句：
相邻段的静音长度、句末语气词、单句长度上限。
"""

from __future__ import annotations

import re

SENT_GAP = 0.55        # 段间静音 >= 0.55s 视为句间
COMMA_LEN = 12         # 句内每约 12 字补逗号
MAX_LEN = 50           # 单句长度上限
END_WORDS = "吗呢吧啊呀啦嘛呗"
QUESTION_TAILS = ("什么", "为什么", "怎么办", "怎么", "多少", "咋", "哪",
                  "是不是", "有没有", "要不要")
STARTERS = (
    "然后", "结果", "所以", "但是", "因为", "其实", "反正", "而且", "后来", "现在",
    "今天", "这期", "大家", "不过", "于是", "接着", "最后", "另外", "毕竟", "如果",
    "虽然", "只有", "还有", "就是", "这个", "那个", "我们", "你们", "他们",
)


def to_srt(segments: list[dict]) -> str:
    def stamp(sec: float) -> str:
        ms = int(round(sec * 1000))
        h, ms = divmod(ms, 3_600_000)
        m, ms = divmod(ms, 60_000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    lines = []
    for i, seg in enumerate(segments, 1):
        lines.append(str(i))
        lines.append(f"{stamp(seg['from'])} --> {stamp(seg['to'])}")
        lines.append(seg["content"])
        lines.append("")
    return "\n".join(lines)


def split_sentences(segments: list[dict]) -> list[str]:
    sentences: list[str] = []
    cur = ""
    prev_end: float | None = None
    for seg in segments:
        text = (seg.get("content") or "").strip()
        if not text:
            continue
        gap = 99.0 if prev_end is None else seg["from"] - prev_end
        starts_new = gap >= SENT_GAP or (len(cur) >= 10 and text.startswith(STARTERS))
        if cur and (starts_new or len(cur) >= MAX_LEN):
            sentences.append(cur)
            cur = ""
        if cur:
            sep = "，" if len(cur) >= COMMA_LEN else ""
            cur = cur + sep + text
        else:
            cur = text
        prev_end = seg["to"]
        if text[-1] in END_WORDS and len(cur) >= 10:
            sentences.append(cur)
            cur = ""
    if cur:
        sentences.append(cur)
    return sentences


def finish(sentence: str) -> str:
    s = sentence.strip("，。、；：!?！？ ")
    if not s:
        return ""
    question = s.endswith(("吗", "呢", "么")) or s.endswith(QUESTION_TAILS)
    return s + ("？" if question else "。")


def punctuate(segments: list[dict], sentences_per_para: int = 4) -> list[str]:
    sentences = [finish(s) for s in split_sentences(segments)]
    sentences = [s for s in sentences if s]
    return ["".join(sentences[i:i + sentences_per_para])
            for i in range(0, len(sentences), sentences_per_para)]


def char_count(text: str) -> int:
    """与项目里的统计口径一致：不计空白与标点。"""
    return len(re.sub(r"[\s\W]", "", text, flags=re.UNICODE))


def coverage(segments: list[dict], duration: int) -> float:
    """最后一段的结束时间 / 视频时长；用于判断字幕是否完整。"""
    if not segments or duration <= 0:
        return 0.0
    return round(min(1.0, segments[-1]["to"] / duration), 3)
