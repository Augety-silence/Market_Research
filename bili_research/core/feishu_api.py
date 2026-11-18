"""飞书公开 API 客户端：认证、请求、容量、单元格读写。"""
import os
import time
from urllib.parse import quote
import requests

class FeishuAPI:
    def __init__(self, config):
        self.config = config
        self.token = config['spreadsheet_token']
        self.root = config.get('api_base', 'https://open.feishu.cn/open-apis').rstrip('/')
        if self.root not in ('https://open.feishu.cn/open-apis','https://open.larksuite.com/open-apis'):
            raise ValueError('api_base 必须是飞书或Lark公开接口域名')
        self.session = requests.Session()
        self.cached_token = None
        self.expires = 0

    def access_token(self):
        existing = os.getenv('FEISHU_USER_ACCESS_TOKEN') or os.getenv('FEISHU_TENANT_ACCESS_TOKEN')
        if existing:
            return existing
        if self.cached_token and time.time() < self.expires:
            return self.cached_token
        app_id, secret = os.getenv('FEISHU_APP_ID'), os.getenv('FEISHU_APP_SECRET')
        if not app_id or not secret:
            raise RuntimeError('请在本机配置 FEISHU_APP_ID / FEISHU_APP_SECRET，或 FEISHU_USER_ACCESS_TOKEN')
        response = self.session.post(self.root+'/auth/v3/tenant_access_token/internal',
            json={'app_id':app_id,'app_secret':secret},timeout=30)
        if response.status_code != 200:
            raise RuntimeError(f'飞书认证请求失败，HTTP {response.status_code}')
        body = response.json()
        if body.get('code') != 0:
            raise RuntimeError(f'飞书认证失败，错误码{body.get("code")}；请检查应用凭证')
        self.cached_token = body['tenant_access_token']
        self.expires = time.time()+max(0,body['expire']-120)
        return self.cached_token

    def request(self, method, path, *, payload=None, params=None, retry=True):
        for attempt in range(4 if retry else 1):
            response = self.session.request(method,self.root+path,json=payload,params=params,
                headers={'Authorization':'Bearer '+self.access_token()},timeout=40)
            if retry and (response.status_code==429 or response.status_code>=500) and attempt<3:
                time.sleep(2**attempt)
                continue
            if response.status_code>=400:
                raise RuntimeError(f'飞书请求失败，HTTP {response.status_code}；本地断点已保留')
            body = response.json()
            if body.get('code') != 0:
                raise RuntimeError(f'飞书接口错误码{body.get("code")}；检查表格权限或凭证有效期')
            return body.get('data',{})
        raise RuntimeError('飞书请求重试失败')

    def sheets(self):
        return self.request('GET',f'/sheets/v3/spreadsheets/{self.token}/sheets/query')['sheets']

    def read(self, sheet, area, formulas=False):
        return self.request('GET',f'/sheets/v2/spreadsheets/{self.token}/values/{quote(sheet+"!"+area,safe="")}',
            params={'valueRenderOption':'Formula' if formulas else 'UnformattedValue',
                    'dateTimeRenderOption':'FormattedString'}).get('valueRange',{}).get('values',[])

    def write(self, ranges):
        return self.request('POST',f'/sheets/v2/spreadsheets/{self.token}/values_batch_update',
            payload={'valueRanges':[{'range':sid+'!'+area,'values':values} for sid,area,values in ranges]})

    def capacity(self, sid, wanted):
        while True:
            sheet = next(s for s in self.sheets() if s['sheet_id']==sid)
            available = sheet['grid_properties']['row_count']
            if available >= wanted:
                return
            # 扩行不是幂等请求；失败后停止，下次先重新读取实际行数。
            self.request('POST',f'/sheets/v2/spreadsheets/{self.token}/dimension_range',
                payload={'dimension':{'sheetId':sid,'majorDimension':'ROWS','length':min(5000,wanted-available)}},retry=False)

    def styles(self, sid, area, formatter):
        self.request('PUT',f'/sheets/v2/spreadsheets/{self.token}/styles',
            payload={'appendStyle':{'range':sid+'!'+area,'style':{'formatter':formatter}}})
