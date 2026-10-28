import asyncio
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock
sys.path.insert(0, str(Path(__file__).parents[1] / 'ops'))
from spec_eval import SpecEvaluations

class EvaluationsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'repo'; self.repo.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True)
        subprocess.run(['git', '-C', str(self.repo), 'remote', 'add', 'origin', 'https://github.com/nekoserver/dynamicneko.git'], check=True)
        (self.repo / 'SPEC.feature.md').write_text('# Feature\nMust work')
        self.service = SpecEvaluations({'nekoserver/dynamicneko': str(self.repo)}, self.root / 'state')
        self.send = AsyncMock()
    def tearDown(self): self.tmp.cleanup()
    async def test_single_submission_and_only_verified_artifact_counts_as_created(self):
        data = await self.service.inspect('nekoserver/dynamicneko', 'SPEC.feature.md')
        self.assertIsNone(data['eval'])
        first = await self.service.create('nekoserver/dynamicneko', 'SPEC.feature.md', self.send)
        again = await self.service.create('nekoserver/dynamicneko', 'SPEC.feature.md', self.send)
        self.assertEqual(first['run']['id'], again['run']['id'])
        self.send.assert_awaited_once()
        self.assertIsNone(again['eval'])
        run = first['run']
        output = self.repo / 'EVAL.feature.md'
        output.write_text('incomplete evaluation')
        self.assertIsNone((await self.service.inspect('nekoserver/dynamicneko', 'SPEC.feature.md'))['eval'])
        output.write_text(self.service.header(run) + '\n## 評価\n実装を確認。根拠: src/a.ts:1\n')
        done = await self.service.inspect('nekoserver/dynamicneko', 'SPEC.feature.md')
        self.assertEqual(done['run']['status'], 'completed')
        self.assertIsNotNone(done['eval']['createdAt'])
        self.assertEqual(done['eval']['dateSource'], 'filesystem_saved_at')
        self.assertEqual(done['eval']['path'], 'EVAL.feature.md')
        restored = SpecEvaluations({'nekoserver/dynamicneko': str(self.repo)}, self.root / 'state')
        self.assertEqual((await restored.inspect('nekoserver/dynamicneko', 'SPEC.feature.md'))['run']['status'], 'completed')
    async def test_rejects_traversal_symlinks_wrong_remote_and_unknown_repo(self):
        for repo, path in [('other/repo','SPEC.feature.md'), ('nekoserver/dynamicneko','../SPEC.feature.md'), ('nekoserver/dynamicneko','README.md')]:
            with self.assertRaises(ValueError): await self.service.inspect(repo,path)
        (self.repo / 'SPEC.link.md').symlink_to(self.root / 'outside')
        with self.assertRaises(ValueError): await self.service.inspect('nekoserver/dynamicneko','SPEC.link.md')
        subprocess.run(['git','-C',str(self.repo),'remote','set-url','origin','https://github.com/other/repo.git'],check=True)
        with self.assertRaises(ValueError): await self.service.create('nekoserver/dynamicneko','SPEC.feature.md',self.send)
        self.send.assert_not_awaited()
    async def test_existing_eval_is_not_overwritten_and_unknown_date_stays_unknown(self):
        (self.repo / 'EVAL.feature.md').write_text('# Existing evaluation')
        data = await self.service.create('nekoserver/dynamicneko','SPEC.feature.md',self.send)
        self.assertEqual(data['eval']['path'],'EVAL.feature.md')
        self.assertIsNone(data['eval']['createdAt'])
        self.send.assert_not_awaited()
    async def test_ambiguous_send_failure_is_retained_without_resubmission(self):
        self.send.side_effect = TimeoutError()
        with self.assertRaises(TimeoutError): await self.service.create('nekoserver/dynamicneko','SPEC.feature.md',self.send)
        self.send.side_effect = None
        result = await self.service.create('nekoserver/dynamicneko','SPEC.feature.md',self.send)
        self.assertEqual(result['run']['status'],'unknown')
        self.send.assert_awaited_once()
    async def test_changed_spec_never_silently_completes_old_evaluation(self):
        first = await self.service.create('nekoserver/dynamicneko','SPEC.feature.md',self.send)
        (self.repo / 'SPEC.feature.md').write_text('changed')
        run=first['run']; (self.repo / 'EVAL.feature.md').write_text(self.service.header(run)+'\n## Result\nA complete evaluation with evidence\n')
        result=await self.service.inspect('nekoserver/dynamicneko','SPEC.feature.md')
        self.assertTrue(result['eval']['specChanged'])

    async def test_completed_file_tampering_and_removal_fail_closed(self):
        result=await self.service.create('nekoserver/dynamicneko','SPEC.feature.md',self.send)
        output=self.repo/'EVAL.feature.md'
        text=self.service.header(result['run'])+'\n## Result\nA complete evaluation with evidence\n'
        output.write_text(text)
        await self.service.inspect('nekoserver/dynamicneko','SPEC.feature.md')
        for corruption in [text+'tampered', '# Metadata removed']:
            output.write_text(corruption)
            with self.assertRaises(ValueError): await self.service.inspect('nekoserver/dynamicneko','SPEC.feature.md')
        output.unlink()
        with self.assertRaises(ValueError): await self.service.inspect('nekoserver/dynamicneko','SPEC.feature.md')


    async def test_legacy_eval_suffix_requires_explicit_spec_reference(self):
        legacy=self.repo/'EVAL.feature.review.md'
        legacy.write_text('# Unrelated document')
        self.assertIsNone((await self.service.inspect('nekoserver/dynamicneko','SPEC.feature.md'))['eval'])
        legacy.write_text('`SPEC.feature.md`の実装を評価する。')
        result=await self.service.create('nekoserver/dynamicneko','SPEC.feature.md',self.send)
        self.assertEqual(result['eval']['path'],'EVAL.feature.review.md')
        self.send.assert_not_awaited()

if __name__ == '__main__': unittest.main()
