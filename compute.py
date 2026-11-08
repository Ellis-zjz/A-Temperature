# -*- coding: utf-8 -*-
"""
A-Temperature · compute.py
从本地 Tushare parquet 数据湖计算情绪指标全历史序列 + 情绪温度，
输出 history.json 供 render.py 渲染成单页。

情绪温度构成（5 项，各取近 250 交易日分位后求均值，0-100）：
1. 综合成交额：上证 + 深证主板 + 创业板 合计成交额（亿元）
2. 综合换手率：Σ成交额 / Σ流通市值（市值加权，%），上证+深证主板+创业板
3. 沪深300 收盘价相对 MA5 / MA20 / MA60 的偏离度（3 个分量）

涨跌停家数仅作页面展示（不参与温度计算）：
- 全 A 样本：剔除北交所、上市不满 60 天新股、当日无成交股票
- 涨停/跌停判定：昨收×(1±板块限制) 四舍五入到分与收盘价比对
  · 主板 ±10%，创业板 2020-08-24 前后 ±10%/±20%，科创板 ±20%
  · 当前简称含 ST 的主板/改革前创业板股票按 ±5% 判定并加严约束
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
HS300_CACHE = os.path.join(OUT_DIR, "hs300_daily.parquet")

TEMP_WINDOW = 250          # 温度分位窗口（交易日）
NEW_STOCK_DAYS = 60        # 次新股剔除天数（仅用于涨跌停统计样本）
PRICE_EPS = 0.005          # 价格比较容差（半分钱）
CHINEXT_REFORM = "20200824"

COMPONENTS = ["amount_total", "turnover", "dev5", "dev20", "dev60"]

META_TEXT = {
    "amount_rule": "上证(含科创板)+深证主板+创业板当日成交额合计，单位亿元",
    "turnover_rule": "三板块Σ成交额 / Σ流通市值（市值加权换手率），来自 daily 与 daily_basic 合并",
    "dev_rule": "沪深300收盘价 / MA(n) − 1，n=5/20/60；均线由指数日线计算",
    "temp_rule": f"温度=5项指标各自在近{TEMP_WINDOW}个交易日窗口内的分位均值，0-100；环境温度=当日温度的5/10日移动平均；是参照系，不是预测",
}


def round_price_arr(x: np.ndarray) -> np.ndarray:
    """交易所口径四舍五入到分；+1e-9 抵消浮点误差。"""
    return np.floor(x * 100 + 0.5 + 1e-9) / 100.0


def null_list(col) -> list:
    """pandas Series / ndarray → JSON 列表（NaN→None）。"""
    return [None if v is None or pd.isna(v) else (float(v) if isinstance(v, (float, np.floating)) else v)
            for v in col]


def board_group(ts_code: str):
    """'sh'=上证(含科创板) 'sz'=深证主板 'chx'=创业板 None=其他(北交所等)。"""
    if "." not in ts_code:
        return None
    code, suffix = ts_code.split(".", 1)
    if suffix == "SH":
        return "sh"
    if suffix == "SZ":
        return "chx" if code.startswith(("300", "301", "302")) else "sz"
    return None


def board_type(ts_code: str) -> int:
    """数字板块类型（涨跌停判定用）：0=主板 1=创业板 2=科创板 -1=北交所。"""
    if "." not in ts_code:
        return -1
    code, suffix = ts_code.split(".", 1)
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
        if len(valid) < 50:
            continue
        out[j] = float((valid <= cur).mean()) * 100
    return pd.Series(out)


# ---------------------------------------------------------------------------
# 沪深300 日线缓存
# ---------------------------------------------------------------------------
def load_hs300(dates: list) -> pd.DataFrame:
    """读缓存并补齐到 dates[-1]（需要 TUSHARE_TOKEN 环境变量才能联网补齐）。
    返回按 trade_date(YYYYMMDD) 索引的 close 序列。"""
    if os.path.exists(HS300_CACHE):
        c = pd.read_parquet(HS300_CACHE)
    else:
        c = pd.DataFrame(columns=["trade_date", "close"])
    c["trade_date"] = c["trade_date"].str.replace("-", "", regex=False)
    close = pd.Series(c["close"].values, index=c["trade_date"].values, dtype=float)

    target = dates[-1]
    if target not in close.index:
        token = os.environ.get("TUSHARE_TOKEN")
        if not token:
            print(f"警告：沪深300缓存截止 {close.index[-1]}，且未提供 TUSHARE_TOKEN，"
                  f"MA 偏离度在缺失日期将为空", file=sys.stderr)
        else:
            import tushare as ts
            pro = ts.pro_api(token)
            start = (pd.to_datetime(close.index[-1]) + pd.Timedelta(days=1)).strftime("%Y%m%d")
            d = pro.index_daily(ts_code="000300.SH", start_date=start, end_date=target)
            if not d.empty:
                d = d.sort_values("trade_date")
                new = pd.Series(d["close"].values, index=d["trade_date"].values, dtype=float)
                close = pd.concat([close, new])
                close[~close.index.duplicated()]
                pd.DataFrame({"trade_date": close.index, "close": close.values}).to_parquet(
                    HS300_CACHE, index=False)
                print(f"    沪深300缓存已补齐至 {close.index[-1]}")
    return close


# ---------------------------------------------------------------------------
# 单日截面统计（compute.py 与 update_daily.py 共用）
# ---------------------------------------------------------------------------
def day_stats(df: pd.DataFrame, db: pd.DataFrame, d: str,
              list_map: dict, board_map: dict, board_num_map: dict,
              st_map: dict) -> dict:
    """df=daily截面, db=daily_basic截面（可能为空）。返回单日全部指标。"""
    d_dt = pd.to_datetime(d, format="%Y%m%d")

    # --- 量能：全部非北交所股票（含新股），按板块分组 ---
    nb = df[~df["ts_code"].str.endswith(".BJ")].copy()
    grp = nb["ts_code"].map(board_map)
    amt = {g: float(nb.loc[grp == g, "amount"].sum()) / 1e5   # 千元 → 亿元
           for g in ("sh", "sz", "chx")}
    amount_total = amt["sh"] + amt["sz"] + amt["chx"]

    # --- 换手率：daily 与 daily_basic 按 ts_code 内连接 ---
    turnover = None
    if db is not None and not db.empty:
        m = nb[["ts_code", "amount"]].merge(
            db[["ts_code", "circ_mv"]], on="ts_code", how="inner")
        if len(m) > 100 and m["circ_mv"].sum() > 0:
            turnover = float(m["amount"].sum() / m["circ_mv"].sum() * 10)  # → %

    # --- 涨跌停家数（展示用，剔除次新/无成交） ---
    list_series = df["ts_code"].map(list_map)
    mask = (
        ~df["ts_code"].str.endswith(".BJ")
        & list_series.notna()
        & (list_series <= d_dt - timedelta(days=NEW_STOCK_DAYS))
        & (df["vol"] > 0)
        & df["pre_close"].gt(0)
    )
    s = df.loc[mask]
    n_limit_up = n_limit_dn = 0
    if not s.empty:
        pre_close = s["pre_close"].to_numpy()
        close = s["close"].to_numpy()
        high = s["high"].to_numpy()
        low = s["low"].to_numpy()
        board = s["ts_code"].map(board_num_map).to_numpy()
        st_name = s["ts_code"].map(st_map).fillna(False).to_numpy(dtype=bool)

        rp = round_price_arr
        up10, dn10 = rp(pre_close * 1.1), rp(pre_close * 0.9)
        up20, dn20 = rp(pre_close * 1.2), rp(pre_close * 0.8)
        up05, dn05 = rp(pre_close * 1.05), rp(pre_close * 0.95)

        m_main = board == 0
        m_chx_pre = (board == 1) & (d < CHINEXT_REFORM)
        eff_up = np.where(m_main | m_chx_pre, up10, up20)
        eff_dn = np.where(m_main | m_chx_pre, dn10, dn20)

        lu = np.abs(close - eff_up) < PRICE_EPS
        ld = np.abs(close - eff_dn) < PRICE_EPS
        m_st = st_name & (m_main | m_chx_pre)
        st_up = m_st & (np.abs(close - up05) < PRICE_EPS) & (np.abs(high - close) < PRICE_EPS)
        st_dn = m_st & (np.abs(close - dn05) < PRICE_EPS) & (np.abs(low - close) < PRICE_EPS)
        lu = lu | st_up
        ld = ld | st_dn
        n_limit_up, n_limit_dn = int(lu.sum()), int(ld.sum())

    return {
        "date": d,
        "amount_sh": round(amt["sh"], 2),
        "amount_sz": round(amt["sz"], 2),
        "amount_chx": round(amt["chx"], 2),
        "amount_total": round(amount_total, 2),
        "turnover": None if turnover is None else round(turnover, 4),
        "limit_up": n_limit_up,
        "limit_dn": n_limit_dn,
    }


# ---------------------------------------------------------------------------
# 全历史温度计算（compute.py 与 update_daily.py 共用）
# ---------------------------------------------------------------------------
def finalize(hist: dict) -> None:
    """从 components 序列计算分位 / 温度 / 环境温度，并刷新 latest。"""
    parts = []
    for k in COMPONENTS:
        s = pd.Series(hist["components"][k], dtype=float)
        p = pct_rank(s, TEMP_WINDOW)
        hist["percentiles"][k] = [None if pd.isna(v) else round(v, 1) for v in p]
        parts.append(p)
    temp = pd.concat(parts, axis=1).mean(axis=1, skipna=True)
    hist["temp"] = [None if pd.isna(v) else round(v, 1) for v in temp]

    temps = pd.Series(hist["temp"], dtype=float)
    for n, key in ((5, "temp_env5"), (10, "temp_env10")):
        e = temps.rolling(n, min_periods=max(2, n // 2)).mean().round(1)
        hist[key] = [None if pd.isna(v) else v for v in e]

    last_i = len(hist["dates"]) - 1
    hist["percentiles_latest"] = {k: hist["percentiles"][k][-1] for k in COMPONENTS}
    hist["latest"].update({
        "temp": hist["temp"][-1],
        "temp_env5": hist["temp_env5"][-1],
        "temp_env10": hist["temp_env10"][-1],
        "amount_total": hist["components"]["amount_total"][-1],
        "amount_sh": hist["amount_sh"][-1],
        "amount_sz": hist["amount_sz"][-1],
        "amount_chx": hist["amount_chx"][-1],
        "turnover": hist["components"]["turnover"][-1],
        "dev5": hist["components"]["dev5"][-1],
        "dev20": hist["components"]["dev20"][-1],
        "dev60": hist["components"]["dev60"][-1],
        "limit_up": hist["limit_up"][-1],
        "limit_dn": hist["limit_dn"][-1],
        "hs300_close": hist["hs300_close"][-1],
    })
    hist["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def hs300_dev_series(close: pd.Series, dates: list) -> pd.DataFrame:
    """沪深300 收盘价对齐到交易日序列，计算 MA5/20/60 与偏离度。"""
    c = close.reindex(dates)
    out = {"hs300_close": c}
    for n in (5, 20, 60):
        ma = c.rolling(n, min_periods=n).mean()
        out[f"dev{n}"] = c / ma - 1
    return pd.DataFrame(out, index=dates)


# ---------------------------------------------------------------------------
def main():
    t0 = datetime.now()
    print("[1/4] 读取数据湖 …")
    basic = pd.read_parquet(os.path.join(LAKE, "stock_basic", "stock_basic_full.parquet"))
    list_dt = pd.to_datetime(basic["list_date"], format="%Y%m%d", errors="coerce")
    list_map = dict(zip(basic["ts_code"], list_dt))
    board_map = {r.ts_code: board_group(r.ts_code) for r in basic.itertuples()}
    board_num_map = {r.ts_code: board_type(r.ts_code) for r in basic.itertuples()}
    st_map = {r.ts_code: ("ST" in str(r.name).upper()) for r in basic.itertuples()}

    daily_files = sorted(glob.glob(os.path.join(LAKE, "daily", "trade_date=*.parquet")))
    if not daily_files:
        print("错误：数据湖中未找到日线文件", file=sys.stderr)
        sys.exit(1)
    dates = [f.split("trade_date=")[-1].replace(".parquet", "") for f in daily_files]
    print(f"    日线 {len(dates)} 个交易日：{dates[0]} ~ {dates[-1]}")

    print("[2/4] 沪深300 日线 …")
    close = load_hs300(dates)

    print("[3/4] 逐日计算量能与涨跌停 …")
    rows = []
    for i, f in enumerate(daily_files):
        d = dates[i]
        df = pd.read_parquet(f)
        db_path = os.path.join(LAKE, "daily_basic", f"trade_date={d}.parquet")
        db = pd.read_parquet(db_path) if os.path.exists(db_path) else None
        rows.append(day_stats(df, db, d, list_map, board_map, board_num_map, st_map))
        if (i + 1) % 400 == 0:
            print(f"    … {i+1}/{len(dates)} 天")

    hist = pd.DataFrame(rows).set_index("date").reindex(dates)

    # 沪深300 偏离度
    dev = hs300_dev_series(close, dates)

    print("[4/4] 计算温度 …")
    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "site": "A-Temperature",
        "meta": {
            "sample": "量能/换手率：全A剔除北交所（含新股与ST）；涨跌停统计：另剔除上市不满60天与无成交",
            **META_TEXT,
        },
        "dates": dates,
        "limit_up": hist["limit_up"].fillna(0).astype(int).tolist(),
        "limit_dn": hist["limit_dn"].fillna(0).astype(int).tolist(),
        "amount_sh": null_list(hist["amount_sh"]),
        "amount_sz": null_list(hist["amount_sz"]),
        "amount_chx": null_list(hist["amount_chx"]),
        "hs300_close": null_list(dev["hs300_close"].round(2)),
        "hs300_ma5": null_list((dev["hs300_close"] / (1 + dev["dev5"])).round(2)),
        "hs300_ma20": null_list((dev["hs300_close"] / (1 + dev["dev20"])).round(2)),
        "hs300_ma60": null_list((dev["hs300_close"] / (1 + dev["dev60"])).round(2)),
        "components": {
            "amount_total": null_list(hist["amount_total"]),
            "turnover": null_list(hist["turnover"]),
            "dev5": null_list(dev["dev5"].round(6)),
            "dev20": null_list(dev["dev20"].round(6)),
            "dev60": null_list(dev["dev60"].round(6)),
        },
        "latest": {"date": dates[-1]},
        "percentiles": {},
    }
    finalize(payload)

    with open(HISTORY_JSON, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)

    dt = (datetime.now() - t0).total_seconds()
    lt = payload["latest"]
    print(f"完成：{HISTORY_JSON}（{dt:.1f}s）")
    print(f"最新交易日 {lt['date']}：温度 {lt['temp']}，成交额 {lt['amount_total']}亿，"
          f"换手 {lt['turnover']}%，涨停 {lt['limit_up']} 家")


if __name__ == "__main__":
    main()
