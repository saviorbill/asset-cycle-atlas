# -*- coding: utf-8 -*-
"""统一的 10 / 20 日评分与倾向 → web/recommendations.js

只读取 hist_stats / ml_model / models_extra，顶部结论和历史统计表共同使用本文件。
指数：规则分 = 40% × 10 日收缩胜率 + 60% × 20 日收缩胜率；
      综合分 = 65% × 规则分 + 35% × 模型 20 日上行估计。
板块：技术、基本面、情绪、规则分、20 日横截面模型排名等权。
"""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def read_generated(name):
    raw = (WEB / (name + ".js")).read_text(encoding="utf-8")
    key = "window.WAW." + name + "="
    start = raw.find(key)
    if start < 0:
        raise ValueError("无法读取 " + name)
    return json.loads(raw[start + len(key):].rstrip().rstrip(";"))


def shrink(win):
    """独立段数越少，胜率越向 50% 收缩。"""
    return 50 + (float(win["win"]) - 50) * int(win["seg"]) / (int(win["seg"]) + 3.0)


def rule_score(win):
    d10, d20 = (win or {}).get("d10") or {}, (win or {}).get("d20") or {}
    if not d10.get("ok") or not d20.get("ok"):
        return None
    r10, r20 = shrink(d10), shrink(d20)
    return {
        "rule": 0.4 * r10 + 0.6 * r20,
        "rule10": r10,
        "rule20": r20,
        "d10": d10,
        "d20": d20,
    }


def tendency_for(item, score, w20):
    """所有资产共用同一倾向规则；分数高但样本不足时仍只列观察。"""
    tech, fund = item.get("tech"), item.get("fund")
    if score is None or tech is None:
        return "—"
    if tech <= 35 and (fund is None or fund <= 35):
        return "偏减仓"
    if (score >= 58 and tech >= 60 and (fund is None or fund >= 40)
            and w20 and w20.get("ok") and w20.get("win", 0) >= 55
            and int(w20.get("seg") or 0) >= 8):
        return "偏买入"
    return "观察"


def confidence_for(rule, model20):
    segments = min(int(rule["d10"].get("seg") or 0), int(rule["d20"].get("seg") or 0))
    if model20 is None or segments < 5:
        return "低"
    if segments >= 12 and model20 >= 45:
        return "中"
    if segments >= 8:
        return "中偏低"
    return "低"


def build_indices(hist, ml):
    rows = []
    predictions = ml.get("all_preds") or {}
    for item in hist.get("indices", []):
        name = item["name"]
        rule = rule_score(item.get("win"))
        if rule is None:
            continue
        p20 = (predictions.get(name) or {}).get("20") or {}
        model20 = p20.get("pup")
        # 缺少模型时保留可复算的规则分，并在表内将模型显示为“—”。
        score = 0.65 * rule["rule"] + 0.35 * float(model20) if model20 is not None else rule["rule"]
        tendency = tendency_for(item, score, rule["d20"])
        rows.append({
            "name": name,
            "score": round(score, 1),
            "tendency": tendency,
            "action": tendency,
            "confidence": confidence_for(rule, model20),
            "components": {
                "rule": round(rule["rule"], 1),
                "rule10": round(rule["rule10"], 1),
                "rule20": round(rule["rule20"], 1),
                "model20": None if model20 is None else round(float(model20), 1),
                "win10": round(float(rule["d10"]["win"]), 1),
                "win20": round(float(rule["d20"]["win"]), 1),
                "segments10": int(rule["d10"]["seg"]),
                "segments20": int(rule["d20"]["seg"]),
                "median10": None,
                "median20": p20.get("p50"),
            },
        })
    # 10 日中位与 20 日模型来自不同字段，单独补齐，保持组件含义清楚。
    for row in rows:
        p10 = (predictions.get(row["name"]) or {}).get("10") or {}
        row["components"]["median10"] = p10.get("p50")
    rows.sort(key=lambda x: x["score"], reverse=True)
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank
    return rows


def build_sectors(hist, extra):
    rank = {x["name"]: x.get("score") for x in (extra.get("rank") or {}).get("sectors", [])}
    rows = []
    for item in hist.get("sectors", []):
        rule = rule_score(item.get("win"))
        if rule is None:
            continue
        model_rank = rank.get(item["name"])
        parts = [item.get("tech"), item.get("fund"), item.get("sent"), rule["rule"], model_rank]
        values = [float(v) for v in parts if v is not None]
        if not values:
            continue
        score = sum(values) / len(values)
        tendency = tendency_for(item, score, rule["d20"])
        rows.append({
            "name": item["name"],
            "score": round(score, 1),
            "tendency": tendency,
            "action": tendency,
            "components": {
                "tech": item.get("tech"),
                "fund": item.get("fund"),
                "sent": item.get("sent"),
                "rule": round(rule["rule"], 1),
                "rule10": round(rule["rule10"], 1),
                "rule20": round(rule["rule20"], 1),
                "model_rank": model_rank,
                "win10": round(float(rule["d10"]["win"]), 1),
                "win20": round(float(rule["d20"]["win"]), 1),
                "segments10": int(rule["d10"]["seg"]),
                "segments20": int(rule["d20"]["seg"]),
                "n_parts": len(values),
            },
        })
    rows.sort(key=lambda x: x["score"], reverse=True)
    for rank_no, row in enumerate(rows, 1):
        row["rank"] = rank_no
    return rows


def main():
    hist = read_generated("hist_stats")
    ml = read_generated("ml_model")
    extra = read_generated("models_extra")
    conclusion = read_generated("conclusion")

    indices = build_indices(hist, ml)
    sectors = build_sectors(hist, extra)
    index_buy = sum(x["tendency"] == "偏买入" for x in indices)
    sector_buy = sum(x["tendency"] == "偏买入" for x in sectors)
    payload = {
        "asof": max(str(x) for x in [ml.get("asof"), hist.get("asof"), conclusion.get("asof")] if x),
        "summary": {
            "index_count": len(indices),
            "sector_count": len(sectors),
            "index_buy": index_buy,
            "sector_buy": sector_buy,
            "sector_eligible": sector_buy,
            "stage": (conclusion.get("stage") or {}).get("label"),
            "n_bear": conclusion.get("n_bear"),
            "n_total": conclusion.get("n_total"),
        },
        "indices": indices,
        "sectors": sectors,
        "method": {
            "horizons": [10, 20],
            "rule": "40% × 10日收缩胜率 + 60% × 20日收缩胜率",
            "index": "65% × 10/20日规则分 + 35% × 模型20日上行估计",
            "sector": "技术、基本面、情绪、10/20日规则分、20日模型排名等权",
        },
    }
    out = WEB / "recommendations.js"
    out.write_text(
        "/* generated by src/build_recommendations.py — do not edit */\n"
        "window.WAW=window.WAW||{};window.WAW.recommendations="
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )
    print("→", out)
    print("指数：", "、".join("%s %.1f %s" % (x["name"], x["score"], x["tendency"]) for x in indices))
    print("偏买入指数 %d 个 / 板块 %d 个" % (index_buy, sector_buy))
    print("板块前五：", "、".join("%s %.1f %s" % (x["name"], x["score"], x["tendency"]) for x in sectors[:5]))


if __name__ == "__main__":
    main()
