"""行単位の状態機械でコメントを抽出する。judgments は 05_structure.py の結果を使う。"""
import csv, re, unicodedata, collections
VALID={'1.1','1.2','1.3','1.4','2.1','2.2','2.3','2.4','2.5','2.6','2.7','2.8','3.1','3.2','4.1','4.2','4.3','4.4','5.1','5.2','6.1','6.2','6.3','6.4','6.5','6.6','7.1','7.2','7.3','7.4','8.1','8.2','8.3','8.4','8.5'}
D=list(csv.DictReader(open('knowledge/documents.csv',encoding='utf-8-sig')))
TYPES=[('特記すべき良い点','特色ある点'),('特色ある点','特色ある点'),('改善のための助言','改善のための助言'),('改善のための示唆','改善のための示唆'),('追加審査におけるコメント','追加審査におけるコメント')]
BUL=re.compile('^\\s*[\u00b7\u2022\ue000-\uf8ff]\\s*(.*)$')
out=[];gaihyo=[]
for d in D:
    t=unicodedata.normalize('NFKC',open('text/'+d['doc_id']+'.txt',encoding='utf-8').read()).replace('\f','\n')
    lines=t.split('\n')
    area=sub=None;lvl='B';typ=None;cur=None;state=None;gbuf=[]
    def flush():
        global cur
        if cur and cur['text'] and not cur['text'].startswith('なし'):
            out.append(cur)
        cur=None
    for ln in lines:
        s=ln.strip()
        if not s: continue
        if re.search(r'医学部医学科\s*評価報告書',s) and len(s)<50: continue
        if re.fullmatch(r'\d{1,3}',s) or '評価報告書(確定版)' in s and len(s)<60 and not s.startswith('·'): continue
        m=re.match(r'^(\d)\.(\d)\s+(\S[^。]{0,35})$',s); m9=re.match(r'^9\.\s*継続的改良',s); ma=re.match(r'^(\d)\.\s+(\S{2,20})$',s)
        if m and f'{m[1]}.{m[2]}' in VALID:
            flush(); sub=f'{m[1]}.{m[2]}'; area=m[1]; typ=None; state=None
            lvl='Q' if '質的向上' in s else 'B'; continue
        if m9 or (ma and area and int(ma[1])==int(area)+1) :
            flush(); 
            if gbuf and area: gaihyo.append({'doc_id':d['doc_id'],'area':area,'text':''.join(gbuf)})
            gbuf=[]; area=('9' if m9 else ma[1]); sub=('9.0' if m9 else None); typ=None; state=None; lvl='B'; continue
        if s.startswith('概評'): flush(); state='gaihyo'; typ=None; continue
        if re.match(r'^\[?(基本的水準)',s) or s.startswith('[基本的水準]'): flush(); lvl='B'; typ=None; state=None; continue
        if re.match(r'^\[?質的向上のための水準',s): flush(); lvl='Q'; typ=None; state=None; continue
        if re.match(r'^(本審査での評価|追加審査の評価|\d{4}\s*年度の評価)',s): flush(); typ=None; state=None; continue
        hit=[v for k,v in TYPES if s.startswith(k)]
        if hit: flush(); typ=hit[0]; state='cm'; continue
        if s.startswith(('医学部は','医科大学・医学部は','評価チーム')) : flush(); typ=None; state=None; continue
        if state=='gaihyo':
            gbuf.append(s); continue
        if state=='cm' and typ and sub:
            b=BUL.match(ln)
            if b: flush(); cur={'doc_id':d['doc_id'],'univ':d['univ'],'eval_year':d['eval_year'],'kind':d['kind'],'area':area,'subarea':sub,'level':lvl,'type':typ,'text':b[1].strip()}
            elif cur: cur['text']+=s
            elif s and not s.startswith('なし'):  # bullet記号が落ちた行
                cur={'doc_id':d['doc_id'],'univ':d['univ'],'eval_year':d['eval_year'],'kind':d['kind'],'area':area,'subarea':sub,'level':lvl,'type':typ,'text':s}
    flush()
    if gbuf and area: gaihyo.append({'doc_id':d['doc_id'],'area':area,'text':''.join(gbuf)})
out=[c for c in out if re.sub(r'[\s\ue000-\uf8ff]+','',c['text']) not in ('なし','')]
for c in out:
    c['text']=re.sub(r'[\s\ue000-\uf8ff]+','',c['text'])
    c['text']=re.sub(r'\S{2,12}(?:大学|大学校)医学部医学科評価報告書(?:\(確定版\))?$','',c['text'])
    c['tone']='must' if re.search(r'すべきである|しなければならない',c['text']) else ('desirable' if re.search(r'望まれる|期待される',c['text']) else ('positive' if c['type']=='特色ある点' else ''))
w=csv.DictWriter(open('knowledge/comments.csv','w',newline='',encoding='utf-8-sig'),fieldnames=out[0].keys());w.writeheader();w.writerows(out)
w=csv.DictWriter(open('knowledge/area_gaihyo.csv','w',newline='',encoding='utf-8-sig'),fieldnames=gaihyo[0].keys());w.writeheader();w.writerows(gaihyo)
print(len(out),collections.Counter(c['type'] for c in out),'gaihyo',len(gaihyo))
C=collections.Counter(c['doc_id'] for c in out);diffs=[]
for d in D:
    t=unicodedata.normalize('NFKC',open('text/'+d['doc_id']+'.txt').read())
    s=t.find('\n1. 使命と学修成果'); s=s if s>0 else 0
    b=[x for x in re.findall(r'\n\s*[·•]\s*(\S{0,4})',t[s:]) if not x.startswith('なし')]
    diffs.append((C[d['doc_id']]-len(b),d['doc_id'],d['univ'],len(b),C[d['doc_id']]))
diffs.sort(); print(diffs[:6],diffs[-6:]); print('exact',sum(1 for x in diffs if x[0]==0),'|abs<=2',sum(1 for x in diffs if abs(x[0])<=2),'of',len(diffs))
