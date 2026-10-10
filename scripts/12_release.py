"""研究リリースを生成する: releases/<version>/ に SQLite（全表、private本文、FTS5）、RELEASE.md、Datasette用 metadata.json と起動スクリプト。
使い方: python3 scripts/12_release.py [version]   既定 jacme-2026.10.0
前提: scripts/11_validate_canonical.py が通っていること（validation_report.json の n_fail==0 を確認する）。"""
import csv, json, os, sys, sqlite3, hashlib, datetime, shutil, collections
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAN = os.path.join(ROOT, 'canonical'); PRIV = os.path.join(CAN, 'private')
VERSION = sys.argv[1] if len(sys.argv) > 1 else 'jacme-2026.10.0'
OUT = os.path.join(ROOT, 'releases', VERSION)
rep = json.load(open(os.path.join(CAN, 'validation_report.json'), encoding='utf-8'))
if rep['n_fail']: sys.exit(f"validation_report.json に失敗 {rep['n_fail']} 件。リリースを中止")
os.makedirs(OUT, exist_ok=True)
DB = os.path.join(OUT, 'jacme.sqlite')
if os.path.exists(DB): os.remove(DB)

def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()
def rd(p):
    with open(p, encoding='utf-8') as f: r = csv.DictReader(f); return r.fieldnames, list(r)
INT = {'size_bytes', 'n_documents', 'n_main_reviews', 'n_subareas', 'n_judgments', 'n_comments', 'n_evaluators', 'ordinal', 'text_len', 'char_start', 'char_end', 'n_judgments',
       'b_comp', 'b_part', 'b_non', 'b_nae', 'q_comp', 'q_part', 'q_non', 'q_nae', 'eval_year', 'cycle', 'jacme_no', 'area'}
REAL = {'prob', 'threshold', 'function_confidence', 'observed_confidence', 'requested_confidence', 'multi_function_p_exploratory', 'outcome_confirmed_p', 'multi_function_p', 'seconds', 'p_retrospective', 'p_mixed', 'p_retro_clef', 'p_mixed_clef'}
PK = {'institutions': 'institution_id', 'documents': 'doc_id', 'review_events': 'event_id', 'concepts': 'concept_id', 'judgments': 'judgment_id', 'comments': 'comment_id', 'comment_text': 'comment_id'}
con = sqlite3.connect(DB)
inputs = []
def load(table, path):
    fields, rows = rd(path); inputs.append((os.path.relpath(path, ROOT), sha(path), len(rows)))
    cols = ', '.join(f'"{c}" {"INTEGER" if c in INT else "REAL" if c in REAL else "TEXT"}' + (' PRIMARY KEY' if PK.get(table) == c else '') for c in fields)
    con.execute(f'CREATE TABLE "{table}" ({cols})')
    def conv(c, v):
        if c in INT: return int(v) if v not in ('', 'unknown') else None
        if c in REAL: return float(v) if v not in ('', 'unknown', 'None') else None
        return v
    con.executemany(f'INSERT INTO "{table}" VALUES ({",".join("?"*len(fields))})', [[conv(c, r[c]) for c in fields] for r in rows])
    return len(rows)
counts = {}
for t in ['institutions', 'source_manifest', 'documents', 'review_events', 'concepts', 'standard_items', 'judgments', 'comments', 'quarantine_judgments', 'comment_tags', 'comment_classes']:
    p = os.path.join(CAN, t + '.csv')
    if os.path.exists(p): counts[t] = load(t, p)
for t in ['comment_text', 'sohyo', 'area_gaihyo', 'event_evidence', 'evaluators', 'comment_tag_probs']:
    if os.path.exists(os.path.join(PRIV, t + '.csv')): counts[t] = load(t, os.path.join(PRIV, t + '.csv'))
# 索引
for t, c in ([('comment_tags', 'comment_id'), ('comment_tags', 'theme')] if 'comment_tags' in counts else []) + [('judgments', 'doc_id'), ('judgments', 'concept_id'), ('judgments', 'event_id'), ('comments', 'doc_id'), ('comments', 'concept_id'), ('comments', 'event_id'), ('documents', 'institution_id'), ('review_events', 'institution_id')]:
    con.execute(f'CREATE INDEX idx_{t}_{c} ON "{t}"("{c}")')
# 全文検索: trigram（3文字未満の語は一致しない）。短語は short_term_hits か LIKE を使う。
con.execute("CREATE VIRTUAL TABLE comment_fts USING fts5(text, content='comment_text', content_rowid='rowid', tokenize='trigram')")
con.execute("INSERT INTO comment_fts(comment_fts) VALUES('rebuild')")
SHORT = ['IR', 'FD', 'AI', 'SD', 'IT', 'SP', 'GP', 'e-', 'IP', 'EQ']
con.execute('CREATE TABLE short_term_hits (term TEXT, comment_id TEXT)')
for term in SHORT:
    con.execute("INSERT INTO short_term_hits SELECT ?, comment_id FROM comment_text WHERE instr(text, ?) > 0", (term, term))
con.execute('CREATE INDEX idx_short_term ON short_term_hits(term)')
# 便利ビュー（本文を含むので研究者限定）
con.execute('''CREATE VIEW comment_full AS SELECT c.*, t.text, i.name AS institution_name, d.url AS source_url
  FROM comments c JOIN comment_text t USING(comment_id) JOIN institutions i USING(institution_id) JOIN documents d ON d.doc_id=c.doc_id''')
con.execute('''CREATE VIEW judgment_full AS SELECT j.*, i.name AS institution_name, k.name AS concept_name, e.eval_year AS event_year, e.retrospective_reassessment, e.mixed_standard, d.url AS source_url
  FROM judgments j JOIN institutions i USING(institution_id) JOIN concepts k USING(concept_id) JOIN review_events e USING(event_id) JOIN documents d ON d.doc_id=j.doc_id''')
con.execute('CREATE TABLE release_info (key TEXT PRIMARY KEY, value TEXT)')
con.executemany('INSERT INTO release_info VALUES (?,?)', [('version', VERSION), ('built_at', datetime.datetime.now().isoformat(timespec='seconds')), ('layer', 'research-private'),
                                                          ('note', '本文・総評・評価チーム氏名を含む非公開層。再配布しない。')])
con.commit()
n_short = {t: con.execute('SELECT count(*) FROM short_term_hits WHERE term=?', (t,)).fetchone()[0] for t in SHORT}
fts_test = con.execute("SELECT count(*) FROM comment_fts WHERE comment_fts MATCH ?", ('診療参加型',)).fetchone()[0]
con.close()
shutil.copy(os.path.join(CAN, 'validation_report.json'), os.path.join(OUT, 'validation_report.json'))
shutil.copy(os.path.join(CAN, 'id_map.json'), os.path.join(OUT, 'id_map.json'))
flags = json.load(open(os.path.join(CAN, 'build_info.json'), encoding='utf-8'))['flags']
md = [f'# {VERSION}', '', f'生成日時: {datetime.datetime.now().isoformat(timespec="seconds")}', '層: 研究者限定（本文を含む。再配布しない）', '',
      '## 入力（canonical/）とSHA-256', '', '| ファイル | 行数 | SHA-256 |', '|---|---|---|'] + [f'| {p} | {n} | `{h}` |' for p, h, n in inputs] + [
      '', '## 表と件数', '', '| 表 | 件数 |', '|---|---|'] + [f'| {t} | {n} |' for t, n in counts.items()] + [
      '', '## 検証', '', f"- 検査 {rep['n_checks']} 件、失敗 {rep['n_fail']} 件（validation_report.json）", f"- 総評集計との照合: {rep['summary_counts_checked']} 文書で確認、不一致 {rep['summary_counts_mismatch']}",
      f"- フラグ分布: retrospective_reassessment={flags['retrospective_reassessment']}, mixed_standard={flags['mixed_standard']}（Jev jev-1.13.0 の noul 確率を閾値 0.8/0.2 で true/false/unknown に写像。確率は正解率ではない。人手確認は未了で private/flag_audit_sample.csv に監査票がある）",
      '', '## 全文検索', '', '- `comment_fts` は FTS5 trigram。3文字未満の語（IR、FD、AI など）は MATCH で一致しないため、`short_term_hits`（事前計算: ' + ', '.join(f'{k}={v}' for k, v in n_short.items()) + '）または `WHERE text LIKE \'%IR%\'` を使う。',
      f'- 動作確認: `MATCH \'診療参加型\'` → {fts_test} 件', '', '## 使い方', '', '```', f'sqlite3 releases/{VERSION}/jacme.sqlite', f'bash releases/{VERSION}/run_datasette.sh   # 127.0.0.1:8001 のみ', '```', '',
      '## 既知の未確認事項', '', '- retrospective_reassessment は「本審査の判定が実地調査後の改善を含むか」。追加審査・公表文は not_applicable（本人決定 2026-10-10）。値は Jev（型付き判定）の確率を 0.8/0.2 で写像、0.2〜0.8 は unknown。人手確認は未了（private/flag_audit_sample.csv）。', '- mixed_standard の上書き規則（本人承認 2026-10-10）: noul が 0.2〜0.8 でも、choice が別版の下位領域を confidence 0.9 以上で選び、本文に版の明記（regex 根拠）があれば true（verification_status=jev_choice+text）。該当 41, 47, 48, 49, 50, 51。', '- observation_start/end は後年再評価の文書だけ本文から取得。他は unknown。',
      '- 版混在文書（6件）で領域4.1・4.2以外の適用版は未確認。', '- quarantine_judgments（report72 5.2 B）は原本確認待ち。', '- 取り組みカード（canonical/pilot_ir/public_practice_cards.csv）は別モデル（ChatGPT）の盲検判定を経て公開。人による全件確認は未了。', '- comment_tags / comment_classes は Jev（codebook v1.1）の自動タグ。妥当性の確認は別モデル（ChatGPT）による盲検判定との比較（60件×3回）であり、人の参照判定ではない。T11・T13 の閾値は pilot03 を見て決めたため独立検証がなく信頼性が低い。scope・multi_function・secondary_function は探索的（集計の主張に使わない）。']
open(os.path.join(OUT, 'RELEASE.md'), 'w', encoding='utf-8').write('\n'.join(md) + '\n')
# 機械生成のリリース manifest: 構成要素ごとの状態（implemented / data_generated / validated / published）
gate_p = os.path.join(CAN, 'tag_tables_manifest.json'); gate = json.load(open(gate_p, encoding='utf-8')) if os.path.exists(gate_p) else {}
cb_p = os.path.join(CAN, 'codebook', 'codebook_v1.1.yaml'); cb = __import__('yaml').safe_load(open(cb_p, encoding='utf-8')) if os.path.exists(cb_p) else {}
pub_leak = os.path.join(ROOT, 'public', 'leak_check.json'); leak = json.load(open(pub_leak, encoding='utf-8')) if os.path.exists(pub_leak) else {}
pub_has_tags = os.path.exists(os.path.join(ROOT, 'public', 'data', 'theme_counts.json'))
def comp(name, implemented, generated, validated, published, **extra):
    return {'component': name, 'implemented': implemented, 'data_generated': generated, 'validated': validated, 'published': published, **extra}
ev_flags = collections.Counter((r['retrospective_reassessment'], r['mixed_standard']) for r in rd(os.path.join(CAN, 'review_events.csv'))[1])
manifest = {'version': VERSION, 'built_at': datetime.datetime.now().isoformat(timespec='seconds'), 'layer_note': 'published = public/data を生成済み（配備はしていない）。validated = 11_validate_canonical.py の自動検査を通過。監査（ChatGPT 盲検判定との比較）は validated と別に audit に書く',
    'components': [
        comp('documents_judgments_comments', True, True, rep['n_fail'] == 0, pub_has_tags or os.path.exists(os.path.join(ROOT, 'public', 'data', 'judgments.json')), counts={k: counts[k] for k in ('documents', 'judgments', 'comments') if k in counts}),
        comp('review_event_flags', True, True, rep['n_fail'] == 0, True, model='jev-1.13.0 (source of record) + clef (second rater)', thresholds={'true': 0.8, 'false': 0.2, 'override': 'choice>=0.9 & text evidence'},
             counts=dict(flags), audit='flag_audit_sample.csv 32件、人手確認は未了'),
        comp('comment_tags', 'comment_tags' in counts, 'comment_tags' in counts, rep['n_fail'] == 0 and rep.get('tag_tables_checked', False), pub_has_tags,
             model=', '.join(gate.get('models_in_run', [])), codebook=gate.get('codebook_version_current'), thresholds=gate.get('thresholds_current'), gate_complete=gate.get('complete'),
             counts={k: counts[k] for k in ('comment_tags', 'comment_classes') if k in counts},
             audit='別モデル（ChatGPT）による盲検判定との比較（60件×3回: pilot01 v0、pilot02 v1、pilot03 v1.1）。人の参照判定ではない。T11・T13 の閾値は pilot03 を見て決めたため独立検証なし',
             exploratory=['observed_scope', 'requested_scope', 'multi_function', 'secondary_function']),
        comp('public_export', True, os.path.exists(os.path.join(ROOT, 'public', 'data')), leak.get('n_violations') == 0 if leak else False, os.path.exists(os.path.join(ROOT, 'public', 'data')),
             leak_check=({k: leak[k] for k in ('checked_files', 'n_needles', 'n_violations', 'checked_at')} if leak else None), deployed=False),
        comp('public_site_prototype', True, True, False, False, screens=['index.html', 'matrix.html', 'stats.html'], note='ローカル確認のみ。配備していない'),
    ],
    'validation': {'n_checks': rep['n_checks'], 'n_fail': rep['n_fail']}, 'inputs': [{'path': p_, 'sha256': h, 'rows': n} for p_, h, n in inputs]}
json.dump(manifest, open(os.path.join(OUT, 'MANIFEST.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
json.dump({'title': f'JACME評価報告書コーパス {VERSION}（研究者限定）', 'description': '本文を含む非公開層。127.0.0.1 のみで起動し、外部公開しない。',
           'databases': {'jacme': {'tables': {'comment_text': {'description': 'コメント本文（非公開）'}, 'sohyo': {'description': '総評本文（非公開）'}, 'evaluators': {'description': '評価チーム（分析単位にしない）'}}}}},
          open(os.path.join(OUT, 'metadata.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
open(os.path.join(OUT, 'run_datasette.sh'), 'w').write(f'''#!/bin/bash
# 研究者限定の閲覧。ローカルホストのみに束縛し、外部公開・Tailscale設定は行わない。
cd "$(dirname "$0")"
DS="${{HOME}}/Library/Python/3.9/bin/datasette"
[ -x "$DS" ] || DS=datasette
exec "$DS" serve -i jacme.sqlite -m metadata.json -h 127.0.0.1 -p 8001
''')
os.chmod(os.path.join(OUT, 'run_datasette.sh'), 0o755)
print(json.dumps({'version': VERSION, 'db': DB, 'counts': counts, 'short_terms': n_short, 'fts_test_診療参加型': fts_test}, ensure_ascii=False, indent=1))
