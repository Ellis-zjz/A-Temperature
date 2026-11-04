# -*- coding: utf-8 -*-
"""
A-Temperation · update_daily.py
在 GitHub Actions 上运行的每日增量更新：
1. 从 Tushare Pro API 拉取历史记录之后缺失交易日的日线截面
2. 增量计算六项指标，追加到 history.json（温度分位用已有历史窗口计算）
3. 连板状态存 state.json（跨日传递，缺失时自动回溯重建）
4. 重新渲染 index.html
"""

import json
import math
import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import tushare as ts

import render  # 同目录，渲染 index.html

HIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "history.json")
STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")

TEMP_WINDOW = 250
NEW_STOCK_DAYS = 60
PRICE_EPS = 0.005
CHINEXT_REFORM = "20200824"
BOOTSTRAP_DAYS = 40   # state.json 缺失时回溯多少个交易日重建连板状态


def round_price_arr(x: np.ndarray) -> np.ndarray:
    return np.floor(x * 100 + 0.5 + 1e-9) / 100.0


def board_type(ts_code: str) -> int:
    code = ts_code.split(".")[0]
    suffix = ts_code.split(".")[-1] if "." in ts_code else ""
    if suffix == "BJ":
        return -1
    if code.startswith(("688", "689")):
        return 2
    if code.startswith(("300", "301", "302")):
        return 1
    return 0


def compute_day(df: pd.DataFrame, basic: pd.DataFrame, d: str,
                streak: dict) -> tuple:
    """与 compute.py 完全一致的口径，计算单日指标。返回 (row, new_streak)。"""
    d_dt = pd.to_datetime(d, format="%Y%m%d")
    list_dt = pd.to_datetime(basic["list_date"], format="%Y%m%d", errors="coerce")
    list_map = dict(zip(basic["ts_code"], list_dt))
    name_map = dict(zip(basic["ts_code"], basic["name"]))
    board_map = {c: board_type(c) for c in basic["ts_code"]}
    st_map = {c: ("ST" in str(n).upper()) for c, n in zip(basic["ts_code"], basic["name"])}

    list_series = df["ts_code"].map(list_map)
    mask = (
        ~df["ts_code"].str.endswith(".BJ")
        & list_series.notna()
        & (list_series <= d_dt - timedelta(days=NEW_STOCK_DAYS))
        & (df["vol"] > 0)
        & df["pre_close"].gt(0)
    )
    df = df.loc[mask]
    if df.empty:
        return {"date": d}, {}

    codes = df["ts_code"].to_numpy()
    pre_close = df["pre_close"].to_numpy()
    close = df["close"].to_numpy()
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    pct_chg = df["pct_chg"].to_numpy()
    board = df["ts_code"].map(board_map).to_numpy()
    st_name = df["ts_code"].map(st_map).fillna(False).to_numpy(dtype=bool)

    rp = round_price_arr
    up10, dn10 = rp(pre_close * 1.1), rp(pre_close * 0.9)
    up20, dn20 = rp(pre_close * 1.2), rp(pre_close * 0.8)
    up05, dn05 = rp(pre_close * 1.05), rp(pre_close * 0.95)

    m_main = board == 0
    m_chx_pre = (board == 1) & (d < CHINEXT_REFORM)
    eff_up = np.where(m_main | m_chx_pre, up10, up20)
    eff_dn = np.where(m_main | m_chx_pre, dn10, dn20)

    limit_up_flags = np.abs(close - eff_up) < PRICE_EPS
    limit_dn_flags = np.abs(close - eff_dn) < PRICE_EPS

    m_st = st_name & (m_main | m_chx_pre)
    st_up = m_st & (np.abs(close - up05) < PRICE_EPS) & (np.abs(high - close) < PRICE_EPS)
    st_dn = m_st & (np.abs(close - dn05) < PRICE_EPS) & (np.abs(low - close) < PRICE_EPS)
    limit_up_flags = limit_up_flags | st_up
    limit_dn_flags = limit_dn_flags | st_dn

    touched_flags = ((high >= eff_up - PRICE_EPS) & ~limit_up_flags) | \
                    (m_st & (high >= up05 - PRICE_EPS) & ~st_up & ~limit_up_flags)

    n_limit_up = int(limit_up_flags.sum())
    n_limit_dn = int(limit_dn_flags.sum())
    n_broke = int(touched_flags.sum())
    broke_rate = n_broke / max(n_limit_up + n_broke, 1)
    up_ratio = float((pct_chg > 0).sum()) / len(df)

    lu_codes = set(codes[limit_up_flags].tolist())
    new_streak = {c: streak.get(c, 0) + 1 for c in lu_codes}
    max_streak = max(new_streak.values()) if new_streak else 0

    prev_limit_up_set = set(streak.keys())
    prev_first_board_set = {c for c, s in streak.items() if s == 1}
    if prev_limit_up_set:
        ymask = np.isin(codes, list(prev_limit_up_set))
        yday_avg = float(np.mean(pct_chg[ymask])) if ymask.any() else None
    else:
        yday_avg = None
    if prev_first_board_set:
        promo = len(lu_codes & prev_first_board_set) / len(prev_first_board_set)
    else:
        promo = None

    row = {
        "date": d,
        "n": len(df),
        "up_ratio": round(up_ratio, 6),
        "limit_up": n_limit_up,
        "limit_dn": n_limit_dn,
        "limit_diff": n_limit_up - n_limit_dn,
        "broke_rate": round(broke_rate, 6),
        "yday_avg": None if yday_avg is None else round(yday_avg, 4),
        "max_streak": max_streak,
        "promo": None if promo is None else round(promo, 6),
    }
    return row, new_streak


def rebuild_streak(pro, before_date: str, basic: pd.DataFrame) -> dict:
    """state.json 缺失时，回溯 BOOTSTRAP_DAYS 个交易日重建连板状态。"""
    cal = pro.query("trade_cal", exchange="SSE",
                    end_date=before_date, is_open="1",
                    start_date=(pd.to_datetime(before_date) - pd.Timedelta(days=90)).strftime("%Y%m%d"))
    days = sorted(cal["cal_date"].tolist())[-BOOTSTRAP_DAYS:-1]
    streak = {}
    for d in days:
        df = pro.daily(trade_date=d)
        _, streak = compute_day(df, basic, d, streak)
    return streak


def append_temp(hist: dict, n_new: int) -> None:
    """对追加的 n_new 天计算温度（用 history 中的全历史分位窗口）。"""
    names = ["up_ratio", "limit_diff", "broke_rate", "yday_avg", "max_streak", "promo"]
    comp = {k: hist["components"][k] for k in names}

    def pct_at(j: int, k: str):
        cur = comp[k][j]
        if cur is None:
            return None
        w = [v for v in comp[k][max(0, j - TEMP_WINDOW + 1): j + 1] if v is not None]
        if len(w) < 50:
            return None
        return float(sum(v <= cur for v in w)) / len(w) * 100

    temps = hist["temp"]
    for j in range(len(hist["dates"]) - n_new, len(hist["dates"])):
        ps = [pct_at(j, k) for k in names]
        valid = [p for p in ps if p is not None]
        t = round(sum(valid) / len(valid), 1) if len(valid) >= 4 else None
        temps.append(t)
    hist["temp"] = temps
    # 5 日均线
    t5 = []
    for j, t in enumerate(temps):
        w = [v for v in temps[max(0, j - 4): j + 1] if v is not None]
        t5.append(round(sum(w) / len(w), 1) if len(w) >= 3 else None)
    hist["temp5"] = t5
    # 最新日
    last_i = len(hist["dates"]) - 1
    hist["latest"]["temp"] = temps[-1]
    hist["latest"]["temp5"] = t5[-1]
    for k, col in zip(names, ["up", "diff", "broke", "yday", "streak", "promo"]):
        hist["percentiles"][col].append(pct_at(last_i, k))
        hist["percentiles_latest"][k] = hist["percentiles"][col][-1]
    hist["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def main():
    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        raise SystemExit("缺少环境变量 TUSHARE_TOKEN")
    pro = ts.pro_api(token)

    hist = json.load(open(HIST, encoding="utf-8"))
    last = hist["dates"][-1]
    today = datetime.now().strftime("%Y%m%d")

    # 缺失的交易日（含今天，今天数据未出会查询为空则跳过）
    cal = pro.query("trade_cal", exchange="SSE", start_date=last, end_date=today, is_open="1")
    missing = [d for d in sorted(cal["cal_date"].tolist()) if d > last]
    print(f"历史截止 {last}，缺失交易日：{missing or '无'}")
    if not missing:
        print("无需更新")
        return

    basic = pd.concat([
        pro.query("stock_basic", list_status="L"),
        pro.query("stock_basic", list_status="D"),
        pro.query("stock_basic", list_status="P"),
    ], ignore_index=True)

    state = {}
    if os.path.exists(STATE):
        state = json.load(open(STATE, encoding="utf-8"))
    streak = state.get("streak", {})
    if not streak:
        streak = rebuild_streak(pro, missing[0], basic)
        print(f"已回溯重建连板状态（{len(streak)} 只）")

    new_rows = []
    for d in missing:
        df = pro.daily(trade_date=d)
        if df.empty:
            print(f"{d} 数据未发布，跳过")
            continue
        row, streak = compute_day(df, basic, d, streak)
        new_rows.append(row)
        print(f"{d}: 涨停 {row['limit_up']} 跌停 {row['limit_dn']}")

    if not new_rows:
        print("无新增数据")
        return

    # 追加到 history
    n_new = len(new_rows)
    hist["dates"].extend([r["date"] for r in new_rows])
    for k in ["up_ratio", "limit_diff", "broke_rate", "yday_avg", "max_streak", "promo"]:
        hist["components"][k].extend([r[k] for r in new_rows])
    hist["limit_up"].extend([r["limit_up"] for r in new_rows])
    hist["limit_dn"].extend([r["limit_dn"] for r in new_rows])
    last_row = new_rows[-1]
    hist["latest"].update({
        "date": last_row["date"],
        "up_ratio": last_row["up_ratio"],
        "limit_up": last_row["limit_up"],
        "limit_dn": last_row["limit_dn"],
        "limit_diff": last_row["limit_diff"],
        "broke_rate": last_row["broke_rate"],
        "yday_avg": last_row["yday_avg"],
        "max_streak": last_row["max_streak"],
        "promo": last_row["promo"],
    })

    append_temp(hist, n_new)

    with open(HIST, "w", encoding="utf-8") as fh:
        json.dump(hist, fh, ensure_ascii=False)
    with open(STATE, "w", encoding="utf-8") as fh:
        json.dump({"streak": streak, "last": last_row["date"]}, fh)

    render.render()
    print("更新完成")


if __name__ == "__main__":
    main()
