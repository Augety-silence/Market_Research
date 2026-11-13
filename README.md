# Market Research · B 站素材采集

面向市场调研的 B 站视频素材采集工具：拉取视频元信息、**AI 字幕正文**、**评论区**，并输出可直接做文本分析的语料。

整套流程**纯 HTTP 实现，不需要浏览器接管、不需要点击页面、不需要 Playwright**，因此可以跑在任何 agent、服务器或定时任务里。

## 为什么不用浏览器方案

浏览器方案依赖“已登录的浏览器 + 页面点击字幕菜单 + 抓网络请求”，换一台机器或换一个 agent 就跑不动。这里把同一件事拆成三步纯接口调用：

1. `view` 接口拿 `aid` / `cid` / 时长；
2. `player/wbi/v2`（带 WBI 签名）拿字幕轨列表；
3. 直接下载字幕 JSON（`aisubtitle.hdslb.com` 的带签名静态资源，不需要 Cookie）。

唯一的登录要求是第 2 步：B 站对匿名请求返回空字幕列表，所以需要一份你自己的 Cookie。

## 快速开始

要求 Python 3.10+，**零第三方依赖**（只用标准库）。

```bash
cd Market_Research
python3 -m bili_research check --cookie-file ~/.bili_cookie   # 先确认登录态
python3 -m bili_research subtitle BV1xxxxxxxxx --out corpus
```

### 准备 Cookie（只做一次）

1. 浏览器登录 B 站，打开任意视频页；
2. `F12` → Application/存储 → Cookies → `https://www.bilibili.com`；
3. 复制 `SESSDATA`（可选再带 `bili_jct`、`buvid3`），拼成一行：

```
SESSDATA=xxxx; bili_jct=yyyy; buvid3=zzzz
```

4. 存到项目外的私有文件并收紧权限：

```bash
chmod 600 ~/.bili_cookie
```

也支持浏览器插件导出的 Netscape 格式 `cookies.txt`，或用环境变量 `BILI_COOKIE`。

在其他 agent / CI 里，可以从密钥管理直接管道传入，不落盘：

```bash
get-cookie-command | python3 -m bili_research check --cookie-file -
```

> 工具不会打印、上传或写入日志 Cookie；请求只发往 `api.bilibili.com` 与字幕/音轨 CDN。

## 命令

```bash
# 检查登录态
python3 -m bili_research check

# 单条视频
python3 -m bili_research subtitle BV1xxxxxxxxx --group 商家推广 --out corpus

# 批量：清单为 JSON [{group,bvid}] 或每行一个 BV 号/链接
python3 -m bili_research batch examples/video_list.example.json --out corpus

# 评论（默认脱敏昵称、按热度）
python3 -m bili_research comments BV1xxxxxxxxx --pages 3 --limit 60

# 无字幕视频：先下音轨，再交给任意 ASR
python3 -m bili_research audio BV1xxxxxxxxx --output demo.m4s
```

通用参数：`--cookie-file`、`--interval`（默认 2.5 秒）。

## 输出

```
corpus/
  商家推广__BV1xxxxxxxxx.json   # 原始元信息 + segments（from/to/content）
  商家推广__BV1xxxxxxxxx.srt    # 标准字幕
  商家推广__BV1xxxxxxxxx.txt    # 还原标点后的正文，按段落
  index.csv / index.json        # 总表：分组、时长、段数、字数、覆盖率、状态
```

`index.csv` 的「覆盖率」= 最后一段结束时间 / 视频时长，用来判断字幕是否完整；低于 0.5 会被判为异常。

## 反爬与数据质量

- **串片校验**：字幕地址必须同时包含该视频的 `aid` 与 `cid`，否则拒绝写入。B 站字幕接口在某些情况下会返回其他视频的字幕，这是最容易踩的坑。
- **限速**：默认 2.5 秒/次，带随机抖动；`--interval` 可调，不建议低于 1 秒。
- **风控识别**：HTTP 412/429 或业务码 `-352/-412/-509` 直接停止并提示，不自动绕过验证码。
- **登录失效**：业务码 `-101` 提示更新 Cookie。
- **重试策略**：网络错误由调用方重跑（批量模式单条失败不影响整体，并写入 `index.csv` 状态列）。

## 没有字幕的视频

部分视频本身没有 AI 字幕轨（播放器里没有字幕入口）。这类视频只能走音频转写：

```bash
python3 -m bili_research audio BV1xxxxxxxxx --output demo.m4s
ffmpeg -i demo.m4s -vn -ac 1 -ar 16000 demo.mp3
# 交给 whisper / 云 ASR / 任意转写服务
```

转写稿与官方字幕的区别要在论文里说明：错字、漏句、专有名词误差风险更高，关键引文需回听核对。

## 目录结构

```
bili_research/
  client.py     # 限速、重试、登录态、WBI 签名请求
  wbi.py        # WBI 签名算法
  video.py      # 元信息、字幕轨、音轨
  subtitles.py  # 解析、SRT、标点还原、覆盖率
  comments.py   # 评论分页与脱敏
  store.py      # 落盘与总表
  cli.py        # 命令行
tests/          # 16 个离线单测，不需要网络与 Cookie
examples/       # 清单样例与输出样例
docs/           # 研究框架说明
```

## 测试

```bash
python3 -m unittest discover -s tests -v
```

## 已知限制

- 多 P 视频只取第 1 P；需要其他分 P 时改 `--` 参数或调用 `video.video_meta` 里的 `pages`；
- 不支持 `b23.tv` 短链，请先展开成 `BV` 号；
- 只读取播放器提供的字幕轨（AI 字幕或 UP 主上传的 CC），不做语音识别；
- 评论接口按页返回，深翻会受限，批量研究建议用「热度前 N 页 + 时间窗」而不是全量翻到底；
- 不处理验证码、不绕过风控，触发即停止。

## 合规边界

- 只采集公开可见内容，不绕过验证码、不破解付费/充电专属内容；
- 默认低频、可配置间隔，避免对平台造成压力；
- 评论昵称默认脱敏，只保留不可逆的用户 ID；
- **采集到的字幕与评论属于原作者的表达，不要公开再分发**；论文引用需标注来源与时间。
