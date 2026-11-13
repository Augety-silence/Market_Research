# 字幕模块

## 能力

拉取单条或批量视频的中文 AI 字幕，输出逐段 JSON、SRT 和带标点的正文，并计算覆盖率。

## 接口路径

1. `/x/web-interface/view?bvid=` → `aid`、`cid`、时长；
2. `/x/player/wbi/v2`（WBI 签名，需登录）→ 字幕轨列表；
3. 字幕 JSON（`aisubtitle.hdslb.com` 带签名静态资源）→ `body[].from/to/content`。

## 命令

```bash
python3 -m bili_research subtitle BV1xxxxxxxxx --group 商家推广 --out corpus
python3 -m bili_research batch examples/video_list.example.json --out corpus
```

批量清单支持两种格式：

```json
[{"group": "供给侧推广", "bvid": "BV1xxxxxxxxx"}]
```

或每行一个 BV 号 / 视频链接。

## 校验

- 字幕地址必须同时包含该视频的 `aid` 与 `cid`，否则判定串片并拒绝写入；
- 覆盖率 < 0.5 判定异常；
- 单条失败不影响批量其余条目，失败原因写进 `index.csv` 的状态列。

## 没有字幕怎么办

```bash
python3 -m bili_research audio BV1xxxxxxxxx --output demo.m4s
ffmpeg -i demo.m4s -vn -ac 1 -ar 16000 demo.mp3
```

转写结果请标注「音频转写」，与官方字幕区分。
