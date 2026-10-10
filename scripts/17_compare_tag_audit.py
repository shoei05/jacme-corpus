"""外部監査（ChatGPT 等の盲検判定）と Jev のタグを比較する。

入力:
  canonical/private/tag_audit_chatgpt_<run_id>.csv  列: #, comment_id, テーマ, 機能, observed, requested, 備考
      テーマは "T03;T04"（区切りは ; , 、 / 空白）または "なし"。コードは接尾辞あり/なし（T03 / T03_assessment_feedback）どちらでもよい。
      機能・段階も同様（F4 / F4_program_evaluation_ir、S3 / S3_implementation、該当なし / S0）。
  canonical/private/tag_audit_key.csv（scripts/16 の出力。Jev ≥0.8 を付与、0.2〜0.8 を不確実とみなす）
出力:
  canonical/private/tag_audit_comparison_<run_id>.csv  テーマ別・機能・段階の指標
  canonical/private/tag_audit_comparison_<run_id>.md   指標、混同表、不一致一覧
使い方: python3 scripts/17_compare_tag_audit.py [--run-id pilot01] [--ref canonical/private/tag_audit_chatgpt_pilot01.csv]
"""
import csv, json, os, re, sys, argparse, collections
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRIV = os.path.join(ROOT, 'canonical', 'private')
ap = argparse.ArgumentParser(); ap.add_argument('--run-id', default='pilot01'); ap.add_argument('--ref', default=None)
ap.add_argument('--codebook', default=None, help='codebook_v0 / codebook_v1（既定: pilot01 は v0、それ以外は v1）'); ap.add_argument('--key', default=None, help='tag_audit_key_<run_id>.csv（pilot01 は tag_audit_key.csv）'); ap.add_argument('--out-suffix', default='', help='出力名の接尾辞（例 _clef-flash）'); ap.add_argument('--label', default='Jev', help='比較対象の名前（表示用）')
args = ap.parse_args()
REF = args.ref or os.path.join(PRIV, f'tag_audit_chatgpt_{args.run_id}.csv')
if not os.path.exists(REF): sys.exit(f'{REF} が無い。監査結果のCSVを置いてから実行する')
KEY = args.key or os.path.join(PRIV, 'tag_audit_key.csv' if args.run_id == 'pilot01' else f'tag_audit_key_{args.run_id}.csv')
CBNAME = args.codebook or ('codebook_v0' if args.run_id == 'pilot01' else 'codebook_v1')
def rd(p):
    with open(p, encoding='utf-8-sig') as f: return list(csv.DictReader(f))
import yaml
CB = yaml.safe_load(open(os.path.join(ROOT, 'canonical', 'codebook', CBNAME + '.yaml'), encoding='utf-8'))
THEMES = list(CB['axes']['theme']['labels']); FUNCS = list(CB['axes']['function']['labels']); STAGES = list(CB['axes']['stage']['labels'])
NAME = {**{k: v['name'] for k, v in CB['axes']['theme']['labels'].items()}, **{k: v['name'] for k, v in CB['axes']['function']['labels'].items()}, **{k: v['name'] for k, v in CB['axes']['stage']['labels'].items()}}
PREFIX = {k.split('_')[0]: k for k in THEMES + FUNCS + STAGES}
BY_NAME = {v: k for k, v in NAME.items()}
NONE_WORDS = {'', 'なし', '無し', 'none', '-', '—', '該当なし', 'n/a', 'na'}

def norm_code(tok):
    """'T03' / 'T03_assessment_feedback' / '学生評価とフィードバック' / '該当なし' を正規コードへ。"""
    t = tok.strip().strip('"').replace('＿', '_')
    if t.lower() in NONE_WORDS: return None
    if t in PREFIX.values(): return t
    m = re.match(r'^([TFSDN])\s*0?(\d{1,2})\s*([ab])?', t, re.I)
    if m:
        code = (f'{m[1].upper()}{int(m[2]):02d}' if m[1].upper() == 'T' else f'{m[1].upper()}{int(m[2])}') + (m[3].lower() if m[3] else '')
        if code in PREFIX: return PREFIX[code]
    if t in ('記載なし',): return PREFIX.get('N0')
    if t in ('段階決定不能', '決定不能'): return PREFIX.get('N1')
    if t in BY_NAME: return BY_NAME[t]
    for name, k in BY_NAME.items():
        if name and name in t: return k
    return f'UNPARSED:{t}'
def split_codes(cell):
    toks = [x for x in re.split(r'[;,、/／\s]+', cell or '') if x]
    out = [norm_code(x) for x in toks]
    return [x for x in out if x]
def find_col(row, *cands):
    for c in row:
        if c and c.strip().lstrip('﻿') in cands: return c
    return None

ref_rows = rd(REF); key = {r['comment_id']: r for r in rd(KEY)}
if not ref_rows: sys.exit('監査CSVが空')
r0 = ref_rows[0]
C_ID = find_col(r0, 'comment_id'); C_TH = find_col(r0, 'テーマ', 'theme', 'themes'); C_FN = find_col(r0, '機能', '主機能', 'function')
C_MF = find_col(r0, '複合/副機能', '複合・副機能', 'multi_secondary'); C_OS = find_col(r0, 'obs範囲', 'observed_scope'); C_RS = find_col(r0, 'req範囲', 'requested_scope'); C_OC = find_col(r0, '成果確認', 'outcome_confirmed')
C_OB = find_col(r0, 'observed', 'observed_stage'); C_RQ = find_col(r0, 'requested', 'requested_stage'); C_NOTE = find_col(r0, '備考', 'note')
if not C_ID: sys.exit(f'comment_id 列が無い: {list(r0)}')
ref = {}; unparsed = []
for r in ref_rows:
    cid = r[C_ID].strip()
    if cid not in key: unparsed.append((cid, 'not_in_key')); continue
    th = split_codes(r.get(C_TH, '')) if C_TH else []
    fn = split_codes(r.get(C_FN, '')) if C_FN else []
    ob = split_codes(r.get(C_OB, '')) if C_OB else []
    rq = split_codes(r.get(C_RQ, '')) if C_RQ else []
    for x in th + fn + ob + rq:
        if x.startswith('UNPARSED'): unparsed.append((cid, x))
    th_set = {x for x in th if x in THEMES}
    if not th_set and 'T00_none' in THEMES: th_set = {'T00_none'}
    ref[cid] = {'themes': th_set, 'function': next((x for x in fn if x in FUNCS), None),
                'observed': next((x for x in ob if x in STAGES), None), 'requested': next((x for x in rq if x in STAGES), 'S0_not_applicable' if (C_RQ and r.get(C_RQ, '').strip() in NONE_WORDS | {'該当なし'}) else None),
                'note': r.get(C_NOTE, '') if C_NOTE else ''}
    SCOPE_MAP = {'一部明示': 'P1_partial_explicit', '全対象明示': 'P2_all_explicit', '不明': 'P9_unknown', '該当なし': 'S0_not_applicable', 'P1': 'P1_partial_explicit', 'P2': 'P2_all_explicit', 'P9': 'P9_unknown'}
    mf = (r.get(C_MF, '') if C_MF else '').strip()
    if mf:
        a, _, b = mf.partition('/'); ref[cid]['multi'] = a.strip() in ('あり', 'true', 'yes', '有'); sec = split_codes(b) if b else []
        ref[cid]['secondary'] = next((x for x in sec if x in FUNCS), 'none')
    ref[cid]['observed_scope'] = SCOPE_MAP.get((r.get(C_OS, '') if C_OS else '').strip()) if C_OS else None
    ref[cid]['requested_scope'] = SCOPE_MAP.get((r.get(C_RS, '') if C_RS else '').strip()) if C_RS else None
    oc = (r.get(C_OC, '') if C_OC else '').strip(); ref[cid]['outcome'] = (True if oc in ('明示', 'あり', 'true') else False if oc in ('なし', 'false', '無') else None) if C_OC else None
ids = sorted(ref)
jev = {}
for cid in ids:
    k = key[cid]
    jev[cid] = {'tag': set(filter(None, k['theme_tags'].split(';'))), 'unc': set(filter(None, k['uncertain_themes'].split(';'))), 'p': json.loads(k['theme_probabilities']),
                'function': k['function'], 'observed': k['observed_stage'], 'requested': k['requested_stage'],
                'multi': (float(k['multi_function_p']) >= 0.5) if k.get('multi_function_p') not in (None, '') else None, 'secondary': k.get('secondary_function'),
                'observed_scope': k.get('observed_scope'), 'requested_scope': k.get('requested_scope'),
                'outcome': (float(k['outcome_confirmed_p']) >= 0.5) if k.get('outcome_confirmed_p') not in (None, '') else None}

def kappa(a, b, labels):
    """Cohen's κ。両者とも1カテゴリしか使わない（pe=1）場合は定義できないので None（NA）。"""
    n = len(a); po = sum(1 for x, y in zip(a, b) if x == y) / n if n else 0
    pe = sum((a.count(l) / n) * (b.count(l) / n) for l in labels) if n else 0
    return None if pe >= 1 - 1e-12 else (po - pe) / (1 - pe)
def kfmt(k): return 'NA' if k is None else f'{k:.2f}'
rows = []
md = [f'# タグ監査の比較 {args.run_id}{args.out_suffix}（参照 vs {args.label}）', '', f'参照: {os.path.relpath(REF, ROOT)}（外部監査、盲検） / Jev: {os.path.basename(KEY)}（閾値はコードブックどおり） / n={len(ids)}', '']
if unparsed: md += ['## 読めなかったコード', ''] + [f'- {c}: {x}' for c, x in unparsed] + ['']
# ---------- テーマ ----------
THR = key[ids[0]].get('theme_threshold', '0.8') if ids else '0.8'
md += [f'## テーマ（Jev ≥{THR} を付与として参照と比較。T00 は参照・Jev とも「テーマなし」で比較）', '', '| テーマ | 参照+ | Jev+ | TP | FP | FN | 一致率 | κ | 適合率 | 再現率 | F1 | Jev不確実のうち参照+ / 参照− |', '|---|---|---|---|---|---|---|---|---|---|---|---|']
for t in THEMES:
    a = [t in ref[c]['themes'] for c in ids]; b = [t in jev[c]['tag'] for c in ids]
    tp = sum(x and y for x, y in zip(a, b)); fp = sum((not x) and y for x, y in zip(a, b)); fn = sum(x and (not y) for x, y in zip(a, b)); tn = len(ids) - tp - fp - fn
    acc = (tp + tn) / len(ids); kp = kappa(a, b, [True, False])
    prec = tp / (tp + fp) if tp + fp else float('nan'); rec = tp / (tp + fn) if tp + fn else float('nan'); f1 = 2 * prec * rec / (prec + rec) if prec == prec and rec == rec and prec + rec else float('nan')
    unc_pos = sum(1 for c in ids if t in jev[c]['unc'] and t in ref[c]['themes']); unc_neg = sum(1 for c in ids if t in jev[c]['unc'] and t not in ref[c]['themes'])
    rows.append({'axis': 'theme', 'code': t, 'name': NAME[t], 'ref_pos': sum(a), 'jev_pos': sum(b), 'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn, 'accuracy': round(acc, 3), 'kappa': round(kp, 3) if kp is not None else 'NA',
                 'precision': round(prec, 3) if prec == prec else '', 'recall': round(rec, 3) if rec == rec else '', 'f1': round(f1, 3) if f1 == f1 else '', 'jev_uncertain_ref_pos': unc_pos, 'jev_uncertain_ref_neg': unc_neg})
    f = lambda v: '' if v != v else f'{v:.2f}'
    md.append(f'| {t.split("_")[0]} {NAME[t]} | {sum(a)} | {sum(b)} | {tp} | {fp} | {fn} | {acc:.2f} | {kfmt(kp)}{"（陽性0件）" if sum(a) == 0 and sum(b) == 0 else ""} | {f(prec)} | {f(rec)} | {f(f1)} | {unc_pos} / {unc_neg} |')
# T00 は不確実帯の感度分析から除く
# 不確実帯を付与に含めた場合（感度分析）
md += ['', '不確実（0.2〜0.8）も付与とみなした場合:', '', '| テーマ | Jev+ | TP | FP | FN | 適合率 | 再現率 |', '|---|---|---|---|---|---|---|']
for t in THEMES:
    a = [t in ref[c]['themes'] for c in ids]; b = [t in jev[c]['tag'] or t in jev[c]['unc'] for c in ids]
    tp = sum(x and y for x, y in zip(a, b)); fp = sum((not x) and y for x, y in zip(a, b)); fn = sum(x and (not y) for x, y in zip(a, b))
    md.append(f'| {t.split("_")[0]} | {sum(b)} | {tp} | {fp} | {fn} | {tp/(tp+fp):.2f} | {tp/(tp+fn):.2f} |' if (tp + fp) and (tp + fn) else f'| {t.split("_")[0]} | {sum(b)} | {tp} | {fp} | {fn} |  |  |')
# ---------- 機能・段階 ----------
def single(axis, labels, title, ref_key, jev_key, subset=None):
    sub = [c for c in ids if (subset is None or subset(c)) and ref[c][ref_key]]
    if not sub: md.extend(['', f'## {title}', '', '参照に値がない']); return
    a = [ref[c][ref_key] for c in sub]; b = [jev[c][jev_key] for c in sub]
    acc = sum(x == y for x, y in zip(a, b)) / len(sub); kp = kappa(a, b, labels)
    single_cat = len(set(a)) == 1 and set(a) == set(b)
    rows.append({'axis': axis, 'code': 'ALL', 'name': title, 'ref_pos': len(sub), 'jev_pos': len(sub), 'accuracy': round(acc, 3), 'kappa': round(kp, 3) if kp is not None else 'NA'})
    line = f'一致率 {acc:.2f}、κ {kfmt(kp)}' + ('（両者とも1カテゴリのみ。陽性0件）' if single_cat else '')
    # 段階は「記載なし」「該当なし」を除いた一致も出す（参照が N0/S0 の件を除く）
    EXCL = {'N0_not_stated', 'S0_not_applicable', 'S8_unknown'}
    if axis in ('observed_stage', 'requested_stage'):
        sub2 = [(x, y) for x, y in zip(a, b) if x not in EXCL]
        if sub2:
            acc2 = sum(x == y for x, y in sub2) / len(sub2); kp2 = kappa([x for x, _ in sub2], [y for _, y in sub2], labels)
            line += f'。参照が 記載なし/該当なし の件を除くと 一致率 {acc2:.2f}（{sum(x == y for x, y in sub2)}/{len(sub2)}）、κ {kfmt(kp2)}'
            rows.append({'axis': axis, 'code': 'ALL_excl_N0_S0', 'name': title + '（N0/S0 除外）', 'ref_pos': len(sub2), 'jev_pos': len(sub2), 'accuracy': round(acc2, 3), 'kappa': round(kp2, 3) if kp2 is not None else 'NA'})
    md.extend(['', f'## {title}（n={len(sub)}）', '', line, '', '混同表（行=参照、列=Jev）', ''])
    used = [l for l in labels if l in a or l in b]
    md.append('| 参照＼Jev | ' + ' | '.join(u.split('_')[0] for u in used) + ' |'); md.append('|---|' + '---|' * len(used))
    for la in used:
        md.append(f'| {la.split("_")[0]} {NAME.get(la, "")} | ' + ' | '.join(str(sum(1 for x, y in zip(a, b) if x == la and y == lb)) for lb in used) + ' |')
    for l in used:
        tp = sum(1 for x, y in zip(a, b) if x == l and y == l); rp = a.count(l); jp = b.count(l)
        rows.append({'axis': axis, 'code': l, 'name': NAME.get(l, ''), 'ref_pos': rp, 'jev_pos': jp, 'tp': tp, 'fp': jp - tp, 'fn': rp - tp,
                     'precision': round(tp / jp, 3) if jp else '', 'recall': round(tp / rp, 3) if rp else ''})
single('function', FUNCS, '機能', 'function', 'function')
single('observed_stage', STAGES, 'observed_stage', 'observed', 'observed')
single('requested_stage', STAGES, 'requested_stage', 'requested', 'requested')
SCOPES = ['P1_partial_explicit', 'P2_all_explicit', 'P9_unknown', 'S0_not_applicable']
NAME.update({'P1_partial_explicit': '一部明示', 'P2_all_explicit': '全対象明示', 'P9_unknown': '不明', 'none': '副機能なし', 'True': 'あり', 'False': 'なし'})
if any(ref[c].get('multi') is not None for c in ids) and any(jev[c]['multi'] is not None for c in ids):
    for c in ids: ref[c]['multi_s'] = str(ref[c].get('multi')); jev[c]['multi_s'] = str(jev[c]['multi'])
    single('multi_function', ['True', 'False'], '複合機能（Jev p≥0.5 = あり）', 'multi_s', 'multi_s')
    single('secondary_function', FUNCS + ['none'], '副機能', 'secondary', 'secondary')
if any(ref[c].get('observed_scope') for c in ids): single('observed_scope', SCOPES, 'observed_scope（展開範囲）', 'observed_scope', 'observed_scope')
if any(ref[c].get('requested_scope') for c in ids):
    single('requested_scope', SCOPES, 'requested_scope（要求を含む種別のみ）', 'requested_scope', 'requested_scope', subset=lambda c: ref[c]['requested'] not in (None, 'S0_not_applicable'))
if any(ref[c].get('outcome') is not None for c in ids):
    for c in ids: ref[c]['outcome_s'] = str(ref[c].get('outcome')); jev[c]['outcome_s'] = str(jev[c]['outcome'])
    single('outcome_confirmed', ['True', 'False'], '成果確認（Jev p≥0.5 = 明示）', 'outcome_s', 'outcome_s')
# ---------- 不一致一覧 ----------
md += ['', '## 不一致一覧', '', '| comment_id | 軸 | 参照 | Jev | Jev確率/不確実 | 備考 |', '|---|---|---|---|---|---|']
n_dis = 0
for c in ids:
    r, j = ref[c], jev[c]
    if r['themes'] != j['tag']:
        n_dis += 1
        md.append(f"| {c} | テーマ | {';'.join(sorted(x.split('_')[0] for x in r['themes'])) or 'なし'} | {';'.join(sorted(x.split('_')[0] for x in j['tag'])) or 'なし'} | " +
                  ', '.join(f"{t.split('_')[0]}={j['p'].get(t, float('nan')):.2f}" for t in sorted(r['themes'] ^ j['tag'])) + f" | {r['note'].replace('|', '｜')} |")
    for axis, rk, jk in (('機能', 'function', 'function'), ('observed', 'observed', 'observed'), ('requested', 'requested', 'requested')):
        if r[rk] and r[rk] != j[jk]:
            n_dis += 1; md.append(f"| {c} | {axis} | {r[rk].split('_')[0]} | {j[jk].split('_')[0]} |  | {r['note'].replace('|', '｜')} |")
md.insert(3, f'不一致 {n_dis} 件（テーマ集合・機能・段階の各軸で数える）。')
with open(os.path.join(PRIV, f'tag_audit_comparison_{args.run_id}{args.out_suffix}.csv'), 'w', newline='', encoding='utf-8') as f:
    fields = ['axis', 'code', 'name', 'ref_pos', 'jev_pos', 'tp', 'fp', 'fn', 'tn', 'accuracy', 'kappa', 'precision', 'recall', 'f1', 'jev_uncertain_ref_pos', 'jev_uncertain_ref_neg']
    w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore'); w.writeheader(); w.writerows(rows)
open(os.path.join(PRIV, f'tag_audit_comparison_{args.run_id}{args.out_suffix}.md'), 'w', encoding='utf-8').write('\n'.join(md) + '\n')
print('\n'.join(md[:30])); print(f'... → canonical/private/tag_audit_comparison_{args.run_id}{args.out_suffix}.md / .csv')
