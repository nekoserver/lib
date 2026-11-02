import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'ops'))
import chat_observer_claude as observer


ENTRIES = [
    {'type': 'ai-title', 'aiTitle': '作業中の会話'},
    {'type': 'user', 'uuid': 'u1', 'message': {'role': 'user', 'content': 'こんにちは'}},
    {'type': 'user', 'uuid': 'meta', 'isMeta': True, 'message': {'role': 'user', 'content': 'PRIVATE_META'}},
    {'type': 'assistant', 'uuid': 'a1', 'message': {'role': 'assistant', 'stop_reason': 'tool_use', 'content': [
        {'type': 'thinking', 'thinking': 'PRIVATE_REASONING'},
        {'type': 'text', 'text': '確認します'},
        {'type': 'tool_use', 'id': 't1', 'name': 'Bash', 'input': {'command': 'SECRET_COMMAND'}},
    ]}},
    {'type': 'user', 'uuid': 'r1', 'toolUseResult': {'stdout': 'PRIVATE_OUTPUT'}, 'message': {'role': 'user', 'content': [
        {'type': 'tool_result', 'tool_use_id': 't1', 'content': 'PRIVATE_OUTPUT'},
    ]}},
    {'type': 'assistant', 'uuid': 'side', 'isSidechain': True, 'message': {'role': 'assistant', 'content': [
        {'type': 'text', 'text': 'PRIVATE_SUBAGENT'},
    ]}},
    {'type': 'assistant', 'uuid': 'a2', 'message': {'role': 'assistant', 'stop_reason': 'end_turn', 'content': [
        {'type': 'text', 'text': '完了しました'},
    ]}},
    {'type': 'system', 'subtype': 'turn_duration'},
]


class ClaudeObserverTest(unittest.IsolatedAsyncioTestCase):
    def test_snapshot_excludes_reasoning_tool_output_and_meta(self):
        snapshot = observer.public_snapshot(ENTRIES)
        wire = json.dumps(snapshot)
        for private in ('PRIVATE_REASONING', 'SECRET_COMMAND', 'PRIVATE_OUTPUT', 'PRIVATE_META', 'PRIVATE_SUBAGENT'):
            self.assertNotIn(private, wire)
        self.assertEqual(snapshot['title'], '作業中の会話')
        self.assertEqual(snapshot['status'], 'idle')
        self.assertEqual([(m['role'], m['phase'], m['text']) for m in snapshot['messages']], [
            ('user', None, 'こんにちは'), ('assistant', 'commentary', '確認します'), ('assistant', None, '完了しました')])
        self.assertEqual(snapshot['activity'], [{'kind': 'commandExecution', 'status': 'completed'}])

    def test_unfinished_turn_is_active(self):
        self.assertEqual(observer.public_snapshot(ENTRIES[:4])['status'], 'active')
        self.assertEqual(observer.public_snapshot(ENTRIES[:4])['activity'][0]['status'], 'inProgress')

    def test_print_mode_turn_without_turn_duration_is_idle(self):
        # `claude -p` (used by send) records no turn_duration; the final answer ends the turn.
        entries = [entry for entry in ENTRIES if entry.get('type') != 'system']
        self.assertEqual(observer.public_snapshot(entries)['status'], 'idle')
        follow_up = {'type': 'user', 'uuid': 'u2', 'message': {'role': 'user', 'content': 'next'}}
        self.assertEqual(observer.public_snapshot(entries + [follow_up])['status'], 'active')

    async def test_trusted_target_change_refreshes_an_existing_stream(self):
        with tempfile.TemporaryDirectory() as directory:
            projects = Path(directory) / 'projects' / '-work'
            projects.mkdir(parents=True)
            for session in ('old-session', 'current-session'):
                (projects / f'{session}.jsonl').write_text(json.dumps(
                    {'type': 'user', 'uuid': session, 'message': {'role': 'user', 'content': session}}) + '\n')
            source = Path(directory) / 'source.json'
            source.write_text(json.dumps({'sessionId': 'old-session'})); source.chmod(0o600)
            with patch.object(observer, 'PROJECTS', Path(directory) / 'projects'), patch.object(observer, 'INTERVAL', 0):
                stream = observer.snapshots('fallback-session', source_file=source)
                first = await anext(stream)
                source.write_text(json.dumps({'sessionId': 'current-session'}))
                second = await anext(stream)
                await stream.aclose()
        self.assertEqual(first['messages'][0]['text'], 'old-session')
        self.assertEqual(second['messages'][0]['text'], 'current-session')

    async def test_send_passes_text_as_prompt_never_as_cli_option(self):
        calls = []
        class Finished:
            async def wait(self): return 0
        async def spawn(*args, **kwargs):
            calls.append(args)
            return Finished()
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / '-work'
            project.mkdir()
            (project / 'session-1.jsonl').write_text(json.dumps({'type': 'user', 'cwd': directory}) + '\n')
            with patch.object(observer, 'PROJECTS', Path(directory)), \
                 patch.object(observer.asyncio, 'create_subprocess_exec', spawn):
                await observer.send_to_console('session-1', '--dangerously-skip-permissions')
        args = calls[0]
        self.assertEqual(args[-2:], ('--', '--dangerously-skip-permissions'))
        self.assertEqual(args[1:args.index('--')], ('-p', '--resume', 'session-1'))

    def test_claude_binary_skips_missing_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / 'missing'
            stub = Path(directory) / 'not-executable'
            stub.write_text('')
            working = Path(directory) / 'claude'
            working.write_text('#!/bin/sh\n'); working.chmod(0o755)
            self.assertEqual(observer.claude_binary([str(missing), str(stub), str(working)]), str(working))
            self.assertEqual(observer.claude_binary([str(missing)]), 'claude')

    def test_source_configuration_must_be_private_and_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.json'
            source.write_text('{"sessionId":"current-session"}'); source.chmod(0o600)
            self.assertEqual(observer.configured_source('fallback', source), 'current-session')
            source.write_text('{"followWorkspace":"/root/lib"}')
            self.assertEqual(observer.configured_source('fallback', source), 'workspace:/root/lib')
            source.chmod(0o666)
            with self.assertRaises(ValueError): observer.configured_source('fallback', source)
            source.chmod(0o600); source.write_text('{}')
            with self.assertRaises(ValueError): observer.configured_source('fallback', source)


if __name__ == '__main__':
    unittest.main()
