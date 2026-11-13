# 评论模块

## 能力

两种模式：

| 模式 | 命令 | 取多少 | 适用 |
| --- | --- | --- | --- |
| 抽样 | `comments` | 前 N 页 / N 条 | 快速看风向 |
| 全量 | `comments-batch` | 游标翻到底 + 楼中楼 | 正式语料 |

主评论走 `/x/v2/reply/wbi/main` 的 `pagination_str` 游标，楼中楼走
`/x/v2/reply/reply` 按根评论分页。**必须登录**：匿名调用只返回 3 条就标记结束。

## 命令

```bash
# 抽样
python3 -m bili_research comments BV1xxxxxxxxx --pages 3 --limit 60

# 全量批量（清单沿用 batch 的格式，含 group）
python3 -m bili_research comments-batch examples/video_list.example.json \
        --out comments --workers 2 --max-sub-pages 8
```

输出：每条视频一个 `<分组>__<BV号>.csv`，外加合并的 `all_comments.csv`；
重复运行会跳过已有结果的视频，`--force` 才重采。

## 输出字段

`分组`、`BV号`、`标题`、`评论ID`、`根评论ID`、`用户`（脱敏）、`用户ID`（不可逆哈希）、
`正文`、`点赞`、`回复数`、`时间`、`时间文本`、`是否楼中楼`。

写飞书时额外带一列 `药物`：由人工或外部字典按 BV 号标注该视频讨论的药品，
多药物对比视频写 `多药物：A/B/C`。导出器只做透传，不做猜测。

## 为什么不能靠 pn 翻页

`/x/v2/reply?pn=` 这条老接口在大约 2000 条、100 页左右就返回空，
热门视频（几千上万条）翻不到底。游标接口没有这个天花板，所以全量只用它。

## 写入飞书

评论按组落到 `评论-供给侧` / `评论-需求侧` 子表，一行一条，带 BV 号与标题，便于跨视频筛选。

```bash
python3 -m bili_research comments BV1xxxxxxxxx --output comments.csv
python3 -m bili_research push-feishu --url "<表格链接>" --corpus corpus --comments comments.csv
```

## 边界

- 楼中楼每个根评论默认最多 8 页（160 条），超长对话按需调 `--max-sub-pages`；
- 请求间隔建议不低于 0.3 秒，连续高速会触发 -352 风控；
- 评论区关闭或无评论时返回明确错误；
- 不处理验证码。
