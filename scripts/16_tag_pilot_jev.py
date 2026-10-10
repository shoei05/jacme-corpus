"""コメントの意味タグ付け試行（Jev）。codebook_v0 の 3軸（テーマ10・機能・実装段階）を、層化抽出した200コメントに付ける。
全コーパスには走らせない（--n で件数、--run-id で識別）。
出力（すべて private）:
  canonical/private/tags_jev_<run_id>.jsonl   1行1コメント。全確率、model_returned、codebook_version、run_id、所要秒
  canonical/private/tag_pilot_sample_<run_id>.csv  抽出した層と大学
  canonical/private/tag_audit_packet.md       外部監査者向け（Jev の答えを含めない）
  canonical/private/tag_audit_key.csv         comment_id → Jev の答え（後で突き合わせる）
使い方: zsh -lc 'python3 scripts/16_tag_pilot_jev.py --n 200 --run-id pilot01'
"""
import csv, json, os, sys, random, argparse, time, datetime, collections
import yaml
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAN = os.path.join(ROOT, 'canonical'); PRIV = os.path.join(CAN, 'private')
sys.path.insert(0, os.path.expanduser('~/.codex/skills/jev/scripts'))
import jev
ap = argparse.ArgumentParser(); ap.add_argument('--n', type=int, default=200); ap.add_argument('--run-id', default='pilot01'); ap.add_argument('--model', default='jev-latest')
ap.add_argument('--cap-per-institution', type=int, default=3); ap.add_argument('--audit-n', type=int, default=60); ap.add_argument('--seed', type=int, default=0)
args = ap.parse_args()
CB = yaml.safe_load(open(os.path.join(CAN, 'codebook', 'codebook_v0.yaml'), encoding='utf-8'))
TT, TF = CB['axes']['theme']['thresholds']['tag'], CB['axes']['theme']['thresholds']['not']
def rd(p):
    with open(p, encoding='utf-8') as f: return list(csv.DictReader(f))
C = rd(os.path.join(CAN, 'comments.csv')); TEXT = {r['comment_id']: r['text'] for r in rd(os.path.join(PRIV, 'comment_text.csv'))}
CONCEPT = {r['concept_id']: r['name'] for r in rd(os.path.join(CAN, 'concepts.csv'))}
INST = {r['institution_id']: r['name'] for r in rd(os.path.join(CAN, 'institutions.csv'))}

# ---------- 層化抽出（審査種別×巡、基準系列、水準、種別。大学ごとの上限あり） ----------
rng = random.Random(args.seed)
def stratum(c): return (c['review_type'] + (c['cycle'] or ''), c['standard_family'], c['level'], c['type'])
by = collections.defaultdict(list)
for c in C: by[stratum(c)].append(c)
for v in by.values(): rng.shuffle(v)
total = len(C); quota = {k: max(1, round(args.n * len(v) / total)) for k, v in by.items()}
# 四捨五入のずれを調整
while sum(quota.values()) > args.n:
    k = max(quota, key=lambda k: quota[k]); quota[k] -= 1
while sum(quota.values()) < args.n:
    k = max(by, key=lambda k: len(by[k]) / quota[k]); quota[k] += 1
inst_count = collections.Counter(); sample = []; chosen = set()
cap = args.cap_per_institution
while len(sample) < args.n and cap <= args.cap_per_institution + 3:   # 大学上限で埋まらなければ上限を1ずつ緩める
    for k, v in by.items():
        taken = sum(1 for c in sample if stratum(c) == k)
        for c in v:
            if taken >= quota[k] or len(sample) >= args.n: break
            if c['comment_id'] in chosen or inst_count[c['institution_id']] >= cap: continue
            sample.append(c); chosen.add(c['comment_id']); inst_count[c['institution_id']] += 1; taken += 1
    cap += 1
rng.shuffle(sample)

# ---------- 質問 ----------
TH = CB['axes']['theme']['labels']; FN = CB['axes']['function']['labels']; ST = CB['axes']['stage']['labels']
STAGE_CRIT = {k: f"{v['name']}: {v['definition']}" for k, v in ST.items() if k != 'S0_not_applicable'}
def questions(c):
    q = {}
    for k, v in TH.items():
        q[k] = {'type': 'noul', 'instructions': f"Does this comment explicitly address the theme 「{v['name']}」? Definition: {v['definition']} Include: {v['include']} Exclude: {v['exclude']} "
                                                "Tag only when the comment itself deals with the theme, not merely because of its subarea."}
    q['function'] = {'type': 'choice', 'instructions': 'Which educational/organizational function does this comment mainly act on? If several, choose the one at the center of the praise or the request.',
                     'criteria': {k: f"{v['name']}: {v['definition']}" for k, v in FN.items()}}
    q['observed_stage'] = {'type': 'choice', 'instructions': 'What implementation stage does the comment describe as CURRENTLY existing at the school (the observed state)? Distinguish "a goal was set" (方針・設計) from "an outcome was measured and confirmed" (成果の確認).',
                           'criteria': STAGE_CRIT}
    if c['type'] != '特色ある点':
        q['requested_stage'] = {'type': 'choice', 'instructions': 'What implementation stage does the comment REQUEST the school to reach (the requested state)? Choose 不明 if the request gives no stage (e.g. "further enhance").',
                                'criteria': STAGE_CRIT}
    return q
def state(c):
    return {'comment_text': TEXT[c['comment_id']], 'subarea': f"{c['concept_id']} {CONCEPT.get(c['concept_id'], '')}", 'level': {'B': '基本的水準', 'Q': '質的向上のための水準'}[c['level']],
            'comment_type': c['type'], 'review_type': c['review_type'], 'unit': 'This is one comment from a JACME medical-education accreditation report. It is a single unit; judge the comment as written.'}

# ---------- 実行 ----------
out_path = os.path.join(PRIV, f'tags_jev_{args.run_id}.jsonl')
done = {}
if os.path.exists(out_path):
    for ln in open(out_path, encoding='utf-8'): r = json.loads(ln); done[r['comment_id']] = r
results = []; t_all = time.time(); tokens = 0
with open(out_path, 'a', encoding='utf-8') as f:
    for i, c in enumerate(sample, 1):
        if c['comment_id'] in done: results.append(done[c['comment_id']]); continue
        q = questions(c); t0 = time.time()
        try: res = jev.call(state(c), q, args.model, timeout=120)
        except SystemExit as e: print('ERROR', c['comment_id'], e); continue
        dt = round(time.time() - t0, 2); A = res['answers']
        themes = {k: A[k]['noul'] for k in TH}
        rec = {'comment_id': c['comment_id'], 'run_id': args.run_id, 'codebook_version': CB['version'], 'model_requested': args.model, 'model_returned': res.get('model'),
               'event_id': c['event_id'], 'institution_id': c['institution_id'], 'concept_id': c['concept_id'], 'level': c['level'], 'type': c['type'], 'review_type': c['review_type'], 'cycle': c['cycle'], 'standard_family': c['standard_family'],
               'themes': themes, 'theme_tags': {k: ('tag' if p >= TT else 'not' if p <= TF else 'uncertain') for k, p in themes.items()},
               'function': {'choice': A['function']['choice'], 'confidence': A['function'].get('confidence'), 'probabilities': A['function'].get('probabilities')},
               'observed_stage': {'choice': A['observed_stage']['choice'], 'confidence': A['observed_stage'].get('confidence'), 'probabilities': A['observed_stage'].get('probabilities')},
               'requested_stage': ({'choice': A['requested_stage']['choice'], 'confidence': A['requested_stage'].get('confidence'), 'probabilities': A['requested_stage'].get('probabilities')} if 'requested_stage' in A else {'choice': 'S0_not_applicable', 'confidence': None, 'probabilities': None}),
               'usage': res.get('usage'), 'seconds': dt, 'called_at': datetime.datetime.now().isoformat(timespec='seconds')}
        tokens += (res.get('usage') or {}).get('input_tokens', 0) or 0
        f.write(json.dumps(rec, ensure_ascii=False) + '\n'); f.flush(); results.append(rec)
        print(f"{i}/{len(sample)} {c['comment_id']} {dt}s tags={[k[:3] for k, v in rec['theme_tags'].items() if v == 'tag']} fn={rec['function']['choice']}", flush=True)
        time.sleep(0.15)
elapsed = round(time.time() - t_all, 1)

# ---------- 抽出表 ----------
with open(os.path.join(PRIV, f'tag_pilot_sample_{args.run_id}.csv'), 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f); w.writerow(['comment_id', 'institution', 'review_type', 'cycle', 'standard_family', 'level', 'type', 'concept_id'])
    for c in sample: w.writerow([c['comment_id'], INST[c['institution_id']], c['review_type'], c['cycle'], c['standard_family'], c['level'], c['type'], c['concept_id']])

# ---------- 監査パケット（Jev の答えなし）と鍵 ----------
R = {r['comment_id']: r for r in results}
unc = [c for c in sample if c['comment_id'] in R and 'uncertain' in R[c['comment_id']]['theme_tags'].values()]
rest = [c for c in sample if c['comment_id'] in R and c not in unc]
rng2 = random.Random(args.seed + 1); rng2.shuffle(unc); rng2.shuffle(rest)
n_unc = min(len(unc), args.audit_n // 2)
audit = unc[:n_unc] + rest[:args.audit_n - n_unc]
# 残りは層をまたいで散らす
audit.sort(key=lambda c: (c['type'], c['level'], c['concept_id']))
md = ['# タグ付け監査パケット（codebook v0、Jev の答えは含まない）', '', f'run_id: {args.run_id} / 件数 {len(audit)} / 作成 {datetime.datetime.now().date()}', '',
      '各コメントについて、(A) 該当する改革テーマ（複数可、T01〜T10、なしも可）、(B) 機能（F1〜F9、1つ）、(C) observed_stage（S1〜S8）、(D) requested_stage（S1〜S8。特色ある点は該当なし）を判定してください。', '',
      '## コードブック定義', '']
for k, v in TH.items(): md.append(f"- **{k} {v['name']}**: {v['definition']} 含む: {v['include']} 含まない: {v['exclude']}")
md.append(''); md.append('機能: ' + ' / '.join(f"{k}={v['name']}（{v['definition']}）" for k, v in FN.items()))
md.append(''); md.append('実装段階: ' + ' / '.join(f"{k}={v['name']}（{v['definition']}）" for k, v in ST.items()))
md.append(''); md.append(CB['axes']['stage']['rule'].strip()); md.append(''); md.append('## コメント'); md.append('')
md.append('| # | comment_id | 下位領域 | 水準 | 種別 | 本文 | テーマ | 機能 | observed | requested |'); md.append('|---|---|---|---|---|---|---|---|---|---|')
for i, c in enumerate(audit, 1):
    md.append(f"| {i} | {c['comment_id']} | {c['concept_id']} {CONCEPT.get(c['concept_id'], '')} | {c['level']} | {c['type']} | {TEXT[c['comment_id']].replace('|', '｜')} |  |  |  |  |")
open(os.path.join(PRIV, 'tag_audit_packet.md'), 'w', encoding='utf-8').write('\n'.join(md) + '\n')
with open(os.path.join(PRIV, 'tag_audit_key.csv'), 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f); w.writerow(['comment_id', 'in_audit_packet', 'theme_tags', 'uncertain_themes', 'theme_probabilities', 'function', 'function_confidence', 'observed_stage', 'observed_confidence', 'requested_stage', 'requested_confidence', 'model_returned', 'run_id'])
    aud = {c['comment_id'] for c in audit}
    for cid, r in R.items():
        w.writerow([cid, cid in aud, ';'.join(k for k, v in r['theme_tags'].items() if v == 'tag'), ';'.join(k for k, v in r['theme_tags'].items() if v == 'uncertain'), json.dumps(r['themes']),
                    r['function']['choice'], r['function']['confidence'], r['observed_stage']['choice'], r['observed_stage']['confidence'], r['requested_stage']['choice'], r['requested_stage']['confidence'], r['model_returned'], r['run_id']])

# ---------- 要約 ----------
n = len(results)
summ = {'run_id': args.run_id, 'n_sampled': len(sample), 'n_judged': n, 'model_returned': sorted({r['model_returned'] for r in results}), 'elapsed_s': elapsed, 'input_tokens_this_run': tokens,
        'mean_seconds_per_call': round(sum(r['seconds'] for r in results) / n, 2), 'strata': len(by), 'institutions_in_sample': len({c['institution_id'] for c in sample}),
        'theme_tag_rate': {k: round(sum(1 for r in results if r['theme_tags'][k] == 'tag') / n, 3) for k in TH},
        'theme_uncertain_rate': {k: round(sum(1 for r in results if r['theme_tags'][k] == 'uncertain') / n, 3) for k in TH},
        'tags_per_comment': dict(collections.Counter(sum(1 for v in r['theme_tags'].values() if v == 'tag') for r in results)),
        'function': dict(collections.Counter(r['function']['choice'] for r in results)), 'function_low_conf(<0.6)': sum(1 for r in results if (r['function']['confidence'] or 0) < 0.6),
        'observed_stage': dict(collections.Counter(r['observed_stage']['choice'] for r in results)), 'observed_low_conf(<0.6)': sum(1 for r in results if (r['observed_stage']['confidence'] or 0) < 0.6),
        'requested_stage': dict(collections.Counter(r['requested_stage']['choice'] for r in results)), 'requested_low_conf(<0.6)': sum(1 for r in results if r['requested_stage']['confidence'] is not None and r['requested_stage']['confidence'] < 0.6),
        'audit_packet': {'n': len(audit), 'with_uncertain': n_unc}}
json.dump(summ, open(os.path.join(PRIV, f'tags_jev_{args.run_id}_summary.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(json.dumps(summ, ensure_ascii=False, indent=1))
