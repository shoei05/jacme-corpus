import json, csv, re, os, time, subprocess
rows=json.load(open('raw/html/table_rows.json'))
man=[];cur=None
for r in rows:
    c=r['cells']
    if c[0].isdigit() and int(c[0])<1000:
        cur={'no':int(c[0]),'univ':c[1],'pref':c[2],'type':c[3]}
        yr,start,end=c[5],c[6],c[7]; rem=c[10] if len(c)>10 else ''
    else:  # 追加審査など継続行
        yr,start,end=c[0],c[1],c[2]
        rem=' '.join(c)
    for label,h in r['links']:
        h=''.join(h.split())
        if 'jacme.or.jp/pdf' not in h and not h.startswith('/pdf'): continue
        fn=h.split('/')[-1].split('?')[0]
        kind='past' if fn.startswith('past_') else ('additional' if '追加' in label else 'current')
        man.append({**cur,'fiscal_year':yr if kind!='past' else '','period_start':start if kind!='past' else '','period_end':end if kind!='past' else '','kind':kind,'label':label,'url':h,'file':fn,'remark':rem.strip()})
seen=set();out=[]
for m in man:
    if m['file'] in seen: continue
    seen.add(m['file']);out.append(m)
with open('knowledge/manifest.csv','w',newline='',encoding='utf-8-sig') as f:
    w=csv.DictWriter(f,fieldnames=list(out[0].keys()));w.writeheader();w.writerows(out)
print(len(out),{k:sum(1 for m in out if m['kind']==k) for k in ['current','additional','past']})
for m in out:
    p='raw/pdf/'+m['file']
    if os.path.exists(p) and os.path.getsize(p)>1000: continue
    subprocess.run(['curl','-sL','--fail','-o',p,m['url']]); time.sleep(1)
