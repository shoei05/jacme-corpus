"""根拠位置（evidence_spans）を作る。対象文書のコメント・総評・概評ごとに、
PDF物理ページ（1始まり）、印刷ページ番号、節（領域/下位領域/水準）、text/<doc>.txt 内の文字位置を記録する。

- text/<doc>.txt は pdftotext -layout の出力で、ページは \\f で区切られている（物理ページ＝\\f 区切りの順番）。
- 照合は NFKC 正規化して空白を除いた文字列で行い、正規化後の位置を元ファイルの文字位置へ戻す。
- 同じ文が複数箇所にある場合は、該当する下位領域見出しの後ろで最初に現れる位置を採る（それでも決まらなければ ambiguous）。
- 固定ID ES-nnnnnn は canonical/id_map.json の 'evidence_span' に自然キー（doc|segment|ref）で永続化。
出力: canonical/private/evidence_spans.csv/.jsonl（文字位置と節は非公開層。公開は物理ページだけを後で許可列に含める）
使い方: python3 scripts/22_evidence_spans.py --docs evaluation_report17,evaluation_report101,...   （--docs all で全文書）
検証: --verify N で N 件を無作為に抜き、pdftotext -f/-l でそのページに本文の先頭20文字があるか確かめる。
"""
import csv, json, os, re, sys, argparse, unicodedata, random, subprocess, collections
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAN = os.path.join(ROOT, 'canonical'); PRIV = os.path.join(CAN, 'private')
ap = argparse.ArgumentParser(); ap.add_argument('--docs', required=True); ap.add_argument('--verify', type=int, default=0); ap.add_argument('--seed', type=int, default=0)
args = ap.parse_args()
def rd(p):
    with open(p, encoding='utf-8') as f: return list(csv.DictReader(f))
D = {d['doc_id']: d for d in rd(os.path.join(CAN, 'documents.csv'))}
docs = list(D) if args.docs == 'all' else args.docs.split(',')
C = [c for c in rd(os.path.join(CAN, 'comments.csv')) if c['doc_id'] in set(docs)]
TEXT = {r['comment_id']: r['text'] for r in rd(os.path.join(PRIV, 'comment_text.csv'))}
SOHYO = {r['doc_id']: r['text'] for r in rd(os.path.join(PRIV, 'sohyo.csv'))}
GAIHYO = [r for r in rd(os.path.join(PRIV, 'area_gaihyo.csv')) if r['doc_id'] in set(docs)]
JUDG = [j for j in rd(os.path.join(CAN, 'judgments.csv')) if j['doc_id'] in set(docs)]
EVID = rd(os.path.join(PRIV, 'event_evidence.csv'))
MAP_PATH = os.path.join(CAN, 'id_map.json'); idmap = json.load(open(MAP_PATH, encoding='utf-8')); idmap.setdefault('evidence_span', {})
def assign(key):
    m = idmap['evidence_span']
    if key not in m: m[key] = f'ES-{len(m) + 1:06d}'
    return m[key]
SUB = re.compile(r'^\s*(\d)\.(\d)\s+\S', re.M); AREA = re.compile(r'^\s*(\d)\.\s+\S{2,}', re.M)

def build(doc):
    raw = open(os.path.join(ROOT, 'text', doc + '.txt'), encoding='utf-8').read()
    # 正規化文字列と、正規化位置→元位置の対応
    norm_chars, back = [], []
    for i, ch in enumerate(raw):
        n = unicodedata.normalize('NFKC', ch)
        for c2 in n:
            if c2.isspace() or '\ue000' <= c2 <= '\uf8ff': continue   # 空白と私用領域の箇条書き記号を除く（07_comments.py と同じ）
            norm_chars.append(c2); back.append(i)
    norm = ''.join(norm_chars)
    # ページ境界（元位置）と印刷ページ番号
    pages = []; pos = 0
    for k, pg in enumerate(raw.split('\f'), 1):
        lines = [l.strip() for l in pg.split('\n') if l.strip()]
        printed = ''
        for l in (lines[-2:][::-1] + lines[:2]) if lines else []:
            if re.fullmatch(r'[0-9０-９]{1,3}', l): printed = unicodedata.normalize('NFKC', l); break
        pages.append({'n': k, 'start': pos, 'end': pos + len(pg), 'printed': printed}); pos += len(pg) + 1
    def page_of(off): return next((p['n'] for p in pages if p['start'] <= off < p['end']), len(pages))
    def printed_of(off): return next((p['printed'] for p in pages if p['start'] <= off < p['end']), '')
    # 見出し位置（元位置）
    heads = []
    for m in SUB.finditer(raw): heads.append((m.start(), 'sub', f'{m[1]}.{m[2]}'))
    for m in AREA.finditer(raw): heads.append((m.start(), 'area', m[1]))
    m9 = re.search(r'^\s*9\.\s*継続的改良', raw, re.M)
    if m9: heads.append((m9.start(), 'sub', '9.0'))
    heads.sort()
    def section_at(off):
        sub = area = ''
        for p, kind, v in heads:
            if p > off: break
            if kind == 'sub': sub = v; area = v.split('.')[0]
            else: area = v; sub = ''
        lvl = ''
        seg = raw[max(0, off - 3000):off]
        b, q = seg.rfind('基本的水準'), seg.rfind('質的向上のための水準')
        if b >= 0 or q >= 0: lvl = 'Q' if q > b else 'B'
        return area, sub, lvl
    def norm_pos_after(raw_off):   # 元位置 → 正規化位置（その位置以降の最初）
        import bisect; return bisect.bisect_left(back, raw_off)
    return raw, norm, back, pages, page_of, printed_of, section_at, norm_pos_after, heads

rows = []; stats = collections.Counter()
for doc in docs:
    raw, norm, back, pages, page_of, printed_of, section_at, norm_pos_after, heads = build(doc)
    sub_pos = {}
    for p, kind, v in heads:
        if kind == 'sub' and v not in sub_pos: sub_pos[v] = p
    def locate(text, sub=None, after_raw=0):
        t = ''.join(ch for ch in unicodedata.normalize('NFKC', text) if not (ch.isspace() or '\ue000' <= ch <= '\uf8ff'))
        if not t: return None, 'empty'
        starts = [m.start() for m in re.finditer(re.escape(t), norm)]
        if not starts:
            # 先頭40文字で再探索（本文に軽微な差がある場合）
            head = t[:30]; starts = [m.start() for m in re.finditer(re.escape(head), norm)] if len(head) >= 20 else []
            if not starts: return None, 'not_found'
            status = 'prefix'
        else: status = 'exact'
        lo = norm_pos_after(max(after_raw, sub_pos.get(sub, 0) if sub else 0))
        cands = [s for s in starts if s >= lo] or starts
        if len(cands) > 1 and status == 'exact': status = 'ambiguous_first_after_heading'
        s = cands[0]; e = s + (len(t) if status != 'prefix' else len(t[:30]))
        return (back[s], back[e - 1] + 1), status
    for c in sorted(C, key=lambda x: (x['doc_id'] != doc, x['original_subarea'], x['level'], x['type'], int(x['ordinal']))):
        if c['doc_id'] != doc: continue
        span, st = locate(TEXT[c['comment_id']], c['original_subarea']); stats[st] += 1
        area, sub, lvl = section_at(span[0]) if span else ('', '', '')
        rows.append({'span_id': assign(f'{doc}|comment|{c["comment_id"]}'), 'doc_id': doc, 'segment_type': 'comment', 'ref_id': c['comment_id'],
                     'pdf_page_start': page_of(span[0]) if span else '', 'pdf_page_end': page_of(span[1] - 1) if span else '', 'printed_page': printed_of(span[0]) if span else '',
                     'area': area or c['area'], 'subarea': sub or c['original_subarea'], 'level': lvl or c['level'], 'comment_type': c['type'],
                     'char_start': span[0] if span else '', 'char_end': span[1] if span else '', 'match_status': st, 'source_txt': f'text/{doc}.txt', 'verified': ''})
    if doc in SOHYO:
        i = raw.find('総評'); j = raw.find('評価チーム', i) if i >= 0 else -1
        if i >= 0:
            e = j if j > i else min(len(raw), i + len(SOHYO[doc]) * 2)
            rows.append({'span_id': assign(f'{doc}|sohyo|{doc}'), 'doc_id': doc, 'segment_type': 'sohyo', 'ref_id': doc, 'pdf_page_start': page_of(i), 'pdf_page_end': page_of(e - 1), 'printed_page': printed_of(i),
                         'area': '', 'subarea': '', 'level': '', 'comment_type': '', 'char_start': i, 'char_end': e, 'match_status': 'section', 'source_txt': f'text/{doc}.txt', 'verified': ''}); stats['sohyo'] += 1
    for g in GAIHYO:
        if g['doc_id'] != doc: continue
        span, st = locate(g['text'][:60]); stats['gaihyo_' + st] += 1
        if span:
            # 概評は冒頭60文字で位置を決め、終端は本文長から推定
            end_span, st2 = locate(g['text'][-40:], after_raw=span[0])
            e = end_span[1] if end_span and end_span[1] > span[0] else span[1]
        rows.append({'span_id': assign(f'{doc}|gaihyo|{doc}#{g["area"]}'), 'doc_id': doc, 'segment_type': 'gaihyo', 'ref_id': f'{doc}#{g["area"]}', 'pdf_page_start': page_of(span[0]) if span else '', 'pdf_page_end': page_of(e - 1) if span else '',
                     'printed_page': printed_of(span[0]) if span else '', 'area': g['area'], 'subarea': '', 'level': '', 'comment_type': '', 'char_start': span[0] if span else '', 'char_end': e if span else '',
                     'match_status': st, 'source_txt': f'text/{doc}.txt', 'verified': ''})
    # 判定行: 下位領域の区間内の「基本的水準：判定」「本審査での評価：」「追加審査の評価：」
    JUD = r'(適合|部分的適合|不適合|評価を実施せず|評価を実施しない|評価は実施せず|部分的評価)'
    for jrow in [j for j in JUDG if j['doc_id'] == doc]:
        sub = jrow['original_subarea']; lvl = jrow['level']
        heads_sub = [(p_, v) for p_, kind, v in heads if kind == 'sub' and v == sub]
        if not heads_sub: continue
        # B/Q の見出しが別々にある文書（追加審査）はラベルで選ぶ
        cand = []
        for hp, _ in heads_sub:
            nxt = min([p_ for p_, k_, v_ in heads if p_ > hp] + [len(raw)])
            seg = raw[hp:nxt]
            if lvl == 'Q' and '質的向上のための水準' not in seg[:200] and '質的向上' in raw[hp:hp+120]: pass
            cand.append((hp, seg))
        found = None
        for hp, seg in cand:
            lab = '質的向上のための水準' if lvl == 'Q' else '基本的水準'
            if D[doc]['review_type'] == 'additional':
                if lvl == 'Q' and '質的向上のための水準' not in seg[:150]: continue
                if lvl == 'B' and '質的向上のための水準' in seg[:150]: continue
                m = re.search(r'追加審査の評価\s*[:：]\s*' + JUD, seg) or re.search(r'(?:本審査での評価|\d{4}\s*年度の評価)\s*[:：]\s*' + JUD, seg)
            else:
                m = re.search(lab + r'\s*[:：]\s*' + JUD, seg)
            if m: found = (hp + m.start(), hp + m.end()); break
        if found:
            rows.append({'span_id': assign(f'{doc}|judgment|{jrow["judgment_id"]}'), 'doc_id': doc, 'segment_type': 'judgment', 'ref_id': jrow['judgment_id'], 'pdf_page_start': page_of(found[0]), 'pdf_page_end': page_of(found[1] - 1), 'printed_page': printed_of(found[0]),
                         'area': sub.split('.')[0], 'subarea': sub, 'level': lvl, 'comment_type': '', 'char_start': found[0], 'char_end': found[1], 'match_status': 'judgment_line', 'source_txt': f'text/{doc}.txt', 'verified': ''}); stats['judgment'] += 1
        else: stats['judgment_not_found'] += 1
    # 時点の根拠（regex 由来の event_evidence）
    for ev in [e for e in EVID if e['doc_id'] == doc and e['source_file'].startswith('text/') and e['char_start']]:
        rows.append({'span_id': assign(f'{doc}|event_evidence|{ev["flag"]}'), 'doc_id': doc, 'segment_type': 'event_evidence', 'ref_id': f"{ev['event_id']}#{ev['flag']}", 'pdf_page_start': page_of(int(ev['char_start'])), 'pdf_page_end': page_of(int(ev['char_end']) - 1), 'printed_page': printed_of(int(ev['char_start'])),
                     'area': '', 'subarea': '', 'level': '', 'comment_type': '', 'char_start': ev['char_start'], 'char_end': ev['char_end'], 'match_status': 'regex_evidence', 'source_txt': f'text/{doc}.txt', 'verified': ''}); stats['event_evidence'] += 1
# 既存ファイルと統合（他文書の行は残す）
out = os.path.join(PRIV, 'evidence_spans')
old = [r for r in rd(out + '.csv') if r['doc_id'] not in set(docs)] if os.path.exists(out + '.csv') else []
allrows = old + rows
FIELDS = ['span_id', 'doc_id', 'segment_type', 'ref_id', 'pdf_page_start', 'pdf_page_end', 'printed_page', 'area', 'subarea', 'level', 'comment_type', 'char_start', 'char_end', 'match_status', 'source_txt', 'verified']
with open(out + '.csv', 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction='ignore'); w.writeheader(); w.writerows(allrows)
with open(out + '.jsonl', 'w', encoding='utf-8') as f:
    for r in allrows: f.write(json.dumps({k: r.get(k, '') for k in FIELDS}, ensure_ascii=False) + '\n')
json.dump(idmap, open(MAP_PATH, 'w', encoding='utf-8'), ensure_ascii=False, indent=0, sort_keys=True)
print(json.dumps({'docs': len(docs), 'rows_new': len(rows), 'rows_total': len(allrows), 'match_status': dict(stats)}, ensure_ascii=False))

# ---------- 検証: pdftotext でページを個別に出し、本文の先頭20文字がそのページにあるか ----------
if args.verify:
    rng = random.Random(args.seed); M = {m['file'].replace('.pdf', ''): m['file'] for m in rd(os.path.join(CAN, 'source_manifest.csv')) if m['doc_id']}
    sample = rng.sample([r for r in rows if r['segment_type'] == 'comment' and r['char_start'] != ''], min(args.verify, len(rows)))
    ok = 0; rep = []
    for r in sample:
        pdf = os.path.join(ROOT, 'raw', 'pdf', D[r['doc_id']]['file']); pg = int(r['pdf_page_start'])
        page_txt = subprocess.run(['pdftotext', '-layout', '-f', str(pg), '-l', str(pg), pdf, '-'], capture_output=True, text=True).stdout
        strip = lambda x: ''.join(ch for ch in unicodedata.normalize('NFKC', x) if not (ch.isspace() or '\ue000' <= ch <= '\uf8ff'))
        pn = strip(page_txt); t = strip(TEXT[r['ref_id']])
        raw = open(os.path.join(ROOT, 'text', r['doc_id'] + '.txt'), encoding='utf-8').read()
        slice_norm = strip(raw[int(r['char_start']):int(r['char_end'])])
        hit = t[:20] in pn; same = slice_norm == t or (r['match_status'] == 'prefix' and t.startswith(slice_norm))
        ok += hit and same; rep.append((r['span_id'], r['doc_id'], pg, r['printed_page'], r['subarea'], r['level'], hit, same, r['match_status']))
    for x in rep: print('VERIFY', x)
    print(f'verified {ok}/{len(sample)} (page hit and slice equals text)')
    if ok == len(sample):
        ids_ok = {x[0] for x in rep}
        for r in allrows:
            if r['span_id'] in ids_ok: r['verified'] = 'sample_ok'
        with open(out + '.csv', 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction='ignore'); w.writeheader(); w.writerows(allrows)
