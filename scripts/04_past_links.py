import csv, os, subprocess, time, re
from pypdf import PdfReader
rows=list(csv.DictReader(open('knowledge/manifest.csv',encoding='utf-8-sig')))
have={r['file'] for r in rows}; new=[]
for r in [x for x in rows if x['kind']=='past']:
    rd=PdfReader('raw/pdf/'+r['file'])
    for p in rd.pages:
        for a in p.get('/Annots') or []:
            o=a.get_object(); A=o.get('/A')
            u=A.get('/URI') if A else None
            if not u or '.pdf' not in u: continue
            u=u if u.startswith('http') else 'https://www.jacme.or.jp/'+u.lstrip('./')
            fn=u.split('/')[-1]
            if fn in have: continue
            have.add(fn)
            new.append({**{k:r[k] for k in ['no','univ','pref','type']},'fiscal_year':'','period_start':'','period_end':'','kind':'prior_cycle','label':'過去の評価報告書','url':u,'file':fn,'remark':'from '+r['file']})
for n in new:
    p='raw/pdf/'+n['file']
    if not os.path.exists(p): subprocess.run(['curl','-sL','--fail','-o',p,n['url']]); time.sleep(1)
rows+=new
w=csv.DictWriter(open('knowledge/manifest.csv','w',newline='',encoding='utf-8-sig'),fieldnames=rows[0].keys());w.writeheader();w.writerows(rows)
print('new',len(new)); [print(n['univ'],n['file']) for n in new]
