"""季度飞书导出：绑定核验、固定行同步、断点与公式汇总。"""
import json
import time
from datetime import date, timedelta
from ..core.feishu_api import FeishuAPI
from ..collectors.quarter_search import HEADERS, PROGRESS_HEADERS

def scalar(value):
    if isinstance(value, dict):
        return value.get('text', value.get('value', ''))
    if isinstance(value, list):
        return ''.join(str(scalar(x)) for x in value)
    return value


def normalize_row(row):
    row = [scalar(v) for v in row] + [''] * max(0, 9-len(row))
    for index in (5, 7):
        row[index] = int(float(str(row[index]).replace(',', '')))
    if isinstance(row[4], (int,float)):
        row[4] = (date(1899,12,30) + timedelta(days=int(row[4]))).isoformat()
    else:
        row[4] = str(row[4]).replace('/', '-')[:10]
    return row[:9]


def typed(value):
    # 所有采集字符串明确按文本写入，避免标题开头的等号被识别为公式。
    return {'type':'text','text':value} if isinstance(value,str) else value


class Feishu(FeishuAPI):
    def binding(self):
        return {k:self.config[k] for k in ('spreadsheet_token','detail_sheet_id','progress_sheet_id','summary_sheet_id')}

    def bind_existing(self, store):
        rows = store.rows()
        if not rows:
            raise RuntimeError('先运行 init --from-snapshot 导入完整快照')
        sid = self.config['detail_sheet_id']
        headers = [scalar(v) for v in self.read(sid,'A1:I1')[0]]
        if headers != HEADERS:
            raise RuntimeError('线上明细表头与代码预期不一致')
        remote = []
        grid = next(s for s in self.sheets() if s['sheet_id']==sid)['grid_properties']['row_count']
        for start in range(2,grid+1,250):
            block = self.read(sid,f'A{start}:I{min(grid,start+249)}')
            for offset,row in enumerate(block):
                if any(scalar(v) not in ('',None) for v in row):
                    remote.append((start+offset,normalize_row(row)))
        local = {(r[0],r[1],r[2]):r for r in rows}
        if len(remote)!=len(local):
            raise RuntimeError('线上条数与本地快照不一致，禁止绑定或覆盖')
        assignments=[];seen=set()
        for rowno,row in remote:
            key=tuple(row[i] for i in (0,1,2))
            if key in seen or key not in local or local[key]!=row:
                raise RuntimeError('线上内容与本地快照不一致；没有覆盖原数据')
            seen.add(key);assignments.append((rowno,*key))
        with store.db:
            for assignment in assignments:
                store.db.execute('UPDATE videos SET remote_row=?,remote_ok=1 WHERE keyword=? AND quarter=? AND bvid=?',assignment)
            store.set_meta('remote_binding',self.binding())
            store.set_meta('remote_next_row',max(rowno for rowno,_ in remote)+1)
        return len(assignments)

    def bind_empty(self, store):
        if store.meta('remote_binding'):
            raise RuntimeError('数据库已经绑定目标表')
        sheets={s['sheet_id']:s for s in self.sheets()}
        for key,lastcol,header in [('detail_sheet_id','I',HEADERS),('progress_sheet_id','K',PROGRESS_HEADERS)]:
            sid=self.config[key];grid=sheets[sid]['grid_properties']['row_count']
            for start in range(1,grid+1,250):
                for offset,row in enumerate(self.read(sid,f'A{start}:{lastcol}{min(grid,start+249)}')):
                    values=[scalar(v) for v in row]
                    if start+offset==1 and values==header:
                        continue
                    if any(v not in ('',None) for v in values):
                        raise RuntimeError('目标工作表已有数据；请选择空白表，或导入快照后 bind-existing')
        sid=self.config['summary_sheet_id']
        if any(scalar(v) not in ('',None) for row in self.read(sid,'A5:I20') for v in row):
            raise RuntimeError('目标季度汇总已有内容，禁止覆盖')
        self.write([(self.config['detail_sheet_id'],'A1:I1',[[typed(v) for v in HEADERS]]),
                    (self.config['progress_sheet_id'],'A1:K1',[[typed(v) for v in PROGRESS_HEADERS]])])
        with store.db:
            store.set_meta('remote_binding',self.binding());store.set_meta('remote_next_row',2)

    def sync(self, store):
        if store.meta('remote_binding')!=self.binding():
            raise RuntimeError('请先 bind-empty 或 bind-existing，绑定并核验目标表')
        pending=store.db.execute('SELECT * FROM videos WHERE remote_ok=0 ORDER BY id').fetchall()
        with store.db:
            next_row=store.meta('remote_next_row')
            for record in pending:
                if record['remote_row'] is None:
                    store.db.execute('UPDATE videos SET remote_row=? WHERE id=?',(next_row,record['id']))
                    next_row+=1
            store.set_meta('remote_next_row',next_row)
        pending=store.db.execute('SELECT * FROM videos WHERE remote_ok=0 ORDER BY remote_row').fetchall()
        sid=self.config['detail_sheet_id']
        for start in range(0,len(pending),100):
            batch=pending[start:start+100]
            # 绑定与重试确保该批行号连续，超时后始终写回相同位置。
            rownos=[r['remote_row'] for r in batch]
            if rownos!=list(range(rownos[0],rownos[-1]+1)):
                raise RuntimeError('待同步行号不连续，请检查本地数据库')
            self.capacity(sid,rownos[-1])
            rows=[json.loads(r['row_json']) for r in batch]
            area=f'A{rownos[0]}:I{rownos[-1]}'
            values = [[typed(v) for v in row] for row in rows]
            for row, record in zip(values, rows):
                row[4] = (date.fromisoformat(record[4]) - date(1899,12,30)).days
            self.styles(sid,f'E{rownos[0]}:E{rownos[-1]}','yyyy-mm-dd')
            self.styles(sid,f'F{rownos[0]}:F{rownos[-1]}','#,##0')
            self.write([(sid,area,values)])
            actual=[normalize_row(row) for row in self.read(sid,area)]
            if actual!=rows:
                raise RuntimeError('飞书回读与本地记录不同；未标记同步成功')
            with store.db:
                store.db.executemany('UPDATE videos SET remote_ok=1 WHERE id=?',[(r['id'],) for r in batch])
        progress=store.progress();psid=self.config['progress_sheet_id']
        self.capacity(psid,len(progress)+1)
        self.write([(psid,f'A2:K{len(progress)+1}',[[typed(v) for v in row] for row in progress])])
        actual=self.read(psid,f'A2:K{len(progress)+1}')
        if len(actual)!=len(progress) or any(int(scalar(a[7]))!=b[7] or scalar(a[4])!=b[4] for a,b in zip(actual,progress)):
            raise RuntimeError('飞书断点回读不一致')
        self.summary(store)

    def summary(self, store):
        jobs=store.jobs();quarters=sorted({j['quarter'] for j in jobs})
        drugs=self.config.get('keywords',['奥利司他','司美格鲁肽','左旋肉碱'])
        if len(quarters)!=12 or len(drugs)!=3:
            raise RuntimeError('在线原表布局支持12季度3关键词；其他范围请用本地export或另建表布局')
        sid=self.config['summary_sheet_id'];detail=self.config.get('detail_sheet_name','视频明细').replace("'","''")
        matrix=[['汇总方式','公式直接引用视频明细','','','','','','',''],
                ['',drugs[0],'',drugs[1],'',drugs[2],'','三类合计',''],
                ['季度','累计播放量','BV数','累计播放量','BV数','累计播放量','BV数','累计播放量','BV数']]
        expected=[]
        source=store.rows()
        for n,q in enumerate(quarters,8):
            row=[typed(q)];want=[]
            for col,drug in zip(('B','D','F'),drugs):
                row += [{'type':'formula','text':f"=SUMIFS('{detail}'!$F:$F,'{detail}'!$A:$A,{col}$6,'{detail}'!$B:$B,$A{n})"},
                        {'type':'formula','text':f"=COUNTIFS('{detail}'!$A:$A,{col}$6,'{detail}'!$B:$B,$A{n},'{detail}'!$C:$C,\"<>\")"}]
                subset=[r for r in source if r[0]==drug and r[1]==q];want.extend([sum(r[5] for r in subset),len(subset)])
            row.extend([{'type':'formula','text':f'=SUM(B{n},D{n},F{n})'}, {'type':'formula','text':f'=SUM(C{n},E{n},G{n})'}])
            matrix.append(row);expected.append(want+[sum(want[i] for i in (0,2,4)),sum(want[i] for i in (1,3,5))])
        matrix.append([typed('合计')]+[{'type':'formula','text':f'=SUM({col}8:{col}19)'} for col in 'BCDEFGHI'])
        matrix[:3]=[[typed(v) for v in row] for row in matrix[:3]]
        self.write([(sid,'A5:I20',matrix)])
        self.styles(sid,'B8:I20','#,##0')
        for _ in range(10):
            actual=self.read(sid,'B8:I19')
            try:
                numeric=[[int(float(str(scalar(v)).replace(',',''))) for v in row] for row in actual]
            except (ValueError,TypeError):
                numeric=[]
            if numeric==expected:
                break
            time.sleep(1)
        else:
            raise RuntimeError('在线公式结果与明细不同，检查表名和公式权限')
        formulas=self.read(sid,'B8:I20',formulas=True)
        if sum(str(scalar(v)).startswith('=') for row in formulas for v in row)!=104:
            raise RuntimeError('未回读到104个公式；不将纯数值冒充公式')
