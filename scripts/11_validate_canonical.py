"""正本（canonical/）の検証。主キー一意、許容値、参照整合、総評集計との照合、判定空欄なし、IDマップ整合。
結果を canonical/validation_report.json に書き、失敗があれば終了コード1。"""
import csv, json, os, sys, collections
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAN = os.path.join(ROOT, 'canonical'); PRIV = os.path.join(CAN, 'private')
def rd(p):
    with open(p, encoding='utf-8') as f: return list(csv.DictReader(f))
T = {n: rd(os.path.join(CAN, n + '.csv')) for n in ['institutions', 'source_manifest', 'documents', 'review_events', 'concepts', 'standard_items', 'judgments', 'comments']}
P = {n: rd(os.path.join(PRIV, n + '.csv')) for n in ['comment_text', 'sohyo', 'area_gaihyo', 'event_evidence', 'evaluators']}
idmap = json.load(open(os.path.join(CAN, 'id_map.json'), encoding='utf-8'))
checks = []
def chk(name, ok, detail=''): checks.append({'check': name, 'status': 'ok' if ok else 'FAIL', 'detail': detail}); return ok

# 1. 主キー一意
PK = {'institutions': 'institution_id', 'source_manifest': 'file', 'documents': 'doc_id', 'review_events': 'event_id', 'concepts': 'concept_id', 'judgments': 'judgment_id', 'comments': 'comment_id'}
for n, k in PK.items():
    vals = [r[k] for r in T[n]]; dup = [v for v, c in collections.Counter(vals).items() if c > 1]
    chk(f'pk_unique:{n}.{k}', not dup and all(vals), f'dup={dup[:5]}')
si = collections.Counter((r['standard_family'], r['original_subarea']) for r in T['standard_items'])
chk('pk_unique:standard_items(family,subarea)', max(si.values()) == 1)
jk = collections.Counter((r['doc_id'], r['original_subarea'], r['level']) for r in T['judgments'])
chk('natural_key_unique:judgments(doc,subarea,level)', max(jk.values()) == 1, str([k for k, c in jk.items() if c > 1][:5]))
chk('pk_unique:comment_text', len({r['comment_id'] for r in P['comment_text']}) == len(P['comment_text']))

# 2. 許容値
ALLOWED = {('review_events', 'mixed_subareas'): {'', '4.1;4.2', 'other'}, ('review_events', 'jev_clef_agree'): {'', 'true', 'false'}, ('review_events', 'regex_retrospective'): {'true', 'none'}, ('review_events', 'regex_mixed'): {'true', 'none'}, ('review_events', 'review_type'): {'main', 'additional', 'notice'}, ('documents', 'review_type'): {'main', 'additional', 'notice'},
           ('review_events', 'retrospective_reassessment'): {'true', 'false', 'unknown', 'not_applicable'}, ('review_events', 'mixed_standard'): {'true', 'false', 'unknown', 'not_applicable'},
           ('review_events', 'verification_status'): {'heuristic_text', 'model_jev', 'jev_choice+text', 'human_verified', 'unknown'},
           ('judgments', 'level'): {'B', 'Q'}, ('comments', 'level'): {'B', 'Q'},
           ('judgments', 'judgment'): {'適合', '部分的適合', '不適合', '評価を実施せず'}, ('judgments', 'judgment_before'): {'', '適合', '部分的適合', '不適合', '評価を実施せず'},
           ('comments', 'type'): {'特色ある点', '改善のための助言', '改善のための示唆', '追加審査におけるコメント'}, ('comments', 'tone'): {'positive', 'must', 'desirable', 'confirm', 'other'},
           ('standard_items', 'relation'): {'same', 'renamed', 'renumbered'}, ('institutions', 'has_two_cycles'): {'true', 'false'}, ('documents', 'has_summary_counts'): {'true', 'false'}}
for (n, col), allowed in ALLOWED.items():
    bad = collections.Counter(r[col] for r in T[n] if r[col] not in allowed)
    chk(f'allowed_values:{n}.{col}', not bad, str(dict(bad)))
chk('no_blank_judgment', all(r['judgment'] for r in T['judgments']), str(sum(1 for r in T['judgments'] if not r['judgment'])))
chk('no_blank_comment_text', all(r['text'] for r in P['comment_text']))

# 3. 参照整合
ids = {n: {r[k] for r in T[n]} for n, k in PK.items()}
def ri(n, col, target, allow_blank=False):
    bad = {r[col] for r in T[n] if r[col] not in ids[target] and not (allow_blank and r[col] == '')}
    chk(f'ref:{n}.{col}->{target}', not bad, str(list(bad)[:5]))
ri('documents', 'institution_id', 'institutions'); ri('review_events', 'institution_id', 'institutions'); ri('review_events', 'doc_id', 'documents')
for n in ('judgments', 'comments'):
    ri(n, 'event_id', 'review_events'); ri(n, 'doc_id', 'documents'); ri(n, 'institution_id', 'institutions'); ri(n, 'concept_id', 'concepts')
chk('ref:standard_items.concept_id->concepts', all(r['concept_id'] in ids['concepts'] for r in T['standard_items']))
files = {r['file'] for r in T['source_manifest']}
chk('ref:documents.file->source_manifest', all(r['file'] in files for r in T['documents']))
chk('ref:comment_text<->comments(1:1)', {r['comment_id'] for r in P['comment_text']} == ids['comments'])
chk('ref:event_evidence.event_id->review_events', all(r['event_id'] in ids['review_events'] for r in P['event_evidence']))
chk('ref:evaluators.doc_id->documents', all(r['doc_id'] in ids['documents'] for r in P['evaluators']))
chk('review_events_one_per_document', {r['doc_id'] for r in T['review_events']} == ids['documents'] and len(T['review_events']) == len(T['documents']))
# フラグが true なら根拠行がある
ev_flags = {(r['event_id'], f) for r in T['review_events'] for f in ('retrospective_reassessment', 'mixed_standard') if r[f] == 'true'}
evid = {(r['event_id'], r['flag']) for r in P['event_evidence']}
chk('flag_true_has_evidence', ev_flags <= evid, str(list(ev_flags - evid)[:5]))
chk('flag_never_false_without_verification', not any(r[f] == 'false' and r['verification_status'] not in ('human_verified', 'model_jev', 'jev_choice+text') for r in T['review_events'] for f in ('retrospective_reassessment', 'mixed_standard')))
# false / true が model_jev 由来なら、Jev の確率行が存在し閾値と整合すること
jevp = os.path.join(PRIV, 'flag_judgments_jev.csv')
jev = {r['doc_id']: r for r in rd(jevp)} if os.path.exists(jevp) else {}
badj = []
for r in T['review_events']:
    if r['verification_status'] not in ('model_jev', 'jev_choice+text'): continue
    j = jev.get(r['doc_id'])
    if not j: badj.append((r['doc_id'], 'no_jev_row')); continue
    for f, p in (('retrospective_reassessment', j['p_retrospective']), ('mixed_standard', j['p_mixed'])):
        exp = 'true' if float(p) >= 0.8 else ('false' if float(p) <= 0.2 else 'unknown')
        if r[f] == 'not_applicable': continue
        if f == 'mixed_standard' and r['verification_status'] == 'jev_choice+text':
            # 上書き規則: noul は閾値の間、choice confidence ≥0.9、regex 根拠あり、値は true
            ch, conf = (r['mixed_subareas_choice'].split('@') + [''])[:2]
            if not (0.2 < float(p) < 0.8 and ch != 'none' and float(conf or 0) >= 0.9 and r['regex_mixed'] == 'true' and r[f] == 'true'): badj.append((r['doc_id'], 'override_rule'))
            continue
        if r[f] != exp or r[f'p_{"retrospective" if f.startswith("retro") else "mixed"}'] != p: badj.append((r['doc_id'], f))
chk('model_flags_backed_by_jev_probability', not badj, str(badj[:5]))
chk('not_applicable_only_for_non_main', not any(r['retrospective_reassessment'] == 'not_applicable' and r['review_type'] == 'main' for r in T['review_events'])
    and all(r['retrospective_reassessment'] == 'not_applicable' for r in T['review_events'] if r['review_type'] != 'main')
    and not any(r['mixed_standard'] == 'not_applicable' and r['review_type'] != 'notice' for r in T['review_events']))

# 4. 総評の集計との照合（scripts/06 と同じ）
cnt = collections.defaultdict(collections.Counter)
for j in T['judgments']: cnt[(j['doc_id'], j['level'])][j['judgment']] += 1
mism = []; n_sum = 0
for d in T['documents']:
    if d['has_summary_counts'] != 'true': continue
    n_sum += 1
    got = tuple(cnt[(d['doc_id'], L)][v] for L in 'BQ' for v in ['適合', '部分的適合', '不適合', '評価を実施せず'])
    exp = tuple(int(d[f'{L}_{x}']) for L in 'bq' for x in ['comp', 'part', 'non', 'nae'])
    if got != exp: mism.append((d['doc_id'], exp, got))
chk('summary_counts_match', not mism, f'checked={n_sum} mismatch={mism[:3]}')
# 本審査36下位領域は72判定
nj = collections.Counter(j['doc_id'] for j in T['judgments'])
bad72 = [d['doc_id'] for d in T['documents'] if d['review_type'] == 'main' and d['n_subareas'] == '36' and nj[d['doc_id']] != 72]
chk('main_36_subareas_have_72_judgments', not bad72, str(bad72[:5]))
chk('notice_has_no_judgments', all(nj[d['doc_id']] == 0 for d in T['documents'] if d['review_type'] == 'notice'))
chk('n_judgments_column_matches', all(int(d['n_judgments']) == nj[d['doc_id']] for d in T['documents']))

# 5. IDマップ整合（表のIDが全てマップに存在し、マップ内で重複がない）
for n, kind, k in (('institutions', 'institution', 'institution_id'), ('review_events', 'event', 'event_id'), ('judgments', 'judgment', 'judgment_id'), ('comments', 'comment', 'comment_id')):
    mapped = set(idmap[kind].values())
    chk(f'idmap_covers:{n}', ids[n] <= mapped and len(mapped) == len(idmap[kind]), f'missing={len(ids[n]-mapped)}')

# 6. 概念は36、全て判定に出現
used = {j['concept_id'] for j in T['judgments']}
chk('concepts_36_all_used', len(ids['concepts']) == 36 and used == ids['concepts'])

# 7. タグ表（scripts/21 の出力があるとき）
tag_path = os.path.join(CAN, 'comment_tags.csv'); cls_path = os.path.join(CAN, 'comment_classes.csv')
if os.path.exists(tag_path) and os.path.exists(cls_path):
    import yaml
    cb = yaml.safe_load(open(os.path.join(CAN, 'codebook', 'codebook_v1.1.yaml'), encoding='utf-8'))
    TH = set(cb['axes']['theme']['labels']); FN = set(cb['axes']['function']['labels']); ST = set(cb['axes']['stage']['labels']); SCP = set(cb['axes']['stage']['scope_labels'])
    tags = rd(tag_path); cls = rd(cls_path)
    per = collections.Counter(r['comment_id'] for r in tags)
    chk('tags_every_comment_has_all_themes', set(per) == ids['comments'] and all(v == len(TH) for v in per.values()), f'comments_with_rows={len(per)} bad_counts={sum(1 for v in per.values() if v != len(TH))}')
    chk('tags_theme_codes_allowed', all(r['theme'] in TH for r in tags))
    chk('tags_tagged_values', all(r['tagged'] in ('true', 'false', 'uncertain') for r in tags))
    chk('tags_prob_consistent_with_threshold', all((r['theme'] == 'T00_none') or ((float(r['prob']) >= float(r['threshold'])) == (r['tagged'] == 'true')) for r in tags))
    t00 = {r['comment_id'] for r in tags if r['theme'] == 'T00_none' and r['tagged'] == 'true'}
    others = {r['comment_id'] for r in tags if r['theme'] != 'T00_none' and r['tagged'] in ('true', 'uncertain')}
    chk('tags_T00_exclusive', not (t00 & others))
    chk('classes_one_per_comment', {r['comment_id'] for r in cls} == ids['comments'] and len(cls) == len(ids['comments']))
    chk('classes_codes_allowed', all(r['function'] in FN and r['observed_stage'] in ST and r['requested_stage'] in ST and r['observed_scope_exploratory'] in SCP and r['requested_scope_exploratory'] in SCP and r['secondary_function_exploratory'] in FN | {'none'} for r in cls))
    Cm = {r['comment_id']: r for r in T['comments']}
    chk('classes_requested_only_for_request_types', all((r['requested_stage'] == 'S0_not_applicable') == (Cm[r['comment_id']]['type'] == '特色ある点') for r in cls))

# 8. IRパイロットの表（canonical/pilot_ir/ があるとき）
PIL = os.path.join(CAN, 'pilot_ir')
if os.path.isdir(PIL) and os.path.exists(os.path.join(PIL, 'practice_observations.csv')):
    import yaml
    pc = yaml.safe_load(open(os.path.join(CAN, 'codebook', 'practices_v0.2.yaml'), encoding='utf-8'))['tables']
    A = rd(os.path.join(PIL, 'actors.csv')); PR = rd(os.path.join(PIL, 'practices.csv')); PO = rd(os.path.join(PIL, 'practice_observations.csv'))
    AR = rd(os.path.join(PIL, 'actor_relations.csv')); PL = rd(os.path.join(PIL, 'practice_links.csv')); PCd = rd(os.path.join(PIL, 'public_practice_cards.csv'))
    ES = {r['span_id'] for r in rd(os.path.join(PRIV, 'evidence_spans.csv'))} if os.path.exists(os.path.join(PRIV, 'evidence_spans.csv')) else set()
    for name, rows, key in (('actors', A, 'actor_id'), ('practices', PR, 'practice_id'), ('practice_observations', PO, 'obs_id'), ('actor_relations', AR, 'rel_id'), ('practice_links', PL, 'link_id'), ('public_practice_cards', PCd, 'card_id')):
        vals = [r[key] for r in rows]; chk(f'pilot_pk_unique:{name}', len(set(vals)) == len(vals) and all(vals))
    aid = {r['actor_id'] for r in A}; pid = {r['practice_id'] for r in PR}; oid = {r['obs_id'] for r in PO}
    chk('pilot_ref:actors.institution', all(r['institution_id'] in ids['institutions'] for r in A))
    chk('pilot_ref:practices.institution', all(r['institution_id'] in ids['institutions'] for r in PR))
    chk('pilot_ref:observations', all(r['practice_id'] in pid and r['doc_id'] in ids['documents'] and r['event_id'] in ids['review_events'] and (r['comment_id'] == '' or r['comment_id'] in ids['comments']) for r in PO))
    chk('pilot_ref:observations.span_ids->evidence_spans', all(all(x in ES for x in r['span_ids'].split(';') if x) for r in PO), 'evidence_spans.csv が無いか span_id 不明')
    chk('pilot_ref:relations', all(r['obs_id'] in oid and r['from_actor_id'] in aid and r['to_actor_id'] in aid for r in AR))
    chk('pilot_ref:links', all(r['from_obs_id'] in oid and r['to_obs_id'] in oid and r['from_obs_id'] != r['to_obs_id'] for r in PL))
    chk('pilot_allowed:claim_type', all(r['claim_type'] in pc['practice_observations']['claim_type'] for r in PO))
    chk('pilot_allowed:statement_time_role', all(r['statement_time_role'] in [k for k in pc['practice_observations']['statement_time_role'] if not k.startswith('note')] for r in PO))
    chk('pilot_allowed:stage', all(r['stage'] in {x.split()[0] for x in pc['practice_observations']['stage']} for r in PO))
    chk('pilot_allowed:result_use', all(r['result_use'] in pc['practice_observations']['result_use'] for r in PO))
    chk('pilot_allowed:outcome_type', all(r['outcome_type'] in pc['practice_observations']['outcome_type'] for r in PO))
    chk('pilot_allowed:process_kind', all(r['process_kind'] in pc['practice_observations']['process_kind'] for r in PO))
    chk('pilot_allowed:actor_type', all(r['actor_type'] in pc['actors']['actor_type'] for r in A))
    chk('pilot_allowed:relation', all(r['relation'] in pc['actor_relations']['relation'] and r['explicit'] in ('true', 'false') for r in AR))
    chk('pilot_allowed:link_type', all(r['link_type'] in pc['practice_links']['link_type'] and r['basis'] in pc['practice_links']['basis'] for r in PL))
    chk('pilot_allowed:practice.status', all(r['status'] in pc['practices']['status'] for r in PR))
    chk('pilot_cards_approved_values', all(r['approved'] in ('true', 'false') for r in PCd))
    chk('pilot_observation_consistency:request_has_result_use_request', all((r['claim_type'] != '要求') or r['result_use'] in ('要求', '不明') for r in PO))
    chk('pilot_observation_consistency:actor_same_institution', all({a['actor_id']: a['institution_id'] for a in A}[r['from_actor_id']] == {a['actor_id']: a['institution_id'] for a in A}[r['to_actor_id']] for r in AR))

fails = [c for c in checks if c['status'] != 'ok']
report = {'n_checks': len(checks), 'n_fail': len(fails), 'checks': checks, 'tag_tables_checked': os.path.exists(tag_path),
          'counts': {n: len(v) for n, v in T.items()}, 'private_counts': {n: len(v) for n, v in P.items()},
          'summary_counts_checked': n_sum, 'summary_counts_mismatch': len(mism)}
json.dump(report, open(os.path.join(CAN, 'validation_report.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
for c in checks: print(f"{c['status']:4} {c['check']} {c['detail'] if c['status'] != 'ok' else ''}")
print(f"checks={len(checks)} fail={len(fails)}")
sys.exit(1 if fails else 0)
