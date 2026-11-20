"""通用OpenAI兼容模型或人工JSON标注；没有模型时绝不伪装成上下文结果。"""
import json
import os
import re
from pathlib import Path
from .io import read_json, atomic_json, write_csv, digest, DIMENSIONS, PRODUCTS
from .http import request_json
from .state import Checkpoint

PROMPT=Path(__file__).with_name('annotation_prompt.txt').read_text(encoding='utf-8')
STANCES=['中性事实','诉求或询问','认可','质疑或不良评价','方向不清']

def validate(item, unit):
    if item.get('id')!=unit['id']: raise ValueError('标注id不匹配')
    values=item.get('a');indices={t[0] for t in unit['tokens']}
    if not isinstance(values,list) or len(values)!=len(indices): raise ValueError('词次标注数量不足或超出')
    if any(not isinstance(v,list) or len(v)!=4 or any(type(x) is not int for x in v) for v in values):
        raise ValueError('标注须为整数四元数组')
    if {v[0] for v in values}!=indices: raise ValueError('词次id重复或漏标')
    for _,dim,stance,mask in values:
        if not (0<=dim<=5 and 0<=stance<=4 and 0<=mask<=7): raise ValueError('维度/态度/产品mask越界')
        if dim==0 and (stance or mask): raise ValueError('零维的态度与产品mask须为零')
    return values

def annotate(prepared, outdir, *, model=None, manual=None):
    prepared=read_json(prepared);out=Path(outdir);out.mkdir(parents=True,exist_ok=True)
    if manual:
        values=read_json(manual)
        if not isinstance(values,list) or len({r['id'] for r in values})!=len(values): raise ValueError('人工结果id重复')
        labels={r['id']:r for r in values};method='manual';model='manual'
    else:
        key=os.getenv('OPENAI_API_KEY','').strip();base=os.getenv('OPENAI_BASE_URL','https://api.openai.com/v1').strip()
        model=model or os.getenv('OPENAI_MODEL','').strip()
        if not key or not model: raise ValueError('请配置OPENAI_API_KEY、OPENAI_MODEL，或提供--manual JSON')
        if not base.startswith('https://') and not base.startswith('http://localhost:'):
            raise ValueError('模型端点须使用HTTPS或本机localhost')
        labels=None;method='openai_compatible'
    state=Checkpoint(out/'annotation.sqlite',{'prepared':digest(prepared),'prompt':digest(PROMPT),'method':method,'model':model,
                                              'endpoint':base if not manual else 'manual','manual_hash':digest(labels) if manual else None})
    done={}
    try:
        for n,unit in enumerate(prepared['units'],1):
            def fetch():
                if manual:
                    if unit['id'] not in labels: raise ValueError('人工标注缺少当前unit')
                    item=labels[unit['id']]
                    validate(item,unit);return item
                body=request_json('POST',base.rstrip('/')+'/chat/completions',headers={'Authorization':'Bearer '+key},
                    payload={'model':model,'temperature':0,'messages':[{'role':'system','content':PROMPT},
                        {'role':'user','content':json.dumps([unit],ensure_ascii=False)}]})
                content=body['choices'][0]['message']['content']
                atomic_json(out/'responses'/f'{unit["id"]}.json',{'unit_id':unit['id'],'model':model,'content':content})
                content=re.sub(r'^```(?:json)?\s*|\s*```$','',content.strip());response=json.loads(content)
                if not isinstance(response,list) or len(response)!=1: raise ValueError('模型须返回恰好一个unit')
                item=response[0];validate(item,unit);return item
            item=state.fetch({'unit_id':unit['id']},fetch);done[unit['id']]=validate(item,unit)
            if n%20==0 or n==len(prepared['units']):
                atomic_json(out/'progress.json',{'completed':n,'total':len(prepared['units']),'method':method,'model':model})
                print('标注',n,'/',len(prepared['units']),flush=True)
        rows=expand(prepared,done);write_csv(out/'word_occurrences.csv',rows)
        atomic_json(out/'labels.json',[{'id':key,'a':value} for key,value in done.items()])
        atomic_json(out/'provenance.json',{'method':method,'model':model,'prompt_sha256':digest(PROMPT),'prepared_sha256':digest(prepared),'complete':True,'occurrences':len(rows)})
        return rows
    finally:state.close()

def expand(prepared,done):
    units={u['id']:u for u in prepared['units']};rows=[]
    if set(done)!=set(units): raise ValueError('标注未覆盖全部unit，停止聚合')
    for doc in prepared['documents']:
        for ref in doc['units']:
            unit=units[ref['unit_id']];a=done[ref['unit_id']]
            annotations={v[0]:v for v in validate({'id':unit['id'],'a':a},unit)}
            for global_i,token in zip(ref['global_indices'],unit['tokens']):
                i,word,start,end=token;_,dim,stance,mask=annotations[i]
                rows.append({'document_id':doc['id'],'side':doc['side'],'source':doc.get('source',''),
                    'purpose':doc.get('purpose',''),'quarter':doc['quarter'],'date':doc['date'],
                    'bvid':doc.get('bvid',''),'token_index':global_i,'word':word,
                    'dimension':DIMENSIONS[dim-1] if dim else '不纳入五维','stance':STANCES[stance],
                    'product_mask':mask,'products':[p for j,p in enumerate(PRODUCTS) if mask&(1<<j)],'count':1})
    return rows
