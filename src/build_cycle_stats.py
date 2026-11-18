# -*- coding: utf-8 -*-
"""构建每轮牛熊的阶段统计（行业/个股 Top10）。

数据源：datahubco（Tushare 代理）
  - index-member-all：申万一级行业历史成员（含 in_date / out_date）
  - stock-basic：当前/退市股票列表（list_date、名称）
  - daily + adj-factor：阶段起止日的全市场收盘价与复权因子

输出：
  cache/cycle_stats_raw/   原始接口分页缓存（可重复运行，自动复用）
  cache/cycle_stats.json   结构化统计
  web/cycle_stats.js       前端数据（window.WAW.cycle_stats）

口径：
  - 行业：申万一级，按阶段起点成员等权平均；样本少于 3 只的行业不参与排名。
  - 个股：沪深 A 股，复权价（含分红送转），剔除阶段内上市新股；
          仅统计阶段起止均有行情的个股；不含北交所。
  - 指数层面的历时/涨跌幅/最大回撤/最大反弹由前端用上证 K 线实时计算。
"""
import os
import sys
import json
import time
import math
import hashlib
import statistics
from collections import defaultdict
from datetime import datetime, timedelta

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import CACHE_DIR, PROJ
from fetch_api_data import BASE, HEAD

os.environ['NO_PROXY'] = '*'
import requests

RAW_DIR = os.path.join(CACHE_DIR, 'cycle_stats_raw')
OUT_JSON = os.path.join(CACHE_DIR, 'cycle_stats.json')
WEB_JS = os.path.join(PROJ, 'web', 'cycle_stats.js')
os.makedirs(RAW_DIR, exist_ok=True)

MIN_INDUSTRY_STOCKS = 5
API_MIN_INTERVAL = 3.2
_last_call = [0.0]


# ------------------------------------------------------------------
# 周期定义（与 web/data.js 的 W.cycles 保持一致）
# ------------------------------------------------------------------
CYCLES = [
    {
        'id': 'c0508', 'name': '2005–2008 全面牛',
        'bull': ('2005-06-06', '2007-10-16'),
        'bear': ('2007-10-16', '2008-10-28'),
        'start_cause': '股权分置改革落地，经济高增长与大宗商品超级周期共振，人民币升值预期吸引资金入场',
        'end_cause': '通胀高企、货币政策持续收紧，叠加美国次贷危机与全球流动性拐点',
    },
    {
        'id': 'c1315', 'name': '2013–2015 全面牛',
        'bull': ('2012-12-04', '2015-06-12'),
        'bear': ('2015-06-12', '2016-01-27'),
        'start_cause': '改革预期升温，移动互联网与并购重组浪潮、两融杠杆资金共振',
        'end_cause': '监管清查场外配资、去杠杆引发流动性踩踏，叠加汇率波动',
    },
    {
        'id': 'c1618', 'name': '2016–2018 结构性',
        'bull': ('2016-01-27', '2018-01-26'),
        'bear': ('2018-01-26', '2019-01-04'),
        'start_cause': '供给侧改革修复盈利，消费升级与行业集中度提升，北向资金持续流入',
        'end_cause': '中美贸易摩擦升级，资管新规下信用收缩、去杠杆',
    },
    {
        'id': 'c1921', 'name': '2019–2021 结构性',
        'bull': ('2019-01-04', '2021-02-18'),
        'bear': ('2021-02-18', '2022-04-27'),
        'start_cause': '科创板与注册制改革，新能源产业趋势、公募和外资增量资金共振',
        'end_cause': '核心资产估值过高、抱团拥挤，叠加反垄断监管、美联储加息与俄乌冲突',
    },
    {
        'id': 'c24now', 'name': '2024–至今 本轮',
        'bull': ('2024-02-05', '2026-05-13'),
        'bear': ('2026-05-13', '2026-11-13'),
        'start_cause': '924 政策组合拳、国家队托底，AI/算力产业趋势与全球资本开支共振',
        'end_cause': '2026-05 后高位拥挤、融资去杠杆，主线进入兑现期；是否构成周期终结仍待确认',
        'ongoing': True,
    },
]


# ------------------------------------------------------------------
# API 抓取（带磁盘缓存 + 限速 + 429 退避）
# ------------------------------------------------------------------
def _cache_path(endpoint, params):
    key = hashlib.md5((endpoint + '|' + json.dumps(params, sort_keys=True)).encode()).hexdigest()[:16]
    return os.path.join(RAW_DIR, key + '.json')


def api_get(endpoint, params, tries=10):
    fp = _cache_path(endpoint, params)
    if os.path.exists(fp):
        return json.load(open(fp))
    for attempt in range(tries):
        wait = API_MIN_INTERVAL - (time.time() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        r = requests.get(BASE + endpoint, headers=HEAD, params=params, timeout=90)
        _last_call[0] = time.time()
        if r.status_code == 429:
            pause = 10 * (attempt + 1)
            print('  429 %s，等待 %ds' % (endpoint, pause), flush=True)
            time.sleep(pause)
            continue
        d = r.json()
        if d.get('code') == 0:
            data = d.get('data') or {}
            json.dump(data, open(fp, 'w'))
            return data
        print('  %s code=%s msg=%s' % (endpoint, d.get('code'), d.get('msg')), flush=True)
        time.sleep(5)
    raise RuntimeError('接口失败: %s %s' % (endpoint, params))


def fetch_all(endpoint, params, limit=5000):
    rows, fields, offset = [], None, 0
    while True:
        p = dict(params)
        p.update({'limit': limit, 'offset': offset})
        d = api_get(endpoint, p)
        fields = d.get('fields') or fields
        items = d.get('items') or []
        rows.extend(items)
        print('  %-18s offset=%-5d +%-5d total=%d' % (endpoint, offset, len(items), len(rows)), flush=True)
        if not items or not d.get('has_more'):
            break
        offset += limit
    return fields, rows


# ------------------------------------------------------------------
# 基础数据
# ------------------------------------------------------------------
def load_members():
    fields, rows = fetch_all('index-member-all', {})
    df = pd.DataFrame(rows, columns=fields)
    for c in ['in_date', 'out_date']:
        df[c] = df[c].fillna('').astype(str).str.replace(r'\.0$', '', regex=True)
    df['ts_code'] = df['ts_code'].astype(str)
    print('申万成员:', len(df), '行 |', df['ts_code'].nunique(), '只股票', flush=True)
    return df


def membership_map(members):
    """当前申万一级分类回溯。

    index-member-all 在本接口下每只股票只有一条当前分类记录，
    in_date 并非历史行业归属日期；若按 in_date 截断会漏掉大量老股票，
    因此这里使用每只股票最新的一条 L1 记录。行业口径会在页面上注明。
    """
    if members.empty:
        return {}
    sub = members.sort_values(['ts_code', 'in_date'])
    last = sub.groupby('ts_code', as_index=False).tail(1)
    return dict(zip(last['ts_code'], last['l1_name']))


def load_basic():
    out = {}
    for status in ('L', 'D'):
        fields, rows = fetch_all('stock-basic', {'list_status': status})
        for r in rows:
            d = dict(zip(fields, r))
            code = str(d.get('ts_code') or '')
            if not code or code in out:
                continue
            out[code] = {
                'name': str(d.get('name') or ''),
                'list_date': str(d.get('list_date') or '').replace('.0', ''),
                'delisted': status == 'D',
            }
    print('股票基础信息:', len(out), '只', flush=True)
    return out


def load_px(date):
    """返回 (实际行情日, close dict, adj_factor dict)。接口暂未更新时向前回退。"""
    for delta in range(0, 8):
        d = (datetime.strptime(date, '%Y-%m-%d') - timedelta(days=delta)).strftime('%Y-%m-%d')
        ds = d.replace('-', '')
        _, dly = fetch_all('daily', {'trade_date': ds})
        if not dly:
            continue
        _, adj = fetch_all('adj-factor', {'trade_date': ds})
        if not adj:
            continue
        close = {str(r[0]): float(r[5]) for r in dly if r[5] is not None}
        af = {str(r[0]): float(r[2]) for r in adj if r[2] is not None}
        if delta:
            print('  %s 暂无行情，回退至 %s' % (date, d), flush=True)
        return d, close, af
    raise RuntimeError('无行情数据: %s' % date)


# ------------------------------------------------------------------
# 统计
# ------------------------------------------------------------------
def clean_name(name):
    name = (name or '').strip()
    for suf in ('(退市)', '（退市）', '(退)', '（退）'):
        name = name.replace(suf, '')
    return name.strip()


def _q(vals, p):
    if not vals:
        return None
    vals = sorted(vals)
    k = (len(vals) - 1) * p
    lo, hi = int(math.floor(k)), int(math.ceil(k))
    if lo == hi:
        return round(vals[lo], 2)
    return round(vals[lo] * (hi - k) + vals[hi] * (k - lo), 2)


def stock_stats(records):
    vals = [r['ret'] for r in records]
    if not vals:
        return {}
    vals_sorted = sorted(vals)
    return {
        'n': len(vals),
        'avg': round(sum(vals) / len(vals), 2),
        'median': round(statistics.median(vals), 2),
        'p10': _q(vals, 0.10), 'p90': _q(vals, 0.90),
        'up_ratio': round(sum(1 for v in vals if v > 0) / len(vals) * 100, 1),
        'top10_avg': round(sum(vals_sorted[-10:]) / min(10, len(vals)), 2),
        'bottom10_avg': round(sum(vals_sorted[:10]) / min(10, len(vals)), 2),
    }


def industry_stats(industries):
    vals = [x['ret'] for x in industries]
    if not vals:
        return {}
    vals_sorted = sorted(vals)
    return {
        'n': len(vals),
        'avg': round(sum(vals) / len(vals), 2),
        'median': round(statistics.median(vals), 2),
        'up_ratio': round(sum(1 for v in vals if v > 0) / len(vals) * 100, 1),
        'top10_avg': round(sum(vals_sorted[-10:]) / min(10, len(vals)), 2),
        'bottom10_avg': round(sum(vals_sorted[:10]) / min(10, len(vals)), 2),
    }


def compute_phase(members, basic, start, end):
    start8, end8 = start.replace('-', ''), end.replace('-', '')
    d0, c0, a0 = load_px(start)
    d1, c1, a1 = load_px(end)
    imap = membership_map(members)

    records = []
    excluded = {'st': 0, 'delisted': 0}
    for code in set(c0) & set(c1) & set(a0) & set(a1):
        if not (code.endswith('.SH') or code.endswith('.SZ')):
            continue  # 仅沪深 A 股
        info = basic.get(code)
        if not info or not info['list_date']:
            continue
        if info['list_date'] >= start8:
            continue  # 剔除阶段内上市新股
        raw_name = (info['name'] or '').upper()
        if info['delisted']:
            excluded['delisted'] += 1
            continue  # 剔除退市股
        if 'ST' in raw_name:
            excluded['st'] += 1
            continue  # 剔除 ST / *ST
        v0, v1 = c0[code] * a0[code], c1[code] * a1[code]
        if v0 <= 0 or v1 <= 0:
            continue
        ret = v1 / v0 - 1
        if not math.isfinite(ret):
            continue
        records.append({
            'code': code,
            'name': clean_name(info['name']),
            'delisted': bool(info['delisted']),
            'industry': imap.get(code),
            'ret': round(ret * 100, 2),
        })

    by_ind = defaultdict(list)
    for r in records:
        if r['industry']:
            by_ind[r['industry']].append(r['ret'])
    industries = [
        {'name': k, 'ret': round(sum(v) / len(v), 2), 'n': len(v)}
        for k, v in by_ind.items() if len(v) >= MIN_INDUSTRY_STOCKS
    ]

    stocks = sorted(records, key=lambda x: x['ret'], reverse=True)
    ind_rank = sorted(industries, key=lambda x: x['ret'], reverse=True)
    return {
        'start': start,
        'end': end,
        'price_start': d0,
        'price_end': d1,
        'industries': ind_rank[:10],
        'stocks': stocks[:10],
        'industries_bottom': sorted(industries, key=lambda x: x['ret'])[:10],
        'stocks_bottom': list(reversed(stocks[-10:])),
        'stock_stats': stock_stats(records),
        'industry_stats': industry_stats(industries),
        'excluded': excluded,
        'coverage': {
            'stocks': len(records),
            'industries': len(industries),
            'unmapped': sum(1 for r in records if not r['industry']),
        },
    }


def main():
    print('=== 拉取申万成员 ===', flush=True)
    members = load_members()
    print('=== 拉取股票列表 ===', flush=True)
    basic = load_basic()

    out = {
        'asof': '2026-11-13',
        'method': {
            'industry': '申万一级（当前分类回溯），阶段起点成员等权；剔除 ST/退市股；样本少于 %d 只不参与排名' % MIN_INDUSTRY_STOCKS,
            'stock': '沪深A股，复权价；剔除 ST/退市股与阶段内上市新股；仅统计阶段起止均有行情',
        },
        'cycles': {},
    }

    for cy in CYCLES:
        print('\n=== %s %s ===' % (cy['id'], cy['name']), flush=True)
        item = {
            'name': cy['name'],
            'start_cause': cy['start_cause'],
            'end_cause': cy['end_cause'],
            'ongoing': bool(cy.get('ongoing')),
        }
        for phase in ('bull', 'bear'):
            s, e = cy[phase]
            print('  %s %s → %s' % (phase, s, e), flush=True)
            item[phase] = compute_phase(members, basic, s, e)
            top = item[phase]['industries'][:3]
            print('    行业前3:', ', '.join('%s %+.1f%% (n=%d)' % (x['name'], x['ret'], x['n']) for x in top), flush=True)
            st = item[phase]['stocks'][:3]
            print('    个股前3:', ', '.join('%s %+.1f%%' % (x['name'], x['ret']) for x in st), flush=True)
        out['cycles'][cy['id']] = item

    json.dump(out, open(OUT_JSON, 'w'), ensure_ascii=False, indent=1)
    js = ('/* generated by src/build_cycle_stats.py — do not edit */\n'
          'window.WAW=window.WAW||{};window.WAW.cycle_stats='
          + json.dumps(out, ensure_ascii=False, separators=(',', ':')) + ';\n')
    open(WEB_JS, 'w').write(js)
    print('\n写出:', OUT_JSON, flush=True)
    print('写出:', WEB_JS, flush=True)


if __name__ == '__main__':
    main()
