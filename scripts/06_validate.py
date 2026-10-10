import csv,collections
D=list(csv.DictReader(open('knowledge/documents.csv',encoding='utf-8-sig')))
J=list(csv.DictReader(open('knowledge/judgments.csv',encoding='utf-8-sig')))
c=collections.defaultdict(collections.Counter);n=collections.Counter(j['doc_id'] for j in J)
for j in J: c[(j['doc_id'],j['level'])][j['judgment']]+=1
ok=bad=0;out=[]
for d in D:
    k=d['doc_id']
    if not d.get('b_comp'): out.append((k,d['univ'],'no_summary',n[k]));continue
    got=tuple(c[(k,L)][v] for L in 'BQ' for v in ['適合','部分的適合','不適合','評価を実施せず'])
    exp=tuple(int(d[f'{L}_{x}']) for L in 'bq' for x in ['comp','part','non','nae'])
    st='ok' if got==exp else f'mismatch exp{exp} got{got}'
    ok+=st=='ok'; bad+=st!='ok'; out.append((k,d['univ'],st,n[k]))
for o in out:
    if o[2]!='ok': print(o)
print('ok',ok,'bad',bad,'blank',[ (j['doc_id'],j['subarea'],j['level']) for j in J if not j['judgment']])
w=csv.writer(open('knowledge/validation.csv','w',newline='',encoding='utf-8-sig'));w.writerow(['doc_id','univ','status','n_items']);w.writerows(out)
