# -*- coding: utf-8 -*-
"""launchd 启动器。

为什么不直接用 /usr/bin/python3：macOS 的 TCC 只放行被授权的那一个可执行文件。
这里用被授予「完全磁盘访问」的 python3.11 作为父进程，再去调用装了 pandas 的
/usr/bin/python3 —— 子进程一般会继承父进程的 TCC 授权。
"""
import os
import subprocess
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
LOG = "/Users/kunrongcai/Desktop/A股数据/validation/launcher.log"


def log(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


def main():
    try:
        os.listdir(os.path.join("/Users/kunrongcai/Desktop/A股数据", "validation"))
    except Exception as e:
        log("读不到输出目录（TCC 未授权）：%s" % e)
        return
    r = subprocess.run(["/usr/bin/python3", os.path.join(ROOT, "auto_run.py")],
                       cwd=ROOT, capture_output=True, text=True)
    log("auto_run 退出码 %d %s" % (r.returncode, (r.stderr or "")[-300:]))


if __name__ == "__main__":
    main()
