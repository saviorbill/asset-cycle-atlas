# -*- coding: utf-8 -*-
"""补拉申万一级里缺失的行业（2021 新分类，原 index_classify 缓存里没有）。

用法：source ~/.ashare_env && python3 src/fetch_sw_missing.py
落盘：A股数据/ml_data/sw_daily/sw_daily_<code>_<year>.parquet（与既有分片同格式）
凭证只从环境变量 TUSHARE_TOKEN 读取，不写入任何文件。
"""
import os
import sys
import time
from datetime import datetime

os.environ.setdefault("NO_PROXY", "*")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from update_tushare import call, get_pro  # noqa: E402

OUT = os.path.join("/Users/kunrongcai/Desktop/A股数据", "ml_data", "sw_daily")
CODES = ["801950.SI", "801960.SI", "801970.SI", "801980.SI"]   # 煤炭/石油石化/环保/美容护理
START_Y = 2008
END = datetime.now().strftime("%Y%m%d")


def main():
    os.makedirs(OUT, exist_ok=True)
    pro = get_pro()
    t0 = time.time()
    total = 0
    for code in CODES:
        got = 0
        for y in range(START_Y, int(END[:4]) + 1):
            fp = os.path.join(OUT, "sw_daily_%s_%d.parquet" % (code.replace(".", "_"), y))
            if os.path.exists(fp):
                continue
            d = call(pro, "sw_daily", ts_code=code,
                     start_date="%d0101" % y, end_date=min("%d1231" % y, END))
            if d is not None and len(d):
                d.to_parquet(fp, index=False)
                got += len(d)
            time.sleep(0.35)
        print("%s 新增 %d 行" % (code, got))
        total += got
    print("完成：%d 行，%.1f 秒" % (total, time.time() - t0))


if __name__ == "__main__":
    main()
