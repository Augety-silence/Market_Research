"""打包已提交源码，生成逐文件SHA256清单；排除历史研究数据。"""
import argparse
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path


def package(root,output):
    root=Path(root).resolve();output=Path(output).resolve()
    tracked=subprocess.check_output(['git','ls-files','-z'],cwd=root).decode().split('\0')
    excluded=('examples/quarter_snapshot/','examples/demo_output/')
    suffixes={'.py','.toml','.md','.json','.txt','.command','.yml','.yaml'}
    include=[]
    for name in tracked:
        if not name or name.startswith(excluded):continue
        path=Path(name)
        if path.suffix in suffixes or path.name in {'.gitignore','.env.example','quarter.env.example'}:
            include.append(name)
    version=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root).decode().strip()
    manifest={'commit':version,'files':{},'excludes':['.git','真实语料/平台数据','Cookie/令牌','运行目录','历史数据示例']}
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for name in sorted(include):
            payload=(root/name).read_bytes();manifest['files'][name]=hashlib.sha256(payload).hexdigest()
            item=zipfile.ZipInfo('Market_Research/'+name,date_time=(2026,1,1,0,0,0));item.compress_type=zipfile.ZIP_DEFLATED
            item.external_attr=0o644<<16;z.writestr(item,payload)
        z.writestr('Market_Research/SOURCE_MANIFEST.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    with zipfile.ZipFile(output) as z:
        if z.testzip() is not None:raise RuntimeError('ZIP完整性校验失败')
        for name,h in manifest['files'].items():
            if hashlib.sha256(z.read('Market_Research/'+name)).hexdigest()!=h:raise RuntimeError('源码摘要不一致')
    return len(include),version

if __name__=='__main__':
    p=argparse.ArgumentParser(description='打包纯源码与配置模板')
    p.add_argument('--root',default=str(Path(__file__).resolve().parents[1]));p.add_argument('--out',required=True)
    a=p.parse_args();count,version=package(a.root,a.out);print('源码文件数：',count,'提交：',version)
