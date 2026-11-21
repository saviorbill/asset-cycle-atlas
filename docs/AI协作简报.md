# AI 协作简报（给 Kimi / 其他 AI 助手）

> 把本文件完整发给 AI，或直接让它读仓库里的 `docs/AI协作简报.md`。

---

## 1. 项目是什么

**「Where are we?」** —— 大类金融资产周期复盘网站。

用一套框架（**周期定位 → 驱动及反转 → 指标监测 → 当前映射**）回答：**现在各类资产走到了周期的哪一步？**
当前已实现 **A股**（7 大指数 K 线、牛熊阶段、历史相似期、状态打分/ML 概率、指标分位）；债券/商品/其他资产在导航中预留。

---

## 2. 代码与数据在哪

| 项 | 位置 |
|---|---|
| GitHub（公开） | https://github.com/saviorbill/asset-cycle-atlas |
| 本地项目 | `/Users/kunrongcai/Desktop/LLM-AI Agent/Deepseek/Skill研究/ashare-fupan` |
| 原始数据（**不在 git 里**） | `/Users/kunrongcai/Desktop/A股数据/` |
| 中间缓存 | `~/Desktop/A股数据/应用数据/cache/` |
| 指数 K 线 xlsx | `~/Desktop/A股数据/应用数据/index_kline/` |
| 指数收盘 csv | `~/Desktop/A股数据/应用数据/index_daily.csv` |

> ⚠️ **没有原始数据也能改前端**（`web/` 下的 `data*.js` 是已生成的），但**重算数据**必须有 `~/Desktop/A股数据/`。

---

## 3. 技术栈

- **前端**：纯静态 HTML + 原生 JS + ECharts 5（`web/echarts.min.js`），**无框架、无构建、无 npm**
- **数据**：Python 3.9（`/usr/bin/python3`，已装 pandas / pyarrow / openpyxl / numpy）
- **部署**：GitHub Actions → GitHub Pages（`web/` 目录）
- **在线数据接口**：datahubco tushare 网关（`X-API-Key` 走环境变量）

---

## 4. 文件地图

### 前端 `web/`
| 文件 | 职责 |
|---|---|
| `index.html` | 6 个视图：`#view-intro / history / trends / current / macro / academy` |
| `style.css` | 全部样式（配色/字体变量在顶部 `:root`） |
| `app.js` | **全部交互逻辑**（~3600 行，图表渲染、路由、懒加载） |
| `echarts.min.js` | ECharts 库（勿动） |
| `data.js` | **首屏核心数据**（147KB，自动生成） |
| `data-cur.js` / `data-overlay.js` / `data-hist.js` / `data-macro.js` | 按视图懒加载的数据块（自动生成） |
| `data-kline.js` | 7 指数 OHLC 全历史（2.5MB，懒加载，自动生成） |
| `state_score.js` / `hist_stats.js` / `ml_model.js` / `models_extra.js` / `conclusion.js` / `cycle_stats.js` / `cycle_analysis.js` / `pullback_stats.js` | 按视图懒加载的模块（自动生成） |

### 数据管道 `src/`（44 个脚本，核心几个）
| 脚本 | 作用 |
|---|---|
| `build_web_data.py` | **主生成器**：产出上面所有 `data*.js` |
| `build_hist_stats.py` | 历史统计/状态打分 → `hist_stats.js` |
| `build_state_score.js` 来源 | `build_state_score.py` |
| `build_ml_model.py` | ML 概率模型 → `ml_model.js` |
| `build_market_agg.py` | 全A面板 → `cache/market_daily.parquet` |
| `update_indicators.py` | **增量更新**指标到最新交易日（联网） |
| `cycle_events.py` | 政策/产品/关键人物事件（叙事用，**纯手写数据**） |
| `config.py` | 路径 + 阈值 + 牛熊周期定义 |
| `run.py` | 一键全量重算 |

---

## 5. 数据流

```
~/Desktop/A股数据/ (面板/融资/宏观/xlsx)
        │
        ├─ build_market_agg.py ──► cache/market_daily.parquet
        │        └─ update_indicators.py（联网增量补最新交易日）
        │
        ├─ build_web_data.py ──► web/data.js + data-cur/overlay/hist/macro + data-kline.js
        ├─ build_hist_stats.py ──► web/hist_stats.js
        ├─ build_ml_model.py ──► web/ml_model.js
        └─ build_state_score.py ──► web/state_score.js
```

**重建顺序**（很重要）：
```
build_market_agg → update_indicators → build_web_data
                 → build_hist_stats → build_state_score → build_ml_model
```

---

## 6. 必须遵守的约定（容易踩雷）

1. **`web/data*.js`、`hist_stats.js`、`state_score.js`、`ml_model.js` 等是生成物，绝对不要手改** —— 改完会被下次构建覆盖。要改数据就改 `src/` 里的脚本再重跑。
2. **`cycle_events.py` 是手写数据**（政策/产品/关键人物事件），可以放心直接编辑。
3. **懒加载架构**：`data*.js` 和 8 个模块**不写在 index.html 里**，由 `app.js` 的 `ensureAssets()` 按视图加载（白名单在 `app.js` 的 `CUR_ASSETS / HIST_ASSETS / MACRO_ASSETS / TRENDS_ASSETS`）。**新增数据块/模块必须同步改白名单**。
4. **配色语义**：全站 A 股口径 **红涨绿跌**（`--rise:#B8402F` / `--fall:#2E7D5B`）；主色 `--navy:#0E1F35`、`--gold:#A8875B`。
5. **字体**：
   - 正文/表格/导航：`--sans`（系统无衬线），**字号层级：正文 14px、表格 td 12.5px、th 12px、导航/菜单 13.5px**
   - 只有**标题**（h1 28px / h2 23px）和总结用 `--serif`（Noto Serif SC）
   - 不要给子元素加粗时忘了父级 `font-weight` 会继承（曾因此出现子菜单变粗的 bug）
6. **"数据截至"只保留每页大标题旁一处**，其余由 CSS 隐藏（`#concl-asof` 等）。

---

## 7. 常用命令

```bash
cd "/Users/kunrongcai/Desktop/LLM-AI Agent/Deepseek/Skill研究/ashare-fupan"

# 只重算网站数据（最常用，几秒）
cd src && /usr/bin/python3 build_web_data.py

# 全量重算（较慢）
/usr/bin/python3 run.py

# 更新到最新交易日（联网，约 5-8 分钟）
export NO_PROXY='*'
export DATAHUB_API_KEY='<向项目所有者索取>'
/usr/bin/python3 update_indicators.py
/usr/bin/python3 update_index_history.py

# 部署：push 到 main 即自动部署
git add -A && git commit -m "xxx" && git push
```

---

## 8. 已知坑

| 坑 | 说明 |
|---|---|
| **联网必设 `NO_PROXY='*'`** | 否则 akshare/eastmoney 被代理拦截，接口全失败 |
| **`DATAHUB_API_KEY` 走环境变量** | 代码里没有硬编码，开源要求；不要提交真实 key |
| **git push 经常 SSL 超时** | 国内网络问题，重试 2-4 次即可；建议 `git config http.version HTTP/1.1` |
| **K线 Excel 路径会变** | 配置在 `config.py` 的 `INDEX_KLINE_DIR`，缺失时程序会用腾讯/东财接口兜底 |
| **无头浏览器截图验证** | Chrome 路径 `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`，加 `--headless=new --no-sandbox --disable-gpu --virtual-time-budget=16000 --screenshot=...` |
| **不能手改生成物** | 见约定 1 |

---

## 9. 当前状态（截至 2026-11-21）

- 最新提交：`41f4a1f`（字体层级统一）+ `1ad70a8`（当前观察拆分为 资产走势/综合建议 两个子页面）
- 数据截至：**2026-11-20**
- 首屏体积：**443KB（gzip）**，已做数据分块 + 模块懒加载
- 部署：GitHub Pages 自动（CI: JS/Python 语法检查；Deploy: Pages）
- 首页有 5 轮牛熊复盘、7 指数 K 线、历史相似期、状态打分、ML 概率、宏观相关性

---

## 10. 如何验证改动（务必做）

```bash
# 1) 语法检查
node --check web/app.js
/usr/bin/python3 -c "import ast;ast.parse(open('src/build_web_data.py').read())"

# 2) 无头浏览器跑每个视图，抓 JS 报错
BASE="file:///Users/kunrongcai/Desktop/LLM-AI%20Agent/Deepseek/Skill%E7%A0%94%E7%A9%B6/ashare-fupan/web/index.html"
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --no-sandbox \
  --disable-gpu --user-data-dir=/tmp/x --virtual-time-budget=16000 \
  --enable-logging=stderr --v=0 --dump-dom "$BASE#current" 2>&1 | grep -E "Uncaught|TypeError"

# 3) 截图看视觉
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --no-sandbox \
  --disable-gpu --hide-scrollbars --window-size=1440,1200 --virtual-time-budget=16000 \
  --screenshot=/tmp/shot.png "$BASE#current"
```

视图：`#intro`、`#trends`（资产走势）、`#current`（综合建议）、`#history`、`#cycle/<轮次id>`、`#macro`、`#academy`

---

## 11. 协作方式建议

1. **先读再改**：改任何文件前先读全文，不要凭记忆改。
2. **小步提交**：一次只改一件事，改完跑验证，再提交。
3. **改前端为主**：`web/` 是最安全的改动区；改 `src/` 数据脚本要谨慎（会影响生成物）。
4. **不要动**：`echarts.min.js`、`web/fonts/`、生成物 `data*.js`。
5. **给具体位置**：回答时给「文件 + 行号 + 改动前后对比」，方便项目所有者 review。
6. **不确定就先问**：数据口径、周期划分、设计风格这些是项目所有者的主观决定，别自己拍板。
