/* 资产走势 · 最近 20 日与历史相似段后续路径（只读取生成数据） */
(function () {
  const NAVY = '#0E1F35', GOLD = '#A8875B', RED = '#B8402F';
  const INK = '#141313', GRID = '#F1EFE8';
  let chart = null;
  let resizeTimer = null;

  const signed = (v, d) => v == null || isNaN(v) ? '—' : (v > 0 ? '+' : '') + Number(v).toFixed(d == null ? 2 : d) + '%';
  const scenarioFor = name => (((window.WAW || {}).pattern_scenarios || {}).current || []).find(x => x.name === name);

  function stageFor(name, date) {
    const W = window.WAW || {};
    const groups = (W.cycle_phases || {})[name] || {};
    const phases = Object.keys(groups).reduce((all, key) => all.concat(groups[key] || []), []);
    const exact = phases.find(p => date >= p.start && date <= p.end && ['bull', 'bear', 'peak'].includes(p.stage));
    if (exact) {
      if (exact.stage === 'bear') return '熊市·' + exact.name;
      return '牛市·' + exact.name.replace(/^牛市/, '');
    }
    const cycles = (W.index_cycles || {})[name] || [];
    const cycle = cycles.find(c => date >= c[1] && date <= c[2]) || cycles.filter(c => c[1] <= date).slice(-1)[0];
    if (!cycle) return '阶段待定';
    const start = new Date(cycle[1] + 'T00:00:00').getTime();
    const end = new Date(cycle[2] + 'T00:00:00').getTime();
    const at = new Date(date + 'T00:00:00').getTime();
    const ratio = end > start ? Math.max(0, Math.min(0.999, (at - start) / (end - start))) : 0;
    const part = ratio < 1 / 3 ? '前段' : ratio < 2 / 3 ? '中段' : '后段';
    return (cycle[0] === 'bear' ? '熊市·' : '牛市·') + part + '（按时间）';
  }

  function dispose() {
    if (chart) { chart.dispose(); chart = null; }
  }

  function band(path, anchor) {
    return function (params, api) {
      const upper = [], lower = [];
      path.days.forEach((day, i) => {
        upper.push(api.coord([day, anchor + path.q75[i]]));
        lower.push(api.coord([day, anchor + path.q25[i]]));
      });
      return {
        type: 'polygon',
        shape: { points: upper.concat(lower.reverse()) },
        style: { fill: 'rgba(194,168,120,.20)', stroke: 'none' }
      };
    };
  }

  function empty(cat, item) {
    dispose();
    const box = document.getElementById('forward-scenario');
    const meta = document.getElementById('forward-scenario-meta');
    const name = item && item.name ? item.name : '该资产';
    if (meta) meta.textContent = name + ' · 暂未上线';
    if (box) {
      box.innerHTML = '<div class="ts-empty" role="status"><b>' + name + '历史匹配与未来路径暂未上线</b>' +
        '<p>当前仅开放 A 股指数；切换至 A 股后可查看最近走势与历史相似路径。</p></div>';
    }
  }

  function render(cat, item) {
    const box = document.getElementById('forward-scenario');
    if (!box) return;
    const scenario = item && scenarioFor(item.name);
    if (cat !== 'a' || !scenario || !scenario.path) { empty(cat, item); return; }

    const cycles = item.cycles || [];
    const current = cycles.find(c => c.current) || cycles[cycles.length - 1];
    if (!current || !current.vals || current.vals.length < 2) { empty(cat, item); return; }

    const recent = current.vals.slice(-21);
    const base = recent[0];
    const history = recent.map((v, i) => [i - (recent.length - 1), ((1 + v / 100) / (1 + base / 100) - 1) * 100]);
    // 两侧使用同一个“最近 20 日窗口起点”基准。未来收益从最新实际终点累加，
    // 不能在当前日再次归零，否则实际线与预测线会在视觉上断开。
    const anchor = history[history.length - 1][1];
    const path = scenario.path;
    const futureMedian = path.days.map((day, i) => [day, anchor + path.median[i]]);
    const futureQ25 = path.days.map((day, i) => [day, anchor + path.q25[i]]);
    const futureQ75 = path.days.map((day, i) => [day, anchor + path.q75[i]]);
    const allY = history.map(x => x[1]).concat(
      futureMedian.map(x => x[1]), futureQ25.map(x => x[1]), futureQ75.map(x => x[1]), [0]
    );
    const yMin = Math.floor(Math.min.apply(null, allY) - 1.5);
    const yMax = Math.ceil(Math.max.apply(null, allY) + 1.5);
    const meta = document.getElementById('forward-scenario-meta');
    if (meta) meta.textContent = item.name + ' · ' + scenario.n + ' 段相似样本 · 截至 ' + ((window.WAW || {}).pattern_scenarios || {}).asof;

    const catItems = ((((window.WAW || {}).cycle_overlay || {})[cat] || {}).items) || [];
    const wasOpen = box.querySelector('details') && box.querySelector('details').open;
    box.innerHTML =
      '<div class="chart-card ts-panel">' +
        '<div class="card-head"><h2>' + item.name + '</h2><span class="asof">最近 20 日 ' + signed(anchor) + '</span></div>' +
        '<div class="scope-chips af-items ts-items" aria-label="选择历史路径指数">' +
          catItems.map(x => '<button type="button" data-forward-index="' + x.key + '" aria-pressed="' + (x.key === item.key) + '"' +
            (x.key === item.key ? ' class="active"' : '') + '>' + x.name + '</button>').join('') + '</div>' +
        '<div class="rec-stats ts-stats">' +
          '<div class="rec-stat"><span>5 日中位</span><b>' + signed(scenario.next5) + '</b></div>' +
          '<div class="rec-stat"><span>10 日中位</span><b>' + signed(scenario.next10) + '</b></div>' +
          '<div class="rec-stat"><span>20 日中位</span><b>' + signed(scenario.median) + '</b></div>' +
          '<div class="rec-stat"><span>期间浮亏中位</span><b>' + signed(scenario.max_dd_median) + '</b></div>' +
        '</div>' +
        '<div class="ts-chart-wrap">' +
          '<div class="ts-legend" aria-hidden="true"><span><i class="actual"></i>最近 20 日实际</span><span><i class="median"></i>后续中位路径</span><span><i class="band"></i>中间 50% 区间</span></div>' +
          '<div id="forward-path-chart" class="chart" role="img" aria-label="' + item.name + '最近 20 日实际走势与历史相似段后续 20 日路径"></div>' +
        '</div>' +
        '<div class="af-note">20 日中间 50% 区间：' + signed(scenario.q25) + ' ～ ' + signed(scenario.q75) + '。右侧从最新实际终点接续，数值均为相对最近 20 日窗口起点的累计涨跌幅。</div>' +
        '<details class="af-collapse ts-matches"' + (wasOpen ? ' open' : '') + '>' +
          '<summary><span>历史匹配明细</span><em>' + scenario.n + ' 段 · 点击展开 / 收起</em></summary>' +
          '<div class="af-collapse-body"><div class="af-table-wrap"><table class="af-tbl ts-match-table"><thead><tr><th>序号</th><th>20 日匹配窗口</th><th>匹配结束</th><th>匹配结束所处阶段</th><th>随后 20 日</th></tr></thead><tbody>' +
            scenario.matches.map(m => '<tr><td>' + String(m.rank).padStart(2, '0') + '</td><td>' + m.window_start + ' → ' + m.match_end + '</td><td>' + m.match_end + '</td><td>' + stageFor(item.name, m.match_end) + '</td><td class="' + (m.next20 >= 0 ? 'up' : 'down') + '">' + signed(m.next20) + '</td></tr>').join('') +
          '</tbody></table></div><div class="af-note">精确阶段沿用原牛熊划分；未覆盖日期按所在牛熊区间的时间位置分为前／中／后段。</div></div>' +
        '</details>' +
      '</div>';

    box.querySelectorAll('[data-forward-index]').forEach(button => {
      button.addEventListener('click', () => {
        const upper = document.querySelector('#af-items [data-afi="' + button.dataset.forwardIndex + '"]');
        if (upper) upper.click();
      });
    });

    dispose();
    const el = document.getElementById('forward-path-chart');
    if (!el || !window.echarts) return;
    chart = echarts.init(el);
    chart.setOption({
      animation: false,
      textStyle: { fontFamily: '"PingFang SC","Microsoft YaHei",sans-serif', color: INK },
      grid: { left: 8, right: 18, top: 58, bottom: 12, containLabel: true },
      tooltip: {
        trigger: 'axis', backgroundColor: '#FFFFFF', borderColor: '#E6E1D6', borderWidth: 1,
        padding: [12, 14], textStyle: { color: INK, fontSize: 12 },
        formatter: function (points) {
          if (!points.length) return '';
          const x = points[0].value[0];
          const index = Math.round(x);
          let html = '<b>' + (x < 0 ? '当前前 ' + Math.abs(x) + ' 个交易日' : x === 0 ? '当前' : '随后第 ' + x + ' 个交易日') + '</b>';
          points.forEach(p => {
            if (p.seriesName === '区间带') return;
            html += '<br>' + p.marker + p.seriesName + ' <b>' + signed(p.value[1]) + '</b>';
          });
          if (x > 0 && path.median[index] != null) {
            html += '<br><span style="color:#635D53">较当前 ' + signed(path.median[index]) + '　中间 50% ' + signed(path.q25[index]) + ' ～ ' + signed(path.q75[index]) + '</span>';
          }
          return html;
        }
      },
      xAxis: {
        type: 'value', min: -20, max: 20, interval: 5,
        axisLine: { show: false }, axisTick: { show: false },
        axisLabel: { color: '#8A8578', fontSize: 11, formatter: v => v === 0 ? '当前' : (v > 0 ? '+' : '') + v },
        splitLine: { lineStyle: { color: GRID } }
      },
      yAxis: {
        type: 'value', min: yMin, max: yMax,
        axisLabel: { color: '#8A8578', fontSize: 11, formatter: v => v + '%' },
        axisLine: { show: false }, axisTick: { show: false }, splitLine: { lineStyle: { color: GRID } }
      },
      series: [
        { name: '区间带', type: 'custom', silent: true, data: [0], renderItem: band(path, anchor), z: 1 },
        { name: '最近 20 日实际', type: 'line', data: history, showSymbol: false, smooth: 0.16,
          lineStyle: { color: RED, width: 2.4 }, itemStyle: { color: RED }, z: 5 },
        { name: '后续中位路径', type: 'line', data: futureMedian, showSymbol: false, smooth: 0.16,
          lineStyle: { color: NAVY, width: 2.4 }, itemStyle: { color: NAVY }, z: 4,
          markLine: { silent: true, symbol: 'none', label: { show: false },
            lineStyle: { color: '#D5CFC1', type: 'dashed', width: 1 }, data: [{ xAxis: 0 }] },
          markPoint: { symbol: 'circle', symbolSize: 8,
            label: { show: true, color: NAVY, fontSize: 11, position: 'top', distance: 8,
              formatter: p => signed(p.value[1] - anchor, 1) },
            data: [{ coord: [20, anchor + path.median[20]], value: [20, anchor + path.median[20]] }] } },
        { name: '区间下沿', type: 'line', data: futureQ25, showSymbol: false, silent: true,
          lineStyle: { color: 'rgba(168,135,91,.58)', width: 1, type: 'dashed' }, itemStyle: { color: GOLD }, z: 2 },
        { name: '区间上沿', type: 'line', data: futureQ75, showSymbol: false, silent: true,
          lineStyle: { color: 'rgba(168,135,91,.58)', width: 1, type: 'dashed' }, itemStyle: { color: GOLD }, z: 2 }
      ]
    }, { notMerge: true });
  }

  window.addEventListener('resize', function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () { if (chart) chart.resize(); }, 120);
  });

  window.TrendView = { render: render };
})();
