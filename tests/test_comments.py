import unittest

from bili_research.collectors.comments import mask_user, user_id


class CommentTest(unittest.TestCase):
    def test_mask(self):
        self.assertEqual(mask_user("张三"), "张*")
        self.assertEqual(mask_user("王小明"), "王*明")
        self.assertEqual(mask_user(""), "匿名用户")

    def test_user_id_stable_and_opaque(self):
        self.assertEqual(user_id(123), user_id("123"))
        self.assertNotIn("123", user_id(123))


if __name__ == "__main__":
    unittest.main()
