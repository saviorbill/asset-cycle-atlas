# -*- coding: utf-8 -*-
"""一键更新：重算市场聚合 + 行业主题 + 生成网站数据。

用法：python3 run.py
"""
import os, sys, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "src")
PY = "/usr/bin/python3"


def run(script):
    print(f"\n===== 运行 {script} =====")
    r = subprocess.run([PY, script], cwd=SRC)
    if r.returncode != 0:
        print(f"[失败] {script}")
        sys.exit(r.returncode)


if __name__ == "__main__":
    run("build_market_agg.py")
    run("build_industry.py")
    run("build_web_data.py")
    run("build_nsf.py")
    run("build_state_score.py")
    run("build_fundamentals.py")
    run("build_hist_stats.py")
    run("build_iv_index.py")
    run("build_ml_model.py")
    run("build_models_extra.py")
    run("build_conclusion.py")
    run("log_recommendation.py")
    run("score_recommendations.py")
    print("\n✅ 全部完成。")
    print("   网站应用：打开 web/index.html")
    print("   复盘报告：dashboard/review_report.html")
