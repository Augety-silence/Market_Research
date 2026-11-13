# Market Research

市场调研用的公开内容采集工具集。每个能力是一个独立模块，共用同一套网络层与导出层，后续新增模块不需要改动已有代码。

当前模块：

| 模块 | 状态 | 采集内容 | 文档 |
| --- | --- | --- | --- |
| 字幕 | 可用 | 视频元信息 + AI 字幕逐段文本 | [docs/features/subtitles.md](docs/features/subtitles.md) |
| 评论 | 可用 | 主评论分页、昵称脱敏、楼中楼预览 | [docs/features/comments.md](docs/features/comments.md) |
| 音轨 | 可用 | DASH 音轨下载，供无字幕视频做转写 | [docs/features/subtitles.md](docs/features/subtitles.md) |
| 飞书表格 | 可用 | 按约定把语料写入电子表格，每类内容一张子表 | [docs/features/feishu-sheets.md](docs/features/feishu-sheets.md) |

研究设计与字段口径见 [docs/research-framework.md](docs/research-framework.md)，仓库约定见 [docs/conventions.md](docs/conventions.md)。

## 设计约束

- **纯 HTTP，不依赖浏览器接管**：不需要 Playwright、不需要点击页面，任何 agent / 服务器 / 定时任务都能跑；
- **零第三方依赖**：只用 Python 标准库，Python 3.10+；
- **模块边界清晰**：采集器只负责拿数据，导出器只负责写存储，新增模块不动老模块；
- **失败可见**：风控、登录失效、串片、覆盖率不足都显式报错，不静默降级。

## 快速开始

```bash
python3 -m bili_research check --cookie-file ~/.bili_cookie

# 字幕：单条 / 批量
python3 -m bili_research subtitle BV1xxxxxxxxx --out corpus
python3 -m bili_research batch examples/video_list.example.json --out corpus

# 评论
python3 -m bili_research comments BV1xxxxxxxxx --pages 3 --limit 60

# 写入飞书工作簿（需本机有 lark-cli）
python3 -m bili_research push-feishu --url "<表格链接>" --corpus corpus
```

Cookie 三种给法：`--cookie-file <路径>`、环境变量 `BILI_COOKIE`、`--cookie-file -` 从标准输入读取（适合接密钥管理）。工具不会打印或上传 Cookie。

## 目录结构

```
bili_research/
  core/         # HTTP 客户端、WBI 签名、错误类型（所有模块共用）
  collectors/   # 采集器：subtitles / comments / video
  exporters/    # 导出器：local_csv / feishu_sheets
  cli.py        # 命令行，按子命令挂载各模块
docs/           # 约定、功能说明、研究框架
tests/          # 离线单测，不联网、不需要 Cookie
examples/       # 清单样例、输出样例
```

## 新增一个采集模块

1. 在 `collectors/` 下新建模块，函数返回结构化 dict / list，不写存储；
2. 如需落地，在 `exporters/` 加对应写出逻辑（或复用现有 CSV / 飞书表格）；
3. 在 `cli.py` 注册子命令；
4. 在 `tests/` 补离线用例，在 `docs/features/` 写一页说明，并更新上表。

## 测试

```bash
python3 -m unittest discover -s tests -v
```

## 合规边界

- 只采集公开可见内容，不绕过验证码、不破解付费/充电专属内容；
- 默认低频（2.5 秒/次），可调但建议不低于 1 秒；
- 评论昵称默认脱敏，仅保留不可逆用户 ID；
- 采集到的字幕与评论属于原作者表达，**不要公开再分发**；引用需标注来源与采集时间。
