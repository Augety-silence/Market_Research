"""入口集成测试：标准库环境可运行旧命令、季度帮助与断点状态。"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from bili_research.cli import build_parser

ROOT = Path(__file__).resolve().parents[1]


class QuarterCLITest(unittest.TestCase):
    def test_quarter_subcommand_and_existing_arguments(self):
        parser = build_parser()
        args = parser.parse_args(['quarter', '--config', 'mine.json', 'collect', '--max-pages', '2', '--sync-feishu'])
        self.assertEqual((args.command, args.quarter_command, args.config, args.max_pages), ('quarter', 'collect', 'mine.json', 2))
        self.assertTrue(args.sync_feishu)
        old = parser.parse_args(['subtitle', 'BV1z44n6bEpU', '--cookie-file', 'cookie.txt'])
        self.assertEqual(old.cookie_file, 'cookie.txt')
        self.assertEqual(old.func.__name__, 'cmd_subtitle')

    def test_help_without_site_packages(self):
        for argv in (['--help'], ['quarter', '--help'], ['comments', '--help']):
            proc = subprocess.run([sys.executable, '-S', '-m', 'bili_research', *argv], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_status_without_optional_dependencies(self):
        with tempfile.TemporaryDirectory() as temp:
            cp = Path(temp)/'config.json'
            cp.write_text(json.dumps({'keywords': ['奥利司他'], 'start_date': '2026-04-01', 'end_date': '2026-06-30'}))
            proc = subprocess.run([sys.executable, '-S', '-m', 'bili_research', 'quarter', '--config', str(cp), 'status'], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn('2026Q2', proc.stdout)
            self.assertTrue((Path(temp)/'output/collection.sqlite3').exists())
            self.assertTrue((Path(temp)/'output/视频明细.csv').exists())

    def test_export_failure_has_nonzero_status(self):
        with tempfile.TemporaryDirectory() as temp:
            cp = Path(temp)/'config.json'
            cp.write_text(json.dumps({'keywords': ['奥利司他'], 'start_date': '2026-04-01', 'end_date': '2026-06-30'}))
            proc = subprocess.run([sys.executable, '-S', '-m', 'bili_research', 'quarter', '--config', str(cp), 'export'], cwd=ROOT, capture_output=True, text=True)
            self.assertNotEqual(proc.returncode, 0)
            self.assertTrue((Path(temp)/'output/collection.sqlite3').exists())
