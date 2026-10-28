"""SPEC evaluations through the existing, fixed Codex conversation.

The observer owns receipts; Codex owns repository edits. Acceptance is never
completion: only the resulting file with matching provenance completes a run.
"""
import asyncio
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import uuid

DEFAULT_REPOSITORIES = {f'nekoserver/{name}': f'/root/{name}' for name in (
    'cloudflare-workers-github-oauth-1', 'dynamicneko', 'rust-worker-sqlx-d1', 'rails-root', 'railway')}


def git(repo, *args):
    result = subprocess.run(['git', '-C', str(repo), *args], capture_output=True,
                            text=True, timeout=5, env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0'})
    if result.returncode: return None
    return result.stdout.strip()


def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')


class SpecEvaluations:
    def __init__(self, repositories, state):
        self.repositories = repositories
        self.state = Path(state)

    def paths(self, repository, path):
        if not isinstance(repository, str) or repository not in self.repositories:
            raise ValueError('repository_unavailable')
        if not isinstance(path, str) or len(path) > 512:
            raise ValueError('invalid_spec_path')
        parts = PurePosixPath(path)
        if re.search(r'[\x00-\x1f\x7f]', path) or parts.is_absolute() or any(part in ('', '.', '..') for part in path.split('/')) or '\\' in path or not re.fullmatch(r'SPEC(?:\.[\w.-]+)?\.md', parts.name):
            raise ValueError('invalid_spec_path')
        root = Path(self.repositories[repository]).resolve(strict=True)
        origin = git(root, 'remote', 'get-url', 'origin')
        if origin not in (f'https://github.com/{repository}.git', f'https://github.com/{repository}', f'git@github.com:{repository}.git'):
            raise ValueError('repository_identity_mismatch')
        spec = root / path
        evaluation = spec.with_name('EVAL' + parts.name[4:])
        for file in (spec, evaluation):
            if file.is_symlink() or not file.resolve().is_relative_to(root):
                raise ValueError('unsafe_repository_path')
        if not spec.is_file() or spec.stat().st_size > 1_048_576:
            raise ValueError('spec_unavailable')
        return root, spec, evaluation

    def receipt_path(self, repository, path):
        key = hashlib.sha256((repository + '\n' + path).encode()).hexdigest()
        return self.state / (key + '.json')

    def save(self, repository, path, run):
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        receipt = self.receipt_path(repository, path)
        temporary = receipt.with_suffix('.' + str(uuid.uuid4()) + '.tmp')
        temporary.write_text(json.dumps(run, ensure_ascii=False)); temporary.chmod(0o600)
        temporary.replace(receipt)

    def read(self, repository, path):
        receipt = self.receipt_path(repository, path)
        if not receipt.exists(): return None
        value = json.loads(receipt.read_text())  # Corrupt state must fail closed.
        if not isinstance(value, dict) or value.get('repository') != repository or value.get('specPath') != path:
            raise ValueError('evaluation_receipt_corrupt')
        return value

    @staticmethod
    def header(run):
        metadata = {key: run[key] for key in ('id', 'repository', 'specPath', 'specSha256', 'sourceCommit')}
        metadata['requestedAt'] = run['createdAt']
        return '<!-- tree-view-spec-eval ' + json.dumps(metadata, ensure_ascii=False, sort_keys=True) + ' -->'

    def inspect_sync(self, repository, path):
        root, spec, evaluation = self.paths(repository, path)
        digest = hashlib.sha256(spec.read_bytes()).hexdigest()
        run = self.read(repository, path)
        artifact = None
        if run is None and not evaluation.exists():
            # Legacy EVALs may have a descriptive suffix. Require an explicit
            # reference to this SPEC, rather than equating dates or prefixes.
            name = spec.name
            for candidate in sorted(spec.parent.glob(evaluation.stem + '.*.md')):
                if candidate.is_symlink() or not candidate.resolve().is_relative_to(root):
                    raise ValueError('unsafe_repository_path')
                if candidate.stat().st_size > 2_097_152: continue
                text = candidate.read_text()
                if any(reference in text for reference in ('`' + name + '`', '](' + name + ')', '](./' + name + ')', '](' + name + '#')):
                    evaluation = candidate
                    break
        if evaluation.is_file():
            if evaluation.stat().st_size > 2_097_152: raise ValueError('evaluation_too_large')
            text = evaluation.read_text()
            verified = run and text.startswith(self.header(run) + '\n') and len(text[len(self.header(run)):].strip()) > 20
            if verified and run.get('artifactSha256') and hashlib.sha256(text.encode()).hexdigest() != run['artifactSha256']:
                raise ValueError('evaluation_artifact_changed')
            if run is None or verified:
                dates = git(root, 'log', '--follow', '--diff-filter=A', '--format=%aI', '--', str(evaluation.relative_to(root)))
                artifact = {'path': str(evaluation.relative_to(root)),
                            'createdAt': (run.get('artifactCreatedAt') or datetime.fromtimestamp(evaluation.stat().st_mtime, timezone.utc).isoformat(timespec='seconds')) if verified else dates.splitlines()[-1] if dates else None,
                            'dateSource': 'filesystem_saved_at' if verified else 'git_creation_commit' if dates else 'unknown',
                            'content': text, 'specChanged': bool(run and run['specSha256'] != digest)}
                if verified and run['status'] != 'completed':
                    run.update(status='completed', completedAt=now(), artifactCreatedAt=artifact['createdAt'], artifactSha256=hashlib.sha256(text.encode()).hexdigest())
                    self.save(repository, path, run)
        if run and run['status'] == 'completed' and artifact is None:
            raise ValueError('evaluation_artifact_missing_or_corrupt')
        return {'eval': artifact, 'run': run, 'available': True}

    async def inspect(self, repository, path):
        return await asyncio.to_thread(self.inspect_sync, repository, path)

    async def create(self, repository, path, send, thread_id=None):
        # The OS lock prevents competing observer processes from submitting twice.
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock = open(self.receipt_path(repository, path).with_suffix('.lock'), 'a')
        try:
            try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: raise ValueError('evaluation_submission_busy')
            result = await self.inspect(repository, path)
            if result['eval'] or result['run']: return result
            root, spec, output = await asyncio.to_thread(self.paths, repository, path)
            run = {'id': str(uuid.uuid4()), 'repository': repository, 'specPath': path,
                   'specSha256': hashlib.sha256(spec.read_bytes()).hexdigest(),
                   'sourceCommit': await asyncio.to_thread(git, root, 'rev-parse', 'HEAD'),
                   'createdAt': now(), 'status': 'submitting', 'threadId': thread_id}
            self.save(repository, path, run)
            prompt = '\n'.join([
                'tree-viewからのSPEC評価依頼です。この依頼はEVALファイルの作成を明示的に許可しています。',
                f'対象リポジトリ: {repository}', f'実際の作業ディレクトリ: {root}',
                f'SPEC: {path}', f'SPEC SHA256: {run["specSha256"]}',
                f'受付時HEAD: {run["sourceCommit"] or "未コミット"}',
                f'出力ファイル: {output.relative_to(root)}',
                '上記リポジトリの指示を読み、SPECと実コード・関連テストを調査して日本語のEVALを作成してください。',
                '要件ごとに充足・未充足・未確認を区別し、根拠のファイルパスと行番号、実行した検証、制約を記録してください。',
                '未実施のテストを成功と書かないでください。コード修正・デプロイ・pushはこの依頼の対象外です。',
                '開始時と保存直前にSPECのSHA256を照合し、変化していたらEVALを保存せず会話で報告してください。',
                '評価本文を最後まで完成してから、同一ディレクトリの一時ファイルを完成させ、既存出力先があれば失敗するos.link等で出力先へ原子的に公開してください（置換renameは禁止）。既存EVALは上書きしないでください。',
                '完成したEVALの先頭行は次の監査メタデータにしてください（以降に評価本文を記載）:', self.header(run),
                '実際のファイル保存まで行ってから、保存先と評価結果をこの会話へ報告してください。',
            ])
            try:
                await send(prompt)
            except BaseException:
                run.update(status='unknown')
                self.save(repository, path, run)
                raise
            run.update(status='pending')
            self.save(repository, path, run)
            return {'eval': None, 'run': run, 'available': True}
        finally: lock.close()


def configured_evaluations():
    repositories = json.loads(os.environ.get('LIB_SPEC_EVAL_REPOSITORIES', json.dumps(DEFAULT_REPOSITORIES)))
    if not isinstance(repositories, dict) or not all(isinstance(k, str) and isinstance(v, str) and Path(v).is_absolute() for k,v in repositories.items()):
        raise ValueError('invalid_evaluation_repository_configuration')
    return SpecEvaluations(repositories, '/var/lib/lib-chat-observer/evaluations')
