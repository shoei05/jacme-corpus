import csv, re, unicodedata, os
D=list(csv.DictReader(open('knowledge/documents.csv',encoding='utf-8-sig')))
M={r['file'].replace('.pdf',''):r for r in csv.DictReader(open('knowledge/manifest.csv',encoding='utf-8-sig'))}
os.makedirs('knowledge/reports',exist_ok=True)
idx=['# JACME 評価報告書 全文ナレッジ索引','','取得日: 2026-10-10 / 出典: https://www.jacme.or.jp/accreditation/evaluation_results.php','','| 大学 | 種別 | 巡 | 評価年度 | 基準Ver | B適合/部分 | Q適合/部分 | ファイル |','|---|---|---|---|---|---|---|---|']
for d in sorted(D,key=lambda x:(int(x['no']),x['eval_year'] or '0')):
    t=unicodedata.normalize('NFKC',open('text/'+d['doc_id']+'.txt',encoding='utf-8').read())
    t=re.sub(r'\n[ \t]*\d{1,3}[ \t]*\n','\n',t.replace('\f','\n'))
    t=re.sub(r'\n{3,}','\n\n',t)
    kind={'current':'現行','prior_cycle':'前回','additional':'追加審査'}[d['kind']]
    fn=f"{int(d['no']):02d}_{d['univ']}_{d['eval_year'] or 'NA'}_{d['kind']}.md"
    fm=['---',f"univ: {d['univ']}",f"pref: {d['pref']}",f"type: {d['type']}",f"kind: {d['kind']}",f"cycle: {d['cycle']}",f"eval_year: {d['eval_year']}",f"standard_ver: {d['standard_ver']}",f"source_url: {M[d['doc_id']]['url']}",f"source_pdf: raw/pdf/{M[d['doc_id']]['file']}",'---','',f"# {d['univ']} 医学教育分野別評価 {kind}（{d['eval_year']}年度）",'','```text',t.strip(),'```','']
    open('knowledge/reports/'+fn,'w',encoding='utf-8').write('\n'.join(fm))
    idx.append(f"| {d['univ']} | {kind} | {d['cycle']} | {d['eval_year']} | {d['standard_ver']} | {d.get('b_comp','')}/{d.get('b_part','')} | {d.get('q_comp','')}/{d.get('q_part','')} | [[reports/{fn[:-3]}]] |")
open('knowledge/INDEX.md','w',encoding='utf-8').write('\n'.join(idx)+'\n')
print(len(os.listdir('knowledge/reports')))
