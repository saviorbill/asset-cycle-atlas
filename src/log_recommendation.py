# -*- coding: utf-8 -*-
"""把每天的综合建议原样记进台账，供以后检验。

设计原则（重要）：
  1. **只追加，不修改**。同一天重复运行不会覆盖已有记录。
  2. **记录当时的全部输入**：合成分、规则分、模型概率、推荐指数与收盘价、
     板块清单、以及参数版本哈希。没有版本号，改了模型再比对毫无意义。
  3. 台账里不写任何"事后"字段；未来收益由 score_recommendations.py 单独算。

输出：应用数据/validation/recommendations.csv
"""
import hashlib
import json
import os
import sys
from datetime import datetime

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from config import DATA_DIR, INDEX_CSV  # noqa: E402

OUT_DIR = os.path.join(DATA_DIR, "validation")
OUT = os.path.join(OUT_DIR, "recommendations.csv")
# 只哈希「方法」相关文件；生成物每天随数据变，不能用来标识口径
FILES = ["src/build_conclusion.py", "src/build_hist_stats.py", "src/build_ml_model.py",
         "src/build_models_extra.py", "src/build_recommendations.py", "web/app.js"]


def load_js(path, key):
    fp = os.path.join(ROOT, path)
    if not os.path.exists(fp):
        return None
    raw = open(fp, encoding="utf-8").read()
    i = raw.find(key)
    if i < 0:
        return None
    return json.loads(raw[i + len(key):].rstrip().rstrip(";"))


def version_hash():
    h = hashlib.sha1()
    for f in FILES:
        fp = os.path.join(ROOT, f)
        if os.path.exists(fp):
            h.update(open(fp, "rb").read())
    return h.hexdigest()[:12]


def sector_picks(hist, models):
    if not hist or not models:
        return ""
    rk = {x["name"]: x["score"] for x in ((models.get("rank") or {}).get("sectors") or [])}
    rows = []
    for x in hist.get("sectors") or []:
        w = (x.get("win") or {}).get("d60") or {}
        parts = [x.get("tech"), x.get("fund"), x.get("sent"),
                 w.get("win") if w.get("ok") else None, rk.get(x.get("name"))]
        vals = [v for v in parts if v is not None]
        if not vals or not w.get("ok") or w.get("seg", 0) < 8:
            continue
        if x.get("tendency") != "偏买入":
            continue
        rows.append((sum(vals) / len(vals), x["name"]))
    rows.sort(reverse=True)
    return ";".join("%s:%.0f" % (n, s) for s, n in rows[:6])


def main():
    C = load_js("web/conclusion.js", "window.WAW.conclusion=")
    H = load_js("web/hist_stats.js", "window.WAW.hist_stats=")
    M = load_js("web/ml_model.js", "window.WAW.ml_model=")
    X = load_js("web/models_extra.js", "window.WAW.models_extra=")
    R = load_js("web/recommendations.js", "window.WAW.recommendations=")
    if not C:
        print("缺 conclusion.js，先跑 build_conclusion.py")
        return

    os.makedirs(OUT_DIR, exist_ok=True)
    asof = C["asof"]
    df = pd.read_csv(OUT, dtype=str) if os.path.exists(OUT) else None

    # 页面实际展示的是 recommendations 的第一名与 action
    recs = (R or {}).get("indices") or []
    top = recs[0] if recs else None
    best = C.get("best") or {}
    name = (top or {}).get("name") or best.get("name")
    px = pd.read_csv(INDEX_CSV, parse_dates=["date"]).set_index("date").sort_index()
    close = None
    if name and name in px.columns:
        s = px[name].dropna()
        s = s[s.index <= pd.Timestamp(asof)]
        if len(s):
            close = float(s.iloc[-1])

    mix = C.get("mix") or {}
    pred = (M or {}).get("pred") or {}
    # 统一评分：recommendations.js 是页面实际展示的口径
    rec = None
    if R and name:
        rec = next((x for x in (R.get("indices") or []) if x.get("name") == name), None)
    rec_score = rec.get("score") if rec else mix.get("combined")
    p60 = pred.get("60") or {}
    row = dict(
        asof=asof,
        logged_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        version=version_hash(),
        stance=(top or {}).get("action") or C.get("stance", ""),
        tone=C.get("tone", ""),
        stage=(C.get("stage") or {}).get("label", ""),
        index_name=name or "",
        index_close=close,
        combined=rec_score,
        rule=(rec or {}).get("components", {}).get("rule", mix.get("rule")),
        ml_pup=mix.get("ml"),
        confidence=(top or {}).get("confidence") or mix.get("confidence"),
        ml_p50=p60.get("p50"),
        ml_p10=p60.get("p10"),
        ml_p90=p60.get("p90"),
        sectors=(";".join("%s:%.0f" % (x["name"], x["score"])
                          for x in (R.get("sectors") or [])
                          if x.get("tendency") == "偏买入")[:400]) if R else sector_picks(H, X),
        n_bear=C.get("n_bear"),
        n_total=C.get("n_total"),
    )
    if df is not None:
        old = df[df["asof"].astype(str) == asof]
        if len(old):
            i = old.index[0]
            if pd.isna(df.loc[i, "combined"]) or str(df.loc[i, "combined"]) in ("", "None", "nan"):
                for k, v in row.items():
                    if k in df.columns:
                        df.loc[i, k] = v
                df.to_csv(OUT, index=False, encoding="utf-8-sig")
                print("台账已有 %s，补全缺失字段（合成分 %s）" % (asof, row.get("combined")))
            else:
                print("台账已有 %s 的记录，跳过（只追加不覆盖）" % asof)
            return
    out = pd.DataFrame([row]) if df is None else pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    out.to_csv(OUT, index=False, encoding="utf-8-sig")
    print("已记录 %s：%s / %s / 合成分 %s → %s" %
          (asof, row["stance"], row["index_name"], row["combined"], OUT))
    print("台账共 %d 条" % len(out))


if __name__ == "__main__":
    main()
