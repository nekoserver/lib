#!/usr/bin/env python3
"""Museへの質問の順番待ち(2026-11-08、利用者の指摘「Museが応答してる間にタスクを積んどくとかできるでしょ」)。

~/.claude/tools/muse-queue/pending/*.json を名前順に1件ずつ inquiry.py ask --engine muse で送る。
各ファイル: {"case": 議題ID, "clue": 手掛かり, "prompt": 質問}。
送る前に、Museの処理中のジョブ(/var/lib/lib-llm/jobs の muse-* が pending・running)が無いことを待つ(同時に送らない)。
結果は inquiry.py が D1 に記録する。終わったファイルは done/ か failed/ へ移し、1件ごとに1行を標準出力へ出す(Monitorの通知になる)。
キューが空のまま idle 分たったら終わる。
"""
import glob, json, os, subprocess, sys, time

BASE = os.path.expanduser('~/.claude/tools/muse-queue')
TOOL = os.path.expanduser('~/.claude/tools/inquiry.py')
IDLE_MINUTES = int(sys.argv[1]) if len(sys.argv) > 1 else 30


def muse_busy():
    for f in glob.glob('/var/lib/lib-llm/jobs/muse-*.json'):
        try:
            if json.load(open(f)).get('ask_status') in ('pending', 'running'):
                return True
        except Exception:
            pass
    return False


def say(text):
    print(time.strftime('%H:%MZ', time.gmtime()) + ' ' + text, flush=True)


def main():
    for d in ('pending', 'done', 'failed'):
        os.makedirs(os.path.join(BASE, d), exist_ok=True)
    idle_since = time.time()
    while True:
        tasks = sorted(glob.glob(os.path.join(BASE, 'pending', '*.json')))
        if not tasks:
            if time.time() - idle_since > IDLE_MINUTES * 60:
                say('キューが空のまま%d分たったので終わる' % IDLE_MINUTES)
                return
            time.sleep(20)
            continue
        while muse_busy():
            time.sleep(15)
        path = tasks[0]
        name = os.path.basename(path)
        try:
            t = json.load(open(path, encoding='utf-8'))
        except Exception as e:
            os.replace(path, os.path.join(BASE, 'failed', name))
            say('読めないタスク %s: %s' % (name, e))
            continue
        pf = path + '.prompt.txt'
        open(pf, 'w', encoding='utf-8').write(t['prompt'])
        say('送信 %s(%s / %s)残り%d件' % (name, t['case'], t['clue'], len(tasks) - 1))
        r = subprocess.run([sys.executable, '-I', TOOL, 'ask', '--engine', 'muse', '--case', t['case'], '--clue', t['clue'], '--prompt-file', pf],
                           capture_output=True, text=True)
        os.remove(pf)
        out = (r.stdout + r.stderr).strip()
        rec = [l for l in out.splitlines() if l.startswith('記録した:')]
        ok = r.returncode == 0 and '"answered"' in ' '.join(rec)
        dest = 'done' if ok else 'failed'
        open(os.path.join(BASE, dest, name + '.out.txt'), 'w', encoding='utf-8').write(out)
        os.replace(path, os.path.join(BASE, dest, name))
        say('%s %s %s' % ('完了' if ok else '失敗', name, rec[-1] if rec else out[-200:].replace('\n', ' ')))
        idle_since = time.time()


if __name__ == '__main__':
    main()
