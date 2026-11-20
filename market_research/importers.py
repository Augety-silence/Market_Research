"""已有百度指数和工作簿原始记录导入；不冒充直接百度采集。"""
from pathlib import Path
from .io import read_rows, read_json, write_csv, atomic_json, digest, iso_date, number

BAIDU_FIELDS=['日期','关键词','搜索指数','地域','设备','指标','原始数据文件','原始文件SHA256','来源页面','来源文档','数据附件']

def import_baidu(source, output, mapping=None):
    rows=read_rows(source); result=[]; seen={}
    for row in rows:
        if isinstance(row,list): row=dict(zip(BAIDU_FIELDS,row))
        if mapping: row={target:row.get(origin) for target,origin in mapping.items()}
        def get(en,zh,default=None): return row.get(en,row.get(zh,default))
        item={'date':iso_date(get('date','日期')),'product':get('product','关键词'),
              'index':number(get('index','搜索指数')),'region':get('region','地域','全国'),
              'device':get('device','设备','PC+移动'),'metric':get('metric','指标','搜索指数'),
              'source_file':get('source_file','原始数据文件',str(Path(source).name)),
              'source_sha256':get('source_sha256','原始文件SHA256'),
              'source_url':get('source_url','来源页面'),'source_document':get('source_document','来源文档'),
              'source_attachment':get('source_attachment','数据附件'),'acquisition':'document_attachment_import'}
        if not item['product']: raise ValueError('缺少百度关键词')
        key=(item['date'],item['product'],item['region'],item['device'],item['metric'])
        if key in seen:
            if seen[key]['index']!=item['index']: raise ValueError('百度指数同日同关键词存在冲突值')
            continue
        seen[key]=item;result.append(item)
    write_csv(output,sorted(result,key=lambda r:(r['date'],r['product'])))
    atomic_json(str(output)+'.provenance.json',{'method':'document_attachment_import','input_sha256':__import__('hashlib').sha256(Path(source).read_bytes()).hexdigest(),'records':len(result),'input_records':len(rows)})
    return result

def map_rows(source, output, mapping):
    """按显式列名映射，迁移旧CSV/JSON，不依赖个人sheet列位置。"""
    rows=read_rows(source)
    if any(not isinstance(r,dict) for r in rows): raise ValueError('标准映射输入必须有列名')
    missing=set(mapping.values())-set(rows[0] if rows else {})
    if missing: raise ValueError('输入缺少配置列：'+','.join(sorted(missing)))
    result=[{k:r.get(v) for k,v in mapping.items()} for r in rows]
    write_csv(output,result,list(mapping));return result
