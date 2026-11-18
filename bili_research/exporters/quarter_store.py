"""SQLite事务断点；页面结果和下一页在同一事务内提交。"""
import json
import sqlite3
from pathlib import Path
from ..collectors.quarter_search import fingerprint, jobs_for, stamp, video_rows, search_url


class Store:
    def __init__(self, path, config):
        self.config = config
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        PRAGMA journal_mode=WAL;
        PRAGMA synchronous=FULL;
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS jobs(keyword TEXT,quarter TEXT,start TEXT,end TEXT,
            last_page INTEGER DEFAULT 0,next_page INTEGER DEFAULT 1,total INTEGER,
            status TEXT DEFAULT '待采集',updated TEXT,note TEXT DEFAULT '',PRIMARY KEY(keyword,quarter));
        CREATE TABLE IF NOT EXISTS videos(id INTEGER PRIMARY KEY,keyword TEXT,quarter TEXT,bvid TEXT,
            row_json TEXT NOT NULL,remote_row INTEGER,remote_ok INTEGER DEFAULT 0,
            UNIQUE(keyword,quarter,bvid));
        ''')
        expected = fingerprint(config)
        previous = self.meta('fingerprint')
        if previous and previous != expected:
            self.db.close()
            raise RuntimeError('本断点对应不同关键词或日期范围；请修改 output_dir 使用新的采集目录')
        with self.db:
            self.set_meta('fingerprint', expected)
            for j in jobs_for(config):
                self.db.execute('INSERT OR IGNORE INTO jobs(keyword,quarter,start,end) VALUES(?,?,?,?)',
                                (j['keyword'],j['quarter'],j['start'],j['end']))

    def meta(self, key):
        r = self.db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        return json.loads(r[0]) if r else None

    def set_meta(self, key, value):
        self.db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)', (key,json.dumps(value,ensure_ascii=False)))

    def jobs(self):
        rows = [dict(r) for r in self.db.execute('SELECT * FROM jobs')]
        return sorted(rows, key=lambda r: (r['quarter'], self.config['keywords'].index(r['keyword'])))

    def rows(self):
        return [json.loads(r[0]) for r in self.db.execute('SELECT row_json FROM videos ORDER BY id')]

    def count(self, keyword, quarter):
        return self.db.execute('SELECT COUNT(*) FROM videos WHERE keyword=? AND quarter=?', (keyword,quarter)).fetchone()[0]

    def save(self, job, result):
        if result['page'] != job['next_page']:
            raise RuntimeError('页面不是断点要求的下一页')
        if job['total'] is not None and job['total'] != result['total']:
            raise RuntimeError('搜索总数发生变化；不拼接两个不同的搜索集合，保留已保存断点')
        rows = video_rows(job,result)
        with self.db:
            for row in rows:
                self.db.execute('INSERT OR IGNORE INTO videos(keyword,quarter,bvid,row_json) VALUES(?,?,?,?)',
                                (row[0],row[1],row[2],json.dumps(row,ensure_ascii=False)))
            count = self.count(job['keyword'],job['quarter'])
            if count > result['total']:
                raise RuntimeError('去重数量大于搜索总数，事务已回滚')
            status = '采集中' if result['next_page'] else ('已完成' if count == result['total'] else '数量待核验')
            self.db.execute('UPDATE jobs SET last_page=?,next_page=?,total=?,status=?,updated=?,note=? '
                'WHERE keyword=? AND quarter=?', (result['page'],result['next_page'],result['total'],status,stamp(),
                f'搜索总数{result["total"]}，去重保存{count}；日期逐条核验',job['keyword'],job['quarter']))
        return next(j for j in self.jobs() if j['keyword']==job['keyword'] and j['quarter']==job['quarter'])

    def seed(self, snapshot):
        if self.rows() or any(j['last_page'] for j in self.jobs()):
            raise RuntimeError('导入快照只允许空数据库，防止覆盖本地采集结果')
        if snapshot['fingerprint'] != self.meta('fingerprint'):
            raise RuntimeError('快照与当前关键词、日期范围不一致')
        with self.db:
            for row in snapshot['videos']:
                self.db.execute('INSERT INTO videos(keyword,quarter,bvid,row_json) VALUES(?,?,?,?)',
                                (row[0],row[1],row[2],json.dumps(row,ensure_ascii=False)))
            for j in snapshot['jobs']:
                count = self.count(j['keyword'], j['quarter'])
                if count != j['total'] or j['status'] != '已完成':
                    raise RuntimeError('快照完整性不通过')
                self.db.execute('UPDATE jobs SET last_page=?,next_page=0,total=?,status=?,updated=?,note=? '
                    'WHERE keyword=? AND quarter=?', (j['last_page'],j['total'],j['status'],j['updated'],
                    '已导入完整采集快照',j['keyword'],j['quarter']))
        return len(self.rows())

    def progress(self):
        return [[j['keyword'],j['quarter'],j['start'],j['end'],j['status'],j['last_page'],j['next_page'],
                 self.count(j['keyword'],j['quarter']),search_url(j,j['next_page'] or max(j['last_page'],1)),
                 j['updated'] or '',j['note']] for j in self.jobs()]

    def close(self):
        self.db.close()
