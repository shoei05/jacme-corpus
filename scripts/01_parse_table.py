import re, html, json, csv
from bs4 import BeautifulSoup
s=BeautifulSoup(open('raw/html/evaluation_results_20261010.html',encoding='utf-8').read(),'html5lib')
rows=[];docs=[]
for t in s.find_all('table'):
    for tr in t.find_all('tr'):
        tds=tr.find_all(['td','th'])
        txt=[re.sub(r'\s+',' ',td.get_text(' ',strip=True)) for td in tds]
        links=[(a.get_text(strip=True),a['href']) for a in tr.find_all('a',href=True)]
        if any('.pdf' in h for _,h in links) or (txt and txt[0].isdigit()):
            rows.append({'cells':txt,'links':links})
json.dump(rows,open('raw/html/table_rows.json','w'),ensure_ascii=False,indent=1)
print(len(rows))
for r in rows[:4]+rows[-4:]: print(r)
