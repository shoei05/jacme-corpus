"""Jev（TypeSafe）と Clef（Workers AI）のフラグ判定を比較する。両方の flag_judgments_*.csv がそろってから使う。
出力: canonical/private/flag_model_comparison.csv と要約（一致率、閾値写像後の一致、確率の差）。"""
import csv, json, os, sys, collections
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRIV = os.path.join(ROOT, 'canonical', 'private')
TT, TF = 0.8, 0.2
def rd(p):
    if not os.path.exists(p): sys.exit(f'{p} が無い。scripts/14_flags_jev.py を該当バックエンドで実行してから使う')
    with open(p, encoding='utf-8') as f: return {r['doc_id']: r for r in csv.DictReader(f)}
A = rd(os.path.join(PRIV, 'flag_judgments_jev.csv')); B = rd(os.path.join(PRIV, 'flag_judgments_clef.csv'))
flag = lambda p: 'true' if float(p) >= TT else ('false' if float(p) <= TF else 'unknown')
rows = []; agree = collections.Counter(); n = 0
for doc in sorted(set(A) & set(B)):
    a, b = A[doc], B[doc]; n += 1
    r = {'doc_id': doc, 'model_a': a['model_returned'], 'model_b': b['model_returned']}
    for q in ('retrospective', 'mixed'):
        pa, pb = float(a[f'p_{q}']), float(b[f'p_{q}'])
        r.update({f'p_{q}_a': pa, f'p_{q}_b': pb, f'flag_{q}_a': flag(pa), f'flag_{q}_b': flag(pb), f'absdiff_{q}': round(abs(pa - pb), 3)})
        agree[q] += flag(pa) == flag(pb)
    r.update({'which_a': a['which_choice'], 'which_b': b['which_choice']}); agree['which'] += a['which_choice'] == b['which_choice']
    rows.append(r)
if not rows: sys.exit('共通の doc_id が無い')
with open(os.path.join(PRIV, 'flag_model_comparison.csv'), 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
print(json.dumps({'n_common': n, 'flag_agreement': {k: f'{v}/{n}' for k, v in agree.items()},
                  'mean_absdiff': {q: round(sum(r[f'absdiff_{q}'] for r in rows) / n, 3) for q in ('retrospective', 'mixed')},
                  'disagreements': [r['doc_id'] for r in rows if any(r[f'flag_{q}_a'] != r[f'flag_{q}_b'] for q in ('retrospective', 'mixed'))]}, ensure_ascii=False, indent=1))
