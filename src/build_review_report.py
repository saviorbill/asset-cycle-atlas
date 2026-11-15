# -*- coding: utf-8 -*-
"""A股复盘报告生成器：严格按用户 docx 的「四阶段」框架逐条回答。

阶段：①牛市起点 ②牛市阶段(初/中/后期) ③牛市顶点 ④转熊
每个复盘点输出：当前数据 + 判断 + 历史对照 + 数据缺口。
输出 dashboard/review_report.html（可直接双击打开阅读）。
"""
import os, sys
import numpy as np
import pandas as pd

SRC = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(SRC)
sys.path.insert(0, SRC)
sys.path.insert(0, PROJ)
from config import INDEX_CSV, CACHE_DIR, MARGIN_CSV, LIMIT_CPT_CSV, HK_HOLD_CSV, DASHBOARD_DIR
import narrative as narrative_mod
import clock as clock_mod


# ---------- 数据加载 ----------
def load_market():
    m = pd.read_parquet(os.path.join(CACHE_DIR, "market_daily.parquet"))
    m["date"] = pd.to_datetime(m["date"])
    return m.sort_values("date").reset_index(drop=True)


def load_theme():
    t = pd.read_parquet(os.path.join(CACHE_DIR, "theme_daily.parquet"))
    t["date"] = pd.to_datetime(t["date"])
    return t


def load_margin():
    m = pd.read_csv(MARGIN_CSV, usecols=["trade_date", "exchange_id", "rzye", "rzmre"])
    m["trade_date"] = pd.to_datetime(m["trade_date"].astype(str), format="%Y%m%d")
    return m.groupby("trade_date").agg(rzye=("rzye", "sum"), rzmre=("rzmre", "sum")).reset_index().sort_values("trade_date")


def load_limit():
    d = pd.read_csv(LIMIT_CPT_CSV, usecols=["trade_date", "up_nums"])
    d["trade_date"] = pd.to_datetime(d["trade_date"].astype(str), format="%Y%m%d")
    return d.groupby("trade_date")["up_nums"].sum().reset_index()


def load_hk():
    d = pd.read_csv(HK_HOLD_CSV, usecols=["trade_date", "ratio"])
    d["trade_date"] = pd.to_datetime(d["trade_date"].astype(str).str.split(".").str[0], format="%Y%m%d", errors="coerce")
    return d.dropna(subset=["trade_date"]).groupby("trade_date")["ratio"].mean().reset_index()


# ---------- 工具 ----------
def pct_rank(series, value):
    s = series.dropna()
    if len(s) == 0 or value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    return float((s <= value).mean())


def judge(val, lo=None, hi=None, lo_txt="偏低", mid_txt="中性", hi_txt="偏高"):
    if val is None:
        return ("未知", "gray")
    if lo is not None and val < lo:
        return (lo_txt, "green")
    if hi is not None and val > hi:
        return (hi_txt, "red")
    return (mid_txt, "amber")


def card(title, current, judgement, hist, gap=None):
    jt, jc = judgement
    color = {"green": "#2e7d5b", "red": "#c0392b", "amber": "#b8860b", "gray": "#888"}[jc]
    gap_html = f'<div class="gap">⚠ 数据缺口：{gap}</div>' if gap else ""
    return f"""
    <div class="card">
      <div class="card-head"><span class="card-title">{title}</span><span class="badge" style="background:{color}">{jt}</span></div>
      <div class="card-body">
        <div class="line"><b>当前：</b>{current}</div>
        <div class="line"><b>历史参照：</b>{hist}</div>
        {gap_html}
      </div>
    </div>"""


# ---------- 主逻辑 ----------
def build():
    mkt = load_market()
    mg = load_margin()
    lim = load_limit()
    hk = load_hk()
    th = load_theme()
    idx = pd.read_csv(INDEX_CSV, parse_dates=["date"]).sort_values("date").reset_index(drop=True)

    mdate = mkt["date"].iloc[-1]
    last = mkt.iloc[-1]
    last_pe = mkt["pe_median"].dropna()
    pe_v = float(last_pe.iloc[-1]) if len(last_pe) else None
    m10 = mkt[mkt["date"] >= mdate - pd.DateOffset(years=10)]

    # 周期位置（指数口径）
    bull_start = pd.Timestamp("2024-02-05")
    seg = idx[idx["date"] >= bull_start]
    peak = float(seg["上证指数"].max())
    peak_date = seg.loc[seg["上证指数"].idxmax(), "date"]
    cur = float(idx["上证指数"].iloc[-1])
    idx_last_date = idx["date"].iloc[-1]
    dd = (cur / peak - 1) * 100

    # 阶段判断
    if dd <= -20:
        stage, stage_desc = "转熊/技术性熊市", f"上证自 {peak_date:%Y-%m-%d} 高点回撤 {dd:.1f}%，已进入技术性熊市"
    elif dd <= -10:
        stage, stage_desc = "顶点后回调（转熊初期）", f"上证自 {peak_date:%Y-%m-%d} 高点回撤 {dd:.1f}%，高位回调但未破 -20%"
    elif dd <= -5:
        stage, stage_desc = "牛市后期/高位震荡", f"上证距高点回撤 {dd:.1f}%"
    else:
        stage, stage_desc = "牛市阶段（中/后期）", f"上证距高点回撤仅 {dd:.1f}%，仍处高位"

    # 关键指标
    pe_pctl = pct_rank(m10["pe_median"], pe_v)
    pb_pctl = pct_rank(m10["pb_median"], last["pb_median"])
    conc_pctl = pct_rank(m10["concentration_top5"], last["concentration_top5"])
    up_pctl = pct_rank(m10["up_ratio"], last["up_ratio"])
    turn_pctl = pct_rank(m10["turnover_median"], last["turnover_median"])

    # 融资
    m10y = mg[mg["trade_date"] >= mg["trade_date"].max() - pd.DateOffset(years=10)]
    mg_last = mg.iloc[-1]
    mg_pctl = pct_rank(m10y["rzye"], mg_last["rzye"])
    mg_amt_chg = (mg["rzye"].iloc[-1] / mg["rzye"].iloc[-21] - 1) * 100 if len(mg) > 21 else None

    # 涨停
    lim_last = lim.iloc[-1]
    lim_pctl = pct_rank(lim["up_nums"], lim_last["up_nums"])

    # 外资(港股通持股比例均值)
    hk_last = hk.iloc[-1]
    hk_prev = hk.iloc[-21] if len(hk) > 21 else hk.iloc[0]
    hk_chg = hk_last["ratio"] - hk_prev["ratio"]

    # 主线板块（叙事口径：250日超额）与 近期强势（单日/近期涨跌）
    nar = narrative_mod.snapshot()
    main_line = nar["themes"][0]["theme"] if nar["themes"] else "—"
    main_state = nar["themes"][0]["state"] if nar["themes"] else "—"
    top3_main = "、".join([r["theme"] for r in nar["themes"][:3]])
    last_th = th[th["date"] == th["date"].max()]
    last_th = last_th.dropna(subset=["ret_equal"])
    near3 = last_th.sort_values("ret_equal", ascending=False).head(3)
    near_txt = "、".join([f"{r.theme}({r.ret_equal*100:+.1f}%)" for r in near3.itertuples()])

    # 历史牛熊对照
    idx2 = idx[idx["date"] >= "2005-01-01"].reset_index(drop=True)
    peaks = [("2007-10-16", "2008-10-28"), ("2009-08-04", "2012-12-04"),
             ("2015-06-12", "2016-01-27"), ("2018-01-26", "2019-01-04"),
             ("2021-02-18", "2022-04-27")]
    hist_rows = []
    for p, l in peaks:
        try:
            pv = idx2.loc[idx2["date"] <= pd.Timestamp(p), "上证指数"].iloc[-1]
            lv = idx2.loc[idx2["date"] <= pd.Timestamp(l), "上证指数"].iloc[-1]
            hist_rows.append((p, l, round((lv / pv - 1) * 100, 1)))
        except Exception:
            pass

    # ===== 生成 HTML =====
    css = """
    <style>
    :root{--ink:#2b2b2b;--muted:#888;--accent:#1f4e79;--border:#e8e5de;--bg:#faf9f6}
    *{box-sizing:border-box;margin:0;padding:0}
    body{background:var(--bg);color:var(--ink);font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;line-height:1.65;padding:28px 22px 60px}
    .wrap{max-width:960px;margin:0 auto}
    h1{font-size:24px;margin-bottom:4px}
    .sub{color:var(--muted);font-size:13px;margin-bottom:18px}
    .banner{background:linear-gradient(135deg,#1f4e79,#2c6a9f);color:#fff;border-radius:12px;padding:18px 22px;margin-bottom:20px}
    .banner .stage{font-size:26px;font-weight:800}
    .banner .desc{font-size:14px;opacity:.92;margin-top:6px}
    h2{font-size:18px;margin:26px 0 12px;padding-left:10px;border-left:4px solid var(--accent)}
    h3{font-size:15px;margin:16px 0 8px;color:var(--accent)}
    .card{background:#fff;border:1px solid var(--border);border-radius:10px;padding:12px 15px;margin:8px 0}
    .card-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}
    .card-title{font-weight:700;font-size:14px}
    .badge{color:#fff;font-size:12px;padding:1px 9px;border-radius:12px}
    .line{font-size:13px;margin:3px 0}
    .gap{font-size:12px;color:#b8860b;margin-top:6px;background:#fdf6e3;padding:4px 8px;border-radius:6px}
    .note{font-size:12.5px;color:var(--muted);margin:10px 0}
    table{width:100%;border-collapse:collapse;font-size:13px;margin-top:6px}
    th,td{padding:6px 9px;border-bottom:1px solid var(--border);text-align:left}
    th{background:#f7f5f0;color:var(--muted);font-weight:600}
    .concl{background:#f0f6fb;border-radius:10px;padding:14px 18px;margin:16px 0;font-size:14px}
    .concl b{color:var(--accent)}
    </style>"""

    h = []
    h.append(f"<!DOCTYPE html><html lang='zh-CN'><head><meta charset='UTF-8'><title>A股复盘报告</title>{css}</head><body><div class='wrap'>")
    h.append(f"<h1>A股复盘报告 · 按「四阶段」框架逐条复盘</h1>")
    h.append(f"<div class='sub'>复盘数据日：{mdate:%Y-%m-%d}（估值/换手/集中度/融资/涨停） · 指数最新：{idx_last_date:%Y-%m-%d} · 生成于 {pd.Timestamp.now():%Y-%m-%d %H:%M}</div>")

    h.append(f"<div class='banner'><div class='stage'>当前阶段：{stage}</div><div class='desc'>{stage_desc}</div></div>")

    # 0. 一句话结论
    h.append("<div class='concl'><b>一句话复盘：</b>" +
             f"上证距 {peak_date:%Y-%m-%d} 高点 {peak:.0f} 点回撤 {dd:.1f}%；"
             f"全A PE 中位数 {pe_v:.1f}（近10年 {pe_pctl*100:.0f}% 分位），成交集中度 {conc_pctl*100:.0f}% 分位（"
             + ("高度拥挤，主线抱团" if conc_pctl and conc_pctl > 0.8 else "不算拥挤") + "）；"
             f"融资余额 {mg_last['rzye']/1e8:.0f} 亿（{mg_pctl*100:.0f}% 分位）。"
             f"叙事主线：{main_line}（{main_state}）。"
             f"→ 当前更像「<b>{stage}</b>」阶段，需重点跟踪「顶部分化是否确认」。"
             "</div>")

    # ===== 一、牛市起点 =====
    h.append("<h2>一、牛市起点：底部环境 与 金融市场</h2>")
    h.append("<h3>1.1 底部环境</h3>")
    # 宏观
    clk = clock_mod.current_stage()
    macro_txt = (f"宏观：GDP {clk['gdp_yoy']}%、CPI {clk['cpi_yoy']}%、M2 {clk['m2_yoy']}%、"
                 f"LPR {clk['lpr1y']}%、实际利率 {clk['real_rate']}%；投资时钟：{clk['stage7']}（美林{clk['stage4']}）")
    h.append(card("宏观：顶层政策、金融创新（货币/财政/景气）",
                  macro_txt, ("需结合时钟", "amber"),
                  "历史底部多对应货币宽松（降准降息）+ 财政发力；当前 M2 7.7%、LPR 3.0% 偏宽松，但 CPI 0.5% 显示需求偏弱。",
                  "『顶层政策文件、金融创新』需政策库/新闻源；宏观数据已有。"))
    h.append(card("中观：行业政策、区域政策", "—", ("需人工研判", "gray"),
                  "观察是否有持续的行业支持文件、区域振兴规划。", "需政策库/新闻源（本地无）。"))
    h.append(card("微观：产品引爆", "—", ("需人工研判", "gray"),
                  "观察龙头公司是否出现爆款产品/技术突破（如新能源车、AI 大模型）。", "需新闻/公告/产业链数据（本地无）。"))

    h.append("<h3>1.2 金融市场（底部特征）</h3>")
    amt = last["amount"] / 1e8
    h.append(card("成交量", f"全A成交额 {amt:,.0f} 亿元（{pct_rank(m10['amount'], last['amount'])*100:.0f}% 分位）",
                  judge(pct_rank(m10["amount"], last["amount"]), lo=0.2, hi=0.8, lo_txt="地量（底部特征）", mid_txt="中性", hi_txt="放量"),
                  "历史上牛市起点多伴随地量（成交额分位 <20%），牛市高潮放量。"))
    h.append(card("融资水平", f"融资余额 {mg_last['rzye']/1e8:,.0f} 亿（{mg_pctl*100:.0f}% 分位）",
                  judge(mg_pctl, lo=0.2, hi=0.8, lo_txt="去杠杆充分", mid_txt="中性", hi_txt="杠杆高"),
                  "底部融资余额往往处于低位；高位融资余额是风险信号。"))
    h.append(card("减持 / 国家队持仓变化", "—", ("需数据源", "gray"),
                  "底部增持/回购增多、减持减少；国家队往往在熊市底部增持。",
                  "本地无『重要股东减持、国家队持仓』数据，需 akshare/API 补充。"))

    # ===== 二、牛市阶段 =====
    h.append("<h2>二、牛市阶段（初期 / 中期 / 后期）</h2>")
    h.append("<h3>2.1 宏大叙事</h3>")
    h.append(card("宏大叙事：市场在讲什么故事？发展到了哪一步？",
                  f"叙事口径主线（250日超额）：{main_line}（状态：{main_state}）；前三：{top3_main}",
                  ("主线已显", "amber"),
                  "叙事经济学：超额收益在『叙事变化的一瞬间』完成。主线状态分 起涨/加速/兑现/回落——『兑现』表示故事已讲完、超额收益见顶。",
                  "本引擎用『板块相对沪深300超额收益』代理叙事进度；『市场在讲什么故事』的语义需新闻/研报语料（本地研报仅近3月）。"))
    h.append("<h3>2.2 产业趋势（一级市场投融资）</h3>")
    h.append(card("产业趋势：巨头和私募在一级市场的投融资", "—", ("需数据源", "gray"),
                  "产业趋势强 → 一级投融资活跃、龙头融资/扩产。", "本地无一级市场投融资数据，需 IT桔子/企查查等。"))
    h.append("<h3>2.3 全球共振</h3>")
    h.append(card("全球共振：全球推动还是本土推动", "—", ("需数据源", "gray"),
                  "全球共振（如AI算力全球资本开支）持续性强；纯本土行情易受政策/资金约束。", "本地无海外股市/半导体销售数据（ADV 有内置国际宏观，可接入）。"))
    h.append("<h3>2.4 新闻舆情和政策</h3>")
    h.append(card("市场情绪代理（涨停家数）",
                  f"当日涨停/连板统计：涨停家数 {int(lim_last['up_nums']):.0f}（{lim_pctl*100:.0f}% 分位）",
                  judge(lim_pctl, lo=0.2, hi=0.8, lo_txt="情绪冰点", mid_txt="情绪中性", hi_txt="情绪过热"),
                  "涨停家数是情绪/舆情的代理指标：过热（>80%分位）常出现在行情后段。"))
    h.append(card("新闻舆情：主流媒体讲什么？政策支持文件？", "—", ("需数据源", "gray"),
                  "政策持续支持 + 主流媒体扩散 = 叙事进入大众传播期（风险上升）。", "本地无新闻/政策文本，需接入新闻API/政策库。"))
    h.append("<h3>2.5 二级市场主线板块（普涨→缩圈、成交量、集中度、机构持仓）</h3>")
    h.append(card("主线板块：叙事主线 vs 近期强势",
                  f"叙事主线（250日超额）：{top3_main}；近期强势（单日）：{near_txt}",
                  ("主线集中", "amber" if (conc_pctl or 0) < 0.8 else "red"),
                  "从普涨→缩圈是行情后段特征：主线成交占比上升、广度下降、个股只剩龙头。"))
    h.append(card("成交量 / 集中度",
                  f"成交额分位 {pct_rank(m10['amount'], last['amount'])*100:.0f}%；集中度(前5%) {conc_pctl*100:.0f}% 分位；"
                  f"上涨家数占比 {last['up_ratio']*100:.0f}%（{up_pctl*100:.0f}% 分位）",
                  judge(conc_pctl, lo=None, hi=0.8, hi_txt="高度拥挤（缩圈）"),
                  "集中度 >80% 分位 = 资金抱团缩圈，是行情后段的重要信号。"))
    h.append(card("机构持仓变化", "—", ("需数据源", "gray"),
                  "公募/外资持仓从低配→超配→减持，是共识形成与瓦解的标志。", "本地无公募季报持仓，需季报/交易所披露。"))

    # ===== 三、牛市顶点 =====
    h.append("<h2>三、牛市顶点</h2>")
    h.append("<h3>3.1 走势：主线是否加速冲顶？</h3>")
    h.append(card("主线加速冲顶", f"上证自高点回撤 {dd:.1f}%；当前主线 " + (last_th.sort_values('ret_equal', ascending=False)['theme'].iloc[0]),
                  judge(dd, lo=None, hi=-10, hi_txt="已见顶回落"),
                  "历史上牛市顶点常以『主线板块加速冲顶』完成，随后主线先见顶、指数滞后。"))
    h.append("<h3>3.2 新闻舆情：是否有明显政策变化？</h3>")
    h.append(card("政策转向", "—", ("需数据源", "gray"), "顶部常伴随政策收紧（加息、查配资、打压投机）。", "需政策库/新闻源。"))
    h.append("<h3>3.3 减持：公司高管、国家队</h3>")
    h.append(card("高管/国家队减持", "—", ("需数据源", "gray"), "顶部高管减持激增、国家队减持是风险信号。", "需减持/国家队持仓数据。"))
    h.append("<h3>3.4 产业融资需求：定增、IPO</h3>")
    h.append(card("定增/IPO发行", "—", ("需数据源", "gray"), "顶部产业融资（定增、IPO）往往放量，反映产业资本高位套现。", "需定增/IPO数据（akshare 有）。"))

    # ===== 四、转熊 =====
    h.append("<h2>四、转熊</h2>")
    h.append("<h3>4.1 高位震荡后是否以快速杀跌完成第一次出清？</h3>")
    h.append(card("第一次出清", f"当前回撤 {dd:.1f}%（上证 {cur:.0f} / 高点 {peak:.0f}）",
                  judge(dd, lo=None, hi=-10, hi_txt="已进入回调/出清"),
                  "A股熊市常见『快速杀跌完成第一次出清』：05-08 -73%/12月，13-15 -45%/7.5月，19-21 -20%+/5月。"))
    h.append("<h3>4.2 二级市场融资水平变化</h3>")
    h.append(card("融资余额变化",
                  f"融资余额 {mg_last['rzye']/1e8:,.0f} 亿，近20日变化 {mg_amt_chg:+.1f}%" if mg_amt_chg is not None else "—",
                  judge(mg_amt_chg, lo=None, hi=5, hi_txt="杠杆仍在扩张"),
                  "转熊初期融资余额往往从高位回落（去杠杆），回落速度决定杀跌烈度。"))
    h.append("<h3>4.3 机构被动减仓、融资盘爆仓</h3>")
    h.append(card("被动减仓/爆仓信号", "—", ("需数据源", "gray"), "关注两融强平、私募止损线、雪球敲入等。", "需两融个股/产品数据。"))
    h.append("<h3>4.4 顶层发声、国家队重新进场</h3>")
    h.append(card("政策托底信号", "—", ("需数据源", "gray"), "熊市底部常伴『顶层发声+国家队进场』（如 2015、2018、2024）。", "需政策/国家队数据。"))
    h.append("<h3>4.5 超跌反弹与反弹后新低</h3>")
    h.append(card("超跌反弹规律", "—", ("需历史验证", "gray"),
                  "历史：大幅杀跌后常有超跌反弹（如 22/4/27→22/10/31 双底），反弹后再探新低、领先指标企稳才真底。",
                  "可用指数日线验证（本地有），但『反弹后是否新低』需逐轮历史标注。"))

    # ===== 五、历史对照 =====
    h.append("<h2>五、历史牛熊对照</h2>")
    h.append("<table><tr><th>牛市高点</th><th>熊市低点</th><th>熊市跌幅</th></tr>")
    for p, l, r in hist_rows:
        h.append(f"<tr><td>{p}</td><td>{l}</td><td style='color:#c0392b'>{r}%</td></tr>")
    h.append(f"<tr><td colspan='3' style='color:#1f4e79'><b>当前：高点 {peak_date:%Y-%m-%d}（{peak:.0f}）→ 现价 {cur:.0f}，回撤 {dd:.1f}%</b></td></tr>")
    h.append("</table>")

    # ===== 六、本周关注清单 =====
    h.append("<h2>六、本周关注清单（基于当前阶段）</h2>")
    watch = [
        f"上证是否跌破 -20%（技术性熊市确认）：当前 {dd:.1f}%，跌破则确认转熊。",
        f"主线（{main_line}）超额收益是否见顶：叙事状态为「{main_state}」，若由加速转兑现/回落，警惕主线切换。",
        f"成交集中度是否从 {conc_pctl*100:.0f}% 分位回落：缩圈缓解则风险偏好修复，继续升则拥挤加剧。",
        f"融资余额变化：近20日 {mg_amt_chg:+.1f}%，关注去杠杆速度是否加速。",
        "涨停家数与龙虎榜资金：判断情绪冰点/过热。",
        "缺口数据（减持/国家队/IPO定增/新闻政策）：建议接 akshare/API 后补入，才能完整复盘。",
    ]
    h.append("<table><tr><th>#</th><th>观察项</th></tr>")
    for i, w in enumerate(watch, 1):
        h.append(f"<tr><td>{i}</td><td>{w}</td></tr>")
    h.append("</table>")

    # 缺口汇总
    h.append("<div class='concl'><b>数据缺口（需补充后才能完整复盘）：</b>" +
             "减持/国家队持仓、IPO/定增、一级市场投融资、新闻舆情/政策文件、公募机构持仓。"
             "这些对应你框架里的『减持、国家队、产业融资、新闻舆情、机构持仓』五项，本地数据没有，"
             "可用 akshare（减持/IPO/定增）与新闻API补充。</div>")

    h.append("<div class='note'>本报告由本地数据自动生成，历史规律不代表未来，仅供复盘研究，不构成投资建议。</div>")
    h.append("</div></body></html>")

    out = os.path.join(DASHBOARD_DIR, "review_report.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(h))
    print("已生成:", out)
    print("阶段:", stage, "| 回撤:", round(dd, 1), "% | PE分位:", round(pe_pctl*100, 1) if pe_pctl else None,
          "| 集中度分位:", round(conc_pctl*100, 1) if conc_pctl else None)


if __name__ == "__main__":
    build()
