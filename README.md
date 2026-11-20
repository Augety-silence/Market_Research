# Market Research

减重产品研究的独立代码包：B站季度视频、字幕和评论，Sensor Tower实际下载/收入/日活，百度指数附件导入，五维词次标注，季度权重和固定宣传特征评分，以及研究图表、飞书公式同步和PDF转纯图片PPT。

全部命令在自己的Python环境中运行，无需Aime浏览器或Aime会话。原有`bili-research`命令继续保留，新研究流水线统一使用`market-research`。

| 流程 | 代码入口 | 数据来源与运行方式 |
| --- | --- | --- |
| B站季度搜索 | `market-research bili-search` | HTTP＋WBI；逐条验证日期、精确播放量和总数 |
| B站季度搜索兼容路径 | `bili-research quarter` | 独立Playwright，适用HTTP日期过滤不生效的环境 |
| 字幕与全评论 | `market-research bili-corpus` | HTTP；主评论游标＋楼中楼；支持多P字幕 |
| 下载、商店收入、设备日活 | `market-research sensor` | Sensor Tower API，自行配置授权令牌 |
| 百度指数 | `market-research import-baidu` | 导入此前文档附件/CSV/JSON；保留来源和文件指纹 |
| 词次与五维归属 | `prepare-text` / `annotate` | jieba词次＋上下文；通用OpenAI兼容模型或人工结果 |
| 季度汇总与匹配分 | `market-research analyze` | 实际值、Top1剔除、固定特征×季度权重、滞后相关 |
| 图表 | `market-research charts` | 白底3×3图、五维雷达、合并评分图、曝光/搜索双轴图、词云 |
| 飞书读取/同步 | `feishu-workbook` / `feishu-doc` / `feishu-sync` | 飞书OpenAPI；小批写入、回读后确认断点 |
| 公式计划 | `market-research sheet-plan` | SUMIFS/COUNTIFS/AVERAGEIFS/SUMPRODUCT；无数据透视 |
| App图标 | `market-research logos` | Apple公开lookup，保留实体与来源 |
| 纯图片PPT | `market-research pdf-ppt` | PDF每页一张整页图片，保留原页面比例 |

## 安装与试跑

Python 3.10+，建议3.11。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[research,quarter]'
cp examples/pipeline/config.example.json config.json
cp examples/pipeline/.env.example .env
# 填写.env后加载；.env不会自动读取
set -a
source .env
set +a

# 无需任何认证、使用合成数据的完整试跑
python -m market_research demo --out data/demo --charts
python -m market_research --help
```

模块化操作和字段说明见[独立流水线使用说明](docs/features/research-pipeline.md)。方法与验证口径见[计算口径](docs/features/research-methods.md)。

## 采集与重算

```bash
# B站季度搜索、Sensor Tower
python -m market_research bili-search --config config.json
python -m market_research sensor --config config.json

# 百度既有原始数据导入；支持此前的11列JSON数组及中文表头CSV
python -m market_research import-baidu --input /你的路径/百度原始数据.json --out data/baidu.csv

# videos清单使用 bvid、products、subtitle_side、purpose 列
python -m market_research bili-corpus --videos /你的路径/语料视频.csv --out data/corpus
python -m market_research prepare-text --input data/corpus/documents.csv --out data/prepared.json
python -m market_research annotate --input data/prepared.json --out data/annotations

python -m market_research analyze --config config.json --out results \
  --videos data/bilibili/videos.csv --baidu data/baidu.csv \
  --occurrences data/annotations/word_occurrences.csv \
  --sales data/sensor/sales.csv --dau data/sensor/dau.csv
python -m market_research charts --input results/analysis.json --out results/charts
```

也可只提供已有的某类数据做分析，无需重复采集其他来源。新参数改变采集范围时使用新的输出目录；请求成功即保存，失败后重跑同一条命令可恢复。

## 目录

- `bili_research/`：原有B站采集、独立浏览器兼容路径和导出。
- `market_research/`：新独立研究流水线；来源认证仅由环境变量提供。
- `examples/pipeline/`：通用配置示例，无个人资源ID。
- `tests/`：离线测试，包含断点、实际值、词次、公式和游标分页。
- `docs/`：使用步骤、字段和统计口径。

源码压缩包包含代码、词典、配置模板、说明和合成测试，不包含工作区的真实评论/字幕、平台数据、Cookie、访问令牌、日志和浏览器登录目录。仓库早期提交的`examples/demo_output`及`examples/quarter_snapshot`属于历史示例，本次新增代码没有带入新的研究原始语料，源码压缩包也不附带这些历史数据。

## 验证

```bash
python -m unittest discover -s tests -v
python -m pip wheel . --no-deps
```

`.[quarter]`相关浏览器测试需要先运行`python -m playwright install chromium`；网页被拦截到本地测试HTML。新增HTTP季度搜索已做日期/页码/播放量校验测试；实际运行中若接口没有应用日期范围，程序立即停止并提示使用独立Playwright兼容路径。Sensor Tower转换按此次保存的真实API响应结构核对。百度流程与此前实际来源一致，提供附件导入代码，不宣称直接爬取百度登录接口。
