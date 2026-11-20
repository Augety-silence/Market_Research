"""真实原始数值聚合；固定五维向量×每季度关注权重。"""
import math
import statistics
from collections import defaultdict,Counter
from datetime import date,timedelta
from .io import PRODUCTS,DIMENSIONS,number,iso_date,quarter,quarter_bounds,shift,product_list


def video_summary(rows):
    unique={};duplicates=0
    for row in rows:
        product=row['product'];dt=iso_date(row['date']);q=quarter(dt);bv=row['bvid'];v=number(row['views'])
        if product not in PRODUCTS or not bv or v is None: raise ValueError('视频产品/BV/播放量不完整')
        if row.get('quarter') and row['quarter']!=q: raise ValueError('视频季度与发布日期不一致')
        key=(product,q,bv)
        if key in unique:
            duplicates+=1
            if number(unique[key]['views'])!=v: raise ValueError('重复BV累计播放冲突，须显式选定一次采集快照')
        unique[key]={**row,'quarter':q,'views':v}
    grouped=defaultdict(list)
    for row in unique.values(): grouped[row['quarter'],row['product']].append(row)
    result=[]
    for (q,p),group in sorted(grouped.items()):
        counts=sorted([r['views'] for r in group],reverse=True);total=sum(counts)
        result.append({'quarter':q,'product':p,'views':total,'bv':len(counts),'median':statistics.median(counts),
                       'without_top1':sum(counts[1:]),'top1_share':counts[0]/total if total else 0,
                       'top5_share':sum(counts[:5])/total if total else 0})
    return result,{'duplicate_rows':duplicates,'unique_bv_global':len({r['bvid'] for r in unique.values()}),
                   'view_semantics':'按发布季度汇总采集时累计播放量；不是季度新增播放量'}

def baidu_summary(rows):
    groups=defaultdict(dict)
    for r in rows:
        if r.get('region','全国')!='全国' or r.get('device','PC+移动')!='PC+移动':continue
        if r.get('metric','搜索指数')!='搜索指数':continue
        dt=iso_date(r['date']);key=quarter(dt),r['product'];v=number(r['index'])
        if dt in groups[key] and groups[key][dt]!=v: raise ValueError('百度同日指数冲突')
        groups[key][dt]=v
    result=[]
    for (q,p),values in sorted(groups.items()):
        valid=[v for v in values.values() if v is not None];begin,end=quarter_bounds(q)
        result.append({'quarter':q,'product':p,'index_mean':statistics.mean(valid) if valid else None,
                       'observed_days':len(valid),'expected_days':(date.fromisoformat(end)-date.fromisoformat(begin)).days+1})
    return result

def five_model(occurrences,exponent=.5):
    if not 0<exponent<=1: raise ValueError('压缩指数须在(0,1]内，对所有产品使用同一规则')
    demand=defaultdict(Counter);supply={p:Counter() for p in PRODUCTS};pure={p:Counter() for p in PRODUCTS};words=defaultdict(Counter)
    seen=set()
    for r in occurrences:
        key=(r['document_id'],int(r['token_index']))
        if key in seen: raise ValueError('重复词次；窗口交叠不能重复累计')
        seen.add(key);dim=r['dimension'];cnt=number(r.get('count',1))
        if cnt!=1: raise ValueError('词次表每行count必须为1，不能使用0/1文档命中表')
        if dim not in DIMENSIONS: continue
        if r['side']=='demand':
            demand[r['quarter']][dim]+=1;words[dim][r['word']]+=1
        elif r['side']=='supply':
            mask=int(r['product_mask'])
            for i,p in enumerate(PRODUCTS):
                if mask&(1<<i):
                    supply[p][dim]+=1
                    if '推广' in r.get('purpose','') and '待核' not in r.get('purpose',''): pure[p][dim]+=1
        else: raise ValueError('side须为demand/supply')
    features=[];vectors={};raw_vectors={}
    for p,counts in supply.items():
        raw=[counts[d] for d in DIMENSIONS];total=sum(raw)
        if not total: raise ValueError(p+'无固定内容五维词次，不能生成虚假零分')
        shares=[c/total for c in raw];compressed=[s**exponent for s in shares];den=sum(compressed)
        vectors[p]=[100*s/den for s in compressed];raw_vectors[p]=[100*s for s in shares]
        for i,d in enumerate(DIMENSIONS):features.append({'product':p,'dimension':d,'count':raw[i],'share':shares[i],'feature':vectors[p][i], 'pure_promotion_count':pure[p][d]})
    weights=[];scores=[]
    for q,counts in sorted(demand.items()):
        total=sum(counts.values())
        if not total: continue
        w=[counts[d]/total for d in DIMENSIONS]
        for i,d in enumerate(DIMENSIONS):weights.append({'quarter':q,'dimension':d,'count':counts[d],'weight':w[i]})
        for p in PRODUCTS:
            scores.append({'quarter':q,'product':p,'score':sum(a*b for a,b in zip(w,vectors[p])),
                           'uncompressed_score':sum(a*b for a,b in zip(w,raw_vectors[p]))})
    freq=[{'dimension':dim,'word':word,'count':count} for dim in DIMENSIONS for word,count in words[dim].most_common()]
    return {'features':features,'weights':weights,'scores':scores,'word_frequency':freq,
            'specification':{'dimensions':DIMENSIONS,'exponent':exponent,'feature_sum':100,
            'uses_video_views':False,'fixed_sample':'全文固定内容；纯推广词次另列','formula':'score[p,q] = sum(weight[q,d] * feature[p,d])'}}

def app_summary(sales,dau,apps,*,country='CN',device='iPhone',missing_policy='strict'):
    """strict：同组任何App缺失时组总值留空；observed：已观察值求和并附覆盖率。"""
    if missing_policy not in ('strict','observed'): raise ValueError('缺失策略无效')
    members=defaultdict(set)
    for app in apps:members[app['group']].add(app['name'])
    s=defaultdict(dict);d=defaultdict(dict);seen=set();dates=set();months=set()
    for kind,rows in [('sales',sales),('dau',dau)]:
        for r in rows:
            if r['country']!=country or r['device']!=device:continue
            dt=iso_date(r['date']);app=r['app'];key=(kind,r['app_id'],dt)
            if key in seen: raise ValueError('App实体日期重复，拒绝重复累计')
            seen.add(key)
            if app not in members[r['group']]: raise ValueError('App分类不匹配')
            if kind=='sales':
                month=dt[:7];months.add(month)
                for metric in ('downloads','revenue_usd'):
                    s[month,app].setdefault(metric,[]).append(number(r.get(metric)))
            else:
                dates.add(dt);months.add(dt[:7]);d[dt][app]=number(r.get('dau'))
    monthly=[]
    for month in sorted(months):
        import calendar
        year,mon=map(int,month.split('-'));expected=calendar.monthrange(year,mon)[1]
        observed_dates=sorted(dt for dt in dates if dt.startswith(month))
        for group,names in members.items():
            item={'month':month,'group':group,'expected_days':expected,'calendar_days':len(observed_dates)}
            for metric in ('downloads','revenue_usd'):
                values=[];coverage=0
                for app in names:
                    rr=s[month,app].get(metric,[])
                    if rr and all(v is not None for v in rr):coverage+=1;values.append(sum(rr))
                item[metric]=sum(values) if values and (coverage==len(names) or missing_policy=='observed') else None
                item[metric+'_app_coverage']=coverage/len(names)
            totals=[];obs=0
            for dt in observed_dates:
                vals=[d[dt].get(app) for app in names];obs+=sum(v is not None for v in vals)
                if all(v is not None for v in vals) or missing_policy=='observed' and any(v is not None for v in vals):
                    totals.append(sum(v for v in vals if v is not None))
            item.update(dau=statistics.mean(totals) if totals else None,dau_sum=sum(totals),
                        dau_valid_days=len(totals),dau_app_day_coverage=obs/(len(names)*expected))
            monthly.append(item)
    quarters=[];grouped=defaultdict(list)
    for r in monthly:grouped[quarter(r['month']+'-01'),r['group']].append(r)
    for (q,g),rows in sorted(grouped.items()):
        n=sum(r['dau_valid_days'] for r in rows);begin,end=quarter_bounds(q);expected=(date.fromisoformat(end)-date.fromisoformat(begin)).days+1
        item={'quarter':q,'group':g,'months':len(rows),'dau_valid_days':n,'expected_days':expected,
              'complete':len(rows)==3 and sum(r['calendar_days'] for r in rows)==expected,
              'dau':sum(r['dau_sum'] for r in rows)/n if n else None,'dau_day_coverage':n/expected}
        for metric in ('downloads','revenue_usd'):
            vals=[r[metric] for r in rows];item[metric]=sum(vals) if all(v is not None for v in vals) else None
        quarters.append(item)
    return {'monthly':monthly,'quarters':quarters,'units':{'downloads':'次','revenue_usd':'美元','dau':'设备日活（跨App未去重）'},'missing_policy':missing_policy}

def pearson(x,y):
    if len(x)<3 or len(set(x))<2 or len(set(y))<2:return None,None
    from scipy.stats import pearsonr
    result=pearsonr(x,y);return float(result.statistic),float(result.pvalue)

def lag_analysis(videos,apps,product='左旋肉碱',lags=(0,1,2)):
    b={r['quarter']:r['views'] for r in videos if r['product']==product}
    a={(r['quarter'],r['group']):r for r in apps if r['complete']}
    results=[]
    for group in sorted({g for q,g in a}):
        for metric in ('downloads','revenue_usd','dau'):
            for lag in lags:
                pairs=[];diff=[]
                for q in sorted(b):
                    aq=shift(q,-lag);prev=shift(q,-1);aprev=shift(aq,-1)
                    if (aq,group) not in a or a[aq,group][metric] is None: continue
                    # 视频发布季度只有完整日历季度参与；末期不足季度由上游配置筛选。
                    x=math.log1p(a[aq,group][metric]);y=math.log1p(b[q]);pairs.append((q,x,y))
                    if prev in b and (aprev,group) in a and a[aprev,group][metric] is not None:
                        diff.append((x-math.log1p(a[aprev,group][metric]),y-math.log1p(b[prev])))
                r,p=pearson([x for q,x,y in pairs],[y for q,x,y in pairs]);dr,dp=pearson([x for x,y in diff],[y for x,y in diff])
                results.append({'group':group,'metric':metric,'app_leads_quarters':lag,'n':len(pairs),'r':r,'p':p,
                                'difference_n':len(diff),'difference_r':dr,'difference_p':dp,
                                'pairs':[{'video_quarter':q,'app_quarter':shift(q,-lag)} for q,x,y in pairs]})
    return results


def group_daily_rows(dau,apps,*,country='CN',device='iPhone',missing_policy='strict'):
    """用于飞书AVERAGEIFS的逐日组总日活；缺失覆盖率可回溯。"""
    members=defaultdict(set);daily=defaultdict(dict)
    for app in apps:members[app['group']].add(app['name'])
    for row in dau:
        if row['country']==country and row['device']==device:
            dt=iso_date(row['date']);app=row['app']
            if app in daily[dt]:raise ValueError('同App同日出现重复日活')
            daily[dt][app]=number(row['dau'])
    result=[]
    for dt,rows in sorted(daily.items()):
        for group,names in members.items():
            values=[rows.get(app) for app in names];observed=sum(v is not None for v in values)
            valid=observed==len(names) or missing_policy=='observed' and observed>0
            result.append({'date':dt,'group':group,'country':country,'device':device,
                           'dau':sum(v for v in values if v is not None) if valid else None,
                           'observed_apps':observed,'expected_apps':len(names)})
    return result
