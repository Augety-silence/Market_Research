"""季度命令参数与采集、断点、导出的编排。"""
import argparse
import json
from pathlib import Path


def env_file(path):
    import os
    if not path.exists():return
    allowed={'FEISHU_APP_ID','FEISHU_APP_SECRET','FEISHU_USER_ACCESS_TOKEN','FEISHU_TENANT_ACCESS_TOKEN'}
    for line in path.read_text().splitlines():
        line=line.strip()
        if not line or line.startswith('#') or '=' not in line:continue
        key,value=line.split('=',1);key=key.strip();value=value.strip().strip('\"\'')
        if key in allowed and value:os.environ.setdefault(key,value)


def configure_parser(parser):
    parser.add_argument('--config',default='quarter.config.json',help='配置文件路径')
    sub=parser.add_subparsers(dest='quarter_command',required=True)
    init=sub.add_parser('init',help='初始化本地数据库');init.add_argument('--from-snapshot',action='store_true')
    sub.add_parser('login',help='手动登录或处理人工验证')
    collect=sub.add_parser('collect',help='按断点采集');collect.add_argument('--max-pages',type=int,default=0,help='本次最多保存页数，0为不限')
    collect.add_argument('--sync-feishu',action='store_true',help='每页本地保存后同步飞书')
    sub.add_parser('status',help='查看断点')
    sub.add_parser('list-sheets',help='读取飞书工作表ID及名称')
    sub.add_parser('export',help='导出CSV和含独立趋势图的Excel')
    sub.add_parser('bind-existing',help='核验已有飞书表与本地快照一致，再绑定固定行')
    sub.add_parser('bind-empty',help='核验空白飞书目标表，再绑定')
    sub.add_parser('sync-feishu',help='补写未同步记录并更新公式汇总')
    parser.set_defaults(func=run)
    return parser


def run(args):
    try:
        return _run(args)
    except KeyboardInterrupt:
        print("已停止；最后提交的断点可继续");return 130
    except Exception as exc:
        print("停止：", str(exc));return 1


def _run(args):
    import fcntl
    from .collectors.quarter_search import VerificationRequired
    from .exporters.quarter_store import Store
    cp=Path(args.config).resolve()
    try:
        config=json.loads(cp.read_text(encoding='utf-8'))
        from .collectors.quarter_search import jobs_for
        jobs_for(config)
        if getattr(args, 'max_pages', 0) < 0:
            raise ValueError('--max-pages 不能为负数')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('配置错误：', str(exc));return 2
    env_file(cp.parent/'.env')
    output=(cp.parent/config.get('output_dir','output')).resolve();output.mkdir(parents=True,exist_ok=True)
    with (output/'run.lock').open('a+') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise SystemExit('同一输出目录已有程序运行，请勿并发启动')
        store=Store(output/'collection.sqlite3',config)
        try:
            if args.quarter_command=='init':
                if args.from_snapshot:
                    snapshot=json.loads((cp.parent/config.get('snapshot_file','examples/quarter_snapshot/collected.json')).read_text())
                    print(f'已导入{store.seed(snapshot)}条明细与完成断点')
                else:print('已初始化；可以运行 collect')
            elif args.quarter_command=='status':
                for j in store.jobs():print(j['quarter'],j['keyword'],j['status'],'已保存页',j['last_page'],'下一页',j['next_page'],'BV',store.count(j['keyword'],j['quarter']),'总数',j['total'])
                print('全部明细：',len(store.rows()))
            elif args.quarter_command in ('bind-existing','bind-empty','sync-feishu','list-sheets'):
                from .exporters.quarter_feishu import Feishu
                api=Feishu(dict(config['feishu'],keywords=config['keywords']))
                if args.quarter_command=='list-sheets':
                    for sheet in api.sheets():print(sheet['sheet_id'], sheet['title'], sheet.get('grid_properties',{}))
                elif args.quarter_command=='bind-existing':print('已核验绑定现有明细：',api.bind_existing(store))
                elif args.quarter_command=='bind-empty':api.bind_empty(store);print('已绑定空白表')
                else:api.sync(store);print('飞书已写入并回读核验')
            elif args.quarter_command in ('collect','login'):
                todo=[j for j in store.jobs() if j['status']!='已完成']
                if args.quarter_command=='collect' and not todo:
                    print('所有任务已经完成；如需重新采集，修改 output_dir 使用新的输出目录')
                    return 0
                from .core.quarter_browser import Browser
                api=None
                if args.quarter_command=='collect' and args.sync_feishu:
                    from .exporters.quarter_feishu import Feishu
                    api=Feishu(dict(config['feishu'],keywords=config['keywords']))
                    api.sync(store)
                profile=(cp.parent/config.get('browser',{}).get('profile_dir','.browser-profile')).resolve()
                browser=Browser(profile,config.get('browser',{}))
                try:
                    if args.quarter_command=='login':browser.login();return 0
                    pages=0
                    for job in todo:
                        if job['status']=='数量待核验' or not job['next_page']:
                            raise RuntimeError('末页去重数与搜索总数不同，请检查该任务，不自动跳过')
                        result=browser.open(job,job['next_page'])
                        while True:
                            job=store.save(job,result);pages+=1
                            from .exporters.quarter_files import export_csv
                            export_csv(store,output)
                            print(job['quarter'],job['keyword'],'已保存第',job['last_page'],'页；BV',store.count(job['keyword'],job['quarter']),'/',job['total'],flush=True)
                            if api:api.sync(store)
                            if job['status']=='数量待核验':raise RuntimeError('完整性核验未通过，断点已保存')
                            if args.max_pages and pages>=args.max_pages:return 0
                            if not job['next_page']:break
                            result=browser.next(job,result)
                    print('全部任务完成，去重数量与搜索总数一致')
                finally:browser.close()
            elif args.quarter_command=='export':
                from .exporters.quarter_files import export_csv, export_xlsx
                export_csv(store,output)
                path=export_xlsx(store,config,output/'三产品季度趋势.xlsx')
                print('已导出：',path)
            return 0
        except VerificationRequired as exc:
            print(str(exc));return 2
        except KeyboardInterrupt:
            print('已停止；最后一次SQLite事务保存的断点可继续');return 130
        except Exception as exc:
            print('停止：',str(exc));return 1
        finally:
            # 失败时也导出已经提交的结果；SQLite始终是续采的主数据。
            try:
                from .exporters.quarter_files import export_csv,export_xlsx
                export_csv(store,output)
                try:
                    if args.quarter_command != 'export':
                        export_xlsx(store,config,output/'三产品季度趋势.xlsx')
                except ModuleNotFoundError:
                    if args.quarter_command == 'export':
                        raise
                    print('Excel导出需要可选依赖：pip install -e ".[quarter]"；SQLite和CSV已保存')
            except Exception as exc:print('导出提示：',str(exc),'；SQLite数据已保留')
            store.close()


def main(argv=None):
    parser=argparse.ArgumentParser(description='B站季度关键词视频采集')
    configure_parser(parser)
    return run(parser.parse_args(argv))


if __name__=='__main__':
    raise SystemExit(main())
