# 季度关键词视频采集

入口为 `bili-research quarter` 或 `python -m bili_research quarter`。这部分从独立季度采集代码包整合而来，使用自己的 Playwright Chromium 窗口，不需要外部浏览器接管服务。原字幕、评论、音轨命令继续使用标准库 HTTP 客户端。

## 安装与配置

需要 Python 3.10+，建议使用3.11。浏览器登录与文件锁流程面向 macOS / Linux。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[quarter]"
python -m playwright install chromium
cp examples/quarter.config.example.json quarter.config.json
```

macOS 可以运行 `bash scripts/启动季度采集.command`。脚本安装可选依赖、创建配置、打开登录窗口并采集；飞书同步由独立命令启用。

示例配置包含奥利司他、司美格鲁肽、左旋肉碱，范围为2024-01-01至2026-11-16。修改关键词、日期后使用新的 `output_dir`，不同采集范围不能共用断点。配置中的相对路径以配置文件所在目录为基准。自定义配置使用：

```bash
python -m bili_research quarter --config /绝对路径/配置.json status
```

## 登录、采集与断点

```bash
python -m bili_research quarter login
python -m bili_research quarter collect --max-pages 2
python -m bili_research quarter collect
python -m bili_research quarter status
```

登录时在专用浏览器窗口完成操作，回到终端按回车保存。`browser.channel` 留空使用安装的 Chromium，设为 `chrome` 可使用本机 Chrome。`profile_dir` 应为专用目录，不要使用日常 Chrome 用户目录。

每页按最多播放排序，读取页面结构中的精确整数播放量；保存前逐条核验发布日期、BV格式、排序、页面数据与界面页码。下一页以页面按钮状态判断，不根据接口的 `next` 字段提前结束。遇到验证码或校验失败立即停止。

`collection.sqlite3` 使用 WAL、FULL 同步和事务。每页视频记录与下一页断点一起提交，关键词+季度+BV唯一；翻页重叠不会重复入库。重新运行相同 collect 命令从最后提交断点继续。同一个输出目录只允许一个进程运行。

末页需满足去重数量等于搜索总数，才能标记“已完成”。不一致会标记“数量待核验”；续采时搜索总数变化也会停止，已有数据继续保留。B站搜索集合可以变化，总数相同并不保证视频集合相同；结果应结合采集时间使用。

## 已有快照与趋势图

`examples/quarter_snapshot/collected.json` 保存5496条关键词匹配记录和36个已完成任务，对应5476个不同BV。只含公开视频元信息与断点，不含登录态。导入只允许空数据库，配置需与快照一致。

```bash
python -m bili_research quarter init --from-snapshot
python -m bili_research quarter status
python -m bili_research quarter export
```

导入后所有任务已完成，collect 不会再次采集。重新采集需换新输出目录。

输出包含 SQLite、`视频明细.csv`、`断点进度.csv`、`三产品季度趋势.xlsx`。Excel 使用 SUMIFS / COUNTIFS 引用明细，含六张独立折线图：三产品各有累计播放量、BV数一张图，每图独立纵轴。没有数据透视表。Excel打开后重算公式，openpyxl本身不计算公式缓存。

播放量为采集时累计值，按视频发布日期归属季度，**不是季度新增播放量**。跨关键词同一BV分别计入各关键词；汇总BV数是关键词匹配记录数，三类合计不是跨关键词去重数。标签或正文可能命中关键词，标题不含药名的结果仍会保留。季度搜索结果尚未做相关性分类，不能直接替代语料研究中的供需分类与药物提及标注。截止季度只覆盖配置截止日期。

## 飞书公开 API 同步

此模块直接使用飞书公开 API，与现有语料导出 `push-feishu` 命令独立。将 `examples/quarter.env.example` 复制到配置文件同目录的 `.env`，填写自己的应用凭证，或用户/租户访问令牌。令牌通过环境变量传入；短期令牌失效后需自行更新。目标表需要电子表格读写权限及编辑权限。

示例的工作簿token、sheet_id均留空。准备“视频明细”“断点进度”“季度汇总”三张工作表，将自己的资源ID填入 `quarter.config.json`：

```bash
python -m bili_research quarter list-sheets
python -m bili_research quarter bind-empty
python -m bili_research quarter collect --sync-feishu
```

已有表先在空输出目录导入对应快照，再运行 `bind-existing`。程序回读全量明细，逐行核对所有字段和数量，成功后绑定线上固定行号；不一致时停止绑定。

```bash
python -m bili_research quarter init --from-snapshot
python -m bili_research quarter bind-existing
python -m bili_research quarter sync-feishu
```

每页先提交 SQLite，再将未同步数据写入预分配线上固定行；回读一致后才标记同步成功。远端成功但响应丢失时重写相同行，不重复追加。同步失败后先运行 `sync-feishu` 补写。

在线汇总目前使用三关键词、十二季度固定布局 A5:I20，包含104个公式；其他范围支持本地采集与Excel导出，在线布局需另行扩展。程序更新公式与断点，不新建线上图表；已有图继续引用汇总，新表可自行按产品插图或查看本地Excel六图。

## 分层与测试

- `core/quarter_browser.py`：独立浏览器、提取表达式、翻页。
- `core/feishu_api.py`：飞书公开 API 认证、请求、单元格与容量操作。
- `collectors/quarter_search.py`：季度划分、URL、数据校验与记录转换，不写存储。
- `exporters/quarter_store.py`：SQLite事务与断点。
- `exporters/quarter_files.py`：CSV、Excel公式与趋势图。
- `exporters/quarter_feishu.py`：固定行绑定、回读核验与在线汇总。
- `quarter_runner.py`：参数和编排，由统一 `cli.py` 注册。

```bash
python -m unittest discover -s tests -v
```

未安装可选依赖时，相关导出/浏览器测试跳过；其他测试仍可运行。浏览器测试需要安装Chromium，通过拦截导航使用本地HTML测试提取、翻页、续采和人工验证，不访问真实B站。快照测试核对数据量、播放总数、断点、公式与六图；同步测试模拟远端响应丢失后的固定行重试。

独立采集程序尚未在用户macOS上完成真实B站和飞书授权写入联调。首次真实运行先检查两页。页面结构变化需更新提取表达式与选择器，校验失败时不会推进断点。
