"""IRパイロットのページ生成。
- review/site/ : 本人確認用のローカル静的ページ（草稿バナー付き、承認前のカードも表示）。公開しない。
- docs/pilot_ir_cards_review.md : 確認用パケット（カード全文と PDF ページへのリンク、承認／修正の記入欄）。
- 近接言い換え検査: カード文と原文（コメント・総評・概評）の連続8文字一致を、主体名（actors.label/aliases）と下位領域名を除いたうえで検出し、結果を表示する。
公開側（public/data/practice_cards.json）は scripts/13 が approved=true のカードだけを出す。
使い方: python3 scripts/24_pilot_pages.py
"""
import csv, json, os, re, collections, html, datetime, unicodedata
import yaml
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAN = os.path.join(ROOT, 'canonical'); PRIV = os.path.join(CAN, 'private'); PIL = os.path.join(CAN, 'pilot_ir'); REV = os.path.join(ROOT, 'review', 'site')
os.makedirs(REV, exist_ok=True)
def rd(p):
    with open(p, encoding='utf-8') as f: return list(csv.DictReader(f))
CB = yaml.safe_load(open(os.path.join(CAN, 'codebook', 'practices_v0.2.yaml'), encoding='utf-8'))
SEC = CB['tables']['public_practice_cards']['sections']
I = {i['institution_id']: i for i in rd(os.path.join(CAN, 'institutions.csv'))}; D = {d['doc_id']: d for d in rd(os.path.join(CAN, 'documents.csv'))}; E = {e['doc_id']: e for e in rd(os.path.join(CAN, 'review_events.csv'))}
CONCEPT = {r['concept_id']: r['name'] for r in rd(os.path.join(CAN, 'concepts.csv'))}
A = {a['actor_id']: a for a in rd(os.path.join(PIL, 'actors.csv'))}; PR = {p['practice_id']: p for p in rd(os.path.join(PIL, 'practices.csv'))}
PO = rd(os.path.join(PIL, 'practice_observations.csv')); AR = rd(os.path.join(PIL, 'actor_relations.csv')); PL = rd(os.path.join(PIL, 'practice_links.csv')); CARDS = rd(os.path.join(PIL, 'public_practice_cards.csv'))
ES = {r['span_id']: r for r in rd(os.path.join(PRIV, 'evidence_spans.csv'))}
J = rd(os.path.join(CAN, 'judgments.csv'))
PILOT_DOCS = ['evaluation_report17', 'evaluation_report101', 'evaluation_report5', 'evaluation_report_02_01', 'evaluation_report39', 'evaluation_report116', 'evaluation_report9', 'evaluation_report_02_05', 'evaluation_report108', 'evaluation_report16', 'evaluation_report72', 'evaluation_report90', 'evaluation_report98', 'evaluation_report97']
PILOT_INST = list(dict.fromkeys(D[d]['institution_id'] for d in PILOT_DOCS))
esc = html.escape
def src_link(span_id):
    s = ES[span_id]; d = D[s['doc_id']]
    return f'<a href="{esc(d["url"])}#page={s["pdf_page_start"]}" target="_blank" rel="noopener">{esc(s["doc_id"])} p.{s["pdf_page_start"]}</a>'
def src_md(span_id):
    s = ES[span_id]; d = D[s['doc_id']]
    return f'[{s["doc_id"]} p.{s["pdf_page_start"]}]({d["url"]}#page={s["pdf_page_start"]})'
CSS = '''body{font-family:"Hiragino Sans","BIZ UDPGothic",sans-serif;max-width:960px;margin:0 auto;padding:16px;color:#1f2933;background:#fff;line-height:1.7}
.banner{background:#fff6e0;color:#7a5600;border:1px solid #f0d78c;padding:10px 14px;border-radius:6px;margin-bottom:16px}
h1{font-size:22px}h2{font-size:17px;margin-top:28px}h3{font-size:15px}table{border-collapse:collapse;width:100%;font-size:14px}th,td{border-bottom:1px solid #d9dee3;padding:6px 8px;text-align:left;vertical-align:top}th{background:#f5f7f9}
.card{border:1px solid #d9dee3;border-radius:8px;padding:14px 16px;margin:14px 0}.card h3{margin:0 0 8px}.sec{margin:6px 0}.sec b{color:#52606d}.hyp{background:#f5f7f9;border-left:3px solid #7b8794;padding:6px 10px}.small{font-size:13px;color:#52606d}
nav a{margin-right:14px}.tag{display:inline-block;font-size:12px;padding:1px 6px;border-radius:10px;background:#f5f7f9;border:1px solid #d9dee3}'''
BANNER = '<div class="banner">草稿（本人確認前）。公開していない。カードの文章はこちらの要約であり、原文の引用ではない。各記載は出典の PDF ページで確認する。</div>'
def page(title, body, nav=True):
    n = '<nav><a href="index.html">カード一覧</a><a href="timelines.html">大学別の経時</a><a href="additional.html">追加審査の前後</a></nav>' if nav else ''
    return f'<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{esc(title)}</title><style>{CSS}</style></head><body>{BANNER}{n}<h1>{esc(title)}</h1>{body}<p class="small">生成 {datetime.date.today()}（scripts/24_pilot_pages.py）</p></body></html>'
def refs_html(text):
    return re.sub(r'\[(ES-\d{6})\]', lambda m: f'<sup>[{src_link(m.group(1))}]</sup>' if m.group(1) in ES else m.group(0), esc(text))
def card_html(c):
    secs = ''.join(f'<div class="sec"><b>{esc(SEC[k])}</b><br>{refs_html(c[k])}</div>' for k in ('summary', 'mechanism', 'actors_flow', 'reached', 'reservations', 'unknowns') if c.get(k))
    hyp = f'<div class="sec hyp"><b>{esc(SEC["hypothesis_links"])}</b><br>{refs_html(c["hypothesis_links"])}</div>' if c.get('hypothesis_links') else ''
    if c.get('footnote'): hyp += f'<div class="sec small">注: {esc(c["footnote"])}</div>'
    src = '<div class="sec"><b>出典</b><br>' + '、'.join(src_link(s) for s in c['span_ids'].split(';') if s in ES) + '</div>'
    st = f'<span class="tag">{"承認済み" if c["approved"] == "true" else "草稿 " + esc(c["version"])}</span>'
    return f'<div class="card" id="{c["card_id"]}"><h3>{esc(c["card_id"])} {esc(c["title"])} {st}</h3><div class="small">{esc(I[c["institution_id"]]["name"])} / {esc(PR[c["practice_id"]]["title"])}</div>{secs}{hyp}{src}</div>'
# ---------- カード一覧 ----------
body = '<p>6大学12枚。対照的な型（体制のみ、要求の継続、局所的な利用と全体の課題の併存）を含む。</p>' + ''.join(card_html(c) for c in CARDS)
open(os.path.join(REV, 'index.html'), 'w', encoding='utf-8').write(page('IR・内部質保証: 取り組みカード（草稿）', body))
# ---------- 大学別の経時 ----------
rows = []
for inst in PILOT_INST:
    docs = sorted([d for d in PILOT_DOCS if D[d]['institution_id'] == inst], key=lambda d: (E[d]['eval_year'], d))
    rows.append(f'<h2>{esc(I[inst]["name"])}</h2>')
    rows.append('<table><tr><th>年度</th><th>審査</th><th>基準版</th><th>観察期間</th><th>7.1B / 9.0B の判定</th><th>この大学の観察（obs_id: 種別 / 段階 / 結果利用）</th></tr>')
    for d in docs:
        e = E[d]; jb = {(j['concept_id'], j['level']): j for j in J if j['doc_id'] == d}
        jj = lambda c: (jb.get((c, 'B'), {}).get('judgment', '—') + ('←' + jb[(c, 'B')]['judgment_before'] if jb.get((c, 'B'), {}).get('judgment_before') else ''))
        obs = [o for o in PO if o['doc_id'] == d]
        ol = '<br>'.join(f"{o['obs_id']}: {o['claim_type']} / {o['stage']} / {o['result_use']}（{o['statement_time_role']}）" for o in obs) or '—'
        period = f"{e['observation_start']}〜{e['observation_end']}" if e['retrospective_reassessment'] == 'true' else '—'
        rows.append(f'<tr><td>{esc(e["eval_year"])}</td><td>{esc(e["review_type"])}{(" 第" + e["cycle"] + "巡") if e["cycle"] else ""}</td><td>{esc(e["standard_version_declared"])}</td><td>{esc(period)}{"（後年再評価）" if e["retrospective_reassessment"] == "true" else ""}</td><td>7.1B {jj("7.1")} / 9.0B {jj("9.0")}</td><td class="small">{ol}</td></tr>')
    rows.append('</table>')
    links = [l for l in PL if any(o['obs_id'] == l['from_obs_id'] and D[o['doc_id']]['institution_id'] == inst for o in PO)]
    if links: rows.append('<p class="small">対応づけ: ' + '；'.join(f"{l['link_id']} {l['from_obs_id']}→{l['to_obs_id']} {l['link_type']}（{l['basis']}）" for l in links) + '</p>')
open(os.path.join(REV, 'timelines.html'), 'w', encoding='utf-8').write(page('大学別の経時（草稿）', ''.join(rows)))
# ---------- 追加審査の前後 ----------
rows = []
for d in ['evaluation_report108', 'evaluation_report72', 'evaluation_report97']:
    inst = D[d]['institution_id']; rows.append(f'<h2>{esc(I[inst]["name"])} {esc(d)}（{esc(E[d]["eval_year"])}年度 追加審査）</h2>')
    rows.append('<table><tr><th>下位領域</th><th>水準</th><th>本審査時</th><th>追加審査</th><th>変化</th></tr>')
    for j in sorted([j for j in J if j['doc_id'] == d and j['judgment_before']], key=lambda j: (tuple(map(int, j['concept_id'].split('.'))), j['level'])):
        ch = '改善' if (j['judgment_before'], j['judgment']) in (('不適合', '部分的適合'), ('部分的適合', '適合'), ('不適合', '適合')) else ('変化なし' if j['judgment_before'] == j['judgment'] else '低下')
        rows.append(f'<tr><td>{j["concept_id"]} {esc(CONCEPT.get(j["concept_id"], ""))}</td><td>{j["level"]}</td><td>{esc(j["judgment_before"])}</td><td>{esc(j["judgment"])}</td><td>{ch}</td></tr>')
    rows.append('</table>')
    obs = [o for o in PO if o['doc_id'] == d]
    if obs: rows.append('<p class="small">この文書の観察: ' + '；'.join(f"{o['obs_id']} {o['claim_type']}/{o['stage']}（{o['statement_time_role']}）" for o in obs) + '</p>')
open(os.path.join(REV, 'additional.html'), 'w', encoding='utf-8').write(page('追加審査の前後（草稿）', ''.join(rows) + '<p class="small">「変化」は判定の文字列の比較で、追加審査は改善報告書に基づく再評価であり本審査とは手続きが異なる。</p>'))
# ---------- 近接言い換え検査（草稿） ----------
def squash(s): return ''.join(ch for ch in unicodedata.normalize('NFKC', s) if not ch.isspace())
CT = {r['comment_id']: r['text'] for r in rd(os.path.join(PRIV, 'comment_text.csv'))}
src12 = set()
for r in list(CT.items()) + [(r['doc_id'], r['text']) for r in rd(os.path.join(PRIV, 'sohyo.csv')) + rd(os.path.join(PRIV, 'area_gaihyo.csv'))]:
    t = squash(r[1]); src12.update(t[i:i + 12] for i in range(0, max(0, len(t) - 11)))
def own_src8(c):   # カードの出典スパンの本文（コメント）と8文字
    s8 = set()
    for sid in c['span_ids'].split(';'):
        if sid in ES and ES[sid]['segment_type'] == 'comment':
            t = squash(CT.get(ES[sid]['ref_id'], '')); s8.update(t[i:i + 8] for i in range(0, max(0, len(t) - 7)))
    return s8
exempt = sorted({squash(x) for a in A.values() for x in [a['label']] + a['aliases'].split(';') if x} | {squash(v) for v in CONCEPT.values()} | {'評価を実施せず', '質的向上のための水準', '基本的水準', '部分的適合'} | {squash(t) for t in CB.get('paraphrase_check', {}).get('criteria_terms', [])}, key=len, reverse=True)
report = []
for c in CARDS:
    body = squash(re.sub(r'\[ES-\d{6}\]', '', ' '.join(c.get(k, '') for k in ('title', 'summary', 'mechanism', 'actors_flow', 'reached', 'reservations', 'unknowns', 'hypothesis_links'))))
    for ex in exempt: body = body.replace(ex, '＊')
    s8 = own_src8(c)
    hits = sorted({body[i:i + 8] for i in range(0, max(0, len(body) - 7)) if '＊' not in body[i:i + 8] and body[i:i + 8] in s8} | {body[i:i + 12] for i in range(0, max(0, len(body) - 11)) if '＊' not in body[i:i + 12] and body[i:i + 12] in src12})
    report.append((c['card_id'], hits))
# ---------- 確認用パケット ----------
md = ['# IR・内部質保証 取り組みカード 確認用（草稿、2026-10-10）', '', 'カードの文章はこちらの要約で、原文の引用はしない。各節の記載を出典の PDF ページ（リンク）で確認し、末尾の欄に 承認／修正 と注記を書いてください。承認されたカードだけ公開する（approved=true に更新）。', '',
      '近接言い換え検査（出典コメントと連続8文字、コーパス全体と連続12文字の一致。主体名・下位領域名は除外）: ' + ('違反なし' if all(not h for _, h in report) else '；'.join(f'{cid}: {h}' for cid, h in report if h)), '']
for c in CARDS:
    md += [f'## {c["card_id"]} {c["title"]}', '', f'大学: {I[c["institution_id"]]["name"]} / 取り組み: {PR[c["practice_id"]]["title"]} / 版: {c["version"]} / approved: {c["approved"]}', '']
    for k in ('summary', 'mechanism', 'actors_flow', 'reached', 'reservations', 'unknowns'): md += [f'**{SEC[k]}** {c[k]}', '']
    md += [f'**{SEC["hypothesis_links"]}** {c["hypothesis_links"]}', '', f'注: {c.get("footnote", "")}', '', '**出典** ' + '、'.join(src_md(s) for s in c['span_ids'].split(';') if s in ES), '', '判定: [ ] 承認  [ ] 修正  注記: ', '']
open(os.path.join(ROOT, 'docs', 'pilot_ir_cards_review.md'), 'w', encoding='utf-8').write('\n'.join(md) + '\n')
# ---------- 判定パケット v2（カード＋リンクした全スパンの本文。評価員氏名なし） ----------
RAW = {}
def span_text(sid):
    r = ES[sid]; d = r['doc_id']
    if r['segment_type'] == 'comment': return CT.get(r['ref_id'], '')
    RAW.setdefault(d, open(os.path.join(ROOT, 'text', d + '.txt'), encoding='utf-8').read())
    return ' '.join(RAW[d][int(r['char_start']):int(r['char_end'])].split())
pk = ['# 取り組みカード 判定パケット v2（draft-2、2026-10-10）', '', '各カードの文章と、カードがリンクした出典スパンの本文（コメント、判定行、時点の根拠）をすべて載せる。評価員氏名は含まない。カード文の各事実文には [ES-id] を付けている。', '', f'近接言い換え検査: ' + ('違反なし' if all(not h for _, h in report) else '；'.join(f'{cid}: {h}' for cid, h in report if h)), '']
for c in CARDS:
    pk += [f'## {c["card_id"]} {c["title"]}', '', f'大学: {I[c["institution_id"]]["name"]} / 版: {c["version"]}', '']
    for k in ('summary', 'mechanism', 'actors_flow', 'reached', 'reservations', 'unknowns', 'hypothesis_links'): pk += [f'**{SEC[k]}** {c[k]}', '']
    pk += [f'注: {c.get("footnote", "")}', '', '### リンクした出典スパン', '', '| span | 文書 / PDF頁 | 種別 / 節 | 本文 |', '|---|---|---|---|']
    for sid in c['span_ids'].split(';'):
        if sid not in ES: pk.append(f'| {sid} | （不明） | | |'); continue
        r = ES[sid]; e = E[r['doc_id']]
        sec = f"{r['segment_type']} {r['subarea']}{r['level']} {r['comment_type']}".strip()
        pk.append(f"| {sid} | {r['doc_id']}（{e['eval_year']}、{e['review_type']}）p.{r['pdf_page_start']} | {sec} | {span_text(sid).replace('|', '｜')} |")
    pk.append('')
os.makedirs(os.path.join(ROOT, 'consult', 'audit'), exist_ok=True)
open(os.path.join(ROOT, 'consult', 'audit', 'cards_judgment_packet_v2.md'), 'w', encoding='utf-8').write('\n'.join(pk) + '\n')
print(json.dumps({'cards': len(CARDS), 'approved': sum(1 for c in CARDS if c['approved'] == 'true'), 'review_site': REV, 'paraphrase_hits': {cid: h for cid, h in report if h}}, ensure_ascii=False, indent=1))
