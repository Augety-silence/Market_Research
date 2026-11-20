# 独立研究流水线

## 1. 配置

`examples/pipeline/config.example.json`包含三产品、2023-01—2026-10、CN、iOS以及14款App的公开商店ID。部分App同时保留两个销售实体；日活只用对应主实体，避免重复累计。时间和范围由用户修改，程序不会把2024当作100或把后续实际值转换成指数。

所有相对路径以启动命令的当前目录为基准。凭证只从环境变量或用户提供的Cookie文件读取；不依赖旧工作区的认证适配器、会话ID或私有SDK。

| 环境变量 | 用途 |
| --- | --- |
| `BILI_COOKIE` | B站评论/字幕登录态；季度搜索也可使用 |
| `SENSOR_TOWER_AUTH_TOKEN` | Sensor Tower已授权API令牌 |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL` | 上下文标注的自选模型 |
| `FEISHU_USER_ACCESS_TOKEN`或`FEISHU_TENANT_ACCESS_TOKEN` | 飞书公开接口认证 |
| `FEISHU_APP_ID` / `FEISHU_APP_SECRET` | 未提供现成访问令牌时获取tenant令牌 |

## 2. B站

`market-research bili-search --config config.json`调用HTTP搜索接口，分页按播放量排序，保存准确整数。日期逐条落在季度区间内、结果总数与去重BV一致才标记完成。风控或筛选失败保留断点，不使用网页“万”单位近似数。

若B站接口未应用日期参数，可运行仓库原有独立浏览器路径；此路径不使用Aime浏览器：

```bash
python -m playwright install chromium
cp examples/quarter.config.example.json quarter.config.json
python -m bili_research quarter --config quarter.config.json login
python -m bili_research quarter --config quarter.config.json collect
python -m bili_research quarter --config quarter.config.json export
```

旧路径导出的中文列可用`map-csv`转换。`videos`规范列按顺序为：`product,quarter,bvid,title,date,views,source_page,source_url,collected_at`。分析会另写出已去重的`results/videos_raw.csv`供飞书公式引用。

语料采集清单：`bvid,products,subtitle_side,purpose`。`products`多个名称用`|`分隔。`subtitle_side`明确设为`demand`或`supply`，决定全文字幕纳入需求端还是固定内容端；评论使用自身发布时间进入需求季度。`purpose`区分推广、科普和体验。每个BV在清单只出现一次，跨产品视频合并products。

```bash
python -m market_research bili-corpus --videos corpus_list.csv --out data/corpus --max-sub-pages 1000
```

字幕每个分P单独落原始段落和覆盖率。无字幕记为missing；已取得字幕有coverage，不能将缺失字幕当作空全文。评论API逐页缓存，失败重跑会复用已保存页。楼中楼每根评论受`--max-sub-pages`上限约束；该上限不是“全站所有评论”的保证，删除、不可见或API不返回的评论无法恢复。

原命令`bili-research subtitle/comments/batch/comments-batch`仍可使用；音轨下载用于无字幕视频后续转写，音频转写模型由用户自行配置，本包不把不存在的字幕伪造为文字。

## 3. Sensor Tower

```bash
python -m market_research sensor --config config.json
```

销售API：`/ios/sales_report_estimates`，按月采集，iPhone与iPad分别展开。`iu/au`为下载，`ir/ar`为美分；`revenue_usd`统一除100。

日活API：`/ios/usage/active_users`，`date_granularity=monthly,time_period=day`，返回逐日设备日活。按月及App拆批，确保App数×天数不超过500。成功即事务保存，最终保留`*_raw.json`和标准` sales.csv/dau.csv`。

标准销售列：`app_id,app,group,date,country,device,downloads,revenue_usd`。标准日活列：`app_id,app,group,date,country,device,dau`。统计以配置的设备/国家为范围，两个设备不会混合。

## 4. 百度指数与旧数据迁移

此次百度指数来自此前文档中的数据附件，独立复现顺序是导出文档、取得附件、导入原始逐日记录。

```bash
cp examples/pipeline/feishu.example.json feishu.json
# 设置spreadsheet_token；即便只读取doc也需保留该配置键
python -m market_research feishu-doc --config feishu.json --document-id 自己的文档ID --out data/document
python -m market_research feishu-download --config feishu.json --file-token 自己的附件token --out data/attachment.json
python -m market_research import-baidu --input data/attachment.json --out data/baidu.csv
```

`feishu-doc`导出全部block及附件token清单；附件需要账号可访问并有对应应用权限。导入支持此前11列列表JSON、中文表头CSV、标准字段CSV。其他附件先按显式列名用`--mapping`转换，不猜字段。

标准百度列：`date,product,index,region,device,metric,source_file,source_sha256,source_url,source_document,source_attachment,acquisition`。`acquisition`固定记录为`document_attachment_import`。全国、PC+移动、搜索指数有效日均，空值保留空。相同日关键词的冲突值会报错。

```bash
python -m market_research map-csv --input 旧导出.csv --mapping 列映射.json --out 新格式.csv
```

也支持旧导出中的`annotated_csv` JSON封套；`has_more=true`时停止，防止把截断导出当作全量。

## 5. 分词和五维

文本CSV最小列：`id,side,date,products,text`。`side`为`demand`或`supply`；可补`source,purpose,bvid`。日期用ISO，products用`|`分隔，id必须唯一。

```bash
python -m market_research prepare-text --input documents.csv --out data/prepared.json
python -m market_research annotate --input data/prepared.json --out data/annotations
```

分词保留每个词的文本位置和每次出现，重复词不会变成一条01命中。提供的候选词典来自此前五维词典，只含词与候选维度，无例句和账号信息。归属由上下文判断，不把词典标签当作最终答案。`--all-tokens`可对全部有效分词标注；这是不同候选范围，需新目录保存并明确记录。

上下文输入不包含年份或待实现的排名。输出对每个候选词次给唯一维度、态度、产品mask；重复、漏标、越界都停止。一个主维度，五维之外标零；模型连接失败不会自动退回关键词匹配。每次成功立即保存SQLite并保存原始响应。

人工标注路径：

```bash
python -m market_research annotate --input data/prepared.json --manual manual.json --out data/annotations_manual
```

人工JSON格式为`[{"id":"unit摘要ID","a":[[词次i,维度0..5,态度0..4,产品mask0..7],...]}]`，须完整覆盖prepared中的unit和词次。司美=1、奥利=2、左旋=4。示例`demo`会生成人工JSON，可直接查看格式。

输出词次Raw的固定列：`document_id,side,source,purpose,quarter,date,bvid,token_index,word,dimension,stance,product_mask,products,count`。每行count=1。只统计五维词次，零维不进入分母。

## 6. 分析、画图和飞书

`analyze`可按实际需要提供数据源。默认`--exponent 0.5`对所有产品统一压缩固定特征。默认`--missing-policy strict`：同组App缺失导致组总值留空；`observed`可复现此前已观察App求和的组合口径，并同时保存覆盖率，缺失仍不会变成某款App的零日活。

输出包括实际视频季度表、去重Raw、百度季度均值、App月/季度表、逐日组日活、五维特征/权重/评分/词频，以及完整季度滞后相关。

```bash
python -m market_research charts --input results/analysis.json --out results/charts
# 使用自己的中文字体或改为直线
python -m market_research charts --input results/analysis.json --out results/charts --font /字体路径.ttf --straight
```

B站3×3：列为三产品，行为BV数、累计播放、去除Top1累计播放。App3×3：列为Keep、其他运动、饮食体重；行为DAU、下载、收入。每类独立纵轴。评分图三产品放一张；雷达图固定内容不切季度。默认PCHIP只绘制曲线，点仍是实际季度数据。

飞书同步：先将配置里的目标token和sheet_id填好。

```bash
python -m market_research feishu-workbook --config feishu.json --out data/workbook_export
python -m market_research feishu-sync --config feishu.json --csv results/videos_raw.csv --sheet-id 自己的Raw子表ID --state data/sync_videos.sqlite
python -m market_research feishu-sync --config feishu.json --csv data/annotations/word_occurrences.csv --sheet-id 自己的词次Raw子表ID --state data/sync_words.sqlite
python -m market_research sheet-plan --config feishu.json --analysis results/analysis.json --out data/formula_plan.json
python -m market_research feishu-sync --config feishu.json --plan data/formula_plan.json --state data/sync_formulas.sqlite
```

百度Raw、App销售Raw及`results/app_group_daily.csv`同样用`feishu-sync --csv`写入。summary只引用这些规范Raw；配置里的表名、模块起始行决定位置。写入既有区域会覆盖这些单元格，计划JSON可以先检查。写入200行一批，固定行号重试，回读值/公式一致才提交断点。采集字符串明确写为文本，避免标题成为公式。日期列默认转为电子表格序列，便于SUMIFS/AVERAGEIFS引用日期区间；可用`--date-columns`指定。

输出的本地图表是静态PNG/PDF。表格公式会随Raw变化重算；新增在线原生图表需在飞书内创建，代码没有把静态图伪称为原生动态图表。

## 7. 纯图片PPT

```bash
python -m market_research pdf-ppt --input 汇报.pdf --out 汇报_纯图片.pptx --dpi 240
```

每页一张整页PNG，转换后重新打开检查shape数量和类型，页面尺寸不一致时停止。无需安装Office。
