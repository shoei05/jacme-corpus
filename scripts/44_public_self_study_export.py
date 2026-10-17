"""Export allowlisted self-study metadata and provisional categories; never source text."""
import argparse,csv,json,pathlib,hashlib,collections,datetime

def read(p):
 with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def dump(p,v):p.write_text(json.dumps(v,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
def csvout(p,rows,fields):
 with p.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields,extrasaction='raise');w.writeheader();w.writerows(rows)
def export(root,out):
 out.mkdir(parents=True,exist_ok=True);src=root/'canonical/private/jev_stage_20261017'
 inst={r['institution_id']:r['name'] for r in read(root/'canonical/institutions.csv')}
 docs=read(root/'canonical/private/.staging/self_study_structure/self_study_documents.csv');dm={r['ss_doc_id']:r for r in docs}
 def meta(r):
  d=dm.get(r.get('ss_doc_id'),{})
  return {'university':inst.get(r.get('institution_id'),''),'institution_id':r.get('institution_id',''),'document_id':r.get('ss_doc_id',''),'cycle':r.get('cycle',''),'document_year':d.get('doc_year',''),'standard_version':d.get('standard_version_declared',''),'source_url':d.get('url','')}
 docrows=[]
 for d in docs:
  assert d['url'].startswith(('https://','http://'))
  docrows.append({**meta(d),'pages':d['pages'],'text_source':d['text_source'],'event_id':d['event_id'],'link_confidence':d['link_confidence']})
 dump(out/'documents.json',docrows);csvout(out/'documents.csv',docrows,list(docrows[0]))
 specs={
 'a':['unit_id','criterion_no','concept_id','level','external_judgment','jev_stage_status','self_recognition_jev_stage','evidence_page'],
 'b':['unit_id','comment_id','criterion_no','concept_id','level','jev_stage_status','recognition_jev_stage','evidence_page'],
 'c':['unit_id','comparison_type','prior_cycle','criterion_no','concept_id','level','jev_stage_status','judgment_jev_stage','evidence_page'],
 'd':['unit_id','criterion_no','concept_id','level','jev_stage_status','themes_jev_stage','function_jev_stage','observed_stage_jev_stage','evidence_page']}
 counts={};statuses={};area9=[]
 for stage,keys in specs.items():
  rows=read(src/f'comparison_{stage}_jev_stage.csv');clean=[]
  for r in rows:
   row={**meta(r),**{k:r[k] for k in keys}}
   if r['jev_stage_status']=='unresolved':
    for k in list(row):
     if k.endswith('_jev_stage'):row[k]='unknown'
   clean.append(row)
   if stage=='a' and r['criterion_no'].startswith(('B9.','Q9.')):area9.append(row)
  counts[stage]=len(clean);statuses[stage]=dict(collections.Counter(x['jev_stage_status'] for x in clean))
  csvout(out/f'comparison_{stage}.csv',clean,list(clean[0]))
 dump(out/'area9.json',area9);csvout(out/'area9.csv',area9,list(area9[0]))
 base=json.loads((src/'manifest.json').read_text())
 remediation=json.loads((root/'canonical/private/jev_stage_remediation_20261017/deterministic_summary.json').read_text())
 summary={'snapshot':'2026-10-17','profile':'Jev-stage provisional','counts':base['counts'],'source_pages':28508,'target_institutions':82,'unavailable_institutions':7,'comparison_counts':counts,'comparison_status_counts':statuses,'area9_rows':len(area9),'remediation_unresolved':remediation['after_deterministic']['unresolved_cells'],'remediation_missing_cells':remediation['after_deterministic']['reason_counts_overlapping']['missing_source_cell'],'notices':['Jevによる自動分類を含む暫定版。精読・独立した意味検証は未完了。','外部評価の下位領域判定と自己点検の個別基準は粒度が異なり、併記だけで過大・過小評価とは判断しない。','報告書本文・PDF・引用は収載せず、元資料へリンクする。','公開対象はJev段階の固定版。別途の修復検査では未解決53,956セル。修正案は固定版に混ぜていない。']}
 dump(out/'summary.json',summary)
 forbidden={'text','evidence_quote','snippet','sohyo','source_file','alignment','alignment_jev_stage'}
 for f in out.glob('*.csv'):
  assert not(forbidden & set(read(f)[0]))
 blobs='\n'.join(p.read_text(encoding='utf-8-sig') for p in out.iterdir() if p.suffix in ('.csv','.json'))
 for needle in ['/home/shoei05','/Users/shoei05','PRIVATE KEY','Bearer ','OPENROUTER_API_KEY']:assert needle not in blobs,needle
 # Check evidence quotations from every comparison row, without writing them.
 leaked=[];checked=0;needles=set()
 for stage in specs:
  for r in read(src/f'comparison_{stage}_jev_stage.csv'):
   q=r.get('evidence_quote','').strip()
   if len(q)<20:continue
   for s in {q[:20],q[-20:],q[max(0,len(q)//2-10):len(q)//2+10]}:
    if len(s)==20:
     checked+=1
     needles.add(s)
 # One rolling-hash pass avoids rescanning a large export for each quote.
 allowed_url_fragments={d['source_url'][i:i+20] for d in docrows for i in range(max(0,len(d['source_url'])-19))}
 exempt_url_fragments=len(needles & allowed_url_fragments);needles-=allowed_url_fragments
 mask=(1<<64)-1;base=257;power=pow(base,19,1<<64);targets={}
 for needle in needles:
  h=0
  for ch in needle:h=(h*base+ord(ch))&mask
  targets.setdefault(h,set()).add(needle)
 h=0
 for i,ch in enumerate(blobs):
  if i>=20:h=(h-ord(blobs[i-20])*power)&mask
  h=(h*base+ord(ch))&mask
  if i>=19 and h in targets:
   candidate=blobs[i-19:i+1]
   if candidate in targets[h]:leaked.append(candidate)
 assert not leaked,leaked[:10]
 for r in read(root/'canonical/private/evaluators.csv'):
  n=r.get('name','').strip()
  if len(n)>=3:assert n not in blobs,'evaluator name detected'
 manifest={'generated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'profile':'public_provisional_processed_self_study','source_snapshot_sha256':hashlib.sha256((src/'manifest.json').read_bytes()).hexdigest(),'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file()},'counts':counts,'privacy_checks':{'source_quote_fragments_checked':checked,'source_quote_matches':0,'explicit_source_url_fragments_exempted':exempt_url_fragments,'forbidden_columns':0,'evaluator_names':0,'local_paths_or_secret_markers':0}}
 dump(out/'manifest.json',manifest)
 return manifest
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--root',type=pathlib.Path,required=True);ap.add_argument('--out',type=pathlib.Path,required=True);a=ap.parse_args();print(json.dumps(export(a.root,a.out),ensure_ascii=False))
