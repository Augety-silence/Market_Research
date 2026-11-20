"""独立命令行入口；所有个人资源和凭证由用户配置。"""
import argparse
import json
from pathlib import Path
from .io import read_json,read_rows,atomic_json,write_csv,quarter_bounds


def parser():
    p=argparse.ArgumentParser(prog='market-research',description='独立采集、词次分析和研究图表')
    sub=p.add_subparsers(dest='command',required=True)
    for name in ['sensor','bili-search','logos']:
        s=sub.add_parser(name);s.add_argument('--config',required=True)
        if name=='logos':s.add_argument('--out',required=True)
    s=sub.add_parser('bili-corpus');s.add_argument('--videos',required=True);s.add_argument('--out',required=True);s.add_argument('--cookie-file');s.add_argument('--max-sub-pages',type=int,default=1000)
    s=sub.add_parser('import-baidu');s.add_argument('--input',required=True);s.add_argument('--out',required=True);s.add_argument('--mapping')
    s=sub.add_parser('map-csv');s.add_argument('--input',required=True);s.add_argument('--out',required=True);s.add_argument('--mapping',required=True)
    s=sub.add_parser('prepare-text');s.add_argument('--input',required=True);s.add_argument('--out',required=True);s.add_argument('--dictionary');s.add_argument('--all-tokens',action='store_true')
    s=sub.add_parser('annotate');s.add_argument('--input',required=True);s.add_argument('--out',required=True);s.add_argument('--model');s.add_argument('--manual')
    s=sub.add_parser('analyze');s.add_argument('--config',required=True);s.add_argument('--out',required=True)
    for name in ['videos','baidu','occurrences','sales','dau']:s.add_argument('--'+name)
    s.add_argument('--exponent',type=float,default=.5);s.add_argument('--missing-policy',choices=['strict','observed'],default='strict')
    s=sub.add_parser('charts');s.add_argument('--input',required=True);s.add_argument('--out',required=True);s.add_argument('--font');s.add_argument('--straight',action='store_true')
    s=sub.add_parser('pdf-ppt');s.add_argument('--input',required=True);s.add_argument('--out',required=True);s.add_argument('--dpi',type=int,default=240)
    s=sub.add_parser('sheet-plan');s.add_argument('--config',required=True);s.add_argument('--analysis',required=True);s.add_argument('--out',required=True)
    s=sub.add_parser('feishu-sync');s.add_argument('--config',required=True);s.add_argument('--state',required=True);s.add_argument('--chunk',type=int,default=200)
    s.add_argument('--plan');s.add_argument('--csv');s.add_argument('--sheet-id');s.add_argument('--start-row',type=int,default=1);s.add_argument('--date-columns',default='date')
    for name in ['feishu-workbook','feishu-doc','feishu-download']:
        s=sub.add_parser(name);s.add_argument('--config',required=True);s.add_argument('--out',required=True)
        if name=='feishu-doc':s.add_argument('--document-id',required=True)
        if name=='feishu-download':s.add_argument('--file-token',required=True)
    s=sub.add_parser('demo');s.add_argument('--out',default='data/demo');s.add_argument('--charts',action='store_true');s.add_argument('--font')
    return p

def analyze(args):
    from .analysis import video_summary,baidu_summary,five_model,app_summary,lag_analysis,group_daily_rows
    config=read_json(args.config);out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    result={'config':config,'schema':'research-v2'}
    if args.videos:
        from .io import iso_date,number,quarter
        raw_videos=read_rows(args.videos)
        result['videos'],result['video_audit']=video_summary(raw_videos)
        write_csv(out/'video_summary.csv',result['videos'])
        canonical={}
        for r in raw_videos:
            dt=iso_date(r['date']);q=quarter(dt)
            canonical[r['product'],q,r['bvid']]={'product':r['product'],'quarter':q,'bvid':r['bvid'],
                'title':r.get('title',''),'date':dt,'views':number(r['views']),
                'source_page':r.get('source_page'),'source_url':r.get('source_url'),'collected_at':r.get('collected_at')}
        write_csv(out/'videos_raw.csv',[canonical[k] for k in sorted(canonical)])
    if args.baidu:result['baidu']=baidu_summary(read_rows(args.baidu));write_csv(out/'baidu_summary.csv',result['baidu'])
    if args.occurrences:
        result['model']=five_model(read_rows(args.occurrences),args.exponent)
        for name in ['features','weights','scores','word_frequency']:write_csv(out/(name+'.csv'),result['model'][name])
    if bool(args.sales)!=bool(args.dau):raise ValueError('App分析必须同时提供sales和dau')
    if args.sales:
        result['apps']=app_summary(read_rows(args.sales),read_rows(args.dau),config['apps'],country=config['country'],device=config.get('device','iPhone'),missing_policy=args.missing_policy)
        write_csv(out/'app_monthly.csv',result['apps']['monthly']);write_csv(out/'app_quarterly.csv',result['apps']['quarters'])
        write_csv(out/'app_group_daily.csv',group_daily_rows(read_rows(args.dau),config['apps'],country=config['country'],device=config.get('device','iPhone'),missing_policy=args.missing_policy))
    if result.get('videos') and result.get('apps'):
        complete=[r for r in result['videos'] if config['start_date']<=quarter_bounds(r['quarter'])[0] and quarter_bounds(r['quarter'])[1]<=config['end_date']]
        result['lags']=lag_analysis(complete,result['apps']['quarters']);write_csv(out/'lag_correlations.csv',result['lags'])
    if result.get('videos') and result.get('model'):
        import math
        from .analysis import pearson
        from .io import PRODUCTS
        associations=[]
        for product in PRODUCTS:
            scores={r['quarter']:r['score'] for r in result['model']['scores'] if r['product']==product}
            pairs=[(scores[r['quarter']],math.log1p(r['views'])) for r in result['videos'] if r['product']==product and r['quarter'] in scores and quarter_bounds(r['quarter'])[1]<=config['end_date']]
            r,p=pearson([x for x,y in pairs],[y for x,y in pairs]);associations.append({'product':product,'n':len(pairs),'matching_logviews_r':r,'p':p})
        result['associations']=associations;write_csv(out/'matching_associations.csv',associations)
    atomic_json(out/'analysis.json',result);print('分析结果已保存到',out)
    return result

def main(argv=None):
    args=parser().parse_args(argv);cmd=args.command
    if cmd in ['sensor','bili-search','logos']:
        config=read_json(args.config)
        if cmd=='sensor':from .sensor import collect;collect(config)
        elif cmd=='bili-search':from .bilibili import collect_search;collect_search(config)
        else:from .logos import collect;collect(config,args.out)
    elif cmd=='bili-corpus':
        from .bilibili import collect_corpus
        collect_corpus(args.videos,args.out,cookie_file=args.cookie_file,max_sub_pages=args.max_sub_pages)
    elif cmd=='import-baidu':
        from .importers import import_baidu
        import_baidu(args.input,args.out,read_json(args.mapping) if args.mapping else None)
    elif cmd=='map-csv':
        from .importers import map_rows
        map_rows(args.input,args.out,read_json(args.mapping))
    elif cmd=='prepare-text':
        from .text import prepare
        prepare(args.input,args.out,args.dictionary,args.all_tokens)
    elif cmd=='annotate':
        from .annotation import annotate
        annotate(args.input,args.out,model=args.model,manual=args.manual)
    elif cmd=='analyze':analyze(args)
    elif cmd=='charts':
        from .charts import create
        create(read_json(args.input),args.out,font=args.font,smooth=not args.straight)
    elif cmd=='pdf-ppt':
        from .presentation import pdf_to_ppt
        print('已生成纯图片PPT，页数：',pdf_to_ppt(args.input,args.out,args.dpi))
    elif cmd=='sheet-plan':
        from .feishu import formula_plan
        atomic_json(args.out,formula_plan(read_json(args.config),read_json(args.analysis)))
    elif cmd=='feishu-sync':
        from .feishu import csv_plan,sync_plan
        if bool(args.plan)==bool(args.csv):raise ValueError('请选择--plan或--csv之一')
        if args.csv and not args.sheet_id:raise ValueError('CSV同步需--sheet-id')
        plan=read_json(args.plan) if args.plan else csv_plan(args.csv,args.sheet_id,args.start_row,args.date_columns.split(','))
        sync_plan(read_json(args.config),plan,args.state,chunk=args.chunk)
    elif cmd=='feishu-workbook':
        from .feishu import export_workbook
        export_workbook(read_json(args.config),args.out)
    elif cmd=='feishu-doc':
        from .feishu import export_doc
        export_doc(read_json(args.config),args.document_id,args.out)
    elif cmd=='feishu-download':
        from .feishu import download_attachment
        download_attachment(read_json(args.config),args.file_token,args.out)
    elif cmd=='demo':
        from .demo import run
        run(args.out,charts=args.charts,font=args.font)
