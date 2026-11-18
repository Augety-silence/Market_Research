"""拦截页面导航，以本地测试页验证浏览器真实提取和翻页，不访问线上网站。"""
import json
import tempfile
import unittest
from pathlib import Path
import importlib.util
if importlib.util.find_spec("playwright") is None:
    raise unittest.SkipTest("季度浏览器测试需安装 .[quarter]")
from playwright.sync_api import sync_playwright
with sync_playwright() as driver:
    if not Path(driver.chromium.executable_path).exists():
        raise unittest.SkipTest("请先运行 python -m playwright install chromium")
from bili_research.core.quarter_browser import Browser
from bili_research.collectors.quarter_search import bounds, VerificationRequired


class BrowserTests(unittest.TestCase):
    def test_real_browser_dates_pagination_and_verification(self):
        job={'keyword':'奥利司他','quarter':'2026Q2','start':'2026-04-01','end':'2026-06-30'}
        lo,_=bounds(job)
        videos=[{'type':'video','bvid':bv,'title':'测试视频','play':play,'pubdate':lo} for bv,play in
                [('BV1UQEv6FEy7',300),('BV1jzDaBCEWo',200),('BV1Anj36jEpW',100)]]
        document='''<html><body>
        <div class="conditions-order"><button class="vui_button--tab">综合排序</button><button class="vui_button--tab">最多播放</button></div>
        <div class="bili-video-card"><a id="first" href="https://www.bilibili.com/video/BV1UQEv6FEy7">测试</a></div>
        <div class="pagination">
        <button class="vui_pagenation--btn-num vui_button--active" onclick="changePage(1)">1</button>
        <button class="vui_pagenation--btn-num" onclick="changePage(2)">2</button>
        <button class="vui_pagenation--btn-side" onclick="changePage(2)">下一页</button></div>
        <script>const videos=VIDEO_DATA;
        window.__pinia={searchTypeResponse:{searchTypeResponse:{page:1,numResults:3,result:videos.slice(0,2),next:0}}};
        function changePage(n){const s=window.__pinia.searchTypeResponse.searchTypeResponse;
          s.page=n;s.result=n===1?videos.slice(0,2):videos.slice(1);
          document.querySelector('#first').href='https://www.bilibili.com/video/'+s.result[0].bvid;
          document.querySelectorAll('.vui_pagenation--btn-num').forEach(e=>e.classList.toggle('vui_button--active',Number(e.innerText)===n));
          document.querySelector('.vui_pagenation--btn-side').classList.toggle('vui_button--disabled',n===2);
        }</script></body></html>'''.replace('VIDEO_DATA',json.dumps(videos,ensure_ascii=False))
        with tempfile.TemporaryDirectory() as temp:
            browser=Browser(Path(temp)/'profile',{'headless':True,'timeout_seconds':10,'page_delay_seconds':1})
            try:
                browser.context.route('**/*',lambda route:route.fulfill(status=200,content_type='text/html',body=document))
                first=browser.open(job,1);self.assertEqual(first['next_page'],2);self.assertEqual(first['videos'][0]['play'],300)
                second=browser.next(job,first);self.assertEqual(second['page'],2);self.assertEqual(second['next_page'],0)
                resumed=browser.open(job,2);self.assertEqual(resumed['page'],2)
                browser.page.evaluate("document.body.append('请完成验证')")
                with self.assertRaises(VerificationRequired):browser.check_block()
            finally:browser.close()


if __name__=='__main__':unittest.main()
