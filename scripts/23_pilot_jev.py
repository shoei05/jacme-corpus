"""IRパイロット Phase 3: 主体候補を正規表現・辞書で集め、Jev の小さな型付き判定で
観察（claim_type / time_role / stage / result_use / outcome_type / process_kind）、主体（役割・行為主体か）、
主体間の関係（関係の種類・明示か）、文書をまたぐ対応（同一取り組みか・前の要求への応答か）を判定する。
対象: パイロット14報告書の IR 関連コメント（T04 付与、または 7.1〜7.4・2.7・9.0）。
確率はすべて保存し、choice は confidence < 0.6、noul は 0.2〜0.8 を 不明 にする。
出力（private）: canonical/private/pilot_ir/jev_<run_id>_{observations,actors,relations,links}.jsonl と summary
評価: --eval で canonical/pilot_ir/ の手作業表（27観察・15関係・11リンク）と比較して一致率を出す。
使い方: zsh -lc 'python3 scripts/23_pilot_jev.py --run-id p3a' ; python3 scripts/23_pilot_jev.py --run-id p3a --eval
"""
import csv, json, os, re, sys, argparse, collections, time, datetime, itertools
import yaml
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAN = os.path.join(ROOT, 'canonical'); PRIV = os.path.join(CAN, 'private'); PIL = os.path.join(CAN, 'pilot_ir'); OUT = os.path.join(PRIV, 'pilot_ir')
os.makedirs(OUT, exist_ok=True)
ap = argparse.ArgumentParser(); ap.add_argument('--run-id', default='p3a'); ap.add_argument('--model', default='jev-latest'); ap.add_argument('--eval', action='store_true'); ap.add_argument('--limit', type=int, default=0); ap.add_argument('--skip-links', action='store_true'); ap.add_argument('--links-from', default=None, help='リンク判定を再利用する run_id')
args = ap.parse_args()
DOCS = 'evaluation_report17,evaluation_report101,evaluation_report5,evaluation_report_02_01,evaluation_report39,evaluation_report116,evaluation_report9,evaluation_report_02_05,evaluation_report108,evaluation_report16,evaluation_report72,evaluation_report90,evaluation_report98,evaluation_report97'.split(',')
CB = yaml.safe_load(open(os.path.join(CAN, 'codebook', 'practices_v0.2.yaml'), encoding='utf-8')); PO = CB['tables']['practice_observations']
def rd(p):
    with open(p, encoding='utf-8') as f: return list(csv.DictReader(f))
TEXT = {r['comment_id']: r['text'] for r in rd(os.path.join(PRIV, 'comment_text.csv'))}
C = [c for c in rd(os.path.join(CAN, 'comments.csv')) if c['doc_id'] in set(DOCS)]
D = {d['doc_id']: d for d in rd(os.path.join(CAN, 'documents.csv'))}; E = {e['doc_id']: e for e in rd(os.path.join(CAN, 'review_events.csv'))}
CONCEPT = {r['concept_id']: r['name'] for r in rd(os.path.join(CAN, 'concepts.csv'))}
tags = collections.defaultdict(set)
for r in rd(os.path.join(CAN, 'comment_tags.csv')):
    if r['tagged'] == 'true': tags[r['comment_id']].add(r['theme'].split('_')[0])
scope = [c for c in C if 'T04' in tags[c['comment_id']] or c['concept_id'] in ('7.1', '7.2', '7.3', '7.4', '2.7', '9.0')]
if args.limit: scope = scope[:args.limit]
IDX = {c['comment_id']: c for c in scope}

# ---------- 主体候補（正規表現＋辞書） ----------
ORG = re.compile(r'([A-Za-zＡ-Ｚａ-ｚ0-9０-９\u3040-\u30ff\u4e00-\u9fff・]{1,25}?(?:センター|委員会|検討委員会|部会|部門|IR室|室|会議|協議会|検討会|教授会|同窓会|執行部|事務局|事務部|学部長|学長|医学部|附属病院|病院|機構|プロジェクト|ワーキンググループ|WG|チーム|IR部|IR|リトリート|懇談会|連絡会|研究会|学会))')
CLAUSE = re.compile(r'^.*?(?:により|によって|において|における|として|を通じて|のもとで|に基づき|に基づいて|のため|のための|に関する|に関して|を受けて|を中心に|ごとに|など)')
GROUP = re.compile(r'(教職員|教員|学生|卒業生|保護者|患者|住民|地域住民|行政|医師会|自治体|他の医療職|医療職|関係者|指導者|指導医|管理者|外部評価者|外部の専門家|専門家|同窓会|学外病院|関連病院|臨床研修病院)')
LEAD = re.compile(r'^(?:・|に|と|の|を|や|が|は|で|から|への|また|および|及び|各|当該|同)+')
def candidates(text):
    cands = []
    for m in ORG.finditer(text):
        s = LEAD.sub('', CLAUSE.sub('', m.group(1))).strip('「」『』')
        for part in re.split(r'(?:および|及び|や|、|と|ならびに)', s):
            part = LEAD.sub('', part)
            if 2 <= len(part) <= 25 and re.search(r'(センター|委員会|部会|部門|室|会議|協議会|検討会|教授会|同窓会|執行部|事務局|事務部|学部長|学長|医学部|病院|機構|プロジェクト|グループ|WG|チーム|IR|リトリート|懇談会|連絡会|研究会|学会)$', part): cands.append(part)
    for m in GROUP.finditer(text): cands.append(m.group(1))
    out = []
    for x in cands:
        if x not in out and not any(x != y and x in y for y in cands): out.append(x)
    return out[:5]

# ---------- 質問 ----------
TYPES = CB['tables']['actors']['actor_type']; RELS = CB['tables']['actor_relations']['relation']
STAGE_CRIT = {'D1': '設計・整備: 組織・仕組み・規程が存在する／設置されたとだけ述べる（例: 体制が整備されている、センターを設置した）', 'D2': '運用: 対象を伴う活動が明示されている（例: 〜を収集している、仕組みが構築され実践されている、稼働している）',
              'D3': '点検・評価: 調査・分析・検証を行った／行っている', 'D4': '結果利用: 分析・評価の結果を決定や改善に用いた／用いている（例: 分析結果に基づいて入試枠を変更した）', 'N0': '記載なし: 現状の段階の記載がない（要求だけの文を含む）', 'N1': '段階決定不能: 記載はあるが決められない'}
def q_obs(c):
    ctx = f"comment_type={c['type']}; review_type={c['review_type']}; subarea={c['concept_id']} {CONCEPT.get(c['concept_id'], '')}"
    block = '本審査での評価 block of an ADDITIONAL-review report (restated from the earlier main review)' if (c['review_type'] == 'additional' and c['type'] != '追加審査におけるコメント') else ('追加審査におけるコメント (current findings of the additional review)' if c['review_type'] == 'additional' else 'main review findings')
    q = {'claim_type': {'type': 'choice', 'instructions': 'What kind of statement is this comment?', 'criteria': {'実施': '活動が行われている／行われたと述べる', '体制・予定': '組織・規程・体制が存在する、または予定・計画を述べる（活動の明示なし）', '要求': '〜すべき／〜が望まれる／〜が期待される', '基準文': '評価基準の引き写し', '不明': '判定できない'}},
         'time_role': {'type': 'choice', 'instructions': f'When does the stated content refer to? Structural position: {block}. A request (〜すべき/〜が望まれる) is NOT a future plan; it refers to the current review.', 'criteria': {'今回': '今回の審査時点の所見（要求文を含む）', '過去': '今回より前の時点の事実（年次明示、現在の状態ではない）', '不明': '判定できない'}},
         'plan_stated': {'type': 'noul', 'instructions': 'Does the comment state a PLAN or SCHEDULE of the school (予定、計画している、〜する予定) as the main content, as opposed to a request by the evaluators?', 'criteria': {'true': 'The school\'s own plan/schedule is stated', 'false': 'No plan stated, or only an evaluator request'}},
         'observed_stage': {'type': 'choice', 'instructions': 'Stage of what the comment states CURRENTLY exists. Use only explicit statements; do not infer from a request. "体制が整備されている" = D1 (not D4). "構築され実践されている" = D2.', 'criteria': STAGE_CRIT},
         'requested_stage': {'type': 'choice', 'instructions': 'If the comment is a request, the stage it asks the school to reach. If not a request choose N0.', 'criteria': STAGE_CRIT},
         'result_use': {'type': 'choice', 'instructions': 'Does the comment state that analysis/evaluation RESULTS were used? 全体 means the stated scope of use covers the whole programme (not confirmation of effect).', 'criteria': {'なし': '結果の利用について記載がない', '局所': '特定の対象（入試枠、科目など）で結果が使われたと記載', '全体': 'プログラム全体の改善・意思決定に使われたと記載', '要求': '利用が要求されている（記載はない）', '不明': '判定できない'}},
         'outcome_type': {'type': 'choice', 'instructions': 'What kind of result does the comment describe? If the comment is a request (要求), choose N/A.', 'criteria': {'体制': '組織・体制', '情報・分析': 'データ・分析結果・調査', '教育の変更': 'カリキュラム・選抜・授業などの変更', '学修成果': '学生・卒業生の成果', '不明': '判定できない', 'N/A': '要求文なので結果の記載がない'}},
         'process_kind': {'type': 'choice', 'instructions': 'How is the process described? 記載された過程 requires all three: an actor (who), an action (what is done), and an object (to/for what).', 'criteria': {'記載された過程': '主体・行為・対象の三つがそろって書かれている', '報告書の因果叙述': '「〜に基づき」「〜を受けて」など因果をことばで述べるが、主体か対象が欠ける', '不明': '主体または行為が本文に無い（要求文、対象だけの文）'}}}
    return q, ctx
def q_actors(cands):
    q = {}
    for i, a in enumerate(cands):
        q[f'role_{i}'] = {'type': 'choice', 'instructions': f'What kind of actor is 「{a}」 in this comment?', 'criteria': {**{t: t for t in TYPES if t != 'unspecified'}, 'not_actor': 'Not an organization/group acting in this comment (e.g. an object, a document, a topic)'}}
        q[f'subject_{i}'] = {'type': 'noul', 'instructions': f'Is 「{a}」 the one who performs (or is asked to perform) the action in this comment?', 'criteria': {'true': 'It acts or is asked to act', 'false': 'It is only mentioned (object, source, place)'}}
    for i, j in itertools.permutations(range(len(cands)), 2):
        if len(cands) > 3 and (i > 2 or j > 2): continue
        q[f'rel_{i}_{j}'] = {'type': 'choice', 'instructions': f'What does 「{cands[i]}」 do toward 「{cands[j]}」 as stated in the comment? Choose none if no relation is stated.', 'criteria': {**{r: r for r in RELS if r != '不明'}, 'none': 'No relation between them is stated'}}
        q[f'relexp_{i}_{j}'] = {'type': 'noul', 'instructions': f'Is a flow from 「{cands[i]}」 to 「{cands[j]}」 explicitly stated in the comment (not inferred)?', 'criteria': {'true': 'The text explicitly states the flow/relation', 'false': 'Only inferable'}}
    return q
def q_link(earlier, later):
    return {'same_practice': {'type': 'noul', 'instructions': 'Do the two comments concern the SAME concrete object/practice at the same school (same body, system, or activity), not just the same topic?', 'criteria': {'true': 'Same concrete object or activity', 'false': 'Different object, or only the same general topic'}},
            'responds': {'type': 'noul', 'instructions': 'Does the LATER comment describe something that would be a response to the EARLIER request (the requested body/activity now exists or operates)?', 'criteria': {'true': 'Later comment reports the requested thing as existing/operating', 'false': 'No, or later comment is itself a request / unrelated'}},
            'still_requested': {'type': 'noul', 'instructions': 'Is the LATER comment itself still requesting the same thing as the earlier request?', 'criteria': {'true': 'Same request persists', 'false': 'Not a request, or a different request'}}}

def state_of(c, ctx):
    return {'comment_text': TEXT[c['comment_id']], 'context': ctx, 'university': D[c['doc_id']]['institution_id'], 'document': f"{c['doc_id']} ({E[c['doc_id']]['eval_year']}, {c['review_type']})"}
def mapc(a, th=0.6): return a['choice'] if (a.get('confidence') or 0) >= th else '不明'
def mapn(p): return 'true' if p >= 0.8 else ('false' if p <= 0.2 else '不明')

if not args.eval:
    sys.path.insert(0, os.path.expanduser('~/.codex/skills/jev/scripts')); import jev
    t0 = time.time(); usage = collections.Counter(); n = 0
    fo = open(os.path.join(OUT, f'jev_{args.run_id}_observations.jsonl'), 'w', encoding='utf-8'); fa = open(os.path.join(OUT, f'jev_{args.run_id}_actors.jsonl'), 'w', encoding='utf-8')
    fr = open(os.path.join(OUT, f'jev_{args.run_id}_relations.jsonl'), 'w', encoding='utf-8'); fl = open(os.path.join(OUT, f'jev_{args.run_id}_links.jsonl'), 'w', encoding='utf-8')
    for c in scope:
        q, ctx = q_obs(c); cands = candidates(TEXT[c['comment_id']]); q.update(q_actors(cands))
        res = jev.call(state_of(c, ctx), q, args.model, timeout=120); A = res['answers']; u = res.get('usage') or {}; usage['in'] += u.get('input_tokens', 0); usage['out'] += u.get('output_tokens', 0); usage['calls'] += 1
        # 構造上の規則: 追加審査報告書の本審査欄は 旧審査再掲（Jev の答えは残す）
        rule_time = '旧審査再掲' if (c['review_type'] == 'additional' and c['type'] != '追加審査におけるコメント') else ('今回' if c['type'] != '特色ある点' else None)   # 要求文は今回。特色は Jev の 今回/過去 を使う
        obs = {'comment_id': c['comment_id'], 'doc_id': c['doc_id'], 'concept_id': c['concept_id'], 'type': c['type'], 'model': res.get('model'), 'run_id': args.run_id,
               **{k: {'value': mapc(A[k]), 'choice': A[k]['choice'], 'confidence': A[k].get('confidence'), 'probabilities': A[k].get('probabilities')} for k in ('claim_type', 'time_role', 'observed_stage', 'requested_stage', 'result_use', 'outcome_type', 'process_kind')},
               'plan_stated': {'value': mapn(A['plan_stated']['noul']), 'p': A['plan_stated']['noul']},
               'time_role_rule': rule_time, 'time_role_final': rule_time or mapc(A['time_role']), 'candidates': cands}
        fo.write(json.dumps(obs, ensure_ascii=False) + '\n')
        for i, a in enumerate(cands):
            fa.write(json.dumps({'comment_id': c['comment_id'], 'candidate': a, 'role': mapc(A[f'role_{i}']), 'role_choice': A[f'role_{i}']['choice'], 'role_confidence': A[f'role_{i}'].get('confidence'), 'role_probabilities': A[f'role_{i}'].get('probabilities'),
                                 'is_subject': mapn(A[f'subject_{i}']['noul']), 'p_subject': A[f'subject_{i}']['noul'], 'run_id': args.run_id}, ensure_ascii=False) + '\n')
        for i, j in itertools.permutations(range(len(cands)), 2):
            k = f'rel_{i}_{j}'
            if k not in A: continue
            fr.write(json.dumps({'comment_id': c['comment_id'], 'from': cands[i], 'to': cands[j], 'relation': mapc(A[k]), 'relation_choice': A[k]['choice'], 'relation_confidence': A[k].get('confidence'), 'relation_probabilities': A[k].get('probabilities'),
                                 'explicit': mapn(A[f'relexp_{i}_{j}']['noul']), 'p_explicit': A[f'relexp_{i}_{j}']['noul'], 'run_id': args.run_id}, ensure_ascii=False) + '\n')
        n += 1
        if n % 50 == 0: print(f'{n}/{len(scope)} obs', flush=True)
    # 文書をまたぐ対応: 同一大学・同一下位領域で、前の文書の要求 × 後の文書のコメント
    by_univ = collections.defaultdict(list)
    for c in scope: by_univ[D[c['doc_id']]['institution_id']].append(c)
    pairs = []
    for u, cs in by_univ.items():
        for a, b in itertools.permutations(cs, 2):
            ya, yb = E[a['doc_id']]['eval_year'], E[b['doc_id']]['eval_year']
            if a['doc_id'] == b['doc_id'] or not (ya and yb) or int(ya) >= int(yb): continue
            if a['type'] == '特色ある点' or a['concept_id'] != b['concept_id']: continue
            if a['review_type'] == 'additional' and a['type'] != '追加審査におけるコメント': continue   # 再掲は起点にしない
            pairs.append((a, b))
    print('link pairs', len(pairs), flush=True)
    if args.links_from:
        import shutil; shutil.copy(os.path.join(OUT, f'jev_{args.links_from}_links.jsonl'), os.path.join(OUT, f'jev_{args.run_id}_links.jsonl')); pairs = []
    for k, (a, b) in enumerate(pairs, 1):
        st = {'earlier': {'document': f"{a['doc_id']} ({E[a['doc_id']]['eval_year']}, {a['review_type']})", 'comment_type': a['type'], 'text': TEXT[a['comment_id']]},
              'later': {'document': f"{b['doc_id']} ({E[b['doc_id']]['eval_year']}, {b['review_type']})", 'comment_type': b['type'], 'text': TEXT[b['comment_id']]}, 'subarea': f"{a['concept_id']} {CONCEPT.get(a['concept_id'], '')}"}
        res = jev.call(st, q_link(a, b), args.model, timeout=120); A = res['answers']; u = res.get('usage') or {}; usage['in'] += u.get('input_tokens', 0); usage['out'] += u.get('output_tokens', 0); usage['calls'] += 1
        fl.write(json.dumps({'earlier_comment_id': a['comment_id'], 'later_comment_id': b['comment_id'], 'concept_id': a['concept_id'], 'same_practice': mapn(A['same_practice']['noul']), 'p_same': A['same_practice']['noul'],
                             'responds': mapn(A['responds']['noul']), 'p_responds': A['responds']['noul'], 'still_requested': mapn(A['still_requested']['noul']), 'p_still': A['still_requested']['noul'], 'model': res.get('model'), 'run_id': args.run_id}, ensure_ascii=False) + '\n')
        if k % 200 == 0: print(f'{k}/{len(pairs)} links', flush=True)
    for f in (fo, fa, fr, fl): f.close()
    summ = {'run_id': args.run_id, 'n_comments': len(scope), 'n_link_pairs': len(pairs), 'usage': dict(usage), 'elapsed_s': round(time.time() - t0, 1), 'finished': datetime.datetime.now().isoformat(timespec='seconds')}
    json.dump(summ, open(os.path.join(OUT, f'jev_{args.run_id}_summary.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1); print(json.dumps(summ, ensure_ascii=False)); sys.exit(0)

# ---------- 評価（手作業表との比較） ----------
J = {json.loads(l)['comment_id']: json.loads(l) for l in open(os.path.join(OUT, f'jev_{args.run_id}_observations.jsonl'), encoding='utf-8')}
JA = collections.defaultdict(list)
for l in open(os.path.join(OUT, f'jev_{args.run_id}_actors.jsonl'), encoding='utf-8'): r = json.loads(l); JA[r['comment_id']].append(r)
JR = collections.defaultdict(list)
for l in open(os.path.join(OUT, f'jev_{args.run_id}_relations.jsonl'), encoding='utf-8'): r = json.loads(l); JR[r['comment_id']].append(r)
JL = {(json.loads(l)['earlier_comment_id'], json.loads(l)['later_comment_id']): json.loads(l) for l in open(os.path.join(OUT, f'jev_{args.run_id}_links.jsonl'), encoding='utf-8')}
MO = rd(os.path.join(PIL, 'practice_observations.csv')); MA = {a['actor_id']: a for a in rd(os.path.join(PIL, 'actors.csv'))}; MR = rd(os.path.join(PIL, 'actor_relations.csv')); ML = rd(os.path.join(PIL, 'practice_links.csv'))
MOc = {o['comment_id']: o for o in MO}
md = [f'# Phase 3 Jev 判定と手作業表の比較（{args.run_id}）', '', f'対象コメント {len(J)} 件、手作業観察 {len(MO)} 件（うち Jev 判定あり {sum(1 for o in MO if o["comment_id"] in J)}）', '']
rows = []
def agree(field, mget, jget):
    pairs = [(mget(o), jget(J[o['comment_id']])) for o in MO if o['comment_id'] in J]
    n = len(pairs); ok = sum(1 for m, j in pairs if m == j); unk = sum(1 for m, j in pairs if j == '不明')
    conf = collections.Counter((m, j) for m, j in pairs if m != j)
    rows.append((field, n, ok, unk, conf)); md.append(f'| {field} | {ok}/{n} ({ok/n:.2f}) | {unk} | ' + '; '.join(f'{m}→{j}:{c}' for (m, j), c in conf.most_common(4)) + ' |')
md += ['## 観察の各項目', '', '| 項目 | 一致 | Jev 不明 | 主な不一致（手作業→Jev） |', '|---|---|---|---|']
agree('claim_type', lambda o: o['claim_type'], lambda j: j['claim_type']['value'])
agree('statement_time_role', lambda o: o['statement_time_role'], lambda j: j['time_role_final'])
agree('stage（実施/体制は observed、要求は requested）', lambda o: o['stage'], lambda j: j['observed_stage']['value'] if MOc[j['comment_id']]['claim_type'] != '要求' else j['requested_stage']['value'])
agree('result_use', lambda o: o['result_use'], lambda j: j['result_use']['value'])
agree('outcome_type（要求は N/A）', lambda o: 'N/A' if o['claim_type'] == '要求' else o['outcome_type'], lambda j: j['outcome_type']['value'])
agree('process_kind（手作業の 研究者の仮説 は除外不可のためそのまま）', lambda o: o['process_kind'], lambda j: j['process_kind']['value'])
# 主体: 手作業の関係に出る主体ラベルが候補に含まれ、is_subject/role が付いたか
md += ['', '## 主体候補と関係（手作業 15 関係）', '', '| rel_id | comment | from→to（手作業） | 関係 | explicit | Jev 候補にある | Jev 関係 | Jev explicit |', '|---|---|---|---|---|---|---|---|']
hit_cand = hit_rel = hit_exp = 0
def norm(s): return re.sub(r'[（(].*?[)）]', '', s).replace('・', '')
for r in MR:
    o = MOc[next(o['obs_id'] for o in MO if o['obs_id'] == r['obs_id']) and r['obs_id']] if False else next(o for o in MO if o['obs_id'] == r['obs_id'])
    cid = o['comment_id']; fa_, ta_ = MA[r['from_actor_id']]['label'], MA[r['to_actor_id']]['label']
    cands = [a['candidate'] for a in JA.get(cid, [])]
    def found(lbl):
        if MA[r['from_actor_id']]['actor_type'] == 'unspecified' and lbl == fa_: return None
        return any(norm(lbl)[:4] in c or c[:4] in norm(lbl) for c in cands)
    f_ok, t_ok = found(fa_), found(ta_)
    jr = next((x for x in JR.get(cid, []) if (norm(fa_)[:4] in x['from'] or x['from'][:4] in norm(fa_)) and (norm(ta_)[:4] in x['to'] or x['to'][:4] in norm(ta_))), None)
    both = (f_ok is None or f_ok) and t_ok
    hit_cand += bool(both); hit_rel += bool(jr and jr['relation'] == r['relation']); hit_exp += bool(jr and jr['explicit'] == r['explicit'])
    md.append(f"| {r['rel_id']} | {cid} | {fa_}→{ta_} | {r['relation']} | {r['explicit']} | {'主体なし' if f_ok is None else f_ok}/{t_ok} | {jr['relation'] if jr else '—'} | {jr['explicit'] if jr else '—'} |")
md.append(f'\n両主体が候補に含まれた: {hit_cand}/{len(MR)}、関係の種類が一致: {hit_rel}/{len(MR)}、explicit が一致: {hit_exp}/{len(MR)}')
# リンク
md += ['', '## 文書をまたぐ対応（手作業 11 リンク）', '', '| link_id | 種類（手作業） | 根拠 | Jev same_practice | Jev responds | Jev still_requested |', '|---|---|---|---|---|---|']
lk = 0
for l in ML:
    a = next(o['comment_id'] for o in MO if o['obs_id'] == l['from_obs_id']); b = next(o['comment_id'] for o in MO if o['obs_id'] == l['to_obs_id'])
    j = JL.get((a, b))
    exp = {'同一取り組みの経時': ('same_practice', 'true'), '要求の継続': ('still_requested', 'true'), '要求への応答': ('responds', 'true'), '旧審査再掲': ('same_practice', 'true')}[l['link_type']]
    ok = bool(j and j[exp[0]] == exp[1]); lk += ok
    md.append(f"| {l['link_id']} | {l['link_type']} | {l['basis']} | {j['same_practice'] + ' (' + str(j['p_same']) + ')' if j else '判定ペアなし'} | {j['responds'] + ' (' + str(j['p_responds']) + ')' if j else '—'} | {j['still_requested'] + ' (' + str(j['p_still']) + ')' if j else '—'} |")
md.append(f'\n期待どおり: {lk}/{len(ML)}（判定ペアが無いものは、起点が特色ある点か再掲のため対象外）')
# 全体分布
md += ['', '## 対象全体の分布（Jev、不明を含む）', '']
for k in ('claim_type', 'observed_stage', 'requested_stage', 'result_use', 'process_kind'):
    md.append(f"- {k}: {dict(collections.Counter(j[k]['value'] for j in J.values()))}")
md.append(f"- time_role_final: {dict(collections.Counter(j['time_role_final'] for j in J.values()))}")
md.append(f"- 主体候補: 平均 {sum(len(v) for v in JA.values())/max(1,len(J)):.2f} 件/コメント、is_subject=true {sum(1 for v in JA.values() for a in v if a['is_subject']=='true')}、role 不明 {sum(1 for v in JA.values() for a in v if a['role']=='不明')}、not_actor {sum(1 for v in JA.values() for a in v if a['role']=='not_actor')}")
md.append(f"- 関係: {sum(len(v) for v in JR.values())} 組、none {sum(1 for v in JR.values() for r in v if r['relation']=='none')}、不明 {sum(1 for v in JR.values() for r in v if r['relation']=='不明')}、explicit=true {sum(1 for v in JR.values() for r in v if r['explicit']=='true')}")
md.append(f"- リンク: {len(JL)} 組、same_practice=true {sum(1 for j in JL.values() if j['same_practice']=='true')}、responds=true {sum(1 for j in JL.values() if j['responds']=='true')}、still_requested=true {sum(1 for j in JL.values() if j['still_requested']=='true')}")
open(os.path.join(OUT, f'jev_{args.run_id}_eval.md'), 'w', encoding='utf-8').write('\n'.join(md) + '\n'); print('\n'.join(md))
