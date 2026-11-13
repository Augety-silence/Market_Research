import unittest

from bili_research.exporters.feishu_sheets import sheet_title, subtitle_rows, video_rows


class FeishuExportTest(unittest.TestCase):
    def test_sheet_title_strips_illegal_chars(self):
        name = sheet_title('减重药：怎么选/有效吗？*[上]', "BV1z44n6bEpU")
        self.assertTrue(name.endswith("-BV1z44n6bEpU"))
        self.assertNotRegex(name, r'[\\/?*\[\]:]')

    def test_sheet_title_truncates_long_title(self):
        name = sheet_title("很长的标题" * 10, "BV1z44n6bEpU")
        self.assertLessEqual(len(name), 24 + 13)

    def test_subtitle_rows_numbering(self):
        rows = subtitle_rows([{"from": 0.0, "to": 1.5, "content": "你好"}])
        self.assertEqual(rows, [[1, 0.0, 1.5, "你好"]])

    def test_video_rows_keep_numbers(self):
        rows = video_rows([{"分组": "a", "BV号": "BV1", "标题": "t", "UP主": "u",
                            "时长秒": 10, "播放": 5, "评论": 1, "字幕段数": 2,
                            "字数": 8, "覆盖率": 1.0, "来源": "AI字幕"}])
        self.assertEqual(rows[0][5], 10)
        self.assertEqual(rows[0][10], 1.0)


if __name__ == "__main__":
    unittest.main()
