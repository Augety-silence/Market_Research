import unittest

from bili_research.subtitles import char_count, coverage, punctuate, to_srt

SEGMENTS = [
    {"from": 0.0, "to": 2.0, "content": "大家好"},
    {"from": 2.1, "to": 4.0, "content": "今天聊聊减肥药"},
    {"from": 5.0, "to": 7.0, "content": "先看第一个问题"},
    {"from": 7.1, "to": 9.0, "content": "它到底有没有用"},
    {"from": 12.0, "to": 14.0, "content": "我们查了文献"},
]


class SubtitleTest(unittest.TestCase):
    def test_srt_numbering_and_timestamps(self):
        srt = to_srt(SEGMENTS[:2])
        self.assertIn("1\n00:00:00,000 --> 00:00:02,000\n大家好", srt)
        self.assertIn("2\n00:00:02,100 --> 00:00:04,000", srt)

    def test_punctuate_produces_paragraphs(self):
        paras = punctuate(SEGMENTS)
        self.assertTrue(paras)
        self.assertTrue(all(p.endswith(("。", "？")) for p in paras))

    def test_coverage(self):
        self.assertEqual(coverage(SEGMENTS, 14), 1.0)
        self.assertAlmostEqual(coverage(SEGMENTS, 28), 0.5)
        self.assertEqual(coverage([], 100), 0.0)

    def test_char_count_ignores_punctuation(self):
        self.assertEqual(char_count("你好，世界！"), 4)


if __name__ == "__main__":
    unittest.main()
