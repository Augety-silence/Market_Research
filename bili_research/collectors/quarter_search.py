"""季度划分、日期校验和记录转换。"""
import calendar
import hashlib
import html
import json
import re
from datetime import date, datetime, time
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Asia/Shanghai')
HEADERS = ['关键词', '季度', 'BV号', '视频标题', '发布日期', '播放量', '视频链接', '来源页', '采集时间']
PROGRESS_HEADERS = ['关键词', '季度', '开始日期', '截止日期', '状态', '已保存页', '下一页', '正式保存视频数', '续采链接', '更新时间', '备注']


def stamp():
    return datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')


def fingerprint(config):
    fields = {k: config[k] for k in ('keywords', 'start_date', 'end_date')}
    return hashlib.sha256(json.dumps(fields, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def jobs_for(config):
    keywords = config.get('keywords', [])
    if not keywords or any(not isinstance(k, str) or not k.strip() for k in keywords) or len(set(keywords)) != len(keywords):
        raise ValueError('关键词必须非空且不能重复')
    start, end = date.fromisoformat(config['start_date']), date.fromisoformat(config['end_date'])
    if end < start:
        raise ValueError('结束日期早于开始日期')
    result = []
    cursor = date(start.year, ((start.month - 1) // 3) * 3 + 1, 1)
    while cursor <= end:
        quarter = (cursor.month - 1) // 3 + 1
        month = cursor.month + 2
        last = date(cursor.year, month, calendar.monthrange(cursor.year, month)[1])
        for keyword in config['keywords']:
            result.append(dict(keyword=keyword, quarter=f'{cursor.year}Q{quarter}',
                               start=max(start, cursor).isoformat(), end=min(end, last).isoformat()))
        cursor = date(cursor.year + 1, 1, 1) if month == 12 else date(cursor.year, month + 1, 1)
    return result


def bounds(job):
    return (int(datetime.combine(date.fromisoformat(job['start']), time.min, TZ).timestamp()),
            int(datetime.combine(date.fromisoformat(job['end']), time.max, TZ).timestamp()))


def search_url(job, page=1):
    begin, end = bounds(job)
    return 'https://search.bilibili.com/all?' + urlencode(dict(keyword=job['keyword'], order='click',
        pubtime_begin_s=begin, pubtime_end_s=end, page=page, o=(page-1)*36))


class VerificationRequired(RuntimeError):
    pass


def validate_page(job, result, page):
    if result.get('blocked'):
        raise VerificationRequired('B站要求人工验证，已停止自动采集。请使用 login 命令处理后重跑 collect。')
    if not result.get('ok') or result.get('page') != page:
        raise ValueError('搜索数据或页码尚未加载')
    total = result.get('total')
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise ValueError('无法读取准确搜索总数')
    videos = result.get('videos', [])
    if total and not videos:
        raise ValueError('有搜索结果但本页视频未加载')
    if videos and (not result.get('domFirst') or videos[0]['bvid'] not in result['domFirst']):
        raise ValueError('页面显示与搜索数据不同步')
    if total > 36 and result.get('uiPage') != page:
        raise ValueError('分页界面与数据页码不同步')
    begin, end = bounds(job)
    for v in videos:
        if not re.fullmatch(r'BV[0-9A-Za-z]{10}', v.get('bvid', '')):
            raise ValueError('缺少有效BV号')
        if not isinstance(v.get('pubdate'), int) or not begin <= v['pubdate'] <= end:
            raise ValueError('日期筛选未生效，拒绝保存跨季度视频')
        if isinstance(v.get('play'), bool) or not isinstance(v.get('play'), int) or v['play'] < 0:
            raise ValueError('缺少准确播放量，拒绝使用“万”单位的近似显示值')
    if len({v['bvid'] for v in videos}) != len(videos):
        raise ValueError('单页返回重复BV')
    if any(a['play'] < b['play'] for a, b in zip(videos, videos[1:])):
        raise ValueError('结果未按最多播放排序')
    result = dict(result)
    result['next_page'] = page + 1 if result.get('nextPresent') and not result.get('nextDisabled') else 0
    return result


def video_rows(job, result):
    now = stamp()
    return [[job['keyword'], job['quarter'], v['bvid'], html.unescape(re.sub('<[^>]*>', '', v['title'])),
             datetime.fromtimestamp(v['pubdate'], TZ).date().isoformat(), v['play'],
             'https://www.bilibili.com/video/' + v['bvid'], result['page'], now] for v in result['videos']]
