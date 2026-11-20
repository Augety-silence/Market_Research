"""统一HTTP错误处理，错误信息不包含带凭证的URL和响应正文。"""
import time
import requests

class HTTPError(RuntimeError): pass

def request_json(method, url, *, params=None, payload=None, headers=None, attempts=4, timeout=120):
    for attempt in range(attempts):
        try:
            r=requests.request(method,url,params=params,json=payload,headers=headers,timeout=timeout)
        except requests.RequestException:
            if attempt+1==attempts: raise HTTPError('网络请求失败，断点已保留') from None
            time.sleep(2**attempt); continue
        if (r.status_code==429 or r.status_code>=500) and attempt+1<attempts:
            time.sleep(min(30,2**(attempt+1))); continue
        if r.status_code>=400: raise HTTPError(f'HTTP {r.status_code}，请检查权限、配额和参数；断点已保留')
        try: return r.json()
        except ValueError: raise HTTPError('接口返回非JSON内容；断点已保留') from None
    raise HTTPError('请求重试失败')
