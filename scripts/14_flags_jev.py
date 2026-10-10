"""後年再評価・版混在フラグを型付き判定モデル（System One 型API）で判定し、確率を private 層に保存する。

バックエンド（--backend）:
  typesafe   TypeSafe Jev。~/.codex/skills/jev/scripts/jev.py の call() を使う（POST https://api.typesafe.ai/v1/systemone、
             モデル jev-latest / jev-preview、鍵は ~/.config/typesafe/env）。出力 canonical/private/flag_judgments_jev.csv
  workers-ai Cloudflare Workers AI の Clef。POST https://api.cloudflare.com/client/v4/accounts/$CLOUDFLARE_ACCOUNT_ID/ai/run/@cf/cloudflare/clef
             （Bearer $CLOUDFLARE_API_TOKEN、本文 {"model":"clef"|"clef-flash","state":…,"questions":…}。
             応答は schema-output.json どおり {"model","answers":{id:{"type":"noul","noul":p}|{"type":"choice","choice","probabilities","confidence"}},"usage"}。
             Cloudflare REST は {"result":…,"success":true} で包むことがあるので両方を受ける）。出力 flag_judgments_clef.csv
             環境変数が無ければ明示的に失敗する。
入力は報告書全文ではなく、正規表現で抜いた候補箇所だけ（はじめに・総評の冒頭、再評価/再開/改善状況/Ver./版/年月まで等を含む文）。
質問: noul 2問（後年再評価、版混在）＋ choice 1問（別版を適用した下位領域）。
フラグへの写像（閾値 0.8/0.2）、regex との不一致表、監査サンプルは scripts/10_canonical.py が行う。
使い方:
  zsh -lc 'python3 scripts/14_flags_jev.py'                                   # Jev（jev-latest）
  zsh -lc 'python3 scripts/14_flags_jev.py --backend workers-ai --model clef'  # Clef（トークン設定後）
  python3 scripts/15_compare_flag_models.py                                    # Jev と Clef の一致
"""
import csv, json, os, re, sys, argparse, unicodedata, datetime, time, urllib.request, urllib.error
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAN = os.path.join(ROOT, 'canonical'); PRIV = os.path.join(CAN, 'private')

ap = argparse.ArgumentParser()
ap.add_argument('--backend', choices=['typesafe', 'workers-ai'], default='typesafe')
ap.add_argument('--model', default=None, help='typesafe: jev-latest|jev-preview（既定 jev-latest）, workers-ai: clef|clef-flash（既定 clef）')
ap.add_argument('--limit', type=int, default=0); ap.add_argument('--only', default='')
args = ap.parse_args()
MODEL = args.model or {'typesafe': 'jev-latest', 'workers-ai': 'clef'}[args.backend]
OUT = os.path.join(PRIV, 'flag_judgments_jev' if args.backend == 'typesafe' else 'flag_judgments_clef')

# ---------- バックエンド ----------
def call_typesafe(state, questions):
    sys.path.insert(0, os.path.expanduser('~/.codex/skills/jev/scripts'))
    import jev
    return jev.call(state, questions, MODEL, timeout=90)
def call_workers_ai(state, questions):
    acct = os.environ.get('CLOUDFLARE_ACCOUNT_ID'); tok = os.environ.get('CLOUDFLARE_API_TOKEN')
    if not acct or not tok: sys.exit('CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN が未設定。Workers AI は呼べない')
    url = f'https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/@cf/cloudflare/{MODEL}'
    body = json.dumps({'model': MODEL, 'state': state, 'questions': questions}, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(url, data=body, headers={'Authorization': 'Bearer ' + tok, 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=120) as r: res = json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f'Workers AI HTTP {e.code}: {e.read().decode("utf-8", "replace")[:800]}')
    if 'answers' not in res and isinstance(res.get('result'), dict): res = res['result']   # Cloudflare REST の包み
    if 'answers' not in res: sys.exit('Workers AI の応答に answers が無い: ' + json.dumps(res)[:500])
    return res
CALL = {'typesafe': call_typesafe, 'workers-ai': call_workers_ai}[args.backend]

# ---------- 候補箇所 ----------
KEY = re.compile(r'再評価|再審査|再開|改善状況|改善報告書|追加審査|Ver\.|版|年\s*\d{0,2}\s*月?\s*まで|当時の評価')
def excerpts(doc_id):
    """[(label, char_start, char_end, text)]。評価チーム欄（氏名）は含めない。"""
    t = unicodedata.normalize('NFKC', open(os.path.join(ROOT, 'text', doc_id + '.txt'), encoding='utf-8').read()).replace('\f', '\n')
    out = []
    i = t.find('はじめに'); j = t.find('評価チーム', i if i >= 0 else 0)
    if i >= 0 and j > i: out.append(('intro', i, min(j, i + 3000), t[i:min(j, i + 3000)]))
    s = t.find('総評'); e = t.find('評価チーム', s) if s >= 0 else -1
    if s >= 0 and (e < 0 or e - s > 200):
        seg = t[s:s + 1500]; out.append(('sohyo_head', s, s + len(seg), seg))
    body_start = max(j, s + 1500, 0); n = 0
    for m in re.finditer(r'[^。\n]*。', t[body_start:]):
        sent = m.group(0)
        if KEY.search(sent) and len(sent) < 400:
            a = body_start + m.start(); out.append(('sentence', a, a + len(sent), sent)); n += 1
            if n >= 25: break
    return [(l, a, b, re.sub(r'\s+', ' ', x).strip()) for l, a, b, x in out]

QUESTIONS = {
    'retro': {'type': 'noul', 'instructions': (
        'Was the evaluation in this report re-done or re-opened LATER than the original site visit, so that its judgments incorporate improvements '
        'the medical school made after that visit (e.g. the text says the report is a "再評価" combining the original evaluation with later 改善状況, '
        'or that deliberation was re-opened ("審議再開"/"評価を再開") after an improvement report)? '
        'Answer NO when the report only describes the state at the time of its own site visit. '
        'The fact that a document is itself an additional review (追加審査評価報告書) does NOT by itself make the answer yes; '
        'answer yes for an additional review only if that additional review itself was later re-done or re-opened.')},
    'mixed': {'type': 'noul', 'instructions': (
        'Does this single report apply MORE THAN ONE version of the evaluation standard (e.g. 日本版 Ver.1.30 and Ver.2.31, or 2013年7月版 and a later Ver.) '
        'to different items or subareas? Answer NO if one version is applied throughout, even if other versions are merely mentioned as history.')},
    'which': {'type': 'choice', 'instructions': 'If some subareas were evaluated under a different standard version than the rest of the report, which ones?',
              'criteria': {'none': 'No subarea uses a different version; a single version is applied throughout',
                           '4.1_4.2': 'Subareas 4.1 and 4.2 (admissions) use a different version from the rest',
                           'other': 'Some other subarea(s) use a different version'}},
}
def rd(p):
    with open(p, encoding='utf-8') as f: return list(csv.DictReader(f))
docs = rd(os.path.join(CAN, 'documents.csv')); events = {e['doc_id']: e for e in rd(os.path.join(CAN, 'review_events.csv'))}
if args.only: docs = [d for d in docs if d['doc_id'] in args.only.split(',')]
if args.limit: docs = docs[:args.limit]
prev = {r['doc_id']: r for r in rd(OUT + '.csv')} if os.path.exists(OUT + '.csv') else {}
FIELDS = ['doc_id', 'event_id', 'backend', 'model_requested', 'model_returned', 'p_retrospective', 'p_mixed', 'which_choice', 'which_confidence', 'which_probabilities',
          'excerpt_spans', 'excerpt_chars', 'n_excerpts', 'input_tokens', 'question_version', 'called_at', 'raw']
QV = 'v2-2026-10-10'   # 質問文の版。文言を変えたら上げる
new = {}
for k, d in enumerate(docs, 1):
    doc = d['doc_id']; ex = excerpts(doc)
    if not ex: print(f'{k}/{len(docs)} {doc} 候補箇所なし → skip'); continue
    state = {'document': f"JACME accreditation evaluation report. review_type={d['review_type']} (main=本審査, additional=追加審査, notice=公表文); "
                         f"declared standard version={d['standard_version_declared'] or 'unknown'}; evaluation year={d['eval_year'] or 'unknown'}",
             'excerpts': [{'where': l, 'text': x} for l, a, b, x in ex]}
    try:
        res = CALL(state, QUESTIONS)
    except SystemExit as e:
        print('ERROR', doc, e); continue
    A = res['answers']
    new[doc] = {'doc_id': doc, 'event_id': events[doc]['event_id'], 'backend': args.backend, 'model_requested': MODEL, 'model_returned': res.get('model', ''),
                'p_retrospective': A['retro']['noul'], 'p_mixed': A['mixed']['noul'], 'which_choice': A['which']['choice'], 'which_confidence': A['which'].get('confidence'),
                'which_probabilities': json.dumps(A['which'].get('probabilities'), ensure_ascii=False),
                'excerpt_spans': ';'.join(f'{l}:{a}-{b}' for l, a, b, x in ex), 'excerpt_chars': sum(len(x) for *_, x in ex), 'n_excerpts': len(ex),
                'input_tokens': (res.get('usage') or {}).get('input_tokens'), 'question_version': QV, 'called_at': datetime.datetime.now().isoformat(timespec='seconds'),
                'raw': json.dumps(res, ensure_ascii=False)}
    print(f"{k}/{len(docs)} {doc} retro={A['retro']['noul']} mixed={A['mixed']['noul']} which={A['which']['choice']} model={res.get('model')}", flush=True)
    time.sleep(0.2)
merged = {**prev, **new}
rows = [merged[d['doc_id']] for d in rd(os.path.join(CAN, 'documents.csv')) if d['doc_id'] in merged]
with open(OUT + '.csv', 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction='ignore'); w.writeheader(); w.writerows(rows)
with open(OUT + '.jsonl', 'w', encoding='utf-8') as f:
    for r in rows: f.write(json.dumps({k: r.get(k, '') for k in FIELDS}, ensure_ascii=False) + '\n')
print(json.dumps({'backend': args.backend, 'model_returned': sorted({r['model_returned'] for r in rows}), 'n_judged': len(rows), 'out': OUT + '.csv',
                  'next': 'python3 scripts/10_canonical.py → 11 → 12 → 13 で正本・リリース・公開に反映'}, ensure_ascii=False))
