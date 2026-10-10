"""全コーパス（12,364コメント）の意味タグ付け（案A: 全質問、Jev、codebook v1.1）。本人の費用承認後にだけ実行する。

- 再開可能: 出力 jsonl は追記専用。既に判定済みの comment_id は飛ばす。200件ごとに checkpoint（進捗と使用量）を書く。
- 並列: --concurrency N（既定1）。スレッドで同時に N 本のリクエストを送る。HTTP 429/5xx は指数バックオフで最大5回再試行。
- 使用量: 入力・出力トークンと所要秒を runs/<run_id>_usage.json に累積。--max-comments で途中で止められる（費用の上限管理）。
- 質問・state・閾値は scripts/18_tag_pilot_v1.py と同じ関数を使う（18 を import せず、同じコードを関数化して複製しないため、ここでは 18 の実装を読み込んで再利用する）。
使い方（準備のみ。実行は承認後）:
  zsh -lc 'python3 scripts/20_tag_full_jev.py --run-id full_v1.1 --codebook codebook_v1.1 --concurrency 2'
  zsh -lc 'python3 scripts/20_tag_full_jev.py --run-id full_v1.1 --dry-run'           # 件数・推定トークンだけ表示
  zsh -lc 'python3 scripts/20_tag_full_jev.py --run-id concurrency_test --only-ids CM-000001,CM-000002,... --concurrency 4 --out-dir /tmp/x'  # 並列の受理試験
"""
import csv, json, os, sys, time, argparse, datetime, threading, queue, collections, urllib.error
import yaml
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAN = os.path.join(ROOT, 'canonical'); PRIV = os.path.join(CAN, 'private')
sys.path.insert(0, os.path.expanduser('~/.codex/skills/jev/scripts'))
import jev
ap = argparse.ArgumentParser()
ap.add_argument('--run-id', default='full_v1.1'); ap.add_argument('--codebook', default='codebook_v1.1'); ap.add_argument('--model', default='jev-latest')
ap.add_argument('--concurrency', type=int, default=1); ap.add_argument('--checkpoint-every', type=int, default=200); ap.add_argument('--max-comments', type=int, default=0)
ap.add_argument('--only-ids', default=''); ap.add_argument('--out-dir', default=None); ap.add_argument('--dry-run', action='store_true')
args = ap.parse_args()
OUT_DIR = args.out_dir or PRIV; os.makedirs(OUT_DIR, exist_ok=True)
CB = yaml.safe_load(open(os.path.join(CAN, 'codebook', args.codebook + '.yaml'), encoding='utf-8'))
TH_ = CB['thresholds']; TT = TH_.get('theme_tag', TH_.get('theme_tag_default')); TF = TH_['theme_not']; PER = TH_.get('per_theme', {})
def thr(k): return PER.get(k, TT)
def rd(p):
    with open(p, encoding='utf-8') as f: return list(csv.DictReader(f))
C = rd(os.path.join(CAN, 'comments.csv')); TEXT = {r['comment_id']: r['text'] for r in rd(os.path.join(PRIV, 'comment_text.csv'))}
CONCEPT = {r['concept_id']: r['name'] for r in rd(os.path.join(CAN, 'concepts.csv'))}

# ---------- 質問と state（18 と同一の定義） ----------
TH = {k: v for k, v in CB['axes']['theme']['labels'].items() if k != 'T00_none'}; FN = CB['axes']['function']['labels']
ST = {k: v for k, v in CB['axes']['stage']['labels'].items() if k != 'S0_not_applicable'}; SC = {k: v for k, v in CB['axes']['stage']['scope_labels'].items() if k != 'S0_not_applicable'}; OC = CB['axes']['stage']['outcome_confirmed']
STAGE_CRIT = {k: f"{v['name']}: {v['definition']}" for k, v in ST.items()}; SCOPE_CRIT = {k: f"{v['name']}: {v['definition']}" for k, v in SC.items()}; FN_CRIT = {k: f"{v['name']}: {v['definition']}" for k, v in FN.items()}
REQ_TYPES = {'改善のための助言', '改善のための示唆', '追加審査におけるコメント'}
def questions(c):
    q = {}
    for k, v in TH.items():
        q[k] = {'type': 'noul', 'instructions': f"Does the comment itself address 「{v['name']}」({v['definition']})? Judge from what the comment states, not from its subarea or names of courses/organizations.",
                'criteria': {'true': f"Includes: {v['include']}", 'false': f"Does not include: {v['exclude']}"}}
    q['function'] = {'type': 'choice', 'instructions': 'Primary function: the object the comment mainly asks to change, or praises. A function that appears only as a means, medium or place is not the primary one.', 'criteria': FN_CRIT}
    q['multi_function'] = {'type': 'noul', 'instructions': 'Is this a compound comment that makes separate requests or evaluations about two or more different objects (functions)?',
                           'criteria': {'true': 'Two or more distinct objects each with its own request/evaluation', 'false': 'One object; other functions appear only as means or context'}}
    q['secondary_function'] = {'type': 'choice', 'instructions': 'Secondary function, if the comment also acts on a second object. Choose none if there is no second object.', 'criteria': {**FN_CRIT, 'none': 'No secondary function'}}
    q['observed_stage'] = {'type': 'choice', 'instructions': 'Stage of what the comment states CURRENTLY exists at the school. Use only explicit statements; do not infer the current state from a request or from an organization name. Setting/placing/formulating only = 設計・整備; implementing/providing = 運用; checking/verifying = 点検・評価; using results for improvement = 結果利用.', 'criteria': STAGE_CRIT}
    q['observed_scope'] = {'type': 'choice', 'instructions': 'Scope of the current state as explicitly stated. "systematic" or "regular" does not mean all-target rollout.', 'criteria': SCOPE_CRIT}
    q['outcome_confirmed'] = {'type': 'noul', 'instructions': f"{OC['name']}: {OC['definition']}", 'criteria': {'true': 'The comment states that outcomes were measured and confirmed', 'false': 'Only goals set, or no outcome measurement stated'}}
    if c['type'] in REQ_TYPES:
        q['requested_stage'] = {'type': 'choice', 'instructions': 'Stage the comment REQUESTS the school to reach. Same stage definitions. Choose 記載なし/段階決定不能 if the request gives no stage (e.g. "further enhance").', 'criteria': STAGE_CRIT}
        q['requested_scope'] = {'type': 'choice', 'instructions': 'Scope the request explicitly asks for.', 'criteria': SCOPE_CRIT}
    return q
def state(c):
    return {'comment_text': TEXT[c['comment_id']], 'subarea': f"{c['concept_id']} {CONCEPT.get(c['concept_id'], '')}", 'level': {'B': '基本的水準', 'Q': '質的向上のための水準'}[c['level']],
            'comment_type': c['type'], 'review_type': c['review_type'], 'unit': 'One comment from a JACME medical-education accreditation report; a single unit.'}
def ch(a): return {'choice': a['choice'], 'confidence': a.get('confidence'), 'probabilities': a.get('probabilities')}
import hashlib
QUESTION_HASH = hashlib.sha256(json.dumps(questions({'type': '改善のための助言'}), ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]   # 質問テンプレートの版
def record(c, res, dt):
    A = res['answers']; themes = {k: A[k]['noul'] for k in TH}
    tags = {k: ('tag' if p >= thr(k) else 'not' if p < TF else 'uncertain') for k, p in themes.items()}
    t00 = 'tag' if not any(v in ('tag', 'uncertain') for v in tags.values()) else 'not'
    return {'comment_id': c['comment_id'], 'run_id': args.run_id, 'backend': 'typesafe', 'codebook_version': CB['version'], 'theme_threshold': TT, 'theme_threshold_per_theme': PER, 'model_requested': args.model, 'model_returned': res.get('model'), 'question_hash': QUESTION_HASH,
            'event_id': c['event_id'], 'institution_id': c['institution_id'], 'concept_id': c['concept_id'], 'level': c['level'], 'type': c['type'], 'review_type': c['review_type'], 'cycle': c['cycle'], 'standard_family': c['standard_family'],
            'themes': themes, 'theme_tags': {**tags, 'T00_none': t00}, 'function': ch(A['function']), 'multi_function': A['multi_function']['noul'], 'secondary_function': ch(A['secondary_function']),
            'observed_stage': ch(A['observed_stage']), 'observed_scope': ch(A['observed_scope']), 'outcome_confirmed': A['outcome_confirmed']['noul'],
            'requested_stage': ch(A['requested_stage']) if 'requested_stage' in A else {'choice': 'S0_not_applicable', 'confidence': None, 'probabilities': None},
            'requested_scope': ch(A['requested_scope']) if 'requested_scope' in A else {'choice': 'S0_not_applicable', 'confidence': None, 'probabilities': None},
            'usage': res.get('usage'), 'seconds': dt, 'called_at': datetime.datetime.now().isoformat(timespec='seconds')}

# ---------- 対象と再開 ----------
out_path = os.path.join(OUT_DIR, f'tags_jev_{args.run_id}.jsonl'); ckpt_path = os.path.join(OUT_DIR, f'tags_jev_{args.run_id}_checkpoint.json'); usage_path = os.path.join(OUT_DIR, f'tags_jev_{args.run_id}_usage.json')
done = set()
if os.path.exists(out_path):
    for ln in open(out_path, encoding='utf-8'):
        try: done.add(json.loads(ln)['comment_id'])
        except json.JSONDecodeError: pass   # 途中で切れた行は無視（次に再判定される）
targets = [c for c in C if c['comment_id'] not in done]
if args.only_ids: want = set(args.only_ids.split(',')); targets = [c for c in C if c['comment_id'] in want and c['comment_id'] not in done]
if args.max_comments: targets = targets[:args.max_comments]
EST_IN = 222 + 237 * 19; EST_IN_REQ = 237 * 2
est_in = sum(EST_IN + (EST_IN_REQ if c['type'] in REQ_TYPES else 0) for c in targets)
print(json.dumps({'run_id': args.run_id, 'codebook': CB['version'], 'thresholds': {'default': TT, 'per_theme': PER, 'not': TF}, 'total_comments': len(C), 'already_done': len(done), 'to_do': len(targets),
                  'estimated_input_tokens': est_in, 'estimated_seconds_sequential': round(len(targets) * 0.24), 'concurrency': args.concurrency, 'out': out_path}, ensure_ascii=False, indent=1))
if args.dry_run or not targets: sys.exit(0)

# ---------- 実行（スレッド並列、追記専用、checkpoint） ----------
def _sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()
usage = json.load(open(usage_path, encoding='utf-8')) if os.path.exists(usage_path) else {'input_tokens': 0, 'output_tokens': 0, 'calls': 0, 'errors': 0, 'seconds': 0.0, 'started': datetime.datetime.now().isoformat(timespec='seconds'),
    'input_hashes': {'canonical/comments.csv': _sha(os.path.join(CAN, 'comments.csv')), 'canonical/private/comment_text.csv': _sha(os.path.join(PRIV, 'comment_text.csv')), 'codebook': _sha(os.path.join(CAN, 'codebook', args.codebook + '.yaml'))},
    'question_hash': QUESTION_HASH, 'codebook_version': CB['version'], 'thresholds': {'default': TT, 'per_theme': PER}}
lock = threading.Lock(); q = queue.Queue(); [q.put(c) for c in targets]
fout = open(out_path, 'a', encoding='utf-8'); n_done = 0; t_all = time.time(); stop = threading.Event()
def call_with_retry(c):
    delay = 2.0
    for attempt in range(5):
        try: return jev.call(state(c), questions(c), args.model, timeout=120)
        except SystemExit as e:   # jev.call は HTTP エラーで SystemExit を投げる
            msg = str(e)
            if attempt == 4 or not any(code in msg for code in ('429', '500', '502', '503', '504')): raise
            time.sleep(delay); delay *= 2
def checkpoint():
    json.dump({'run_id': args.run_id, 'done': len(done), 'to_do_remaining': q.qsize(), 'at': datetime.datetime.now().isoformat(timespec='seconds'), 'usage': usage}, open(ckpt_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    json.dump(usage, open(usage_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
def worker():
    global n_done
    while not stop.is_set():
        try: c = q.get_nowait()
        except queue.Empty: return
        t0 = time.time()
        try: res = call_with_retry(c)
        except SystemExit as e:
            with lock: usage['errors'] += 1; print('ERROR', c['comment_id'], str(e)[:200], flush=True)
            continue
        dt = round(time.time() - t0, 2); rec = record(c, res, dt); u = res.get('usage') or {}
        with lock:
            fout.write(json.dumps(rec, ensure_ascii=False) + '\n'); fout.flush(); done.add(c['comment_id']); n_done += 1
            usage['input_tokens'] += u.get('input_tokens', 0) or 0; usage['output_tokens'] += u.get('output_tokens', 0) or 0; usage['calls'] += 1; usage['seconds'] += dt
            if n_done % args.checkpoint_every == 0:
                checkpoint(); el = time.time() - t_all
                print(f"{n_done}/{len(targets)} done, {el/60:.1f} min, {n_done/el:.2f}/s, in={usage['input_tokens']:,} out={usage['output_tokens']:,} errors={usage['errors']}", flush=True)
threads = [threading.Thread(target=worker, daemon=True) for _ in range(max(1, args.concurrency))]
try:
    [t.start() for t in threads]; [t.join() for t in threads]
except KeyboardInterrupt:
    stop.set(); print('interrupted; checkpointing', flush=True)
finally:
    fout.close(); usage['finished'] = datetime.datetime.now().isoformat(timespec='seconds'); checkpoint()
el = time.time() - t_all
print(json.dumps({'done_this_run': n_done, 'elapsed_min': round(el / 60, 1), 'rate_per_s': round(n_done / el, 2) if el else None, 'usage_total': usage}, ensure_ascii=False, indent=1))
