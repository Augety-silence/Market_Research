"""每次成功请求立即事务提交；改变配置不能混用旧断点。"""
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from .io import digest

class Checkpoint:
    def __init__(self, path, signature):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db=sqlite3.connect(path, timeout=60)
        self.db.executescript('''
        PRAGMA journal_mode=WAL;
        PRAGMA synchronous=FULL;
        CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY,v TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS jobs(k TEXT PRIMARY KEY,params TEXT NOT NULL,result TEXT NOT NULL,at TEXT NOT NULL);
        ''')
        previous=self.db.execute("SELECT v FROM meta WHERE k='signature'").fetchone()
        expected=digest(signature)
        if previous and previous[0]!=expected:
            self.db.close(); raise ValueError('断点配置已变化，请使用新的输出目录或显式删除旧断点')
        with self.db: self.db.execute("INSERT OR IGNORE INTO meta VALUES ('signature',?)",(expected,))
    def get(self, key):
        row=self.db.execute('SELECT result FROM jobs WHERE k=?',(digest(key),)).fetchone()
        return json.loads(row[0]) if row else None
    def put(self, key, result):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO jobs VALUES (?,?,?,?)',
                (digest(key),json.dumps(key,ensure_ascii=False),json.dumps(result,ensure_ascii=False,allow_nan=False),datetime.now(timezone.utc).isoformat()))
    def fetch(self, key, callback):
        value=self.get(key)
        if value is None: value=callback(); self.put(key,value)
        return value
    def close(self): self.db.close()
