# -*- coding: utf-8 -*-
"""构建「全指数 × 牛熊阶段」对比统计。

只依赖本地 web/data-kline.js（日线 OHLC，至 2026-11-13），不访问网络。
输出 web/cycle_analysis.js（window.WAW.cycle_analysis）。

口径：
  - 牛市起点、熊市终点沿用周期名义日期；各指数用自身最高点切分牛熊。
  - 指数在阶段起点尚未成立时，该阶段留空（不强行统计）。
  - 涨幅 = 起点收盘 → 区间最高价；跌幅 = 区间最高价 → 终点收盘。
  - 回撤/反弹次数按收盘价 ZigZag 统计，阈值 10%，区间不重叠。
  - 历时按交易日数；同时给出自然月，便于展示。
"""
import json
import os
import re
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KLINE_JS = os.path.join(ROOT, 'web', 'data-kline.js')
OUT_JSON = os.path.join(ROOT, 'cache', 'cycle_analysis.json')
OUT_JS = os.path.join(ROOT, 'web', 'cycle_analysis.js')

INDEX_LIST = ['上证指数', '沪深300', '创业板指', '中证500', '中证1000', '中证2000', '科创50']
THRESHOLD = 0.10
ASOF = '2026-11-13'

CYCLES = [
    {'id': 'c0508', 'name': '2005–2008', 'bull': ('2005-06-06', '2007-10-16'), 'bear': ('2007-10-16', '2008-10-28'), 'ongoing': False},
    {'id': 'c1315', 'name': '2013–2015', 'bull': ('2012-12-04', '2015-06-12'), 'bear': ('2015-06-12', '2016-01-27'), 'ongoing': False},
    {'id': 'c1618', 'name': '2016–2018', 'bull': ('2016-01-27', '2018-01-26'), 'bear': ('2018-01-26', '2019-01-04'), 'ongoing': False},
    {'id': 'c1921', 'name': '2019–2021', 'bull': ('2019-01-04', '2021-02-18'), 'bear': ('2021-02-18', '2022-04-27'), 'ongoing': False},
    {'id': 'c24now', 'name': '2024–至今', 'bull': ('2024-02-05', '2026-05-13'), 'bear': ('2026-05-13', ASOF), 'ongoing': True},
]


def load_kline():
    s = open(KLINE_JS, encoding='utf-8').read()
    i = s.index('window.WAW_KLINE=') + len('window.WAW_KLINE=')
    return json.loads(s[i:].rstrip().rstrip(';'))


def days_between(a, b):
    return (datetime.strptime(b, '%Y-%m-%d') - datetime.strptime(a, '%Y-%m-%d')).days


def months_between(a, b):
    return round(days_between(a, b) / 30.44, 1)


def slice_range(kd, start, end):
    ds = kd['dates']
    lo, hi = 0, len(ds)
    while lo < len(ds) and ds[lo] < start:
        lo += 1
    hi = lo
    while hi < len(ds) and ds[hi] <= end:
        hi += 1
    return lo, hi


def down_episodes(ds, cs, th=THRESHOLD):
    """收盘价回撤 >= th 的不重叠区段。返回峰值日、谷值日、幅度、交易日。"""
    out = []
    if not cs:
        return out
    peak_i = 0
    in_ep = False
    ep_peak = 0
    trough_i = 0
    trough_v = cs[0]
    for i, v in enumerate(cs):
        if not in_ep:
            if v > cs[peak_i]:
                peak_i = i
            if cs[peak_i] > 0 and v / cs[peak_i] - 1 <= -th:
                in_ep, ep_peak, trough_i, trough_v = True, peak_i, i, v
        else:
            if v < trough_v:
                trough_v, trough_i = v, i
            if v >= cs[ep_peak]:
                out.append(ep(ep_peak, trough_i, cs, ds, 'dd'))
                in_ep = False
                peak_i = i
    if in_ep:
        out.append(ep(ep_peak, trough_i, cs, ds, 'dd'))
    return out


def up_episodes(ds, cs, th=THRESHOLD):
    """收盘价反弹 >= th 的不重叠区段。"""
    out = []
    if not cs:
        return out
    low_i = 0
    in_ep = False
    ep_low = 0
    peak_i = 0
    peak_v = cs[0]
    for i, v in enumerate(cs):
        if not in_ep:
            if v < cs[low_i]:
                low_i = i
            if cs[low_i] > 0 and v / cs[low_i] - 1 >= th:
                in_ep, ep_low, peak_i, peak_v = True, low_i, i, v
        else:
            if v > peak_v:
                peak_v, peak_i = v, i
            if v <= cs[ep_low]:
                out.append(ep(ep_low, peak_i, cs, ds, 'rb'))
                in_ep = False
                low_i = i
    if in_ep:
        out.append(ep(ep_low, peak_i, cs, ds, 'rb'))
    return out


def ep(a, b, cs, ds, kind):
    if kind == 'dd':
        return {
            'peak': ds[a], 'trough': ds[b],
            'pct': round((cs[b] / cs[a] - 1) * 100, 2),
            'days': b - a,
        }
    return {
        'trough': ds[a], 'peak': ds[b],
        'pct': round((cs[b] / cs[a] - 1) * 100, 2),
        'days': b - a,
    }


def max_drawdown(ds, cs):
    peak_i = 0
    best = None
    for i, v in enumerate(cs):
        if v > cs[peak_i]:
            peak_i = i
        dd = v / cs[peak_i] - 1 if cs[peak_i] else 0
        if best is None or dd < best['dd']:
            best = {'dd': dd, 'peak_i': peak_i, 'trough_i': i}
    if not best or best['dd'] >= 0:
        return None
    return {
        'pct': round(best['dd'] * 100, 2),
        'peak': ds[best['peak_i']], 'trough': ds[best['trough_i']],
        'days': best['trough_i'] - best['peak_i'],
    }


def max_rebound(ds, cs):
    low_i = 0
    best = None
    for i, v in enumerate(cs):
        if v < cs[low_i]:
            low_i = i
        gain = v / cs[low_i] - 1 if cs[low_i] else 0
        if best is None or gain > best['gain']:
            best = {'gain': gain, 'low_i': low_i, 'peak_i': i}
    if not best or best['gain'] <= 0:
        return None
    return {
        'pct': round(best['gain'] * 100, 2),
        'trough': ds[best['low_i']], 'peak': ds[best['peak_i']],
        'days': best['peak_i'] - best['low_i'],
    }


def index_phase(kd, start, end, kind, ongoing=False):
    """kind=bull: 起点→自身最高；kind=bear: 自身最高→终点。"""
    ds, hi, lo, cl = kd['dates'], kd['high'], kd['low'], kd['close']
    lo_i, hi_i = slice_range(kd, start, end)
    if hi_i - lo_i < 2:
        return None
    if kind == 'bull':
        # 最高价所在日作为该指数自己的牛市终点
        seg = range(lo_i, hi_i)
        peak_i = max(seg, key=lambda i: hi[i] if hi[i] is not None else -1)
        if peak_i <= lo_i:
            return None
        cs = [cl[i] for i in range(lo_i, peak_i + 1)]
        dsub = ds[lo_i:peak_i + 1]
        if any(v is None for v in cs):
            return None
        ret = (hi[peak_i] / lo[lo_i] - 1) * 100 if lo[lo_i] else None
        mdd = max_drawdown(dsub, cs)
        eps = down_episodes(dsub, cs)
        for e in eps:
            e['from_start'] = ds.index(e['peak']) - lo_i
        return {
            'start': ds[lo_i], 'end': ds[peak_i],
            'days': peak_i - lo_i, 'months': months_between(ds[lo_i], ds[peak_i]),
            'ret': round(ret, 2) if ret is not None else None,
            'start_price': round(lo[lo_i], 2), 'end_price': round(hi[peak_i], 2),
            'mdd': mdd['pct'] if mdd else 0,
            'mdd_peak': mdd['peak'] if mdd else None,
            'mdd_trough': mdd['trough'] if mdd else None,
            'mdd_days': mdd['days'] if mdd else 0,
            'mdd_from_start': (ds.index(mdd['peak']) - lo_i) if mdd else None,
            'dd_count': len(eps), 'episodes': eps,
        }
    # bear：自身最高价 → 终点
    seg = range(lo_i, hi_i)
    peak_i = max(seg, key=lambda i: hi[i] if hi[i] is not None else -1)
    if peak_i >= hi_i - 1:
        return None
    cs = [cl[i] for i in range(peak_i, hi_i)]
    dsub = ds[peak_i:hi_i]
    if any(v is None for v in cs):
        return None
    end_px = cl[hi_i - 1] if ongoing else lo[hi_i - 1]
    ret = (end_px / hi[peak_i] - 1) * 100 if hi[peak_i] else None
    mrb = max_rebound(dsub, cs)
    eps = up_episodes(dsub, cs)
    for e in eps:
        e['from_start'] = ds.index(e['trough']) - peak_i
    return {
        'start': ds[peak_i], 'end': ds[hi_i - 1],
        'days': hi_i - 1 - peak_i, 'months': months_between(ds[peak_i], ds[hi_i - 1]),
        'ret': round(ret, 2) if ret is not None else None,
        'start_price': round(hi[peak_i], 2), 'end_price': round(end_px, 2),
        'mrb': mrb['pct'] if mrb else 0,
        'mrb_trough': mrb['trough'] if mrb else None,
        'mrb_peak': mrb['peak'] if mrb else None,
        'mrb_days': mrb['days'] if mrb else 0,
        'mrb_from_start': (ds.index(mrb['trough']) - peak_i) if mrb else None,
        'rb_count': len(eps), 'episodes': eps,
    }


def avg(vals):
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


def main():
    klines = load_kline()
    # 本轮熊市终点跟随最新 K 线日期，避免每次更新都要手改常量
    asof = max((kd['dates'][-1] for kd in klines.values() if kd.get('dates')),
               default=ASOF)
    CYCLES[-1]['bear'] = (CYCLES[-1]['bear'][0], asof)
    out = {'asof': asof, 'threshold': 10, 'indices': INDEX_LIST, 'cycles': {}, 'overall': {}}

    for cy in CYCLES:
        item = {'name': cy['name'], 'ongoing': cy['ongoing'], 'bull': {}, 'bear': {}}
        for name in INDEX_LIST:
            kd = klines.get(name)
            if not kd or not kd.get('dates'):
                continue
            first = kd['dates'][0]
            # 牛市：起点已成立才统计
            item['bull'][name] = index_phase(kd, cy['bull'][0], cy['bull'][1], 'bull', cy['ongoing']) if first <= cy['bull'][0] else None
            # 熊市：名义见顶日已成立才统计
            item['bear'][name] = index_phase(kd, cy['bear'][0], cy['bear'][1], 'bear', cy['ongoing']) if first <= cy['bear'][0] else None
        out['cycles'][cy['id']] = item

    completed = [c['id'] for c in CYCLES if not c['ongoing']]
    overall = {'completed': completed, 'indices': {}, 'market': {}}
    for name in INDEX_LIST:
        bull = [out['cycles'][cid]['bull'].get(name) for cid in completed]
        bear = [out['cycles'][cid]['bear'].get(name) for cid in completed]
        bull = [x for x in bull if x]
        bear = [x for x in bear if x]
        overall['indices'][name] = {
            'bull_n': len(bull), 'bear_n': len(bear),
            'bull_days': avg([x['days'] for x in bull]),
            'bull_months': avg([x['months'] for x in bull]),
            'bull_ret': avg([x['ret'] for x in bull]),
            'bull_mdd': avg([x['mdd'] for x in bull]),
            'bull_dd_count': avg([x['dd_count'] for x in bull]),
            'bear_days': avg([x['days'] for x in bear]),
            'bear_months': avg([x['months'] for x in bear]),
            'bear_ret': avg([x['ret'] for x in bear]),
            'bear_mrb': avg([x['mrb'] for x in bear]),
            'bear_rb_count': avg([x['rb_count'] for x in bear]),
        }
    # 全指数、全周期均值（仅用于概览一句话，不替代分指数表）
    keys = ['bull_days', 'bull_months', 'bull_ret', 'bull_mdd', 'bull_dd_count',
            'bear_days', 'bear_months', 'bear_ret', 'bear_mrb', 'bear_rb_count']
    for k in keys:
        overall['market'][k] = avg([overall['indices'][n][k] for n in INDEX_LIST])
    overall['market']['bull_n'] = len(completed)
    overall['market']['bear_n'] = len(completed)

    # 每轮全指数等权均值（概览表用）
    for cid, c in out['cycles'].items():
        c['avg'] = {}
        for ph in ('bull', 'bear'):
            k_depth = 'mdd' if ph == 'bull' else 'mrb'
            k_count = 'dd_count' if ph == 'bull' else 'rb_count'
            rows = [c[ph][n] for n in INDEX_LIST if c[ph].get(n)]
            c['avg'][ph] = {
                'days': avg([x['days'] for x in rows]),
                'ret': avg([x['ret'] for x in rows]),
                k_depth: avg([x[k_depth] for x in rows]),
                'count': avg([x[k_count] for x in rows]),
                'n': len(rows),
            }

    out['overall'] = overall
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    json.dump(out, open(OUT_JSON, 'w'), ensure_ascii=False, indent=1)
    js = ('/* generated by src/build_cycle_analysis.py — do not edit */\n'
          'window.WAW=window.WAW||{};window.WAW.cycle_analysis='
          + json.dumps(out, ensure_ascii=False, separators=(',', ':')) + ';\n')
    open(OUT_JS, 'w').write(js)
    print('写出:', OUT_JSON)
    print('写出:', OUT_JS)
    for cid in ['c0508', 'c1315', 'c1618', 'c1921', 'c24now']:
        c = out['cycles'][cid]
        print(cid, 'avg bull', c['avg']['bull'], '| bear', c['avg']['bear'])
        for n in ['上证指数', '创业板指']:
            b = c['bull'].get(n)
            s = c['bear'].get(n)
            print('  ', n, 'bull', (b['days'], b['ret'], b['mdd'], b['dd_count']) if b else None,
                  'bear', (s['days'], s['ret'], s['mrb'], s['rb_count']) if s else None)


if __name__ == '__main__':
    main()
