// 公開データ（../data/*.json）を読む共通処理。原文・PDFは公開データに含まれない。
const DATA = '../data/';
async function loadJSON(name) {
  const r = await fetch(DATA + name + '.json');
  if (!r.ok) throw new Error(name + ' を読めません: ' + r.status);
  return r.json();
}
const LBL = {
  review_type: { main: '本審査', additional: '追加審査', notice: '公表文' },
  flag: { true: 'あり', false: 'なし', unknown: '未確認', not_applicable: '対象外' },
  tone: { positive: '肯定', must: '必須（べき）', desirable: '推奨（望まれる）', confirm: '確認', other: 'その他' },
  level: { B: '基本的水準', Q: '質的向上のための水準' },
};
function esc(s) { return String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }
function flagTag(v) { return `<span class="tag ${esc(v)}">${LBL.flag[v] || esc(v)}</span>`; }
function fillSelect(sel, values, allLabel) {
  sel.innerHTML = `<option value="">${allLabel}</option>` + values.map(v => `<option value="${esc(v[0])}">${esc(v[1])}</option>`).join('');
}
function renderHeader(current) {
  const pages = [['self-study.html', '自己点検評価報告書'], ['explore.html', '図で見る'], ['index.html', '資料・審査イベント検索'], ['matrix.html', 'テーマ・下位領域×審査の行列'], ['cards.html', '取り組みカード'], ['pilot.html', '大学別の経時・追加審査'], ['stats.html', '統計・品質・更新履歴']];
  document.getElementById('hdr').innerHTML = `<div class="inner"><span class="title">JACME評価報告書コーパス（試作）</span><nav>` +
    pages.map(([h, t]) => `<a href="${h}" class="${h === current ? 'current' : ''}">${t}</a>`).join('') + `</nav></div>`;
}
