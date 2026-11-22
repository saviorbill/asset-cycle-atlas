/* 综合建议 · 本期观察资产（只渲染生成结果，不改写数据） */
(function () {
  const $ = id => document.getElementById(id);
  const num = (v, d) => v == null || isNaN(v) ? '—' : Number(v).toFixed(d == null ? 1 : d);
  const data = () => (window.WAW || {}).recommendations || { summary: {}, indices: [], sectors: [] };

  function component(label, value, suffix) {
    const digits = suffix && suffix.indexOf(' 段') >= 0 ? 0 : 1;
    return '<span>' + label + '<b>' + num(value, digits) + (suffix || '') + '</b></span>';
  }

  function indexItem(row) {
    const c = row.components || {};
    return '<article class="watch-item">' +
      '<div class="watch-item-head"><div><span class="watch-name">' + row.name + '</span>' +
        '<span class="watch-action">' + row.action + '</span></div>' +
        '<div class="watch-score">' + num(row.score, 1) + '<small>/100</small></div></div>' +
      '<div class="watch-formula">综合分＝<b>65% × ' + num(c.rule60, 1) + '＋35% × ' + num(c.model60, 1) + '＝' + num(row.score, 1) + '</b></div>' +
      '<div class="watch-components">' +
        component('同档 60 日原始胜率', c.win60, '%') +
        component('独立样本', c.segments60, ' 段') +
        component('收缩胜率', c.rule60) +
        component('模型 60 日上行估计', c.model60, '%') +
      '</div>' +
      '<div class="watch-sample">收缩胜率＝50＋（原始胜率－50）× 独立段数 ÷（独立段数＋3）。' +
        (c.segments60 < 5 ? '本期独立样本少于 5 段，评分仅作观察，不升级为仓位建议。' : '独立样本达到 5 段，仍须结合操作档位执行。') + '</div>' +
    '</article>';
  }

  function sectorItem(row) {
    const c = row.components || {};
    const values = [c.tech, c.fund, c.sent, c.win60, c.model_rank];
    const labels = ['技术', '基本面', '情绪', '同档 60 日胜率', '模型排名'];
    const present = values.map((v, i) => ({ label: labels[i], value: v })).filter(x => x.value != null);
    const formula = present.map(x => num(x.value, 1)).join('＋');
    return '<article class="watch-item">' +
      '<div class="watch-item-head"><div><span class="watch-name">' + row.name + '</span>' +
        '<span class="watch-action">' + row.action + '</span></div>' +
        '<div class="watch-score">' + num(row.score, 1) + '<small>/100</small></div></div>' +
      '<div class="watch-formula">综合分＝<b>（' + formula + '）÷' + present.length + '＝' + num(row.score, 1) + '</b></div>' +
      '<div class="watch-components">' + present.map(x => component(x.label, x.value)).join('') +
        component('独立样本', c.segments60, ' 段') + '</div>' +
      '<div class="watch-sample">五个维度等权；同档 60 日胜率使用原始值，独立样本不少于 8 段且原规则为“偏买入”后纳入候选。</div>' +
    '</article>';
  }

  function renderList(id, rows, renderer, emptyText) {
    const el = $(id);
    if (!el) return;
    el.innerHTML = rows.length ? rows.map(renderer).join('') : '<div class="watch-empty">' + emptyText + '</div>';
  }

  function render() {
    const R = data();
    renderList('index-watch', R.indices || [], indexItem, '本期没有指数达到观察线，暂不新增指数观察项。');
    renderList('sector-watch', R.sectors || [], sectorItem, '本期没有板块达到原筛选条件，暂不新增板块观察项。');
    const S = R.summary || {};
    if ($('index-watch-meta')) $('index-watch-meta').textContent = (R.indices || []).length + ' 项';
    if ($('sector-watch-meta')) $('sector-watch-meta').textContent = (R.sectors || []).length + ' 项 / ' + (S.sector_eligible || 0) + ' 项符合原筛选';
  }

  window.ResearchView = { render };
})();
