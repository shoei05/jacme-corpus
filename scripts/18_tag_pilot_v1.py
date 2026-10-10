"""コメントの意味タグ付け試行 v1（codebook_v1、Jev）。v0 は scripts/16_tag_pilot_jev.py。
- 層化抽出は v0 と同じ（審査種別×巡、基準系列、B/Q、種別。大学上限）。--exclude-run で以前の run に含めた comment_id を除く。
- 質問: テーマ13（noul、criteria true/false に包含・除外）、主機能（choice）、複合機能（noul）、副機能（choice、無しあり）、
  observed_stage / observed_scope / outcome_confirmed、requested_stage / requested_scope（要求を含む種別のみ）。
- 閾値はコードブックの thresholds（theme_tag 0.3 暫定、theme_not 0.2）。--theme-threshold で上書き可。
- T00 はコードで導出: 閾値以上のテーマが無く、不確実帯（theme_not〜閾値）も無いとき。
出力（private）: tags_jev_<run_id>.jsonl、tags_jev_<run_id>_summary.json、tag_pilot_sample_<run_id>.csv、tag_audit_packet_<run_id>.md（答えなし）、tag_audit_key_<run_id>.csv
使い方: zsh -lc 'python3 scripts/18_tag_pilot_v1.py --n 200 --run-id pilot02 --exclude-run pilot01'
"""
import csv, json, os, sys, random, argparse, time, datetime, collections
import yaml
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAN = os.path.join(ROOT, 'canonical'); PRIV = os.path.join(CAN, 'private')
sys.path.insert(0, os.path.expanduser('~/.codex/skills/jev/scripts'))
import jev, urllib.request, urllib.error
def call_workers_ai(state, questions, model, timeout=120):
    """Cloudflare Workers AI の Clef。応答は {"result": {...}, "success": true} で包まれる。"""
    acct = os.environ.get('CLOUDFLARE_ACCOUNT_ID'); tok = os.environ.get('CLOUDFLARE_API_TOKEN')
    if not acct or not tok: sys.exit('CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN が未設定（~/.config/typesafe/env を source する）')
    body = json.dumps({'model': model, 'state': state, 'questions': questions}, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(f'https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/@cf/cloudflare/{model}', data=body, headers={'Authorization': 'Bearer ' + tok, 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r: res = json.load(r)
    except urllib.error.HTTPError as e: sys.exit(f'Workers AI HTTP {e.code}: {e.read().decode("utf-8", "replace")[:800]}')
    if 'answers' not in res and isinstance(res.get('result'), dict): res = res['result']
    if 'answers' not in res: sys.exit('Workers AI の応答に answers が無い: ' + json.dumps(res)[:500])
    return res
ap = argparse.ArgumentParser(); ap.add_argument('--n', type=int, default=200); ap.add_argument('--run-id', default='pilot02'); ap.add_argument('--model', default='jev-latest')
ap.add_argument('--codebook', default='codebook_v1.1'); ap.add_argument('--exclude-run', action='append', default=[]); ap.add_argument('--theme-threshold', type=float, default=None)
ap.add_argument('--backend', choices=['typesafe', 'workers-ai'], default='typesafe'); ap.add_argument('--only-audited-of', default=None, help='この run の tag_audit_key_<run>.csv で in_audit_packet=True のコメントだけを判定'); ap.add_argument('--out-prefix', default=None, help='出力名の接頭辞（既定: tags_jev）'); ap.add_argument('--no-packet', action='store_true')
ap.add_argument('--cap-per-institution', type=int, default=3); ap.add_argument('--audit-n', type=int, default=60); ap.add_argument('--seed', type=int, default=1)
args = ap.parse_args()
if args.backend == 'workers-ai' and args.model == 'jev-latest': args.model = 'clef-flash'
PREFIX = args.out_prefix or ('tags_jev' if args.backend == 'typesafe' else 'tags_clef')
CB = yaml.safe_load(open(os.path.join(CAN, 'codebook', args.codebook + '.yaml'), encoding='utf-8'))
TH_ = CB['thresholds']; TT = args.theme_threshold if args.theme_threshold is not None else TH_.get('theme_tag', TH_.get('theme_tag_default')); TF = TH_['theme_not']
PER = TH_.get('per_theme', {}) if args.theme_threshold is None else {}   # v1.1: テーマ別閾値（T11/T13 暫定）。--theme-threshold 指定時は一律
def thr(k): return PER.get(k, TT)
def rd(p):
    with open(p, encoding='utf-8') as f: return list(csv.DictReader(f))
C = rd(os.path.join(CAN, 'comments.csv')); TEXT = {r['comment_id']: r['text'] for r in rd(os.path.join(PRIV, 'comment_text.csv'))}
CONCEPT = {r['concept_id']: r['name'] for r in rd(os.path.join(CAN, 'concepts.csv'))}; INST = {r['institution_id']: r['name'] for r in rd(os.path.join(CAN, 'institutions.csv'))}
excl = set()
for rid in args.exclude_run:
    p = os.path.join(PRIV, f'tags_jev_{rid}.jsonl')
    if os.path.exists(p): excl |= {json.loads(l)['comment_id'] for l in open(p, encoding='utf-8')}
pool = [c for c in C if c['comment_id'] not in excl]

# ---------- 層化抽出 ----------
rng = random.Random(args.seed)
def stratum(c): return (c['review_type'] + (c['cycle'] or ''), c['standard_family'], c['level'], c['type'])
by = collections.defaultdict(list)
for c in pool: by[stratum(c)].append(c)
for v in by.values(): rng.shuffle(v)
total = len(pool); quota = {k: max(1, round(args.n * len(v) / total)) for k, v in by.items()}
while sum(quota.values()) > args.n: k = max(quota, key=lambda k: quota[k]); quota[k] -= 1
while sum(quota.values()) < args.n: k = max(by, key=lambda k: len(by[k]) / quota[k]); quota[k] += 1
inst_count = collections.Counter(); sample = []; chosen = set(); cap = args.cap_per_institution
while len(sample) < args.n and cap <= args.cap_per_institution + 3:
    for k, v in by.items():
        taken = sum(1 for c in sample if stratum(c) == k)
        for c in v:
            if taken >= quota[k] or len(sample) >= args.n: break
            if c['comment_id'] in chosen or inst_count[c['institution_id']] >= cap: continue
            sample.append(c); chosen.add(c['comment_id']); inst_count[c['institution_id']] += 1; taken += 1
    cap += 1
rng.shuffle(sample)
if args.only_audited_of:
    aud_ids = {r['comment_id'] for r in rd(os.path.join(PRIV, f'tag_audit_key_{args.only_audited_of}.csv')) if r['in_audit_packet'] == 'True'}
    sample = [c for c in C if c['comment_id'] in aud_ids]

# ---------- 質問（短い instructions、包含・除外は criteria に） ----------
TH = {k: v for k, v in CB['axes']['theme']['labels'].items() if k != 'T00_none'}; FN = CB['axes']['function']['labels']
ST = {k: v for k, v in CB['axes']['stage']['labels'].items() if k != 'S0_not_applicable'}; SC = CB['axes']['stage']['scope_labels']; OC = CB['axes']['stage']['outcome_confirmed']
STAGE_CRIT = {k: f"{v['name']}: {v['definition']}" for k, v in ST.items()}; SCOPE_CRIT = {k: f"{v['name']}: {v['definition']}" for k, v in SC.items()}
FN_CRIT = {k: f"{v['name']}: {v['definition']}" for k, v in FN.items()}
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

# ---------- 実行 ----------
SUFFIX = args.run_id + ('' if args.backend == 'typesafe' else f'_{args.model}')
out_path = os.path.join(PRIV, f'{PREFIX}_{SUFFIX}.jsonl'); done = {}
if os.path.exists(out_path):
    for ln in open(out_path, encoding='utf-8'): r = json.loads(ln); done[r['comment_id']] = r
results = []; t_all = time.time(); tok_in = tok_out = 0
with open(out_path, 'a', encoding='utf-8') as f:
    for i, c in enumerate(sample, 1):
        if c['comment_id'] in done: results.append(done[c['comment_id']]); continue
        q = questions(c); t0 = time.time()
        try: res = jev.call(state(c), q, args.model, timeout=120) if args.backend == 'typesafe' else call_workers_ai(state(c), q, args.model)
        except SystemExit as e: print('ERROR', c['comment_id'], e); continue
        dt = round(time.time() - t0, 2); A = res['answers']
        themes = {k: A[k]['noul'] for k in TH}
        tags = {k: ('tag' if p >= thr(k) else 'not' if p < TF else 'uncertain') for k, p in themes.items()}
        t00 = 'tag' if not any(v in ('tag', 'uncertain') for v in tags.values()) else 'not'
        rec = {'comment_id': c['comment_id'], 'run_id': args.run_id, 'backend': args.backend, 'codebook_version': CB['version'], 'theme_threshold': TT, 'theme_threshold_per_theme': PER, 'model_requested': args.model, 'model_returned': res.get('model'),
               'event_id': c['event_id'], 'institution_id': c['institution_id'], 'concept_id': c['concept_id'], 'level': c['level'], 'type': c['type'], 'review_type': c['review_type'], 'cycle': c['cycle'], 'standard_family': c['standard_family'],
               'themes': themes, 'theme_tags': {**tags, 'T00_none': t00},
               'function': ch(A['function']), 'multi_function': A['multi_function']['noul'], 'secondary_function': ch(A['secondary_function']),
               'observed_stage': ch(A['observed_stage']), 'observed_scope': ch(A['observed_scope']), 'outcome_confirmed': A['outcome_confirmed']['noul'],
               'requested_stage': ch(A['requested_stage']) if 'requested_stage' in A else {'choice': 'S0_not_applicable', 'confidence': None, 'probabilities': None},
               'requested_scope': ch(A['requested_scope']) if 'requested_scope' in A else {'choice': 'S0_not_applicable', 'confidence': None, 'probabilities': None},
               'usage': res.get('usage'), 'seconds': dt, 'called_at': datetime.datetime.now().isoformat(timespec='seconds')}
        u = res.get('usage') or {}; tok_in += u.get('input_tokens', 0) or 0; tok_out += u.get('output_tokens', 0) or 0
        f.write(json.dumps(rec, ensure_ascii=False) + '\n'); f.flush(); results.append(rec)
        print(f"{i}/{len(sample)} {c['comment_id']} {dt}s tags={[k.split('_')[0] for k, v in rec['theme_tags'].items() if v == 'tag']} fn={rec['function']['choice'].split('_')[0]} obs={rec['observed_stage']['choice'].split('_')[0]}", flush=True)
        time.sleep(0.15)
elapsed = round(time.time() - t_all, 1)
with open(os.path.join(PRIV, f'tag_pilot_sample_{SUFFIX}.csv'), 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f); w.writerow(['comment_id', 'institution', 'review_type', 'cycle', 'standard_family', 'level', 'type', 'concept_id'])
    for c in sample: w.writerow([c['comment_id'], INST[c['institution_id']], c['review_type'], c['cycle'], c['standard_family'], c['level'], c['type'], c['concept_id']])

# ---------- 監査パケット（答えなし）と鍵 ----------
R = {r['comment_id']: r for r in results}
unc = [c for c in sample if c['comment_id'] in R and 'uncertain' in R[c['comment_id']]['theme_tags'].values()]
rest = [c for c in sample if c['comment_id'] in R and c not in unc]
rng2 = random.Random(args.seed + 1); rng2.shuffle(unc); rng2.shuffle(rest)
n_unc = min(len(unc), args.audit_n // 2); audit = unc[:n_unc] + rest[:args.audit_n - n_unc]
audit.sort(key=lambda c: (c['type'], c['level'], c['concept_id']))
md = [f'# タグ付け監査パケット {args.run_id}（{CB["version"]}、Jev の答えは含まない）', '', f'run_id: {args.run_id} / 件数 {len(audit)} / 作成 {datetime.datetime.now().date()}', '',
      '各コメントについて判定してください: (A) テーマ（複数可。T01〜T13、T10 は T10a/T10b。どれも満たさなければ T00）、(B) 主機能（F1〜F9）、複合機能の有無（あり/なし）と副機能（F1〜F9 または なし）、'
      '(C) observed_stage（D1〜D4 / 記載なし / 段階決定不能）、observed_scope（一部明示/全対象明示/不明）、成果確認（明示/なし）、(D) requested_stage（D1〜D4 / 記載なし / 段階決定不能。特色ある点は該当なし）、requested_scope。', '',
      '## コードブック定義（v1）', '']
for k, v in CB['axes']['theme']['labels'].items():
    md.append(f"- **{k.split('_')[0]} {v['name']}**: {v['definition']}" + (f" 含む: {v['include']} 含まない: {v['exclude']}" if 'include' in v else ''))
md.append(''); md.append('テーマ規則: ' + ' / '.join(CB['axes']['theme']['rules']))
md.append(''); md.append('主機能: ' + ' / '.join(f"{k.split('_')[0]}={v['name']}（{v['definition']}）" for k, v in FN.items())); md.append('機能規則: ' + ' / '.join(CB['axes']['function']['rules']))
md.append(''); md.append('段階: ' + ' / '.join(f"{k.split('_')[0]}={v['name']}（{v['definition']}）" for k, v in CB['axes']['stage']['labels'].items()))
md.append('展開範囲: ' + ' / '.join(f"{v['name']}（{v['definition']}）" for v in SC.values()) + f"。成果確認: {OC['definition']}"); md.append('段階規則: ' + ' / '.join(CB['axes']['stage']['rules']))
md.append(''); md.append('## コメント'); md.append('')
md.append('| # | comment_id | 下位領域 | 水準 | 種別 | 本文 | テーマ | 主機能 | 複合/副機能 | observed | obs範囲 | 成果確認 | requested | req範囲 |'); md.append('|---|---|---|---|---|---|---|---|---|---|---|---|---|---|')
for i, c in enumerate(audit, 1):
    md.append(f"| {i} | {c['comment_id']} | {c['concept_id']} {CONCEPT.get(c['concept_id'], '')} | {c['level']} | {c['type']} | {TEXT[c['comment_id']].replace('|', '｜')} |  |  |  |  |  |  |  |  |")
if not args.no_packet: open(os.path.join(PRIV, f'tag_audit_packet_{SUFFIX}.md'), 'w', encoding='utf-8').write('\n'.join(md) + '\n')
with open(os.path.join(PRIV, f'tag_audit_key_{SUFFIX}.csv'), 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f); w.writerow(['comment_id', 'in_audit_packet', 'theme_tags', 'uncertain_themes', 'theme_probabilities', 'theme_threshold', 'function', 'function_confidence', 'multi_function_p', 'secondary_function', 'secondary_confidence',
                                   'observed_stage', 'observed_confidence', 'observed_scope', 'outcome_confirmed_p', 'requested_stage', 'requested_confidence', 'requested_scope', 'model_returned', 'run_id', 'codebook_version'])
    aud = {c['comment_id'] for c in audit}
    for cid, r in R.items():
        w.writerow([cid, cid in aud, ';'.join(k for k, v in r['theme_tags'].items() if v == 'tag'), ';'.join(k for k, v in r['theme_tags'].items() if v == 'uncertain'), json.dumps(r['themes']), r['theme_threshold'],
                    r['function']['choice'], r['function']['confidence'], r['multi_function'], r['secondary_function']['choice'], r['secondary_function']['confidence'],
                    r['observed_stage']['choice'], r['observed_stage']['confidence'], r['observed_scope']['choice'], r['outcome_confirmed'], r['requested_stage']['choice'], r['requested_stage']['confidence'], r['requested_scope']['choice'], r['model_returned'], r['run_id'], r['codebook_version']])

# ---------- 要約 ----------
n = len(results); allk = list(TH) + ['T00_none']
summ = {'run_id': args.run_id, 'codebook': CB['version'], 'theme_threshold': TT, 'theme_threshold_per_theme': PER, 'n_sampled': len(sample), 'n_judged': n, 'excluded_from_prior_runs': len(excl), 'model_returned': sorted({r['model_returned'] for r in results}),
        'elapsed_s_this_run': elapsed, 'tokens_this_run': {'input': tok_in, 'output': tok_out}, 'tokens_per_comment_all': {'input': round(sum((r['usage'] or {}).get('input_tokens', 0) for r in results) / n), 'output': round(sum((r['usage'] or {}).get('output_tokens', 0) for r in results) / n)},
        'mean_seconds_per_call': round(sum(r['seconds'] for r in results) / n, 2), 'strata': len(by), 'institutions_in_sample': len({c['institution_id'] for c in sample}),
        'theme_tag_rate': {k.split('_')[0]: round(sum(1 for r in results if r['theme_tags'][k] == 'tag') / n, 3) for k in allk},
        'theme_uncertain_rate': {k.split('_')[0]: round(sum(1 for r in results if r['theme_tags'][k] == 'uncertain') / n, 3) for k in TH},
        'tags_per_comment_excl_T00': dict(collections.Counter(sum(1 for k, v in r['theme_tags'].items() if v == 'tag' and k != 'T00_none') for r in results)),
        'function': dict(collections.Counter(r['function']['choice'] for r in results)), 'function_low_conf(<0.6)': sum(1 for r in results if (r['function']['confidence'] or 0) < 0.6),
        'multi_function(p>=0.5)': sum(1 for r in results if r['multi_function'] >= 0.5), 'secondary_function': dict(collections.Counter(r['secondary_function']['choice'] for r in results)),
        'observed_stage': dict(collections.Counter(r['observed_stage']['choice'] for r in results)), 'observed_low_conf(<0.6)': sum(1 for r in results if (r['observed_stage']['confidence'] or 0) < 0.6),
        'observed_scope': dict(collections.Counter(r['observed_scope']['choice'] for r in results)), 'outcome_confirmed(p>=0.5)': sum(1 for r in results if r['outcome_confirmed'] >= 0.5),
        'requested_stage': dict(collections.Counter(r['requested_stage']['choice'] for r in results)), 'requested_low_conf(<0.6)': sum(1 for r in results if r['requested_stage']['confidence'] is not None and r['requested_stage']['confidence'] < 0.6),
        'requested_scope': dict(collections.Counter(r['requested_scope']['choice'] for r in results)), 'audit_packet': {'n': len(audit), 'with_uncertain': n_unc}}
summ['backend'] = args.backend; summ['model_requested'] = args.model
json.dump(summ, open(os.path.join(PRIV, f'{PREFIX}_{SUFFIX}_summary.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(json.dumps(summ, ensure_ascii=False, indent=1))
