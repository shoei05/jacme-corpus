renderHeader('self-study.html');
const SS_DATA = '../data/self-study/';
const recognitionLabel = {positive:'肯定的（暫定）',mixed:'肯定・課題の混合（暫定）',negative:'否定的（暫定）',not_stated:'明示なし（暫定）',unknown:'保留'};
const statusLabel = value => value === 'provisional_jev' ? '暫定分類あり' : '保留';
function sourceLink(url, page) {
  try {const u = new URL(url); if (!['http:','https:'].includes(u.protocol)) return '—'; if (page) u.hash = 'page=' + page;
    return `<a href="${esc(u.href)}" target="_blank" rel="noopener">PDF${page ? ' '+esc(page)+'頁' : ''}</a>`;
  } catch { return '—'; }
}
function csvValue(value) {let s = String(value ?? '');if (/^[=+@-]/.test(s)) s = "'"+s;return '"'+s.replace(/"/g,'""')+'"';}
(async () => {
  const [meta, rows, documents] = await Promise.all(['summary','area9','documents'].map(async n => {const r=await fetch(SS_DATA+n+'.json');if(!r.ok) throw Error(n+': '+r.status);return r.json();}));
  document.getElementById('metrics').innerHTML = [[meta.counts.institutions,'収集できた大学'],[meta.counts.logical_documents,'自己点検報告書（分冊統合後）'],[meta.counts.items,'抽出した基準項目（暫定）'],[meta.area9_rows,'領域9の突合行']].map(([n,t])=>`<div class="metric"><strong>${Number(n).toLocaleString('ja')}</strong><span>${esc(t)}</span></div>`).join('');
  document.getElementById('load-status').textContent='データを読み込みました。';
  const names=[...new Map(documents.map(d=>[d.institution_id,d.university])).entries()].sort((a,b)=>a[1].localeCompare(b[1],'ja'));
  fillSelect(document.getElementById('university'),names,'すべての大学');fillSelect(document.getElementById('doc-university'),names,'すべての大学');
  fillSelect(document.getElementById('criterion'),[...new Set(rows.map(r=>r.criterion_no))].sort((a,b)=>a.localeCompare(b,'ja',{numeric:true})).map(n=>[n,n]),'すべての基準');
  let filtered=[],page=0;const size=75;
  function renderTable(){
    const u=document.getElementById('university').value,c=document.getElementById('criterion').value,s=document.getElementById('status').value;
    filtered=rows.filter(r=>(!u||r.institution_id===u)&&(!c||r.criterion_no===c)&&(!s||r.jev_stage_status===s)).sort((a,b)=>a.university.localeCompare(b.university,'ja')||a.criterion_no.localeCompare(b.criterion_no,'ja',{numeric:true}));
    const pages=Math.max(1,Math.ceil(filtered.length/size));page=Math.min(page,pages-1);
    document.getElementById('row-count').textContent=filtered.length.toLocaleString('ja')+' 行／'+new Set(filtered.map(r=>r.institution_id)).size+' 大学';
    document.getElementById('area9-body').innerHTML=filtered.length?filtered.slice(page*size,(page+1)*size).map(r=>`<tr><td>${esc(r.university)}</td><td>${esc(r.cycle)||'不明'}巡／${esc(r.document_year)||'不明'}</td><td>${esc(r.criterion_no)}<br><small>版 ${esc(r.standard_version)||'不明'}</small></td><td>${esc(recognitionLabel[r.self_recognition_jev_stage]||'保留')}</td><td>下位領域 ${esc(r.concept_id)}<br>${r.level==='B'?'基本的水準':'質的向上の水準'}</td><td>${esc(r.external_judgment)||'判定未対応'}</td><td class="status">${statusLabel(r.jev_stage_status)}</td><td>${sourceLink(r.source_url,r.evidence_page)}</td></tr>`).join(''):'<tr><td colspan="8">条件に合う行はありません。</td></tr>';
    document.getElementById('page-label').textContent=(page+1)+' / '+pages;document.getElementById('prev').disabled=page===0;document.getElementById('next').disabled=page>=pages-1;document.getElementById('download').disabled=filtered.length===0;
  }
  ['university','criterion','status'].forEach(id=>document.getElementById(id).addEventListener('change',()=>{page=0;renderTable();}));
  document.getElementById('prev').onclick=()=>{page--;renderTable();};document.getElementById('next').onclick=()=>{page++;renderTable();};
  document.getElementById('download').onclick=()=>{if(!filtered.length)return;const keys=Object.keys(filtered[0]);const text='\uFEFF'+[keys.map(csvValue).join(','),...filtered.map(r=>keys.map(k=>csvValue(r[k])).join(','))].join('\r\n');const url=URL.createObjectURL(new Blob([text],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='jacme-area9-filtered-20261017.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
  function renderDocs(){const u=document.getElementById('doc-university').value;const ds=documents.filter(d=>!u||d.institution_id===u).sort((a,b)=>a.university.localeCompare(b.university,'ja')||a.document_year.localeCompare(b.document_year));document.getElementById('doc-count').textContent=ds.length+' 文書';document.getElementById('docs-body').innerHTML=ds.map(d=>`<tr><td>${esc(d.university)}</td><td>${esc(d.cycle)||'不明'}</td><td>${esc(d.document_year)||'不明'}</td><td>${esc(d.standard_version)||'不明'}</td><td>${Number(d.pages).toLocaleString('ja')}</td><td>${esc({high:'高確信',medium:'中間',low:'低確信'}[d.link_confidence]||d.link_confidence||'未確認')}</td><td>${sourceLink(d.source_url)}</td></tr>`).join('');}
  document.getElementById('doc-university').onchange=renderDocs;
  const counts=meta.comparison_counts;document.getElementById('download-counts').textContent=`全領域：自己記述と外部判定 ${counts.a.toLocaleString('ja')}行／助言との対応 ${counts.b.toLocaleString('ja')}行／経時比較 ${counts.c.toLocaleString('ja')}行／取り組み分類 ${counts.d.toLocaleString('ja')}行。いずれも保留行を含みます。`;
  document.getElementById('quality').innerHTML=`<p>対象82大学中75大学から収集。未入手・未確定7大学。96 PDF・28,508頁を整理し、Jev段階では109,226セルに判定を付けました。うち55,456セルを暫定利用、53,770セルを未解決として保存しています。分類の確信度は正しさの保証ではありません。</p>`;
  renderTable();renderDocs();
})().catch(err=>{const el=document.getElementById('load-status');el.className='error';el.textContent='読み込みに失敗しました。再読み込みしてください。('+err.message+')';});
