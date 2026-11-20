"""标准文件、日期与数值口径；空值始终保留为空。"""
import calendar
import csv
import hashlib
import io
import json
import math
import os
import re
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

PRODUCTS = ['司美格鲁肽', '奥利司他', '左旋肉碱']
DIMENSIONS = ['减重效果与维持', '证据与宣传可信度', '安全性与耐受', '用药便利性', '经济负担与可及性']

def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def atomic_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=path.name+'.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.flush(); os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp): os.unlink(temp)

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def read_rows(path):
    """支持标准CSV、字典数组JSON，以及旧导出的annotated_csv封套。"""
    path = Path(path); text = path.read_text(encoding='utf-8-sig')
    if text.lstrip().startswith(('[', '{')):
        obj = json.loads(text)
        if isinstance(obj, list): return obj
        if 'annotated_csv' in obj:
            if obj.get('has_more'): raise ValueError('导出被截断，请补齐再导入')
            text = re.sub(r'^\[row=\d+\]\s?', '', obj['annotated_csv'], flags=re.M)
        else:
            raise ValueError('需要字典数组JSON或CSV，不能隐式猜测字段')
    return list(csv.DictReader(io.StringIO(text)))

def write_csv(path, rows, fields=None):
    rows = list(rows); fields = fields or list(dict.fromkeys(k for r in rows for k in r))
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader()
            for r in rows:
                writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v for k,v in r.items()})
            f.flush(); os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp): os.unlink(temp)

def number(value):
    if value is None or value == '': return None
    if isinstance(value, bool): raise ValueError('布尔值不能当作实际数值')
    result = float(str(value).replace(',', '').strip())
    if not math.isfinite(result) or result < 0: raise ValueError('实际指标必须为非负有限数值')
    return int(result) if result.is_integer() else result

def iso_date(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return (date(1899, 12, 30)+timedelta(days=int(value))).isoformat()
    return date.fromisoformat(str(value).replace('/', '-')[:10]).isoformat()

def quarter(value):
    dt = date.fromisoformat(iso_date(value)); return f'{dt.year}Q{(dt.month-1)//3+1}'

def shift(q, delta):
    if not re.fullmatch(r'\d{4}Q[1-4]',q): raise ValueError('季度必须为YYYYQ1..Q4')
    z=int(q[:4])*4+int(q[-1])-1+delta
    return f'{z//4}Q{z%4+1}'

def quarter_bounds(q):
    start=date(int(q[:4]),(int(q[-1])-1)*3+1,1)
    nxt=shift(q,1); end=date(int(nxt[:4]),(int(nxt[-1])-1)*3+1,1)-timedelta(days=1)
    return start.isoformat(), end.isoformat()

def month_windows(start, end):
    start=date.fromisoformat(start); end=date.fromisoformat(end)
    if end<start: raise ValueError('结束日期早于开始日期')
    cursor=start.replace(day=1)
    while cursor<=end:
        last=cursor.replace(day=calendar.monthrange(cursor.year,cursor.month)[1])
        yield max(start,cursor).isoformat(),min(end,last).isoformat()
        cursor=(last+timedelta(days=1))

def product_list(value):
    if isinstance(value,list): result=value
    elif not value: result=[]
    elif str(value).startswith('['): result=json.loads(value)
    else: result=str(value).split('|')
    if any(x not in PRODUCTS for x in result): raise ValueError('products需明确填写三款产品名称，多个用|分隔')
    return list(dict.fromkeys(result))
