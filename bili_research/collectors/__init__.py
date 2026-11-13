"""采集模块：每个模块负责一类内容的抓取，返回结构化数据，不直接决定存储形态。"""

from .comments import fetch_comments
from .subtitles import coverage, punctuate, to_srt
from .video import extract_bvid, get_view, subtitle_tracks, video_meta

__all__ = [
    "fetch_comments", "coverage", "punctuate", "to_srt",
    "extract_bvid", "get_view", "subtitle_tracks", "video_meta",
]
