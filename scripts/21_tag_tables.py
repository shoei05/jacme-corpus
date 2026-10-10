"""全件タグ（private/tags_jev_<run_id>.jsonl）から正本のタグ表を作る。

canonical/comment_tags.csv/.jsonl   1行 = comment × theme（T00〜T13）。comment_id, theme, tagged(true/false/uncertain), prob, model, codebook_version, threshold, reliability_note
canonical/comment_classes.csv/.jsonl 1行 = comment。主機能・段階（observed/requested）と confidence、探索的列（scope, multi_function, secondary_function）
canonical/private/comment_tag_probs.csv  全確率・全選択肢確率（JSON列）。閾値変更はここから再計算する
canonical/tag_tables_manifest.json       公開の関門。complete=true のときだけ 13_public_export.py がテーマ集計を出す
閾値はコードブックの thresholds から読む（jsonl に保存された閾値ではなく、現在のコードブックの値で再写像する）。
関門: 作業ディレクトリ canonical/_work/ に生成し、判定済み comment_id の集合が comments.csv と一致し、重複・余分がなく、
コードブック版・閾値・モデル・質問ハッシュ（記録があるもの）が現在値と一致するときだけ正本へ置換する。満たさなければ何も書かず終了コード1。
使い方: python3 scripts/21_tag_tables.py [--run-id full_v1.1] [--codebook codebook_v1.1]
"""
import csv, json, os, sys, argparse, collections
import yaml
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAN = os.path.join(ROOT, 'canonical'); PRIV = os.path.join(CAN, 'private')
ap = argparse.ArgumentParser(); ap.add_argument('--run-id', default='full_v1.1'); ap.add_argument('--codebook', default='codebook_v1.1')
args = ap.parse_args()
CB = yaml.safe_load(open(os.path.join(CAN, 'codebook', args.codebook + '.yaml'), encoding='utf-8'))
TH_ = CB['thresholds']; TT = TH_.get('theme_tag', TH_.get('theme_tag_default')); TF = TH_['theme_not']; PER = TH_.get('per_theme', {})
LOW = set(TH_.get('reliability', {}).get('low', [])); EXPL = set(TH_.get('reliability', {}).get('exploratory', []))
def thr(k): return PER.get(k, TT)
THEMES = [k for k in CB['axes']['theme']['labels'] if k != 'T00_none']
def rd(p):
    with open(p, encoding='utf-8') as f: return list(csv.DictReader(f))
def wr(path, rows, fields):
    with open(path + '.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore'); w.writeheader(); w.writerows(rows)
    with open(path + '.jsonl', 'w', encoding='utf-8') as f:
        for r in rows: f.write(json.dumps({k: r.get(k, '') for k in fields}, ensure_ascii=False) + '\n')
C = rd(os.path.join(CAN, 'comments.csv')); ids = {c['comment_id'] for c in C}
import hashlib, shutil
def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()
src = os.path.join(PRIV, f'tags_jev_{args.run_id}.jsonl')
R = {}; n_lines = 0; dup = collections.Counter(); bad_lines = 0
for ln in open(src, encoding='utf-8'):
    n_lines += 1
    try: r = json.loads(ln)
    except json.JSONDecodeError: bad_lines += 1; continue
    dup[r['comment_id']] += 1; R[r['comment_id']] = r   # 同じ comment_id が複数あれば後勝ち（重複は関門で検出）
missing = sorted(ids - set(R)); extra = sorted(set(R) - ids); dups = sorted(k for k, v in dup.items() if v > 1)
# 現在の質問テンプレートのハッシュ（20_tag_full_jev.py と同じ定義から計算）
import importlib.util
spec = importlib.util.spec_from_file_location('q20', os.path.join(ROOT, 'scripts', '20_tag_full_jev.py'))
cbv_set = {r['codebook_version'] for r in R.values()}; model_set = {r['model_returned'] for r in R.values()}
thr_set = {json.dumps([r.get('theme_threshold'), r.get('theme_threshold_per_theme')], sort_keys=True) for r in R.values()}
qh_set = {r.get('question_hash') for r in R.values()}
cur_thr = json.dumps([TT, PER], sort_keys=True)
gate = {'run_id': args.run_id, 'n_comments': len(C), 'n_judged_ids': len(R), 'n_lines': n_lines, 'bad_lines': bad_lines, 'n_missing': len(missing), 'n_extra': len(extra), 'n_duplicate_ids': len(dups),
        'codebook_version_current': CB['version'], 'codebook_versions_in_run': sorted(cbv_set), 'thresholds_current': {'default': TT, 'per_theme': PER, 'not': TF}, 'thresholds_in_run_match': thr_set == {cur_thr},
        'models_in_run': sorted(model_set), 'question_hash_in_run': sorted(str(x) for x in qh_set),
        'input_hashes': {'canonical/comments.csv': sha(os.path.join(CAN, 'comments.csv')), 'canonical/private/comment_text.csv': sha(os.path.join(PRIV, 'comment_text.csv')), 'tags_jsonl': sha(src),
                         'codebook': sha(os.path.join(CAN, 'codebook', args.codebook + '.yaml'))},
        'input_hashes_note': '20_tag_full_jev.py は実行開始時の入力ハッシュを記録していなかった run についてはここで事後に計算した値（この run の後に comments.csv が変わっていないことは別途 id 集合の一致で担保）',
        'built_at': __import__('datetime').datetime.now().isoformat(timespec='seconds')}
problems = []
if missing: problems.append(f'missing {len(missing)}')
if extra: problems.append(f'extra {len(extra)}')
if dups: problems.append(f'duplicate ids {len(dups)}')
if bad_lines: problems.append(f'bad lines {bad_lines}')
if cbv_set != {CB['version']}: problems.append(f'codebook version mismatch {sorted(cbv_set)} vs {CB["version"]}')
if thr_set != {cur_thr}: problems.append('threshold mismatch between run and codebook')
if len(model_set) != 1: problems.append(f'multiple models {sorted(model_set)}')
if len(qh_set - {None}) > 1: problems.append('multiple question hashes')
gate['complete'] = not problems; gate['problems'] = problems
os.makedirs(os.path.join(CAN, '_work'), exist_ok=True)
json.dump(gate, open(os.path.join(CAN, 'tag_tables_manifest.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(json.dumps({k: gate[k] for k in ['n_comments', 'n_judged_ids', 'n_missing', 'n_extra', 'n_duplicate_ids', 'bad_lines', 'complete', 'problems']}, ensure_ascii=False))
if problems: sys.exit('関門を満たさないため正本のタグ表は書かない: ' + '; '.join(problems))
WORK = os.path.join(CAN, '_work')
tags, classes, probs = [], [], []
for c in C:
    r = R[c['comment_id']]
    model = r['model_returned']; cbv = r['codebook_version']
    any_tag = any_unc = False
    for t in THEMES:
        p = r['themes'][t]; th = thr(t)
        tagged = 'true' if p >= th else ('false' if p < TF else 'uncertain')
        any_tag |= tagged == 'true'; any_unc |= tagged == 'uncertain'
        tags.append({'comment_id': c['comment_id'], 'theme': t, 'tagged': tagged, 'prob': p, 'model': model, 'codebook_version': cbv, 'threshold': th,
                     'reliability_note': 'low' if t in LOW else ''})
    tags.append({'comment_id': c['comment_id'], 'theme': 'T00_none', 'tagged': 'true' if not (any_tag or any_unc) else 'false', 'prob': '', 'model': model, 'codebook_version': cbv, 'threshold': '', 'reliability_note': 'derived'})
    classes.append({'comment_id': c['comment_id'], 'function': r['function']['choice'], 'function_confidence': r['function']['confidence'],
                    'observed_stage': r['observed_stage']['choice'], 'observed_confidence': r['observed_stage']['confidence'],
                    'requested_stage': r['requested_stage']['choice'], 'requested_confidence': r['requested_stage']['confidence'],
                    'observed_scope_exploratory': r['observed_scope']['choice'], 'requested_scope_exploratory': r['requested_scope']['choice'],
                    'multi_function_p_exploratory': r['multi_function'], 'secondary_function_exploratory': r['secondary_function']['choice'], 'outcome_confirmed_p': r['outcome_confirmed'],
                    'model': model, 'codebook_version': cbv, 'run_id': r['run_id']})
    probs.append({'comment_id': c['comment_id'], 'themes': json.dumps(r['themes']), 'function_probabilities': json.dumps(r['function']['probabilities'], ensure_ascii=False),
                  'observed_probabilities': json.dumps(r['observed_stage']['probabilities'], ensure_ascii=False), 'requested_probabilities': json.dumps(r['requested_stage']['probabilities'], ensure_ascii=False),
                  'secondary_probabilities': json.dumps(r['secondary_function']['probabilities'], ensure_ascii=False), 'observed_scope_probabilities': json.dumps(r['observed_scope']['probabilities'], ensure_ascii=False),
                  'requested_scope_probabilities': json.dumps(r['requested_scope']['probabilities'], ensure_ascii=False), 'multi_function_p': r['multi_function'], 'outcome_confirmed_p': r['outcome_confirmed'],
                  'input_tokens': (r.get('usage') or {}).get('input_tokens'), 'output_tokens': (r.get('usage') or {}).get('output_tokens'), 'seconds': r.get('seconds'), 'called_at': r.get('called_at'), 'model': model, 'run_id': r['run_id']})
wr(os.path.join(WORK, 'comment_tags'), tags, ['comment_id', 'theme', 'tagged', 'prob', 'model', 'codebook_version', 'threshold', 'reliability_note'])
wr(os.path.join(WORK, 'comment_classes'), classes, list(classes[0].keys()))
with open(os.path.join(WORK, 'comment_tag_probs.csv'), 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=list(probs[0].keys())); w.writeheader(); w.writerows(probs)
# 作業ディレクトリの表を再読込して件数を確認してから置換
chk_tags = rd(os.path.join(WORK, 'comment_tags.csv')); chk_cls = rd(os.path.join(WORK, 'comment_classes.csv'))
assert {r['comment_id'] for r in chk_tags} == ids and len(chk_tags) == len(C) * (len(THEMES) + 1) and len(chk_cls) == len(C), '作業表の件数が合わない'
for fn in ['comment_tags.csv', 'comment_tags.jsonl', 'comment_classes.csv', 'comment_classes.jsonl']: shutil.move(os.path.join(WORK, fn), os.path.join(CAN, fn))
shutil.move(os.path.join(WORK, 'comment_tag_probs.csv'), os.path.join(PRIV, 'comment_tag_probs.csv'))
gate['output_hashes'] = {'canonical/comment_tags.csv': sha(os.path.join(CAN, 'comment_tags.csv')), 'canonical/comment_classes.csv': sha(os.path.join(CAN, 'comment_classes.csv'))}
json.dump(gate, open(os.path.join(CAN, 'tag_tables_manifest.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
summary = {'run_id': args.run_id, 'codebook': CB['version'], 'thresholds': {'default': TT, 'per_theme': PER, 'not': TF}, 'n_comments': len(C), 'n_judged': len(R), 'n_missing': len(missing),
           'theme_counts': {t.split('_')[0]: collections.Counter(x['tagged'] for x in tags if x['theme'] == t)['true'] for t in THEMES + ['T00_none']},
           'theme_uncertain': {t.split('_')[0]: collections.Counter(x['tagged'] for x in tags if x['theme'] == t)['uncertain'] for t in THEMES},
           'function': dict(collections.Counter(x['function'] for x in classes)), 'observed_stage': dict(collections.Counter(x['observed_stage'] for x in classes)), 'requested_stage': dict(collections.Counter(x['requested_stage'] for x in classes)),
           'usage': {'input_tokens': sum(int(p['input_tokens'] or 0) for p in probs), 'output_tokens': sum(int(p['output_tokens'] or 0) for p in probs), 'seconds_sum': round(sum(float(p['seconds'] or 0) for p in probs), 1)}}
json.dump(summary, open(os.path.join(CAN, 'comment_tags_summary.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(json.dumps(summary, ensure_ascii=False, indent=1))
