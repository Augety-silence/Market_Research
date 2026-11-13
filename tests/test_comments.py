import unittest

from bili_research.collectors.comments import (fetch_all_comments, format_time,
                                               mask_user, user_id)


class _FakeClient:
    """按调用顺序返回预置响应，并记录请求参数。"""

    def __init__(self, main_pages, sub_pages=None):
        self.main_pages = list(main_pages)
        self.sub_pages = sub_pages or {}
        self.calls = []

    def get_json(self, path, params=None, signed=False, referer=""):
        self.calls.append((path, dict(params or {})))
        if path.endswith("/wbi/main"):
            return self.main_pages.pop(0)
        root = str((params or {}).get("root"))
        pn = int((params or {}).get("pn", 1))
        pages = self.sub_pages.get(root, [])
        return pages[pn - 1] if pn - 1 < len(pages) else {"replies": []}


def _reply(rpid, text, rcount=0):
    return {"rpid": rpid, "member": {"uname": "王小明", "mid": 42},
            "content": {"message": text}, "like": 3, "rcount": rcount,
            "ctime": 1700000000}


class CommentTest(unittest.TestCase):
    def test_mask(self):
        self.assertEqual(mask_user("张三"), "张*")
        self.assertEqual(mask_user("王小明"), "王*明")
        self.assertEqual(mask_user(""), "匿名用户")

    def test_user_id_stable_and_opaque(self):
        self.assertEqual(user_id(123), user_id("123"))
        self.assertNotIn("123", user_id(123))

    def test_format_time(self):
        self.assertEqual(format_time(0), "")
        self.assertRegex(format_time(1700000000), r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")

    def test_full_crawl_follows_cursor_and_sub_replies(self):
        client = _FakeClient(
            main_pages=[
                {"replies": [_reply(1, "主评论一", rcount=25)],
                 "cursor": {"is_end": False,
                            "pagination_reply": {"next_offset": "AAA"}}},
                {"replies": [_reply(2, "主评论二")],
                 "cursor": {"is_end": True, "pagination_reply": {}}},
                {"replies": [_reply(3, "主评论三")],
                 "cursor": {"is_end": True, "pagination_reply": {}}},
            ],
            sub_pages={"1": [{"replies": [_reply(11, "楼中楼", rcount=0)]},
                             {"replies": [_reply(12, "楼中楼二")]}]},
        )
        rows = fetch_all_comments(client, 100, "BV1test", title="标题",
                                  group="商家推广", max_sub_pages=5)
        ids = [r["评论ID"] for r in rows]
        # 第二页 is_end=True 就停，第三页不会被请求
        self.assertEqual(ids, ["1", "2", "11", "12"])
        self.assertTrue(all(r["分组"] == "商家推广" and r["标题"] == "标题" for r in rows))
        self.assertEqual([r["是否楼中楼"] for r in rows], [False, False, True, True])
        # 根评论 1 的 rcount=25 → 2 页楼中楼
        sub_calls = [c for c in client.calls if c[0] == "/x/v2/reply/reply"]
        self.assertEqual([c[1]["pn"] for c in sub_calls], [1, 2])
        self.assertTrue(all(c[1]["root"] == "1" for c in sub_calls))


if __name__ == "__main__":
    unittest.main()
