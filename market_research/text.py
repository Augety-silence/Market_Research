"""中文词次分词和上下文窗口。重复词逐次保留，窗口交叠不重复计数。"""
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
import jieba
from .io import read_rows, read_json, atomic_json, digest, product_list, quarter
from .lexicon import STOPWORDS, SINGLE_WORDS, DOMAIN_WORDS, EMOTICONS, EXTRA_WORDS


def segment(text):
    for w in DOMAIN_WORDS+EXTRA_WORDS: jieba.add_word(w,freq=200000)
    body=re.sub(r'^\s*回复\s*@?[^:：\n]{1,100}\s*[:：]\s*','',text)
    normalized=unicodedata.normalize('NFKC',body).lower()
    normalized=re.sub(r'https?://[^\s<>]+',' ',normalized)
    normalized=re.sub(r'\[([^\[\]\n]{1,30})\]',lambda m:' ' if m[1].lower() in {x.lower() for x in EMOTICONS} else m[0],normalized)
    tokens=[(t,a,b) for t,a,b in jieba.tokenize(normalized,HMM=True)
        if t.strip() and t not in STOPWORDS and (len(t)>1 or t in SINGLE_WORDS)
        and re.search(r'[\u4e00-\u9fffA-Za-z]',t) and not re.fullmatch(r'(?:bv[\da-z]+|av\d+)',t)]
    return normalized,tokens

def prepare(source,output,dictionary=None,all_tokens=False):
    docs=read_rows(source);mapping=read_json(dictionary or Path(__file__).with_name('candidate_dictionary.json'))
    candidates={t for t,label in mapping.items() if label!='不纳入五维'}|set(EXTRA_WORDS)
    seen=set();units={};records=[]
    for doc in docs:
        if not doc.get('id') or doc['id'] in seen: raise ValueError('文本id缺失或重复，请按评论ID/字幕CID去重')
        seen.add(doc['id'])
        if doc.get('side') not in ('demand','supply'): raise ValueError('side须为demand或supply')
        q=quarter(doc['date'])
        if doc.get('quarter') and doc['quarter']!=q: raise ValueError('文本日期与季度不一致')
        normalized,tokens=segment(doc['text']);products=product_list(doc.get('products'))
        groups=defaultdict(list)
        for i,(word,a,b) in enumerate(tokens):
            if all_tokens or word in candidates:groups[a//550].append((i,word,a,b))
        refs=[]
        for group in groups.values():
            begin=max(0,min(t[2] for t in group)-100);end=min(len(normalized),max(t[3] for t in group)+100)
            payload={'text':normalized[begin:end],'context_products':products,
                     'tokens':[[i,t[1],t[2]-begin,t[3]-begin] for i,t in enumerate(group)]}
            key=digest(payload)
            if key not in units:units[key]={'id':key,**payload}
            refs.append({'unit_id':key,'global_indices':[t[0] for t in group]})
        records.append({**doc,'quarter':q,'products':products,'normalized':normalized,'tokens':tokens,'units':refs})
    result={'version':'contextual-token-five-v4-portable','dictionary_sha256':digest(mapping),
            'all_tokens':all_tokens,'documents':records,'units':list(units.values())}
    atomic_json(output,result);return result
