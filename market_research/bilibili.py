"""纯HTTP季度搜索与语料采集；每一页API结果即时入SQLite。"""
import html
import json
import re
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from bili_research.core.client import Client, read_cookie
from bili_research.collectors.quarter_search import jobs_for, bounds, search_url
from bili_research.collectors.video import get_view, video_meta, subtitle_tracks, pick_chinese, track_url_ok, fetch_subtitle
from bili_research.collectors.comments import fetch_all_comments
from bili_research.collectors.subtitles import coverage
from .state import Checkpoint
from .io import atomic_json, write_csv, read_rows, product_list, quarter, iso_date

class CachedClient(Client):
    def __init__(self,state,**kwargs): super().__init__(**kwargs);self.state=state
    def get_json(self,path,params=None,signed=False,referer='https://www.bilibili.com/'):
        key={'path':path,'params':params or {},'signed':signed}
        return self.state.fetch(key,lambda:super(CachedClient,self).get_json(path,params,signed,referer))

def validate_search(job,page,data):
    if data.get('page')!=page: raise ValueError('搜索返回页码不匹配')
    total=data.get('numResults');pages=data.get('numPages');videos=data.get('result') or []
    if type(total) is not int or total<0 or type(pages) is not int or pages<0: raise ValueError('缺少准确搜索总数')
    if total>0 and not videos: raise ValueError('本页为空，不能标记采集完成')
    begin,end=bounds(job);seen=set()
    for v in videos:
        if not re.fullmatch(r'BV[0-9A-Za-z]{10}',v.get('bvid','')): raise ValueError('BV号无效')
        if type(v.get('pubdate')) is not int or not begin<=v['pubdate']<=end:
            raise ValueError('HTTP接口未应用日期筛选，请使用仓库已有独立Playwright适配器；已停止，未保存越界页')
        if type(v.get('play')) is not int or v['play']<0: raise ValueError('播放量不是准确整数')
        if v['bvid'] in seen: raise ValueError('同页出现重复BV')
        seen.add(v['bvid'])
    if any(a['play']<b['play'] for a,b in zip(videos,videos[1:])): raise ValueError('搜索未按播放量排序')
    return videos,total,pages

def collect_search(config):
    out=Path(config.get('output_dir','data'))/'bilibili';out.mkdir(parents=True,exist_ok=True)
    signature={k:config[k] for k in ('keywords','start_date','end_date')}
    state=Checkpoint(out/'search.sqlite',{'schema':'bili-http-v2',**signature})
    client=Client(cookie=read_cookie(config.get('cookie_file')),interval=config.get('interval',2.5))
    allrows=[];progress=[]
    try:
        for job in jobs_for(config):
            page=1;unique={};expected=None
            while True:
                begin,end=bounds(job)
                params={'search_type':'video','keyword':job['keyword'],'order':'click','pubtime_begin_s':begin,'pubtime_end_s':end,'page':page,'page_size':42}
                key={'job':job,'page':page}
                def fetch():
                    data=client.get_json('/x/web-interface/wbi/search/type',params,signed=True,referer=search_url(job,page))
                    validate_search(job,page,data)
                    return {'data':data,'collected_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()}
                pack=state.fetch(key,fetch);videos,total,pages=validate_search(job,page,pack['data'])
                if expected is not None and total!=expected: raise ValueError('搜索总数变化，请新建输出目录重采')
                expected=total
                for v in videos:
                    if v['bvid'] in unique: raise ValueError('分页重复BV，拒绝把搜索截断当作完成')
                    unique[v['bvid']]={'product':job['keyword'],'quarter':job['quarter'],'bvid':v['bvid'],
                        'title':html.unescape(re.sub('<[^>]*>','',v['title'])),
                        'date':datetime.fromtimestamp(v['pubdate'],ZoneInfo('Asia/Shanghai')).date().isoformat(),
                        'views':v['play'],'source_page':page,'source_url':search_url(job,page),'collected_at':pack['collected_at']}
                write_csv(out/'videos.csv',allrows+list(unique.values()))
                atomic_json(out/'progress.json',progress+[{'job':job,'saved_page':page,'saved_bv':len(unique),'expected_bv':total,'complete':False}])
                print(job['keyword'],job['quarter'],'页',page,'BV',len(unique),'/',total,flush=True)
                if page>=pages: break
                page+=1
            complete=len(unique)==total
            progress.append({'job':job,'saved_page':page,'saved_bv':len(unique),'expected_bv':total,'complete':complete})
            allrows.extend(unique.values());write_csv(out/'videos.csv',allrows);atomic_json(out/'progress.json',progress)
            if not complete: raise ValueError('搜索页上限或集合变化导致数量不足，断点和已采数据保留')
        atomic_json(out/'provenance.json',{'source':'Bilibili HTTP search','complete':True,'config':signature,'view_semantics':'发布季度内视频在采集时的累计播放量，不是当季新增播放'})
    finally:state.close()

def collect_corpus(source,outdir,*,cookie_file=None,interval=2.5,max_sub_pages=1000):
    videos=read_rows(source);out=Path(outdir);out.mkdir(parents=True,exist_ok=True)
    state=Checkpoint(out/'corpus.sqlite',{'schema':'corpus-v2','videos':videos,'max_sub_pages':max_sub_pages})
    client=CachedClient(state,cookie=read_cookie(cookie_file),interval=interval);client.require_login()
    documents=[];statuses=[];seen=set()
    try:
        for entry in videos:
            bvid=entry['bvid']
            if bvid in seen: raise ValueError('语料清单BV重复，请先合并products')
            seen.add(bvid);products=product_list(entry.get('products',entry.get('product')))
            view=get_view(client,bvid);meta=video_meta(view)
            pubdate=datetime.fromtimestamp(meta['pubdate'],ZoneInfo('Asia/Shanghai')).date().isoformat()
            # 多P视频每个分P单独保留全文和覆盖率。
            for p in meta['pages']:
                cid=p['cid'];track=pick_chinese(subtitle_tracks(client,bvid,meta['aid'],cid))
                status={'bvid':bvid,'cid':cid,'subtitle_status':'missing'}
                if track:
                    url=track['subtitle_url']
                    if not track_url_ok(url,meta['aid'],cid): raise ValueError('字幕串片校验失败')
                    segments=state.fetch({'kind':'subtitle','bvid':bvid,'cid':cid},lambda:fetch_subtitle(client,url,bvid))
                    ratio=coverage(segments,p['duration']);status.update(subtitle_status='available',coverage=ratio)
                    atomic_json(out/f'{bvid}_{cid}_subtitle.json',segments)
                    documents.append({'id':f'{bvid}:subtitle:{cid}','side':entry.get('subtitle_side','supply'),
                        'source':'字幕','purpose':entry.get('purpose','固定内容（科普/体验/推广待核）'),
                        'date':pubdate,'quarter':quarter(pubdate),'products':products,'bvid':bvid,
                        'coverage':ratio,'text':'。'.join(s['content'] for s in segments)})
                statuses.append(status)
            comments=state.fetch({'kind':'all_comments','bvid':bvid},lambda:fetch_all_comments(client,meta['aid'],bvid,title=meta['title'],max_sub_pages=max_sub_pages))
            for r in comments:
                dt=datetime.fromtimestamp(r['时间'],ZoneInfo('Asia/Shanghai')).date().isoformat()
                documents.append({'id':f'{bvid}:comment:{r["评论ID"]}','side':'demand','source':'评论',
                    'date':dt,'quarter':quarter(dt),'products':products,'bvid':bvid,'text':r['正文']})
            write_csv(out/'documents.csv',documents)
            atomic_json(out/'coverage.json',statuses)
            print('已保存语料',bvid,len(documents),flush=True)
    finally:state.close()
