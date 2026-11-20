# -*- coding: utf-8 -*-
"""全局配置：路径、阈值、规范牛熊周期划分。"""
import os

# ---- 路径 ----
PROJ = "/Users/kunrongcai/Desktop/LLM-AI Agent/Deepseek/Skill研究/ashare-fupan"
DATA_DIR = "/Users/kunrongcai/Desktop/A股数据"
SRC_DIR = os.path.join(PROJ, "src")
DASHBOARD_DIR = os.path.join(PROJ, "dashboard")

# ---- 应用数据：本项目的输入与缓存，全部收在「A股数据/应用数据」下 ----
# 这样所有金融数据只有一个入口，换机器/备份只搬一个文件夹。
# 数据地图见 A股数据/数据地图.md
APP_DATA = os.path.join(DATA_DIR, "应用数据")
CACHE_DIR = os.path.join(APP_DATA, "cache")           # 可重建的中间层
INDEX_KLINE_DIR = os.path.join(APP_DATA, "index_kline")  # 7 个指数的原始日线 xlsx
INDEX_CSV = os.path.join(APP_DATA, "index_daily.csv")    # 八大指数收盘价（脚本产出/增量）
EVENTS_CSV = os.path.join(APP_DATA, "policy_events.csv")  # 人工整理的政策事件
OVERSEAS_DIR = os.path.join(DATA_DIR, "指数")
GOLD_BRENT_CSV = os.path.join(APP_DATA, "gold_brent.csv")   # 黄金 / 布伦特原油             # 标普/道指/纳指/恒生 长历史日线

# ADV 中国宏观数据（external，与 financial-charts 共用）
ADV_MACRO_PATH = "/Users/kunrongcai/Desktop/LLM-AI Agent/Deepseek/Skill研究/financial-charts/js/china-macro.js"
if not os.path.exists(ADV_MACRO_PATH):
    _adv_alt = os.path.expanduser("~/.adv/js/china-macro.js")
    if os.path.exists(_adv_alt):
        ADV_MACRO_PATH = _adv_alt

# 本地数据文件
PANEL_PARQUET = os.path.join(DATA_DIR, "panel_csi_all_full.parquet")  # 全A面板 2016-2026
TECH_PARQUET = os.path.join(DATA_DIR, "tech_indicators_all.parquet")   # 38技术指标 2021-2026
MARGIN_BAK = os.path.join(DATA_DIR, "alt_margin_tushare.csv")          # 融资融券(原始)
MARGIN_CACHE = os.path.join(CACHE_DIR, "margin_full.csv")              # 融资融券(已增量更新)
MARGIN_CSV = MARGIN_CACHE if os.path.exists(MARGIN_CACHE) else MARGIN_BAK
HK_HOLD_CSV = os.path.join(DATA_DIR, "alt_hk_hold_tushare.csv")        # 港股通持股(北向代理)
MONEYFLOW_CSV = os.path.join(DATA_DIR, "alt_moneyflow_tushare.csv")    # 资金流
ETF_DAILY_CSV = os.path.join(DATA_DIR, "alt_etf_daily.csv")            # ETF日线
ETF_BASIC_CSV = os.path.join(DATA_DIR, "etf_basic.csv")                # ETF基本信息
FUND_SHARE_DIR = os.path.join(DATA_DIR, "ml_data", "fund_share")       # 场内基金份额（国家队）
DC_HOT_CSV = os.path.join(DATA_DIR, "alt_dc_hot.csv")                  # 东财热股榜
THS_HOT_CSV = os.path.join(DATA_DIR, "alt_ths_hot.csv")                # 同花顺热度
LIMIT_CPT_CSV = os.path.join(DATA_DIR, "alt_limit_cpt.csv")            # 涨停板（概念口径）
LIMIT_DAILY_CSV = os.path.join(CACHE_DIR, "limit_daily.csv")            # 真实涨停/跌停家数（日）
TOP_LIST_CSV = os.path.join(DATA_DIR, "alt_top_list_tushare.csv")      # 龙虎榜
CYQ_CSV = os.path.join(DATA_DIR, "alt_cyq_perf_tushare.csv")           # 筹码分布
STOCK_BASIC_CSV = os.path.join(DATA_DIR, "stock_basic_all.csv")        # 股票信息(行业/市场)
CONS_CSI_CSV = os.path.join(DATA_DIR, "cons_csi_all.csv")              # 中证全指成分
FUND_MONTHLY_CSV = os.path.join(DATA_DIR, "fundamental_factors_monthly.csv")
MACRO = {  # 宏观
    "cpi": os.path.join(DATA_DIR, "alt_macro_cpi.csv"),
    "gdp": os.path.join(DATA_DIR, "alt_macro_gdp.csv"),
    "m2": os.path.join(DATA_DIR, "alt_macro_m2.csv"),
    "pmi": os.path.join(DATA_DIR, "alt_macro_pmi.csv"),
    "ppi": os.path.join(DATA_DIR, "alt_macro_ppi.csv"),
    "sf": os.path.join(DATA_DIR, "alt_macro_sf.csv"),
    "lpr": os.path.join(DATA_DIR, "alt_lpr.csv"),
    "shibor": os.path.join(DATA_DIR, "alt_shibor.csv"),
}

# 指数中文名 → 代码列名
INDEX_COLS = ["上证指数", "深证成指", "创业板指", "科创50", "中证500", "中证1000", "中证2000", "沪深300"]

# ---- 规范牛熊周期划分（研报口径，用于校准与标注）----
# 每轮: (牛市起点, 牛市高点, 熊市低点, 类型, 主线)
CANONICAL_CYCLES = [
    ("2005-06-06", "2007-10-16", "2008-10-28", "全面牛", "周期+大金融"),
    ("2008-10-28", "2009-08-04", "2012-12-04", "反弹牛", "基建→消费→科技"),
    ("2012-12-04", "2015-06-12", "2016-01-27", "全面牛", "TMT"),
    ("2016-01-27", "2018-01-26", "2019-01-04", "结构牛", "价值/消费龙头"),
    ("2019-01-04", "2021-02-18", "2022-04-27", "结构牛", "新能源+核心资产"),
    ("2024-02-05", None, None, "进行中", "924政策+AI/算力"),
]

# ---- 牛熊分段算法阈值 ----
BB_THRESHOLD = 0.20        # 20% 回撤/回升触发切换
BB_MIN_DAYS = 40           # 最小持续交易日（过滤早期噪声）

# ---- 指标分位窗口 ----
PERCENTILE_WINDOW_YEARS = 10   # 默认近10年分位

# ---- 阈值常量（研报口径）----
TH = {
    "pe_top": 56.5,                 # 全A PE(TTM) 顶部锚（56-57倍）
    "risk_premium_1sig": None,      # 风险溢价均值-1σ（运行时计算）
    "discount_safe": 10.0,          # 折现率 ≥10% 安全
    "discount_warn": 8.0,           # <8% 边打边撤
    "discount_extreme": 6.7,        # 全股票折现率下限
    "margin_buy_pct_hi": 0.95,      # 融资买入占比半年分位 >95% 卖出
    "margin_buy_pct_lo": 0.05,      # <5% 买入
    "north_outflow": 50e8,          # 北向连续5日净流出>50亿 止盈
    "sector_pos_lo": 0.10,          # 机构持仓历史10%分位以下=左侧
    "sector_val_hi": 0.90,          # PE/PB 90%分位以上=风险钝化
    "concentration_hi": 0.40,       # 主线成交占比>40% 拥挤
    "ema20_dev": -0.08,             # EMA20乖离率<-8% 超跌
}
