# -*- coding: utf-8 -*-
"""构建「回调 / 反弹」期间的板块与个股 Top10。

数据源（全部本地，不访问网络）：
  - /Users/kunrongcai/Desktop/A股数据/panel_csi_all_full.parquet  个股复权日线，2016-01-04 → 2026-08-28
  - /Users/kunrongcai/Desktop/A股数据/stock_basic_all.csv          当前股票名称/行业/上市日
  - cache/cycle_analysis.json                                      中证500 的 ≥10% 回调/反弹窗口

输出 web/pullback_stats.js（window.WAW.pullback_stats）。

口径与限制：
  - 仅覆盖 2016 年及以后的周期；2005–2008、2013–2015 无本地全市场日线，标记 unavailable。
  - 行业为本地 110 个细分行业（东财口径），个股等权；样本 <5 只的行业不排名。
  - 剔除当前名称含 ST/*ST/退 的股票；本地面板不含已退市股票（幸存者偏差）。
  - 牛市回调窗口：中证500 收盘价回撤 ≥10%；熊市反弹窗口：中证500 收盘价反弹 ≥10%；
    若该轮熊市无 ≥10% 反弹，回退创业板指。窗口与 web/cycle_analysis.js 完全一致。
  - 个股复权价 close；剔除窗口起点后上市的新股。
"""
import json
import os
from datetime import datetime

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = '/Users/kunrongcai/Desktop/A股数据'
PANEL = os.path.join(DATA, 'panel_csi_all_full.parquet')
BASIC = os.path.join(DATA, 'stock_basic_all.csv')
ANALYSIS = os.path.join(ROOT, 'cache', 'cycle_analysis.json')
OUT_JSON = os.path.join(ROOT, 'cache', 'pullback_stats.json')
OUT_JS = os.path.join(ROOT, 'web', 'pullback_stats.js')


def _panel_last():
    """本地个股面板的最后日期（跟随面板更新，不用手改常量）。"""
    try:
        d = pd.read_parquet(PANEL, columns=['date'])['date']
        return str(pd.to_datetime(d).max().date())
    except Exception:
        return '2026-08-28'


LOCAL_END = _panel_last()
MIN_STOCKS = 5

CYCLES = [
    {'id': 'c0508', 'name': '2005–2008', 'bull': ('2005-06-06', '2007-10-16'), 'bear': ('2007-10-16', '2008-10-28'), 'available': False},
    {'id': 'c1315', 'name': '2013–2015', 'bull': ('2012-12-04', '2015-06-12'), 'bear': ('2015-06-12', '2016-01-27'), 'available': False},
    {'id': 'c1618', 'name': '2016–2018', 'bull': ('2016-01-27', '2018-01-26'), 'bear': ('2018-01-26', '2019-01-04'), 'available': True},
    {'id': 'c1921', 'name': '2019–2021', 'bull': ('2019-01-04', '2021-02-18'), 'bear': ('2021-02-18', '2022-04-27'), 'available': True},
    {'id': 'c24now', 'name': '2024–至今', 'bull': ('2024-02-05', '2026-05-13'), 'bear': ('2026-05-13', LOCAL_END), 'available': True},
]


def ts(s):
    return pd.Timestamp(s)


def load_basic():
    b = pd.read_csv(BASIC, dtype={'ts_code': str})
    b = b[b['ts_code'].str.endswith(('.SH', '.SZ'))].copy()
    b['name'] = b['name'].fillna('').astype(str).str.strip()
    b['industry'] = b['industry'].fillna('').astype(str).str.strip()
    b['list_date'] = pd.to_numeric(b['list_date'], errors='coerce').fillna(0).astype(int)
    b = b[~b['name'].str.upper().str.contains('ST')]
    b = b[~b['name'].str.contains('退')]
    b = b.set_index('ts_code')
    print('股票基础:', len(b), '只（已剔除 ST/退市名称）', flush=True)
    return b


def load_panel(dates):
    px = pd.read_parquet(PANEL, columns=['ticker', 'date', 'close'])
    px = px[px['date'].isin([ts(d) for d in dates])]
    w = px.pivot(index='ticker', columns='date', values='close')
    print('价格矩阵:', w.shape, '| 日期', len(dates), flush=True)
    return w


def ret_series(wide, basic, start, end):
    a, b = ts(start), ts(end)
    if a not in wide.columns or b not in wide.columns:
        return pd.Series(dtype=float)
    v0, v1 = wide[a], wide[b]
    ok = v0.notna() & v1.notna() & (v0 > 0) & (v1 > 0)
    r = (v1[ok] / v0[ok] - 1) * 100
    r = r[r.index.isin(basic.index)]
    meta = basic.loc[r.index]
    # 窗口起点后上市的新股剔除
    ld = meta['list_date'].astype(str)
    keep = ld < start.replace('-', '')
    r = r[keep]
    meta = basic.loc[r.index]
    return pd.DataFrame({'ret': r.round(2), 'name': meta['name'], 'industry': meta['industry'],
                         'code': r.index})


def industry_rank(df):
    rows = []
    for name, g in df[df['industry'] != ''].groupby('industry'):
        if len(g) < MIN_STOCKS:
            continue
        rows.append({'name': name, 'ret': round(float(g['ret'].mean()), 2), 'n': int(len(g))})
    return sorted(rows, key=lambda x: x['ret'], reverse=True)


def top_stocks(df, asc=False):
    d = df.sort_values('ret', ascending=asc).head(10)
    return [{'code': r.code, 'name': r.name, 'industry': r.industry, 'ret': float(r.ret)}
            for r in d.itertuples()]


def phase_rank(wide, basic, start, end):
    df = ret_series(wide, basic, start, end)
    inds = industry_rank(df)
    return {
        'start': start, 'end': end,
        'industries': inds[:10], 'industries_bottom': list(reversed(inds[-10:])),
        'stocks': top_stocks(df), 'stocks_bottom': top_stocks(df, asc=True),
        'n_stocks': int(len(df)), 'median': round(float(df['ret'].median()), 2) if len(df) else None,
        'avg': round(float(df['ret'].mean()), 2) if len(df) else None,
    }


def episode_rows(wide, basic, ep, leader_inds, leader_codes, worst_inds, worst_codes, kind):
    """kind=bull: 回调，取跌幅前10；kind=bear: 反弹，取涨幅前10。"""
    start, end = ep['start'], ep['end']
    df = ret_series(wide, basic, start, end)
    inds = industry_rank(df)
    if kind == 'bull':
        inds_sel = sorted(inds, key=lambda x: x['ret'])[:10]
        stocks_sel = top_stocks(df, asc=True)
    else:
        inds_sel = inds[:10]
        stocks_sel = top_stocks(df)
    for x in inds_sel:
        x['leader'] = x['name'] in leader_inds
        x['worst'] = x['name'] in worst_inds
    for x in stocks_sel:
        x['leader'] = x['code'] in leader_codes
        x['worst'] = x['code'] in worst_codes
    return {
        'start': start, 'end': end, 'pct': ep['pct'], 'days': ep['days'],
        'industries': inds_sel, 'stocks': stocks_sel,
        'n_stocks': int(len(df)),
        'avg': round(float(df['ret'].mean()), 2) if len(df) else None,
        'up_ratio': round(float((df['ret'] > 0).mean() * 100), 1) if len(df) else None,
    }


def episodes_for(analysis, cid, phase):
    proc = analysis['cycles'][cid][phase].get('中证500')
    proxy = '中证500'
    if not proc or not proc.get('episodes'):
        proc = analysis['cycles'][cid][phase].get('创业板指')
        proxy = '创业板指'
    if not proc:
        return None, None
    rows = []
    for e in proc.get('episodes') or []:
        if phase == 'bull':
            start, end = e.get('peak'), e.get('trough')
        else:
            start, end = e.get('trough'), e.get('peak')
        rows.append({'start': start, 'end': end, 'pct': e.get('pct'), 'days': e.get('days')})
    return rows, proxy


def main():
    analysis = json.load(open(ANALYSIS))
    basic = load_basic()
    dates = set()
    for cy in CYCLES:
        if not cy['available']:
            continue
        dates.update([cy['bull'][0], cy['bull'][1], cy['bear'][0], cy['bear'][1]])
        for phase in ('bull', 'bear'):
            eps, _ = episodes_for(analysis, cy['id'], phase)
            for e in eps or []:
                dates.update([e['start'], e['end']])
    wide = load_panel(sorted(dates))

    out = {
        'asof': LOCAL_END,
        'proxy': '中证500',
        'min_stocks': MIN_STOCKS,
        'method': {
            'industry': '本地110个细分行业，个股等权，样本少于5只不排名',
            'stock': '沪深A股复权价，剔除ST/退市名称与窗口内上市新股',
            'window': '牛市回调=中证500收盘回撤≥10%；熊市反弹=中证500收盘反弹≥10%，无则回退创业板指',
        },
        'cycles': {},
    }

    for cy in CYCLES:
        item = {'name': cy['name'], 'bull': {}, 'bear': {}}
        if not cy['available']:
            reason = '本地全市场日线自 2016 年起，该轮无行业/个股日频数据；需 Tushare 全历史日线与历史行业成员'
            item['unavailable'] = reason
            item['bull']['unavailable'] = reason
            item['bear']['unavailable'] = reason
            out['cycles'][cy['id']] = item
            continue

        bull_full = phase_rank(wide, basic, *cy['bull'])
        bear_full = phase_rank(wide, basic, *cy['bear'])
        bull_leaders = {x['name'] for x in bull_full['industries']}
        bull_leader_codes = {x['code'] for x in bull_full['stocks']}
        bear_worst = {x['name'] for x in bear_full['industries_bottom']}
        bear_worst_codes = {x['code'] for x in bear_full['stocks_bottom']}

        for phase, kind, l_inds, l_codes, w_inds, w_codes in (
            ('bull', 'bull', bull_leaders, bull_leader_codes, set(), set()),
            ('bear', 'bear', bull_leaders, bull_leader_codes, bear_worst, bear_worst_codes),
        ):
            eps, proxy = episodes_for(analysis, cy['id'], phase)
            item[phase] = {
                'proxy': proxy,
                'start': cy[phase][0], 'end': cy[phase][1],
                'full': bull_full if phase == 'bull' else bear_full,
                'episodes': [episode_rows(wide, basic, e, l_inds, l_codes, w_inds, w_codes, kind) for e in (eps or [])],
            }
        if cy['id'] == 'c24now':
            item['bear']['note'] = ('本地个股/行业数据截至 %s，熊市全段排名按该日截止' % LOCAL_END)
        out['cycles'][cy['id']] = item
        print(cy['id'], 'bull eps', len(item['bull']['episodes']), 'bear eps', len(item['bear']['episodes']), flush=True)

    json.dump(out, open(OUT_JSON, 'w'), ensure_ascii=False, indent=1)
    js = ('/* generated by src/build_pullback_stats.py — do not edit */\n'
          'window.WAW=window.WAW||{};window.WAW.pullback_stats='
          + json.dumps(out, ensure_ascii=False, separators=(',', ':')) + ';\n')
    open(OUT_JS, 'w').write(js)
    print('写出:', OUT_JSON)
    print('写出:', OUT_JS)


if __name__ == '__main__':
    main()
