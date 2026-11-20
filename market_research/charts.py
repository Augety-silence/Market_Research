"""白底研究图：三产品各自纵轴，组合分数统一纵轴。平滑仅作用于画线。"""
from pathlib import Path
import math
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from .io import PRODUCTS,DIMENSIONS,atomic_json

COLORS=['#2673B8','#D1555A','#569B83']

def setup(font=None):
    if font:
        font_manager.fontManager.addfont(font);name=font_manager.FontProperties(fname=font).get_name()
    else:
        available={f.name for f in font_manager.fontManager.ttflist}
        name=next((n for n in ['Noto Sans CJK SC','Source Han Sans CN','PingFang SC','Microsoft YaHei','WenQuanYi Zen Hei'] if n in available),'DejaVu Sans')
    plt.rcParams.update({'font.family':name,'axes.unicode_minus':False,'figure.facecolor':'white',
                        'axes.facecolor':'white','axes.spines.top':False,'axes.spines.right':False,'font.size':10})
    return font or font_manager.findfont(font_manager.FontProperties(family=[name]))

def line(ax,labels,values,*,color,label=None,smooth=False):
    x=np.arange(len(labels));y=np.array([np.nan if v is None else v for v in values],dtype=float)
    if smooth and len(labels)>2 and np.isfinite(y).all():
        from scipy.interpolate import PchipInterpolator
        xx=np.linspace(0,len(labels)-1,250);ax.plot(xx,PchipInterpolator(x,y)(xx),color=color,label=label)
    else:ax.plot(x,y,color=color,label=label)
    ax.plot(x,y,'o',color=color,markersize=3)
    step=max(1,math.ceil(len(labels)/7));ax.set_xticks(x[::step],labels[::step],rotation=30,ha='right')
    ax.grid(axis='y',alpha=.18);ax.ticklabel_format(axis='y',style='plain',useOffset=False)

def finish(fig,out,name):
    fig.tight_layout();fig.savefig(out/(name+'.png'),dpi=200,bbox_inches='tight');fig.savefig(out/(name+'.pdf'),bbox_inches='tight');plt.close(fig)

def matrix(out,name,rows,columns,data,time_key,metrics,units,smooth):
    fig,axes=plt.subplots(len(metrics),len(columns),figsize=(15,9),squeeze=False)
    periods=sorted({r[time_key] for r in data})
    for i,(metric,unit) in enumerate(zip(metrics,units)):
        for j,col in enumerate(columns):
            ax=axes[i,j];lookup={r[time_key]:r.get(metric) for r in data if r[rows]==col}
            line(ax,periods,[lookup.get(t) for t in periods],color=COLORS[j],smooth=smooth)
            if i==0:ax.set_title(col,loc='left',color=COLORS[j])
            ax.set_ylabel(unit)
    finish(fig,out,name)

def create(analysis,outdir,*,font=None,smooth=True):
    font_path=setup(font);out=Path(outdir);out.mkdir(parents=True,exist_ok=True)
    manifest=[]
    if analysis.get('videos'):
        matrix(out,'bilibili_3x3','product',PRODUCTS,analysis['videos'],'quarter',
               ['bv','views','without_top1'],['视频数（BV）','累计播放量','去除Top1后累计播放量'],smooth)
        manifest.append('bilibili_3x3')
    if analysis.get('apps'):
        groups=list(dict.fromkeys(r['group'] for r in analysis['apps']['monthly']))
        if len(groups)!=3: raise ValueError('App3×3图需恰好三组，配置可调整分类')
        matrix(out,'app_3x3','group',groups,analysis['apps']['monthly'],'month',
               ['dau','downloads','revenue_usd'],['平均设备日活','下载量（次）','商店收入（USD）'],smooth)
        manifest.append('app_3x3')
    model=analysis.get('model')
    if model:
        fig,ax=plt.subplots(figsize=(12,5));periods=sorted({r['quarter'] for r in model['scores']})
        for p,c in zip(PRODUCTS,COLORS):
            lookup={r['quarter']:r['score'] for r in model['scores'] if r['product']==p}
            line(ax,periods,[lookup.get(q) for q in periods],color=c,label=p,smooth=smooth)
        ax.set_ylabel('五维加权匹配分');ax.legend(frameon=False);finish(fig,out,'matching_scores');manifest.append('matching_scores')
        fig,axes=plt.subplots(1,3,figsize=(15,5),subplot_kw={'projection':'polar'})
        theta=np.linspace(0,2*np.pi,5,endpoint=False);theta=np.r_[theta,theta[0]]
        for ax,p,c in zip(axes,PRODUCTS,COLORS):
            lookup={r['dimension']:r['feature'] for r in model['features'] if r['product']==p};values=[lookup[d] for d in DIMENSIONS];values+=[values[0]]
            ax.plot(theta,values,color=c);ax.fill(theta,values,color=c,alpha=.10);ax.set_xticks(theta[:-1],[d.replace('与','\n与') for d in DIMENSIONS],fontsize=8)
            ax.set_ylim(0,max(50,max(r['feature'] for r in model['features'])));ax.set_title(p,color=c,pad=28)
        finish(fig,out,'fixed_radar');manifest.append('fixed_radar')
        fig,ax=plt.subplots(figsize=(12,5));periods=sorted({r['quarter'] for r in model['weights']})
        for dim,c in zip(DIMENSIONS,['#2673B8','#D1555A','#569B83','#B6924A','#8763A0']):
            lookup={r['quarter']:100*r['weight'] for r in model['weights'] if r['dimension']==dim}
            line(ax,periods,[lookup.get(q) for q in periods],color=c,label=dim,smooth=smooth)
        ax.set_ylabel('需求侧五维词次占比（%）');ax.legend(frameon=False,ncol=3);finish(fig,out,'demand_weights');manifest.append('demand_weights')
        try:
            from wordcloud import WordCloud
            path=font_path
            freq={}
            for r in model['word_frequency']:freq[r['word']]=freq.get(r['word'],0)+r['count']
            if freq:
                cloud=WordCloud(font_path=path,width=1500,height=700,background_color='white',random_state=1843).generate_from_frequencies(freq)
                cloud.to_file(str(out/'wordcloud.png'));manifest.append('wordcloud')
        except ImportError:pass
    if analysis.get('baidu') and analysis.get('videos'):
        fig,axes=plt.subplots(1,3,figsize=(15,5))
        periods=sorted({r['quarter'] for r in analysis['videos']})
        for ax,p in zip(axes,PRODUCTS):
            v={r['quarter']:r['views'] for r in analysis['videos'] if r['product']==p};b={r['quarter']:r['index_mean'] for r in analysis['baidu'] if r['product']==p}
            line(ax,periods,[v.get(q) for q in periods],color=COLORS[0],label='视频累计播放',smooth=smooth);ax.set_ylabel('累计播放量',color=COLORS[0]);ax.set_title(p)
            right=ax.twinx();line(right,periods,[b.get(q) for q in periods],color=COLORS[1],label='百度指数',smooth=smooth);right.set_ylabel('百度指数日均',color=COLORS[1]);right.grid(False)
        finish(fig,out,'exposure_baidu');manifest.append('exposure_baidu')
    atomic_json(out/'manifest.json',{'charts':manifest,'smooth':'PCHIP仅画线，不改变点值' if smooth else '直线连接真实点','theme':'white'})
    return manifest
