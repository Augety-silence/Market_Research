"""关键数据口径与恢复行为；使用合成数据，不联网。"""
import calendar
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from datetime import date,timedelta
import requests
from market_research.io import PRODUCTS,DIMENSIONS,quarter,quarter_bounds,shift,number,read_json,write_csv
from market_research.state import Checkpoint
from market_research.sensor import usage_batches,normalize
from market_research.bilibili import validate_search
from market_research.analysis import video_summary,baidu_summary,five_model,app_summary,lag_analysis
from market_research.annotation import validate
from market_research.http import request_json,HTTPError

class StateTests(unittest.TestCase):
    def test_resume_and_changed_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'state.sqlite';s=Checkpoint(path,{'dates':['2023','2024']})
            s.put({'page':1},[]);s.close();s=Checkpoint(path,{'dates':['2023','2024']})
            with patch('builtins.print'):
                self.assertEqual(s.fetch({'page':1},lambda:self.fail('断点已完成不应重复请求')),[])
            with self.assertRaises(RuntimeError):s.fetch({'page':2},lambda:(_ for _ in ()).throw(RuntimeError('失败')))
            self.assertIsNone(s.get({'page':2}));s.close()
            with self.assertRaises(ValueError):Checkpoint(path,{'dates':['2023','2025']})
    def test_error_does_not_expose_secret(self):
        with patch('requests.request',side_effect=requests.RequestException('auth_token=SECRET')),patch('time.sleep'):
            with self.assertRaises(HTTPError) as ctx:request_json('GET','https://example.com',attempts=1)
        self.assertNotIn('SECRET',str(ctx.exception))

class SensorTests(unittest.TestCase):
    def test_usage_batches_cover_leap_year(self):
        ids=[str(i) for i in range(25)];batches=list(usage_batches(ids,'2024-02-01','2024-03-02'))
        counts={}
        for group,a,b in batches:
            days=(date.fromisoformat(b)-date.fromisoformat(a)).days+1
            self.assertLessEqual(len(group)*days,500)
            counts.setdefault((a,b),[]).extend(group)
        self.assertTrue(all(set(v)==set(ids) and len(v)==len(ids) for v in counts.values()))
        self.assertIn(('2024-02-01','2024-02-29'),counts)
    def test_sensor_cents_and_none_and_duplicates(self):
        config={'country':'CN','start_date':'2023-01-01','end_date':'2023-01-31','apps':[{'name':'App','group':'运动','sales_ids':['1'],'dau_id':'1'}]}
        sales=[{'aid':1,'cc':'CN','d':'2023-01-01','iu':4,'ir':1234,'au':None,'ar':None}]
        daily=[{'app_id':1,'country':'CN','date':'2023-01-01','iphone_users':100,'ipad_users':None}]
        sr,dr=normalize(config,sales,daily);iphone=next(r for r in sr if r['device']=='iPhone');ipad=next(r for r in sr if r['device']=='iPad')
        self.assertEqual(iphone['revenue_usd'],12.34);self.assertIsNone(ipad['revenue_usd'])
        self.assertIsNone(next(r for r in dr if r['device']=='iPad')['dau'])
        with self.assertRaises(ValueError):normalize(config,sales,daily+daily)

class VideoTests(unittest.TestCase):
    def test_dedup_top1_and_actual_units(self):
        rows=[{'product':PRODUCTS[0],'date':'2024-07-01','bvid':'a','views':100},{'product':PRODUCTS[0],'date':'2024-07-02','bvid':'b','views':20}]
        result,audit=video_summary(rows+[rows[0]]);r=result[0]
        self.assertEqual((r['views'],r['bv'],r['without_top1']),(120,2,20));self.assertEqual(audit['duplicate_rows'],1)
        with self.assertRaises(ValueError):video_summary(rows+[dict(rows[0],views=101)])
    def test_http_rejects_inactive_date_filter(self):
        from bili_research.collectors.quarter_search import bounds
        job={'keyword':PRODUCTS[0],'start':'2024-07-01','end':'2024-09-30'};begin,end=bounds(job)
        data={'page':1,'numResults':1,'numPages':1,'result':[{'bvid':'BV1234567890','pubdate':begin,'play':100}]}
        self.assertEqual(validate_search(job,1,data)[1],1)
        data['result'][0]['pubdate']=begin-1
        with self.assertRaises(ValueError):validate_search(job,1,data)

class WordTests(unittest.TestCase):
    def test_repeated_tokens_and_offsets(self):
        from market_research.text import segment
        text,tokens=segment('副作用副作用反弹反弹 [doge] https://example.com')
        self.assertEqual(sum(w=='副作用' for w,a,b in tokens),2)
        self.assertEqual(sum(w=='反弹' for w,a,b in tokens),2)
        self.assertTrue(all(text[a:b]==w for w,a,b in tokens))
        self.assertFalse(any(w in ['doge','example'] for w,a,b in tokens))
    def test_annotation_coverage_and_mask(self):
        unit={'id':'a','tokens':[[0,'效果',0,2],[1,'效果',2,4]]}
        self.assertEqual(len(validate({'id':'a','a':[[0,1,0,4],[1,1,0,4]]},unit)),2)
        for values in [[[0,1,0,4]],[[0,1,0,4],[0,1,0,4]],[[0,0,3,4],[1,1,0,4]]]:
            with self.assertRaises(ValueError):validate({'id':'a','a':values},unit)
    def test_model_fixed_features_and_quarter_weights(self):
        rows=[]
        for j,p in enumerate(PRODUCTS):
            for i,d in enumerate(DIMENSIONS):
                for n in range(i+1+j):rows.append({'document_id':'s'+str(j),'token_index':len(rows),'side':'supply','dimension':d,'word':'词','product_mask':1<<j,'count':1,'purpose':'推广'})
        for q,dimension in [('2024Q1',DIMENSIONS[0]),('2024Q2',DIMENSIONS[2])]:
            rows.append({'document_id':q,'token_index':0,'side':'demand','quarter':q,'dimension':dimension,'word':'词','count':1})
        model=five_model(rows)
        for p in PRODUCTS:
            fs=[r['feature'] for r in model['features'] if r['product']==p];self.assertAlmostEqual(sum(fs),100);self.assertLess(max(fs),100)
            scores=[r['score'] for r in model['scores'] if r['product']==p];self.assertAlmostEqual(scores[0],fs[0]);self.assertAlmostEqual(scores[1],fs[2])
        self.assertFalse(model['specification']['uses_video_views'])
        with self.assertRaises(ValueError):five_model(rows+[rows[0]])

class AggregateTests(unittest.TestCase):
    def test_baidu_excludes_missing(self):
        rows=[{'date':'2024-01-01','product':PRODUCTS[0],'index':None},{'date':'2024-01-02','product':PRODUCTS[0],'index':200}]
        result=baidu_summary(rows)[0];self.assertEqual(result['index_mean'],200);self.assertEqual(result['observed_days'],1)
    def test_dau_day_weighting_not_mean_month_means(self):
        apps=[{'name':'A','group':'g'}];sales=[];daily=[]
        for month,value in [(1,100),(2,200),(3,300)]:
            sales.append({'app_id':'1','app':'A','group':'g','country':'CN','device':'iPhone','date':f'2024-{month:02}-01','downloads':10,'revenue_usd':1})
            for day in range(1,calendar.monthrange(2024,month)[1]+1):daily.append({'app_id':'1','app':'A','group':'g','country':'CN','device':'iPhone','date':f'2024-{month:02}-{day:02}','dau':value})
        result=app_summary(sales,daily,apps)['quarters'][0]
        self.assertAlmostEqual(result['dau'],(31*100+29*200+31*300)/91);self.assertEqual(result['downloads'],30);self.assertTrue(result['complete'])
    def test_missing_app_is_not_zero(self):
        apps=[{'name':'A','group':'g'},{'name':'B','group':'g'}]
        daily=[{'app_id':'1','app':'A','group':'g','country':'CN','device':'iPhone','date':'2024-01-01','dau':100}]
        self.assertIsNone(app_summary([],daily,apps)['monthly'][0]['dau'])
        observed=app_summary([],daily,apps,missing_policy='observed')['monthly'][0]
        self.assertEqual(observed['dau'],100);self.assertLess(observed['dau_app_day_coverage'],1)
    def test_lag_direction_and_complete_quarters(self):
        videos=[{'quarter':q,'product':PRODUCTS[2],'views':i*10} for i,q in enumerate(['2024Q1','2024Q2','2024Q3','2024Q4'],1)]
        apps=[{'quarter':q,'group':'g','complete':True,'dau':i,'downloads':i,'revenue_usd':i} for i,q in enumerate(['2023Q4','2024Q1','2024Q2','2024Q3'],1)]
        results=lag_analysis(videos,apps);r=next(r for r in results if r['metric']=='dau' and r['app_leads_quarters']==1)
        self.assertEqual(r['n'],4);self.assertEqual(r['pairs'][0],{'video_quarter':'2024Q1','app_quarter':'2023Q4'})
    def test_quarter_edges(self):
        self.assertEqual(quarter_bounds('2024Q4'),('2024-10-01','2024-12-31'));self.assertEqual(shift('2024Q1',-1),'2023Q4')
        self.assertIsNone(number(''))
        with self.assertRaises(ValueError):number(True)

class FeishuTests(unittest.TestCase):
    def test_chunk_resume_only_after_readback(self):
        from market_research.feishu import sync_plan
        class FakeAPI:
            storage={};writes=0
            def __init__(self,cfg):pass
            def sheets(self):return [{'sheet_id':'s'}]
            def capacity(self,*a):pass
            def write(self,ranges):
                self.__class__.writes+=1
                for sid,area,values in ranges:self.storage[sid,area]=values
            def read(self,sid,area,formulas=False):return self.storage[sid,area]
        plan=[{'sheet_id':'s','values':[['a'],[1],[2],[3]]}]
        with tempfile.TemporaryDirectory() as tmp,patch('market_research.feishu.FeishuAPI',FakeAPI):
            sync_plan({'spreadsheet_token':'x'},plan,Path(tmp)/'sync.sqlite',chunk=2)
            self.assertEqual(FakeAPI.writes,2)
            sync_plan({'spreadsheet_token':'x'},plan,Path(tmp)/'sync.sqlite',chunk=2)
            self.assertEqual(FakeAPI.writes,2)
    def test_formula_plan_and_csv_text(self):
        from market_research.feishu import formula_plan,csv_plan
        a={'videos':[{'quarter':'2024Q1','product':PRODUCTS[0]}]}
        plan=formula_plan({'summary_sheet_id':'s','raw_sheet_names':{'videos':'视频Raw'}},a)
        self.assertIn('SUMIFS',plan[0]['values'][1][2]['text']);self.assertIn('MAXIFS',plan[0]['values'][1][4]['text'])
        with tempfile.TemporaryDirectory() as tmp:
            f=Path(tmp)/'raw.csv';write_csv(f,[{'product':PRODUCTS[0],'title':'=HYPERLINK("x")','date':'2024-01-01','views':10}])
            row=csv_plan(f,'s',date_columns=['date'])[0]['values'][1]
            self.assertEqual(row[1]['type'],'text');self.assertIsInstance(row[2],int);self.assertEqual(row[3],10)

class EndToEndTests(unittest.TestCase):
    def test_demo_all_formula_modules(self):
        from market_research.demo import run
        from market_research.feishu import formula_plan
        with tempfile.TemporaryDirectory() as tmp:
            a=run(tmp)
            plan=formula_plan({'summary_sheet_id':'s','raw_sheet_names':{'videos':'v','occurrences':'w','baidu':'b','sales':'sale','app_group_daily':'daily'}},a)
            all_formulas=[c['text'] for b in plan for r in b['values'] for c in r if isinstance(c,dict) and c.get('type')=='formula']
            self.assertTrue(any('SUMPRODUCT' in f for f in all_formulas))
            self.assertTrue(any("'daily'!" in f and 'AVERAGEIFS' in f for f in all_formulas))
            self.assertTrue(any('MAXIFS' in f for f in all_formulas))
            self.assertEqual(len(a['model']['features']),15)
    def test_pdf_one_image_per_slide(self):
        import fitz
        from pptx import Presentation
        from market_research.presentation import pdf_to_ppt
        with tempfile.TemporaryDirectory() as tmp:
            pdf=Path(tmp)/'x.pdf';ppt=Path(tmp)/'x.pptx'
            with fitz.open() as doc:
                for n in range(2):doc.new_page(width=480,height=270).insert_text((30,30),'Synthetic slide '+str(n))
                doc.save(pdf)
            self.assertEqual(pdf_to_ppt(pdf,ppt,dpi=72),2)
            deck=Presentation(ppt)
            for slide in deck.slides:
                self.assertEqual(len(slide.shapes),1);self.assertEqual(slide.shapes[0].width,deck.slide_width)

if __name__=='__main__':unittest.main()
