/* ===== Where are we? · TradingView/ADV 风格交互逻辑 ===== */
(function () {
  const W = window.WAW;
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const _asofEl = document.getElementById('asof'); if (_asofEl) _asofEl.textContent = W.asof;
  const _footAsof = document.getElementById('foot-asof'); if (_footAsof) _footAsof.textContent = W.asof;

  // 顶级金融机构配色
  const C = {
    bg: '#F6F4EF', panel: '#FFFFFF', ink: '#141313', muted: '#635D53',
    accent: '#A8875B', accentD: '#8E6F3E', up: '#B8402F', down: '#2E7D5B',
    grid: 'rgba(20,19,19,.05)', axis: 'rgba(20,19,19,.28)', line: 'rgba(20,19,19,.08)',
  };
  const SERIES = ['#0E1F35', '#A8875B', '#2E7D5B', '#B8402F', '#1B3350', '#8E6F3E', '#4A6FA5', '#7D3C98'];
  const charts = {};
  const FONT_STACK = '-apple-system,BlinkMacSystemFont,"SF Pro Text","Inter","Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei","Noto Sans SC",sans-serif';
  const CHART_OPTS = { textStyle: { fontFamily: FONT_STACK } };

  const RANGES = [
    { k: 'ytd', label: '今年以来' }, { k: '1y', label: '近1年' }, { k: '3y', label: '近3年' },
    { k: '5y', label: '近5年' }, { k: '10y', label: '近10年' }, { k: 'all', label: '全部' },
  ];

  // ---------- 全局研究口径：基准指数 + 区间 ----------
  const QP = new URLSearchParams(location.search);
  const INDEX_LIST = ['上证指数', '沪深300', '创业板指', '中证500', '中证1000', '中证2000', '科创50'];
  const SCOPE = {
    index: INDEX_LIST.indexOf(QP.get('idx')) >= 0 ? QP.get('idx')
      : (INDEX_LIST.indexOf(QP.get('gidx')) >= 0 ? QP.get('gidx') : '上证指数'),
    range: RANGES.some(r => r.k === QP.get('grange')) ? QP.get('grange') : 'all',
  };
  function ts(s) { return Date.parse(s + 'T00:00:00'); }
  // 时间戳 → 本地日期（toISOString 会按 UTC 偏移，东八区会少一天）
  function fmtDate(v) {
    const d = new Date(v); const p = n => String(n).padStart(2, '0');
    return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate());
  }
  // ---------- 数字规范：千分位、固定小数、显式正负号 ----------
  const _nf = {};
  function nf(d) {
    return _nf[d] || (_nf[d] = new Intl.NumberFormat('en-US', { minimumFractionDigits: d, maximumFractionDigits: d }));
  }
  function isNil(v) { return v == null || typeof v !== 'number' || isNaN(v); }
  function fmtNum(v, d) { return isNil(v) ? '—' : nf(d == null ? 2 : d).format(v); }
  function fmtSigned(v, d, unit) {
    if (isNil(v)) return '—';
    d = d == null ? 1 : d;
    return (v > 0 ? '+' : '') + nf(d).format(v) + (unit || '');
  }
  function fmtUnit(v, d, unit) {
    if (isNil(v)) return '—';
    const s = nf(d == null ? 2 : d).format(v);
    if (!unit) return s;
    return unit === '%' ? s + '%' : s + ' ' + unit;
  }
  // 东方财富式 K 线悬浮框：开高低收、涨跌额/幅、成交额，红涨绿跌
  function klineTipHtml(date, o, h, l, c, prevClose, amt, extra) {
    const pct = (!isNil(prevClose) && prevClose !== 0 && !isNil(c)) ? (c / prevClose - 1) * 100 : null;
    const chg = (!isNil(prevClose) && !isNil(c)) ? c - prevClose : null;
    const cls = pct == null ? 'kt-flat' : (pct > 0 ? 'kt-up' : pct < 0 ? 'kt-down' : 'kt-flat');
    const row = (k, v, c2) => '<div class="kt-r"><span>' + k + '</span><b class="' + (c2 || cls) + '">' + v + '</b></div>';
    let s = '<div class="k-tip"><div class="k-tip-d">' + date + '</div>';
    s += row('开盘', fmtNum(o, 2)) + row('最高', fmtNum(h, 2)) +
      row('最低', fmtNum(l, 2)) + row('收盘', fmtNum(c, 2));
    s += row('涨跌额', chg == null ? '—' : fmtSigned(chg, 2)) +
      row('涨跌幅', pct == null ? '—' : fmtSigned(pct, 2, '%'));
    if (amt != null) s += row('成交额', fmtNum(amt / 1e8, 0) + ' 亿元', 'kt-flat');
    if (extra) s += extra;
    return s + '</div>';
  }
  // 传入 0–1 的分位值，输出 0–100%
  function fmtPct(v, d) { return isNil(v) ? '—' : nf(d == null ? 0 : d).format(v * 100) + '%'; }
  function fmtAxis(v) {
    if (isNil(v)) return '';
    if (v === 0) return '0';
    const a = Math.abs(v);
    if (a >= 1e12) return nf(a % 1e12 === 0 ? 0 : 1).format(v / 1e12) + '万亿';
    if (a >= 1e8) return nf(a % 1e8 === 0 ? 0 : 1).format(v / 1e8) + '亿';
    if (a >= 1e4) return nf(a % 1e4 === 0 ? 0 : 1).format(v / 1e4) + '万';
    if (a >= 100) return nf(0).format(v);
    return nf(a >= 10 ? 0 : 1).format(v);
  }
  function pctlCls(p) { return isNil(p) ? '' : (p >= 0.7 ? 'up' : p <= 0.3 ? 'down' : ''); }
  function pctile(arr, v) {
    const a = arr.filter(x => x != null && !isNaN(x)).slice().sort((p, q) => p - q);
    if (!a.length || v == null) return null;
    let k = 0; while (k < a.length && a[k] <= v) k++;
    return k / a.length;
  }
  function percentileVal(arr, p) {
    const a = arr.filter(x => x != null && !isNaN(x)).slice().sort((x, y) => x - y);
    if (!a.length) return null;
    const idx = Math.min(a.length - 1, Math.max(0, Math.floor(p * (a.length - 1))));
    return a[idx];
  }
  // 分类轴用的区间起点（按日期，而不是固定日线根数，周/月线也正确）
  function rangeStartDate(dates, key) {
    if (!dates.length || key === 'all') return null;
    const d = new Date(dates[dates.length - 1] + 'T00:00:00');
    const p = n => String(n).padStart(2, '0');
    if (key === 'ytd') return d.getFullYear() + '-01-01';
    const yrs = { '1y': 1, '3y': 3, '5y': 5, '10y': 10 }[key];
    if (!yrs) return null;
    const t = new Date(d); t.setFullYear(t.getFullYear() - yrs);
    return t.getFullYear() + '-' + p(t.getMonth() + 1) + '-' + p(t.getDate());
  }

  // ---------- 图表工厂：统计条 + 图表(+最新值线/P30P50P70) ----------
  function buildChart(divId, opts) {
    const el = document.getElementById(divId);
    if (!el) return null;
    const card = el.closest('.chart-card');

    // 统计条
    let st = card.querySelector('.chart-stats');
    if (!st) { st = document.createElement('div'); st.className = 'chart-stats'; card.insertBefore(st, el); }

    const data = opts.data; // {dates:[], series:[{name, values, color}]}
    const dec = opts.decimals == null ? 2 : opts.decimals;
    // 有单位的序列，坐标轴沿用该单位，不再二次缩写（标题已标注单位）
    const axisFmt = function (v) {
      if (isNil(v)) return '';
      if (!opts.unit || opts.unit === '%') return fmtAxis(v);
      return nf(Math.abs(v) >= 100 || v === 0 ? 0 : 1).format(v);
    };
    const chart = charts[divId] || echarts.init(el);
    charts[divId] = chart;

    function render(data) {
      const dates = data.dates;
      const xs = dates.map(ts);
      const primary = data.series[0].values;
      const lastV = primary[primary.length - 1];
      const p30 = percentileVal(primary, 0.30), p50 = percentileVal(primary, 0.50), p70 = percentileVal(primary, 0.70);
      const pctl = pctile(primary, lastV);
      // 统计条
      if (opts.statsHtml != null) {
        st.innerHTML = opts.statsHtml;
      } else {
        let _h = '<span class="stat"><b>最新</b> ' + fmtUnit(lastV, dec, opts.unit) + '</span>' +
          '<span class="stat"><b>历史分位</b> <em class="' + pctlCls(pctl) + '">' + fmtPct(pctl, 0) + '</em></span>';
        if (opts.showPct && !opts.hidePctStats) _h += '<span class="stat p">P30 ' + fmtNum(p30, dec) + '</span><span class="stat p">P50 ' + fmtNum(p50, dec) + '</span><span class="stat p">P70 ' + fmtNum(p70, dec) + '</span>';
        st.innerHTML = _h;
      }

      const series = data.series.map((s, i) => ({
        name: s.name, type: 'line', showSymbol: false, smooth: true, connectNulls: false,
        data: xs.map((t, j) => [t, s.values[j]]),
        lineStyle: { color: s.color || SERIES[i % SERIES.length], width: s.width || 1.9 },
        itemStyle: { color: s.color || SERIES[i % SERIES.length] },
        areaStyle: (s.area || (opts.area && data.series.length === 1)) ? { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(201,169,106,.16)' }, { offset: 1, color: 'rgba(201,169,106,0)' }] } } : undefined,
        emphasis: { focus: 'series' },
      }));

      // markLine: P30/P50/P70 + 最新值
      let mkLines;
      if (opts.noPct) {
        mkLines = [{ yAxis: 0, lineStyle: { color: 'rgba(0,0,0,.22)', type: 'dashed', width: 1 }, label: { formatter: '基准 0%', position: 'insideEndTop', color: '#7A7367', fontSize: 12 } }];
      } else if (opts.showPct) {
        mkLines = [
          { yAxis: p30, lineStyle: { color: 'rgba(20,19,19,.14)', type: 'dashed', width: 1 }, label: { show: false } },
          { yAxis: p50, lineStyle: { color: 'rgba(20,19,19,.20)', type: 'dashed', width: 1 }, label: { show: false } },
          { yAxis: p70, lineStyle: { color: 'rgba(20,19,19,.14)', type: 'dashed', width: 1 }, label: { show: false } },
          { yAxis: lastV, lineStyle: { color: C.accentD, type: 'dashed', width: 1.6 }, label: { show: false } },
        ];
      } else {
        mkLines = [
          { yAxis: lastV, lineStyle: { color: C.accentD, type: 'dashed', width: 1.6 }, label: { show: false } },
        ];
      }
      // 标注专用系列：不参与图例开关，保证任意隐藏某条指数后牛熊/事件标注仍在
      const annoSeries = {
        name: '__anno__', type: 'line', data: xs.map(t => [t, null]),
        showSymbol: false, silent: true, z: 1,
        lineStyle: { width: 0, opacity: 0 }, itemStyle: { opacity: 0 },
        markLine: { silent: true, symbol: 'none', data: mkLines },
      };
      // 只保留与当前数据区间相交的牛熊段，并把起止裁剪到数据范围内
      const cyc = opts.cycleSegs || (opts.cycleShade ? (W.index_cycles[SCOPE.index] || W.index_cycles['上证指数']) : null) || [];
      const segs = cyc
        .filter(sg => sg && sg[1] <= dates[dates.length - 1] && sg[2] >= dates[0])
        .map(sg => [sg[0], sg[1] < dates[0] ? dates[0] : sg[1], sg[2] > dates[dates.length - 1] ? dates[dates.length - 1] : sg[2]]);
      if (segs.length) {
        annoSeries.markArea = { silent: true, data: segs.map(sg => [
          { xAxis: ts(sg[1]), itemStyle: { color: sg[0] === 'bull' ? 'rgba(184,147,92,.13)' : 'rgba(96,116,142,.12)' } },
          { xAxis: ts(sg[2]) },
        ]) };
      }
      if (opts.markPoints && opts.markPoints.length) {
        annoSeries.markPoint = { symbolSize: 7, silent: true, data: opts.markPoints, label: { fontSize: 12, color: C.muted } };
      }
      series.push(annoSeries);
      chart.setOption({
        textStyle: CHART_OPTS.textStyle,
        grid: { left: 8, right: 16, top: 34, bottom: opts.zoom === false ? 28 : 54, containLabel: true },
        legend: data.series.length > 1 ? { data: data.series.map(s => s.name), selected: opts.legendSelected || {}, top: 0, textStyle: { color: C.ink, fontSize: 11.5 }, icon: 'roundRect', itemWidth: 14, itemHeight: 3 } : undefined,
        tooltip: {
          trigger: 'axis', confine: true,
          axisPointer: { type: 'cross', crossStyle: { color: 'rgba(0,0,0,.35)' }, lineStyle: { color: 'rgba(0,0,0,.35)', type: 'dashed' }, label: { backgroundColor: C.accent } },
          backgroundColor: 'rgba(255,255,255,.98)', borderColor: C.line, borderRadius: 6,
          textStyle: { color: C.ink, fontSize: 12 },
          formatter: function (ps) {
            ps = (ps || []).filter(p => p.seriesName !== '__anno__');
            if (!ps.length) return '';
            const ds = fmtDate(ps[0].value[0]);
            let h = '<b>' + ds + '</b>';
            ps.forEach(p => { h += '<br/>' + p.marker + p.seriesName + '：<b>' + fmtUnit(p.value[1], dec, opts.unit) + '</b>'; });
            const f = opts.cycleShade ? findCycle(ds) : null;
            if (f) h += '<br/><span style="color:' + C.accentD + '">区间：' + f.cycle.name + ' · ' + (f.seg.type === 'bull' ? '牛市' : '熊市') + '</span>';
            return h;
          },
        },
        xAxis: { type: 'time', axisLine: { lineStyle: { color: C.axis } }, axisTick: { show: false }, axisLabel: { color: C.muted, fontSize: 12 }, splitLine: { show: false } },
        yAxis: { type: 'value', scale: true, splitNumber: 4, splitLine: { lineStyle: { color: C.grid } }, axisLabel: { color: C.muted, fontSize: 12, formatter: axisFmt } },
        dataZoom: opts.zoom === false ? [] : [
          { type: 'inside' },
          { type: 'slider', height: 16, bottom: 8, borderColor: 'transparent', fillerColor: 'rgba(201,169,106,.12)', handleStyle: { color: C.accent }, dataBackground: { lineStyle: { color: 'rgba(0,0,0,.15)' }, areaStyle: { color: 'rgba(0,0,0,.04)' } }, textStyle: { color: C.muted, fontSize: 12 } },
        ],
        series,
      }, { notMerge: true });

      // 当前观察、宏观页固定展示全区间；单图仍可用滑块缩放
      if (opts.zoomRange) {
        chart.dispatchAction({ type: 'dataZoom', startValue: opts.zoomRange[0], endValue: opts.zoomRange[1] });
      } else if (opts.zoom !== false) {
        chart.dispatchAction({ type: 'dataZoom', start: 0, end: 100 });
      }
    }

    render(data);
    return { chart, render };
  }

  // ---------- 周期工具 ----------
  function cycleMarkArea() {
    const arr = [];
    W.cycles.forEach(cy => cy.segments.forEach(seg => arr.push([
      { xAxis: ts(seg.start), itemStyle: { color: seg.type === 'bull' ? 'rgba(184,147,92,.12)' : 'rgba(96,116,142,.11)' } },
      { xAxis: ts(seg.end) },
    ])));
    return { silent: true, data: arr };
  }
  function findCycle(dateStr) {
    for (const cy of W.cycles) {
      if (dateStr >= cy.start && (cy.end ? dateStr <= cy.end : true)) {
        for (const seg of cy.segments) if (dateStr >= seg.start && dateStr <= seg.end) return { cycle: cy, seg };
        return { cycle: cy, seg: cy.segments[cy.segments.length - 1] };
      }
    }
    return null;
  }

  // ---------- 全局口径：基准指数（区间控件在主图工具栏内） ----------
  function renderScopeBar() {
    const iBox = document.getElementById('scope-index');
    if (!iBox) return;
    iBox.innerHTML = INDEX_LIST.map(k =>
      '<button data-gidx="' + k + '"' + (k === SCOPE.index ? ' class="active"' : '') + '>' + k + '</button>').join('');
    $$('[data-gidx]', iBox).forEach(b => b.addEventListener('click', () => setScopeIndex(b.dataset.gidx)));
  }

  function setScopeIndex(i) {
    if (INDEX_LIST.indexOf(i) < 0 || i === SCOPE.index) return;
    SCOPE.index = i;
    renderScopeBar();
    histIndex = i; histPhase = null; historyFirstRender = true;
    // 事件时间轴固定不变，仅刷新右侧对照图与阶段统计
    refreshCycleLensIndex(i);
    if (histInit) renderHistory();
    if (document.body.dataset.view === 'history') refreshCycleOverview();
    if (document.body.dataset.view === 'cycle') renderCyclePage(detailCycleId, true);
    if (curInit) { renderNsf(); renderLongIndicators(); renderIndicators(); }
    if (macroInit) rebuildMacro();
  }

  function setScopeRange(r) {
    if (!RANGES.some(x => x.k === r) || r === SCOPE.range) return;
    SCOPE.range = r;
    $$('[data-grange]').forEach(b => b.classList.toggle('active', b.dataset.grange === r));
    applyHistoryRange(r);
  }

  function disposeChartsIn(root) {
    if (!root) return;
    Object.keys(charts).forEach(id => {
      const el = document.getElementById(id);
      if (!el || root.contains(el)) {
        try { charts[id].dispose(); } catch (e) { }
        delete charts[id];
      }
    });
  }

  function rebuildMacro() {
    const grid = document.getElementById('macro-grid');
    const body = document.getElementById('macro-corr-body');
    disposeChartsIn(grid);
    if (grid) { grid.innerHTML = ''; delete grid.dataset.done; }
    if (body) { body.innerHTML = ''; delete body.dataset.done; }
    renderMacro();
  }

  // ---------- K线懒加载（data-kline.js 约2.5MB，首次进入复盘/当前观察时再下） ----------
  let _klineLoading = false, _klineLoaded = false, _klineQueue = [];
  function ensureKline(cb) {
    if (_klineLoaded || (W.kline && W.kline['上证指数'] && W.kline['上证指数'].open)) {
      _klineLoaded = true; if (cb) cb(); return;
    }
    if (cb) _klineQueue.push(cb);
    if (_klineLoading) return;
    _klineLoading = true;
    var s2 = document.createElement('script');
    s2.src = 'data-kline.js?v=20261118c';
    s2.async = true;
    s2.onload = function () {
      if (window.WAW_KLINE) W.kline = window.WAW_KLINE;
      _klineLoaded = true; _klineLoading = false;
      _klineQueue.splice(0).forEach(function (f) { try { f(); } catch (e) { console.error(e); } });
    };
    s2.onerror = function () {
      _klineLoading = false;
      _klineQueue.splice(0).forEach(function (f) { try { f(); } catch (e) { console.error(e); } });
    };
    document.head.appendChild(s2);
  }

  // ---------- 按视图懒加载（数据分块 + 次要模块），首屏只留核心 ----------
  const _assetLoaded = {};
  function ensureAssets(files, cb) {
    let i = 0;
    (function next() {
      while (i < files.length && _assetLoaded[files[i]]) i++;
      if (i >= files.length) { if (cb) cb(); return; }
      const f = files[i++];
      const sc = document.createElement('script');
      sc.src = f + '?v=20261122a';
      sc.async = true;
      sc.onload = function () { _assetLoaded[f] = 1; next(); };
      sc.onerror = function () { _assetLoaded[f] = 1; next(); };
      document.head.appendChild(sc);
    })();
  }
  const CUR_ASSETS = ['data-cur.js', 'data-overlay.js', 'state_score.js', 'hist_stats.js', 'ml_model.js', 'models_extra.js', 'conclusion.js', 'recommendations.js'];
  const TRENDS_ASSETS = ['data-overlay.js', 'pattern_scenarios.js', 'conclusion.js', 'hist_stats.js', 'models_extra.js'];
  const HIST_ASSETS = ['data-overlay.js', 'data-hist.js', 'cycle_stats.js', 'cycle_analysis.js', 'pullback_stats.js'];
  const MACRO_ASSETS = ['data-macro.js', 'models_extra.js'];
  function withDeps(files, cb) { ensureAssets(files, function () { if (cb) cb(); }); }

  // ---------- 视图切换 ----------
  let histInit = false, curInit = false, macroInit = false, trendsInit = false;
  function go(view) {
    document.body.dataset.view = view;
    $$('.view').forEach(v => v.classList.remove('active'));
    const el = document.getElementById('view-' + view); if (el) el.classList.add('active');
    $$('.tn-item[data-view]').forEach(n => n.classList.toggle('active', n.dataset.view === view));
    const _assets = document.getElementById('nav-assets');
    if (_assets) _assets.classList.toggle('active', view === 'history' || view === 'cycle' || view === 'macro');
    $$('.menu-item[data-view="history"]').forEach(n => n.classList.toggle('active', view === 'history' || view === 'cycle'));
    const _curNav = document.getElementById('nav-current');
    if (_curNav) _curNav.classList.toggle('active', view === 'trends' || view === 'current');
    $$('.menu-item[data-view="trends"]').forEach(n => n.classList.toggle('active', view === 'trends'));
    $$('.menu-item[data-view="current"]').forEach(n => n.classList.toggle('active', view === 'current'));
    window.scrollTo({ top: 0, behavior: 'smooth' });
    if (view === 'history' && !histInit) {
      histInit = true;
      withDeps(HIST_ASSETS, function () {
        ensureKline(function () {
          setTimeout(function () {
            renderHistory();
            renderCycleOverview();
          }, 40);
        });
      });
    } else if (view === 'history') {
      // 从其他页面切回时容器才重新可见，按当前宽度重算主图纵向布局
      withDeps(HIST_ASSETS, function () { ensureKline(function () { setTimeout(renderHistory, 30); }); });
    }
    if (view === 'cycle') {
      syncCycleTabs();
      withDeps(HIST_ASSETS, function () {
        ensureKline(function () { setTimeout(function () { renderCyclePage(detailCycleId || W.cycles[W.cycles.length - 1].id); }, 40); });
      });
    }
    if (view === 'history') { syncCycleTabs(); renderCycleOverview(); }
    if (view === 'trends' && !trendsInit) {
      trendsInit = true;
      withDeps(TRENDS_ASSETS, function () { setTimeout(renderTrends, 40); });
    } else if (view === 'trends') {
      withDeps(TRENDS_ASSETS, function () { setTimeout(renderTrends, 30); });
    }
    if (view === 'current' && !curInit) {
      curInit = true;
      withDeps(CUR_ASSETS, function () { ensureKline(function () { setTimeout(renderCurrent, 40); }); });
    }
    if (view === 'macro' && !macroInit) {
      macroInit = true;
      withDeps(MACRO_ASSETS, function () { setTimeout(renderMacro, 40); });
    }
    setTimeout(() => Object.values(charts).forEach(c => c.resize()), 80);
    // 复盘页首次可见后再建对照图，避免在隐藏容器里按 0 宽初始化
    if (view === 'history' || view === 'cycle') withDeps(HIST_ASSETS, function () { ensureKline(function () { setTimeout(function () { updateCycleLens(true); }, 60); }); });
  }
  $$('.tn-item[data-view], .menu-item[data-view]').forEach(n => n.addEventListener('click', () => go(n.dataset.view)));

  // ---------- 历史复盘 ----------
  let histFreq = 'week', histCycle = null;
  let histChartData = null;
  let histIndex = SCOPE.index;
  let detailCycleId = null;      // 单轮叙事页当前周期
  let cycleTab = 'index';        // 单轮统计页签：index | sector | stock
  let cycleFreq = 'week';        // 单轮主图频度
  let cycleMode = 'kline';       // 单轮主图：kline | line
  let epChartSeq = 0;            // 回调/反弹小图唯一 id
  let historyFirstRender = true;
  const HIDE = (function () { const q = QP.get('hide'); return q ? q.split(',') : []; })();
  const EV_COLOR = { bottom: '#B8402F', top: '#2E7D5B', policy: '#A8875B', risk: '#8E6F3E', up: '#B8402F', now: '#0E1F35' };
  function eventColor(t) { return EV_COLOR[t] || '#6B6B6B'; }

  function aggregateOHLC(k, freq) {
    if (freq === 'day') return k;
    const keyFn = freq === 'week'
      ? (dstr) => { const d = new Date(dstr + 'T00:00:00'); const o = new Date(d.getFullYear(), 0, 1); return d.getFullYear() + '-W' + String(Math.ceil(((d - o) / 86400000 + o.getDay() + 1) / 7)).padStart(2, '0'); }
      : (dstr) => dstr.slice(0, 7);
    const bk = {}; const order = [];
    k.dates.forEach((d, i) => {
      const key = keyFn(d);
      const v = (k.vol && k.vol[i]) ? k.vol[i] : 0;
      const am = (k.amt && k.amt[i]) ? k.amt[i] : 0;
      if (!bk[key]) { bk[key] = { date: d, open: k.open[i], high: k.high[i], low: k.low[i], close: k.close[i], vol: v, amt: am }; order.push(key); }
      else { const b = bk[key]; b.date = d; b.high = Math.max(b.high, k.high[i]); b.low = Math.min(b.low, k.low[i]); b.close = k.close[i]; b.vol += v; b.amt += am; }
    });
    const out = { dates: [], open: [], high: [], low: [], close: [], vol: [], amt: [] };
    order.forEach(key => { const b = bk[key]; out.dates.push(b.date); out.open.push(b.open); out.high.push(b.high); out.low.push(b.low); out.close.push(b.close); out.vol.push(b.vol); out.amt.push(b.amt); });
    return out;
  }

  function lastValid(arr) { for (let i = arr.length - 1; i >= 0; i--) if (arr[i] != null) return arr[i]; return null; }

  function cycleContext(key) {
    const kl = W.kline && W.kline[key];
    const dates = kl ? kl.dates : W.main_daily.dates;
    const closes = kl ? kl.close : W.main_daily[key];
    let idxStart = null;
    for (let i = 0; i < closes.length; i++) if (closes[i] != null) { idxStart = dates[i]; break; }
    if (!idxStart) idxStart = dates[0] || '1990-01-01';
    let effCycle = histCycle;
    if (effCycle) { const cy0 = W.cycles.find(c => c.id === effCycle); if (!cy0 || (cy0.end || W.asof) < idxStart) effCycle = null; }
    const allEvs = W.index_events[key] || [];
    const valAt = (ds) => { const i = nearestIdx(dates, ds); return closes[i]; };
    let mp = [];
    if (effCycle) {
      const cy = W.cycles.find(c => c.id === effCycle); const st = cy.start, en = cy.end || W.asof;
      mp = allEvs.filter(e => e.date >= st && e.date <= en).map(e => {
        const v = valAt(e.date); if (v == null) return null;
        return { coord: [e.date, v], value: e.label, symbolSize: 6, itemStyle: { color: eventColor(e.type) }, label: { formatter: e.label, position: (e.type === 'top' || e.type === 'risk') ? 'top' : 'bottom', fontSize: 12, color: eventColor(e.type) } };
      }).filter(Boolean);
    } else {
      mp = allEvs.filter(e => e.kind === 'tp').map(e => {
        const v = valAt(e.date); if (v == null) return null;
        const isBull = e.type === 'bottom';
        return { coord: [e.date, v], value: e.label, symbolSize: 6, itemStyle: { color: isBull ? C.up : C.down }, label: { formatter: isBull ? '底' : '顶', position: isBull ? 'bottom' : 'top', color: isBull ? C.up : C.down, fontSize: 12 } };
      }).filter(Boolean);
    }
    let zoomRange = null;
    if (effCycle) { const cy = W.cycles.find(c => c.id === effCycle); if (cy) zoomRange = [cy.start, cy.end || W.asof]; }
    return { effCycle, mp, zoomRange };
  }
  let histMode = 'kline';
  let histPhase = null;
  let cycleLensState = null;
  let lensRaf = null;
  let lensMode = 'line';  // line | kline
  const FREQ_LABEL = { day: '日', week: '周', month: '月' };
  const EV_PRIORITY = { tp: 3, risk: 2, policy: 1, up: 0 };
  const PHASE_SHORT = { '底部初期': '底部/初期', '牛市中期': '中期', '牛市后期': '后期', '转熊': '转熊' };
  const ALL_INDICES = ['上证指数', '沪深300', '创业板指', '中证500', '中证1000', '中证2000', '科创50'];

  // ---------- 工具栏下拉：图形 / 周期 / 区间 / 牛熊 ----------
  const CYCLE_ICON_PATHS = {
    home: '<rect x="2.6" y="2.6" width="4.6" height="4.6" rx=".8"/><rect x="8.8" y="2.6" width="4.6" height="4.6" rx=".8"/><rect x="2.6" y="8.8" width="4.6" height="4.6" rx=".8"/><rect x="8.8" y="8.8" width="4.6" height="4.6" rx=".8"/>',
    c0508: '<path d="M2.4 13.6h11.2M3.2 6.6h9.6M3.2 6.6 8 3l4.8 3.6M4.6 6.6v7M8 6.6v7M11.4 6.6v7"/>',
    c1315: '<rect x="4.7" y="1.9" width="6.6" height="12.2" rx="1.3"/><path d="M6.8 12.2h2.4M6.3 4.3h3.4"/>',
    c1618: '<path d="M2.4 6.4h11.2v7.2H2.4zM2 6.4 3.2 3h9.6l1.2 3.4M6 9h4v4.6"/>',
    c1921: '<circle cx="8" cy="8" r="2.5"/><path d="M8 1.5v1.7M8 12.8v1.7M1.5 8h1.7M12.8 8h1.7M3.4 3.4l1.2 1.2M11.4 11.4l1.2 1.2M3.4 12.6l1.2-1.2M11.4 4.6l1.2-1.2"/>',
    c24now: '<rect x="4.6" y="4.6" width="6.8" height="6.8" rx="1"/><path d="M6.5 2v2.6M9.5 2v2.6M6.5 11.4V14M9.5 11.4V14M2 6.5h2.6M2 9.5h2.6M11.4 6.5H14M11.4 9.5H14"/>',
  };
  function cycleIcon(id, cls) {
    const p = CYCLE_ICON_PATHS[id] || CYCLE_ICON_PATHS.home;
    return '<svg class="cy-ic' + (cls ? ' ' + cls : '') + '" viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.35" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + p + '</svg>';
  }
  function rangeLabel(k) { const r = RANGES.find(x => x.k === k); return r ? r.label : '全部'; }
  function tbDrop(key, label, value, menuHtml, cls) {
    return '<div class="tb-drop' + (cls ? ' ' + cls : '') + '" data-drop="' + key + '">' +
      '<button type="button" class="tb-key" aria-haspopup="true" aria-expanded="false">' +
      '<span class="tb-k">' + label + '</span><span class="tb-v">' + value + '</span>' +
      '<svg class="tb-caret" viewBox="0 0 10 10" width="9" height="9" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2.5 3.8 5 6.3l2.5-2.5"/></svg>' +
      '</button><div class="tb-menu">' + menuHtml + '</div></div>';
  }
  function tbItem(attrs, label, active, sub, icon) {
    return '<button type="button" class="tb-mi' + (active ? ' active' : '') + '" ' + attrs + '>' +
      (icon ? '<span class="tb-mi-ic">' + icon + '</span>' : '') +
      '<span class="tb-mi-t">' + label + (sub ? '<small>' + sub + '</small>' : '') + '</span>' +
      '<span class="tb-mi-ck">' + (active ? '✓' : '') + '</span></button>';
  }
  function closeTbMenus(except) {
    $$('.tb-drop.open').forEach(d => {
      if (d === except) return;
      d.classList.remove('open');
      const b = d.querySelector('.tb-key'); if (b) b.setAttribute('aria-expanded', 'false');
    });
  }
  function positionTbMenu(drop) {
    const menu = drop.querySelector('.tb-menu');
    if (!menu) return;
    menu.style.position = ''; menu.style.left = ''; menu.style.right = ''; menu.style.top = ''; menu.style.width = '';
    menu.style.maxHeight = ''; menu.style.overflowY = '';
    if (window.innerWidth <= 720) {
      const r = drop.getBoundingClientRect();
      menu.style.position = 'fixed';
      menu.style.left = '8px';
      menu.style.right = '8px';
      menu.style.width = 'auto';
      menu.style.top = (r.bottom + 5) + 'px';
      menu.style.maxHeight = 'calc(100vh - ' + Math.round(r.bottom + 13) + 'px)';
      menu.style.overflowY = 'auto';
    }
  }
  function bindTbMenus(tb) {
    $$('.tb-drop', tb).forEach(drop => {
      const btn = drop.querySelector('.tb-key');
      if (!btn) return;
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        const willOpen = !drop.classList.contains('open');
        closeTbMenus(drop);
        drop.classList.toggle('open', willOpen);
        btn.setAttribute('aria-expanded', String(willOpen));
        if (willOpen) positionTbMenu(drop);
      });
    });
  }
  document.addEventListener('click', function (e) {
    if (!e.target.closest('.tb-drop')) closeTbMenus();
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closeTbMenus();
  });
  window.addEventListener('scroll', function () { closeTbMenus(); }, { passive: true });
  window.addEventListener('resize', function () { closeTbMenus(); });
  window.addEventListener('resize', function () {
    ['chart-ml', 'chart-sec'].forEach(function (id) {
      if (charts[id] && charts[id].getDom() && charts[id].getDom().offsetParent) charts[id].resize();
    });
  });

  function nearestIdx(dates, ds) {
    if (!dates.length) return 0;
    if (ds <= dates[0]) return 0;
    if (ds >= dates[dates.length - 1]) return dates.length - 1;
    let lo = 0, hi = dates.length - 1;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (dates[mid] < ds) lo = mid + 1; else hi = mid; }
    const a0 = lo > 0 ? lo - 1 : 0;
    const da = Math.abs(new Date(dates[a0] + 'T00:00:00') - new Date(ds + 'T00:00:00'));
    const db = Math.abs(new Date(dates[lo] + 'T00:00:00') - new Date(ds + 'T00:00:00'));
    return db < da ? lo : a0;
  }
  function nearestCat(dates, ds) { return dates[nearestIdx(dates, ds)]; }

  function pickEventsByPeriod(evs, freq) {
    if (freq === 'day') return evs;
    const keyFn = freq === 'week'
      ? (d) => { const dt = new Date(d + 'T00:00:00'); const o = new Date(dt.getFullYear(), 0, 1); return dt.getFullYear() + '-W' + Math.ceil(((dt - o) / 86400000 + o.getDay() + 1) / 7); }
      : (d) => d.slice(0, 7);
    const best = {};
    evs.forEach(e => { const k = keyFn(e.date); if (!best[k] || (EV_PRIORITY[e.kind] || 0) > (EV_PRIORITY[best[k].kind] || 0)) best[k] = e; });
    return Object.values(best);
  }

  function buildMarkArea(cycleSegs, key, effCycle, useCategory, dates) {
    const X = useCategory ? (d) => nearestCat(dates, d) : (d) => ts(d);
    if (!effCycle) {
      return cycleSegs.map(sg => [{ xAxis: X(sg[1]), itemStyle: { color: sg[0] === 'bull' ? 'rgba(184,147,92,.13)' : 'rgba(96,116,142,.12)' } }, { xAxis: X(sg[2]) }]);
    }
    const phs = getPhases(key, effCycle);
    if (!phs.length) return [];
    return phs.map(p => {
      const c = p.stage === 'bear' ? 'rgba(96,116,142,.12)' : (p.stage === 'peak' ? 'rgba(176,46,36,.15)' : 'rgba(184,147,92,.12)');
      return [{ xAxis: X(p.start), itemStyle: { color: c } }, { xAxis: X(p.end) }];
    });
  }

  function getPhases(idx, cycleId) {
    const cp = (W.cycle_phases && W.cycle_phases[idx]) || (W.cycle_phases && W.cycle_phases['上证指数']) || {};
    const phs = (cp[cycleId] || []).slice();
    const bottom = phs.find(p => p.name === '底部环境');
    const early = phs.find(p => p.name === '牛市初期');
    let out = phs.filter(p => p.name !== '底部环境' && p.name !== '牛市初期' && p.name !== '牛市顶点');
    if (bottom || early) {
      const s0 = bottom ? bottom.start : early.start;
      const e0 = early ? early.end : bottom.end;
      out.unshift({ name: '底部初期', start: s0, end: e0, stage: 'bull' });
    }
    return out;
  }

  function buildPhaseList(idx, kd, ctx) {
    if (!ctx || !ctx.effCycle) return [];
    const phs = getPhases(idx, ctx.effCycle);
    const d = kd.dates, c = kd.close, v = kd.amt || [];
    return phs.map(p => {
      const si = nearestIdx(d, p.start), ei = nearestIdx(d, p.end);
      const seg = c.slice(si, ei + 1), vseg = v.slice(si, ei + 1);
      let peak = -Infinity, mdd = 0;
      seg.forEach(x => { if (x > peak) peak = x; const dd = x / peak - 1; if (dd < mdd) mdd = dd; });
      const ret = seg.length ? (seg[seg.length - 1] / seg[0] - 1) * 100 : null;
      const avgVol = vseg.length ? vseg.reduce((a, b) => a + (b || 0), 0) / vseg.length : null;
      const daily = (W.kline && W.kline[idx] && W.kline[idx].dates) || [];
      const wdays = daily.filter(dd => dd >= p.start && dd <= p.end).length || (ei - si + 1);
      return { name: p.name, sCat: d[si], eCat: d[ei], ret: ret == null ? null : (Math.round(ret * 10) / 10), mdd: Math.round(mdd * 1000) / 10, width: wdays, avgVol: avgVol == null ? null : avgVol / 1e8, stage: p.stage };
    });
  }

  function histEventScatter(idx, dates, closes, ctx) {
    const evs = (W.index_events && W.index_events[idx]) || [];
    let list = (ctx && ctx.effCycle)
      ? evs.filter(e => { const cy = W.cycles.find(c => c.id === ctx.effCycle); return cy && e.date >= cy.start && e.date <= (cy.end || W.asof); })
      : evs.filter(e => e.kind === 'tp');
    list = pickEventsByPeriod(list, histFreq);
    return list.map(e => {
      const ii = nearestIdx(dates, e.date);
      const isTop = e.type === 'top' || e.type === 'risk';
      return { value: [ii, closes[ii]], name: e.label, evDate: e.date, itemStyle: { color: eventColor(e.type) }, label: { show: true, formatter: e.label, position: isTop ? 'top' : 'bottom', fontSize: 12, color: eventColor(e.type) } };
    });
  }

  // 主图纵向分配：价格区尽量高，成交量与区间滑块压到紧凑的一小条
  function klineGridLayout(el) {
    const cssH = parseFloat(getComputedStyle(el).height);
    const H = el.clientHeight || (isFinite(cssH) && cssH > 0 ? cssH : 500);
    const top = 30;
    const sliderH = 12, sliderBottom = 4, xRoom = 22;
    const volH = Math.max(22, Math.round(Math.min(38, H * 0.075)));
    const volTop = H - sliderBottom - sliderH - xRoom - volH;
    const priceH = Math.max(120, volTop - top - 20);
    return { top, priceH, volTop, volH, sliderH, sliderBottom };
  }

  // 共享 K 线绘制：分类轴 + 成交量 + 事件散点 + 阶段框 + 阶段高亮/变暗
  function drawKlineGrid(containerId, idx, kd, ctx, cycleSegs, zoomStartPct, phases) {
    const el = document.getElementById(containerId);
    const ch = charts[containerId] || echarts.init(el); charts[containerId] = ch;
    const dates = kd.dates;
    const candle = dates.map((d, i) => [kd.open[i], kd.close[i], kd.low[i], kd.high[i]]);
    const vol = dates.map((d, i) => ({ value: (kd.amt && kd.amt[i]) || 0, itemStyle: { color: kd.close[i] >= kd.open[i] ? 'rgba(184,64,47,.5)' : 'rgba(46,125,91,.5)' } }));
    const lastC = lastValid(kd.close);
    const lastLabel = (ctx && ctx.effCycle)
      ? (((W.cycles.find(c => c.id === ctx.effCycle) || {}).ongoing) ? '最新 ' : '期末 ')
      : '最新 ';
    const evs = histEventScatter(idx, dates, kd.close, ctx);
    // 窄屏隐藏事件文字，只保留圆点与悬浮提示，避免标签互相压叠
    const narrow = el.clientWidth < 560;
    if (narrow) evs.forEach(e => { if (e.label) e.label.show = false; });
    phases = phases || [];
    // 阶段框 / 高亮 / 变暗
    let annoArea = buildMarkArea(cycleSegs, idx, ctx && ctx.effCycle, true, dates);
    let hlArea = [], dimArea = [];
    if (histPhase) {
      const ph = phases.find(p => p.name === histPhase);
      if (ph) {
        const sIdx = dates.indexOf(ph.sCat), eIdx = dates.indexOf(ph.eCat);
        if (sIdx > 0) dimArea.push([{ xAxis: dates[0], itemStyle: { color: 'rgba(250,249,246,.62)' } }, { xAxis: dates[sIdx] }]);
        if (eIdx < dates.length - 1) dimArea.push([{ xAxis: dates[eIdx], itemStyle: { color: 'rgba(250,249,246,.62)' } }, { xAxis: dates[dates.length - 1] }]);
        hlArea = [[{ xAxis: ph.sCat, itemStyle: { color: 'rgba(168,135,91,.10)', borderColor: '#A8875B', borderWidth: 2 } }, { xAxis: ph.eCat }]];
      }
    }
    const GL = klineGridLayout(el);
    ch.setOption({
      textStyle: CHART_OPTS.textStyle, animation: false,
      grid: [{ left: 58, right: 84, top: GL.top, height: GL.priceH }, { left: 58, right: 84, top: GL.volTop, height: GL.volH }],
      axisPointer: { link: [{ xAxisIndex: 'all' }] },
      legend: { show: false },
      tooltip: {
        trigger: 'axis', confine: true, axisPointer: { type: 'cross', lineStyle: { color: 'rgba(20,19,19,.35)', type: 'dashed' }, label: { backgroundColor: C.accent } },
        backgroundColor: 'rgba(255,255,255,.98)', borderColor: C.line, borderRadius: 6, textStyle: { color: C.ink, fontSize: 12 },
        formatter: function (ps) {
          if (!ps || !ps.length) return '';
          const date = ps[0].axisValue;
          let h = '';
          const c = ps.find(p => p.seriesType === 'candlestick');
          const evHtml = ps.filter(p => p.seriesType === 'scatter')
            .map(p => '<div class="kt-r"><span>事件</span><b style="color:' + p.color + '">' + p.data.name + '</b></div>').join('');
          if (c) {
            const i = c.dataIndex;
            const prev = i > 0 ? kd.close[i - 1] : null;
            h = klineTipHtml(date, kd.open[i], kd.high[i], kd.low[i], kd.close[i], prev, kd.amt ? kd.amt[i] : null, evHtml);
          } else {
            h = '<b>' + date + '</b>' + evHtml;
          }
          return h;
        }
      },
      xAxis: [
        { type: 'category', data: dates, gridIndex: 0, axisLine: { lineStyle: { color: C.axis } }, axisTick: { show: false }, axisLabel: { show: false }, splitLine: { show: false } },
        { type: 'category', data: dates, gridIndex: 1, axisLine: { lineStyle: { color: C.axis } }, axisTick: { show: false }, axisLabel: { color: C.muted, fontSize: 12, hideOverlap: true }, splitLine: { show: false } },
      ],
      yAxis: [
        { type: 'value', gridIndex: 0, scale: true, splitLine: { lineStyle: { color: C.grid } }, axisLabel: { color: C.muted, fontSize: 12, formatter: fmtAxis } },
        { type: 'value', gridIndex: 1, min: 0, splitNumber: 1, splitLine: { show: false }, axisLabel: { show: false } },
      ],
      dataZoom: [
        { type: 'inside', xAxisIndex: [0, 1] },
        { type: 'slider', xAxisIndex: [0, 1], height: GL.sliderH, bottom: GL.sliderBottom, borderColor: 'transparent', fillerColor: 'rgba(168,135,91,.14)', handleStyle: { color: C.accent }, dataBackground: { lineStyle: { color: 'rgba(20,19,19,.15)' }, areaStyle: { color: 'rgba(20,19,19,.04)' } }, textStyle: { color: C.muted, fontSize: 11.5 } },
      ],
      series: [
        { name: idx, type: 'candlestick', xAxisIndex: 0, yAxisIndex: 0, data: candle, itemStyle: { color: C.up, color0: C.down, borderColor: C.up, borderColor0: C.down }, emphasis: { itemStyle: { borderWidth: 1.5 } } },
        { name: '成交额', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: vol, barWidth: '60%' },
        { name: '__events__', type: 'scatter', xAxisIndex: 0, yAxisIndex: 0, data: evs, symbolSize: 9, z: 12, labelLayout: { hideOverlap: true }, emphasis: { itemStyle: { borderColor: '#fff', borderWidth: 2, shadowBlur: 8, shadowColor: 'rgba(0,0,0,.35)' }, label: { fontSize: 12, fontWeight: 'bold' } } },
        { name: '__dim__', type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: [], showSymbol: false, silent: true, z: 18, lineStyle: { width: 0, opacity: 0 }, itemStyle: { opacity: 0 }, markArea: { silent: true, data: dimArea } },
        { name: '__hl__', type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: [], showSymbol: false, silent: true, z: 16, lineStyle: { width: 0, opacity: 0 }, itemStyle: { opacity: 0 }, markArea: { silent: true, data: hlArea } },
        { name: '__anno__', type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: [], showSymbol: false, silent: true, z: 1, lineStyle: { width: 0, opacity: 0 }, itemStyle: { opacity: 0 },
          markLine: { silent: true, symbol: 'none', data: [{ yAxis: lastC, lineStyle: { color: C.accentD, type: 'dashed', width: 1.5 }, label: { show: !narrow, formatter: lastLabel + fmtNum(lastC, 0), position: 'end', distance: 6, color: C.accentD, fontSize: 11.5, fontWeight: 'bold' } }] },
          markArea: { silent: true, data: annoArea } },
      ],
    }, { notMerge: true });
    if (zoomStartPct != null) ch.dispatchAction({ type: 'dataZoom', start: zoomStartPct, end: 100 });
    else if (ctx && ctx.zoomRange) {
      const cy = W.cycles.find(c => c.id === ctx.effCycle);
      const i0 = cy ? nearestIdx(dates, cy.start) : 0, i1 = cy ? nearestIdx(dates, cy.end || W.asof) : dates.length - 1;
      ch.dispatchAction({ type: 'dataZoom', startValue: dates[i0], endValue: dates[i1] });
    } else ch.dispatchAction({ type: 'dataZoom', start: 0, end: 100 });
    return { ch, dates, lastC };
  }

  function histToolbar(card, el, phases) {
    let tb = card.querySelector('.chart-toolbar');
    if (!tb) { tb = document.createElement('div'); tb.className = 'chart-toolbar'; card.insertBefore(tb, el); }
    const cy = histCycle ? W.cycles.find(c => c.id === histCycle) : null;
    const modeLabel = { kline: '蜡烛图', line: '折线图', all: '多指数对比' }[histMode] || '蜡烛图';
    const idxMenu = INDEX_LIST.map(k => tbItem('data-gidx="' + k + '"', k, k === SCOPE.index)).join('');
    const modeMenu = [['kline', '蜡烛图'], ['line', '折线图'], ['all', '多指数对比']]
      .map(m => tbItem('data-tbmode="' + m[0] + '"', m[1], histMode === m[0])).join('');
    const freqMenu = ['day', 'week', 'month'].map(k =>
      tbItem('data-tbfreq="' + k + '"', FREQ_LABEL[k] + '线', histFreq === k)).join('');
    const rangeMenu = RANGES.map(r =>
      tbItem('data-grange="' + r.k + '"', r.label, !cy && SCOPE.range === r.k)).join('');
    const cyMenu = tbItem('data-tbcycle="all"', '全历史', !histCycle) +
      W.cycles.map(c => tbItem('data-tbcycle="' + c.id + '"',
        shortCycleName(c.name) + ' · ' + c.type, histCycle === c.id, '', cycleIcon(c.id))).join('');
    tb.innerHTML =
      tbDrop('idx', '指数', SCOPE.index, idxMenu, 'tb-scope') +
      '<span class="tb-div" aria-hidden="true"></span>' +
      tbDrop('mode', '图形', modeLabel, modeMenu) +
      tbDrop('freq', '周期', FREQ_LABEL[histFreq] + '线', freqMenu) +
      tbDrop('range', '区间', cy ? '本轮区间' : rangeLabel(SCOPE.range), rangeMenu) +
      tbDrop('cycle', '牛熊', cy ? shortCycleName(cy.name) : '全历史', cyMenu, 'tb-cycle tb-right') +
      '<span class="toolbar-asof"><span class="dot"></span>数据截至 <b>' + W.asof + '</b></span>';
    bindTbMenus(tb);
    $$('[data-gidx]', tb).forEach(b => b.addEventListener('click', function () {
      closeTbMenus();
      setScopeIndex(b.dataset.gidx);
    }));
    $$('[data-tbmode]', tb).forEach(b => b.addEventListener('click', function () {
      closeTbMenus();
      histMode = b.dataset.tbmode; histPhase = null; renderHistory();
    }));
    $$('[data-tbfreq]', tb).forEach(b => b.addEventListener('click', function () {
      closeTbMenus();
      histFreq = b.dataset.tbfreq; renderHistory();
    }));
    $$('[data-grange]', tb).forEach(b => b.addEventListener('click', function () {
      const k = b.dataset.grange;
      closeTbMenus();
      if (histCycle) {
        histCycle = null; SCOPE.range = k;
        syncCycleTabs(); renderCycleOverview(); renderHistory();
        applyHistoryRange(k);
      } else {
        setScopeRange(k);
        renderHistory();
      }
    }));
    $$('[data-tbcycle]', tb).forEach(b => b.addEventListener('click', function () {
      closeTbMenus();
      const id = b.dataset.tbcycle;
      if (id === 'all') {
        histCycle = null; syncCycleTabs();
        ensureKline(function () { renderHistory(); renderCycleOverview(); });
      } else selectCycle(id);
    }));
    return tb;
  }

  // 当前图表区间（牛熊阶段或时间区间）的表现统计
  function rangePerf(kd, ctx) {
    if (!kd || !kd.dates || !kd.dates.length) return null;
    const dates = kd.dates, closes = kd.close, highs = kd.high, lows = kd.low;
    const cy = ctx.effCycle ? W.cycles.find(c => c.id === ctx.effCycle) : null;
    let start = null, label;
    if (cy) { start = cy.start; label = cy.name; }
    else if (SCOPE.range !== 'all') { start = rangeStartDate(dates, SCOPE.range); label = rangeLabel(SCOPE.range); }
    else label = '全历史';

    let i0 = start ? dates.findIndex(d => d >= start) : 0;
    if (i0 < 0) i0 = 0;
    let i1 = dates.length - 1;
    if (cy) {
      const en = cy.end || W.asof;
      while (i1 >= i0 && dates[i1] > en) i1--;
    }
    let f = -1, l = -1;
    for (let j = i0; j <= i1; j++) if (closes[j] != null) { f = j; break; }
    for (let j = i1; j >= i0; j--) if (closes[j] != null) { l = j; break; }
    if (f < 0 || l < f) return null;

    // 区间收益用区间前一交易日收盘为基准；牛熊阶段用阶段起点收盘，和阶段统计口径一致
    let base = null;
    if (!cy) for (let j = f - 1; j >= 0; j--) if (closes[j] != null) { base = closes[j]; break; }
    const first = base == null ? closes[f] : base;
    const last = closes[l];
    if (first == null || last == null) return null;
    const ret = (last / first - 1) * 100;

    const seq = base == null ? [] : [base];
    for (let j = f; j <= l; j++) if (closes[j] != null) seq.push(closes[j]);
    let peak = seq[0], mdd = 0;
    seq.forEach(v => { if (v > peak) peak = v; const dd = (v / peak - 1) * 100; if (dd < mdd) mdd = dd; });

    const rs = [];
    for (let j = 1; j < seq.length; j++) rs.push(seq[j] / seq[j - 1] - 1);
    let vol = null;
    if (rs.length > 1) {
      const mu = rs.reduce((a, b) => a + b, 0) / rs.length;
      const va = rs.reduce((a, b) => a + (b - mu) * (b - mu), 0) / rs.length;
      const periods = { day: 252, week: 50.4, month: 12 }[histFreq] || 252;
      vol = Math.sqrt(va * periods) * 100;
    }

    let lo = null, hi = null;
    for (let j = f; j <= l; j++) {
      if (highs[j] != null && (hi == null || highs[j] > hi)) hi = highs[j];
      if (lows[j] != null && (lo == null || lows[j] < lo)) lo = lows[j];
    }
    const amp = hi != null && lo ? (hi / lo - 1) * 100 : null;
    return { label, ret, vol, mdd, amp };
  }

  function histStats(st, kd, ctx) {
    if (!st) return;
    const p = rangePerf(kd, ctx);
    if (!p) { st.innerHTML = '<span class="stat"><b>区间统计</b> —</span>'; return; }
    st.innerHTML =
      '<span class="stat"><b>' + p.label + '</b> <em class="' + (p.ret >= 0 ? 'up' : 'down') + '">' + fmtSigned(p.ret, 1, '%') + '</em></span>' +
      '<span class="stat"><b>年化波动</b> ' + (isNil(p.vol) ? '—' : fmtNum(p.vol, 1) + '%') + '</span>' +
      '<span class="stat"><b>最大回撤</b> <em class="down">' + (isNil(p.mdd) ? '—' : fmtSigned(p.mdd, 1, '%')) + '</em></span>' +
      '<span class="stat"><b>区间振幅</b> ' + (isNil(p.amp) ? '—' : fmtNum(p.amp, 1) + '%') + '</span>';
  }

  function renderHistoryKline(idx, el, card, tb, st, ctx, cycleSegs, kd, phases) {
    histStats(st, kd, ctx);
    drawKlineGrid('chart-history', idx, kd, ctx, cycleSegs, null, phases);
    histChartData = { dates: kd.dates };
  }

  function renderHistoryAllKline(el, card, tb, st) {
    const rows = ALL_INDICES.map(n => { const k = W.kline[n]; return k ? { name: n, kd: aggregateOHLC(k, histFreq) } : null; }).filter(Boolean);
    const n = rows.length;
    // 公共起点 = 各指数首日的最大值
    const startDate = rows.reduce((m, r) => r.kd.dates[0] > m ? r.kd.dates[0] : m, '');
    const dateSet = new Set();
    rows.forEach(r => r.kd.dates.filter(d => d >= startDate).forEach(d => dateSet.add(d)));
    const dates = Array.from(dateSet).sort();
    rows.forEach(r => { r.map = {}; r.kd.dates.forEach((d, j) => { r.map[d] = j; }); });
    const colors = ['#0E1F35', '#4A6FA5', '#1B3350', '#7D3C98', '#2E7D5B', '#A8875B', '#B8402F'];
    st.innerHTML = '<span class="stat"><b>全部指数 K 线对比</b> ' + n + ' 个指数 · ' + FREQ_LABEL[histFreq] + '线</span>' +
      '<span class="stat"><b>归一化</b> 起点=100（' + startDate + '）</span>' +
      '<span class="stat p">图例可开关单个指数</span>';
    const series = rows.map((r, i) => {
      const baseIdx = Math.max(0, r.kd.dates.findIndex(d => d >= startDate));
      const base = r.kd.close[baseIdx] || 1;
      const data = dates.map(d => {
        const j = r.map[d];
        if (j == null) return [null, null, null, null];
        return [r.kd.open[j] / base * 100, r.kd.close[j] / base * 100, r.kd.low[j] / base * 100, r.kd.high[j] / base * 100];
      });
      const col = colors[i % colors.length];
      return { name: r.name, type: 'candlestick', xAxisIndex: 0, yAxisIndex: 0, data: data, itemStyle: { color: col, color0: col, borderColor: col, borderColor0: col } };
    });
    el.style.height = '500px';
    const ch = charts['chart-history'] || echarts.init(el); charts['chart-history'] = ch;
    ch.setOption({
      textStyle: CHART_OPTS.textStyle, animation: false,
      grid: { left: 62, right: 18, top: 44, bottom: 42 },
      legend: { top: 0, data: rows.map(r => r.name), textStyle: { color: C.ink, fontSize: 12 }, itemWidth: 10, itemHeight: 3 },
      tooltip: { trigger: 'axis', axisPointer: { type: 'cross', lineStyle: { color: 'rgba(20,19,19,.3)', type: 'dashed' } }, backgroundColor: 'rgba(255,255,255,.98)', borderColor: C.line, textStyle: { color: C.ink, fontSize: 11.5 },
        formatter: function (ps) { if (!ps || !ps.length) return ''; let h = '<b>' + ps[0].axisValue + '</b>'; ps.filter(p => p.seriesType === 'candlestick').forEach(p => { h += '<br/>' + p.marker + p.seriesName + '：' + (p.data[1] == null ? '—' : fmtNum(p.data[1], 1)); }); return h; } },
      legendHoverLink: true,
      xAxis: { type: 'category', data: dates, axisLine: { lineStyle: { color: C.axis } }, axisTick: { show: false }, axisLabel: { color: C.muted, fontSize: 12, hideOverlap: true }, splitLine: { show: false } },
      yAxis: { type: 'value', scale: true, splitLine: { lineStyle: { color: C.grid } }, axisLabel: { color: C.muted, fontSize: 12, formatter: fmtAxis } },
      dataZoom: [{ type: 'inside' }, { type: 'slider', height: 12, bottom: 4, borderColor: 'transparent', fillerColor: 'rgba(168,135,91,.14)', handleStyle: { color: C.accent }, textStyle: { color: C.muted, fontSize: 11.5 } }],
      series,
    }, { notMerge: true });
    ch.resize();
    ch.dispatchAction({ type: 'dataZoom', start: 0, end: 100 });
    histChartData = { dates: dates };
  }
  function renderHistoryLine(idx, el, card, tb, st, ctx, cycleSegs, kd, phases) {
    if (!kd) return;
    const dates = kd.dates, closes = kd.close;
    const lastC = lastValid(closes);
    histStats(st, kd, ctx);
    let annoArea = buildMarkArea(cycleSegs, idx, ctx.effCycle, true, dates);
    let hlArea = [], dimArea = [];
    if (histPhase) {
      const ph = (phases || []).find(p => p.name === histPhase);
      if (ph) {
        const sIdx = dates.indexOf(ph.sCat), eIdx = dates.indexOf(ph.eCat);
        if (sIdx > 0) dimArea.push([{ xAxis: dates[0], itemStyle: { color: 'rgba(250,249,246,.62)' } }, { xAxis: dates[sIdx] }]);
        if (eIdx < dates.length - 1) dimArea.push([{ xAxis: dates[eIdx], itemStyle: { color: 'rgba(250,249,246,.62)' } }, { xAxis: dates[dates.length - 1] }]);
        hlArea = [[{ xAxis: ph.sCat, itemStyle: { color: 'rgba(168,135,91,.10)', borderColor: '#A8875B', borderWidth: 2 } }, { xAxis: ph.eCat }]];
      }
    }
    const evs = histEventScatter(idx, dates, closes, ctx);
    const narrow = el.clientWidth < 560;
    if (narrow) evs.forEach(e => { if (e.label) e.label.show = false; });
    const ch = charts['chart-history'] || echarts.init(el); charts['chart-history'] = ch;
    ch.setOption({
      textStyle: CHART_OPTS.textStyle, animation: false,
      grid: { left: 58, right: 18, top: 34, bottom: 38 },
      legend: { show: false },
      tooltip: { trigger: 'axis', axisPointer: { type: 'cross', lineStyle: { color: 'rgba(20,19,19,.35)', type: 'dashed' } }, backgroundColor: 'rgba(255,255,255,.98)', borderColor: C.line, textStyle: { color: C.ink, fontSize: 12 } },
      xAxis: { type: 'category', data: dates, axisLine: { lineStyle: { color: C.axis } }, axisTick: { show: false }, axisLabel: { color: C.muted, fontSize: 12, hideOverlap: true }, splitLine: { show: false } },
      yAxis: { type: 'value', scale: true, splitLine: { lineStyle: { color: C.grid } }, axisLabel: { color: C.muted, fontSize: 12, formatter: fmtAxis } },
      dataZoom: [{ type: 'inside' }, { type: 'slider', height: 12, bottom: 4, borderColor: 'transparent', fillerColor: 'rgba(168,135,91,.14)', handleStyle: { color: C.accent }, textStyle: { color: C.muted, fontSize: 11.5 } }],
      series: [
        { name: idx, type: 'line', data: dates.map((d, i) => closes[i] == null ? null : closes[i]), showSymbol: false, smooth: true, connectNulls: false, lineStyle: { color: SERIES[0], width: 2 }, itemStyle: { color: SERIES[0] } },
        { name: '__events__', type: 'scatter', data: evs, symbolSize: 9, z: 12, labelLayout: { hideOverlap: true }, emphasis: { itemStyle: { borderColor: '#fff', borderWidth: 2, shadowBlur: 8, shadowColor: 'rgba(0,0,0,.35)' }, label: { fontSize: 12, fontWeight: 'bold' } } },
        { name: '__dim__', type: 'line', data: [], showSymbol: false, silent: true, z: 18, lineStyle: { width: 0, opacity: 0 }, itemStyle: { opacity: 0 }, markArea: { silent: true, data: dimArea } },
        { name: '__hl__', type: 'line', data: [], showSymbol: false, silent: true, z: 16, lineStyle: { width: 0, opacity: 0 }, itemStyle: { opacity: 0 }, markArea: { silent: true, data: hlArea } },
        { name: '__anno__', type: 'line', data: [], showSymbol: false, silent: true, z: 1, lineStyle: { width: 0, opacity: 0 }, itemStyle: { opacity: 0 },
          markLine: { silent: true, symbol: 'none', data: [{ yAxis: lastC, lineStyle: { color: C.accentD, type: 'dashed', width: 1.5 }, label: { show: !narrow, formatter: '最新 ' + fmtNum(lastC, 0), position: 'end', distance: 6, color: C.accentD, fontSize: 11.5, fontWeight: 'bold' } }] },
          markArea: { silent: true, data: annoArea } },
      ],
    }, { notMerge: true });
    histChartData = { dates: dates };
    if (ctx.zoomRange) {
      const i0 = nearestIdx(dates, ctx.zoomRange[0]), i1 = nearestIdx(dates, ctx.zoomRange[1]);
      ch.dispatchAction({ type: 'dataZoom', startValue: dates[i0], endValue: dates[i1] });
    } else ch.dispatchAction({ type: 'dataZoom', start: 0, end: 100 });
  }

  function applyHistoryRange(r) {
    const ch = charts['chart-history'];
    if (!ch || !histChartData || !histChartData.dates.length) return;
    const dates = histChartData.dates;
    if (r === 'all') { ch.dispatchAction({ type: 'dataZoom', start: 0, end: 100 }); return; }
    const sd = rangeStartDate(dates, r);
    const i = nearestIdx(dates, sd);
    ch.dispatchAction({ type: 'dataZoom', startValue: dates[i], endValue: dates[dates.length - 1] });
  }

  function renderHistory() {
    const _hch = charts['chart-history'];
    if (_hch) { try { _hch.dispatchAction({ type: 'hideTip' }); } catch (e) { } }
    const idx = histIndex;
    const el = document.getElementById('chart-history');
    const card = el.closest('.chart-card');
    const key = idx;
    const ctx = cycleContext(key);
    const cycleSegs = W.index_cycles[key] || W.index_cycles['上证指数'];
    const isAll = histMode === 'all';
    const isKline = !isAll && histMode === 'kline';
    let kd = null, phases = [];
    if (!isAll) { const kk = W.kline[idx]; if (kk) { kd = aggregateOHLC(kk, histFreq); phases = buildPhaseList(idx, kd, ctx); } }
    const tb = histToolbar(card, el, phases);
    let st = card.querySelector('.chart-stats');
    if (!st) { st = document.createElement('div'); st.className = 'chart-stats'; card.insertBefore(st, el); }
    if (isAll) { el.style.height = ''; renderHistoryAllKline(el, card, tb, st); }
    else if (isKline && kd) {
      el.style.height = '';
      if (charts['chart-history']) charts['chart-history'].resize();  // 从「多指数对比」的固定高度切回主图高度
      renderHistoryKline(idx, el, card, tb, st, ctx, cycleSegs, kd, phases);
    } else {
      el.style.height = '';
      if (charts['chart-history']) charts['chart-history'].resize();
      renderHistoryLine(idx, el, card, tb, st, ctx, cycleSegs, kd, phases);
    }
    if (historyFirstRender) historyFirstRender = false;
    if (!histCycle) applyHistoryRange(SCOPE.range);
  }

  // ---------- 首页迷你走势：多资产切换 ----------
  let HERO_KEY = 'hs300';
  function renderHeroChart() {
    const el = document.getElementById('hero-chart');
    if (!el) return;
    const list = W.hero || [];
    if (!list.length) { el.innerHTML = '<div class="desc">走势数据未生成</div>'; return; }
    let a = list.filter(x => x.key === HERO_KEY)[0] || list[0];
    HERO_KEY = a.key;

    const box = document.getElementById('hero-chips');
    if (box) {
      box.innerHTML = list.map(x =>
        '<button data-hero="' + x.key + '"' + (x.key === a.key ? ' class="active"' : '') + '>' +
        x.name + '</button>').join('');
      box.querySelectorAll('button').forEach(function (b) {
        b.addEventListener('click', function () {
          HERO_KEY = b.dataset.hero;
          renderHeroChart();
        });
      });
    }

    const nm = document.getElementById('hero-name');
    if (nm) nm.textContent = a.name;
    const rg = document.getElementById('hero-range');
    if (rg) rg.textContent = a.dates[0].slice(0, 4) + ' — ' + a.dates[a.dates.length - 1].slice(0, 4);

    const ch = charts['hero-chart'] || echarts.init(el);
    charts['hero-chart'] = ch;
    const data = a.dates.map(function (d, i) { return [ts(d), a.vals[i]]; });
    ch.setOption({
      textStyle: CHART_OPTS.textStyle,
      animation: false,
      grid: { left: 0, right: 0, top: 6, bottom: 0 },
      tooltip: {
        trigger: 'axis', backgroundColor: '#fff', borderColor: '#E6E1D6', borderWidth: 1,
        textStyle: { color: '#141313', fontSize: 12 },
        formatter: function (ps) {
          if (!ps.length) return '';
          const d = new Date(ps[0].value[0]);
          return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '<br>' +
            a.name + ' ' + fmtNum(ps[0].value[1], 1);
        }
      },
      xAxis: { type: 'time', show: false },
      yAxis: { type: 'value', show: false, scale: true },
      series: [{
        type: 'line', data: data, showSymbol: false, smooth: true,
        lineStyle: { color: '#0E1F35', width: 2 },
        areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(14,31,53,.10)' }, { offset: 1, color: 'rgba(14,31,53,0)' }] } },
        markArea: {
          silent: true,
          data: (a.segs || []).map(function (sg) {
            return [{ xAxis: ts(sg[1]), itemStyle: { color: sg[0] === 'bull' ? 'rgba(184,147,92,.12)' : 'rgba(96,116,142,.11)' } },
                    { xAxis: ts(sg[2]) }];
          })
        }
      }]
    }, { notMerge: true });

    const lastV = a.vals[a.vals.length - 1];
    document.getElementById('hero-val').textContent = fmtNum(lastV, lastV >= 1000 ? 0 : 1);
    const chgEl = document.getElementById('hero-chg');
    const yr = a.dates[a.dates.length - 1].slice(0, 4);
    const bi = a.dates.findIndex(d => d >= yr + '-01-01');
    let ytd = null;
    if (bi >= 0 && a.vals[bi] != null && lastV != null) ytd = (lastV / a.vals[bi] - 1) * 100;
    if (ytd == null) { chgEl.textContent = '—'; chgEl.className = 'chg'; }
    else { chgEl.textContent = fmtSigned(ytd, 1, '%') + ' 今年以来'; chgEl.className = 'chg ' + (ytd >= 0 ? 'up' : 'down'); }
  }

  function shortCycleName(name) {
    return name.replace(/(\d{4})–(?:(\d{4})|(至今))/, function (m, a, b, c) {
      return a.slice(2) + '–' + (b ? b.slice(2) : c);
    });
  }
  function renderCycleTabs() {
    const box = document.getElementById('cycle-tabs');
    if (!box) return;
    box.innerHTML = '<button type="button" class="cycle-tab cycle-tab-home" data-id="all" title="首页总览 · 五轮牛熊统计与全指数对比">' +
      '<span class="ct-ic">' + cycleIcon('home') + '</span>' +
      '<span class="ct-full">首页总览</span><span class="ct-short">总览</span></button>' +
      W.cycles.map(cy =>
      '<button type="button" class="cycle-tab" data-id="' + cy.id + '" title="' + cy.name + ' · ' + cy.type + ' · ' + cy.theme + ' · 打开完整叙事">' +
      '<span class="ct-ic">' + cycleIcon(cy.id) + '</span>' +
      '<span class="ct-full">' + cy.name + '<em>' + cy.type + '</em></span>' +
      '<span class="ct-short">' + shortCycleName(cy.name) + '<em>' + cy.type + '</em></span></button>').join('');
    $$('.cycle-tab', box).forEach(tab => tab.addEventListener('click', function () {
      if (tab.dataset.id === 'all') {
        histCycle = null;
        detailCycleId = null;
        if (location.hash === '#history') go('history');
        else location.hash = 'history';
        return;
      }
      openCycle(tab.dataset.id);
    }));
    syncCycleTabs();
  }

  function syncCycleTabs() {
    const view = document.body.dataset.view;
    const active = view === 'cycle' ? detailCycleId : (view === 'history' ? 'all' : null);
    $$('.cycle-tab').forEach(t => t.classList.toggle('active', t.dataset.id === active));
    const lab = document.getElementById('cycle-scope-label');
    if (lab) lab.textContent = '牛熊周期';
    const box = document.getElementById('cycle-tabs');
    const at = box && box.querySelector('.cycle-tab.active');
    if (box && at && box.scrollWidth > box.clientWidth) {
      const br = box.getBoundingClientRect(), ar = at.getBoundingClientRect();
      if (ar.left < br.left - 1 || ar.right > br.right + 1) box.scrollBy({ left: ar.left - br.left - 8, behavior: 'smooth' });
    }
  }

  function revealHistoryChart() {
    const el = document.getElementById('chart-history');
    if (!el) return;
    const r = el.getBoundingClientRect();
    if (r.top < 70 || r.bottom > window.innerHeight) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }

  function selectCycle(id) {
    if (!W.cycles.some(c => c.id === id)) return;
    histCycle = id;
    if (histMode === 'all') histMode = 'kline';
    syncCycleTabs();
    ensureKline(function () {
      renderHistory();
      renderCycleOverview();
      setTimeout(revealHistoryChart, 80);
    });
  }

  function openCycle(id) {
    if (!W.cycles.some(c => c.id === id)) return;
    detailCycleId = id;
    histCycle = id;
    if (histMode === 'all') histMode = 'kline';
    if (location.hash === '#cycle/' + id) go('cycle');
    else location.hash = 'cycle/' + id;
  }

  // ==================================================================
  // 总览统计：全指数横向对比 + 行业 / 个股（仅 4 轮完整周期）
  // ==================================================================
  function caData() { return W.cycle_analysis || null; }
  function csData() { return (W.cycle_stats && W.cycle_stats.cycles) || {}; }
  function psData() { return (W.pullback_stats && W.pullback_stats.cycles) || {}; }
  function completedCycles() { return W.cycles.filter(c => c.id !== 'c24now'); }
  function meanNums(arr) {
    const v = arr.filter(x => typeof x === 'number' && !isNaN(x));
    return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
  }
  function csMean(key, phase, sub) {
    return meanNums(completedCycles().map(c => {
      const x = csData()[c.id] && csData()[c.id][phase] && csData()[c.id][phase][key];
      return x ? x[sub] : null;
    }));
  }
  function signedCls(v) { return isNil(v) ? '' : v > 0 ? 'up' : v < 0 ? 'down' : ''; }

  function coIndexCell(v, kind) {
    if (isNil(v)) return '<span class="na">—</span>';
    if (kind === 'days') return fmtNum(v, 0) + '<small>日</small>';
    const cls = kind === 'mdd' ? 'down' : kind === 'mrb' ? 'up' : signedCls(v);
    return '<span class="' + cls + '">' + fmtSigned(v, 1, '%') + '</span>';
  }

  function coPanel(title, meta, items, note) {
    return '<section class="co-panel">' +
      '<div class="co-sec-h"><h3>' + title + '</h3><span>' + meta + '</span></div>' +
      '<div class="co-kvs">' + items.map(it => {
        const v = it[1];
        const txt = isNil(v) ? '—' : it[2] === 'ratio' ? fmtNum(v, 0) + '%' : fmtSigned(v, 1, '%');
        const cls = it[2] === 'ratio' ? '' : signedCls(v);
        return '<div class="co-kv"><span>' + it[0] + '</span><b class="' + cls + '">' + txt + '</b></div>';
      }).join('') + '</div>' +
      '<div class="co-foot">' + note + '</div></section>';
  }

  function renderCycleOverview() {
    const box = document.getElementById('cycle-overview');
    const ca = caData();
    if (!box || !ca) return;
    const overall = ca.overall.indices || {};

    const head = '<tr><th>指标</th>' + INDEX_LIST.map(k => {
      const ov = overall[k] || {};
      const bits = [];
      if (ov.bull_n) bits.push(ov.bull_n + ' 牛');
      if (ov.bear_n) bits.push(ov.bear_n + ' 熊');
      return '<th>' + k + '<small>' + (bits.length ? bits.join(' / ') : '样本不足') + '</small></th>';
    }).join('') + '</tr>';

    const metrics = [
      ['牛市平均历时', 'bull_days', 'days'],
      ['牛市平均涨幅', 'bull_ret', 'ret'],
      ['牛市最大回撤', 'bull_mdd', 'mdd'],
      ['熊市平均历时', 'bear_days', 'days'],
      ['熊市平均跌幅', 'bear_ret', 'ret'],
      ['熊市最大反弹', 'bear_mrb', 'mrb'],
    ];
    const body = metrics.map(m => '<tr><th>' + m[0] + '</th>' +
      INDEX_LIST.map(k => '<td>' + coIndexCell((overall[k] || {})[m[1]], m[2]) + '</td>').join('') + '</tr>').join('');

    const indItems = [
      ['牛市平均涨幅', csMean('industry_stats', 'bull', 'avg'), 'pct'],
      ['牛市上涨占比', csMean('industry_stats', 'bull', 'up_ratio'), 'ratio'],
      ['熊市平均跌幅', csMean('industry_stats', 'bear', 'avg'), 'pct'],
      ['熊市上涨占比', csMean('industry_stats', 'bear', 'up_ratio'), 'ratio'],
    ];
    const stkItems = [
      ['牛市个股中位数', csMean('stock_stats', 'bull', 'median'), 'pct'],
      ['牛市上涨占比', csMean('stock_stats', 'bull', 'up_ratio'), 'ratio'],
      ['熊市个股中位数', csMean('stock_stats', 'bear', 'median'), 'pct'],
      ['熊市上涨占比', csMean('stock_stats', 'bear', 'up_ratio'), 'ratio'],
    ];

    box.innerHTML = '<div class="co-head"><div>' +
      '<div class="co-kicker">Cycle Statistics</div>' +
      '<div class="co-title">牛熊统计 <span>4 轮完整周期 · 全指数横向对比</span></div></div></div>' +
      '<section class="co-sec">' +
      '<div class="co-sec-h"><h3>指数</h3><span>按各自高点切分 · 第 5 轮不计入</span></div>' +
      '<div class="co-ix-wrap"><table class="co-ix"><thead>' + head + '</thead><tbody>' + body + '</tbody></table></div>' +
      '<div class="co-foot">— 表示该指数当时尚未成立或样本不足。</div></section>' +
      '<div class="co-subgrid">' +
      coPanel('行业', '申万一级等权 · 4 轮平均', indItems, '沿用指数阶段窗口。') +
      coPanel('个股', '全 A 复权 · 4 轮平均', stkItems, '牛市剔除阶段内新股；本地面板不含退市股。') +
      '</div>';
  }

  function refreshCycleOverview() {
    if (document.body.dataset.view !== 'history') return;
    renderCycleOverview();
  }

  // ==================================================================
  // 单轮叙事页：区间锁定 K 线 + 全指数对比 + 板块/个股 + 事件时间轴
  // ==================================================================
  function sliceKline(kd, start, end) {
    if (!kd || !kd.dates) return null;
    const out = { dates: [], open: [], high: [], low: [], close: [], vol: [], amt: [] };
    kd.dates.forEach((d, i) => {
      if (d < start || d > end) return;
      out.dates.push(d);
      out.open.push(kd.open[i]); out.high.push(kd.high[i]); out.low.push(kd.low[i]); out.close.push(kd.close[i]);
      out.vol.push(kd.vol ? kd.vol[i] : null); out.amt.push(kd.amt ? kd.amt[i] : null);
    });
    return out;
  }

  function cyclePageHtml(cy) {
    const i = W.cycles.indexOf(cy);
    const prev = W.cycles[i - 1], next = W.cycles[i + 1];
    const end = cy.end || W.asof;
    const nav = '<div class="cp-nav">' +
      (prev ? '<a href="#cycle/' + prev.id + '">← ' + prev.name + '</a>' : '<span class="disabled">已是首轮</span>') +
      (next ? '<a href="#cycle/' + next.id + '">' + next.name + ' →</a>' : '<span class="disabled">已是末轮</span>') + '</div>';
    return '<a class="cp-back" href="#history">← 返回五轮总览</a>' +
      '<div class="cp-head"><div>' +
      '<div class="overline">Cycle Narrative · 完整复盘</div>' +
      '<h1 class="cp-title">' + cy.name + ' <span>' + cy.type + (cy.theme ? ' · ' + cy.theme : '') + '</span></h1>' +
      '<div class="cp-meta">' + cy.start + ' → ' + end + ' · 完整区间走势</div></div>' + nav + '</div>' +
      '<div class="chart-card" style="margin-top:18px">' +
      '<div class="card-head"><h2>区间走势</h2><span class="cp-lock"><span class="dot"></span>' + cy.start + ' → ' + end + '</span></div>' +
      '<div class="chart-toolbar" id="cycle-toolbar"></div>' +
      '<div class="chart" id="chart-cycle"></div>' +
      '<div class="chart-empty" id="chart-cycle-empty" hidden></div></div>' +
      '<section class="cycle-stats">' +
      '<div class="cst-head"><div><div class="cs-kicker">Cycle Statistics · 阶段统计</div>' +
      '<h2 class="cst-title">' + cy.name + '</h2></div>' +
      '<div class="cst-sub">指数按各自最高点切分；板块、个股沿用同一阶段窗口。</div></div>' +
      '<div class="cst-tabs">' +
      '<button class="cst-tab' + (cycleTab === 'index' ? ' active' : '') + '" data-cstab="index">指数</button>' +
      '<button class="cst-tab' + (cycleTab === 'sector' ? ' active' : '') + '" data-cstab="sector">板块</button>' +
      '<button class="cst-tab' + (cycleTab === 'stock' ? ' active' : '') + '" data-cstab="stock">个股</button>' +
      '</div><div class="cst-body" id="cst-body"></div></section>' +
      '<div class="cycle-narrative"><div class="cn-head"><h2>完整叙事 · 两月分段与事件</h2><span>滚动左栏，右侧对照两月走势</span></div>' +
      '<div id="cycle-narrative"></div></div>';
  }

  function bindCyclePage(cy) {
    const page = document.getElementById('cycle-page');
    $$('[data-cstab]', page).forEach(b => b.addEventListener('click', function () {
      cycleTab = b.dataset.cstab;
      renderCycleStats(cy);
    }));
  }

  function renderCycleToolbar(cy) {
    const tb = document.getElementById('cycle-toolbar');
    if (!tb) return;
    const end = cy.end || W.asof;
    const modeLabel = cycleMode === 'line' ? '折线图' : '蜡烛图';
    const idxMenu = INDEX_LIST.map(k => tbItem('data-gidx="' + k + '"', k, k === SCOPE.index)).join('');
    const modeMenu = [['kline', '蜡烛图'], ['line', '折线图']]
      .map(m => tbItem('data-cym="' + m[0] + '"', m[1], cycleMode === m[0])).join('');
    const freqMenu = ['day', 'week', 'month'].map(k =>
      tbItem('data-cyf="' + k + '"', FREQ_LABEL[k] + '线', cycleFreq === k)).join('');
    const rangeMenu = tbItem('data-cyrange="all"', '本轮全区间', true, cy.start + ' → ' + end) +
      '<div class="tb-mf"><button type="button" data-cyreset>重置缩放</button></div>';
    const cyMenu = tbItem('data-cypick="all"', '五轮总览', false, '', cycleIcon('home')) +
      W.cycles.map(c => tbItem('data-cypick="' + c.id + '"',
        shortCycleName(c.name) + ' · ' + c.type, c.id === cy.id, '', cycleIcon(c.id))).join('');
    tb.innerHTML =
      tbDrop('idx', '指数', SCOPE.index, idxMenu, 'tb-scope') +
      '<span class="tb-div" aria-hidden="true"></span>' +
      tbDrop('mode', '图形', modeLabel, modeMenu) +
      tbDrop('freq', '周期', FREQ_LABEL[cycleFreq] + '线', freqMenu) +
      tbDrop('range', '区间', '本轮全区间', rangeMenu) +
      tbDrop('cycle', '牛熊', shortCycleName(cy.name), cyMenu, 'tb-cycle tb-right') +
      '<span class="toolbar-asof"><span class="dot"></span>数据截至 <b>' + W.asof + '</b></span>';
    bindTbMenus(tb);
    $$('[data-gidx]', tb).forEach(b => b.addEventListener('click', function () {
      closeTbMenus(); setScopeIndex(b.dataset.gidx);
    }));
    $$('[data-cym]', tb).forEach(b => b.addEventListener('click', function () {
      closeTbMenus(); cycleMode = b.dataset.cym; renderCycleToolbar(cy); renderCycleChart(cy);
    }));
    $$('[data-cyf]', tb).forEach(b => b.addEventListener('click', function () {
      closeTbMenus(); cycleFreq = b.dataset.cyf; renderCycleToolbar(cy); renderCycleChart(cy);
    }));
    $$('[data-cypick]', tb).forEach(b => b.addEventListener('click', function () {
      closeTbMenus();
      const id = b.dataset.cypick;
      if (id === 'all') { histCycle = null; location.hash = 'history'; }
      else if (id !== cy.id) location.hash = 'cycle/' + id;
    }));
    $$('[data-cyrange]', tb).forEach(b => b.addEventListener('click', function () { closeTbMenus(); }));
    const reset = tb.querySelector('[data-cyreset]');
    if (reset) reset.addEventListener('click', function () {
      closeTbMenus();
      renderCycleChart(cy);
    });
  }

  function renderCyclePage(id, keepTab) {
    const cy = W.cycles.find(c => c.id === id) || W.cycles[W.cycles.length - 1];
    if (!cy) return;
    detailCycleId = cy.id;
    const page = document.getElementById('cycle-page');
    if (!page) return;
    if (page.dataset.cy !== cy.id) {
      disposeChartsIn(page);
      page.dataset.cy = cy.id;
      page.innerHTML = cyclePageHtml(cy);
      bindCyclePage(cy);
      renderCycleDetail(cy);
    }
    renderCycleToolbar(cy);
    renderCycleChart(cy);
    renderCycleStats(cy);
    syncCycleTabs();
  }

  function drawCycleLine(cy, kd, idx) {
    const el = document.getElementById('chart-cycle');
    const ch = charts['chart-cycle'] || echarts.init(el); charts['chart-cycle'] = ch;
    const dates = kd.dates, closes = kd.close;
    const lastC = lastValid(closes);
    const end = cy.end || W.asof;
    const segs = [['bull', cy.start, cy.peak], ['bear', cy.peak, end]];
    const area = segs.map(sg => [
      { xAxis: sg[1], itemStyle: { color: sg[0] === 'bull' ? 'rgba(184,147,92,.12)' : 'rgba(96,116,142,.11)' } },
      { xAxis: sg[2] },
    ]);
    const hf = histFreq; histFreq = cycleFreq;
    const evs = histEventScatter(idx, dates, closes, { effCycle: cy.id });
    histFreq = hf;
    const narrow = el.clientWidth < 560;
    if (narrow) evs.forEach(e => { if (e.label) e.label.show = false; });
    const lastLabel = (cy.ongoing ? '最新 ' : '期末 ') + fmtNum(lastC, 2);
    ch.setOption({
      textStyle: CHART_OPTS.textStyle, animation: false,
      grid: { left: 58, right: 18, top: 30, bottom: 38 },
      legend: { show: false },
      tooltip: {
        trigger: 'axis', confine: true, axisPointer: { type: 'cross', lineStyle: { color: 'rgba(20,19,19,.35)', type: 'dashed' }, label: { backgroundColor: C.accent } },
        backgroundColor: 'rgba(255,255,255,.98)', borderColor: C.line, borderRadius: 6, textStyle: { color: C.ink, fontSize: 12 },
        formatter: function (ps) {
          if (!ps || !ps.length) return '';
          const i = ps[0].dataIndex;
          const prev = i > 0 ? closes[i - 1] : null;
          const chg = prev ? (closes[i] / prev - 1) * 100 : null;
          const evsHtml = ps.filter(p => p.seriesType === 'scatter')
            .map(p => '<div class="kt-r"><span>事件</span><b style="color:' + p.color + '">' + p.data.name + '</b></div>').join('');
          return '<b>' + ps[0].axisValue + '</b>' +
            '<div class="kt-r"><span>' + idx + '</span><b>' + fmtNum(closes[i], 2) + '</b></div>' +
            (chg == null ? '' : '<div class="kt-r"><span>较前值</span><b class="' + (chg >= 0 ? 'up' : 'down') + '">' + fmtSigned(chg, 2, '%') + '</b></div>') + evsHtml;
        }
      },
      xAxis: { type: 'category', data: dates, axisLine: { lineStyle: { color: C.axis } }, axisTick: { show: false }, axisLabel: { color: C.muted, fontSize: 12, hideOverlap: true }, splitLine: { show: false } },
      yAxis: { type: 'value', scale: true, splitLine: { lineStyle: { color: C.grid } }, axisLabel: { color: C.muted, fontSize: 12, formatter: fmtAxis } },
      dataZoom: [{ type: 'inside' }, { type: 'slider', height: 12, bottom: 4, borderColor: 'transparent', fillerColor: 'rgba(168,135,91,.14)', handleStyle: { color: C.accent }, textStyle: { color: C.muted, fontSize: 11.5 } }],
      series: [
        { name: idx, type: 'line', data: closes, showSymbol: false, connectNulls: false, lineStyle: { color: SERIES[0], width: 2 }, itemStyle: { color: SERIES[0] }, areaStyle: { color: 'rgba(14,31,53,.045)' } },
        { name: '__events__', type: 'scatter', data: evs, symbolSize: 9, z: 12, labelLayout: { hideOverlap: true }, emphasis: { itemStyle: { borderColor: '#fff', borderWidth: 2, shadowBlur: 8, shadowColor: 'rgba(0,0,0,.35)' }, label: { fontSize: 12, fontWeight: 'bold' } } },
        { name: '__anno__', type: 'line', data: [], showSymbol: false, silent: true, z: 1, lineStyle: { width: 0, opacity: 0 }, itemStyle: { opacity: 0 },
          markLine: { silent: true, symbol: 'none', data: [{ yAxis: lastC, lineStyle: { color: C.accentD, type: 'dashed', width: 1.5 }, label: { show: !narrow, formatter: lastLabel, position: 'end', distance: 6, color: C.accentD, fontSize: 11.5, fontWeight: 'bold' } }] },
          markArea: { silent: true, data: area } },
      ],
    }, { notMerge: true });
    ch.dispatchAction({ type: 'dataZoom', startValue: dates[0], endValue: dates[dates.length - 1] });
  }

  function renderCycleChart(cy) {
    const el = document.getElementById('chart-cycle');
    const empty = document.getElementById('chart-cycle-empty');
    if (!el) return;
    const kd0 = W.kline && W.kline[SCOPE.index];
    const end = cy.end || W.asof;
    const sliced = sliceKline(kd0, cy.start, end);
    if (!sliced || !sliced.dates.length) {
      if (charts['chart-cycle']) { try { charts['chart-cycle'].dispose(); } catch (e) { } delete charts['chart-cycle']; }
      el.innerHTML = '';
      el.style.display = 'none';
      if (empty) { empty.hidden = false; empty.textContent = SCOPE.index + ' 在本轮区间内尚无行情（该指数成立较晚）；切换主图左侧基准指数即可查看。'; }
      return;
    }
    el.style.display = '';
    if (empty) empty.hidden = true;
    const kd = aggregateOHLC(sliced, cycleFreq);
    if (cycleMode === 'line') { drawCycleLine(cy, kd, SCOPE.index); return; }
    const segs = [['bull', cy.start, cy.peak], ['bear', cy.peak, end]];
    const hp = histPhase, hf = histFreq;
    histPhase = null; histFreq = cycleFreq;
    drawKlineGrid('chart-cycle', SCOPE.index, kd, { effCycle: cy.id }, segs, null, []);
    histPhase = hp; histFreq = hf;
  }

  function renderCycleStats(cy) {
    const page = document.getElementById('cycle-page');
    if (!page) return;
    $$('[data-cstab]', page).forEach(x => x.classList.toggle('active', x.dataset.cstab === cycleTab));
    const body = document.getElementById('cst-body');
    if (!body) return;
    disposeChartsIn(body);
    if (cycleTab === 'index') body.innerHTML = indexStatsHtml(cy);
    else if (cycleTab === 'sector') body.innerHTML = sectorStatsHtml(cy);
    else body.innerHTML = stockStatsHtml(cy);
    bindEpisodeCharts(body);
  }

  function phaseValue(v, kind) {
    if (!v) return '<span class="ix-v na">—</span>';
    if (kind === 'days') return '<span class="ix-v">' + fmtNum(v.months / 12, 1) + '<small>年</small></span>';
    if (kind === 'ret') return '<span class="ix-v ' + (v.ret > 0 ? 'up' : 'down') + '">' + fmtSigned(v.ret, 1, '%') + '</span>';
    if (kind === 'mdd') return '<span class="ix-v down">' + fmtSigned(v.mdd, 1, '%') + '</span>';
    if (kind === 'mrb') return '<span class="ix-v up">' + fmtSigned(v.mrb, 1, '%') + '</span>';
    return '<span class="ix-v na">—</span>';
  }

  // 回调 / 反弹小图：右栏指数走势，金色区间标出该次波段；左侧多带 3 个月看趋势
  function episodeChartPanel(chartId, kind, iname) {
    return '<div class="ep-chart-side" data-mode="line"><div class="ep-chart-top">' +
      '<span class="ep-chart-k">' + (kind === 'bull' ? '回调' : '反弹') + ' · ' + iname + '</span>' +
      '<span class="ep-chart-modes" role="group" aria-label="图表类型">' +
      '<button type="button" data-epmode="line" class="active" aria-pressed="true">走势</button>' +
      '<button type="button" data-epmode="kline" aria-pressed="false">K线</button></span>' +
      '<span class="ep-chart-v">—</span></div>' +
      '<div class="ep-chart-d">—</div>' +
      '<div class="ep-chart-plot" id="' + chartId + '"></div></div>';
  }

  function episodeChartHeader(root, kind, iname, start, end, pct, days) {
    const side = root && root.querySelector('.ep-chart-side');
    if (!side) return;
    const k = side.querySelector('.ep-chart-k');
    const v = side.querySelector('.ep-chart-v');
    const d = side.querySelector('.ep-chart-d');
    if (k) k.textContent = (kind === 'bull' ? '回调' : '反弹') + ' · ' + iname;
    if (v) {
      v.textContent = fmtSigned(pct, 1, '%');
      v.className = 'ep-chart-v ' + (pct >= 0 ? 'up' : 'down');
    }
    if (d) d.textContent = start + ' → ' + end + ' · ' + days + ' 日 · 含前 3 个月';
  }

  function episodeChartEmpty(el, msg) {
    if (charts[el.id]) { try { charts[el.id].dispose(); } catch (e) { } delete charts[el.id]; }
    el.innerHTML = '<div class="ep-chart-empty">' + msg + '</div>';
  }

  function shiftMonths(dateStr, n) {
    const p = String(dateStr).split('-').map(Number);
    if (p.length !== 3 || p.some(isNaN)) return dateStr;
    const d = new Date(p[0], p[1] - 1 + n, p[2]);
    const p2 = v => String(v).padStart(2, '0');
    return d.getFullYear() + '-' + p2(d.getMonth() + 1) + '-' + p2(d.getDate());
  }

  // 区间较长时把日K合成周K，否则几百根细柱在窄栏里看不清趋势
  function toWeeklyRows(rows) {
    const out = [];
    let cur = null;
    const weekKey = function (ds) {
      const d = new Date(ds + 'T00:00:00');
      d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
      const p2 = v => String(v).padStart(2, '0');
      return d.getFullYear() + '-' + p2(d.getMonth() + 1) + '-' + p2(d.getDate());
    };
    rows.forEach(r => {
      const k = weekKey(r.d);
      if (!cur || cur.k !== k) {
        if (cur) out.push(cur);
        cur = {
          k: k, d: r.d, o: r.o, h: r.h, l: r.l, c: r.c,
          amt: r.amt, prev: out.length ? out[out.length - 1].c : r.prev,
        };
      } else {
        cur.d = r.d;
        cur.h = Math.max(cur.h, r.h);
        cur.l = Math.min(cur.l, r.l);
        cur.c = r.c;
        if (r.amt != null) cur.amt = (cur.amt || 0) + r.amt;
      }
    });
    if (cur) out.push(cur);
    return out;
  }

  function drawEpisodeMini(chartId, iname, start, end, kind, mode) {
    const el = document.getElementById(chartId);
    if (!el) return;
    if (el.clientWidth < 40) return;
    const kd = W.kline && W.kline[iname];
    if (!kd || !kd.dates || !kd.dates.length) return episodeChartEmpty(el, iname + ' 暂无行情');
    const isK = mode === 'kline';
    const dates = kd.dates;
    const from = shiftMonths(start, -3);
    let a = -1, z = -1;
    for (let i = 0; i < dates.length; i++) if (dates[i] >= from) { a = i; break; }
    if (a < 0) return episodeChartEmpty(el, iname + ' 自 ' + dates[0] + ' 起有行情');
    for (let i = dates.length - 1; i >= 0; i--) if (dates[i] <= end) { z = i; break; }
    if (z < a) return episodeChartEmpty(el, '该区间暂无行情');
    const i1 = Math.min(dates.length - 1, z + 14);
    const all = [];
    let prev = null;
    for (let i = a; i <= i1; i++) {
      const c = kd.close[i];
      if (c == null) continue;
      all.push({
        d: dates[i], o: kd.open[i], h: kd.high[i], l: kd.low[i], c: c,
        amt: kd.amt ? kd.amt[i] : null, prev: prev,
      });
      prev = c;
    }
    let rows = isK ? all.filter(r => !isNil(r.o) && !isNil(r.h) && !isNil(r.l)) : all;
    let weekly = false;
    if (isK && rows.length > 80) { rows = toWeeklyRows(rows); weekly = true; }
    if (!rows.length) return episodeChartEmpty(el, isK ? '该区间暂无 K 线' : '该区间暂无行情');
    if (isK) {
      const dt = el.closest('.ep-chart-side') && el.closest('.ep-chart-side').querySelector('.ep-chart-d');
      if (dt) dt.textContent += weekly ? ' · 周K' : ' · 日K';
    }
    let bi = -1, zi = -1;
    for (let i = 0; i < rows.length; i++) {
      if (bi < 0 && rows[i].d >= start) bi = i;
      if (rows[i].d <= end) zi = i;
    }
    const band = (bi >= 0 && zi >= bi)
      ? [[{ xAxis: rows[bi].d, itemStyle: { color: 'rgba(184,147,92,.16)' } }, { xAxis: rows[zi].d }]]
      : [];
    const xs = rows.map(r => r.d);
    const baseRow = rows.find(r => r.d >= start) || rows[0];
    const lineBase = baseRow.c;
    const narrow = el.clientWidth < 360;
    const ch = charts[chartId] || echarts.init(el);
    charts[chartId] = ch;
    const markArea = {
      silent: true,
      label: { show: !narrow, color: C.accentD, fontSize: 12, position: 'insideTop', formatter: kind === 'bull' ? '回调' : '反弹' },
      data: band,
    };
    const opt = {
      textStyle: CHART_OPTS.textStyle,
      animation: false,
      grid: { left: 50, right: 14, top: 14, bottom: 26 },
      tooltip: {
        trigger: 'axis', confine: true,
        axisPointer: { type: isK ? 'cross' : 'line', lineStyle: { color: 'rgba(20,19,19,.3)', type: 'dashed' } },
        backgroundColor: 'rgba(255,255,255,.98)', borderColor: C.line, borderRadius: 4,
        textStyle: { color: C.ink, fontSize: 12.5 },
        formatter: function (ps) {
          if (!ps || !ps.length) return '';
          const p = ps[0];
          const r = rows[p.dataIndex];
          if (!r) return '';
          if (isK) return klineTipHtml(r.d + (weekly ? '（周）' : ''), r.o, r.h, r.l, r.c, r.prev, r.amt);
          return '<b>' + r.d + '</b><br/>' + iname + ' ' + fmtNum(r.c, 2) +
            '　<span style="color:' + (p.value >= 0 ? C.up : C.down) + ';font-weight:700">' +
            fmtSigned(p.value, 2, '%') + '</span>';
        },
      },
      xAxis: {
        type: 'category', data: xs, boundaryGap: isK,
        axisLine: { lineStyle: { color: C.axis } }, axisTick: { show: false },
        axisLabel: { color: C.muted, fontSize: 12, hideOverlap: true, formatter: v => String(v).slice(5) },
        splitLine: { show: false },
      },
      yAxis: isK ? {
        type: 'value', scale: true, splitNumber: 4,
        axisLine: { show: false }, axisTick: { show: false },
        splitLine: { lineStyle: { color: C.grid } },
        axisLabel: { color: C.muted, fontSize: 12, formatter: v => fmtNum(v, 0) },
        axisPointer: { label: { formatter: p => fmtNum(p.value, 0) } },
      } : {
        type: 'value', scale: true, splitNumber: 4,
        axisLine: { show: false }, axisTick: { show: false },
        splitLine: { lineStyle: { color: C.grid } },
        axisLabel: { color: C.muted, fontSize: 12, formatter: v => (v > 0 ? '+' : '') + nf(Math.abs(v) >= 10 ? 0 : 1).format(v) + '%' },
        axisPointer: { label: { formatter: p => fmtSigned(p.value, 1, '%') } },
      },
      series: [isK ? {
        name: iname, type: 'candlestick', data: rows.map(r => [r.o, r.c, r.l, r.h]),
        barMaxWidth: 7,
        itemStyle: { color: C.up, color0: C.down, borderColor: C.up, borderColor0: C.down },
        markArea: markArea,
      } : {
        name: iname, type: 'line', data: rows.map(r => (r.c / lineBase - 1) * 100), showSymbol: false,
        lineStyle: { color: '#0E1F35', width: 2 },
        areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(14,31,53,.10)' }, { offset: 1, color: 'rgba(14,31,53,0)' }] } },
        markLine: { silent: true, symbol: 'none', label: { show: false }, data: [{ yAxis: 0, lineStyle: { color: 'rgba(20,19,19,.25)', type: 'dashed', width: 1 } }] },
        markArea: markArea,
      }],
    };
    if (isK) opt.dataZoom = [{ type: 'inside', xAxisIndex: 0, filterMode: 'none' }];
    ch.setOption(opt, { notMerge: true });
    ch.resize();
  }

  function renderEpisodeSide(root) {
    if (!root) return;
    const side = root.querySelector('.ep-chart-side');
    const plot = root.querySelector('.ep-chart-plot');
    if (!side || !plot) return;
    const mode = side.dataset.mode === 'kline' ? 'kline' : 'line';
    const row = root.querySelector('.ep-pick.sel') || root.querySelector('.ep-pick');
    const src = row ? row.dataset : root.dataset;
    const iname = row ? src.iname : src.proxy;
    if (!src.start || !iname) return;
    episodeChartHeader(root, src.kind, iname, src.start, src.end, +src.pct, +src.days);
    drawEpisodeMini(plot.id, iname, src.start, src.end, src.kind, mode);
  }

  function selectEpisode(details, row) {
    $$('.ep-pick', details).forEach(x => x.classList.toggle('sel', x === row));
    renderEpisodeSide(details);
  }

  function bindEpisodeCharts(root) {
    $$('.ep-chart-modes button', root).forEach(btn => {
      btn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        const side = btn.closest('.ep-chart-side');
        if (!side) return;
        side.dataset.mode = btn.dataset.epmode;
        $$('.ep-chart-modes button', side).forEach(x => {
          const on = x === btn;
          x.classList.toggle('active', on);
          x.setAttribute('aria-pressed', on ? 'true' : 'false');
        });
        const holder = btn.closest('details');
        if (holder) renderEpisodeSide(holder);
      });
    });
    $$('details.ix-details', root).forEach(d => {
      const open = function () {
        if (!d.open) return;
        const first = d.querySelector('.ep-pick');
        if (first) selectEpisode(d, first);
      };
      d.addEventListener('toggle', function () { if (d.open) requestAnimationFrame(open); });
      $$('.ep-pick', d).forEach(row => {
        row.addEventListener('click', function () { selectEpisode(d, row); });
        row.addEventListener('keydown', function (e) {
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectEpisode(d, row); }
        });
      });
      if (d.open) requestAnimationFrame(open);
    });
    $$('details.ep-block', root).forEach(d => {
      const open = function () {
        if (!d.open) return;
        if (!d.querySelector('.ep-chart-plot')) return;
        renderEpisodeSide(d);
      };
      d.addEventListener('toggle', function () { if (d.open) requestAnimationFrame(open); });
      if (d.open) requestAnimationFrame(open);
    });
  }

  function epLine(e, kind, iname) {
    const d1 = kind === 'bear' ? e.trough : e.peak;
    const d2 = kind === 'bear' ? e.peak : e.trough;
    const pct = e.pct;
    return '<div class="ep-li ep-pick" role="button" tabindex="0" data-iname="' + iname + '" data-kind="' + kind + '" data-start="' + d1 + '" data-end="' + d2 + '" data-pct="' + pct + '" data-days="' + e.days + '">' +
      '<span class="d">' + d1 + ' → ' + d2 + '</span>' +
      '<span class="p ' + (pct > 0 ? 'up' : 'down') + '">' + fmtSigned(pct, 1, '%') + '</span>' +
      '<span class="n">' + e.days + ' 日</span>' +
      '<span class="t">' + (kind === 'bull' ? '主升浪第 ' : '主跌浪第 ') + (e.from_start == null ? '—' : e.from_start) + ' 日后</span></div>';
  }

  function indexSummary(ca, c) {
    const bulls = [], bears = [];
    ca.indices.forEach(n => {
      const b = c.bull[n], s = c.bear[n];
      if (b && b.ret != null) bulls.push({ n: n, v: b.ret, mdd: b.mdd });
      if (s && s.ret != null) bears.push({ n: n, v: s.ret, mrb: s.mrb });
    });
    if (bulls.length < 3 || bears.length < 3) return '';
    const byRet = bulls.slice().sort((a, b) => b.v - a.v);
    const lead = byRet[0];
    const byDd = bulls.filter(x => x.mdd != null).sort((a, b) => a.mdd - b.mdd);
    const leadDdRank = byDd.findIndex(x => x.n === lead.n) + 1;

    const byDrop = bears.slice().sort((a, b) => a.v - b.v);
    const worst = byDrop[0];
    const byReb = bears.filter(x => x.mrb != null).sort((a, b) => b.mrb - a.mrb);
    const worstRebRank = byReb.findIndex(x => x.n === worst.n) + 1;

    let t1 = '牛市领涨 <b>' + lead.n + '</b>（' + fmtSigned(lead.v, 1, '%') + '）';
    t1 += leadDdRank <= 3
      ? '，回调时也跌得最凶（最大回撤第 ' + leadDdRank + '/' + byDd.length + '）—— 高 beta 的双刃剑。'
      : '，回调时相对抗跌（最大回撤第 ' + leadDdRank + '/' + byDd.length + '）—— 主线韧性更强。';
    let t2 = '熊市跌得最深的是 <b>' + worst.n + '</b>（' + fmtSigned(worst.v, 1, '%') + '）';
    t2 += worstRebRank <= 3
      ? '，反弹时也最能涨（最大反弹第 ' + worstRebRank + '/' + byReb.length + '）—— 超跌反弹成立。'
      : '，但反弹并不领先（最大反弹第 ' + worstRebRank + '/' + byReb.length + '）—— 跌得多不等于弹得快。';
    return '<div class="cst-sec-note" style="margin-top:10px;color:var(--ink-2)">' + t1 + t2 + '</div>';
  }

  function indexStatsHtml(cy) {
    const ca = caData();
    const c = ca && ca.cycles && ca.cycles[cy.id];
    if (!c) return '<div class="avail">指数对比数据未加载。</div>';
    let head = '<div class="ix-tr head group"><span>指数</span><span class="bull" style="grid-column:span 3">牛市</span><span class="bear" style="grid-column:span 3">熊市</span></div>' +
      '<div class="ix-tr head"><span></span><span>历时</span><span>涨幅</span><span>最大回撤</span>' +
      '<span>历时</span><span>跌幅</span><span>最大反弹</span></div>';
    let rows = '', details = '';
    ca.indices.forEach(n => {
      const b = c.bull[n], s = c.bear[n];
      rows += '<div class="ix-tr"><span class="ix-name">' + n + (b || s ? '' : '<em>未成立</em>') + '</span>' +
        phaseValue(b, 'days') + phaseValue(b, 'ret') + phaseValue(b, 'mdd') +
        phaseValue(s, 'days') + phaseValue(s, 'ret') + phaseValue(s, 'mrb') + '</div>';
      const bEps = (b && b.episodes) || [], sEps = (s && s.episodes) || [];
      const bTxt = b ? (bEps.length ? '牛市 ' + bEps.length + ' 次回调' : '牛市无 ≥10% 回调') : '牛市未成立';
      const sTxt = s ? (sEps.length ? '熊市 ' + sEps.length + ' 次反弹' : '熊市无 ≥10% 反弹') : '熊市未成立';
      const hasEps = bEps.length > 0 || sEps.length > 0;
      const chartId = 'ep-chart-' + (++epChartSeq);
      details += '<details class="ix-details" data-iname="' + n + '"><summary><b>' + n + '</b><span>' + bTxt + ' · ' + sTxt + '</span><em>展开每次回撤 / 反弹</em></summary>' +
        '<div class="ix-d-body' + (hasEps ? '' : ' no-chart') + '">' +
        '<div class="ix-ep-lists"><div class="ep-list"><h4 class="bull">牛市 · 回撤 ≥10%</h4>' +
        (b ? (bEps.length ? bEps.map(e => epLine(e, 'bull', n)).join('') : '<div class="ep-li"><span class="t">无 ≥10% 的回撤</span></div>') : '<div class="ep-li"><span class="t">该指数此时尚未成立，阶段留空</span></div>') + '</div>' +
        '<div class="ep-list"><h4 class="bear">熊市 · 反弹 ≥10%</h4>' +
        (s ? (sEps.length ? sEps.map(e => epLine(e, 'bear', n)).join('') : '<div class="ep-li"><span class="t">无 ≥10% 的反弹</span></div>') : '<div class="ep-li"><span class="t">该指数此时尚未成立，阶段留空</span></div>') + '</div></div>' +
        (hasEps ? episodeChartPanel(chartId, 'bull', n) : '') +
        '</div></details>';
    });
    return '<div class="cst-sec"><div class="cst-sec-h"><h3>全指数 · 牛市 / 熊市对比</h3><span>按各指数自身高点切分 · 涨跌幅与历时（年）</span></div>' +
      '<div class="ix-wrap"><div class="ix-table">' + head + rows + '</div></div>' +
      '<div class="cst-sec-note">牛市涨幅 = 起点 → 区间最高；熊市跌幅 = 区间最高 → 终点。最大回撤/反弹取阶段极值；≥10% 波段次数与明细见下方展开；指数成立晚于阶段起点时留空。</div>' +
      indexSummary(ca, c) +
      '<div style="margin-top:10px">' + details + '</div></div>';
  }

  function miniIndustryTable(items) {
    return '<div class="cs-table"><div class="cs-row ind head"><span>#</span><span>行业</span><span>样本</span><span>涨跌幅</span></div>' + csRows(items, 'industry') + '</div>';
  }
  function miniStockTable(items) {
    return '<div class="cs-table"><div class="cs-row head"><span>#</span><span>个股</span><span>涨跌幅</span></div>' + csRows(items, 'stock') + '</div>';
  }

  function episodeTagHtml(x) {
    return (x.leader ? '<span class="tag leader" title="本轮牛市全阶段涨幅前10">主涨</span>' : '') +
      (x.worst ? '<span class="tag worst" title="本轮熊市全阶段跌幅前10">超跌</span>' : '');
  }

  function episodeHtml(e, kind, mode, proxy) {
    const items = mode === 'sector' ? e.industries : e.stocks;
    const leaderN = items.filter(x => x.leader).length;
    const worstN = items.filter(x => x.worst).length;
    const short = kind === 'bull' ? '主涨 ' + leaderN + '/10' : '超跌 ' + worstN + '/10';
    let read;
    if (kind === 'bull') {
      read = '回调跌幅前10中，<b>' + leaderN + ' 个</b>是本轮牛市主涨行业/个股。' +
        (leaderN >= 5 ? '主涨板块同步回调，更像主线内洗盘；回调结束时优先回到这些方向。' : '回调以非主线为主，主线相对抗跌；若主线未跌，反弹时通常先修复。');
    } else {
      read = '反弹涨幅前10中，<b>' + worstN + ' 个</b>是熊市跌幅前10。' +
        (worstN >= 5 ? '超跌反弹特征明显，参与应以跌得最深、弹性最大的方向为主。' : '反弹由新主线主导，而非超跌修复；参与应跟随领涨主线，不宜单纯抄跌得最多的板块。');
    }
    let tbl;
    if (mode === 'sector') {
      tbl = '<div class="ep-tbl-h"><span>#</span><span>行业</span><span>样本</span><span>涨跌幅</span></div>' +
        items.map((x, i) => '<div class="ep-row"><span class="r">' + (i + 1) + '</span>' +
          '<span class="nm">' + x.name + episodeTagHtml(x) + '</span>' +
          '<span class="n">' + x.n + ' 只</span>' +
          '<span class="v ' + (x.ret >= 0 ? 'up' : 'down') + '">' + fmtSigned(x.ret, 1, '%') + '</span></div>').join('');
    } else {
      tbl = '<div class="ep-tbl-h"><span>#</span><span>个股</span><span>行业</span><span>涨跌幅</span></div>' +
        items.map((x, i) => '<div class="ep-row"><span class="r">' + (i + 1) + '</span>' +
          '<span class="nm">' + x.name + '<em>' + x.code + '</em>' + episodeTagHtml(x) + '</span>' +
          '<span class="n">' + (x.industry || '—') + '</span>' +
          '<span class="v ' + (x.ret >= 0 ? 'up' : 'down') + '">' + fmtSigned(x.ret, 1, '%') + '</span></div>').join('');
    }
    const chartId = 'ep-chart-' + (++epChartSeq);
    return '<details class="ep-block" data-kind="' + kind + '" data-proxy="' + proxy + '" data-start="' + e.start + '" data-end="' + e.end + '" data-pct="' + e.pct + '" data-days="' + e.days + '"><summary>' +
      '<span class="ed">' + e.start + ' → ' + e.end + '</span>' +
      '<span class="ep ' + (e.pct >= 0 ? 'up' : 'down') + '">' + fmtSigned(e.pct, 1, '%') + '</span>' +
      '<span class="en">' + e.days + ' 日</span>' +
      '<span class="er">' + short + '</span></summary>' +
      '<div class="ep-body"><div class="ep-main"><div class="ep-read">' + read + '</div>' + tbl +
      '<div class="cst-sec-note">窗口内 ' + fmtNum(e.n_stocks, 0) + ' 只个股，涨跌幅均值 ' + fmtSigned(e.avg, 1, '%') + '，上涨占比 ' + fmtNum(e.up_ratio, 1) + '%。</div></div>' +
      episodeChartPanel(chartId, kind, proxy) + '</div></details>';
  }

  function episodesSection(cy, phase, mode, title) {
    const ps = psData()[cy.id];
    if (!ps || ps.unavailable) {
      return '<div class="cst-sec"><div class="cst-sec-h"><h3>' + title + '</h3><span>本地数据不可用</span></div>' +
        '<div class="avail"><b>该轮逐段回调/反弹的行业、个股 Top10 暂不可得。</b>上方全阶段 Top10 仍是起止端点统计；逐段明细需要全历史个股日线。本地全市场面板自 2016-01-04 起，要补齐 2005–2015 两轮，需 Tushare 全历史日线（daily + adj_factor）与历史行业成员。指数层面的每次回撤/反弹已在「指数」页签完整给出。</div></div>';
    }
    const p = ps[phase];
    if (!p || !p.episodes || !p.episodes.length) {
      return '<div class="cst-sec"><div class="cst-sec-h"><h3>' + title + '</h3><span>' + (p && p.proxy ? p.proxy : '中证500') + ' · 无 ≥10% 波段</span></div>' +
        '<div class="avail">本轮该代理指数未出现 ≥10% 的' + (phase === 'bull' ? '回调' : '反弹') + '，因此没有可统计的行业 Top10。可切换到其他指数查看其波段。</div></div>';
    }
    return '<div class="cst-sec"><div class="cst-sec-h"><h3>' + title + '</h3><span>' + p.episodes.length + ' 次 · 窗口按 ' + p.proxy + ' ≥10% 收盘' + (phase === 'bull' ? '回撤' : '反弹') + '</span></div>' +
      p.episodes.map(e => episodeHtml(e, phase, mode, p.proxy)).join('') +
      '<div class="cst-sec-note">标记「主涨」= 该行业/个股在本轮牛市全阶段涨幅前10；「超跌」= 在本轮熊市全阶段跌幅前10。行业为本地 110 个细分行业等权，样本少于 5 只不排名。' +
      (cy.id === 'c24now' ? ' 逐段行业/个股明细基于本地日线，截至 2026-08-28；最近一次反弹窗口已完整覆盖。' : '') + '</div></div>';
  }

  function sectorStatsHtml(cy) {
    const cs = csData()[cy.id];
    if (!cs) return '<div class="avail">板块统计未加载。</div>';
    const bearWord = cy.id === 'c24now' ? '调整' : '熊市';
    return '<div class="cst-sec"><div class="cst-sec-h"><h3>全阶段 · 行业 Top10</h3><span>名义区间 · 申万一级等权 · 剔除 ST/退市</span></div>' +
      '<div class="cs-lists two">' +
      '<div class="cs-list"><div class="cs-list-h"><h3>牛市 · 行业涨幅 Top10</h3><span>阶段起点 → 终点</span></div>' + miniIndustryTable(cs.bull.industries) + '</div>' +
      '<div class="cs-list"><div class="cs-list-h"><h3>' + bearWord + ' · 行业跌幅 Top10</h3><span>阶段起点 → 终点</span></div>' + miniIndustryTable(cs.bear.industries_bottom) + '</div>' +
      '</div></div>' +
      episodesSection(cy, 'bull', 'sector', '牛市主要回调 · 跌幅前10行业') +
      episodesSection(cy, 'bear', 'sector', bearWord + '主要反弹 · 涨幅前10行业');
  }

  function stockStatsHtml(cy) {
    const cs = csData()[cy.id];
    if (!cs) return '<div class="avail">个股统计未加载。</div>';
    const bearWord = cy.id === 'c24now' ? '调整' : '熊市';
    return '<div class="cst-sec"><div class="cst-sec-h"><h3>全阶段 · 个股 Top10</h3><span>复权 · 剔除 ST/退市与阶段内新股</span></div>' +
      '<div class="cs-lists two">' +
      '<div class="cs-list"><div class="cs-list-h"><h3>牛市 · 个股涨幅 Top10</h3><span>阶段起点 → 终点</span></div>' + miniStockTable(cs.bull.stocks) + '</div>' +
      '<div class="cs-list"><div class="cs-list-h"><h3>' + bearWord + ' · 个股跌幅 Top10</h3><span>阶段起点 → 终点</span></div>' + miniStockTable(cs.bear.stocks_bottom) + '</div>' +
      '</div></div>' +
      '<div class="cst-sec-note" style="margin-top:10px">口径：沪深A股复权价；剔除当前名称含 ST/*ST/退 的股票；牛市阶段剔除起点后上市新股；仅统计窗口起止均有行情的个股。逐段明细的本地面板不含已退市股票，跌幅榜存在幸存者偏差。</div>';
  }

  // ---------- 牛熊复盘：按自然两个月分段（无事件的月份也保留） ----------
  const pad2 = n => String(n).padStart(2, '0');
  function twoMonthBuckets(cy, evThis) {
    const end = cy.end || W.asof;
    const out = [];
    let y = +cy.start.slice(0, 4);
    let bm = Math.floor((+cy.start.slice(5, 7) - 1) / 2) * 2 + 1;
    const ey = +end.slice(0, 4), em = +end.slice(5, 7);
    while (y < ey || (y === ey && bm <= em)) {
      const emo = bm + 1;
      const start = y + '-' + pad2(bm) + '-01';
      const fin = y + '-' + pad2(emo) + '-' + pad2(new Date(y, emo, 0).getDate());
      out.push({
        key: y + '-' + pad2(bm),
        label: y + '.' + pad2(bm) + '–' + pad2(emo),
        start, end: fin,
        events: evThis.filter(e => e.date >= start && e.date <= fin),
      });
      bm += 2; if (bm > 12) { bm = 1; y++; }
    }
    return out;
  }
  function lowerBound(dates, ds) {
    let lo = 0, hi = dates.length;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (dates[mid] < ds) lo = mid + 1; else hi = mid; }
    return lo;
  }
  function rowsBetween(kd, start, end) {
    const out = [];
    if (!kd || !kd.dates) return out;
    for (let i = lowerBound(kd.dates, start); i < kd.dates.length && kd.dates[i] <= end; i++) {
      if (kd.close[i] != null) out.push({ d: kd.dates[i], o: kd.open[i], h: kd.high[i], l: kd.low[i], c: kd.close[i], amt: kd.amt ? kd.amt[i] : null });
    }
    return out;
  }
  function nearestRow(rows, ds) {
    if (!rows.length) return null;
    let lo = 0, hi = rows.length - 1;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (rows[mid].d < ds) lo = mid + 1; else hi = mid; }
    if (lo > 0) {
      const a = rows[lo - 1], b = rows[lo];
      return Math.abs(ts(b.d) - ts(ds)) < Math.abs(ts(a.d) - ts(ds)) ? b : a;
    }
    return rows[lo];
  }
  // 窄屏内嵌走势：累计涨跌幅形状 + 事件刻度，纯 SVG，不增加图表实例
  function sparkSvg(rows, events) {
    if (rows.length < 2) return '';
    const Wd = 600, H = 58, P = 4;
    const base = rows[0].c;
    if (!base) return '';
    const vals = rows.map(r => (r.c / base - 1) * 100);
    let min = Math.min.apply(null, vals), max = Math.max.apply(null, vals);
    if (min === max) { min -= 1; max += 1; }
    const X = i => P + i * (Wd - 2 * P) / (rows.length - 1);
    const Y = v => H - P - (v - min) / (max - min) * (H - 2 * P);
    const pts = rows.map((r, i) => (i ? 'L' : 'M') + X(i).toFixed(1) + ' ' + Y(vals[i]).toFixed(1)).join(' ');
    const area = pts + ' L ' + X(rows.length - 1).toFixed(1) + ' ' + (H - P) + ' L ' + X(0).toFixed(1) + ' ' + (H - P) + ' Z';
    let zero = '';
    if (min < 0 && max > 0) {
      const zy = Y(0).toFixed(1);
      zero = '<line x1="' + P + '" y1="' + zy + '" x2="' + (Wd - P) + '" y2="' + zy + '" stroke="rgba(20,19,19,.18)" stroke-width="1" stroke-dasharray="2 3" vector-effect="non-scaling-stroke"/>';
    }
    const ticks = events.map(e => {
      const row = nearestRow(rows, e.date); if (!row) return '';
      const i = rows.indexOf(row);
      const x = X(i).toFixed(1), y = Y(vals[i]);
      return '<line x1="' + x + '" x2="' + x + '" y1="' + (y - 4).toFixed(1) + '" y2="' + (y + 4).toFixed(1) +
        '" stroke="' + eventColor(e.type) + '" stroke-width="2" stroke-linecap="round" vector-effect="non-scaling-stroke"/>';
    }).join('');
    return '<svg viewBox="0 0 ' + Wd + ' ' + H + '" preserveAspectRatio="none" aria-hidden="true">' +
      '<path d="' + area + '" fill="rgba(14,31,53,.05)"/>' + zero +
      '<path d="' + pts + '" fill="none" stroke="#0E1F35" stroke-width="1.4" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>' +
      ticks + '</svg>';
  }
  // ---------- 阶段综述：嵌入对应日期的时间轴分组 ----------
  function stripHtml(html) {
    return String(html || '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
  }
  function stageAnchors(cy) {
    const segs = cy.segments || [];
    const bull = segs.find(s => s.type === 'bull') || { start: cy.start, end: cy.peak };
    const bear = segs.find(s => s.type === 'bear') || { start: cy.peak, end: cy.end || W.asof };
    const a = cy.analysis || {};
    return [
      { key: 'bottom', title: '1）底部环境', date: cy.start, tone: 'bottom', body: a.bottom || '' },
      { key: 'bull', title: '2）牛市阶段', date: bull.start, tone: 'bull', body: a.bull || '' },
      { key: 'peak', title: '3）牛市顶点', date: bull.end, tone: 'peak', body: a.peak || '' },
      { key: 'bear', title: '4）转熊', date: bear.start, tone: 'bear', body: a.bear || '' },
    ];
  }
  function stageHtml(st) {
    return '<details class="tl-stage ' + st.tone + '">' +
      '<summary><span class="st-dot"></span>' +
      '<span class="st-title">' + st.title + '</span>' +
      '<span class="st-date">' + st.date + '</span>' +
      '<span class="st-preview">' + stripHtml(st.body).slice(0, 58) + '…</span>' +
      '<span class="st-toggle"><span class="st-open">展开</span><span class="st-close">收起</span></span>' +
      '</summary><div class="st-body">' + st.body + '</div></details>';
  }

  // ---------- Cycle Snapshot：选中周期后的阶段统计 ----------
  function monthDiff(a, b) {
    const A = new Date(a + 'T00:00:00'), B = new Date(b + 'T00:00:00');
    return (B.getFullYear() - A.getFullYear()) * 12 + (B.getMonth() - A.getMonth());
  }
  function fmtDuration(months, days) {
    if (months <= 0) return (days || 0) + ' 天';
    if (months < 12) return months + ' 个月';
    const y = Math.floor(months / 12), m = months % 12;
    return y + ' 年' + (m ? ' ' + m + ' 个月' : '');
  }
  function phaseIndexStats(idx, start, end) {
    const kd = W.kline && W.kline[idx];
    // 指数成立晚于阶段起点时，该阶段整体留空，不拿半段行情冒充全程
    if (!kd || !kd.dates || !kd.dates.length || kd.dates[0] > start) return null;
    const rows = rowsBetween(kd, start, end);
    if (!rows.length) return null;
    const first = rows[0], last = rows[rows.length - 1];
    let peak = first.c, peakDate = first.d, mdd = 0, ddFrom = first.d, ddTo = first.d;
    let trough = first.c, troughDate = first.d, mrb = 0, rbFrom = first.d, rbTo = first.d;
    let high = first, low = first;
    rows.forEach(r => {
      if (r.c > peak) { peak = r.c; peakDate = r.d; }
      const dd = r.c / peak - 1;
      if (dd < mdd) { mdd = dd; ddFrom = peakDate; ddTo = r.d; }
      if (r.c < trough) { trough = r.c; troughDate = r.d; }
      const rb = r.c / trough - 1;
      if (rb > mrb) { mrb = rb; rbFrom = troughDate; rbTo = r.d; }
      if (r.h > high.h) high = r;
      if (r.l < low.l) low = r;
    });
    return {
      rows, first, last, high, low,
      ret: (last.c / first.c - 1) * 100,
      months: monthDiff(start, end),
      mdd: mdd * 100, ddFrom, ddTo,
      mrb: mrb * 100, rbFrom, rbTo,
    };
  }
  // 各指数见顶时间不同：在整轮区间（牛市起点→熊市终点）内取该指数自身最高价作为阶段分界。
  // 指数中途才上市时从上市首日开始找，保证熊市段仍可单独统计。
  function phasePeak(idx, start, end) {
    const kd = W.kline && W.kline[idx];
    if (!kd || !kd.dates || !kd.dates.length || kd.dates[kd.dates.length - 1] < start) return null;
    const from = kd.dates[0] > start ? kd.dates[0] : start;
    let bi = -1;
    for (let i = lowerBound(kd.dates, from); i < kd.dates.length && kd.dates[i] <= end; i++) {
      if (kd.high[i] == null) continue;
      if (bi < 0 || kd.high[i] > kd.high[bi]) bi = i;
    }
    if (bi < 0) return null;
    return { i: bi, d: kd.dates[bi], h: kd.high[bi], c: kd.close[bi] };
  }
  // 指数在该轮起点尚未上市时，不强行取自身高点（会与名义牛熊重叠），沿用名义见顶日的行情
  function phasePeakAt(idx, date) {
    const kd = W.kline && W.kline[idx];
    if (!kd || !kd.dates || !kd.dates.length) return null;
    const i = lowerBound(kd.dates, date);
    if (i >= kd.dates.length) return null;
    return { i, d: kd.dates[i], h: kd.high[i], c: kd.close[i] };
  }
  // 熊市结束之后，首次收盘回到前高；避免把见顶后一两天的反抽当作“消化完成”
  function findRecovery(idx, peakDate, bearEnd, peakClose) {
    const kd = W.kline && W.kline[idx];
    if (!kd || !kd.dates || peakClose == null) return null;
    let i = lowerBound(kd.dates, bearEnd);
    if (i < kd.dates.length && kd.dates[i] === bearEnd) i++;
    for (; i < kd.dates.length; i++) {
      if (kd.close[i] != null && kd.close[i] >= peakClose) return { date: kd.dates[i], close: kd.close[i] };
    }
    return null;
  }
  function csMetric(label, value, sub, cls) {
    return '<div class="cs-metric"><span>' + label + '</span>' +
      '<b class="' + (cls || '') + '">' + value + '</b><em>' + sub + '</em></div>';
  }
  function csRows(items, kind) {
    if (!items || !items.length) return '<div class="cs-empty">暂无样本</div>';
    return items.map((x, i) => {
      const retCls = x.ret >= 0 ? 'up' : 'down';
      if (kind === 'industry') {
        return '<div class="cs-row ind"><span class="cs-rank">' + (i + 1) + '</span>' +
          '<span class="cs-name">' + x.name + '</span>' +
          '<span class="cs-n">' + x.n + ' 只</span>' +
          '<span class="cs-ret ' + retCls + '">' + fmtSigned(x.ret, 1, '%') + '</span></div>';
      }
      return '<div class="cs-row"><span class="cs-rank">' + (i + 1) + '</span>' +
        '<span class="cs-name">' + x.name +
        '<em>' + x.code + '</em>' +
        (x.delisted ? '<i class="cs-del">退</i>' : '') +
        (x.industry ? '<span class="cs-ind">' + x.industry + '</span>' : '') +
        '</span>' +
        '<span class="cs-ret ' + retCls + '">' + fmtSigned(x.ret, 1, '%') + '</span></div>';
    }).join('');
  }
  function cycleSnapshotHtml(cy) {
    const CS = W.cycle_stats && W.cycle_stats.cycles && W.cycle_stats.cycles[cy.id];
    if (!CS) return '';
    const idx = (SCOPE.index === '全部' || !SCOPE.index) ? '上证指数' : SCOPE.index;
    const segs = cy.segments || [];
    const bullSeg = segs.find(s => s.type === 'bull') || { start: cy.start, end: cy.peak };
    const bearSeg = segs.find(s => s.type === 'bear') || { start: cy.peak, end: cy.end || W.asof };
    // 各指数见顶时间不同：完整经历本轮牛市的指数，用自身最高点切分牛熊；
    // 中途才上市的指数，牛市段留空，熊市段沿用名义见顶日。
    const kdIdx = W.kline && W.kline[idx];
    const listedAtStart = !!(kdIdx && kdIdx.dates && kdIdx.dates.length && kdIdx.dates[0] <= bullSeg.start);
    const peak = listedAtStart ? phasePeak(idx, bullSeg.start, bearSeg.end) : phasePeakAt(idx, bullSeg.end);
    const bull = (listedAtStart && peak) ? phaseIndexStats(idx, bullSeg.start, peak.d) : null;
    const bear = peak ? phaseIndexStats(idx, peak.d, bearSeg.end) : null;
    const bullRet = (bull && peak) ? (peak.h / bull.first.c - 1) * 100 : null;
    const bearRet = (bear && peak) ? (bear.last.c / peak.h - 1) * 100 : null;

    const ongoing = !cy.end || cy.id === 'c24now';
    const bearLabel = ongoing ? '调整阶段 · 进行中' : '熊市阶段';
    const bearWord = ongoing ? '调整' : '熊市';
    const incep = kdIdx && kdIdx.dates && kdIdx.dates[0];
    const emptyPhase = (label, seg, tone) => {
      const msg = (incep && incep > seg.start && incep <= seg.end)
        ? idx + ' 于 ' + incep + ' 上市 · 阶段起点无行情，区间数据留空'
        : idx + ' 此时尚未上市 · 区间数据留空';
      return '<div class="cs-phase ' + tone + '">' +
        '<div class="cs-phase-h"><span class="cs-dot"></span><b>' + label + '</b><span>' + seg.start + ' → ' + seg.end + '</span></div>' +
        '<div class="cs-phase-empty">' + msg + '</div></div>';
    };

    const bullHtml = bull ? '<div class="cs-phase bull">' +
      '<div class="cs-phase-h"><span class="cs-dot"></span><b>牛市阶段</b><span>' + bullSeg.start + ' → ' + peak.d + '</span></div>' +
      '<div class="cs-metrics">' +
      csMetric('历时', fmtDuration(bull.months), bull.rows.length + ' 个交易日') +
      csMetric('涨幅', fmtSigned(bullRet, 1, '%'), fmtNum(bull.first.c, 0) + ' → ' + fmtNum(peak.h, 0), 'up') +
      csMetric('最大回撤', fmtSigned(bull.mdd, 1, '%'), bull.ddFrom + ' → ' + bull.ddTo, 'down') +
      csMetric('区间高点', fmtNum(peak.h, 0), peak.d, '') +
      '</div></div>' : emptyPhase('牛市阶段', bullSeg, 'bull');

    const bearHtml = bear ? '<div class="cs-phase bear">' +
      '<div class="cs-phase-h"><span class="cs-dot"></span><b>' + bearLabel + '</b><span>' + peak.d + ' → ' + bearSeg.end + '</span></div>' +
      '<div class="cs-metrics">' +
      csMetric('历时', fmtDuration(bear.months), bear.rows.length + ' 个交易日') +
      csMetric('跌幅', fmtSigned(bearRet, 1, '%'), fmtNum(peak.h, 0) + ' → ' + fmtNum(bear.last.c, 0), 'down') +
      csMetric('最大反弹', fmtSigned(bear.mrb, 1, '%'), bear.rbFrom + ' → ' + bear.rbTo, 'up') +
      csMetric('区间低点', fmtNum(bear.low.l, 0), bear.low.d, '') +
      '</div></div>' : emptyPhase(bearLabel, bearSeg, 'bear');

    const listHtml = '<div class="cs-lists">' +
      '<section class="cs-list"><div class="cs-list-h"><h3>牛市 · 行业 Top10</h3><span>名义区间 · 等权</span></div>' +
      '<div class="cs-table"><div class="cs-row ind head"><span>#</span><span>行业</span><span>样本</span><span>涨幅</span></div>' +
      csRows(CS.bull.industries, 'industry') + '</div></section>' +
      '<section class="cs-list"><div class="cs-list-h"><h3>牛市 · 个股 Top10</h3><span>名义区间 · 复权</span></div>' +
      '<div class="cs-table"><div class="cs-row head"><span>#</span><span>个股</span><span>涨幅</span></div>' +
      csRows(CS.bull.stocks, 'stock') + '</div></section>' +
      '<section class="cs-list"><div class="cs-list-h"><h3>' + bearWord + ' · 行业跌幅 Top10</h3><span>名义区间 · 等权</span></div>' +
      '<div class="cs-table"><div class="cs-row ind head"><span>#</span><span>行业</span><span>样本</span><span>跌幅</span></div>' +
      csRows(CS.bear.industries_bottom, 'industry') + '</div></section>' +
      '<section class="cs-list"><div class="cs-list-h"><h3>' + bearWord + ' · 个股跌幅 Top10</h3><span>名义区间 · 复权</span></div>' +
      '<div class="cs-table"><div class="cs-row head"><span>#</span><span>个股</span><span>跌幅</span></div>' +
      csRows(CS.bear.stocks_bottom, 'stock') + '</div></section>' +
      '</div>';

    return '<section class="cycle-snapshot">' +
      '<div class="cs-head"><div><div class="cs-kicker">Cycle Snapshot · 阶段统计</div>' +
      '<h2 class="cs-title">' + cy.name + ' <span>' + cy.type + (cy.theme ? ' · ' + cy.theme : '') + '</span></h2></div>' +
      '<div class="cs-badge">指数口径 · ' + idx + '</div></div>' +
      '<div class="cs-phases">' + bullHtml + bearHtml + '</div>' +
      listHtml +
      '<div class="cs-note">口径：指数阶段按' + idx + '自身最高点切分（各指数见顶时间不同）；牛市起点时尚未上市的指数，牛市段留空、熊市段沿用名义见顶日。涨幅为阶段起点收盘→区间最高价，跌幅为区间最高价→阶段终点收盘；牛市起点与熊市终点沿用周期名义日期，随顶部基准指数切换。行业/个股 Top10 为全市场口径，按名义区间统计，不随指数切换。行业为申万一级（当前分类回溯）等权，样本少于 5 只不参与排名；个股为沪深A股复权价，剔除阶段内上市新股，仅统计阶段起止均有行情的个股，含已退市个股。历史统计仅供参考，不构成投资建议。</div>' +
      '</section>';
  }
  // 左侧事件：合并所有已有股指的事件；拐点统一取上证口径，
  // 避免同一轮底部在时间轴里出现 7 个不同点位。
  function mergedCycleEvents(cy) {
    const end = cy.end || W.asof;
    const inWin = e => e.date >= cy.start && e.date <= end;
    const out = [], seen = new Set();
    const push = e => {
      const key = e.date + '|' + e.label;
      if (seen.has(key)) return;
      seen.add(key); out.push(e);
    };
    Object.keys(W.index_events || {}).forEach(n => {
      (W.index_events[n] || []).filter(e => e.kind !== 'tp' && inWin(e)).forEach(push);
    });
    ((W.index_events && W.index_events['上证指数']) || [])
      .filter(e => e.kind === 'tp' && inWin(e)).forEach(push);
    out.sort((a, b) => a.date < b.date ? -1 : a.date > b.date ? 1 : 0);
    return out;
  }

  // 右侧两月视图的数据：按当前基准指数实时取，未上市则返回空 rows
  function lensDataFor(b) {
    const st = cycleLensState;
    const kd = W.kline && W.kline[st.iname];
    const rows = rowsBetween(kd, b.start, b.end);
    const base = rows.length ? rows[0].c : null;
    const last = rows.length ? rows[rows.length - 1].c : null;
    const ret = (base != null && last != null && base !== 0) ? (last / base - 1) * 100 : null;
    const byDate = {}, evByRow = {}, evPts = [], rowByDate = {};
    b.events.forEach(e => { (byDate[e.date] = byDate[e.date] || []).push(e); });
    rows.forEach(r => { rowByDate[r.d] = r; });
    Object.keys(byDate).sort().forEach(d => {
      const row = nearestRow(rows, d);
      if (!row) return;  // 该指数此时无行情，事件不画点
      evByRow[row.d] = (evByRow[row.d] || []).concat(byDate[d]);
      evPts.push({
        value: [lensMode === 'kline' ? row.d : ts(d),
          lensMode === 'kline' ? row.c : (row.c / base - 1) * 100],
        name: d, evs: byDate[d],
        itemStyle: { color: eventColor(byDate[d][0].type) },
      });
    });
    return { rows, base, last, ret, byDate, evPts, evByRow, rowByDate };
  }

  function renderCycleDetail(cy) {
    const box = document.getElementById('cycle-narrative');
    if (!box) return;
    disposeChartsIn(box);
    const events = mergedCycleEvents(cy);
    const refKd = W.kline && W.kline['上证指数'];
    const buckets = twoMonthBuckets(cy, events);
    const stages = stageAnchors(cy);
    let totalEv = 0;
    buckets.forEach(b => {
      b.refRows = rowsBetween(refKd, b.start, b.end);
      b.refBase = b.refRows.length ? b.refRows[0].c : null;
      b.refLast = b.refRows.length ? b.refRows[b.refRows.length - 1].c : null;
      b.refRet = (b.refBase != null && b.refLast != null && b.refBase !== 0)
        ? (b.refLast / b.refBase - 1) * 100 : null;
      b.spark = sparkSvg(b.refRows, b.events);
      b.stages = stages.filter(st => st.date >= b.start && st.date <= b.end);
      totalEv += b.events.length;
    });
    const lensIdx = (SCOPE.index === '全部' || !SCOPE.index) ? '上证指数' : SCOPE.index;
    const head = '<div class="card-head"><h2>' + cy.name + ' · ' + cy.type + '</h2>' +
      '<span class="asof">' + cy.start + ' — ' + (cy.end || '至今') + '</span></div>';
    const sub = '<div class="cycle-sub">' + buckets.length + ' 个两月分段 · ' +
      (totalEv ? totalEv + ' 个关键事件' : '暂无关键事件') +
      ' · 点位与涨跌幅参照上证指数</div>';

    let gHtml = '';
    buckets.forEach((b, i) => {
      const has = b.refRows.length > 0;
      const chgCls = b.refRet == null ? 'flat' : (b.refRet > 0.05 ? 'up' : b.refRet < -0.05 ? 'down' : 'flat');
      const chgTxt = b.refRet == null ? '—' : (Math.abs(b.refRet) < 0.05 ? '0.0%' : fmtSigned(b.refRet, 1, '%'));
      const rangeTxt = has ? '上证 ' + fmtNum(b.refBase, 0) + ' → ' + fmtNum(b.refLast, 0) : '无行情';
      const evHtml = b.events.length
        ? '<div class="tl-events">' + b.events.map(e =>
            '<div class="ev-item" data-date="' + e.date + '" data-label="' + String(e.label).replace(/"/g, '&quot;') + '">' +
            '<span class="ev-dot ' + e.type + '"></span><span class="ev-date">' + e.date.slice(5) + '</span>' +
            '<span class="ev-label">' + e.label + '</span></div>').join('') + '</div>'
        : '';
      gHtml += '<div class="tl-group" data-key="' + b.key + '" data-i="' + i + '">' +
        '<div class="tl-head">' +
        '<span class="tl-period">' + b.label + '</span>' +
        '<span class="tl-range">' + rangeTxt + '</span>' +
        '<span class="tl-chg ' + chgCls + '">' + chgTxt + '</span>' +
        '<span class="tl-count' + (b.events.length ? '' : ' zero') + '">' +
        (b.events.length ? b.events.length + ' 事件' : '暂无事件') + '</span>' +
        '</div>' +
        (b.stages.length ? b.stages.map(stageHtml).join('') : '') +
        evHtml +
        (b.spark ? '<div class="tl-spark">' + b.spark + '</div>' : '') +
        '</div>';
    });

    box.innerHTML = '<div class="chart-card">' + head + sub +
      '<div class="cycle-layout">' +
      '<div class="cycle-main">' + gHtml + '</div>' +
      '<aside class="cycle-aside"><div class="lens-card">' +
      '<div class="lens-top"><div class="lens-kicker">Two-Month Lens · 指数对照</div>' +
      '<div class="lens-mode" id="lens-mode">' +
      '<button data-lmode="line"' + (lensMode === 'line' ? ' class="active"' : '') + '>走势</button>' +
      '<button data-lmode="kline"' + (lensMode === 'kline' ? ' class="active"' : '') + '>K线</button>' +
      '</div></div>' +
      '<div class="lens-head"><div class="lens-period" id="lens-period">—</div>' +
      '<div class="lens-idx" id="lens-idx">' + lensIdx + '</div></div>' +
      '<div class="lens-stats" id="lens-stats"></div>' +
      '<div class="lens-plot"><div class="chart" id="cycle-lens" style="height:252px"></div>' +
      '<div class="lens-empty" id="lens-empty" hidden><span id="lens-empty-txt">该指数此区间暂无行情</span></div></div>' +
      '<div class="lens-foot"><span class="lens-note" id="lens-note">—</span></div>' +
      '<div class="lens-hint">滚动左栏自动切换；点选事件在图中定位。底部灰线为本轮全周期，金色为本段。</div>' +
      '</div></aside></div></div>';

    cycleLensState = {
      cy, iname: lensIdx, buckets,
      overview: rowsBetween(W.kline && W.kline[lensIdx], cy.start, cy.end || W.asof),
      activeKey: null,
    };

    $$('[data-lmode]', box).forEach(btn => btn.addEventListener('click', function () {
      if (lensMode === btn.dataset.lmode) return;
      lensMode = btn.dataset.lmode;
      $$('[data-lmode]', box).forEach(x => x.classList.toggle('active', x === btn));
      const st = cycleLensState;
      const b = st && st.buckets.find(x => x.key === st.activeKey);
      if (b) renderCycleLens(b);
    }));
    $$('.ev-item', box).forEach(it => it.addEventListener('click', function () { selectCycleEvent(it); }));

    if (document.body.dataset.view === 'cycle') {
      requestAnimationFrame(function () { updateCycleLens(true); });
    }
  }

  // 点选事件：不跳主图，只把右侧两月窗口切到该段并弹出对应位置
  function selectCycleEvent(item) {
    const st = cycleLensState;
    const box = document.getElementById('cycle-narrative');
    if (!st || !box) return;
    const group = item.closest('.tl-group');
    const b = group && st.buckets.find(x => x.key === group.dataset.key);
    if (!b) return;
    $$('.ev-item', box).forEach(x => x.classList.toggle('sel', x === item));
    if (st.activeKey !== b.key) {
      st.activeKey = b.key;
      $$('.tl-group', box).forEach(g => g.classList.toggle('active', g === group));
    }
    const ld = renderCycleLens(b);
    if (!ld) return;
    const row = nearestRow(ld.rows, item.dataset.date);
    if (!row) return;
    const di = (lensMode === 'kline' && ld.catDates)
      ? ld.catDates.indexOf(row.d) : ld.rows.indexOf(row);
    const ch = charts['cycle-lens'];
    if (ch && di >= 0) {
      setTimeout(function () {
        try { ch.dispatchAction({ type: 'showTip', seriesIndex: 0, dataIndex: di }); } catch (e) { }
      }, 40);
    }
  }

  function renderCycleLens(b) {
    const st = cycleLensState;
    if (!st || !b) return null;
    const periodEl = document.getElementById('lens-period');
    const idxEl = document.getElementById('lens-idx');
    const statsEl = document.getElementById('lens-stats');
    const noteEl = document.getElementById('lens-note');
    const emptyEl = document.getElementById('lens-empty');
    const emptyTxt = document.getElementById('lens-empty-txt');
    const el = document.getElementById('cycle-lens');
    if (!el) return null;
    const ld = lensDataFor(b);
    const has = ld.rows.length > 0;
    const evTxt = b.events.length ? b.events.length + ' 个关键事件' : '本段暂无关键事件';
    if (periodEl) periodEl.textContent = b.label;
    if (idxEl) idxEl.textContent = st.iname;
    if (statsEl) {
      statsEl.innerHTML = has
        ? '<span><b>' + fmtNum(ld.base, 0) + '</b> → <b>' + fmtNum(ld.last, 0) + '</b></span>' +
          '<span class="' + (ld.ret == null ? '' : ld.ret > 0.05 ? 'up' : ld.ret < -0.05 ? 'down' : '') + '">' +
          (ld.ret == null ? '—' : (Math.abs(ld.ret) < 0.05 ? '0.0%' : fmtSigned(ld.ret, 2, '%'))) + '</span>' +
          '<span class="ev">' + evTxt + '</span>'
        : '<span class="ev">暂无行情 · ' + evTxt + '</span>';
    }
    const kd = W.kline && W.kline[st.iname];
    const first = kd && kd.dates && kd.dates[0];
    if (emptyTxt) {
      emptyTxt.textContent = (first && first > b.end)
        ? st.iname + ' 自 ' + first + ' 起有行情'
        : '该指数此区间暂无行情';
    }
    if (emptyEl) emptyEl.hidden = has;
    if (noteEl) noteEl.textContent = has ? ld.rows.length + ' 个交易日' : '无行情数据';
    if (el.clientWidth < 50) return null;  // 窄屏/隐藏容器不按 0 宽初始化

    const winEnd = b.end < W.asof ? b.end : W.asof;
    const ov = st.overview || [];
    const ovData = ov.map(r => [ts(r.d), r.c]);
    let band = [];
    if (ov.length) {
      const a = Math.max(ts(b.start), ts(ov[0].d));
      const z = Math.min(ts(b.end), ts(ov[ov.length - 1].d));
      if (z > a) band = [[{ xAxis: a, itemStyle: { color: 'rgba(168,135,91,.30)' } }, { xAxis: z }]];
    }
    const axisDate = v => { const d = new Date(v); return pad2(d.getMonth() + 1) + '-' + pad2(d.getDate()); };
    const isK = lensMode === 'kline';
    let catDates = [], candleData = [];
    if (isK) {
      // K 线用上证交易日做市场日历，指数尚未上市时也能保留两月框架
      const cal = rowsBetween(W.kline && W.kline['上证指数'], b.start, winEnd);
      catDates = cal.map(r => r.d);
      if (!catDates.length) catDates = ld.rows.map(r => r.d);
      candleData = catDates.map(d => {
        const r = ld.rowByDate[d];
        return r ? [r.o, r.c, r.l, r.h] : '-';
      });
    }
    const lineData = ld.base ? ld.rows.map(r => [ts(r.d), (r.c / ld.base - 1) * 100]) : [];
    const ch = charts['cycle-lens'] || echarts.init(el);
    charts['cycle-lens'] = ch;
    ch.setOption({
      textStyle: CHART_OPTS.textStyle,
      animation: false,
      grid: [
        { left: 48, right: 18, top: 12, bottom: 72 },
        { left: 48, right: 18, height: 22, bottom: 10 },
      ],
      tooltip: {
        trigger: 'axis', confine: true,
        axisPointer: { type: 'cross', lineStyle: { color: 'rgba(20,19,19,.3)', type: 'dashed' }, label: { backgroundColor: C.accent } },
        backgroundColor: 'rgba(255,255,255,.98)', borderColor: C.line, borderRadius: 4,
        textStyle: { color: C.ink, fontSize: 11.5 },
        formatter: function (ps) {
          if (!ps || !ps.length) return '';
          if (isK) {
            const ds = ps[0].axisValue;
            const row = ld.rowByDate[ds];
            if (!row) {
              return '<div class="k-tip"><div class="k-tip-d">' + ds + '</div>' +
                '<div class="kt-r"><span>行情</span><b class="kt-flat">该指数此日无行情</b></div></div>';
            }
            const ri = ld.rows.indexOf(row);
            const prev = ri > 0 ? ld.rows[ri - 1] : null;
            const evHtml = (ld.evByRow[ds] || []).map(e =>
              '<div class="kt-r"><span>事件</span><b style="color:' + eventColor(e.type) + '">' + e.label + '</b></div>').join('');
            return klineTipHtml(ds, row.o, row.h, row.l, row.c, prev ? prev.c : null, row.amt, evHtml);
          }
          const p = (ps || []).find(x => x.seriesName === st.iname);
          if (!p || !p.value) return '';
          const ds = fmtDate(p.value[0]);
          const row = ld.rows[p.dataIndex];
          const pct = p.value[1];
          let h = '<b>' + ds + '</b><br/>' + st.iname + ' ' + fmtNum(row ? row.c : null, 2) +
            '　<span style="color:' + (pct >= 0 ? C.up : C.down) + ';font-weight:700">' + fmtSigned(pct, 2, '%') + '</span>';
          const evs = ld.evByRow[ds];
          if (evs) evs.forEach(e => { h += '<br/><span style="color:' + eventColor(e.type) + '">●</span> ' + e.label; });
          return h;
        },
      },
      xAxis: isK ? [
        { type: 'category', data: catDates, gridIndex: 0, axisLine: { lineStyle: { color: C.axis } }, axisTick: { show: false },
          axisLabel: { color: C.muted, fontSize: 11.5, hideOverlap: true, formatter: v => String(v).slice(5) },
          axisPointer: { label: { formatter: function (p) { return String(p.value); } } },
          splitLine: { show: false } },
        { type: 'time', gridIndex: 1, show: false },
      ] : [
        { type: 'time', gridIndex: 0, min: ts(b.start), max: ts(winEnd), splitNumber: 4,
          axisLine: { lineStyle: { color: C.axis } }, axisTick: { show: false },
          axisLabel: { color: C.muted, fontSize: 11.5, hideOverlap: true, showMinLabel: false, formatter: axisDate },
          axisPointer: { label: { formatter: function (p) { return fmtDate(p.value); } } },
          splitLine: { show: false } },
        { type: 'time', gridIndex: 1, show: false },
      ],
      yAxis: [
        isK ? {
          type: 'value', gridIndex: 0, scale: true, splitNumber: 4,
          axisLine: { show: false }, axisTick: { show: false },
          splitLine: { show: has, lineStyle: { color: C.grid } },
          axisLabel: { show: has, color: C.muted, fontSize: 11.5, formatter: v => fmtNum(v, 0) },
          axisPointer: { label: { formatter: function (p) { return fmtNum(p.value, 0); } } },
        } : {
          type: 'value', gridIndex: 0, scale: true, splitNumber: 4,
          axisLine: { show: false }, axisTick: { show: false },
          splitLine: { show: has, lineStyle: { color: C.grid } },
          axisLabel: { show: has, color: C.muted, fontSize: 11.5, formatter: v => (v > 0 ? '+' : '') + nf(Math.abs(v) >= 10 ? 0 : 1).format(v) + '%' },
          axisPointer: { label: { formatter: function (p) { return fmtSigned(p.value, 1, '%'); } } },
        },
        { type: 'value', gridIndex: 1, show: false, scale: true },
      ],
      series: isK ? [
        {
          name: st.iname, type: 'candlestick', xAxisIndex: 0, yAxisIndex: 0, data: candleData,
          barMaxWidth: 8,
          itemStyle: { color: C.up, color0: C.down, borderColor: C.up, borderColor0: C.down },
        },
        {
          name: '__events__', type: 'scatter', xAxisIndex: 0, yAxisIndex: 0, data: ld.evPts,
          symbolSize: 7, z: 5, itemStyle: { borderColor: '#fff', borderWidth: 1.2 },
          tooltip: {
            trigger: 'item', confine: true, backgroundColor: 'rgba(255,255,255,.98)', borderColor: C.line,
            textStyle: { color: C.ink, fontSize: 11.5 },
            formatter: function (p) {
              let h = '<b>' + p.data.name + '</b>';
              (p.data.evs || []).forEach(e => { h += '<br/><span style="color:' + eventColor(e.type) + '">●</span> ' + e.label; });
              return h;
            },
          },
        },
        {
          name: '__overview__', type: 'line', xAxisIndex: 1, yAxisIndex: 1, data: ovData,
          showSymbol: false, silent: true,
          lineStyle: { color: 'rgba(20,19,19,.30)', width: 1 }, itemStyle: { color: 'rgba(20,19,19,.30)' },
          areaStyle: { color: 'rgba(20,19,19,.04)' },
          markArea: { silent: true, data: band },
        },
      ] : [
        {
          name: st.iname, type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: lineData,
          showSymbol: ld.rows.length < 4, symbolSize: 5, smooth: false,
          lineStyle: { color: '#0E1F35', width: 1.8 }, itemStyle: { color: '#0E1F35' },
          areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [
            { offset: 0, color: 'rgba(14,31,53,.09)' }, { offset: 1, color: 'rgba(14,31,53,0)' }] } },
          markLine: { silent: true, symbol: 'none', data: [{ yAxis: 0, lineStyle: { color: 'rgba(20,19,19,.18)', type: 'dashed', width: 1 }, label: { show: false } }] },
        },
        {
          name: '__events__', type: 'scatter', xAxisIndex: 0, yAxisIndex: 0, data: ld.evPts,
          symbolSize: 7, z: 5, itemStyle: { borderColor: '#fff', borderWidth: 1.2 },
          tooltip: {
            trigger: 'item', confine: true, backgroundColor: 'rgba(255,255,255,.98)', borderColor: C.line,
            textStyle: { color: C.ink, fontSize: 11.5 },
            formatter: function (p) {
              let h = '<b>' + p.data.name + '</b>';
              (p.data.evs || []).forEach(e => { h += '<br/><span style="color:' + eventColor(e.type) + '">●</span> ' + e.label; });
              return h;
            },
          },
        },
        {
          name: '__overview__', type: 'line', xAxisIndex: 1, yAxisIndex: 1, data: ovData,
          showSymbol: false, silent: true,
          lineStyle: { color: 'rgba(20,19,19,.30)', width: 1 }, itemStyle: { color: 'rgba(20,19,19,.30)' },
          areaStyle: { color: 'rgba(20,19,19,.04)' },
          markArea: { silent: true, data: band },
        },
      ],
    }, { notMerge: true });
    ch.resize();
    if (isK) ld.catDates = catDates;
    return ld;
  }

  // 基准指数切换：左侧事件轴固定不动，只刷新右侧对照图
  function refreshCycleLensIndex(i) {
    const st = cycleLensState;
    if (!st) return;
    st.iname = (i === '全部' || !i) ? '上证指数' : i;
    st.overview = rowsBetween(W.kline && W.kline[st.iname], st.cy.start, st.cy.end || W.asof);
    if (document.body.dataset.view !== 'history' && document.body.dataset.view !== 'cycle') return;
    const b = st.buckets.find(x => x.key === st.activeKey);
    if (b) renderCycleLens(b); else updateCycleLens(true);
  }

  function updateCycleLens(force) {
    const st = cycleLensState;
    const box = document.getElementById('cycle-narrative');
    if (!st || !box || (document.body.dataset.view !== 'history' && document.body.dataset.view !== 'cycle')) return;
    const groups = $$('.tl-group', box);
    if (!groups.length) return;
    // 阅读线放在粘性口径栏之下（移动端口径栏会换成两行）
    const sb = document.querySelector('.scope-bar');
    const line = Math.max(150, (sb ? sb.getBoundingClientRect().bottom : 112) + 28);
    let active = groups[0];
    for (let i = 0; i < groups.length; i++) {
      if (groups[i].getBoundingClientRect().top <= line) active = groups[i]; else break;
    }
    const key = active.dataset.key;
    if (!force && key === st.activeKey) return;
    if (key !== st.activeKey) $$('.ev-item.sel', box).forEach(x => x.classList.remove('sel'));
    st.activeKey = key;
    groups.forEach(g => g.classList.toggle('active', g === active));
    const b = st.buckets.find(x => x.key === key);
    if (b) renderCycleLens(b);
  }

  // ---------- 当前观察 ----------
  const RECENT_WD = { '1m': 20, '3m': 60, '6m': 120 };
  function renderCurrent() {
    const _pa = document.getElementById('dash-asof');
    if (_pa) _pa.innerHTML = '<span class="dot"></span>数据截至 <b>' + W.asof + '</b>';
    const aOnly = document.getElementById('a-only');
    if (aOnly) aOnly.hidden = false;
    // 综合建议页顶部的资产类别功能栏（与资产走势页共用同一份渲染）
    const _D = W.cycle_overlay || {};
    renderAfLists(_D, Object.keys(_D));
    renderConclusion();
    renderNsf();
    renderHistStats();
    renderMl();
    renderModels();
    renderLongIndicators();
    renderIndicators();
  }
  // 资产走势（独立子页）：只要周期叠加图，不加载 K 线与全A指标
  function renderTrends() {
    const _pa = document.getElementById('trends-asof');
    if (_pa) _pa.innerHTML = '<span class="dot"></span>数据截至 <b>' + W.asof + '</b>';
    renderCycleOverlay();
  }
  // ---------- 综合建议：结论先行，下方恢复原两种评价机制 ----------
  function renderConclusion() {
    const el = document.getElementById('conclusion');
    if (!el) return;
    if (typeof AF_CAT !== 'undefined' && AF_CAT !== 'a') {
      const nm = ((W.cycle_overlay || {})[AF_CAT] || {}).name || '该资产';
      el.innerHTML = '<div class="rec-placeholder"><b>' + nm + '</b> 综合建议暂未上线。' +
        '<span>当前仅开放 A 股指数与板块建议。</span></div>';
      return;
    }
    const C = W.conclusion || {};
    const R = W.recommendations || { summary: {}, indices: [], sectors: [] };
    const S = R.summary || {};
    const top = (R.indices || [])[0];
    if (!top) {
      el.innerHTML = '<div class="rec-stance watch">观察</div><div class="rec-sub">本期没有指数达到观察线，暂不新增指数观察项。</div>';
      return;
    }
    const c = top.components || {};
    const stats = [
      ['最高综合分 · ' + top.name, fmtNum(top.score, 1), '<small>/100</small>'],
      ['10／20 日规则分', fmtNum(c.rule, 1), '<small>/100</small>'],
      ['模型 20 日上行估计', c.model20 == null ? '—' : fmtNum(c.model20, 1), '<small>%</small>'],
      ['置信度', top.confidence || '低', ''],
    ].map(s => '<div class="rec-stat"><span>' + s[0] + '</span><b>' + s[1] + s[2] + '</b></div>').join('');
    el.innerHTML =
      '<div class="rec-stance watch">结构观察</div>' +
      '<div class="rec-sub">熊市' + (S.stage || (C.stage || {}).label || '—') +
        '<span class="dim"> · </span>' + (S.n_bear == null ? C.n_bear : S.n_bear) + '/' + (S.n_total == null ? C.n_total : S.n_total) + ' 指数处于熊市' +
        '<span class="dim"> · </span>' + (S.index_buy || 0) + ' 个指数、' + (S.sector_buy || 0) + ' 个板块偏买入</div>' +
      '<div class="rec-stats">' + stats + '</div>' +
      '<div class="rec-guide-row"><button type="button" class="guide-btn" data-guide="C" aria-expanded="false">这 4 个数字是什么<i>▾</i></button></div>' +
      '<div class="panel-guide" id="guide-C" hidden>' +
        '<dl>' +
          '<dt>最高综合分 · 指数</dt><dd>当前<b>综合分最高</b>的那个指数，以及它的分数（0–100）。综合分 = 65% × 规则分 + 35% × 模型 20 日上行估计，用于给所有指数排序。</dd>' +
          '<dt>10／20 日规则分</dt><dd>纯规则打分：40% × 10 日收缩胜率 + 60% × 20 日收缩胜率。只用「历史上相似状态后续涨不涨」的统计，不含模型。</dd>' +
          '<dt>模型 20 日上行估计</dt><dd>机器学习给的「未来 20 个交易日收盘高于今天」的概率。<b>不是实际胜率</b>，只适合横向比较。</dd>' +
          '<dt>置信度</dt><dd>规则分与模型是否一致：一致且样本充足为「高」，两者分歧或样本少为「中/低」。它反映的是<b>这个结论有多可靠</b>，不是涨跌幅度。</dd>' +
        '</dl>' +
        '<p class="pg-note">规则分与模型同向时结论更可信；若两者背离（例如规则偏买入但模型偏弱），建议按「观察」处理、不要一次打满。</p>' +
      '</div>';
  }

  // ---------- 资产走势：按资产类别 + 具体标的 ----------
  let AF_CAT = 'a';
  let AF_ITEM = null;
  const AF_CATS = [
    ['a', 'A股', '', 'stock'],
    ['us', '美股', '', 'stock'],
    ['jp', '日股', '', 'stock'],
    ['bond', '债券', '未上线', 'other'],
    ['cmdty', '商品', '', 'other'],
    ['other', '其他', '未上线', 'other'],
  ];
  function afCurrent() {
    const D = W.cycle_overlay || {};
    const cat = D[AF_CAT];
    if (!cat || !cat.items || !cat.items.length) return null;
    const item = cat.items.filter(x => x.key === AF_ITEM)[0] || cat.items[0];
    AF_ITEM = item.key;
    return { cat: cat, item: item };
  }
  // 资产类别功能栏：资产走势页 + 综合建议页 两处共用同一份渲染，任何一处点击都双向同步
  function renderAfLists(D, keys) {
    ['af-list', 'af-list-cur'].forEach(function (id) {
      const list = document.getElementById(id);
      if (!list) return;
      const mk = it => {
        const ok = keys.indexOf(it[0]) >= 0;
        return '<div class="af-item' + (ok ? '' : ' disabled') + (it[0] === AF_CAT ? ' active' : '') +
          '" data-af="' + it[0] + '"><span>' + it[1] + '</span></div>';
      };
      list.innerHTML = '<div class="af-group">股票</div>' +
        AF_CATS.filter(x => x[3] === 'stock').map(mk).join('') +
        '<div class="af-group">其他资产</div>' +
        AF_CATS.filter(x => x[3] === 'other').map(mk).join('');
      list.querySelectorAll('.af-item').forEach(function (d) {
        d.addEventListener('click', function () {
          if (d.classList.contains('disabled') || d.dataset.af === AF_CAT) return;
          AF_CAT = d.dataset.af; AF_ITEM = null;
          renderCycleOverlay();
          renderConclusion();
        });
      });
    });
  }

  function renderCycleOverlay() {
    const el = document.getElementById('chart-cycle-overlay');
    if (!el) return;
    const D = W.cycle_overlay || {};
    const keys = Object.keys(D);
    if (!keys.length) { el.innerHTML = '<div class="desc">走势数据未生成</div>'; return; }
    if (!D[AF_CAT]) AF_CAT = keys[0];
    const aOnly = document.getElementById('a-only');
    if (aOnly) aOnly.hidden = (AF_CAT !== 'a');
    const cur = afCurrent();
    if (!cur) return;
    const cat = cur.cat, item = cur.item;

    renderAfLists(D, keys);

    const chips = document.getElementById('af-items');
    if (chips) {
      chips.innerHTML = (cat.items || []).map(x =>
        '<button data-afi="' + x.key + '"' + (x.key === item.key ? ' class="active"' : '') + '>' +
        x.name + '</button>').join('');
      chips.querySelectorAll('button').forEach(function (b) {
        b.addEventListener('click', function () {
          if (b.dataset.afi === AF_ITEM) return;
          AF_ITEM = b.dataset.afi;
          renderCycleOverlay();
        });
      });
    }

    const n = (item.cycles || []).length;
    const title = document.getElementById('af-title');
    const cycleCount = document.getElementById('af-cycle-count');
    if (title) title.textContent = item.name;
    if (cycleCount) cycleCount.textContent = n + ' 轮牛熊';
    const note = document.getElementById('af-note');
    if (note) {
      note.innerHTML = '每条线从该轮起点归零，横轴是第几个交易日，纵轴是相对起点的累计收益。红色为本轮。';
    }

    const ch = charts['chart-cycle-overlay'] || echarts.init(el);
    charts['chart-cycle-overlay'] = ch;
    const GOLD = '#A8875B';
    const series = (item.cycles || []).map(function (c, i) {
      return {
        name: c.label,
        type: 'line',
        data: c.vals.map(function (v, j) { return [j, v]; }),
        showSymbol: false, smooth: true, z: c.current ? 6 : 2 + i,
        lineStyle: {
          width: c.current ? 2.6 : 1.4,
          color: c.current ? '#B8402F' : 'rgba(168,135,91,' + (0.42 + i * 0.07) + ')',
        },
        itemStyle: { color: c.current ? '#B8402F' : GOLD },
        emphasis: { focus: 'series' },
      };
    });
    ch.setOption({
      animation: false,
      grid: { left: 8, right: 18, top: 58, bottom: 12, containLabel: true },
      legend: { top: 0, left: 0, itemWidth: 14, itemHeight: 2, itemGap: 14,
        textStyle: { color: '#6B6558', fontSize: 11.5 } },
      tooltip: {
        trigger: 'axis', backgroundColor: '#fff', borderColor: '#E6E1D6', borderWidth: 1,
        textStyle: { color: '#141313', fontSize: 12 },
        formatter: function (ps) {
          let h = '<b>第 ' + ps[0].value[0] + ' 个交易日</b>';
          ps.forEach(function (p) {
            if (p.value == null) return;
            h += '<br>' + p.marker + p.seriesName + ' ' + fmtSigned(p.value[1], 1, '%');
          });
          return h;
        },
      },
      xAxis: {
        type: 'value', min: 0,
        axisLine: { show: false }, axisTick: { show: false },
        splitLine: { lineStyle: { color: '#F1EFE8' } },
        axisLabel: { color: '#8A8578', fontSize: 11 },
      },
      yAxis: {
        type: 'value', axisLabel: { color: '#8A8578', fontSize: 11, formatter: '{value}%' },
        splitLine: { lineStyle: { color: '#F1EFE8' } }, axisLine: { show: false },
      },
      series: series,
    }, { notMerge: true });

    // 图表下方：各资产周期统计
    const stBox = document.getElementById('af-stats');
    if (stBox) {
      let rows = '';
      Object.keys(D).forEach(function (k) {
        const cat = D[k];
        (cat.items || []).forEach(function (it) {
          const st = it.stats;
          if (!st) return;
          const on = (k === AF_CAT && it.key === AF_ITEM);
          rows += '<tr' + (on ? ' class="on"' : '') + '>' +
            '<td class="cat">' + cat.name + '</td>' +
            '<td>' + it.name + '</td>' +
            '<td>' + st.n + '</td>' +
            '<td>' + fmtNum(st.med_yrs, 1) + ' 年</td>' +
            '<td>' + fmtNum(st.max_yrs, 1) + ' 年</td>' +
            '<td>' + fmtSigned(st.med_peak, 0, '%') + '</td>' +
            '<td>' + fmtSigned(st.med_end, 0, '%') + '</td></tr>';
        });
      });
      const detailsOpen = stBox.querySelector('details') && stBox.querySelector('details').open;
      stBox.innerHTML = '<details class="af-collapse"' + (detailsOpen ? ' open' : '') + '>' +
        '<summary><span>各资产周期统计</span><em>点击展开 / 收起</em></summary>' +
        '<div class="af-collapse-body"><div class="af-table-wrap"><table class="af-tbl"><thead><tr>' +
        '<th>类别</th><th>标的</th><th>轮数</th><th>中位时长</th><th>最长</th>' +
        '<th>中位最大涨幅</th><th>中位终值</th></tr></thead><tbody>' + rows + '</tbody></table></div>' +
        '<div class="af-note">时长按 244 个交易日/年折算；最大涨幅 = 该轮内相对起点的最高涨幅；' +
        '终值 = 该轮结束时相对起点的收益。样本少（A股 4–5 轮），中位数只作量级参考。</div></div></details>';
    }
    if (window.TrendView && typeof window.TrendView.render === 'function') {
      window.TrendView.render(AF_CAT, item);
    }
  }

  // ---------- 历史统计：技术 / 基本面 / 情绪 三维打分 ----------
  function hsScore(v) {
    if (v == null) return '<td class="hs-num none">—</td>';
    return '<td class="hs-num"><i class="hs-bar"><b style="width:' + v + '%"></b></i>' +
      '<em>' + v + '</em></td>';
  }
  function hsWin(d) {
    if (!d || !d.ok) return '<td class="hs-win none">' + (d && d.n ? 'n=' + d.n : '—') + '</td>';
    return '<td class="hs-win"><b class="' + (d.win >= 50 ? 'up' : 'down') + '">' +
      fmtNum(d.win, 0) + '%</b><span>' + d.seg + '段</span></td>';
  }
  function hsDim(title, obj) {
    const keys = Object.keys(obj || {});
    if (!keys.length) return '';
    const items = keys.map(function (k) {
      const d = obj[k];
      if (!d || d.s == null) {
        return '<div class="hs-item none"><span>' + k + '</span><em>—</em><b>—</b></div>';
      }
      const raw = (d.v == null) ? '' :
        (d.u === '%' ? fmtSigned(d.v, 1, '%') : fmtNum(d.v, 1) + (d.u || ''));
      return '<div class="hs-item"><span>' + k + '</span><em>' + raw + '</em>' +
        '<b>' + d.s + '</b><i class="hs-bar"><b style="width:' + d.s + '%"></b></i></div>';
    }).join('');
    return '<div class="hs-dim"><h4>' + title + '</h4>' + items + '</div>';
  }
  function hsTable(rows, key) {
    if (!rows || !rows.length) return '<div class="desc">无数据</div>';
    const scored = {};
    const recRows = (W.recommendations && W.recommendations[key === 'idx' ? 'indices' : 'sectors']) || [];
    recRows.forEach(function (x) { scored[x.name] = x; });
    let h = '<table class="hs-tbl"><thead><tr><th>资产</th><th>阶段</th><th>技术</th>' +
      '<th>基本面</th><th>情绪</th><th>10日</th><th>20日</th><th>模型20</th><th>综合</th><th>倾向</th></tr></thead><tbody>';
    rows.forEach(function (x, i) {
      const k = (x.kind === 'bear') ? '熊' : '牛';
      const rec = scored[x.name] || {};
      const cp = rec.components || {};
      const tendency = rec.tendency || x.tendency || '—';
      const model = key === 'idx' ? cp.model20 : cp.model_rank;
      const tn = tendency === '偏买入' ? ' buy' : (tendency === '偏减仓' ? ' sell' : '');
      h += '<tr class="hs-row" data-det="hs-d-' + key + '-' + i + '">' +
        '<td class="hs-name"><b>' + x.name + '</b>' +
        (x.desc ? '<span>' + x.desc + '</span>' : '') + '</td>' +
        '<td class="hs-stage"><span class="' + (x.kind === 'bear' ? 'down' : 'up') + '">' + k + '</span></td>' +
        hsScore(x.tech) + hsScore(x.fund) + hsScore(x.sent) +
        hsWin(x.win && x.win.d10) + hsWin(x.win && x.win.d20) +
        '<td class="hs-rank">' + (model == null ? '—' : fmtNum(model, 1)) + '</td>' +
        '<td class="hs-rank hs-score">' + (rec.score == null ? '—' : fmtNum(rec.score, 1)) + '</td>' +
        '<td class="hs-tend' + tn + '">' + tendency + '<i class="hs-caret">▾</i></td></tr>' +
        '<tr class="hs-det" id="hs-d-' + key + '-' + i + '" hidden><td colspan="10">' +
        '<div class="hs-det-in">' + hsDim('技术', x.tech_items) +
        hsDim('基本面', x.fund_items) + hsDim('情绪', x.sent_items) + '</div></td></tr>';
    });
    return '<div class="hs-tbl-wrap">' + h + '</tbody></table></div>';
  }
  function renderHistStats() {
    const H = W.hist_stats;
    const idxEl = document.getElementById('hist-pane-idx');
    const secEl = document.getElementById('hist-pane-sec');
    if (!idxEl || !secEl) return;
    if (!H) {
      idxEl.innerHTML = '<div class="desc">历史统计未生成，运行 python3 src/build_hist_stats.py</div>';
      return;
    }
    const ae = document.getElementById('hist-asof');
    if (ae) ae.textContent = '截至 ' + H.asof;
    idxEl.innerHTML = hsTable(H.indices, 'idx');
    secEl.innerHTML = hsTable(H.sectors, 'sec');

    const tabs = document.querySelectorAll('.ml-tab[data-htab]');
    if (tabs.length >= 2) {
      tabs[0].querySelector('em').textContent = H.indices.length;
      tabs[1].querySelector('em').textContent = H.sectors.length;
    }
    const note = document.getElementById('hist-note');
    if (note) {
      note.innerHTML = '技术、基本面、情绪均为 0–100 分，越高代表越极端。规则分＝40% × 10 日收缩胜率＋60% × 20 日收缩胜率；' +
        '指数综合分＝65% × 规则分＋35% × 模型 20 日上行估计，板块为技术、基本面、情绪、规则分、模型排名五维等权。' +
        '10／20 日列显示同档历史胜率，下方为独立段数；点任意一行展开技术、基本面和情绪明细。';
    }
    document.querySelectorAll('.hs-row').forEach(function (tr) {
      tr.addEventListener('click', function () {
        const d = document.getElementById(tr.dataset.det);
        if (!d) return;
        d.hidden = !d.hidden;
        tr.classList.toggle('open', !d.hidden);
      });
    });
    tabs.forEach(function (b) {
      if (b.dataset.bound) return;
      b.dataset.bound = '1';
      b.addEventListener('click', function () {
        tabs.forEach(function (x) { x.classList.toggle('on', x === b); });
        document.querySelectorAll('[data-hpane]').forEach(function (p) {
          p.hidden = (p.dataset.hpane !== b.dataset.htab);
        });
      });
    });
  }

  // ---------- 机器学习机制：同一焦点指数的 10 / 20 日分布 ----------
  function renderMl() {
    const el = document.getElementById('ml-body');
    if (!el) return;
    const M = W.ml_model;
    if (!M || !M.all_preds) {
      el.innerHTML = '<div class="desc">模型未生成，运行 python3 src/build_ml_model.py</div>';
      return;
    }
    const recTop = ((W.recommendations || {}).indices || [])[0] || {};
    const focus = M.all_preds[recTop.name] ? recTop.name : M.focus;
    const current = M.all_preds[focus] || {};
    const p = current['20'];
    if (!p) { el.innerHTML = '<div class="desc">当前指数暂无 20 日模型结果</div>'; return; }
    const ae = document.getElementById('ml-asof');
    if (ae) ae.textContent = focus + ' · 截至 ' + M.asof;
    const cells = [
      ['20 日中位', fmtSigned(p.p50, 1, '%')],
      ['下行 p10', fmtSigned(p.p10, 1, '%')],
      ['上行 p90', fmtSigned(p.p90, 1, '%')],
    ].map(c => '<div class="ml-cell"><span>' + c[0] + '</span><b>' + c[1] + '</b></div>').join('');
    el.innerHTML =
      '<div class="ml-top">' +
      '<div class="ml-big"><b>' + fmtNum(p.pup, 0) + '%</b><span>' + focus + ' · 未来 20 日上行估计 · 非实际胜率</span></div>' +
      '<div class="ml-cells">' + cells + '</div></div>' +
      '<div class="chart" id="chart-ml" style="height:252px"></div>';

    const scores = {};
    ((W.recommendations || {}).indices || []).forEach(x => { scores[x.name] = x.score; });
    const idx = Object.keys(M.all_preds || {}).map(k => ({
      name: k, p10: M.all_preds[k]['10'], p20: M.all_preds[k]['20']
    })).sort((a, b) => (scores[b.name] || 0) - (scores[a.name] || 0));
    const sec = (M.sectors || []).slice();
    const cell4 = r => '<div class="ml-row four"><b>' + r.name + '</b>' +
      '<span class="' + (r.p10.p50 >= 0 ? 'up' : 'down') + '">' + fmtSigned(r.p10.p50, 1, '%') + '</span>' +
      '<span>' + fmtNum(r.p20.pup, 0) + '%</span>' +
      '<span class="' + (r.p20.p50 >= 0 ? 'up' : 'down') + '">' + fmtSigned(r.p20.p50, 1, '%') + '</span></div>';
    const sector4 = r => '<div class="ml-row four"><b>' + r.name + '</b>' +
      '<span>' + fmtSigned(r.dd, 1, '%') + '</span>' +
      '<span>' + fmtNum(r.pup, 0) + '%</span>' +
      '<span class="' + (r.p50 >= 0 ? 'up' : 'down') + '">' + fmtSigned(r.p50, 1, '%') + '</span></div>';

    if (idx.length || sec.length) {
      el.innerHTML +=
        '<div class="ml-tabs">' +
        '<button class="ml-tab on" data-mlt="idx">指数 <em>' + idx.length + '</em></button>' +
        '<button class="ml-tab" data-mlt="sec">板块 <em>' + sec.length + '</em></button>' +
        '</div>' +
        '<div class="ml-pane" id="ml-pane-idx" data-pane="idx"><div class="ml-tbl">' +
        '<div class="ml-row ml-head four"><span>指数</span><span>10 日中位</span><span>20 日上行</span><span>20 日中位</span></div>' +
        idx.map(cell4).join('') + '</div></div>' +
        '<div class="ml-secwrap" data-pane="sec" hidden>' +
        '<div class="chart" id="chart-sec" style="height:232px"></div>' +
        '<div class="ml-scap" id="ml-scap"></div>' +
        '<div class="ml-pane"><div class="ml-tbl">' +
        '<div class="ml-row ml-head four"><span>板块</span><span>回撤</span><span>20 日上行</span><span>20 日中位</span></div>' +
        sec.map(sector4).join('') + '</div></div></div>' +
        '<div class="ml-note" data-pane="sec" hidden>申万一级行业，只列当前处于熊市的板块。</div>';
      el.querySelectorAll('.ml-tab').forEach(b => b.addEventListener('click', () => {
        el.querySelectorAll('.ml-tab').forEach(x => x.classList.toggle('on', x === b));
        el.querySelectorAll('[data-pane]').forEach(p => { p.hidden = (p.dataset.pane !== b.dataset.mlt); });
        if (b.dataset.mlt === 'sec') renderSectorChart();
      }));
    }
    renderMlChart(focus);
  }

  function renderMlChart(focus) {
    const el = document.getElementById('chart-ml');
    const M = W.ml_model;
    const current = M && M.all_preds && M.all_preds[focus];
    if (!el || !current || !current['10'] || !current['20']) return;
    const fan = [{ d: 0, p10: 0, p25: 0, p50: 0, p75: 0, p90: 0 }].concat([10, 20].map(function (h) {
      const q = current[String(h)];
      return { d: h, p10: q.p10, p25: q.p25, p50: q.p50, p75: q.p75, p90: q.p90 };
    }));
    const xs = fan.map(f => (f.d === 0 ? '今天' : f.d + '日'));
    const p10 = fan.map(f => f.p10), p25 = fan.map(f => f.p25), p50 = fan.map(f => f.p50),
      p75 = fan.map(f => f.p75), p90 = fan.map(f => f.p90);
    const b90 = p90.map((v, i) => +(v - p10[i]).toFixed(2));
    const b50 = p75.map((v, i) => +(v - p25[i]).toFixed(2));
    const GOLD = '#A8875B';
    const ymin = Math.floor(Math.min.apply(null, p10) / 10) * 10 - 5;
    const ymax = Math.ceil(Math.max.apply(null, p90) / 10) * 10 + 5;
    const bandPoly = (api, lo, hi) => {
      const top = [], bot = [];
      for (let i = 0; i < fan.length; i++) {
        top.push(api.coord([xs[i], hi[i]]));
        bot.push(api.coord([xs[i], lo[i]]));
      }
      return { type: 'polygon', shape: { points: top.concat(bot.reverse()) }, style: api.style() };
    };
    if (charts['chart-ml']) charts['chart-ml'].dispose();
    const ch = echarts.init(el);
    charts['chart-ml'] = ch;
    ch.setOption({
      animation: false,
      grid: { left: 4, right: 12, top: 16, bottom: 2, containLabel: true },
      tooltip: {
        trigger: 'axis',
        backgroundColor: '#fff', borderColor: '#E6E1D6', borderWidth: 1,
        padding: [9, 12], textStyle: { color: '#141313', fontSize: 12.5 },
        formatter: ps => {
          const i = ps[0].dataIndex, f = fan[i];
          if (i === 0) return '<b>今天</b>';
          return '<b>' + f.d + ' 个交易日后</b><br>' +
            '中位 <b>' + fmtSigned(f.p50, 1, '%') + '</b><br>' +
            'p25–p75 ' + fmtSigned(f.p25, 1, '%') + ' ~ ' + fmtSigned(f.p75, 1, '%') + '<br>' +
            'p10–p90 ' + fmtSigned(f.p10, 1, '%') + ' ~ ' + fmtSigned(f.p90, 1, '%');
        }
      },
      xAxis: {
        type: 'category', data: xs, boundaryGap: false,
        axisLine: { lineStyle: { color: '#E6E1D6' } }, axisTick: { show: false },
        axisLabel: { color: '#8A8578', fontSize: 11.5 }
      },
      yAxis: {
        type: 'value', min: ymin, max: ymax,
        axisLabel: { color: '#8A8578', fontSize: 11.5, formatter: '{value}%' },
        splitLine: { lineStyle: { color: '#EFEBE2' } }, axisLine: { show: false }
      },
      series: [
        {
          type: 'custom', silent: true, z: 1,
          data: fan.map((_, i) => i),
          renderItem: (params, api) => bandPoly(api, p10, p90),
          itemStyle: { color: 'rgba(168,135,91,0.045)' }
        },
        {
          type: 'custom', silent: true, z: 2,
          data: fan.map((_, i) => i),
          renderItem: (params, api) => bandPoly(api, p25, p75),
          itemStyle: { color: 'rgba(168,135,91,0.085)' }
        },
        {
          name: 'p10', type: 'line', data: p10, symbol: 'none', silent: true, z: 2,
          lineStyle: { color: 'rgba(168,135,91,0.45)', width: 1, type: 'dashed' }
        },
        {
          name: 'p90', type: 'line', data: p90, symbol: 'none', silent: true, z: 2,
          lineStyle: { color: 'rgba(168,135,91,0.45)', width: 1, type: 'dashed' }
        },
        {
          name: '中位', type: 'line', data: p50, symbol: 'circle', symbolSize: 5,
          lineStyle: { color: '#0E1F35', width: 2 }, itemStyle: { color: '#0E1F35' }, z: 3,
          markLine: {
            silent: true, symbol: 'none',
            lineStyle: { color: '#B9B3A6', type: 'dashed', width: 1 },
            label: { show: false }, data: [{ yAxis: 0 }]
          }
        }
      ]
    });
  }


  // ---------- 板块散点：回撤 vs 模型上行概率 ----------
  function renderSectorChart() {
    const el = document.getElementById('chart-sec');
    const M = W.ml_model;
    if (!el || !M || !M.sectors || !M.sectors.length) return;
    const pts = M.sectors;
    const sorted = pts.slice().sort((a, b) => b.pup - a.pup);
    const labelled = {};
    const labPts = sorted.slice(0, 3).concat(sorted.slice(-3));
    labPts.forEach(x => { labelled[x.name] = 1; });
    // 标签相近时手动错位，避免两个名称叠在一起
    const off = {};
    for (let i = 0; i < labPts.length; i++) {
      off[labPts[i].name] = off[labPts[i].name] || 0;
      for (let j = 0; j < i; j++) {
        if (Math.abs(labPts[i].dd - labPts[j].dd) < 4 &&
            Math.abs(labPts[i].pup - labPts[j].pup) < 5) {
          off[labPts[i].name] = (off[labPts[j].name] || 0) + 13;
        }
      }
    }

    const xs = pts.map(x => x.dd), ys = pts.map(x => x.pup);
    const xmin = Math.floor(Math.min.apply(null, xs) / 10) * 10;
    const xmax = Math.ceil(Math.max.apply(null, xs) / 10) * 10;
    const ymin = Math.max(0, Math.floor(Math.min.apply(null, ys) / 10) * 10);
    const ymax = Math.ceil(Math.max.apply(null, ys) / 10) * 10;

    const mk = arr => arr.map(x => ({
      name: x.name, value: [x.dd, x.pup],
      med: x.p50, tp: x.t_pct, sp: x.s_pct,
      label: labelled[x.name]
        ? { show: true, position: x.dd > xmax - 6 ? 'left' : 'right', offset: [0, off[x.name] || 0] }
        : { show: false }
    }));
    const ups = mk(pts.filter(x => x.p50 >= 0));
    const downs = mk(pts.filter(x => x.p50 < 0));

    if (charts['chart-sec']) charts['chart-sec'].dispose();
    const ch = echarts.init(el);
    charts['chart-sec'] = ch;
    const ser = (name, data, color) => ({
      name: name, type: 'scatter', data: data, symbolSize: 8.5, z: 3,
      itemStyle: { color: color, borderColor: '#fff', borderWidth: 1 },
      emphasis: { scale: 1.5 },
      label: {
        show: true, position: 'top', distance: 5, fontSize: 10.5, color: '#6B6558',
        formatter: p => p.name
      }
    });
    ch.setOption({
      animation: false,
      grid: { left: 8, right: 14, top: 28, bottom: 28, containLabel: true },
      tooltip: {
        trigger: 'item', backgroundColor: '#fff', borderColor: '#E6E1D6', borderWidth: 1,
        padding: [9, 12], textStyle: { color: '#141313', fontSize: 12.5 },
        formatter: p => {
          const d = p.data;
          return '<b>' + d.name + '</b><br>' +
            '当前回撤 <b>' + fmtSigned(d.value[0], 1, '%') + '</b><br>' +
            '上行概率 <b>' + fmtNum(d.value[1], 0) + '%</b><br>' +
            '20 日中位 ' + fmtSigned(d.med, 1, '%') + '<br>' +
            '时间进度 ' + d.tp + '% · 空间进度 ' + d.sp + '%';
        }
      },
      xAxis: {
        type: 'value', min: xmin, max: xmax, name: '当前回撤', nameLocation: 'middle', nameGap: 26,
        nameTextStyle: { color: '#8A8578', fontSize: 11 },
        axisLine: { show: false }, axisTick: { show: false },
        splitLine: { lineStyle: { color: '#F1EDE4' } },
        axisLabel: { color: '#8A8578', fontSize: 11, formatter: '{value}%' }
      },
      yAxis: {
        type: 'value', min: ymin, max: ymax,
        axisLine: { show: false }, axisTick: { show: false },
        splitLine: { lineStyle: { color: '#F1EDE4' } },
        axisLabel: { color: '#8A8578', fontSize: 11, formatter: '{value}%' }
      },
      series: [
        Object.assign(ser('中位为正', ups, '#B8402F'), {
          markLine: {
            silent: true, symbol: 'none', z: 1,
            lineStyle: { color: '#C9C2B2', type: 'dashed', width: 1 },
            label: { formatter: '五五开', color: '#A8A294', fontSize: 10, position: 'insideEndTop' },
            data: [{ yAxis: 50 }]
          }
        }),
        ser('中位为负', downs, '#2E7D5B'),
      ]
    });

    const cap = document.getElementById('ml-scap');
    if (cap && M.sector_rho) {
      const r = M.sector_rho;
      cap.innerHTML = '横轴＝当前回撤（越左跌得越深），纵轴＝模型给出的上行概率。' +
        '跌得深不等于概率高（ρ=' + fmtSigned(r.dd, 2, '') +
        '）；真正把板块拉开的是「跌幅相对自己历史的进度」（ρ=' + fmtSigned(r.space, 2, '') + '）。';
    }
  }

  // ---------- 国家队资金流 · 与指数对照 ----------
  let NSF_IDX = '沪深300';
  function renderNsf() {
    const el = document.getElementById('chart-nsf');
    if (!el) return;
    const S = W.state_score;
    const all = (S && S.nsf_all) || null;
    const idxList = all ? Object.keys(all) : ['沪深300'];
    if (idxList.indexOf(NSF_IDX) < 0) NSF_IDX = idxList[0];
    const nsf = all ? all[NSF_IDX] : (S && S.nsf);
    if (!nsf || !nsf.dates || !nsf.dates.length) {
      el.innerHTML = '<div class="desc">国家队数据未生成，运行 python3 src/build_nsf.py</div>';
      return;
    }
    const chipBox = document.getElementById('nsf-scope');
    if (chipBox) {
      chipBox.innerHTML = idxList.map(k =>
        '<button data-nsf="' + k + '"' + (k === NSF_IDX ? ' class="active"' : '') + '>' + k + '</button>').join('');
      chipBox.querySelectorAll('button').forEach(b => b.addEventListener('click', () => {
        if (b.dataset.nsf === NSF_IDX) return;
        NSF_IDX = b.dataset.nsf;
        renderNsf();
      }));
    }
    const idx = NSF_IDX;
    const k = (W.kline || {})[idx];
    const closeMap = {};
    if (k) k.dates.forEach((d, i) => { closeMap[d] = k.close[i]; });

    const dates = nsf.dates, pct = nsf.pct, amt = nsf.amt || [];
    const price = dates.map(d => (closeMap[d] == null ? null : closeMap[d]));

    const asofEl = document.getElementById('nsf-asof');
    if (asofEl) asofEl.textContent = '截至 ' + dates[dates.length - 1];

    // 默认显示近 3 年，可滚轮缩放
    const startPct = Math.max(0, Math.round((1 - 750 / dates.length) * 1000) / 10);

    const noteEl = document.getElementById('nsf-note');
    if (noteEl) {
      const cur = pct[pct.length - 1], curAmt = amt[amt.length - 1];
      const hist = pct.filter(v => v != null && !isNaN(v));
      const rank = hist.filter(v => v < cur).length / hist.length * 100;
      noteEl.innerHTML = '当前 <b>' + fmtSigned(cur, 1, '%') + '</b>' +
        '（' + fmtSigned(curAmt, 0, '') + ' 亿元）· 历史 <b>' + fmtNum(rank, 0) + '%</b> 分位。' +
        idx + ' ETF 份额变化 × 收盘价，20 日累计。';
    }

    const ch = charts['chart-nsf'] || echarts.init(el); charts['chart-nsf'] = ch;
    ch.setOption({
      textStyle: CHART_OPTS.textStyle, animation: false,
      axisPointer: { link: [{ xAxisIndex: 'all' }] },
      grid: [
        { left: 64, right: 22, top: 22, height: '40%' },
        { left: 64, right: 22, top: '60%', height: '26%' },
      ],
      tooltip: {
        trigger: 'axis', axisPointer: { type: 'cross', lineStyle: { color: 'rgba(20,19,19,.3)', type: 'dashed' } },
        backgroundColor: 'rgba(255,255,255,.98)', borderColor: C.line,
        textStyle: { color: C.ink, fontSize: 11.5 },
        formatter: function (ps) {
          if (!ps.length) return '';
          let h = '<b>' + ps[0].axisValue + '</b>';
          ps.forEach(p => {
            if (p.value == null) return;
            if (p.seriesIndex === 0) h += '<br/>' + p.marker + idx + ' ' + fmtNum(p.value, 1);
            else {
              const i = p.dataIndex;
              h += '<br/>' + p.marker + '20 日净申购 ' + fmtSigned(p.value, 1, '%') +
                (amt[i] != null ? '（' + fmtSigned(amt[i], 0, '') + ' 亿元）' : '');
            }
          });
          return h;
        },
      },
      xAxis: [
        { type: 'category', data: dates, gridIndex: 0, boundaryGap: false,
          axisLine: { lineStyle: { color: C.axis } }, axisLabel: { show: false }, axisTick: { show: false } },
        { type: 'category', data: dates, gridIndex: 1, boundaryGap: true,
          axisLine: { lineStyle: { color: C.axis } }, axisTick: { show: false },
          axisLabel: { color: C.muted, fontSize: 11, hideOverlap: true } },
      ],
      yAxis: [
        { gridIndex: 0, scale: true, splitLine: { lineStyle: { color: C.grid } },
          axisLine: { show: false }, axisLabel: { color: C.muted, fontSize: 11, formatter: v => fmtNum(v, 0) } },
        { gridIndex: 1, scale: true, splitLine: { lineStyle: { color: C.grid } },
          axisLine: { show: false }, axisLabel: { color: C.muted, fontSize: 11, formatter: v => fmtNum(v, 0) + '%' } },
      ],
      dataZoom: [{ type: 'inside', xAxisIndex: [0, 1], start: startPct, end: 100 }],
      series: [
        { name: idx, type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: price,
          showSymbol: false, connectNulls: false, z: 3,
          lineStyle: { color: C.ink, width: 1.5 }, itemStyle: { color: C.ink },
          areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(14,31,53,.13)' }, { offset: 1, color: 'rgba(14,31,53,0)' }]) } },
        { name: '20 日净申购', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: pct,
          barWidth: '62%',
          itemStyle: { color: p => (p.value >= 0 ? 'rgba(184,64,47,.72)' : 'rgba(46,125,91,.72)') },
          markLine: { silent: true, symbol: 'none', label: { show: false },
            lineStyle: { color: 'rgba(20,19,19,.28)', width: 1 }, data: [{ yAxis: 0 }] } },
      ],
    }, { notMerge: true });
  }

  // ---------- 状态打分 · 历史同档分布 ----------
  function ssDistCell(d) {
    if (!d || !d.ok) {
      return '<td class="none">n=' + (d && d.n ? d.n : 0) + '</td>';
    }
    const tip = '胜率 ' + fmtNum(d.win, 0) + '%，中位 ' + fmtSigned(d.med, 1, '%') +
      '，n=' + d.n + ' 天，' + (d.seg == null ? '—' : d.seg) + ' 段独立样本';
    return '<td class="ssd" title="' + tip + '"><b class="' + (d.med >= 0 ? 'up' : 'down') + '">' +
      fmtNum(d.win, 0) + '%</b><span>' + fmtSigned(d.med, 1, '%') + ' · ' +
      (d.seg == null ? '—' : d.seg) + '段</span></td>';
  }
  function renderStateScore() {
    const dimsEl = document.getElementById('state-dims');
    const tblEl = document.getElementById('state-table');
    if (!dimsEl || !tblEl) return;
    const S = W.state_score;
    if (!S) {
      dimsEl.innerHTML = '<div class="desc">状态打分数据未生成，运行 python3 src/build_state_score.py</div>';
      return;
    }
    const asofEl = document.getElementById('state-asof');
    if (asofEl) asofEl.textContent = '截至 ' + S.asof;

    // 全市场维度：只给分位，不合成
    dimsEl.innerHTML = (S.market || []).map(function (m) {
      const ext = (!isNil(m.pct) && (m.pct <= 5 || m.pct >= 95)) ? ' ext' : '';
      const isCnt = (m.key === 'newhl');
      const val = isCnt ? fmtSigned(m.value, 0, '') : fmtNum(m.value, 2);
      const unit = isCnt ? ' 家' : (m.unit === '%' ? '%' : '');
      const pct = isNil(m.pct) ? 0 : Math.max(2, Math.min(100, m.pct));
      const range = (isNil(m.hist_min) || isNil(m.hist_max)) ? ''
        : '<span class="ssm">历史 ' + fmtNum(m.hist_min, 1) + ' ~ ' + fmtNum(m.hist_max, 1) +
          ' · 中位 ' + fmtNum(m.hist_med, 1) + '</span>';
      const stale = m.stale ? '<span class="sswarn">数据截至 ' + m.data_asof + '，已过期</span>' : '';
      const sub = m.sub ? '<span class="ssm sssub">' + m.sub + '</span>' : '';
      return '<div class="ss-dim' + ext + '">' +
        '<span class="ssn">' + m.name + '</span>' +
        '<div class="ssv">' + val + (unit ? '<small>' + unit + '</small>' : '') + '</div>' +
        '<div class="ss-bar"><i style="width:' + pct + '%"></i>' +
        '<b style="left:calc(' + pct + '% - 1px)"></b></div>' +
        '<span class="ssm">分位 ' + (isNil(m.pct) ? '—' : fmtNum(m.pct, 0) + '%') + '</span> ' + range + sub + stale +
        '<span class="ssm" style="display:block;margin-top:2px">' + (m.desc || '') + '</span></div>';
    }).join('');

    // 指数对比表
    let h = '<table class="ss-tbl"><thead><tr>' +
      '<th>指数</th><th>距高</th><th>回撤</th><th>PB</th><th>PE</th>' +
      '<th>30 日<br><span style="font-weight:400">胜率 / 中位</span></th>' +
      '<th>60 日<br><span style="font-weight:400">胜率 / 中位</span></th>' +
      '</tr></thead><tbody>';
    (S.indices || []).forEach(function (x) {
      const c = x.cur, s = x.score;
      const bar = '<span class="pbar"><i style="width:' +
        (isNil(s.dd) ? 0 : Math.max(2, Math.min(100, s.dd))) + '%"></i></span>';
      h += '<tr>' +
        '<td class="ss-idx"><b>' + x.name + '</b><span>' + (x.desc || '') + '</span></td>' +
        '<td class="' + (c.dd250 <= -30 ? 'down' : '') + '">' + fmtSigned(c.dd250, 1, '%') + '</td>' +
        '<td>' + bar + (isNil(s.dd) ? '<span class="none">—</span>' : fmtNum(s.dd, 0) + '%') + '</td>' +
        '<td>' + (isNil(s.pb_pct) ? '<span class="none">—</span>' : fmtNum(s.pb_pct, 0)) + '</td>' +
        '<td>' + (isNil(s.pe_pct) ? '<span class="none">—</span>' : fmtNum(s.pe_pct, 0)) + '</td>' +
        ssDistCell(x.d30) + ssDistCell(x.d60) + '</tr>';
    });
    h += '</tbody></table>' +
      '<div class="ss-note">回撤分位越低越极端。"同档"＝历史上回撤幅度相近（±7.5pp）的日子，其后续 30/60 日涨跌；' +
      '段数是独立片段数——几千天如果只落在同几轮熊市里，那其实只有几个样本。</div>';
    tblEl.innerHTML = h;
  }

  function renderMacroCorr() {
    const body = document.getElementById('macro-corr-body');
    if (!body || body.dataset.done) return;
    const mc = W.macro_corr;
    if (!mc) { body.innerHTML = '<div class="desc">相关性数据未生成</div>'; return; }
    body.dataset.done = '1';
    const rows = mc.rows || [];
    let html = '<div class="corr-concl">';
    (mc.conclusion || []).forEach(t => { html += '<div class="cc-item">' + t + '</div>'; });
    html += '</div>';
    html += '<div class="corr-tbl-wrap"><table class="phase-tbl"><tr><th>指标</th><th class="num">牛均值</th><th class="num">熊均值</th><th class="num">同步相关</th><th class="num">领先6月</th><th class="num">区分度d</th></tr>';
    rows.forEach(r => {
      const role = (r.r_sync > 0.15 ? 'up' : (r.r_sync < -0.15 ? 'down' : ''));
      html += '<tr><td>' + r.name + '</td><td class="num">' + fmtNum(r.bull_mean, 2) + '</td><td class="num">' + fmtNum(r.bear_mean, 2) + '</td>' +
        '<td class="num ' + role + '">' + fmtSigned(r.r_sync, 2) + '</td>' +
        '<td class="num">' + fmtSigned(r.r_lead6, 2) + '</td>' +
        '<td class="num">' + fmtSigned(r.d, 2) + '</td></tr>';
    });
    html += '</table></div>';
    body.innerHTML = html;
  }

  function renderMacro() {
    const grid = document.getElementById('macro-grid');
    if (!grid) return;
    if (grid.dataset.done) return;
    // 相关性汇总
    renderMacroCorr();
    const m = W.macro;
    if (!m) { grid.innerHTML = '<div class="empty">宏观数据未加载</div>'; return; }
    grid.dataset.done = '1';
    const meta = document.getElementById('macro-meta');
    const corrAsof = document.getElementById('macro-corr-asof');
    if (corrAsof) corrAsof.textContent = '截至 ' + (m.updated || W.asof);
    let k = 0;
    const pending = [];
    m.sections.forEach(sec => {
      const h = document.createElement('div');
      h.className = 'macro-section-title';
      h.textContent = sec.name;
      grid.appendChild(h);
      sec.items.forEach(it => {
        k++;
        const cid = 'macro-' + k;
        const card = document.createElement('div');
        card.className = 'chart-card';
        const _lastLabel = (it.labels && it.labels.length) ? it.labels[it.labels.length - 1] : '';
        card.innerHTML = '<div class="card-head"><h2>' + it.title +
          (it.unit ? ' <span class="unit">' + it.unit + '</span>' : '') + '</h2>' +
          (_lastLabel ? '<span class="asof">截至 ' + _lastLabel + '</span>' : '') + '</div>' +
          '<div class="chart small" id="' + cid + '"></div>';
        grid.appendChild(card);
        pending.push({ cid: cid, it: it });
      });
    });
    // 卡片全部插入后再初始化，避免 auto-fit 空列折叠时按整行宽度建图
    pending.forEach(function (p) {
      const it = p.it;
      buildChart(p.cid, {
        cycleSegs: W.index_cycles[SCOPE.index],
        decimals: it.unit === '%' ? 1 : 0,
        data: { dates: it.labels, series: it.series.map(sr => ({ name: sr.name, values: sr.values })) },
        unit: it.unit,
      });
    });
    if (meta) meta.textContent = SCOPE.index + ' 牛熊分段 · ' + k + ' 项 · 截至 ' + (m.updated || W.asof);
  }

  // 长周期指数口径：上证 2004 起 / 沪深300 2005 起
  // ---------- 模型面板：排名 / 生存 / 转移 / 变点 ----------
  function renderModels() {
    const M = W.models_extra;
    const tilesEl = document.getElementById('mp-tiles');
    if (!tilesEl) return;
    if (!M) {
      tilesEl.innerHTML = '<div class="desc">模型面板未生成，运行 python3 src/build_models_extra.py</div>';
      return;
    }
    const ae = document.getElementById('mp-asof');
    if (ae) ae.textContent = '截至 ' + M.asof;

    const en = M.ensemble || {}, tr = M.transition || {}, sv = M.survival || {},
      rk = M.risk || {}, by = M.bayes || {};
    // VaR 只在已生成风险的指数里选：优先当前基准，其次创业板指
    const rkName = rk[SCOPE.index] ? SCOPE.index : (rk['创业板指'] ? '创业板指' : Object.keys(rk)[0]);
    const r0 = (rkName && rk[rkName]) || {};
    const tiles = [
      ['集成分', en.score == null ? '—' : fmtNum(en.score, 1), '/100'],
      ['20 日转牛概率', tr.p_bull_20 == null ? '—' : fmtNum(tr.p_bull_20 * 100, 0), '%'],
      ['中位剩余', sv.median_remaining == null ? '—' : sv.median_remaining, '日'],
      ['20 日 VaR95 · ' + (rkName || '—'), r0.var95 == null ? '—' : fmtSigned(r0.var95, 1, '%'), ''],
      ['贝叶斯后验', by.posterior == null ? '—' : fmtSigned(by.posterior, 1, '%'), ''],
    ];
    tilesEl.innerHTML = tiles.map(t =>
      '<div class="mp-tile"><span>' + t[0] + '</span><b>' + t[1] +
      '<small>' + t[2] + '</small></b></div>').join('');

    // 排名
    const items = ((M.rank || {}).indices || []).slice();
    if (items.length) {
      const el = document.getElementById('mp-rank');
      if (el) {
        if (charts['mp-rank']) charts['mp-rank'].dispose();
        const ch = echarts.init(el); charts['mp-rank'] = ch;
        const sorted = items.slice().sort((a, b) => a.score - b.score);
        ch.setOption({
          animation: false,
          grid: { left: 8, right: 26, top: 8, bottom: 8, containLabel: true },
          tooltip: { trigger: 'item', backgroundColor: '#fff', borderColor: '#E6E1D6', borderWidth: 1,
            textStyle: { color: '#141313', fontSize: 12.5 },
            formatter: p => '<b>' + p.name + '</b><br>相对强弱得分 ' + fmtNum(p.value, 1) },
          xAxis: { type: 'value', min: 0, max: 100, splitLine: { lineStyle: { color: '#F1EDE4' } },
            axisLabel: { color: '#8A8578', fontSize: 11 } },
          yAxis: { type: 'category', data: sorted.map(x => x.name), axisTick: { show: false },
            axisLine: { show: false }, axisLabel: { color: '#37342F', fontSize: 12 } },
          series: [{
            type: 'bar', data: sorted.map(x => x.score), barWidth: 9,
            itemStyle: { color: '#A8875B', borderRadius: [0, 2, 2, 0] },
            label: { show: true, position: 'right', fontSize: 10.5, color: '#8A8578',
              formatter: p => fmtNum(p.value, 0) }
          }]
        });
      }
    }

    // 生存曲线
    if (sv.days && sv.days.length) {
      const el = document.getElementById('mp-surv');
      if (el) {
        if (charts['mp-surv']) charts['mp-surv'].dispose();
        const ch = echarts.init(el); charts['mp-surv'] = ch;
        ch.setOption({
          animation: false,
          grid: { left: 8, right: 18, top: 16, bottom: 4, containLabel: true },
          tooltip: { trigger: 'axis', backgroundColor: '#fff', borderColor: '#E6E1D6', borderWidth: 1,
            textStyle: { color: '#141313', fontSize: 12.5 },
            formatter: ps => { const i = ps[0].dataIndex; return sv.days[i] + ' 日<br>仍有 <b>' +
              fmtNum(sv.surv[i] * 100, 0) + '%</b> 的熊市未结束'; } },
          xAxis: { type: 'category', data: sv.days, boundaryGap: false,
            axisLabel: { color: '#8A8578', fontSize: 11, interval: 9, formatter: v => v + '日' },
            axisLine: { lineStyle: { color: '#E6E1D6' } }, axisTick: { show: false } },
          yAxis: { type: 'value', min: 0, max: 1, axisLabel: { color: '#8A8578', fontSize: 11, formatter: v => (v * 100) + '%' },
            splitLine: { lineStyle: { color: '#F1EFE8' } }, axisLine: { show: false } },
          series: [{
            type: 'line', data: sv.surv, symbol: 'none', smooth: false,
            lineStyle: { color: '#0E1F35', width: 2 }, areaStyle: { color: 'rgba(14,31,53,0.05)' },
            markLine: sv.current_days == null ? undefined : {
              silent: true, symbol: 'none',
              lineStyle: { color: '#B8402F', type: 'dashed', width: 1 },
              label: { formatter: '当前 ' + sv.current_days + ' 日', color: '#B8402F', fontSize: 10, position: 'insideEndTop' },
              data: [{ xAxis: Math.round(sv.current_days / 20) }]
            }
          }]
        });
      }
    }

    // 转移概率
    if (tr.curve && tr.curve.length) {
      const el = document.getElementById('mp-trans');
      if (el) {
        if (charts['mp-trans']) charts['mp-trans'].dispose();
        const ch = echarts.init(el); charts['mp-trans'] = ch;
        ch.setOption({
          animation: false,
          grid: { left: 8, right: 14, top: 18, bottom: 4, containLabel: true },
          tooltip: { trigger: 'item', backgroundColor: '#fff', borderColor: '#E6E1D6', borderWidth: 1,
            textStyle: { color: '#141313', fontSize: 12.5 },
            formatter: p => p.name + '<br>转牛概率 <b>' + fmtNum(p.value, 0) + '%</b>' },
          xAxis: { type: 'category', data: tr.curve.map(x => x.bucket),
            axisLabel: { color: '#8A8578', fontSize: 10.5 }, axisTick: { show: false },
            axisLine: { lineStyle: { color: '#E6E1D6' } } },
          yAxis: { type: 'value', axisLabel: { color: '#8A8578', fontSize: 11, formatter: '{value}%' },
            splitLine: { lineStyle: { color: '#F1EFE8' } }, axisLine: { show: false } },
          series: [{
            type: 'bar', barWidth: 26,
            data: tr.curve.map(x => ({
              value: (x.p * 100), name: x.bucket,
              itemStyle: { color: (x.bucket === tr.current_bucket) ? '#B8402F' : '#D8C9AE' }
            })),
            label: { show: true, position: 'top', fontSize: 10.5, color: '#8A8578', formatter: p => fmtNum(p.value, 0) + '%' }
          }]
        });
      }
    }

    // 变点强度
    const cp = M.changepoint;
    if (cp && cp.series && cp.series.length) {
      const el = document.getElementById('mp-cp');
      if (el) {
        if (charts['mp-cp']) charts['mp-cp'].dispose();
        const ch = echarts.init(el); charts['mp-cp'] = ch;
        ch.setOption({
          animation: false,
          grid: { left: 8, right: 14, top: 18, bottom: 4, containLabel: true },
          tooltip: { trigger: 'axis', backgroundColor: '#fff', borderColor: '#E6E1D6', borderWidth: 1,
            textStyle: { color: '#141313', fontSize: 12.5 },
            formatter: ps => { const i = ps[0].dataIndex; const d = cp.series[i];
              return d.date + '<br>强度 <b>' + d.p + '</b>（z=' + d.z + '）'; } },
          xAxis: { type: 'category', data: cp.series.map(x => x.date),
            axisLabel: { color: '#8A8578', fontSize: 10.5, interval: 60 },
            axisTick: { show: false }, axisLine: { lineStyle: { color: '#E6E1D6' } } },
          yAxis: { type: 'value', min: 0, max: 1, axisLabel: { color: '#8A8578', fontSize: 11 },
            splitLine: { lineStyle: { color: '#F1EFE8' } }, axisLine: { show: false } },
          series: [{
            type: 'line', data: cp.series.map(x => x.p), symbol: 'none',
            lineStyle: { color: '#A8875B', width: 1.6 }, areaStyle: { color: 'rgba(168,135,91,0.10)' },
            markLine: { silent: true, symbol: 'none',
              lineStyle: { color: '#C9C2B2', type: 'dashed', width: 1 },
              label: { formatter: '0.5', color: '#A8A294', fontSize: 10 },
              data: [{ yAxis: 0.5 }] }
          }]
        });
      }
    }
  }

  function renderLongIndicators() {
    const grid = document.getElementById('ind-long');
    if (!grid) return;
    disposeChartsIn(grid);
    grid.innerHTML = '';
    const ih = W.index_history || {};
    const has = !!ih[SCOPE.index];
    const name = has ? SCOPE.index : '上证指数';
    const h = ih[name];
    const head = document.getElementById('ind-long-head');
    const startY = (h && h.dates && h.dates[0] || '').slice(0, 4);
    if (head) head.innerHTML = '<b>长周期 · ' + name + '</b><span>' +
      (has ? startY + ' 起 · 周频 · 指数口径' + (h && h.proj_start ? ' · ' + h.proj_start + ' 起为价格推算' : '') : '暂无' + SCOPE.index + '估值数据 · 暂以上证指数替代') + '</span>';
    if (!h || !h.dates || !h.dates.length) { grid.innerHTML = '<div class="empty-ind">长周期数据未加载</div>'; return; }
    const ITEMS = [
      { key: 'pe', title: 'PE(TTM)（倍）', unit: '', dec: 2 },
      { key: 'pb', title: 'PB（倍）', unit: '', dec: 2 },
      { key: 'turnover', title: '换手率（%）', unit: '%', dec: 2 },
    ];
    const asof = h.dates[h.dates.length - 1];
    ITEMS.forEach(function (it) {
      const box = document.createElement('div'); box.className = 'chart-card';
      box.innerHTML = '<div class="card-head"><h2>' + it.title + '</h2><span class="asof">截至 ' + asof + '</span></div>' +
        '<div class="chart small" id="ind-long-' + it.key + '"></div>';
      grid.appendChild(box);
      buildChart('ind-long-' + it.key, {
        showPct: true, hidePctStats: true, cycleShade: true, cycleSegs: W.index_cycles[name], decimals: it.dec,
        data: { dates: h.dates, series: [{ name: it.title, values: h[it.key], color: C.accentD }] },
        unit: it.unit, area: true,
      });
    });
  }

  function renderIndicators() {
    const grid = document.getElementById('ind-grid');
    disposeChartsIn(grid);
    grid.innerHTML = '';
    const INDS = [
      { key: 'margin', title: '融资余额 / A股总市值（%）', unit: '%', dec: 2 },
      { key: 'amount_ratio', title: '全A成交额占A股总市值（%）', unit: '%', dec: 2 },
      { key: 'concentration', title: '成交集中度（前5%占比 %）', unit: '%', dec: 1 },
      { key: 'pe', title: '全A PE中位数（倍）', unit: '', dec: 2, showPct: true },
      { key: 'pb', title: '全A PB中位数（倍）', unit: '', dec: 2, showPct: true },
      { key: 'limit', title: '涨停家数（家/日）', unit: '', dec: 0 },
      { key: 'above200', title: '200日均线上方占比（%）', unit: '%', dec: 1 },
      { key: 'newhigh', title: '52周新高家数（家/日）', unit: '', dec: 0 },
      { key: 'newlow', title: '52周新低家数（家/日）', unit: '', dec: 0 },
      { key: 'turnover', title: '换手率中位数（%）', unit: '%', dec: 2 },
      { key: 'breadth', title: '上涨家数占比（%）', unit: '%', dec: 1 },
      { key: 'hk', title: '港股通持股（亿股）', unit: '亿股', dec: 0 },
      { key: 'ipo', title: 'IPO 数量（家/月）', unit: '', dec: 0 },
      { key: 'holder', title: '股东净减持（亿元/月）', unit: '', dec: 0 },
    ];
    // 先把所有卡片插入 DOM，再初始化图表：
    // auto-fit 网格在只有一张卡片时会把空列折叠，先建图会按整行宽度初始化
    const pending = [];
    INDS.forEach(function (ind) {
      const d = (ind.key === 'ipo' || ind.key === 'holder') ? (window.WAW.extra && window.WAW.extra[ind.key]) : W.indicators[ind.key];
      const box = document.createElement('div'); box.className = 'chart-card';
      const has = d && d.dates && d.dates.length;
      const _asof = has ? d.dates[d.dates.length - 1] : '';
      box.innerHTML = '<div class="card-head"><h2>' + ind.title + '</h2>' +
        (has ? '<span class="asof">截至 ' + _asof + '</span>' : '') + '</div>' +
        (has ? '<div class="chart small" id="ind-' + ind.key + '"></div>' : '<div class="empty-ind">本地未接入该指标</div>');
      grid.appendChild(box);
      if (has) pending.push({ ind: ind, d: d });
    });
    pending.forEach(function (p) {
      buildChart('ind-' + p.ind.key, {
        showPct: !!p.ind.showPct, cycleShade: true, decimals: p.ind.dec,
        data: { dates: p.d.dates, series: [{ name: p.ind.title, values: p.d.values, color: C.accentD }] },
        unit: p.ind.unit, area: true,
      });
    });
  }

  // ---------- 初始化 ----------
  renderScopeBar();
  renderHeroChart();
  renderCycleTabs();
  renderCycleOverview();
  histCycle = null;   // 默认「全历史」：主图完整历史 + 区间统计
  window.addEventListener('resize', function () {
    Object.values(charts).forEach(c => c.resize());
    updateCycleLens(true);
  });
  // 滚动联动：只改当前分段，rAF 节流
  window.addEventListener('scroll', function () {
    if (lensRaf) return;
    lensRaf = requestAnimationFrame(function () { lensRaf = null; updateCycleLens(false); });
  }, { passive: true });
  function parseAppHash() {
    const h = (location.hash || '').replace('#', '');
    if (h.indexOf('cycle/') === 0) {
      const id = h.slice(6);
      if (W.cycles.some(c => c.id === id)) { detailCycleId = id; histCycle = id; go('cycle'); }
      else go('history');
      return true;
    }
    if (['intro', 'history', 'current', 'trends', 'macro', 'academy'].indexOf(h) >= 0) { go(h); return true; }
    return false;
  }
  window.addEventListener('hashchange', parseAppHash);
  // 面板「指标说明 / 模型说明」展开收起（事件委托，支持动态渲染出来的按钮）
  document.addEventListener('click', function (e) {
    var btn = e.target && e.target.closest ? e.target.closest('[data-guide]') : null;
    if (!btn) return;
    var g = document.getElementById('guide-' + btn.dataset.guide);
    if (!g) return;
    var willOpen = g.hidden;
    g.hidden = !willOpen;
    btn.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
  });

  // 锚点链接（进入当前观察 / 股票卡 / 侧链）直接绑定，确保点击必跳
  $$('a[href^="#"]').forEach(function (a) {
    a.addEventListener('click', function (e) {
      const h = (a.getAttribute('href') || '').replace('#', '');
      if (h.indexOf('cycle/') === 0) {
        const id = h.slice(6);
        if (W.cycles.some(c => c.id === id)) { e.preventDefault(); detailCycleId = id; histCycle = id; go('cycle'); }
        return;
      }
      if (['intro', 'history', 'current', 'trends', 'macro', 'academy'].indexOf(h) >= 0) { e.preventDefault(); go(h); }
    });
  });

  // 区间/频度段：当前观察主图 + 指标图的区间按钮统一绑定（buildChart 内已绑）
  // hash 直达
  (function () {
    if (!parseAppHash()) {
      const h = (location.hash || '').replace('#', '');
      if (!h && new URLSearchParams(location.search).get('to') === 'macro') go('macro');
    }
  })();
})();
