# -*- coding: utf-8 -*-
"""ADV 制图助手：把 {type,title,labels,series,palette,unit} 编码成 ?chart= 链接。
用法：python3 adv_chart.py  或  import 后调用 make_chart_url(...)
"""
import json, base64, sys

ADV_BASE = "https://saviorbill.github.io/adv/"

def b64url(o):
    s = json.dumps(o, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(s).decode("ascii")

def make_chart_url(type, title, labels, series, palette="consult", unit=None):
    cfg = {"type": type, "title": title}
    if palette: cfg["palette"] = palette
    if unit: cfg["unit"] = unit
    if type == "heatmap":
        cfg["xLabels"] = labels
        cfg["yLabels"] = [s["name"] for s in series]
        cfg["values"] = [s["values"] for s in series]
    else:
        cfg["labels"] = labels
        cfg["series"] = series
    return ADV_BASE + "?chart=" + b64url(cfg)

if __name__ == "__main__":
    # 冒烟测试
    url = make_chart_url("area", "ADV制图冒烟测试：沪深300 vs 中证500",
        ["2020","2021","2022","2023","2024","2025"],
        [{"name":"沪深300","values":[1,1.05,0.9,0.95,1.2,1.35]},
         {"name":"中证500","values":[1,1.1,0.85,1.0,1.25,1.4]}])
    print("URL长度:", len(url))
    print(url)
