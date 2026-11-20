"""合成数据端到端示例；不夹带真实评论、字幕或平台数据。"""
from pathlib import Path
from .io import PRODUCTS,DIMENSIONS,atomic_json,write_csv
from .text import prepare
from .annotation import annotate
from .analysis import video_summary,baidu_summary,five_model,app_summary,lag_analysis


def run(outdir,charts=False,font=None):
    out=Path(outdir);out.mkdir(parents=True,exist_ok=True)
    docs=[];videos=[];baidu=[];sales=[];dau=[];apps=[]
    dates=['2024-01-01','2024-04-01','2024-07-01','2024-10-01']
    for j,p in enumerate(PRODUCTS):
        docs.append({'id':f'supply-{j}','side':'supply','date':'2024-01-01','products':[p],'source':'合成字幕','purpose':'合成推广',
                     'text':p+'效果效果反弹副作用临床试验注射便宜'+('效果'*j)})
    for i,dt in enumerate(dates):
        docs.append({'id':f'demand-{i}','side':'demand','date':dt,'products':PRODUCTS,'source':'合成评论','text':'效果反弹副作用临床试验注射便宜'+('副作用'*i)})
        for j,p in enumerate(PRODUCTS):
            for n in range(2):videos.append({'product':p,'bvid':f'BVdemo{i}{j}{n}','title':'合成视频','date':dt,'views':(i+1)*(j+1)*100+n*20})
            baidu.append({'date':dt,'product':p,'index':100*(i+1)+j,'region':'全国','device':'PC+移动'})
    write_csv(out/'documents.csv',docs);prepared=prepare(out/'documents.csv',out/'prepared.json',all_tokens=True)
    dim_map={'效果':1,'反弹':1,'临床试验':2,'副作用':3,'注射':4,'便宜':5}
    labels=[]
    for unit in prepared['units']:
        mask=sum(1<<PRODUCTS.index(p) for p in unit['context_products'])
        labels.append({'id':unit['id'],'a':[[i,dim_map.get(w,0),0,mask if w in dim_map else 0] for i,w,a,b in unit['tokens']]})
    atomic_json(out/'manual.json',labels);occurrences=annotate(out/'prepared.json',out/'annotations',manual=out/'manual.json')
    from datetime import date,timedelta
    for j,g in enumerate(['Keep','其他运动','饮食体重']):
        app={'name':'合成App'+str(j),'group':g,'sales_ids':[str(j)],'dau_id':str(j)};apps.append(app)
        for month in range(1,13):
            sales.append({'app_id':str(j),'app':app['name'],'group':g,'date':f'2024-{month:02}-01','country':'CN','device':'iPhone','downloads':month*100+j,'revenue_usd':month*10+j})
        dt=date(2024,1,1)
        while dt<=date(2024,12,31):
            dau.append({'app_id':str(j),'app':app['name'],'group':g,'date':dt.isoformat(),'country':'CN','device':'iPhone','dau':dt.month*100+j});dt+=timedelta(days=1)
    b,audit=video_summary(videos);result={'schema':'synthetic-demo','config':{'apps':apps,'country':'CN','device':'iPhone','start_date':'2024-01-01','end_date':'2024-12-31'},'videos':b,'video_audit':audit,'baidu':baidu_summary(baidu),'model':five_model(occurrences),'apps':app_summary(sales,dau,apps)}
    result['lags']=lag_analysis(b,result['apps']['quarters']);atomic_json(out/'analysis.json',result)
    write_csv(out/'videos.csv',videos);write_csv(out/'baidu.csv',baidu);write_csv(out/'sales.csv',sales);write_csv(out/'dau.csv',dau)
    for k in ['features','weights','scores','word_frequency']:write_csv(out/(k+'.csv'),result['model'][k])
    if charts:
        from .charts import create
        create(result,out/'charts',font=font)
    print('合成数据端到端示例完成：',out)
    return result
