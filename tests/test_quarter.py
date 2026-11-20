import copy
import json
import tempfile
import unittest
from pathlib import Path
import importlib.util
if any(importlib.util.find_spec(name) is None for name in ("openpyxl", "requests")):
    raise unittest.SkipTest("季度导出测试需安装 .[quarter]")
from openpyxl import load_workbook
from bili_research.collectors.quarter_search import jobs_for, bounds, validate_page, VerificationRequired
from bili_research.exporters.quarter_store import Store
from bili_research.exporters.quarter_files import export_xlsx
from bili_research.exporters.quarter_feishu import Feishu

CONFIG={'keywords':['奥利司他','司美格鲁肽','左旋肉碱'],'start_date':'2024-01-01','end_date':'2026-11-16'}
ROOT=Path(__file__).resolve().parents[1]


def sample(job, page=1, bvs=('BV1UQEv6FEy7',), total=1, next_present=False):
    lo,_=bounds(job)
    return {'ok':True,'page':page,'total':total,'uiPage':page,'blocked':False,
            'domFirst':'https://www.bilibili.com/video/'+bvs[0] if bvs else None,
            'nextPresent':next_present,'nextDisabled':False,
            'videos':[{'bvid':bv,'play':100-i,'pubdate':lo,'title':'<em>奥利司他</em>，标题\n下一行'} for i,bv in enumerate(bvs)]}


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'state.sqlite3';self.store=Store(self.path,CONFIG)
        self.job=self.store.jobs()[0]
    def tearDown(self):
        self.store.close();self.temp.cleanup()

    def test_quarter_boundaries(self):
        jobs=jobs_for(CONFIG);self.assertEqual(len(jobs),36)
        self.assertEqual(jobs[-1]['end'],'2026-11-16')
        q=next(j for j in jobs if j['keyword']=='奥利司他' and j['quarter']=='2026Q2')
        self.assertEqual(bounds(q),(1774972800,1782835199))

    def test_reject_outside_dates(self):
        r=sample(self.job);r['videos'][0]['pubdate']=bounds(self.job)[0]-1
        with self.assertRaises(ValueError):validate_page(self.job,r,1)

    def test_captcha_stops(self):
        r=sample(self.job);r['blocked']=True
        with self.assertRaises(VerificationRequired):validate_page(self.job,r,1)

    def test_play_count_is_not_rounded(self):
        r=sample(self.job);r['videos'][0]['play']='4.2万'
        with self.assertRaises(ValueError):validate_page(self.job,r,1)

    def test_dom_drives_next_even_when_server_says_end(self):
        r=sample(self.job,next_present=True);r['server_next']=0
        self.assertEqual(validate_page(self.job,r,1)['next_page'],2)

    def test_overlap_pages_and_restart(self):
        r=validate_page(self.job,sample(self.job,bvs=('BV1UQEv6FEy7','BV1jzDaBCEWo'),total=3,next_present=True),1)
        self.job=self.store.save(self.job,r)
        self.store.close();self.store=Store(self.path,CONFIG)
        self.job=next(j for j in self.store.jobs() if j['keyword']==self.job['keyword'] and j['quarter']==self.job['quarter'])
        self.assertEqual(self.job['next_page'],2)
        r=validate_page(self.job,sample(self.job,page=2,bvs=('BV1jzDaBCEWo','BV1Anj36jEpW'),total=3),2)
        self.job=self.store.save(self.job,r)
        self.assertEqual(self.store.count(self.job['keyword'],self.job['quarter']),3)
        self.assertEqual(self.job['status'],'已完成')
        self.assertIn('\n',self.store.rows()[0][3])

    def test_changed_search_set_not_combined(self):
        self.job=self.store.save(self.job,validate_page(self.job,sample(self.job,total=2,next_present=True),1))
        with self.assertRaises(RuntimeError):self.store.save(self.job,validate_page(self.job,sample(self.job,page=2,total=3),2))
        self.assertEqual(self.store.count(self.job['keyword'],self.job['quarter']),1)

    def test_page_transaction_rolls_back_on_bad_count(self):
        result=sample(self.job,bvs=('BV1UQEv6FEy7','BV1jzDaBCEWo'),total=1);result['next_page']=0
        with self.assertRaises(RuntimeError):self.store.save(self.job,result)
        self.assertEqual(len(self.store.rows()),0)
        self.assertEqual(self.store.jobs()[0]['last_page'],0)

    def test_mismatch_tail_marked(self):
        self.job=self.store.save(self.job,validate_page(self.job,sample(self.job,total=2),1))
        self.assertEqual(self.job['status'],'数量待核验')

    def test_snapshot_and_six_charts(self):
        from bili_research.collectors.quarter_search import fingerprint,video_rows
        seed={'fingerprint':fingerprint(CONFIG),'videos':[],'jobs':[]}
        for j in self.store.jobs():
            result=sample(j,bvs=('BV0000000001','BV0000000002'),total=2)
            seed['videos'].extend(video_rows(j,result))
            seed['jobs'].append(dict(j,last_page=1,next_page=0,total=2,status='已完成',updated='2024-01-01'))
        self.assertEqual(self.store.seed(seed),72)
        self.assertTrue(all(j['status']=='已完成' for j in self.store.jobs()))
        self.assertEqual(len({r[2] for r in self.store.rows()}),2)
        self.assertEqual(sum(r[5] for r in self.store.rows()),7164)
        path=Path(self.temp.name)/'result.xlsx';export_xlsx(self.store,CONFIG,path)
        wb=load_workbook(path)
        self.assertEqual(len(wb['独立趋势图']._charts),6)
        self.assertTrue(all(len(c.series)==1 for c in wb['独立趋势图']._charts))
        self.assertEqual(sum(c.data_type=='f' for row in wb['季度汇总'] for c in row),72)
        self.assertEqual(wb['视频明细'].max_row,73)

    def test_config_change_rejected(self):
        cfg=dict(CONFIG,end_date='2026-11-18')
        with self.assertRaises(RuntimeError):Store(self.path,cfg)

    def test_fixed_row_retry_after_remote_failure(self):
        self.store.save(self.job,validate_page(self.job,sample(self.job),1))
        class Fake(Feishu):
            def __init__(self):
                self.config={'spreadsheet_token':'test','detail_sheet_id':'detail','progress_sheet_id':'progress','summary_sheet_id':'summary'}
                self.values={};self.attempts=[];self.fail=True
            def capacity(self,*args):pass
            def styles(self,*args):pass
            def write(self,ranges):
                for sid,area,values in ranges:
                    self.attempts.append((sid,area));self.values[sid,area]=values
                if self.fail:self.fail=False;raise RuntimeError('模拟远端已经写入，但返回丢失')
            def read(self,sid,area,formulas=False):return self.values.get((sid,area),[])
            def summary(self,store):pass
        api=Fake()
        with self.store.db:
            self.store.set_meta('remote_binding',api.binding());self.store.set_meta('remote_next_row',2)
        with self.assertRaises(RuntimeError):api.sync(self.store)
        assigned=self.store.db.execute('SELECT remote_row,remote_ok FROM videos').fetchone()
        self.assertEqual(tuple(assigned),(2,0))
        api.sync(self.store)
        self.assertEqual(api.attempts[:2],[('detail','A2:I2'),('detail','A2:I2')])
        self.assertEqual(tuple(self.store.db.execute('SELECT remote_row,remote_ok FROM videos').fetchone()),(2,1))
        self.assertEqual(self.store.meta('remote_next_row'),3)


if __name__=='__main__':unittest.main()
