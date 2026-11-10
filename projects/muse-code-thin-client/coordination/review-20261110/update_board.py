"""Record this explicit user-requested board update; credentials stay in ENV."""
import json, os, time, urllib.request
from pathlib import Path
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
URL = 'https://api.cloudflare.com/client/v4/accounts/' + os.environ['CLOUDFLARE_ACCOUNT_ID'] + '/d1/database/ab65ff96-6333-4673-9ad4-4324be622184/query'
LAST = 0.0
LOG = []
def query(sql, params=()):
    global LAST
    time.sleep(max(0, 1 - (time.monotonic() - LAST)))
    req = urllib.request.Request(URL, data=json.dumps({'sql': sql, 'params': list(params)}).encode(), headers={'Authorization': 'Bearer ' + os.environ['CF_CONTAINER_API_TOKEN'], 'Content-Type': 'application/json'}, method='POST')
    LAST = time.monotonic()
    with urllib.request.urlopen(req, timeout=25) as response:
        data = json.load(response)
    if not data.get('success') or not all(r.get('success') for r in data.get('result', [])):
        raise RuntimeError('D1 request failed; inspect API result without exposing credentials')
    result = data['result'][0]
    LOG.append({'sql': sql, 'params': list(params), 'changes': result.get('meta', {}).get('changes', 0)})
    (HERE / 'board-operations.json').write_text(json.dumps(LOG, ensure_ascii=False, indent=2) + '\n')
    return result.get('results', [])
def insert(table, values, key='id'):
    existing = query('SELECT * FROM ' + table + ' WHERE ' + key + '=?', [values[key]])
    if existing:
        for k, v in values.items():
            if k != 'status' and existing[0].get(k) != v:
                raise RuntimeError('Existing record differs: ' + table + '/' + values[key])
        return
    columns = ','.join(values)
    query('INSERT INTO ' + table + '(' + columns + ') VALUES (' + ','.join('?' for _ in values) + ')', values.values())

case = 'muse-code-wasm-thin-client-20261110'
pre = 'preprint-browser-evidence-20261110'
entry = case + '-e2'
run = 'sdk-wasm-reconsolidation-20261110'
baseline = {
    'cases': query('SELECT id,goal,status,stage FROM inquiry_cases ORDER BY id'),
    'keys': query("SELECT id,case_id,text,status FROM inquiry_keys WHERE status='open' ORDER BY id"),
    'proposals': query("SELECT id,case_id,text,status FROM inquiry_proposals WHERE status IN ('proposed','adopted') ORDER BY id"),
}
(HERE / 'board-before.json').write_text(json.dumps(baseline, ensure_ascii=False, indent=2) + '\n')
insert('inquiry_cases', {'id': case, 'goal': '現稼働Workerから必要機能を移植するMuse Code SDK/Tailscale WASMシンクライアントについて、作成済み成果と未検証範囲を照合し、次の段取りを決める。', 'status': 'open', 'stage': 'plan'})
insert('inquiry_cases', {'id': pre, 'goal': 'preprintを既存の画面確認・移植比較・検証根拠保存へ活用する用途と最初の独立session実験案をMuseと協議する。実装・ブラウザ操作は今回は行わない。', 'status': 'open', 'stage': 'plan'})
report = (ROOT / 'REPORT.lib.20261110.muse-code-wasm-received.md').read_text()
insert('inquiry_entries', {'id': case + '-e1', 'case_id': case, 'seq': 1, 'clue': '利用者がMuse側の専用Worker作成結果を共有。独立確認と区別して既存計画を更新する。', 'asked_by': 'user', 'agent': 'muse-main-chat', 'question': '利用者経由で受領した作成報告の記録。以下のanswerは受領記録の要約でありAPIから取得したMuse回答全文ではない。', 'answer': report, 'info': 'ソース・軽量検証まで成功との利用者共有。:auto-review実ターン、8090到達、WASM実機、配備は未確認。', 'progress': '作成済み成果に一本化し、こちらの重複試作を継続しない。段階はplanを維持。', 'status': 'answered'})
prebase = HERE.parent / 'preprint'
insert('inquiry_entries', {'id': pre + '-e1', 'case_id': pre, 'seq': 1, 'clue': '導入済みpreprintの有用な用途と最初の小実験を協議。過去の同一議題がないことを確認。', 'asked_by': 'codex', 'agent': 'muse', 'question': (prebase / 'request.md').read_text(), 'answer': (prebase / 'response.md').read_text(), 'info': '画面状態、移植前後のUI/console、Job再訪の3用途。独立sessionの公開1画面から始める案。', 'progress': '提案を取得。ブラウザ試験・本番確認は行っていない。今回の新規再質問には含めず根拠として利用。', 'status': 'answered'})
insert('inquiry_proposals', {'id': pre + '-p1', 'case_id': pre, 'entry_id': pre + '-e1', 'proposed_by': 'muse', 'text': '既存ログインを使わない独立sessionで公開1画面を読み、Markdown投影とconsole記録を取得する小実験。API/SDK/WASM検証の代替や必須前提にはしない。', 'status': 'proposed', 'reason': 'Museから提案を取得。実験は未実施であり採用・完了とはしない。'})
request = (HERE / 'request.md').read_text()
insert('inquiry_entries', {'id': entry, 'case_id': case, 'seq': 2, 'clue': '作成済み成果・profile/認証の説明と以前の構想の整合を取り、残差だけ再協議する。', 'asked_by': 'codex', 'agent': 'muse', 'question': request, 'info': '認証とreviewer、到達性と実SDK終端、保存結果と重複抑止を区別する。', 'progress': '既決方針は再質問せず、次の2〜3工程を具体化する依頼。', 'status': 'planned'})
keys = [
    (case + '-k-auth-profile', 'モデル認証と自動レビュアー可用性の条件・観測エラー・実効profileを分け、実ターンの開始条件を確定する。'),
    (case + '-k-live-path', 'Worker実機WASMとtailnet→:8090到達、実SDKの正常終端を段階別に確認する。dry-run/Job受付だけでは成立としない。'),
    (case + '-k-result-contract', '受信側requestId、保存結果の再取得、送信結果不明・重複要求の保証をソースとログで照合する。'),
]
for key, text in keys:
    insert('inquiry_keys', {'id': key, 'case_id': case, 'kind': 'unknown', 'text': text, 'status': 'open', 'blocking': 1, 'mutating': 0, 'opened_by_entry_id': entry})
    query("INSERT INTO inquiry_entry_keys(entry_id,key_id,role) SELECT ?,?,'target' WHERE NOT EXISTS (SELECT 1 FROM inquiry_entry_keys WHERE entry_id=? AND key_id=? AND role='target')", [entry, key, entry, key])
insert('inquiry_work_runs', {'id': run, 'performed_by': 'codex', 'request_text': '最新情報で既存協議を更新・再要約し、残差を再質問にまとめ再協議。必要に応じカンバンも更新。', 'selection_policy': 'D1/D4/E1:新情報で前提が変わる3残差に限定。既回答preprint案と既決構成は再質問しない。', 'success_criterion': '次の2〜3工程・担当・合格条件を明確化し、未実測を成功や解除済みとしない。', 'reason_timing': 'contemporaneous', 'expected_items': 3, 'expected_groups': 1, 'progress_snapshot_json': json.dumps(baseline, ensure_ascii=False)})
query('INSERT INTO inquiry_work_groups(run_id,entry_id,case_id,group_reason,goal_snapshot) SELECT ?,?,?,?,? WHERE NOT EXISTS(SELECT 1 FROM inquiry_work_groups WHERE run_id=? AND entry_id=?)', [run, entry, case, '単一の段取りに影響する認証・通信・結果契約を一問に集約。', '作成済みmuse-code-wasmを基準に次の工程を決める。', run, entry])
for rank, (key, text) in enumerate(keys, 1):
    query('INSERT INTO inquiry_work_items(run_id,entry_id,key_id,priority_rank,selection_reason,grouping_reason,title_snapshot) SELECT ?,?,?,?,?,?,? WHERE NOT EXISTS(SELECT 1 FROM inquiry_work_items WHERE run_id=? AND key_id=?)', [run, entry, key, rank, '正常終端と代替可能性を判定するために必要。', '既決の構想は維持し、作成済み成果の残差に限定。', text, run, key])
insert('inquiry_work_audits', {'id': run + '-audit', 'run_id': run, 'entry_id': entry, 'audit_timing': 'before_dispatch', 'progress_snapshot_json': json.dumps(baseline, ensure_ascii=False), 'duplicate_check_json': json.dumps({'same_case_found': False, 'related_case': 'muse-status-wasm-20261107', 'distinct_acceptance': '専用WorkerのSDK実行経路。既存status画面とは異なる。', 'preprint_answer_reused': True, 'previous_origin_query_unknown': True, 'code_creation_not_resent': True}, ensure_ascii=False), 'conclusion': '既回答のpreprint用途と既決構成は再送せず、最新の作成結果で変わった3残差だけ協議。ソース保存先の旧問い合わせを重複する作成依頼として再送しない。', 'checked_by': 'codex'})
query('INSERT INTO inquiry_work_completions(run_id,recorded_by) SELECT ?,? WHERE NOT EXISTS(SELECT 1 FROM inquiry_work_completions WHERE run_id=?)', [run, 'codex', run])
state = query('SELECT c.id,c.status,c.stage,(SELECT COUNT(*) FROM inquiry_entries e WHERE e.case_id=c.id) AS entries,(SELECT COUNT(*) FROM inquiry_keys k WHERE k.case_id=c.id AND k.status=\'open\') AS open_keys FROM inquiry_cases c WHERE c.id IN (?,?)', [case, pre])
(HERE / 'board-readback.json').write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'board_readback': state, 'review_entry': entry, 'work_run': run}, ensure_ascii=False))
