# -*- coding: utf-8 -*-
"""融资余额交易所完整性校验，避免把残缺交易日合计成全市场数据。"""
import pandas as pd


def _prepare(df, date_col):
    work = df.copy()
    raw_date = work[date_col].astype(str).str.replace("-", "", regex=False).str.slice(0, 8)
    work["_margin_date"] = pd.to_datetime(raw_date, format="%Y%m%d", errors="coerce")
    work["_margin_exchange"] = work["exchange_id"].astype(str).str.upper().str.strip()
    work["_margin_value"] = pd.to_numeric(work["rzye"], errors="coerce")
    return work.dropna(subset=["_margin_date", "_margin_value"])


def complete_margin_dates(df, date_col="trade_date"):
    """北交所出现前要求沪深齐全，出现后要求沪深北三所齐全。"""
    work = _prepare(df, date_col)
    if work.empty:
        return set()
    bse = work.loc[work["_margin_exchange"] == "BSE", "_margin_date"]
    bse_start = bse.min() if len(bse) else None
    exchanges = work.groupby("_margin_date")["_margin_exchange"].agg(set)
    valid = set()
    for date, present in exchanges.items():
        required = {"SSE", "SZSE"}
        if bse_start is not None and date >= bse_start:
            required.add("BSE")
        if required.issubset(present):
            valid.add(date)
    return valid


def filter_complete_margin(df, date_col="trade_date"):
    """仅保留交易所记录完整的日期，原列和行顺序不变。"""
    work = _prepare(df, date_col)
    valid = complete_margin_dates(df, date_col)
    keep = work["_margin_date"].isin(valid)
    return df.loc[keep].copy()
