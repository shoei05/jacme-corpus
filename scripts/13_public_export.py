"""公開エクスポート: canonical/ の非private表だけを読み、許可列（allowlist）で public/data/ をゼロから生成する。
非公開DBのコピーや列削除では作らない。最後に漏えい検査を行い、違反があれば public/data/ を削除して終了コード1。
使い方: python3 scripts/13_public_export.py [release_version]"""
import csv, json, os, sys, random, shutil, collections, datetime
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAN = os.path.join(ROOT, 'canonical'); PRIV = os.path.join(CAN, 'private')
PUB = os.path.join(ROOT, 'public'); DATA = os.path.join(PUB, 'data'); SITE = os.path.join(PUB, 'site')
VERSION = sys.argv[1] if len(sys.argv) > 1 else 'jacme-2026.10.0'
def rd(p):
    with open(p, encoding='utf-8') as f: return list(csv.DictReader(f))

# ---------- 許可列（ここに無い列は公開ファイルに出ない） ----------
ALLOW = {
    'institutions': ['institution_id', 'name', 'pref', 'type', 'n_documents', 'n_main_reviews', 'has_two_cycles'],
    'events': ['event_id', 'institution_id', 'doc_id', 'review_type', 'cycle', 'eval_year', 'standard_version_declared', 'standard_family',
               'retrospective_reassessment', 'mixed_standard', 'mixed_subareas', 'observation_start', 'observation_end', 'verification_status',
               'source_url', 'b_comp', 'b_part', 'b_non', 'b_nae', 'q_comp', 'q_part', 'q_non', 'q_nae', 'has_summary_counts', 'n_judgments', 'n_comments'],
    'concepts': ['concept_id', 'area', 'name'],
    'standard_items': ['standard_family', 'original_subarea', 'original_name', 'concept_id', 'relation'],
    'judgments': ['judgment_id', 'event_id', 'concept_id', 'original_subarea', 'level', 'judgment', 'judgment_before'],
    'comment_counts': ['event_id', 'concept_id', 'level', 'type', 'tone', 'n'],
    'theme_counts': ['event_id', 'concept_id', 'level', 'type', 'theme', 'n_comments'],
    'theme_summary': ['theme', 'review_type', 'cycle', 'level', 'n_comments', 'n_universities', 'n_universities_with_comments', 'n_universities_judged'],
    'codebook_themes': ['theme', 'name', 'definition', 'include', 'exclude', 'threshold', 'reliability', 'codebook_version', 'model'],
}
inst = rd(os.path.join(CAN, 'institutions.csv')); docs = rd(os.path.join(CAN, 'documents.csv')); evs = rd(os.path.join(CAN, 'review_events.csv'))
concepts = rd(os.path.join(CAN, 'concepts.csv')); items = rd(os.path.join(CAN, 'standard_items.csv'))
judg = rd(os.path.join(CAN, 'judgments.csv')); cmts = rd(os.path.join(CAN, 'comments.csv'))
vrep = json.load(open(os.path.join(CAN, 'validation_report.json'), encoding='utf-8'))
Dm = {d['doc_id']: d for d in docs}
events = []
for e in evs:
    d = Dm[e['doc_id']]
    events.append({**e, 'source_url': d['url'], **{k: d[k] for k in ['b_comp', 'b_part', 'b_non', 'b_nae', 'q_comp', 'q_part', 'q_non', 'q_nae', 'has_summary_counts', 'n_judgments', 'n_comments']}})
cc = collections.Counter((c['event_id'], c['concept_id'], c['level'], c['type'], c['tone']) for c in cmts)
comment_counts = [{'event_id': k[0], 'concept_id': k[1], 'level': k[2], 'type': k[3], 'tone': k[4], 'n': n} for k, n in sorted(cc.items())]
tables = {'institutions': inst, 'events': events, 'concepts': concepts, 'standard_items': items, 'judgments': judg, 'comment_counts': comment_counts}
# ---------- テーマ集計（comment_tags があるとき。本文は読まない） ----------
tag_path = os.path.join(CAN, 'comment_tags.csv'); theme_counts = []; theme_summary = []; codebook_themes = []; tag_stats = {}
gate_path = os.path.join(CAN, 'tag_tables_manifest.json'); gate = json.load(open(gate_path, encoding='utf-8')) if os.path.exists(gate_path) else {}
def _sha(p):
    import hashlib; h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()
tags_ok = bool(gate.get('complete')) and os.path.exists(tag_path) and gate.get('input_hashes', {}).get('canonical/comments.csv') == _sha(os.path.join(CAN, 'comments.csv')) \
          and gate.get('output_hashes', {}).get('canonical/comment_tags.csv') == _sha(tag_path)
if os.path.exists(tag_path) and not tags_ok: print('タグ表は関門（tag_tables_manifest.json complete / ハッシュ一致）を満たさないので公開しない')
if tags_ok:
    import yaml
    cb = yaml.safe_load(open(os.path.join(CAN, 'codebook', 'codebook_v1.1.yaml'), encoding='utf-8'))
    tags = [r for r in rd(tag_path) if r['tagged'] == 'true']
    Cm = {c['comment_id']: c for c in cmts}; Em = {e['event_id']: e for e in events}; I_name = {i['institution_id']: i['name'] for i in inst}
    tc = collections.Counter((Cm[t['comment_id']]['event_id'], Cm[t['comment_id']]['concept_id'], Cm[t['comment_id']]['level'], Cm[t['comment_id']]['type'], t['theme']) for t in tags)
    theme_counts = [{'event_id': k[0], 'concept_id': k[1], 'level': k[2], 'type': k[3], 'theme': k[4], 'n_comments': n} for k, n in sorted(tc.items())]
    # テーマ × 審査種別/巡 × 水準: コメント数、言及のある大学数、分母（判定のある大学数）
    col_of = lambda e: (e['review_type'], e['cycle'] if e['review_type'] == 'main' else '')
    judged_univ = collections.defaultdict(set)
    for j in judg: e = Em[j['event_id']]; judged_univ[(col_of(e), j['level'])].add(e['institution_id'])
    tu = collections.defaultdict(set); tn = collections.Counter(); cu = collections.defaultdict(set)
    for c in cmts: e = Em[c['event_id']]; cu[(col_of(e), c['level'])].add(e['institution_id'])
    for t in tags:
        c = Cm[t['comment_id']]; e = Em[c['event_id']]; k = (t['theme'], col_of(e), c['level'])
        tu[k].add(e['institution_id']); tn[k] += 1
    for (theme, col, level), n in sorted(tn.items()):
        theme_summary.append({'theme': theme, 'review_type': col[0], 'cycle': col[1], 'level': level, 'n_comments': n, 'n_universities': len(tu[(theme, col, level)]),
                              'n_universities_with_comments': len(cu[(col, level)]), 'n_universities_judged': len(judged_univ[(col, level)])})
    TH_ = cb['thresholds']; low = set(TH_.get('reliability', {}).get('low', [])); model = tags[0]['model'] if tags else ''
    for k, v in cb['axes']['theme']['labels'].items():
        codebook_themes.append({'theme': k, 'name': v['name'], 'definition': v['definition'], 'include': v.get('include', ''), 'exclude': v.get('exclude', ''),
                                'threshold': '' if k == 'T00_none' else TH_.get('per_theme', {}).get(k, TH_.get('theme_tag_default')), 'reliability': 'low' if k in low else ('derived' if k == 'T00_none' else 'compared_blind_60x3'),
                                'codebook_version': cb['version'], 'model': model})
    tables.update({'theme_counts': theme_counts, 'theme_summary': theme_summary, 'codebook_themes': codebook_themes})
    # --- 可視化用: テーマ共起（同一コメント内）、イベント単位の Jaccard、列（本審査1巡/2巡/追加審査）×種別群（特色/改善要求） ---
    TG = lambda t: 'positive' if t == '特色ある点' else 'request'
    by_c = collections.defaultdict(set)
    for t in tags: by_c[t['comment_id']].add(t['theme'])
    ev_theme = collections.defaultdict(set); ev_pair = collections.defaultdict(set); univ_theme = collections.defaultdict(set); theme_sub = collections.Counter()
    for cid, ths in by_c.items():
        c = Cm[cid]; e = Em[c['event_id']]; key = (col_of(e), TG(c['type']))
        for th in ths: ev_theme[(key, th)].add(c['event_id']); univ_theme[(key, th)].add(e['institution_id']); theme_sub[(key, th, c['concept_id'])] += 1
        for a in ths:
            for b in ths:
                if a < b: ev_pair[(key, a, b)].add(c['event_id'])
    theme_nodes = [{'col': k[0][0] + (k[0][1] or ''), 'type_group': k[1], 'theme': th, 'n_events': len(evs), 'n_universities': len(univ_theme[(k, th)]),
                    'universities': ';'.join(sorted(I_name[u] for u in univ_theme[(k, th)]))} for (k, th), evs in sorted(ev_theme.items())]
    theme_edges = []
    for (k, a, b), both in sorted(ev_pair.items()):
        either = ev_theme[(k, a)] | ev_theme[(k, b)]
        theme_edges.append({'col': k[0][0] + (k[0][1] or ''), 'type_group': k[1], 'source': a, 'target': b, 'n_events_both': len(both), 'n_events_either': len(either), 'jaccard': round(len(both) / len(either), 3) if either else 0})
    theme_subareas = [{'col': k[0][0] + (k[0][1] or ''), 'type_group': k[1], 'theme': th, 'concept_id': cc_, 'n_comments': n} for (k, th, cc_), n in sorted(theme_sub.items())]
    # --- テーマ×段階: 特色の observed_stage と 要求の requested_stage（comment_classes） ---
    cls_p = os.path.join(CAN, 'comment_classes.csv'); theme_stage = []
    if os.path.exists(cls_p):
        CL = {r['comment_id']: r for r in rd(cls_p)}; st = collections.Counter(); stu = collections.defaultdict(set)
        for cid, ths in by_c.items():
            c = Cm[cid]; e = Em[c['event_id']]; k = CL[cid]; g = TG(c['type']); stage = k['observed_stage'] if g == 'positive' else k['requested_stage']
            for th in ths: st[(col_of(e), g, th, stage)] += 1; stu[(col_of(e), g, th, stage)].add(e['institution_id'])
        theme_stage = [{'col': k[0][0] + (k[0][1] or ''), 'type_group': k[1], 'theme': k[2], 'stage': k[3], 'n_comments': n, 'n_universities': len(stu[k])} for k, n in sorted(st.items())]
    # --- 判定行の PDF ページ（evidence_spans があるもの） ---
    es_p = os.path.join(PRIV, 'evidence_spans.csv'); judgment_pages = []
    if os.path.exists(es_p):
        for r in rd(es_p):
            if r['segment_type'] == 'judgment': judgment_pages.append({'judgment_id': r['ref_id'], 'doc_id': r['doc_id'], 'pdf_page': r['pdf_page_start']})
    ALLOW.update({'theme_nodes': ['col', 'type_group', 'theme', 'n_events', 'n_universities', 'universities'], 'theme_edges': ['col', 'type_group', 'source', 'target', 'n_events_both', 'n_events_either', 'jaccard'],
                  'theme_subareas': ['col', 'type_group', 'theme', 'concept_id', 'n_comments'], 'theme_stage': ['col', 'type_group', 'theme', 'stage', 'n_comments', 'n_universities'], 'judgment_pages': ['judgment_id', 'doc_id', 'pdf_page']})
    tables.update({'theme_nodes': theme_nodes, 'theme_edges': theme_edges, 'theme_subareas': theme_subareas, 'theme_stage': theme_stage, 'judgment_pages': judgment_pages})
    tag_stats = {'n_tagged_rows': len(tags), 'comments_by_theme': dict(collections.Counter(t['theme'] for t in tags)), 'codebook': cb['version'], 'model': model,
                 'note': 'テーマは型付き判定モデル（TypeSafe Jev）の自動付与。妥当性の確認は別モデル（ChatGPT）による盲検判定との比較（60件×3回）で、人の参照判定ではない。T11・T13 の閾値は独立に検証されていない。集計の単位は大学（審査イベント）。'}

def project(rows, cols):
    return [{c: (r[c] if r.get(c) is not None else '') for c in cols} for r in rows]

# 統計（公開画面③用）
ev_main = [e for e in events if e['review_type'] == 'main']
stats = {'release_version': VERSION, 'built_at': datetime.datetime.now().isoformat(timespec='seconds'), 'fetched_date': '2026-10-10',
         'source_page': 'https://www.jacme.or.jp/accreditation/evaluation_results.php',
         'n_institutions': len(inst), 'n_institutions_two_cycles': sum(1 for i in inst if i['has_two_cycles'] == 'true'),
         'n_events': len(events), 'events_by_review_type': dict(collections.Counter(e['review_type'] for e in events)),
         'events_by_year': dict(sorted(collections.Counter(e['eval_year'] or '不明' for e in events).items())),
         'events_by_standard_family': dict(collections.Counter(e['standard_family'] or '不明' for e in events)),
         'events_by_cycle_main': dict(collections.Counter(e['cycle'] for e in ev_main)),
         'n_judgments': len(judg), 'judgments_by_value': dict(collections.Counter(j['judgment'] for j in judg)),
         'judgments_by_level_value': {L: dict(collections.Counter(j['judgment'] for j in judg if j['level'] == L)) for L in 'BQ'},
         'n_comments': len(cmts), 'comments_by_type': dict(collections.Counter(c['type'] for c in cmts)), 'comments_by_tone': dict(collections.Counter(c['tone'] for c in cmts)),
         'flags': {f: dict(collections.Counter(e[f] for e in events)) for f in ['retrospective_reassessment', 'mixed_standard']},
         'validation': {'n_checks': vrep['n_checks'], 'n_fail': vrep['n_fail'], 'summary_counts_checked': vrep['summary_counts_checked'],
                        'summary_counts_mismatch': vrep['summary_counts_mismatch'], 'n_quarantined_judgments': vrep['counts'].get('quarantine_judgments', 1)},
         'n_source_pdfs': 164, 'themes': tag_stats, 'practice_cards': ({'n_approved': len(tables.get('practice_cards', [])), 'version': (cards_meta.get('cards_version') if 'cards_meta' in dir() else ''), 'note': '取り組みカードは別モデル（ChatGPT）の盲検判定（出典スパンとの対応）を経て公開。人による全件確認は未了。', 'rounds': (cards_meta.get('approval', {}).get('rounds', []) if 'cards_meta' in dir() else [])} if tables.get('practice_cards') else {}),
         'changelog': [{'date': '2026-10-10', 'version': VERSION, 'note': '初版。82大学・125文書。判定・コメント件数・審査イベントの構造化。'}, {'date': '2026-10-10', 'version': VERSION, 'note': 'テーマタグ（codebook v1.1、Jev）を全コメントに付与し、テーマ別の集計を追加。T11・T13 は信頼性が低い。'}] + ([{'date': '2026-10-10', 'version': VERSION, 'note': 'IR・内部質保証の取り組みカード（6大学12枚）を公開。別モデルの盲検判定を経ており、人による全件確認は未了。'}] if tables.get('practice_cards') else []) if tag_stats else [{'date': '2026-10-10', 'version': VERSION, 'note': '初版。82大学・125文書。判定・コメント件数・審査イベントの構造化。テーマタグは未整備。'}],
         'notes': ['報告書の本文とPDFは再配布しない。原文はJACMEの元PDFを参照する。', '評価員個人は分析・表示の単位にしない。大学の順位・総合点は作らない。',
                   '後年再評価フラグは「本審査の判定が実地調査後の改善を含むか」を指し、追加審査・公表文は対象外（not_applicable）。値は報告書の該当箇所を型付き判定モデル（TypeSafe Jev）に読ませた確率を閾値（0.8以上=あり、0.2以下=なし）で写像したもの。中間は未確認。版混在は、下位領域の選択問題と本文の版の明記がそろう場合に「あり」としている。人による確認は未了。']}

# ---------- 取り組みカード（承認済みだけ。文章はこちらの言葉。近接言い換え検査は公開時に行う） ----------
cards_path = os.path.join(CAN, 'pilot_ir', 'public_practice_cards.csv')
if os.path.exists(cards_path):
    cards = [r for r in rd(cards_path) if r['approved'] == 'true']
    if cards:
        ALLOW['practice_cards'] = ['card_id', 'practice_id', 'institution_id', 'title', 'summary', 'mechanism', 'actors_flow', 'reached', 'reservations', 'unknowns', 'hypothesis_links', 'footnote', 'span_pages', 'version']
        ES = {r['span_id']: r for r in rd(os.path.join(PRIV, 'evidence_spans.csv'))}
        for c in cards:   # span_id → 文書と物理ページだけ（文字位置は出さない）
            c['span_pages'] = ';'.join(f"{ES[x]['doc_id']}:p{ES[x]['pdf_page_start']}" for x in c['span_ids'].split(';') if x in ES)
        tables['practice_cards'] = cards
        meta_p = os.path.join(CAN, 'pilot_ir', 'cards_metadata.json'); cards_meta = json.load(open(meta_p, encoding='utf-8')) if os.path.exists(meta_p) else {}
    print(f'practice_cards: approved {len(cards)} / drafts {sum(1 for r in rd(cards_path))}')
    if cards:   # stats はカード処理より前に作られるので、ここで追記する
        stats['practice_cards'] = {'n_approved': len(cards), 'version': cards_meta.get('cards_version', ''), 'note': '取り組みカードは別モデル（ChatGPT）の盲検判定（出典スパンとの対応）を経て公開。人による全件確認は未了。', 'rounds': cards_meta.get('approval', {}).get('rounds', [])}
        stats['changelog'].append({'date': '2026-10-10', 'version': VERSION, 'note': 'IR・内部質保証の取り組みカード（6大学12枚）を公開。別モデルの盲検判定を経ており、人による全件確認は未了。'})
# ---------- 書き出し（ゼロから） ----------
if os.path.exists(DATA): shutil.rmtree(DATA)
os.makedirs(DATA)
for name, rows in tables.items():
    rows = project(rows, ALLOW[name])
    json.dump(rows, open(os.path.join(DATA, name + '.json'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    with open(os.path.join(DATA, name + '.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=ALLOW[name]); w.writeheader(); w.writerows(rows)
json.dump(stats, open(os.path.join(DATA, 'stats.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

# ---------- 漏えい検査 ----------
def squash(s): return ''.join(s.split())
forbidden = []  # (label, needle)
ct = rd(os.path.join(PRIV, 'comment_text.csv')); rng = random.Random(0)
sampled = {r['comment_id'] for r in rng.sample(ct, min(500, len(ct)))}
for r in ct:  # 全コメントの先頭20文字。抽出500件は中央・末尾も加える
    t = squash(r['text'])
    wins = {t[:20]} | ({t[len(t)//2 - 10:len(t)//2 + 10], t[-20:]} if r['comment_id'] in sampled else set())
    for s in wins:
        if len(s) >= 12: forbidden.append((f"comment:{r['comment_id']}", s))
for r in rd(os.path.join(PRIV, 'sohyo.csv')) + rd(os.path.join(PRIV, 'area_gaihyo.csv')):
    t = squash(r['text'])
    for s in {t[:20], t[len(t)//2 - 10:len(t)//2 + 10], t[-20:]}:
        if len(s) >= 12: forbidden.append((f"prose:{r['doc_id']}", s))
for r in rd(os.path.join(PRIV, 'evaluators.csv')):
    n = squash(r['name'])
    if len(n) >= 3: forbidden.append(('evaluator', n))
forbidden.append(('word', '全文'))
# 取り組みカードの近接言い換え検査: 公開するカード文のうち、原文（コメント・総評・概評）と連続8文字以上が一致する箇所を違反にする
if 'practice_cards' in tables:
    src = set(); CT = {r['comment_id']: r['text'] for r in ct}   # コーパス全体とは12文字、出典コメントとは8文字
    for r in ct: t = squash(r['text']); src.update(t[i:i + 12] for i in range(0, max(0, len(t) - 11)))
    for r in rd(os.path.join(PRIV, 'sohyo.csv')) + rd(os.path.join(PRIV, 'area_gaihyo.csv')):
        t = squash(r['text']); src.update(t[i:i + 12] for i in range(0, max(0, len(t) - 11)))
    ES2 = {r['span_id']: r for r in rd(os.path.join(PRIV, 'evidence_spans.csv'))}
    act_p = os.path.join(CAN, 'pilot_ir', 'actors.csv')
    exempt = sorted({squash(x) for a in (rd(act_p) if os.path.exists(act_p) else []) for x in [a['label']] + a['aliases'].split(';') if x} | {squash(k['name']) for k in concepts} | {squash(t) for t in __import__('yaml').safe_load(open(os.path.join(CAN, 'codebook', 'practices_v0.2.yaml'), encoding='utf-8')).get('paraphrase_check', {}).get('criteria_terms', [])}, key=len, reverse=True)
    for c in tables['practice_cards']:
        body = squash(' '.join(c.get(k, '') for k in ('title', 'summary', 'mechanism', 'actors_flow', 'reached', 'reservations', 'unknowns', 'hypothesis_links')))
        for ex in exempt: body = body.replace(ex, '＊')
        s8 = set()
        for sid in c['span_ids'].split(';'):
            if sid in ES2 and ES2[sid]['segment_type'] == 'comment':
                t = squash(CT.get(ES2[sid]['ref_id'], '')); s8.update(t[i:i + 8] for i in range(0, max(0, len(t) - 7)))
        hits = {body[i:i + 8] for i in range(0, max(0, len(body) - 7)) if '＊' not in body[i:i + 8] and body[i:i + 8] in s8} | {body[i:i + 12] for i in range(0, max(0, len(body) - 11)) if '＊' not in body[i:i + 12] and body[i:i + 12] in src}
        # 組織名など事実の語（8文字未満の重なりは許容）。8文字以上の一致は近接言い換えとみなす
        if hits: violations_cards = violations_cards if 'violations_cards' in dir() else []; violations_cards.append((c['card_id'], sorted(hits)[:5]))
    if 'violations_cards' in dir() and violations_cards: forbidden.append(('card_paraphrase', '__CARD_PARAPHRASE__'))
FORBIDDEN_COLS = {'text', 'sohyo', 'snippet', 'name_variants', 'created', 'file', 'n_evaluators', 'text_sha256'}
violations = []
targets = []
if 'violations_cards' in dir() and violations_cards: violations.extend(('public/data/practice_cards.json', f'card_paraphrase:{cid}', ' '.join(h)) for cid, h in violations_cards)
for base in (DATA, SITE):
    if not os.path.isdir(base): continue
    for dp, _, fns in os.walk(base):
        for fn in fns:
            if fn.endswith(('.json', '.csv', '.html', '.js', '.css', '.md', '.txt')): targets.append(os.path.join(dp, fn))
for p in targets:
    raw = open(p, encoding='utf-8').read(); body = squash(raw)
    for label, needle in forbidden:
        if needle in body: violations.append((os.path.relpath(p, ROOT), label, needle[:12]))
    if p.startswith(DATA) and p.endswith('.csv'):
        hdr = open(p, encoding='utf-8').readline().strip().split(',')
        for c in hdr:
            if c in FORBIDDEN_COLS: violations.append((os.path.relpath(p, ROOT), 'column', c))
report = {'checked_files': len(targets), 'n_needles': len(forbidden), 'violations': violations[:50], 'n_violations': len(violations), 'checked_at': datetime.datetime.now().isoformat(timespec='seconds')}
json.dump(report, open(os.path.join(PUB, 'leak_check.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(json.dumps({'tables': {k: len(v) for k, v in tables.items()}, 'leak_check': {k: v for k, v in report.items() if k != 'violations'}, 'violations': violations[:10]}, ensure_ascii=False, indent=1))
if violations:
    shutil.rmtree(DATA); sys.exit('漏えい検査に失敗。public/data を削除した')
