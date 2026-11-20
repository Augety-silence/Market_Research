"""飞书OpenAPI读写、附件下载、公式计划；独立运行，无需lark-cli。"""
import json
import time
from pathlib import Path
from urllib.parse import quote
from datetime import date
import requests
from bili_research.core.feishu_api import FeishuAPI
from bili_research.exporters.quarter_feishu import scalar
from .state import Checkpoint
from .io import read_rows, read_json, write_csv, atomic_json, digest, quarter_bounds, PRODUCTS, DIMENSIONS

def col(n):
    result=''
    while n: n,r=divmod(n-1,26);result=chr(65+r)+result
    return result

def text(v):
    if isinstance(v,(list,dict)):v=json.dumps(v,ensure_ascii=False)
    return {'type':'text','text':v} if isinstance(v,str) else v

def sync_plan(config,plan,state_path,*,chunk=200):
    if not 1<=chunk<=500: raise ValueError('批次行数须在1..500')
    api=FeishuAPI(config);state=Checkpoint(state_path,{'target':config['spreadsheet_token'],'plan':plan,'chunk':chunk})
    available={s['sheet_id'] for s in api.sheets()}
    try:
        for block in plan:
            sid=block['sheet_id'];rows=block['values'];start=block.get('start_row',1);startcol=block.get('start_col',1)
            if sid not in available: raise ValueError('配置中的sheet_id不存在')
            api.capacity(sid,start+len(rows)-1)
            for c in block.get('date_columns',[]):
                if len(rows)>1:api.styles(sid,f'{col(startcol+c)}{start+1}:{col(startcol+c)}{start+len(rows)-1}','yyyy-mm-dd')
            for offset in range(0,len(rows),chunk):
                batch=rows[offset:offset+chunk];first=start+offset;last=first+len(batch)-1
                width=max(len(r) for r in batch);area=f'{col(startcol)}{first}:{col(startcol+width-1)}{last}'
                key={'sheet':sid,'area':area,'values':batch}
                if state.get(key) is not None:continue
                api.write([(sid,area,batch)])
                expected=[[v.get('text','') if isinstance(v,dict) else v for v in r] for r in batch]
                ok=False
                for attempt in range(4):
                    actual=[[scalar(v) for v in r] for r in api.read(sid,area,formulas=True)]
                    def trimmed(row):
                        row=list(row)
                        while row and row[-1] in ('',None):row.pop()
                        return row
                    if [trimmed(r) for r in actual]==[trimmed(r) for r in expected]:ok=True;break
                    time.sleep(attempt+1)
                if not ok:raise ValueError('飞书回读不一致，当前批次未标记成功')
                state.put(key,{'verified':True});print('已同步并回读',sid,area,flush=True)
    finally:state.close()

def csv_plan(source,sheet_id,start_row=1,date_columns=()):
    rows=read_rows(source);fields=list(rows[0]) if rows else []
    values=[[text(f) for f in fields]]
    for row in rows:
        packed=[]
        for f in fields:
            value=row.get(f)
            if f in date_columns and value:value=(date.fromisoformat(value[:10])-date(1899,12,30)).days
            elif value in ('',None):value=''
            elif isinstance(value,str):
                from .io import number
                if f in {'views','count','token_index','product_mask','downloads','revenue_usd','dau','index','coverage'}:value=number(value)
            packed.append(text(value))
        values.append(packed)
    return [{'sheet_id':sheet_id,'start_row':start_row,'values':values,'date_columns':[i for i,f in enumerate(fields) if f in date_columns]}]

def export_workbook(config,outdir):
    """按分页遍历所有sheet原始单元格；公式与值分别保存。"""
    api=FeishuAPI(config);out=Path(outdir);out.mkdir(parents=True,exist_ok=True)
    metadata=api.sheets();atomic_json(out/'sheets.json',metadata)
    for sheet in metadata:
        sid=sheet['sheet_id'];grid=sheet['grid_properties'];rows=[];formulas=[]
        for begin in range(1,grid['row_count']+1,200):
            end=min(begin+199,grid['row_count']);area=f'A{begin}:{col(grid["column_count"])}{end}'
            values=api.read(sid,area);formula=api.read(sid,area,formulas=True)
            rows.extend({'row':begin+i,'values':r} for i,r in enumerate(values));formulas.extend({'row':begin+i,'values':r} for i,r in enumerate(formula))
            atomic_json(out/f'{sid}_values.json',rows);atomic_json(out/f'{sid}_formulas.json',formulas)
            print('已导出',sheet['title'],end,'/',grid['row_count'],flush=True)
    return metadata

def export_doc(config,document_id,outdir):
    api=FeishuAPI(config);out=Path(outdir);out.mkdir(parents=True,exist_ok=True);blocks=[];cursor=None
    while True:
        params={'page_size':500}
        if cursor:params['page_token']=cursor
        body=api.request('GET',f'/docx/v1/documents/{document_id}/blocks',params=params)
        blocks.extend(body.get('items',[]));atomic_json(out/'blocks.json',blocks)
        if not body.get('has_more'):break
        nxt=body.get('page_token')
        if not nxt or nxt==cursor:raise ValueError('文档分页游标未前进')
        cursor=nxt
    # 保存表格结构和文本，附件token只保留在本机导出。
    attachments=[]
    for block in blocks:
        token=(block.get('file') or {}).get('token')
        if token:attachments.append({'token':token,'name':(block.get('file') or {}).get('name','')})
    atomic_json(out/'attachments.json',attachments);return blocks

def download_attachment(config,file_token,output):
    api=FeishuAPI(config);url=api.root+'/drive/v1/medias/'+quote(file_token,safe='')+'/download'
    try:
        with requests.get(url,headers={'Authorization':'Bearer '+api.access_token()},stream=True,timeout=120) as r:
            if r.status_code!=200:raise RuntimeError(f'附件下载HTTP {r.status_code}')
            dest=Path(output);dest.parent.mkdir(parents=True,exist_ok=True);temp=dest.with_suffix(dest.suffix+'.part')
            with temp.open('wb') as f:
                for chunk in r.iter_content(1024*1024):f.write(chunk)
            temp.replace(dest)
    except requests.RequestException:raise RuntimeError('附件下载网络错误') from None

def formula_plan(book,analysis):
    """仅引用规范化、已去重的Raw表；生成JSON写入计划，目标由配置决定。"""
    sid=book['summary_sheet_id'];refs=book['raw_sheet_names'];blocks=[]
    def ref(key):return "'"+refs[key].replace("'","''")+"'!"
    def f(value):return {'type':'formula','text':'='+value}
    def block(start,values):blocks.append({'sheet_id':sid,'start_row':start,'values':values})
    # videos规范列：A产品 B季度 C BV D标题 E日期 F累计播放量；需先去重。
    if analysis.get('videos'):
        raw=ref('videos');values=[['季度','产品','累计播放量','BV数','去除Top1后播放量']]
        for i,r in enumerate(analysis['videos'],2):
            values.append([text(r['quarter']),text(r['product']),f(f'SUMIFS({raw}$F:$F,{raw}$A:$A,B{i},{raw}$B:$B,A{i})'),
                f(f'COUNTIFS({raw}$A:$A,B{i},{raw}$B:$B,A{i},{raw}$C:$C,"<>")'),
                f(f'C{i}-MAXIFS({raw}$F:$F,{raw}$A:$A,B{i},{raw}$B:$B,A{i})')])
        block(1,values)
    # word_occurrences固定列：A文档 B侧 C来源 D用途 E季度 F日期 G BV H词次ID I词 J维 K态度 Lmask M产品 N词次
    model=analysis.get('model')
    if model:
        raw=ref('occurrences');qs=sorted({r['quarter'] for r in model['weights']});start=book.get('model_start_row',200)
        values=[['季度',*DIMENSIONS,'总词次']]
        for i,q in enumerate(qs,start+1):
            row=[text(q)]
            for dim in DIMENSIONS:row.append(f(f'SUMIFS({raw}$N:$N,{raw}$B:$B,"demand",{raw}$E:$E,A{i},{raw}$J:$J,"{dim}")'))
            row.append(f(f'SUM(B{i}:F{i})'));values.append(row)
        block(start,values)
        wstart=start+len(values)+3;weights=[['季度',*DIMENSIONS]]
        for offset,q in enumerate(qs,1):weights.append([text(q)]+[f(f'IF($G{start+offset}=0,"",{c}{start+offset}/$G{start+offset})') for c in 'BCDEF'])
        block(wstart,weights)
        pstart=wstart+len(weights)+3;profile=[['产品',*DIMENSIONS,'总词次']]
        for offset,p in enumerate(PRODUCTS,1):
            masks=[m for m in range(1,8) if m&(1<<(offset-1))]
            row=[text(p)]
            for dim in DIMENSIONS:
                terms=[f'SUMIFS({raw}$N:$N,{raw}$B:$B,"supply",{raw}$J:$J,"{dim}",{raw}$L:$L,{mask})' for mask in masks]
                row.append(f('+'.join(terms)))
            row.append(f(f'SUM(B{pstart+offset}:F{pstart+offset})'));profile.append(row)
        block(pstart,profile)
        ftstart=pstart+len(profile)+3;feature=[['产品',*DIMENSIONS]];exponent=model['specification']['exponent']
        for offset,p in enumerate(PRODUCTS,1):
            r=pstart+offset;den='+'.join(f'POWER({c}{r}/$G{r},{exponent})' for c in 'BCDEF')
            feature.append([text(p)]+[f(f'IF($G{r}=0,"",100*POWER({c}{r}/$G{r},{exponent})/({den}))') for c in 'BCDEF'])
        block(ftstart,feature)
        sstart=ftstart+len(feature)+3;scores=[['季度',*PRODUCTS]]
        for offset,q in enumerate(qs,1):
            wr=wstart+offset;scores.append([text(q)]+[f(f'IF(COUNT(B{wr}:F{wr})<5,"",SUMPRODUCT(B{wr}:F{wr},B{ftstart+p}:F{ftstart+p}))') for p in (1,2,3)])
        block(sstart,scores)
    if analysis.get('baidu'):
        raw=ref('baidu');start=book.get('baidu_start_row',400);values=[['季度','产品','百度指数日均','有效日数']]
        # 规范百度列：A日期 B产品 C实际指数 D地域 E设备 F指标。
        for r in analysis['baidu']:
            begin,end=quarter_bounds(r['quarter']);a=(date.fromisoformat(begin)-date(1899,12,30)).days;b=(date.fromisoformat(end)-date(1899,12,30)).days
            cond=f'{raw}$B:$B,"{r["product"]}",{raw}$A:$A,">={a}",{raw}$A:$A,"<={b}",{raw}$D:$D,"全国",{raw}$E:$E,"PC+移动",{raw}$F:$F,"搜索指数"'
            values.append([text(r['quarter']),text(r['product']),f(f'IFERROR(AVERAGEIFS({raw}$C:$C,{cond}),"")'),f(f'COUNTIFS({cond},{raw}$C:$C,">=0",{raw}$C:$C,"<>")')])
        block(start,values)
    if analysis.get('apps'):
        sales=ref('sales');daily=ref('app_group_daily');start=book.get('app_start_row',600)
        values=[['季度','分类','下载量','平均设备日活','商店收入USD','有效日数','期望天数']]
        country=analysis['config']['country'];device=analysis['config'].get('device','iPhone')
        for r in analysis['apps']['quarters']:
            begin,end=quarter_bounds(r['quarter']);a=(date.fromisoformat(begin)-date(1899,12,30)).days;b=(date.fromisoformat(end)-date(1899,12,30)).days
            group=r['group'].replace('"','""')
            scond=f'{sales}$C:$C,"{group}",{sales}$D:$D,">={a}",{sales}$D:$D,"<={b}",{sales}$E:$E,"{country}",{sales}$F:$F,"{device}"'
            dcond=f'{daily}$B:$B,"{group}",{daily}$A:$A,">={a}",{daily}$A:$A,"<={b}",{daily}$C:$C,"{country}",{daily}$D:$D,"{device}"'
            # 为空的严格口径季度保留空；有观察值时公式直接引用Raw。
            dl=f(f'SUMIFS({sales}$G:$G,{scond})') if r['downloads'] is not None else text('')
            rev=f(f'SUMIFS({sales}$H:$H,{scond})') if r['revenue_usd'] is not None else text('')
            values.append([text(r['quarter']),text(r['group']),dl,f(f'IFERROR(AVERAGEIFS({daily}$E:$E,{dcond}),"")'),rev,
                f(f'COUNTIFS({dcond},{daily}$E:$E,"<>",{daily}$E:$E,">=0")'),r['expected_days']])
        block(start,values)
    occupied=set()
    for item in blocks:
        for row in range(item['start_row'],item['start_row']+len(item['values'])):
            if row in occupied:raise ValueError('summary目标区间重叠，请调整各模块start_row')
            occupied.add(row)
    for b in blocks:b['values']=[[text(x) if isinstance(x,str) else x for x in r] for r in b['values']]
    return blocks
