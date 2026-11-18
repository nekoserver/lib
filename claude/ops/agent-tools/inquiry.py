#!/usr/bin/env python3
"""D1 agent-inquiries への問い合わせと記録をまとめる道具(2026-11-08、利用者の指摘「業務の最適化を考えないの？」)。

それまでは、問い合わせのたびに「送る→待つ→応答から取り出す→D1に書く」を手で書いていた。
  ask   : Muse・Codex・Claudeへ ~/lib の askgk_request.rb で送り、結果(失敗も)を inquiry_entries に書く。
          Museは muse-vm の /health が戻るまで待ってから送る(再起動が多いため)。
  note  : 利用者の発言・決定、実装の記録を inquiry_entries に書く。
  clarify: 利用者が「何が分からないか」(目的・因果・効果・根拠・手順・所要時間・費用・危険・代替)を指定すると、
          提案と議題の記録から質問を組み立て、Muse(キュー)とCodexへ同時に送る。回答は自動でD1に記録される。
  sql   : 読み取り用。SELECTを実行して表示する。
使い方の例:
  inquiry.py ask --engine codex --case CASE --clue 手掛かり --prompt-file q.txt
  inquiry.py note --case CASE --clue 手掛かり --asked-by user --agent user --question '(利用者の発言)' --answer 本文
注意: プロンプトに半角の二重引用符を入れない(◯_prompt= の区切りが壊れる)。外部への送信は1秒以上の間隔を空ける。
"""
import argparse, json, os, subprocess, sys, time, urllib.request

DB = 'ab65ff96-6333-4673-9ad4-4324be622184'
# 標準の答え方(利用者の指定、2026-11-08「因果関係や目的や効果は標準仕様でないとおかしい」)。
# すべての問い合わせの末尾に付け、提案・判断ごとに同じ項目で答えさせる。--raw のときだけ付けない。
STANDARD = ('答え方の決まり: 提案や判断を述べるときは、1件ごとに次の項目をすべて書いてください。'
            '問題(何が起きているか)、原因と因果(なぜ起きるか、何が何を引き起こすか)、'
            '根拠(実物の形跡: ファイルと行、ログ、時刻、件数。無ければ形跡無しと書く)、'
            '目的(何のためにするか)、期待する効果(何がどれだけ良くなるか)、'
            '測り方(どの数字がどう変われば効いたと言えるか)、手順(誰が何をどの順でするか)、'
            '所要時間(作業と待ちの見込み)、費用と危険。'
            '分からない項目は推測で埋めず、不明と書いてください。'
            '各項目は1〜2文、全体で800字以内にまとめてください(1件の処理の上限は300秒です)。')

# 利用者が「何が分からないか」を指定するだけで、必要な問い合わせを組み立てて埋める(利用者の提案、2026-11-08)。
ASPECTS = {
    '目的': '何のためにするのか。誰のどの困りごとを解くのか',
    '因果': '問題の原因は何か。この対策が、どういう筋道でその原因を断つのか',
    '効果': '何がどれだけ良くなるのか。どの数字で測り、今の値と目標の値はいくつか',
    '根拠': '問題が実際に起きている形跡(ファイルと行、ログ、時刻、件数)。無ければ形跡無しと答える',
    '手順': '誰が何をどの順でするのか。取り消すときの手順も',
    '所要時間': '作業の時間と待ちの時間の見込み。何に時間がかかるか',
    '費用': '手間、計算資源、外部への課金、止まる時間',
    '危険': '壊れ方、影響の範囲、取り消せるか',
    '代替': 'しない場合や、ほかの方法と比べてどうか',
}
LIB = os.path.expanduser('~/lib')
_last = [0.0]


def q(sql, params=()):
    wait = 1.1 - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    url = f"https://api.cloudflare.com/client/v4/accounts/{os.environ['CLOUDFLARE_ACCOUNT_ID']}/d1/database/{DB}/query"
    req = urllib.request.Request(url, json.dumps({'sql': sql, 'params': list(params)}).encode(),
                                 {'Authorization': 'Bearer ' + os.environ['CF_CONTAINER_API_TOKEN'], 'Content-Type': 'application/json'})
    d = json.load(urllib.request.urlopen(req))
    _last[0] = time.time()
    if not d.get('success'):
        raise SystemExit('D1の失敗: ' + json.dumps(d.get('errors'), ensure_ascii=False))
    return d['result'][0]['results']


def next_seq(case):
    if not q('SELECT 1 FROM inquiry_cases WHERE id = ?', [case]):
        raise SystemExit('議題が無い: ' + case)
    return q('SELECT COALESCE(MAX(seq), 0) + 1 AS s FROM inquiry_entries WHERE case_id = ?', [case])[0]['s']


def muse_up():
    try:
        out = subprocess.run("( printf 'GET /health HTTP/1.0\\r\\nHost: muse-vm\\r\\n\\r\\n'; sleep 3 ) | timeout 8 tailscale nc muse-vm 8080",
                             shell=True, capture_output=True, text=True, timeout=15).stdout
        return '"ok"' in out
    except Exception:
        return False


def insert_entry(case, clue, asked_by, agent, question, answer=None, info=None, progress=None, status='answered', ask_id=None, error=None, duration=None):
    seq = next_seq(case)
    eid = f'{case}-e{seq}'
    q('INSERT INTO inquiry_entries (id, case_id, seq, clue, asked_by, agent, ask_id, question, answer, info, progress, status, error, duration_seconds) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
      [eid, case, seq, clue, asked_by, agent, ask_id, question, answer, info, progress, status, error, duration])
    got = q('SELECT id, seq, status FROM inquiry_entries WHERE id = ?', [eid])
    print('記録した:', json.dumps(got[0], ensure_ascii=False))
    return eid


def cmd_ask(a):
    prompt = open(a.prompt_file, encoding='utf-8').read().strip()
    if not a.raw and STANDARD not in prompt:
        prompt = prompt + ' ' + STANDARD
    if '"' in prompt:
        raise SystemExit('プロンプトに半角の二重引用符がある。「」に置き換えること')
    if a.engine == 'muse':
        deadline = time.time() + a.wait_minutes * 60
        while not muse_up():
            if time.time() > deadline:
                insert_entry(a.case, a.clue, 'claude-code', 'muse', prompt, status='failed', error='muse_vm_down_timeout')
                raise SystemExit('muse-vmが戻らない')
            print('muse-vmの応答待ち…', flush=True)
            time.sleep(30)
    start = time.time()
    r = subprocess.run(['timeout', '330', 'ruby', 'claude/test/manual/askgk_request.rb', 'claude/api/tunnels.claude.rb', f'{a.engine}_prompt="{prompt}"'],
                       cwd=LIB, capture_output=True, text=True)
    dur = int(time.time() - start)
    out = r.stdout + r.stderr
    try:
        d = json.loads(out[out.index('{'):out.rindex('}') + 1])
    except ValueError:
        insert_entry(a.case, a.clue, 'claude-code', a.engine, prompt, status='failed', error='no_json_response', duration=dur)
        raise SystemExit('応答がJSONでない:\n' + out[-500:])
    ok = d.get('ask_status') == 'done'
    insert_entry(a.case, a.clue, 'claude-code', a.engine, prompt, answer=d.get('reply') if ok else None,
                 status='answered' if ok else 'failed', ask_id=d.get('ask_id'), error=None if ok else d.get('ask_error'), duration=dur)
    print(d.get('reply') or d.get('ask_error'))


def cmd_note(a):
    insert_entry(a.case, a.clue, a.asked_by, a.agent, a.question, answer=a.answer, info=a.info, progress=a.progress)


def cmd_clarify(a):
    aspects = [x.strip() for x in a.aspects.replace('、', ',').split(',') if x.strip()]
    unknown = [x for x in aspects if x not in ASPECTS]
    if unknown:
        raise SystemExit('知らない区分: ' + ','.join(unknown) + ' (使える区分: ' + ','.join(ASPECTS) + ')')
    rows = q('SELECT p.id, p.case_id, p.text, p.status, p.reason, c.goal FROM inquiry_proposals p JOIN inquiry_cases c ON c.id = p.case_id WHERE p.id = ?', [a.target])
    if rows:
        r = rows[0]; case = r['case_id']
        subject = '提案(' + r['id'] + '、状態 ' + r['status'] + '): ' + r['text']
    else:
        rows = q('SELECT id, goal FROM inquiry_cases WHERE id = ?', [a.target])
        if not rows:
            raise SystemExit('提案にも議題にも無い: ' + a.target)
        r = rows[0]; case = r['id']; subject = '議題そのもの'
    goal = q('SELECT goal FROM inquiry_cases WHERE id = ?', [case])[0]['goal']
    keys = q("SELECT kind, text FROM inquiry_keys WHERE case_id = ? AND status = 'open' ORDER BY blocking DESC, created_at LIMIT 8", [case])
    lines = ['読み取りのみ。調べて答えてください。変更はしないでください。',
             '議題の目的: ' + goal, '対象: ' + subject]
    if keys:
        lines.append('関係する未解決の論点: ' + ' / '.join(k['kind'] + ': ' + k['text'] for k in keys))
    lines.append('利用者は次の点が分からないと言っています。それぞれを実物(ファイル、ログ、記録)で確かめて、項目ごとに答えてください。')
    for x in aspects:
        lines.append(x + ': ' + ASPECTS[x])
    prompt = ' '.join(lines).replace('"', '「')
    clue = '利用者の不明点の解消(' + '・'.join(aspects) + ')'
    stamp = time.strftime('%Y%m%d%H%M%S', time.gmtime())
    targets = a.engines.split(',')
    if 'muse' in targets:
        qdir = os.path.expanduser('~/.claude/tools/muse-queue/pending')
        os.makedirs(qdir, exist_ok=True)
        path = os.path.join(qdir, '90-clarify-' + stamp + '-' + a.target + '.json')
        json.dump({'case': case, 'clue': clue, 'prompt': prompt}, open(path, 'w', encoding='utf-8'), ensure_ascii=False)
        print('Museのキューに積んだ:', os.path.basename(path))
    # 役割分担(2026-11-08): Codexの実行環境からはmuse-vmの中が見えないため、実物の確認(根拠)はMuseだけに頼む。
    # Codexには筋道・壊れ方・抜けの点検として、根拠を除いた区分を渡す。
    review_aspects = [x for x in aspects if x != '根拠']
    review_prompt = prompt
    if '根拠' in aspects:
        review_prompt = prompt.replace('根拠: ' + ASPECTS['根拠'], '').replace('それぞれを実物(ファイル、ログ、記録)で確かめて、', '実物の確認はMuseが別に行います。あなたは筋道・壊れ方・抜けを点検する立場で、')
    for eng in [t for t in targets if t != 'muse']:
        if not review_aspects:
            print(eng + 'には送らない(区分が根拠だけのため、Museの実物の確認に任せる)')
            continue
        pf = os.path.join('/tmp', 'clarify-' + stamp + '-' + eng + '.txt')
        open(pf, 'w', encoding='utf-8').write(review_prompt)
        log = os.path.expanduser('~/.claude/tools/clarify-' + stamp + '-' + eng + '.log')
        subprocess.Popen([sys.executable, '-I', os.path.abspath(__file__), 'ask', '--engine', eng, '--case', case, '--clue', clue, '--prompt-file', pf],
                         stdout=open(log, 'w'), stderr=subprocess.STDOUT, start_new_session=True)
        print(eng + 'へ送った(裏で実行、記録は自動):', log)



def cmd_sql(a):
    if not a.sql.lstrip().upper().startswith(('SELECT', 'PRAGMA')):
        raise SystemExit('sqlは読み取りだけ')
    for row in q(a.sql):
        print(json.dumps(row, ensure_ascii=False))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('ask'); s.add_argument('--engine', choices=['muse', 'codex', 'claude'], required=True)
    s.add_argument('--case', required=True); s.add_argument('--clue', required=True); s.add_argument('--prompt-file', required=True)
    s.add_argument('--wait-minutes', type=int, default=15)
    s.add_argument('--raw', action='store_true', help='標準の答え方を付けない(雑談や疎通の確認だけ)'); s.set_defaults(f=cmd_ask)
    s = sub.add_parser('note'); s.add_argument('--case', required=True); s.add_argument('--clue', required=True)
    s.add_argument('--asked-by', default='claude-code'); s.add_argument('--agent', default='claude-code')
    s.add_argument('--question', required=True); s.add_argument('--answer'); s.add_argument('--info'); s.add_argument('--progress'); s.set_defaults(f=cmd_note)
    s = sub.add_parser('clarify', help='利用者が分からない点を指定して、Muse・Codexに埋めさせる')
    s.add_argument('target', help='提案ID(例 pr-flock-scripts)か議題ID'); s.add_argument('aspects', help='分からない点。例: 目的,因果,効果,所要時間')
    s.add_argument('--engines', default='muse,codex'); s.set_defaults(f=cmd_clarify)
    s = sub.add_parser('sql'); s.add_argument('sql'); s.set_defaults(f=cmd_sql)
    a = p.parse_args(); a.f(a)


if __name__ == '__main__':
    main()
