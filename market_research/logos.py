"""通过Apple公开lookup接口获取App图标并保留来源。"""
from pathlib import Path
import requests
from .http import request_json,HTTPError
from .io import atomic_json

def collect(config,outdir):
    out=Path(outdir);out.mkdir(parents=True,exist_ok=True);manifest=[]
    for app in config['apps']:
        aid=str(app['dau_id']);obj=request_json('GET','https://itunes.apple.com/lookup',params={'id':aid,'country':config['country'].lower()})
        rows=obj.get('results',[])
        if not rows: raise ValueError('Apple lookup无结果：'+app['name'])
        row=next((r for r in rows if str(r.get('trackId'))==aid),None)
        if row is None: raise ValueError('Apple lookup实体不匹配')
        url=row.get('artworkUrl512') or row.get('artworkUrl100')
        if not url: raise ValueError('App没有图标URL')
        try:
            r=requests.get(url,timeout=30)
            if r.status_code!=200: raise HTTPError('图标下载失败')
        except requests.RequestException:raise HTTPError('图标下载网络错误') from None
        name=aid+'.png';(out/name).write_bytes(r.content)
        manifest.append({'app':app['name'],'app_id':aid,'apple_name':row.get('trackName'),'source_url':url,'file':name})
        atomic_json(out/'manifest.json',manifest)
    return manifest
