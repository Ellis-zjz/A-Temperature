# -*- coding: utf-8 -*-
"""
A-Temperature · compute.py
从本地 Tushare parquet 数据湖计算 A 股情绪六项指标全历史序列 + 情绪温度，
输出 history.json 供 render.py 渲染成单页。

口径说明（与 a-share-pulse 对齐，日线近似版）：
- 全 A 样本：剔除北交所、剔除上市不满 60 天新股、剔除当日无成交（vol<=0）股票
- 涨停/跌停判定：按「昨收 x (1±板块涨跌幅限制) 四舍五入到分」与收盘价比对
  · 主板 ±10%，创业板 2020-08-24 前后 ±10%/±20%，科创板 ±20%
  · 当前简称含 ST 的主板/改革前创业板股票按 ±5% 判定，并加严约束
    （涨停需最高价=收盘=5%价，跌停需最低价=收盘=5%价，避免正常股误判）
  · 历史 ST 状态按当前简称近似（已知误差）；不含北交所及当日无成交股票
- 炸板：盘中最高价触及涨停价但收盘未封住（日线近似，不含封单口径差异）
- 情绪温度：六项指标各自在过去 250 个交易日窗口内的分位（当前值在窗口中的排位），
  再取六项分位的均值，映射到 0-100
"""

import glob
import json
import os
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
LAKE = os.environ.get(
    "PULSE_LAKE",
    "/Users/ellis/Desktop/股票学习/toshare/data_lake/lake",
)
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_JSON = os.path.join(OUT_DIR, "history.json")

TEMP_WINDOW = 250          # 情绪温度分位窗口（交易日）
NEW_STOCK_DAYS = 60        # 次新股剔除天数
PRICE_EPS = 0.005          # 价格比较容差（半分钱，2 位小数价格安全）

NAMES = {   # 六项指标（显示名 / percentiles 键 / components 键）
    "up_ratio":   "上涨家数占比",
    "limit_diff": "涨停减跌停",
    "broke_rate": "炸板率（反向）",
    "yday_avg":   "昨日涨停今日平均涨幅",
    "max_streak": "最高连板",
    "promo":      "首板晋级二板比例",
}

PERC_COL = {   # 六项指标 -> hist 中分位列名
    "up_ratio":   "p_up",
    "limit_diff": "p_diff",
    "broke_rate": "p_broke",
    "yday_avg":   "p_yday",
    "max_streak": "p_streak",
    "promo":      "p_promo",
}


def round_price_arr(x: np.ndarray) -> np.ndarray:
    """交易所口径：四舍五入到分（非银行家舍入），向量化。
    +1e-9 抵消浮点误差（如 9.495 存储为 9.4949999…，会导致半分钱边界舍错）。"""
    return np.floor(x * 100 + 0.5 + 1e-9) / 100.0


def load_stock_basic() -> pd.DataFrame:
    # 用 full 版：包含已退市股票（当前存续版会让历史样本缺 200+ 只退市股）
    path = os.path.join(LAKE, "stock_basic", "stock_basic_full.parquet")
    df = pd.read_parquet(path)
    return df[["ts_code", "name", "list_date"]].copy()


CHINEXT_REFORM = "20200824"   # 创业板注册制改革日：此后 ±20%，此前 ±10%


def board_type(ts_code: str) -> int:
    """0=主板 1=创业板 2=科创板（北交所返回 -1）。"""
    code = ts_code.split(".")[0]
    suffix = ts_code.split(".")[-1] if "." in ts_code else ""
    if suffix == "BJ":
        return -1
    if code.startswith(("688", "689")):
        return 2
    if code.startswith(("300", "301", "302")):
        return 1
    return 0


def pct_rank(series: pd.Series, window: int) -> pd.Series:
    """当前值在过去 window 个交易日窗口中的分位（含自身），0-100。"""
    vals = series.to_numpy(dtype=float)
    out = np.full(len(vals), np.nan)
    for j in range(window - 1, len(vals)):
        cur = vals[j]
        if np.isnan(cur):
            continue
        w = vals[j - window + 1: j + 1]
        valid = w[~np.isnan(w)]
        if len(valid) < 50:   # 窗口有效样本太少则不输出
            continue
        out[j] = float((valid <= cur).mean()) * 100
    return pd.Series(out)


def env_temp_series(hist: pd.DataFrame, n: int) -> pd.Series:
    """环境温度：当日温度的 n 日移动平均。
    （曾尝试「先平滑指标再取分位」，因平滑序列方差小、分位在密集区被放大而更跳，弃用。）"""
    return hist["temp"].rolling(n, min_periods=max(2, n // 2)).mean().round(1)


def main():
    t0 = datetime.now()
    print("[1/3] 读取数据湖 …")
    basic = load_stock_basic()
    list_dt = pd.to_datetime(basic["list_date"], format="%Y%m%d", errors="coerce")
    basic = basic.assign(list_dt=list_dt)

    # 每只股票的板块类型与当前 ST 标记（历史 ST 状态近似，详见口径说明）
    board_map = {r.ts_code: board_type(r.ts_code) for r in basic.itertuples()}
    st_map = {
        r.ts_code: ("ST" in str(r.name).upper())
        for r in basic.itertuples()
    }
    list_map = dict(zip(basic["ts_code"], basic["list_dt"]))

    daily_files = sorted(glob.glob(os.path.join(LAKE, "daily", "trade_date=*.parquet")))
    if not daily_files:
        print("错误：数据湖中未找到日线文件", file=sys.stderr)
        sys.exit(1)
    dates = [f.split("trade_date=")[-1].replace(".parquet", "") for f in daily_files]
    print(f"    日线 {len(dates)} 个交易日：{dates[0]} ~ {dates[-1]}")

    # -----------------------------------------------------------------------
    print("[2/3] 逐日计算六项指标 …")
    streak = {}                     # ts_code -> 当前连续涨停天数
    rows = []
    prev_limit_up_set = set()       # 昨日涨停股票集合
    prev_first_board_set = set()    # 昨日首板股票集合

    for i, f in enumerate(daily_files):
        d = dates[i]
        d_dt = pd.to_datetime(d, format="%Y%m%d")
        df = pd.read_parquet(f)

        # 当日有效样本：非北交所、上市>=60天、当日有成交
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
            rows.append({"date": d})
            prev_limit_up_set, prev_first_board_set = set(), set()
            continue

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
        m_star = board == 2
        m_chx_pre = (board == 1) & (d < CHINEXT_REFORM)    # 创业板改革前 ±10%
        # 有效涨跌停价：主板/改革前创业板 10%，改革后创业板与科创板 20%
        eff_up = np.where(m_main | m_chx_pre, up10, up20)
        eff_dn = np.where(m_main | m_chx_pre, dn10, dn20)

        limit_up_flags = np.abs(close - eff_up) < PRICE_EPS
        limit_dn_flags = np.abs(close - eff_dn) < PRICE_EPS

        # 5% 候选（当前简称 ST，主板/改革前创业板）：加严约束
        # 真实 ST 封板时盘中极值=收盘价=5%价；正常股不可能恰好全天收在极值的 -5.00%
        m_st = st_name & (m_main | m_chx_pre)
        st_up = m_st & (np.abs(close - up05) < PRICE_EPS) & (np.abs(high - close) < PRICE_EPS)
        st_dn = m_st & (np.abs(close - dn05) < PRICE_EPS) & (np.abs(low - close) < PRICE_EPS)
        limit_up_flags = limit_up_flags | st_up
        limit_dn_flags = limit_dn_flags | st_dn

        # 炸板：触及有效涨停价（含 ST 5% 价）但收盘未封住
        touched_flags = ((high >= eff_up - PRICE_EPS) & ~limit_up_flags) | \
                        (m_st & (high >= up05 - PRICE_EPS) & ~st_up & ~limit_up_flags)

        n_limit_up = int(limit_up_flags.sum())
        n_limit_dn = int(limit_dn_flags.sum())
        n_broke = int(touched_flags.sum())
        broke_rate = n_broke / max(n_limit_up + n_broke, 1)
        up_ratio = float((pct_chg > 0).sum()) / len(df)

        # --- 连板与晋级 -----------------------------------------------------
        lu_codes = set(codes[limit_up_flags].tolist())
        new_streak = {c: streak.get(c, 0) + 1 for c in lu_codes}
        max_streak = max(new_streak.values()) if new_streak else 0
        streak = new_streak  # 只保留今日涨停链

        # 昨日涨停股今日平均涨幅
        if prev_limit_up_set:
            ymask = np.isin(codes, list(prev_limit_up_set))
            yday_avg = float(np.mean(pct_chg[ymask])) if ymask.any() else None
        else:
            yday_avg = None

        # 首板晋级率：昨日首板(streak==1) 今日再涨停的比例
        if prev_first_board_set:
            promo = len(lu_codes & prev_first_board_set) / len(prev_first_board_set)
        else:
            promo = None

        # 更新昨日集合
        prev_limit_up_set = lu_codes
        prev_first_board_set = {c for c, s in new_streak.items() if s == 1}

        rows.append({
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
        })
        if (i + 1) % 200 == 0:
            print(f"    … {i+1}/{len(dates)} 天")

    hist = pd.DataFrame(rows)

    # -----------------------------------------------------------------------
    print("[3/3] 计算情绪温度 …")
    p_up = pct_rank(hist["up_ratio"], TEMP_WINDOW)
    p_diff = pct_rank(hist["limit_diff"].astype(float), TEMP_WINDOW)
    p_broke = pct_rank(1 - hist["broke_rate"].astype(float), TEMP_WINDOW)   # 反向
    p_yday = pct_rank(hist["yday_avg"].astype(float), TEMP_WINDOW)
    p_streak = pct_rank(hist["max_streak"].astype(float), TEMP_WINDOW)
    p_promo = pct_rank(hist["promo"].astype(float), TEMP_WINDOW)

    parts = pd.concat([p_up, p_diff, p_broke, p_yday, p_streak, p_promo], axis=1)
    temp = parts.mean(axis=1, skipna=True)
    temp5 = temp.rolling(5, min_periods=3).mean()

    hist["temp"] = temp.round(1)
    hist["temp5"] = temp5.round(1)
    hist["temp_env5"] = env_temp_series(hist, 5)
    hist["temp_env10"] = env_temp_series(hist, 10)
    hist["p_up"], hist["p_diff"], hist["p_broke"] = p_up.round(1), p_diff.round(1), p_broke.round(1)
    hist["p_yday"], hist["p_streak"], hist["p_promo"] = p_yday.round(1), p_streak.round(1), p_promo.round(1)

    # -----------------------------------------------------------------------
    last = hist.iloc[-1]

    def null_list(col):
        return [None if v is None or pd.isna(v) else v for v in hist[col]]

    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "site": "A-Temperature",
        "meta": {
            "sample": f"全A（剔除北交所、上市不满{NEW_STOCK_DAYS}天新股、当日无成交）",
            "limit_rule": "昨收×(1±限制)四舍五入到分与收盘比对；主板及2020-08-24前创业板±10%、此后创业板/科创板±20%；当前简称含ST按±5%（加严：需盘中极值=收盘价=5%价）；历史ST状态按当前简称近似",
            "broke_rule": "盘中最高价触及涨停价但收盘未封住（日线近似）",
            "temp_rule": f"当日温度=六项指标各自在近{TEMP_WINDOW}个交易日窗口内的分位均值，0-100；环境温度=当日温度的5/10日移动平均；是参照系，不是预测",
        },
        "dates": hist["date"].tolist(),
        "temp": null_list("temp"),
        "temp5": null_list("temp5"),
        "temp_env5": null_list("temp_env5"),
        "temp_env10": null_list("temp_env10"),
        "limit_up": hist["limit_up"].tolist(),
        "limit_dn": hist["limit_dn"].tolist(),
        "components": {k: null_list(k) for k in NAMES},
        "percentiles": {k: null_list(PERC_COL[k]) for k in NAMES},
        "latest": {
            "date": last["date"],
            "temp": None if pd.isna(last["temp"]) else float(last["temp"]),
            "temp5": None if pd.isna(last["temp5"]) else float(last["temp5"]),
            "temp_env5": None if pd.isna(last["temp_env5"]) else float(last["temp_env5"]),
            "temp_env10": None if pd.isna(last["temp_env10"]) else float(last["temp_env10"]),
            "up_ratio": float(last["up_ratio"]),
            "limit_up": int(last["limit_up"]),
            "limit_dn": int(last["limit_dn"]),
            "limit_diff": int(last["limit_diff"]),
            "broke_rate": float(last["broke_rate"]),
            "yday_avg": None if pd.isna(last["yday_avg"]) else float(last["yday_avg"]),
            "max_streak": int(last["max_streak"]),
            "promo": None if pd.isna(last["promo"]) else float(last["promo"]),
        },
        "percentiles_latest": {
            k: None if pd.isna(last[PERC_COL[k]]) else float(last[PERC_COL[k]])
            for k in NAMES
        },
    }
    with open(HISTORY_JSON, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)

    dt = (datetime.now() - t0).total_seconds()
    print(f"完成：{HISTORY_JSON}（{dt:.1f}s）")
    print(f"最新交易日 {last['date']}：温度 {last['temp']}，涨停 {last['limit_up']} 家，跌停 {last['limit_dn']} 家")


if __name__ == "__main__":
    main()
