"""Sensor Tower独立API采集；下载、收入和DAU均使用实际单位。"""
import os
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from .http import request_json
from .state import Checkpoint
from .io import month_windows, atomic_json, write_csv, number

BASE='https://api.sensortower.com/v1'

def usage_batches(ids, start, end, limit=500):
    """API限制App数×天数<=500，拆月并拆App，覆盖闰日和非整月区间。"""
    for begin,last in month_windows(start,end):
        days=(date.fromisoformat(last)-date.fromisoformat(begin)).days+1
        size=max(1,limit//days)
        for i in range(0,len(ids),size): yield ids[i:i+size],begin,last

def app_map(config):
    apps=config['apps']; seen=set(); mapped={}
    for app in apps:
        if not app['name'] or not app['group']: raise ValueError('App名称和分类不能为空')
        for aid in app['sales_ids']:
            aid=str(aid)
            if aid in seen: raise ValueError('sales_ids出现重复实体')
            seen.add(aid);mapped[aid]=app
        if str(app['dau_id']) not in mapped or mapped[str(app['dau_id'])]['name']!=app['name']:
            raise ValueError('DAU主实体须属于同款App的sales_ids')
    if len({a['name'] for a in apps})!=len(apps): raise ValueError('逻辑App名称重复')
    return mapped

def collect(config):
    token=os.environ.get('SENSOR_TOWER_AUTH_TOKEN','').strip()
    if not token: raise ValueError('请设置SENSOR_TOWER_AUTH_TOKEN环境变量')
    if config.get('platform','ios')!='ios': raise ValueError('本采集器使用已验证的iOS接口')
    out=Path(config.get('output_dir','data'))/'sensor';out.mkdir(parents=True,exist_ok=True)
    meta=app_map(config); sales_ids=sorted(meta); dau_ids=sorted(str(a['dau_id']) for a in config['apps'])
    signature={k:config[k] for k in ('start_date','end_date','apps','country')}
    state=Checkpoint(out/'checkpoint.sqlite',{'schema':'sensor-v2',**signature})
    def query(path,params):
        def fetch():
            result=request_json('GET',BASE+path,params={**params,'auth_token':token})
            if not isinstance(result,list): raise ValueError('Sensor Tower返回结构变化，应为记录数组')
            # 防止错误响应被当成空采集存入断点。
            return {'records':result,'queried_at':datetime.now(timezone.utc).isoformat()}
        return state.fetch({'path':path,'params':params},fetch)['records']
    sales=[]; daily=[]
    try:
        for begin,last in month_windows(config['start_date'],config['end_date']):
            if begin[-2:]!='01': raise ValueError('月度下载收入采集的start_date须为月初')
            params={'app_ids':','.join(sales_ids),'countries':config['country'],'start_date':begin,'end_date':last,'date_granularity':'monthly'}
            sales.extend(query('/ios/sales_report_estimates',params))
            atomic_json(out/'sales_raw.json',sales)
            print('已保存下载/收入',begin[:7],flush=True)
        for ids,begin,last in usage_batches(dau_ids,config['start_date'],config['end_date']):
            params={'app_ids':','.join(ids),'countries':config['country'],'start_date':begin,'end_date':last,'date_granularity':'monthly','time_period':'day'}
            daily.extend(query('/ios/usage/active_users',params))
            atomic_json(out/'dau_raw.json',daily)
            print('已保存日活',begin[:7],'App实体数',len(ids),flush=True)
        sales_rows,dau_rows=normalize(config,sales,daily)
        write_csv(out/'sales.csv',sales_rows);write_csv(out/'dau.csv',dau_rows)
        atomic_json(out/'provenance.json',{'source':'Sensor Tower API','base':BASE,'config':signature,'sales_records':len(sales),'daily_records':len(daily),'complete':True,'units':{'downloads':'次','revenue_usd':'美元（API美分/100）','dau':'设备日活；跨App未去重'}})
    finally: state.close()

def normalize(config,sales,daily):
    meta=app_map(config);sr=[];dr=[];seen=set()
    for row in sales:
        aid=str(row['aid']);country=row['cc'];month=row['d'][:7]
        if aid not in meta or country!=config['country']: raise ValueError('下载收入响应实体或国家不匹配')
        if not config['start_date'][:7]<=month<=config['end_date'][:7]:raise ValueError('下载收入月份越界')
        for device,u,v in [('iPhone','iu','ir'),('iPad','au','ar')]:
            key=('sales',aid,country,month,device)
            if key in seen: raise ValueError('下载收入重复实体月份')
            seen.add(key);cents=number(row.get(v))
            sr.append({'app_id':aid,'app':meta[aid]['name'],'group':meta[aid]['group'],'date':month+'-01','country':country,'device':device,'downloads':number(row.get(u)),'revenue_usd':None if cents is None else cents/100})
    dau_ids={str(a['dau_id']) for a in config['apps']}
    for row in daily:
        aid=str(row['app_id']);country=row['country'];dt=row['date'][:10]
        if aid not in dau_ids or country!=config['country']: raise ValueError('日活响应实体或国家不匹配')
        if not config['start_date']<=dt<=config['end_date']: raise ValueError('日活日期越界')
        for device,col in [('iPhone','iphone_users'),('iPad','ipad_users')]:
            key=('dau',aid,country,dt,device)
            if key in seen: raise ValueError('日活重复实体日期')
            seen.add(key)
            dr.append({'app_id':aid,'app':meta[aid]['name'],'group':meta[aid]['group'],'date':dt,'country':country,'device':device,'dau':number(row.get(col))})
    return sorted(sr,key=lambda r:(r['date'],r['app_id'],r['device'])),sorted(dr,key=lambda r:(r['date'],r['app_id'],r['device']))
