import csv, re, json, unicodedata
rows=[r for r in csv.DictReader(open('knowledge/manifest.csv',encoding='utf-8-sig')) if r['kind']!='past']
def norm(t):
    t=unicodedata.normalize('NFKC',t)
    t=re.sub(r'\n\s*\d+\s*\n','\n',t.replace('\f','\n'))   # page numbers
    return t
JUD=r'(適合|部分的適合|不適合|評価を実施せず|評価を実施しない|評価は実施せず|部分的評価)'
VALID={'1.1','1.2','1.3','1.4','2.1','2.2','2.3','2.4','2.5','2.6','2.7','2.8','3.1','3.2','4.1','4.2','4.3','4.4','5.1','5.2','6.1','6.2','6.3','6.4','6.5','6.6','7.1','7.2','7.3','7.4','8.1','8.2','8.3','8.4','8.5','9.0'}
SUB=re.compile(r'^\s*(\d{1,2})\.(\d{1,2})\s+(\S.*?)\s*$|^\s*(9)\.()\s*(継続的改良)\s*$',re.M)
docs=[];items=[];comments=[]
for r in rows:
    t=norm(open('text/'+r['file'].replace('.pdf','.txt'),encoding='utf-8').read())
    lines=t.split('\n'); ADD='追加審査評価報告書' in t[:300]
    g=lambda p:(re.search(p,t) or [None,''])[1] if re.search(p,t) else ''
    d={'doc_id':r['file'].replace('.pdf',''),'no':r['no'],'univ':r['univ'],'pref':r['pref'],'type':r['type'],'kind':r['kind'],
       'eval_year':g(r'評価実施年度\s*(\d{4})'),'created':re.sub(r'\s','',g(r'作成日\s*([0-9]{4}\s*年\s*\d+\s*月\s*\d+\s*日)')),
       'eval_year_alt':g(r'(\d{4})\s*年度?に(?:行った|行われた|実施した)'),'standard_ver':g(r'日本版\s*Ver\.?\s*([\d.]+)'),'n_evaluators':g(r'([0-9一二三四五六七八九十]+)\s*名の評価員'),
       'additional':'追加審査評価報告書' in t[:300],'online':'オンライン' in t[:3000],'cycle2':'２巡目' in t[:3000] or '2巡目' in t[:3000]}
    if not d['eval_year']: d['eval_year']=d['eval_year_alt']
    intro=t[:2500]
    d['cycle']=2 if re.search(r'[2２]\s*巡目',intro) and not re.search(r'[1１]\s*巡目の分野別評価を受審して(?!いる。[2２])',intro) and r['kind']!='prior_cycle' else 1
    if r['kind']=='additional': d['cycle']=2 if re.search(r'[2２]\s*巡目の分野別評価を受審',intro) else 1
    if r['kind']=='current' and re.search(r'[2２]\s*巡目',intro): d['cycle']=2
    flat=re.sub(r'\s+','',t)
    m=re.search(r'基本的水準」?は(.*?)質的向上のための水準」?は(.*?)であった',flat)
    if m:
        for L,seg_ in (('b',m[1]),('q',m[2])):
            for k,lab in (('comp','適合'),('part','部分的適合'),('non','不適合'),('nae','評価を実施せず')):
                mm=re.search(r'(\d+)項目が「?'+lab+'」?',seg_.replace('部分的適合','部分的X').replace('不適合','不X') if lab=='適合' else seg_)
                d[f'{L}_{k}']=mm[1] if mm else '0'
    s=t.find('総評'); e=t.find('評価チーム',s); d['sohyo']=re.sub(r'\s+','',t[s+2:e]) if s>0 else ''
    # subarea segmentation
    pos=[]
    for m in SUB.finditer(t):
        a,b,name=(m[1],m[2],m[3]) if m[1] else (m[4],'0',m[6])
        name=re.sub(r'\[(基本的水準|質的向上のための水準)\]$','',name)
        if f'{a}.{b}' in VALID and len(name)<40 and not re.search(r'[。、)]$',name): pos.append((m.start(),a,b,name))
    seen=set();segs=[]
    for i,(p,a,b,name) in enumerate(pos):
        key=f'{a}.{b}'
        if key in seen and not ADD: continue
        seen.add(key); segs.append((p,key,name))
    if ADD:
        for i,(p,key,name) in enumerate(segs):
            end=segs[i+1][0] if i+1<len(segs) else len(t)
            seg=t[p:end]; head=t[p:p+200]
            hl=head.lstrip('\n').split('\n')[0]
            lvl='Q' if '質的向上のための水準' in hl else 'B'
            BEF=r'(?:本審査での評価|\d{4}\s*年度の評価)\s*:\s*'
            if key=='9.0' and '[質的向上のための水準]' in seg:
                k9=seg.index('[質的向上のための水準]')
                for lv,sg in (('B',seg[:k9]),('Q',seg[k9:])):
                    a1=re.search(BEF+JUD,sg); a2=re.search(r'追加審査の評価\s*:\s*'+JUD,sg)
                    items.append({'doc_id':d['doc_id'],'univ':d['univ'],'eval_year':d['eval_year'],'kind':d['kind'],'area':'9','subarea':key,'subarea_name':name,'level':lv,'judgment':a2[1] if a2 else '','judgment_before':a1[1] if a1 else ''})
            m1=re.search(BEF+JUD,seg); m2=re.search(r'追加審査の評価\s*:\s*'+JUD,seg)
            if key=='9.0' and '[質的向上のための水準]' in seg: m1=m2=None
            if not (key=='9.0' and '[質的向上のための水準]' in seg): items.append({'doc_id':d['doc_id'],'univ':d['univ'],'eval_year':d['eval_year'],'kind':d['kind'],'area':key.split('.')[0],'subarea':key,'subarea_name':name,'level':lvl,'judgment':m2[1] if m2 else '','judgment_before':m1[1] if m1 else ''})
            for blk in re.finditer(r'(特色ある点|改善のための助言|改善のための示唆|追加審査におけるコメント)\s*\n(.*?)(?=\n\s*(?:特色ある点|改善のための助言|改善のための示唆|追加審査の評価|追加審査におけるコメント|\d\.\d)|\Z)',seg,re.S):
                for c in re.split(r'\n\s*[·・•]\s*',('\n'+blk[2]))[1:]:
                    c=re.sub(r'\s+','',c)
                    if c and c!='なし': comments.append({'doc_id':d['doc_id'],'univ':d['univ'],'eval_year':d['eval_year'],'kind':d['kind'],'subarea':key,'level':lvl,'type':blk[1],'text':c})
        d['n_subareas']=len(segs); docs.append(d); continue
    for i,(p,key,name) in enumerate(segs):
        end=segs[i+1][0] if i+1<len(segs) else len(t)
        seg=t[p:end]
        for lvl,lab in [('B','基本的水準'),('Q','質的向上のための水準')]:
            m=re.search(lab+r'\s*[:：]\s*'+JUD,seg)
            items.append({'doc_id':d['doc_id'],'univ':d['univ'],'eval_year':d['eval_year'],'kind':d['kind'],'area':key.split('.')[0],'subarea':key,'subarea_name':name,'level':lvl,'judgment':m[1] if m else ''})
        # comment blocks
        for blk in re.finditer(r'(特色ある点|特記すべき良い点（特色）|改善のための助言|改善のための示唆)\s*\n(.*?)(?=\n\s*(?:特色ある点|特記すべき良い点|改善のための助言|改善のための示唆|質的向上のための水準|基本的水準)|\Z)',seg,re.S):
            typ={'特記すべき良い点（特色）':'特色ある点'}.get(blk[1],blk[1])
            lvl='Q' if (seg.rfind('質的向上のための水準',0,blk.start())>seg.rfind('基本的水準',0,blk.start())) else 'B'
            for c in re.split(r'\n\s*[·・•]\s*',('\n'+blk[2]))[1:]:
                c=re.sub(r'\s+','',c)
                c=re.split(r'(?=\d\.\d+\s|領域\d)',c)[0]
                if c and c!='なし':
                    comments.append({'doc_id':d['doc_id'],'univ':d['univ'],'eval_year':d['eval_year'],'kind':d['kind'],'subarea':key,'level':lvl,'type':typ,'text':c})
    d['n_subareas']=len(segs); docs.append(d)
for i in items:
    i['source_typo']=''
    for k in ('judgment','judgment_before'):
        if i.get(k) in ('評価は実施せず','評価を実施しない'): i[k]='評価を実施せず'
        if i.get(k)=='部分的評価': i[k]='部分的適合'; i['source_typo']='原文「部分的評価」'
prior={d['univ'] for d in docs if d['kind']=='prior_cycle'}
for d in docs:
    if d['kind']=='current' and d['univ'] in prior: d['cycle']=2
def dump(name,L):
    keys=[];[keys.append(k) for x in L for k in x if k not in keys]
    w=csv.DictWriter(open(f'knowledge/{name}.csv','w',newline='',encoding='utf-8-sig'),fieldnames=keys);w.writeheader();w.writerows(L)
dump('documents',docs);dump('judgments',items);dump('comments',comments)
import collections
print('docs',len(docs),'subareas dist',collections.Counter(d['n_subareas'] for d in docs))
print('judg blank',sum(1 for i in items if not i['judgment']),'/',len(items))
print(collections.Counter(i['judgment'] for i in items))
print(collections.Counter((c['type']) for c in comments))
print('no summary counts',[ (d['doc_id'],d['univ']) for d in docs if 'b_comp' not in d])
