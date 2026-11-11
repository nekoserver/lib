"""CONTAINERS.md(各コンテナの仕組み・根拠・設定状況・共通項目の表)が、決めた形を保っているか。"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ContainersDocTest(unittest.TestCase):
    def setUp(self):
        self.text = (ROOT / 'CONTAINERS.md').read_text(encoding='utf-8')

    def test_has_the_four_sections_as_tables(self):
        for heading in ('## 1. 設定状況', '## 2. 特殊な仕組みと、それが必要になった根拠', '## 3. 主な版', '## 4. 共通項目'):
            self.assertIn(heading, self.text)
            section = self.text.split(heading, 1)[1].split('\n## ', 1)[0]
            self.assertRegex(section, r'(?m)^\|---', heading)

    def test_lists_every_repository_with_a_container_and_its_main_commit(self):
        for repo in ('cloudflare-workers-github-oauth-1', 'dynamicneko', 'redmine', 'musevm', 'musevm-kernel'):
            self.assertRegex(self.text, rf'(?m)^\| nekoserver/{re.escape(repo)}(\(本体\))? \| `[0-9a-f]{{7}}` \|$', repo)

    def test_rules_require_updating_it_with_container_changes(self):
        self.assertIn('CONTAINERS.md', (ROOT / 'CLAUDE.md').read_text(encoding='utf-8'))
