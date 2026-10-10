import csv, subprocess, re, os, json
rows=list(csv.DictReader(open('knowledge/manifest.csv',encoding='utf-8-sig')))
stat=[]
for r in rows:
    p='raw/pdf/'+r['file']; out='text/'+r['file'].replace('.pdf','.txt')
    info=subprocess.run(['pdfinfo',p],capture_output=True,text=True).stdout
    pages=int(re.search(r'Pages:\s+(\d+)',info).group(1))
    subprocess.run(['pdftotext','-layout',p,out])
    t=open(out,encoding='utf-8',errors='ignore').read()
    jp=len(re.findall(r'[぀-ヿ一-鿿]',t))
    per=[len(re.findall(r'[぀-ヿ一-鿿]',pg)) for pg in t.split('\f')[:pages]]
    low=sum(1 for x in per if x<50)
    stat.append({'file':r['file'],'univ':r['univ'],'kind':r['kind'],'pages':pages,'jp_chars':jp,'chars_per_page':round(jp/max(pages,1)),'low_text_pages':low})
w=csv.DictWriter(open('knowledge/text_layer_check.csv','w',newline='',encoding='utf-8-sig'),fieldnames=stat[0].keys());w.writeheader();w.writerows(stat)
need=[s for s in stat if s['chars_per_page']<200 or s['low_text_pages']>s['pages']*0.2]
print('total pages',sum(s['pages'] for s in stat),'docs',len(stat))
print('OCR candidates',len(need))
for s in need: print(s)
