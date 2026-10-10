"""正本（canonical層）を knowledge/*.csv と text/ から生成する。

- 固定IDは canonical/id_map.json に自然キー→IDで永続化し、再実行でも同じIDを返す。
- 自由文（コメント本文、総評、概評、根拠断片、評価チーム氏名）は canonical/private/ にだけ置く。
- 後年再評価・版混在フラグは本文に明示がある場合だけ true にし、それ以外は unknown。
"""
import csv, json, os, re, hashlib, unicodedata, collections, datetime
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
K = os.path.join(ROOT, 'knowledge'); CAN = os.path.join(ROOT, 'canonical'); PRIV = os.path.join(CAN, 'private')
os.makedirs(PRIV, exist_ok=True)
FETCHED = '2026-10-10'

def rd(name):
    with open(os.path.join(K, name + '.csv'), encoding='utf-8-sig') as f: return list(csv.DictReader(f))
def wr(path, rows, fields):
    with open(path + '.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore'); w.writeheader(); w.writerows(rows)
    with open(path + '.jsonl', 'w', encoding='utf-8') as f:
        for r in rows: f.write(json.dumps({k: r.get(k, '') for k in fields}, ensure_ascii=False) + '\n')
def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()
def norm(t): return unicodedata.normalize('NFKC', t).replace('\f', '\n')

# ---------- 固定ID ----------
MAP_PATH = os.path.join(CAN, 'id_map.json')
idmap = json.load(open(MAP_PATH, encoding='utf-8')) if os.path.exists(MAP_PATH) else {'institution': {}, 'event': {}, 'judgment': {}, 'comment': {}}
PREFIX = {'institution': ('INST-', 3), 'event': ('EV-', 4), 'judgment': ('JG-', 6), 'comment': ('CM-', 6)}
def assign(kind, keys):
    m = idmap[kind]; pre, width = PREFIX[kind]
    nxt = max([int(v[len(pre):]) for v in m.values()] + [0]) + 1
    for k in sorted(set(keys)):
        if k not in m: m[k] = f'{pre}{nxt:0{width}d}'; nxt += 1
    return m

D, J, C, M = rd('documents'), rd('judgments'), rd('comments'), rd('manifest')
G = rd('area_gaihyo')
Q = rd('quarantine_judgments') if os.path.exists(os.path.join(K, 'quarantine_judgments.csv')) else []
Dm = {d['doc_id']: d for d in D}
Mfile = {m['file'].replace('.pdf', ''): m for m in M}

# ---------- 大学 ----------
inst_ids = assign('institution', [f"inst|{d['univ']}" for d in D])
institutions = []
for u in sorted({d['univ'] for d in D}, key=lambda x: int(min(d['no'] for d in D if d['univ'] == x))):
    ds = [d for d in D if d['univ'] == u]
    institutions.append({'institution_id': inst_ids[f'inst|{u}'], 'name': u, 'pref': ds[0]['pref'], 'type': ds[0]['type'],
                         'jacme_no': ds[0]['no'], 'n_documents': len(ds),
                         'n_main_reviews': sum(1 for d in ds if d['review_type'] == 'main'),
                         'has_two_cycles': 'true' if sum(1 for d in ds if d['review_type'] == 'main') >= 2 else 'false'})
inst_of = {d['doc_id']: inst_ids[f"inst|{d['univ']}"] for d in D}

# ---------- 原本マニフェスト（raw/pdf 全件 + raw/duplicates） ----------
source_manifest = []
for sub in ('pdf', 'duplicates'):
    dirp = os.path.join(ROOT, 'raw', sub)
    for fn in sorted(os.listdir(dirp)):
        if fn.startswith('.'): continue
        p = os.path.join(dirp, fn); m = Mfile.get(fn.replace('.pdf', ''), {})
        source_manifest.append({'file': fn, 'dir': f'raw/{sub}', 'sha256': sha256(p), 'size_bytes': os.path.getsize(p),
                                'url': m.get('url', ''), 'fetched_date': FETCHED, 'kind': m.get('kind', 'duplicate' if sub == 'duplicates' else ''),
                                'label': m.get('label', ''), 'jacme_no': m.get('no', ''), 'institution_id': inst_ids.get(f"inst|{m.get('univ','')}", ''),
                                'doc_id': fn.replace('.pdf', '') if fn.replace('.pdf', '') in Dm else '',
                                'note': '番号62は98と同一の旧ファイル' if sub == 'duplicates' else ''})

# ---------- 文書 ----------
CNT = ['b_comp', 'b_part', 'b_non', 'b_nae', 'q_comp', 'q_part', 'q_non', 'q_nae']
nJ = collections.Counter(j['doc_id'] for j in J); nC = collections.Counter(c['doc_id'] for c in C)
documents = []
for d in D:
    m = Mfile.get(d['doc_id'], {})
    documents.append({'doc_id': d['doc_id'], 'institution_id': inst_of[d['doc_id']], 'jacme_no': d['no'], 'file': m.get('file', ''), 'url': m.get('url', ''),
                      'kind': d['kind'], 'review_type': d['review_type'], 'eval_year': d['eval_year'], 'created': d['created'],
                      'standard_version_declared': d['standard_ver'], 'standard_family': d['standard_family'],
                      'n_evaluators': d['n_evaluators'], 'n_subareas': d['n_subareas'], 'online': d['online'].lower(),
                      **{k: d.get(k, '') for k in CNT}, 'has_summary_counts': 'true' if d.get('b_comp') else 'false',
                      'n_judgments': nJ[d['doc_id']], 'n_comments': nC[d['doc_id']]})

# ---------- 審査イベント + 根拠 ----------
RE_RETRO = [re.compile(r'(\d{4})年当時の評価に、?(\d{4})[~～\-](\d{4})年(\d{1,2})?月?までの改善状況を併せて再評価を行った'),
            re.compile(r'(\d{4})年までの改善状況を併せて評価を行い')]
RE_MIXED = re.compile(r'Ver\.?([\d.]+)をもとに関連する領域である領域4\.1(?:および|及び)(?:領域)?4\.2に関し[^。]*。')
RE_VER = re.compile(r'Ver\.?\s*([\d.]+)')
def locate(flat_match, text):
    """空白を除いた一致文字列を、元テキスト中の位置へ戻す（空白を許す正規表現で再探索）。"""
    pat = r'\s*'.join(re.escape(ch) for ch in flat_match)
    m = re.search(pat, text)
    return (m.start(), m.end()) if m else ('', '')
ev_ids = assign('event', [f"event|{d['doc_id']}" for d in D])
events, evidence = [], []
for d in D:
    doc = d['doc_id']; ev = ev_ids[f'event|{doc}']
    t = norm(open(os.path.join(ROOT, 'text', doc + '.txt'), encoding='utf-8').read())
    intro = t[:3500]; flat = re.sub(r'\s+', '', intro)
    retro = mixed = 'unknown'; cutoff = obs_s = obs_e = 'unknown'; note = []; status = 'unknown'
    for rx in RE_RETRO:
        m = rx.search(flat)
        if m:
            retro = 'true'; status = 'heuristic_text'
            if rx is RE_RETRO[0]:
                obs_s = m[2]; obs_e = f'{m[3]}-{int(m[4]):02d}' if m[4] else m[3]
            else:
                obs_s = d['eval_year']; obs_e = m[1]
            cutoff = obs_e
            s, e = locate(m[0], t)
            evidence.append({'event_id': ev, 'doc_id': doc, 'flag': 'retrospective_reassessment', 'value': 'true', 'source_file': f'text/{doc}.txt', 'char_start': s, 'char_end': e, 'snippet': m[0]})
            break
    vers = sorted(set(RE_VER.findall(flat)))
    mm = RE_MIXED.search(flat)
    if mm and len(vers) > 1:
        mixed = 'true'; status = 'heuristic_text'
        s, e = locate(mm[0], t)
        evidence.append({'event_id': ev, 'doc_id': doc, 'flag': 'mixed_standard', 'value': 'true', 'source_file': f'text/{doc}.txt', 'char_start': s, 'char_end': e, 'snippet': mm[0]})
        note.append(f"領域4.1・4.2にVer.{mm[1]}を適用（宣言版は{d['standard_ver']}）。他領域の適用版は未確認")
    if d['review_type'] == 'notice': note.append('公表文（不認定）。下位領域判定なし')
    if d['review_type'] == 'additional': note.append('追加審査。判定は改善報告書に基づく再評価で、本審査時の判定は judgment_before')
    events.append({'event_id': ev, 'institution_id': inst_of[doc], 'doc_id': doc, 'review_type': d['review_type'], 'cycle': d['cycle'],
                   'eval_year': d['eval_year'], 'standard_version_declared': d['standard_ver'], 'standard_family': d['standard_family'],
                   'retrospective_reassessment': retro, 'mixed_standard': mixed, 'evidence_cutoff_date': cutoff,
                   'observation_start': obs_s, 'observation_end': obs_e, 'verification_status': status, 'note': '；'.join(note)})
ev_of = {e['doc_id']: e['event_id'] for e in events}
# Jev判定（scripts/14_flags_jev.py の出力）があればフラグはそれで決める。regex の結果は regex_* 列と根拠行に残し、不一致表と監査サンプルを書く。
JEV = os.path.join(PRIV, 'flag_judgments_jev.csv')
THRESH_TRUE, THRESH_FALSE = 0.8, 0.2   # noul 確率 → true / false / unknown
def to_flag(p):
    p = float(p); return 'true' if p >= THRESH_TRUE else ('false' if p <= THRESH_FALSE else 'unknown')
jev_rows = {r['doc_id']: r for r in csv.DictReader(open(JEV, encoding='utf-8'))} if os.path.exists(JEV) else {}
CLEF = os.path.join(PRIV, 'flag_judgments_clef.csv')   # 第2判定者（Cloudflare Clef 27B）。正本の値には使わず併記だけ
clef_rows = {r['doc_id']: r for r in csv.DictReader(open(CLEF, encoding='utf-8'))} if os.path.exists(CLEF) else {}
disagreements = []
for e in events:
    e['regex_retrospective'] = 'true' if e['retrospective_reassessment'] == 'true' else 'none'
    e['regex_mixed'] = 'true' if e['mixed_standard'] == 'true' else 'none'
    e.update({'flag_model': '', 'p_retrospective': '', 'p_mixed': '', 'mixed_subareas': '', 'mixed_subareas_choice': '', 'p_retro_clef': '', 'p_mixed_clef': '', 'clef_model': '', 'jev_clef_agree': ''})
    cr = clef_rows.get(e['doc_id'])
    if cr: e['p_retro_clef'] = cr['p_retrospective']; e['p_mixed_clef'] = cr['p_mixed']; e['clef_model'] = cr['model_returned']
    r = jev_rows.get(e['doc_id'])
    if not r:
        if jev_rows: e['retrospective_reassessment'] = e['mixed_standard'] = 'unknown'; e['verification_status'] = 'unknown'   # 判定対象外（公表文など）
        if e['review_type'] != 'main': e['retrospective_reassessment'] = 'not_applicable'   # 公表文
        if e['review_type'] == 'notice': e['mixed_standard'] = 'not_applicable'
        continue
    e['retrospective_reassessment'] = to_flag(r['p_retrospective']); e['mixed_standard'] = to_flag(r['p_mixed']); e['verification_status'] = 'model_jev'
    # 本人決定（2026-10-10）: 後年再評価は「本審査の判定が実地調査後の改善を含むか」を指す。追加審査は対象外（確率は保存するが写像しない）
    if e['review_type'] != 'main': e['retrospective_reassessment'] = 'not_applicable'
    e['flag_model'] = r['model_returned']; e['p_retrospective'] = r['p_retrospective']; e['p_mixed'] = r['p_mixed']
    e['mixed_subareas_choice'] = f"{r['which_choice']}@{r['which_confidence']}"   # choice の生の答え（mixed が unknown でも残す）
    # 上書き規則（本人承認 2026-10-10）: noul が閾値の間でも、choice が「別版の下位領域」を confidence 0.9 以上で選び、
    # かつ本文に版の明記（regex 根拠行）があれば mixed_standard=true とし、verification_status='jev_choice+text' を付ける。
    CHOICE_CONF = 0.9
    if (e['mixed_standard'] == 'unknown' and r['which_choice'] != 'none' and float(r['which_confidence'] or 0) >= CHOICE_CONF and e['regex_mixed'] == 'true'):
        e['mixed_standard'] = 'true'; e['verification_status'] = 'jev_choice+text'
    e['mixed_subareas'] = {'4.1_4.2': '4.1;4.2', 'other': 'other'}.get(r['which_choice'], '') if e['mixed_standard'] == 'true' else ''
    for flag, p, rx in (('retrospective_reassessment', r['p_retrospective'], e['regex_retrospective']), ('mixed_standard', r['p_mixed'], e['regex_mixed'])):
        if e[flag] == 'not_applicable': continue
        src = f"jev:{r['model_returned']}" + ('+choice+text' if flag == 'mixed_standard' and e['verification_status'] == 'jev_choice+text' else '')
        evidence.append({'event_id': e['event_id'], 'doc_id': e['doc_id'], 'flag': flag, 'value': e[flag], 'source_file': src, 'char_start': '', 'char_end': '',
                         'snippet': f"p={p}; choice={e['mixed_subareas_choice'] if flag == 'mixed_standard' else ''}; excerpts={r['excerpt_spans']}"})
        if (rx == 'true') != (e[flag] == 'true'):
            disagreements.append({'doc_id': e['doc_id'], 'event_id': e['event_id'], 'review_type': e['review_type'], 'eval_year': e['eval_year'], 'flag': flag, 'regex': rx, 'jev_flag': e[flag], 'jev_p': p, 'excerpt_spans': r['excerpt_spans']})
    if e['mixed_subareas'] == '4.1;4.2' and not e['note'].startswith('領域4.1・4.2'):
        e['note'] = ('領域4.1・4.2に別版を適用（Jev choice＋本文明記）；' + e['note']).rstrip('；')
for e in events:
    if e['p_retro_clef'] and e['verification_status'] in ('model_jev', 'jev_choice+text'):
        cf_r = to_flag(e['p_retro_clef']); cf_m = to_flag(e['p_mixed_clef'])
        r_ok = e['retrospective_reassessment'] == 'not_applicable' or e['retrospective_reassessment'] == cf_r
        e['jev_clef_agree'] = 'true' if (r_ok and e['mixed_standard'] == cf_m) else 'false'
EV_COLS = ['event_id', 'institution_id', 'doc_id', 'review_type', 'cycle', 'eval_year', 'standard_version_declared', 'standard_family', 'retrospective_reassessment', 'mixed_standard',
           'evidence_cutoff_date', 'observation_start', 'observation_end', 'verification_status', 'mixed_subareas', 'mixed_subareas_choice', 'flag_model', 'p_retrospective', 'p_mixed', 'regex_retrospective', 'regex_mixed', 'p_retro_clef', 'p_mixed_clef', 'clef_model', 'jev_clef_agree', 'note']
events = [{k: e[k] for k in EV_COLS} for e in events]
if jev_rows:
    import random
    rng = random.Random(0)
    judged = [e for e in events if e['verification_status'] in ('model_jev', 'jev_choice+text')]
    judged = [e for e in judged if e['review_type'] == 'main']   # 追加審査は後年再評価の対象外なので監査サンプルから外す
    trues = [e for e in judged if 'true' in (e['retrospective_reassessment'], e['mixed_standard'])]
    falses = [e for e in judged if e['retrospective_reassessment'] == 'false' and e['mixed_standard'] == 'false']
    dis_ids = {d['doc_id'] for d in disagreements}
    unknowns = [e for e in judged if 'unknown' in (e['retrospective_reassessment'], e['mixed_standard'])]
    pick = {e['doc_id']: e for e in trues + rng.sample(falses, min(10, len(falses))) + unknowns + [e for e in judged if e['doc_id'] in dis_ids]}
    PRESERVE = ['human_verdict_retro', 'human_verdict_mixed', 'human_note', 'chatgpt_verdict', 'chatgpt_note']
    audit_path = os.path.join(PRIV, 'flag_audit_sample')
    old_rows = {r['doc_id']: r for r in csv.DictReader(open(audit_path + '.csv', encoding='utf-8'))} if os.path.exists(audit_path + '.csv') else {}
    extra_cols = [c for c in (next(iter(old_rows.values())).keys() if old_rows else []) if c not in PRESERVE and c.startswith(('human_', 'chatgpt_'))]
    audit = []
    for e in pick.values():
        row = {'doc_id': e['doc_id'], 'event_id': e['event_id'], 'review_type': e['review_type'], 'eval_year': e['eval_year'], 'standard_version_declared': e['standard_version_declared'],
               'retrospective_reassessment': e['retrospective_reassessment'], 'p_retrospective': e['p_retrospective'], 'regex_retrospective': e['regex_retrospective'],
               'mixed_standard': e['mixed_standard'], 'p_mixed': e['p_mixed'], 'regex_mixed': e['regex_mixed'], 'mixed_subareas': e['mixed_subareas'], 'mixed_subareas_choice': e['mixed_subareas_choice'], 'verification_status': e['verification_status'],
               'reason': ';'.join(x for x, c in (('true', e in trues), ('false_sample', e in falses), ('unknown', e in unknowns), ('disagreement', e['doc_id'] in dis_ids)) if c),
               'excerpt_spans': jev_rows[e['doc_id']]['excerpt_spans'], 'source_txt': f"text/{e['doc_id']}.txt"}
        for c in PRESERVE + extra_cols: row[c] = old_rows.get(e['doc_id'], {}).get(c, '')   # 監査結果の列は引き継ぐ
        audit.append(row)
    # 行（doc_id の集合と生成値）が変わらなければ上書きしない
    gen_cols = [c for c in audit[0] if c not in PRESERVE + extra_cols]
    unchanged = set(old_rows) == {a['doc_id'] for a in audit} and all(all(str(old_rows[a['doc_id']].get(c, '')) == str(a[c]) for c in gen_cols) for a in audit)
    if not unchanged: wr(audit_path, audit, list(audit[0].keys()))
    print('flag_audit_sample:', 'unchanged (kept)' if unchanged else f'rewritten ({len(audit)} rows, verdict columns preserved)')
    wr(os.path.join(PRIV, 'flag_disagreements'), disagreements, ['doc_id', 'event_id', 'review_type', 'eval_year', 'flag', 'regex', 'jev_flag', 'jev_p', 'excerpt_spans'])

# ---------- 概念と基準項目の対応表 ----------
names = collections.defaultdict(collections.Counter)
for j in J: names[(j['standard_family'], j['subarea'])][j['subarea_name']] += 1
canon = {}
for (fam, sub), cnt in names.items():
    if fam.startswith('WFME2015'): canon[sub] = cnt.most_common(1)[0][0]
concepts = [{'concept_id': cid, 'area': cid.split('.')[0], 'name': canon[cid], 'name_basis': 'WFME2015系(Ver.2.x)の最頻名称', 'levels': 'B;Q'} for cid in sorted(canon, key=lambda x: tuple(map(int, x.split('.'))))]
cmap = {}
for j in J: cmap[(j['standard_family'], j['subarea'])] = j['concept_id']
standard_items = []
for (fam, sub) in sorted(names, key=lambda k: (k[0], tuple(map(int, k[1].split('.'))))):
    if not fam: continue
    cnt = names[(fam, sub)]; name = cnt.most_common(1)[0][0]; cid = cmap[(fam, sub)]
    rel = 'renumbered' if sub != cid else ('renamed' if re.sub(r'\s', '', name) != re.sub(r'\s', '', canon[cid]) else 'same')
    standard_items.append({'standard_family': fam, 'original_subarea': sub, 'original_name': name, 'name_variants': '|'.join(sorted(cnt)),
                           'concept_id': cid, 'concept_name': canon[cid], 'relation': rel, 'n_judgments': sum(cnt.values())})

# ---------- 判定 ----------
jg_ids = assign('judgment', [f"judg|{j['doc_id']}|{j['subarea']}|{j['level']}" for j in J])
judgments = [{'judgment_id': jg_ids[f"judg|{j['doc_id']}|{j['subarea']}|{j['level']}"], 'event_id': ev_of[j['doc_id']], 'institution_id': inst_of[j['doc_id']], 'doc_id': j['doc_id'],
              'concept_id': j['concept_id'], 'original_subarea': j['subarea'], 'original_subarea_name': j['subarea_name'], 'level': j['level'],
              'judgment': j['judgment'], 'judgment_before': j['judgment_before'], 'source_typo': j['source_typo'],
              'standard_family': j['standard_family'], 'review_type': j['review_type'], 'cycle': j['cycle']} for j in J]

# ---------- コメント（本文は private） ----------
ordn = collections.Counter(); ckeys = []
for c in C:
    g = (c['doc_id'], c['subarea'], c['level'], c['type']); ordn[g] += 1
    h = hashlib.sha256(c['text'].encode('utf-8')).hexdigest()
    c['_ord'] = ordn[g]; c['_sha'] = h
    c['_key'] = f"cmt|{c['doc_id']}|{c['subarea']}|{c['level']}|{c['type']}|{ordn[g]}|{h[:12]}"
cm_ids = assign('comment', [c['_key'] for c in C])
comments, comment_text = [], []
for c in C:
    cid = cm_ids[c['_key']]
    comments.append({'comment_id': cid, 'event_id': ev_of[c['doc_id']], 'institution_id': inst_of[c['doc_id']], 'doc_id': c['doc_id'], 'concept_id': c['concept_id'],
                     'original_subarea': c['subarea'], 'area': c['area'], 'level': c['level'], 'type': c['type'], 'tone': c['tone'], 'kind': c['kind'],
                     'ordinal': c['_ord'], 'text_len': len(c['text']), 'text_sha256': c['_sha'], 'review_type': c['review_type'], 'cycle': c['cycle'], 'standard_family': c['standard_family']})
    comment_text.append({'comment_id': cid, 'doc_id': c['doc_id'], 'text': c['text']})

# ---------- private: 総評・概評・評価チーム ----------
sohyo = [{'doc_id': d['doc_id'], 'text': d['sohyo']} for d in D if d.get('sohyo')]
gaihyo = [{'doc_id': g['doc_id'], 'area': g['area'], 'text': g['text']} for g in G]
ROLE = re.compile(r'^(主\s*査|副\s*査|評価員|委\s*員|評価者)\s*')
evaluators = []
for d in D:
    t = norm(open(os.path.join(ROOT, 'text', d['doc_id'] + '.txt'), encoding='utf-8').read())
    i = t.find('評価チーム'); m0 = re.search(r'^\s*主\s*査', t, re.M)
    start = i if i >= 0 else (m0.start() if m0 else -1)
    if start < 0: continue
    role = ''
    for ln in t[start:start + 1200].split('\n')[(1 if i >= 0 else 0):]:
        s = ln.strip()
        if not s: continue
        if re.fullmatch(r'\d{1,3}', s) or re.match(r'^(総評|\d\.|１\.|概評|はじめに)', s): break
        rm = ROLE.match(s)
        if rm: role = rm[1].replace(' ', ''); s = s[rm.end():]
        # 氏名: 和文（拡張漢字・互換漢字を含む）または欧文。それ以外の行（所属など）は読み飛ばす
        if re.fullmatch(r'[A-Za-z][A-Za-z .\-]{2,40}', s): evaluators.append({'doc_id': d['doc_id'], 'role': role, 'name': re.sub(r'\s+', ' ', s)}); continue
        s = re.sub(r'\s+', '', s)
        if 2 <= len(s) <= 10 and re.fullmatch(r'[぀-ヿ㐀-䶿一-鿿豈-﫿\U00020000-\U0002ffff々ヶ]+', s): evaluators.append({'doc_id': d['doc_id'], 'role': role, 'name': s})

# ---------- 書き出し ----------
wr(os.path.join(CAN, 'institutions'), institutions, list(institutions[0].keys()))
wr(os.path.join(CAN, 'source_manifest'), source_manifest, list(source_manifest[0].keys()))
wr(os.path.join(CAN, 'documents'), documents, list(documents[0].keys()))
wr(os.path.join(CAN, 'review_events'), events, list(events[0].keys()))
wr(os.path.join(CAN, 'concepts'), concepts, list(concepts[0].keys()))
wr(os.path.join(CAN, 'standard_items'), standard_items, list(standard_items[0].keys()))
wr(os.path.join(CAN, 'judgments'), judgments, list(judgments[0].keys()))
wr(os.path.join(CAN, 'comments'), comments, list(comments[0].keys()))
if Q: wr(os.path.join(CAN, 'quarantine_judgments'), Q, list(Q[0].keys()))
wr(os.path.join(PRIV, 'comment_text'), comment_text, ['comment_id', 'doc_id', 'text'])
wr(os.path.join(PRIV, 'sohyo'), sohyo, ['doc_id', 'text'])
wr(os.path.join(PRIV, 'area_gaihyo'), gaihyo, ['doc_id', 'area', 'text'])
wr(os.path.join(PRIV, 'event_evidence'), evidence, ['event_id', 'doc_id', 'flag', 'value', 'source_file', 'char_start', 'char_end', 'snippet'])
wr(os.path.join(PRIV, 'evaluators'), evaluators, ['doc_id', 'role', 'name'])
json.dump(idmap, open(MAP_PATH, 'w', encoding='utf-8'), ensure_ascii=False, indent=0, sort_keys=True)
json.dump({'built_at': datetime.datetime.now().isoformat(timespec='seconds'), 'fetched_date': FETCHED,
           'counts': {'institutions': len(institutions), 'source_manifest': len(source_manifest), 'documents': len(documents), 'review_events': len(events),
                      'concepts': len(concepts), 'standard_items': len(standard_items), 'judgments': len(judgments), 'comments': len(comments),
                      'quarantine_judgments': len(Q), 'event_evidence': len(evidence), 'evaluators': len(evaluators)},
           'flags': {'retrospective_reassessment': dict(collections.Counter(e['retrospective_reassessment'] for e in events)),
                     'mixed_standard': dict(collections.Counter(e['mixed_standard'] for e in events)),
                     'regex_vs_jev_disagreements': len(disagreements), 'flag_source': 'jev' if jev_rows else 'regex'}},
          open(os.path.join(CAN, 'build_info.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(json.dumps(json.load(open(os.path.join(CAN, 'build_info.json'))), ensure_ascii=False, indent=1))
