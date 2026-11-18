"""独立 Playwright 浏览器；使用专用用户目录保存手动登录状态。"""
import time
from urllib.parse import parse_qs, urlparse
from ..collectors.quarter_search import search_url, validate_page, VerificationRequired

EXTRACT = r'''(() => {
 const s = window.__pinia?.searchTypeResponse?.searchTypeResponse;
 const cards = Array.from(document.querySelectorAll('.bili-video-card'));
 const text = document.body.innerText;
 return {ok: !!s, url: location.href, page: s?.page, total: s?.numResults,
 blocked: /验证后继续|安全验证|访问受限|请完成验证|人机验证/.test(text),
 uiPage: Number(document.querySelector('.vui_pagenation--btn-num.vui_button--active')?.innerText),
 nextPresent: !!document.querySelector('.vui_pagenation--btn-side:last-child'),
 nextDisabled: !!document.querySelector('.vui_pagenation--btn-side:last-child.vui_button--disabled'),
 domFirst: cards[0]?.querySelector('a[href*="/video/"]')?.href,
 videos: (Array.isArray(s?.result) ? s.result : []).filter(v => v.type === 'video').map(v =>
 ({bvid:v.bvid, title:v.title, play:v.play, pubdate:v.pubdate}))};
})()'''


class Browser:
    def __init__(self, profile, config):
        from playwright.sync_api import sync_playwright
        self.driver = sync_playwright().start()
        try:
            self.context = self.driver.chromium.launch_persistent_context(str(profile),
                headless=bool(config.get('headless', False)), channel=config.get('channel') or None, viewport={'width':1440,'height':1000})
            self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
            self.page.set_default_timeout(config.get('timeout_seconds', 40) * 1000)
            self.delay = max(float(config.get('page_delay_seconds', 2)), 1)
            self.timeout = config.get('timeout_seconds', 40)
        except BaseException:
            self.driver.stop()
            raise

    def close(self):
        self.context.close()
        self.driver.stop()

    def login(self):
        self.page.goto('https://www.bilibili.com/', wait_until='domcontentloaded')
        input('请在独立浏览器中完成B站登录或人工验证；完成后回到终端按回车保存并退出：')

    def read(self, job, page):
        deadline = time.monotonic() + self.timeout
        last = '页面尚未加载'
        while time.monotonic() < deadline:
            result = self.page.evaluate(EXTRACT)
            query = parse_qs(urlparse(result.get('url', '')).query)
            if query.get('keyword') != [job['keyword']] or query.get('order') != ['click']:
                raise RuntimeError('当前页面关键词或排序发生变化，请停止手动操作采集窗口')
            try:
                return validate_page(job, result, page)
            except VerificationRequired:
                raise
            except ValueError as exc:
                last = str(exc)
                self.page.wait_for_timeout(500)
        raise RuntimeError(last + '；未推进断点')

    def open(self, job, target):
        self.page.goto(search_url(job), wait_until='domcontentloaded')
        self.check_block()
        # 切换排序触发一次真实的日期筛选刷新。
        self.page.locator('.conditions-order button.vui_button--tab').nth(0).click()
        self.page.locator('.conditions-order button.vui_button--tab').nth(1).click()
        result = self.read(job, 1)
        for _ in range(200):
            if result['page'] == target:
                return result
            numbers = self.page.locator('.vui_pagenation--btn-num').all_text_contents()
            choices = [int(n) for n in numbers if n.strip().isdigit() and int(n) != result['page']]
            if not choices:
                raise RuntimeError('续采页码已不存在；搜索集合可能变化，保留断点等待核查')
            chosen = min(choices, key=lambda n: abs(n-target))
            if abs(chosen-target) >= abs(result['page']-target):
                raise RuntimeError('不能跳转到续采页码；没有修改断点')
            time.sleep(self.delay)
            self.check_block()
            self.page.evaluate('(n)=>{const b=Array.from(document.querySelectorAll(".vui_pagenation--btn-num"))'
                '.find(e=>Number(e.innerText)===n);if(!b)throw Error("页码按钮缺失");b.click();}', chosen)
            result = self.read(job, chosen)
        raise RuntimeError('超过分页保护上限')

    def check_block(self):
        if self.page.evaluate(EXTRACT).get('blocked'):
            raise VerificationRequired('B站要求人工验证，已停止自动采集；请运行 login 处理。')

    def next(self, job, result):
        time.sleep(self.delay)
        self.check_block()
        button = self.page.locator('.vui_pagenation--btn-side').last
        if not result['next_page'] or not button.count() or 'vui_button--disabled' in (button.get_attribute('class') or ''):
            raise RuntimeError('下一页状态变化，未推进断点')
        button.click()
        return self.read(job, result['next_page'])
