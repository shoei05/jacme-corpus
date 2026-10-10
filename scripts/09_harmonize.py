"""ChatGPT指摘（2026-10-10）を反映: review_type、基準系列、共通概念ID、tone再判定、対応ペア。"""
import csv, re, collections
def rd(n): return list(csv.DictReader(open(f'knowledge/{n}.csv',encoding='utf-8-sig')))
def wr(n,L):
    keys=[];[keys.append(k) for x in L for k in x if k not in keys]
    w=csv.DictWriter(open(f'knowledge/{n}.csv','w',newline='',encoding='utf-8-sig'),fieldnames=keys);w.writeheader();w.writerows(L)
D,J,C=rd('documents'),rd('judgments'),rd('comments')
# 誤抽出の隔離: 判定が空欄で、下位領域名に本文が混入した行（ChatGPT 2回目の指摘、report72 5.2 B）
bad=[j for j in J if not j['judgment'] and re.search(r'\[|年度|。',j['subarea_name'])]
J=[j for j in J if j not in bad]
if bad: wr('quarantine_judgments',[{**b,'reason':'見出し誤認（本文の一節を下位領域名として抽出、判定空欄）'} for b in bad])
OLD1={'使命の策定への参画':'1.4','大学の自律性および学部の自由度':'1.2','教育成果':'1.3'}
for d in D:
    d['review_type']='notice' if d['n_subareas']=='0' else ('additional' if d['additional']=='True' else 'main')
    if not d['standard_ver']: d['standard_ver']='2013-07' if d['eval_year'] in ('2013','2014') else ''
    v=d['standard_ver']
    d['standard_family']='WFME2012系(日本版2013/Ver.1.30)' if v in ('2013-07','1.30') else ('WFME2015系(Ver.2.x)' if v.startswith('2.') else '')
Dm={d['doc_id']:d for d in D}
# main系列の巡目: 大学ごとに main を年度順に並べる
by=collections.defaultdict(list)
for d in D:
    if d['review_type']=='main': by[d['univ']].append(d)
for u,L in by.items():
    L.sort(key=lambda x:int(x['eval_year']))
    for i,d in enumerate(L,1): d['cycle']=str(i)
for d in D:
    if d['review_type']!='main': d['cycle']=''
for j in J+C:
    d=Dm[j['doc_id']]
    name=j.get('subarea_name','')
    j['concept_id']=OLD1.get(name,j['subarea']) if j['subarea'].startswith('1.') and d['standard_family'].startswith('WFME2012') else j['subarea']
    j['review_type']=d['review_type']; j['cycle']=d['cycle']; j['standard_family']=d['standard_family']
# コメント側は subarea_name を持たないので judgments から引く
nm={(j['doc_id'],j['subarea']):j['concept_id'] for j in J}
for c in C:
    c['concept_id']=nm.get((c['doc_id'],c['subarea']),c['subarea'])
    t=c['text']
    c['tone']=('positive' if c['type']=='特色ある点' else
               'must' if re.search(r'べき|なければならない|なくてはならない',t) else
               'desirable' if re.search(r'望まれる|期待される|望ましい',t) else
               'confirm' if re.search(r'確認した|確認された|認められる',t) else 'other')
pairs=[]
for u,L in by.items():
    if len(L)>=2: pairs.append({'univ':u,'doc_cycle1':L[0]['doc_id'],'year1':L[0]['eval_year'],'ver1':L[0]['standard_ver'],'doc_cycle2':L[1]['doc_id'],'year2':L[1]['eval_year'],'ver2':L[1]['standard_ver']})
wr('documents',D);wr('judgments',J);wr('comments',C);wr('pairs',pairs)
print(collections.Counter((d['review_type'],d['cycle']) for d in D),'pairs',len(pairs))
print(collections.Counter(c['tone'] for c in C))
print(collections.Counter(d['standard_family'] for d in D))
print('quarantined',len(bad),'blank judgments left',sum(1 for j in J if not j['judgment']))
print('area1 remapped',sum(1 for j in J if j['concept_id']!=j['subarea']))
