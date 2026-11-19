# -*- coding: utf-8 -*-
"""开机后自动补齐：16:00 之后、当天还没跑过，就更新数据并重算。

设计成「幂等 + 补齐」：
  - 由 launchd 每 30 分钟叫一次，也可以登录时叫一次。
  - 如果 16:00 之前、或今天已经成功跑过，直接退出（几乎零成本）。
  - 数据更新失败（断网 / token 过期）不阻塞重算，用现有数据算。
  - 重算失败不写成功标记，下一次会重试。

台账记录的是「数据日期」，所以晚跑、隔天跑都不会错，只是少几个样本。
"""
import os
import subprocess
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
PY = "/usr/bin/python3"
VAL = "/Users/kunrongcai/Desktop/A股数据/validation"
SENTINEL = os.path.join(VAL, ".last_auto_run")
LOG = os.path.join(VAL, "auto_run.log")


def log(msg):
    os.makedirs(VAL, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write("[%s] %s\n" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg))


def load_env():
    env = os.environ.copy()
    fp = os.path.expanduser("~/.ashare_env")
    if os.path.exists(fp):
        for line in open(fp, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            line = line.replace("export ", "", 1)
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def main():
    now = datetime.now()
    if now.hour < 16:
        return
    today = now.strftime("%Y-%m-%d")
    if os.path.exists(SENTINEL):
        if open(SENTINEL, encoding="utf-8").read().strip() == today:
            return

    log("开始：%s" % today)
    env = load_env()

    # 1) 更新数据（失败不阻塞）
    r = subprocess.run([PY, os.path.join(ROOT, "src", "update_tushare.py"), "all"],
                       cwd=ROOT, env=env, capture_output=True, text=True)
    if r.returncode != 0:
        log("数据更新失败（沿用现有数据）：%s" % (r.stderr or r.stdout)[-300:])

    # 2) 重算 + 记台账
    r = subprocess.run([PY, os.path.join(ROOT, "run.py")],
                       cwd=ROOT, env=env, capture_output=True, text=True)
    if r.returncode != 0:
        log("重算失败：%s" % (r.stderr or r.stdout)[-500:])
        return

    os.makedirs(VAL, exist_ok=True)
    with open(SENTINEL, "w", encoding="utf-8") as f:
        f.write(today)
    log("完成")


if __name__ == "__main__":
    main()
