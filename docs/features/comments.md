# 评论模块

## 能力

按页采集视频主评论，支持热度/时间排序、条数上限、楼中楼预览，昵称默认脱敏。

## 命令

```bash
python3 -m bili_research comments BV1xxxxxxxxx --pages 3 --limit 60
python3 -m bili_research comments BV1xxxxxxxxx --sort 0 --include-preview
```

## 输出字段

`评论ID`、`用户`（脱敏）、`用户ID`（不可逆哈希）、`正文`、`点赞`、`回复数`、`时间`、`是否楼中楼`、`根评论ID`。

## 写入飞书

评论按组落到 `评论-供给侧` / `评论-需求侧` 子表，一行一条，带 BV 号与标题，便于跨视频筛选。

```bash
python3 -m bili_research comments BV1xxxxxxxxx --output comments.csv
python3 -m bili_research push-feishu --url "<表格链接>" --corpus corpus --comments comments.csv
```

## 边界

- 深翻会被限制，研究建议「热度前 N 页 + 时间窗」，不做全量翻到底；
- 评论区关闭或无评论时返回明确错误；
- 不处理验证码。
