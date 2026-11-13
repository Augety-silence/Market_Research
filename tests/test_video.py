import unittest

from bili_research.collectors.video import extract_bvid, pick_chinese, track_url_ok


class VideoTest(unittest.TestCase):
    def test_extract_bvid_from_url(self):
        self.assertEqual(
            extract_bvid("https://www.bilibili.com/video/BV1z44n6bEpU/?spm=1"),
            "BV1z44n6bEpU")

    def test_extract_bvid_rejects_short_link(self):
        with self.assertRaises(Exception):
            extract_bvid("https://b23.tv/abcd")

    def test_pick_chinese_prefers_ai_track(self):
        tracks = [
            {"lan": "en-US", "lan_doc": "English", "subtitle_url": "//x/en"},
            {"lan": "zh-CN", "lan_doc": "中文（中国）", "subtitle_url": "//x/zh"},
            {"lan": "ai-zh", "lan_doc": "中文（自动生成）", "subtitle_url": "//x/ai"},
        ]
        self.assertEqual(pick_chinese(tracks)["lan"], "ai-zh")

    def test_track_url_must_match_aid_and_cid(self):
        ok = "//aisubtitle.hdslb.com/bfs/ai_subtitle/prod/112/2024/1/abc.json"
        self.assertTrue(track_url_ok(ok, 112, 2024))
        self.assertFalse(track_url_ok(ok, 112, 9999))


if __name__ == "__main__":
    unittest.main()
