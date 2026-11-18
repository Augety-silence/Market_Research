# Market Research

市场调研用的公开内容采集工具集。每个能力按网络、采集、导出与入口分层组织，原有字幕与评论共用HTTP客户端，季度搜索使用可选的独立浏览器适配器。

当前模块：

| 模块 | 状态 | 采集内容 | 文档 |
| --- | --- | --- | --- |
| 字幕 | 可用 | 视频元信息 + AI 字幕逐段文本 | [docs/features/subtitles.md](docs/features/subtitles.md) |
| 评论 | 可用 | 全量主评论（游标翻到底）+ 楼中楼，昵称脱敏 | [docs/features/comments.md](docs/features/comments.md) |
| 音轨 | 可用 | DASH 音轨下载，供无字幕视频做转写 | [docs/features/subtitles.md](docs/features/subtitles.md) |
| 飞书表格 | 可用 | 按约定把语料写入电子表格，每类内容一张子表 | [docs/features/feishu-sheets.md](docs/features/feishu-sheets.md) |
| 季度关键词 | 可用（可选依赖） | 日期范围搜索、精确播放量、SQLite断点、公式汇总、三产品六图 | [docs/features/quarter-search.md](docs/features/quarter-search.md) |

研究设计与字段口径见 [docs/research-framework.md](docs/research-framework.md)，仓库约定见 [docs/conventions.md](docs/conventions.md)。

## 设计约束

- **基础命令纯 HTTP、零第三方依赖**：字幕、评论、音轨只用 Python 标准库，Python 3.10+；
- **季度能力可选安装**：`pip install -e ".[quarter]"` 安装 Playwright、requests、openpyxl，使用自己的浏览器窗口；
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
python3 -m bili_research comments-batch examples/video_list.example.json --out comments

# 写入飞书工作簿（需本机有 lark-cli）
python3 -m bili_research push-feishu --url "<表格链接>" --corpus corpus
```

季度采集、恢复已有5496条记录、导出六张独立趋势图：

```bash
python3 -m pip install -e ".[quarter]"
python3 -m playwright install chromium
cp examples/quarter.config.example.json quarter.config.json
python3 -m bili_research quarter init --from-snapshot
python3 -m bili_research quarter export
# 全新采集：使用新的 output_dir，再运行 login / collect
```

季度采集与飞书同步完整步骤见 [季度采集说明](docs/features/quarter-search.md)。配置示例中的飞书资源ID留空，运行配置、凭证与浏览器登录状态不提交到仓库。

Cookie 三种给法：`--cookie-file <路径>`、环境变量 `BILI_COOKIE`、`--cookie-file -` 从标准输入读取（适合接密钥管理）。工具不会打印或上传 Cookie。

## 目录结构

```
bili_research/
  core/         # HTTP客户端、WBI、错误类型；季度浏览器/飞书API适配器
  collectors/   # 采集器：subtitles / comments / video / quarter_search
  exporters/    # 语料导出；季度SQLite / CSV / Excel / 飞书同步
  cli.py        # 统一命令行，quarter由quarter_runner编排
docs/           # 约定、功能说明、研究框架
tests/          # 离线单测，不联网、不需要 Cookie
examples/       # 清单、输出、季度配置和已有快照
scripts/        # macOS季度采集启动脚本
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

季度导出测试需要 `.[quarter]`；浏览器测试还需安装Chromium，导航全部拦截到本地HTML。未安装可选依赖时相关测试会跳过。

## 合规边界

- 只采集公开可见内容，不绕过验证码、不破解付费/充电专属内容；
- 默认低频（2.5 秒/次），可调但建议不低于 1 秒；
- 评论昵称默认脱敏，仅保留不可逆用户 ID；
- 采集到的字幕与评论属于原作者表达，**不要公开再分发**；引用需标注来源与采集时间。
