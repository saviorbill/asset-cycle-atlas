# -*- coding: utf-8 -*-
"""生成当前观察的 20 日历史相似情景与样本外检验。

口径固定：20 日归一化对数价格路径、RMSE、10 个间隔至少 20 日的相似段。
回测使用非重叠月度锚点，候选段结局必须在锚点前已经可观察，避免未来函数。
"""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

ROOT = Path(__file__).resolve().parents[1]
DAILY = ROOT / "data" / "index_daily.csv"
OUT = ROOT / "web" / "pattern_scenarios.js"
RESEARCH = ROOT / "research"
L = H = 20
K = 10
CANDIDATE_START = pd.Timestamp("2000-01-01")
EVAL_START = pd.Timestamp("2005-01-01")
MIN_CANDIDATES = 200


def normalized_windows(close, length=L):
    windows = sliding_window_view(np.log(close), length + 1)
    return windows - windows[:, [0]]


def select_spaced(endpoints, dist, k=K, spacing=H):
    chosen = []
    for idx in np.argsort(dist, kind="mergesort"):
        if not np.isfinite(dist[idx]):
            continue
        endpoint = int(endpoints[idx])
        if all(abs(endpoint - old) >= spacing for old in chosen):
            chosen.append(endpoint)
            if len(chosen) == k:
                break
    return chosen


def current_match(s, name):
    close = s.to_numpy(dtype=float)
    dates = s.index
    t = len(s) - 1
    windows = normalized_windows(close)
    fwd = close[H:] / close[:-H] - 1
    endpoints = np.arange(L, t - H + 1)
    endpoints = endpoints[dates[endpoints] >= CANDIDATE_START]
    candidate = windows[endpoints - L]
    dist = np.sqrt(np.mean((candidate - windows[t - L]) ** 2, axis=1))
    chosen = select_spaced(endpoints, dist)
    if len(chosen) < K:
        raise ValueError(f"{name} 可用相似段不足：{len(chosen)}")
    paths = np.asarray([close[e:e + H + 1] / close[e] - 1 for e in chosen])
    rets = paths[:, -1]
    matches = []
    for rank, endpoint in enumerate(chosen, 1):
        di = int(np.where(endpoints == endpoint)[0][0])
        matches.append({
            "rank": rank,
            "window_start": dates[endpoint - L].strftime("%Y-%m-%d"),
            "match_end": dates[endpoint].strftime("%Y-%m-%d"),
            "distance": round(float(dist[di]), 5),
            "next20": round(float(fwd[endpoint] * 100), 2),
        })
    return {
        "name": name,
        "latest_close": round(float(close[-1]), 4),
        "current20": round(float((close[-1] / close[-L - 1] - 1) * 100), 2),
        "n": K,
        "mean_distance": round(float(np.mean([dist[np.where(endpoints == e)[0][0]] for e in chosen])), 5),
        "next5": round(float(np.median(paths[:, 5]) * 100), 2),
        "next10": round(float(np.median(paths[:, 10]) * 100), 2),
        "median": round(float(np.median(rets) * 100), 2),
        "mean": round(float(np.mean(rets) * 100), 2),
        "q10": round(float(np.quantile(rets, 0.1) * 100), 2),
        "q25": round(float(np.quantile(rets, 0.25) * 100), 2),
        "q75": round(float(np.quantile(rets, 0.75) * 100), 2),
        "q90": round(float(np.quantile(rets, 0.9) * 100), 2),
        "up_rate": round(float(np.mean(rets > 0) * 100), 1),
        "max_dd_median": round(float(np.median(np.min(paths, axis=1)) * 100), 2),
        "max_dd_q10": round(float(np.quantile(np.min(paths, axis=1), 0.1) * 100), 2),
        "path": {
            "days": list(range(H + 1)),
            "median": [round(float(x * 100), 3) for x in np.median(paths, axis=0)],
            "q25": [round(float(x * 100), 3) for x in np.quantile(paths, 0.25, axis=0)],
            "q75": [round(float(x * 100), 3) for x in np.quantile(paths, 0.75, axis=0)],
        },
        "matches": matches,
    }


def backtest(s, name):
    close = s.to_numpy(dtype=float)
    dates = s.index
    n = len(s)
    windows = normalized_windows(close)
    fwd = close[H:] / close[:-H] - 1
    records = []
    for t in range(L + H + MIN_CANDIDATES, n - H, H):
        if dates[t] < EVAL_START:
            continue
        endpoints = np.arange(L, t - H + 1)
        endpoints = endpoints[dates[endpoints] >= CANDIDATE_START]
        if len(endpoints) < MIN_CANDIDATES:
            continue
        candidate = windows[endpoints - L]
        dist = np.sqrt(np.mean((candidate - windows[t - L]) ** 2, axis=1))
        chosen = select_spaced(endpoints, dist)
        if len(chosen) < K:
            continue
        analogue = fwd[chosen]
        records.append({
            "actual": float(fwd[t]),
            "predicted": float(np.mean(analogue)),
            "baseline": float(np.mean(fwd[endpoints])),
        })
    if not records:
        return {"name": name, "n": 0}
    frame = pd.DataFrame(records)
    actual = frame.actual.to_numpy()
    pred = frame.predicted.to_numpy()
    baseline = frame.baseline.to_numpy()
    mae = float(np.mean(np.abs(actual - pred)))
    base_mae = float(np.mean(np.abs(actual - baseline)))
    corr = float(np.corrcoef(pred, actual)[0, 1]) if np.std(pred) > 0 else None
    return {
        "name": name,
        "n": int(len(frame)),
        "direction": round(float(np.mean((pred > 0) == (actual > 0)) * 100), 1),
        "actual_up": round(float(np.mean(actual > 0) * 100), 1),
        "pearson": None if corr is None or not np.isfinite(corr) else round(corr, 3),
        "mae_skill": round(float((1 - mae / base_mae) * 100), 1) if base_mae else None,
    }


def read_research():
    models = []
    global_value = None
    fp = RESEARCH / "model_comparison_summary.csv"
    if fp.exists():
        frame = pd.read_csv(fp)
        wanted = ["analog_own", "ridge_own", "logistic_own"]
        labels = {"analog_own": "历史相似段", "ridge_own": "Ridge · 自身", "logistic_own": "Logistic · 自身"}
        for model in wanted:
            row = frame[frame.model == model]
            if not row.empty:
                r = row.iloc[0]
                models.append({
                    "model": model,
                    "label": labels[model],
                    "direction": round(float(r.median_direction_accuracy * 100), 1),
                    "auc": round(float(r.median_auc * 100), 1),
                })
    fp = RESEARCH / "global_value_summary.csv"
    if fp.exists():
        r = pd.read_csv(fp).iloc[0]
        global_value = {
            "n": int(r.paired_direction_tests),
            "improved": int(r.direction_improved),
            "declined": int(r.direction_declined),
            "unchanged": int(r.direction_unchanged),
            "mae_tests": int(r.paired_mae_tests),
            "mae_improved": int(r.mae_improved),
        }
    return models, global_value


def main():
    frame = pd.read_csv(DAILY, parse_dates=["date"]).set_index("date").sort_index()
    frame = frame[~frame.index.duplicated(keep="last")].replace(0, np.nan)
    current, tests = [], []
    for name in frame.columns:
        s = frame[name].dropna().astype(float)
        if len(s) < L + H + MIN_CANDIDATES + K:
            continue
        current.append(current_match(s, name))
        tests.append(backtest(s, name))
    models, global_value = read_research()
    payload = {
        "asof": frame.index[-1].strftime("%Y-%m-%d"),
        "method": {
            "lookback": L, "horizon": H, "analogues": K,
            "candidate_start": CANDIDATE_START.strftime("%Y-%m-%d"),
            "evaluation_start": EVAL_START.strftime("%Y-%m-%d"),
            "distance": "归一化对数价格路径 RMSE",
            "note": "非重叠月度样本外锚点；候选结局必须在锚点前已可观察。",
        },
        "current": current,
        "backtest": tests,
        "model_comparison": models,
        "global_value": global_value,
        "data_note": "近期指数行情已按 Tushare 校验副本修正；原始项目数据未改写。",
    }
    OUT.write_text(
        "/* generated by src/build_pattern_scenarios.py — do not edit */\n"
        "window.WAW=window.WAW||{};window.WAW.pattern_scenarios="
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )
    print(f"asof {payload['asof']} → {OUT}")
    for row in current:
        print("%-6s 20日中位 %+6.2f%%  区间 %+6.2f%%～%+6.2f%%  浮亏中位 %6.2f%%" %
              (row["name"], row["median"], row["q25"], row["q75"], row["max_dd_median"]))


if __name__ == "__main__":
    main()
