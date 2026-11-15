# Where are we? · 大类金融资产周期复盘

用同一套框架（周期定位 → 驱动及反转 → 指标监测 → 当前映射）回答一个问题：**现在，各类金融资产走到了周期的哪一步？**

> 当前已实现 **A股**（7 大指数 K 线、牛熊阶段、历史相似期、指标分位）；**债券 / 商品 / 其他资产** 已在导航中预留，规划中。

前端是纯静态网站（HTML + 原生 JS + ECharts），后端是 Python 数据管道，**不需要 Node、不需要打包**。

![当前观察](web/preview-current.png)

> 首页介绍 · 当前观察 · 资产周期 · 金融学院 四大模块；A股已上线，涵盖 7 大指数 K 线、牛熊阶段高亮、历史相似期类比、情景矩阵、指标分位。

---

## 快速开始（克隆后）

**只看网站**（无需 Python）：
```bash
# 双击打开，或用任意静态服务器
open web/index.html
```

**跑数据管道**（可选）：
```bash
pip install -r requirements.txt
export DATAHUB_API_KEY=你的_key        # 在线增量更新需要（datahubco tushare 网关）
cd src && python3 build_web_data.py    # 重新生成 web/data.js
```

---

## 一、用 VSCode 打开

1. VSCode → `File > Open Folder…` → 选 `ashare-fupan` 目录
2. 建议装两个扩展：
   - **Live Server**（右键 `web/index.html` → Open with Live Server，热刷新，推荐）
   - **Python**（跑数据脚本用）
3. 选解释器：`⌘⇧P` → `Python: Select Interpreter` → 选 `/usr/bin/python3`（系统 Python 3.9，已装 pandas/pyarrow/openpyxl）

---

## 二、目录结构（重点看前两个）

```
ashare-fupan/
├── web/                       ★ 前端（改界面就改这里）
│   ├── index.html             页面骨架 + 顶部导航 + 各视图
│   ├── style.css              全部样式（配色/字体/卡片/工具栏）
│   ├── app.js                 全部交互逻辑（图表渲染/导航/相似度计算）
│   ├── data.js                【自动生成】所有数据，window.WAW = {...}
│   └── echarts.min.js         ECharts 库（本地，勿动）
│
├── src/                       ★ 数据管道（改数据/指标就改这里）
│   ├── build_web_data.py      主数据生成器 → 输出 web/data.js
│   ├── update_indicators.py   增量更新指标到最新（抓 datahubco API）
│   ├── build_market_agg.py    全A面板 → cache/market_daily.parquet
│   ├── build_industry.py      行业/主题聚合 → cache/theme_daily.parquet
│   ├── config.py              路径 + 阈值 + 牛熊周期定义
│   ├── cycle_events.py        牛熊事件/政策事件（改事件标注改这里）
│   ├── cycle.py               牛熊峰谷分段（ZigZag）
│   ├── clock.py / scoring.py / sentiment.py / narrative.py   其他分析模块
│   └── fetch_api_data.py      IPO/减持等月度数据抓取
│
├── cache/                     中间数据（parquet，自动生成）
├── docs/                      设计文档、宏观相关性分析
├── notes/                     研报笔记
├── data_index_daily.csv       8大指数日线（1990起，收盘价）
├── run.py                     一键重算：build_market_agg → build_industry → build_web_data
└── README.md                  本文件
```

> **数据源在项目外**：`/Users/kunrongcai/Desktop/A股数据/`（面板/宏观/融资等 parquet/csv）。改数据要会读这些文件。

---

## 三、三种日常工作流

### ① 只改界面（最快，不用跑 Python）
改 `web/index.html`、`web/style.css`、`web/app.js` → 用 Live Server 或直接双击 `web/index.html` 看效果。
- 改标题/文案 → `index.html`
- 改配色/字体/间距 → `style.css` 顶部 `:root` 变量（`--navy` `--gold` `--bg` `--serif` 等）
- 改图表逻辑/交互 → `app.js`（各 `renderXxx()` 函数）

### ② 改了指标/周期/事件后重新生成数据
```bash
cd src
/usr/bin/python3 build_web_data.py      # 最常用：只重算 web/data.js（几秒）
# 如果改了面板聚合逻辑才需要：
/usr/bin/python3 build_market_agg.py    # 较慢，几分钟
/usr/bin/python3 build_industry.py
```
或一键（全部重算，较慢）：
```bash
/usr/bin/python3 run.py
```

### ③ 把数据更新到最新日期
```bash
cd src
/usr/bin/python3 update_indicators.py   # 抓 datahubco API，增量更新指标（约5-8分钟）
/usr/bin/python3 build_web_data.py      # 重新生成 data.js
```
> ⚠️ 接口必须设 `NO_PROXY='*'`（`update_indicators.py` 里已写好），否则被代理拦。

---

## 四、常见修改对照表

| 想改什么 | 改哪个文件 |
|---|---|
| 标题 / 导航文案 / 首页内容 | `web/index.html` |
| 配色、字体、卡片样式、工具栏 | `web/style.css`（顶部 `:root` 变量） |
| K线/相似图/仪表盘的渲染逻辑 | `web/app.js` 里对应 `renderHistory / renderSimilarity / renderDashboard` |
| 牛熊周期分段 | `src/build_web_data.py` 的 `INDEX_CYCLES` |
| 政策/牛熊事件标注 | `src/cycle_events.py` 的 `POLICY_EVENTS` |
| 指标列表（右侧"关键指标"） | `web/app.js` 的 `INDS` 数组 |
| 指标计算方式 | `src/build_market_agg.py`（市场类）/ `src/build_web_data.py` |
| K线数据来源 | `src/build_web_data.py` 的 `load_kline()` + `KLINE_FILES` |
| 历史相似度算法 | `web/app.js` 的 `computeSimilarity()` |

---

## 五、几个关键点（避免踩坑）

1. **`web/data.js` 是生成物**，不要手改——改完会被下次 `build_web_data.py` 覆盖。要改数据就改 `src/` 里的脚本再重跑。
2. **页面直接双击 `web/index.html` 就能开**（数据用 `<script>` 加载，file:// 可用）；但推荐 Live Server，改完自动刷新。
3. **K线 Excel 在桌面**：`~/Desktop/K线导出_000001_日线数据.xlsx` 等 7 个文件。`load_kline()` 读它们 + 腾讯接口补最新几天；文件缺失时会用 `data_index_daily.csv` 收盘价兜底。
4. **API Key 不写在代码里**：通过环境变量 `DATAHUB_API_KEY` 提供（`src/fetch_api_data.py` / `src/update_indicators.py` 读取）。开源时切勿提交真实 Key。
5. **图表尺寸**：每个图表容器 `<div class="chart" id="...">` 的高度在 CSS 里定义（`.chart` / `.chart.mid`），"全部"对比图会动态设高度。
6. **改完 app.js 建议先跑一下语法检查**（VSCode 会标红），页面按 `⌘⇧R` 刷新看控制台报错。

---

## 六、页面结构速览（5 个视图）

| 视图 | 内容 |
|---|---|
| 首页介绍 | Hero + 资产选择（股/债/商品/其他）+ 研究框架四支柱 |
| 当前观察 | 仪表盘（状态+4分位）+ 历史相似期（归一化对比+中位路径+情景矩阵）+ 关键指标 |
| 资产周期 → A股 | 历史复盘：7 指数 K 线（日/周/月）、牛熊阶段高亮、成交额、事件标注 |
| 宏观环境 | 24 项宏观指标 + 与牛熊相关性 |
| 金融学院 | 占位（可做成方法论/指标字典） |

---

## 七、环境与数据源

- Python：`/usr/bin/python3`（pandas / numpy / pyarrow / openpyxl / PIL 已装）
- 本地数据：`/Users/kunrongcai/Desktop/A股数据/`
- 在线增量：`datahubco.com` tushare 网关（`update_indicators.py`）
- 行情兜底：腾讯 `web.ifzq.gtimg.cn`（`_fetch_tencent_tail`）

---

## 许可证

[MIT](LICENSE)

## 免责声明

本项目仅用于**研究与学习**，所有内容（含历史数据、指标、相似度、情景矩阵）**不构成任何投资建议**。
历史规律不代表未来，市场有风险，决策请独立判断。

---

## 路线图

- [x] **A股**：7 大指数 K 线（日/周/月）、牛熊阶段划分与高亮、成交额、事件标注
- [x] 历史相似期类比（归一化折线 + 后30日中位路径 + 情景矩阵 P10/P50/P90）
- [x] 指标监测（PE/PB/融资/成交/集中度/200MA广度/新高新低/外资/IPO/减持）
- [x] 宏观环境（24 项宏观指标 + 与牛熊相关性）
- [ ] **债券**：国债收益率曲线、信用利差、股债性价比（ERP）
- [ ] **商品**：南华商品指数、CRB、金银铜油
- [ ] **其他**：汇率、REITs、另类资产
- [ ] 金融学院：方法论与指标字典
