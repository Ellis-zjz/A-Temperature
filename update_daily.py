# -*- coding: utf-8 -*-
"""
A-Temperature · update_daily.py
在 GitHub Actions 上运行的每日增量更新：
1. 从 Tushare Pro API 拉取缺失交易日的 daily / daily_basic / 沪深300 指数日线
2. 调用 compute.day_stats 计算单日指标，追加到 history.json
3. 调用 compute.finalize 重算温度与分位
4. 重新渲染 index.html
"""

import json
import os
from datetime import datetime

import pandas as pd
import tushare as ts

import compute  # 同目录，复用 day_stats / finalize / 常量
import render   # 同目录，渲染 index.html

HIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "history.json")


def fetch_basic(pro) -> pd.DataFrame:
    return pd.concat([
        pro.query("stock_basic", list_status="L"),
        pro.query("stock_basic", list_status="D"),
        pro.query("stock_basic", list_status="P"),
    ], ignore_index=True)


def main():
    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        raise SystemExit("缺少环境变量 TUSHARE_TOKEN")
    pro = ts.pro_api(token)

    hist = json.load(open(HIST, encoding="utf-8"))
    last = hist["dates"][-1]
    today = datetime.now().strftime("%Y%m%d")

    # 缺失的交易日（今天数据未出时查询为空则跳过）
    cal = pro.query("trade_cal", exchange="SSE", start_date=last, end_date=today)
    cal = cal[cal["is_open"] == 1]
    missing = [d for d in sorted(cal["cal_date"].tolist()) if d > last]
    print(f"历史截止 {last}，缺失交易日：{missing or '无'}")
    if not missing:
        print("无需更新")
        return

    basic = fetch_basic(pro)
    list_dt = pd.to_datetime(basic["list_date"], format="%Y%m%d", errors="coerce")
    list_map = dict(zip(basic["ts_code"], list_dt))
    board_map = {c: compute.board_group(c) for c in basic["ts_code"]}
    board_num_map = {c: compute.board_type(c) for c in basic["ts_code"]}
    st_map = {c: ("ST" in str(n).upper()) for c, n in zip(basic["ts_code"], basic["name"])}

    for d in missing:
        df = pro.daily(trade_date=d)
        if df.empty:
            print(f"{d} 数据未发布，跳过")
            continue
        db = pro.daily_basic(trade_date=d)

        # 沪深300 当日收盘（失败不阻塞，偏离度留空）
        idx = pro.index_daily(ts_code="000300.SH", start_date=d, end_date=d)
        hs300_close = float(idx.iloc[0]["close"]) if not idx.empty else None

        row = compute.day_stats(df, db, d, list_map, board_map, board_num_map, st_map)
        hist["dates"].append(d)
        hist["limit_up"].append(row["limit_up"])
        hist["limit_dn"].append(row["limit_dn"])
        hist["amount_sh"].append(row["amount_sh"])
        hist["amount_sz"].append(row["amount_sz"])
        hist["amount_chx"].append(row["amount_chx"])
        hist["hs300_close"].append(hs300_close)

        # MA 偏离度：用已有收盘序列计算（需要足够的此前数据）
        closes = [v for v in hist["hs300_close"] if v is not None]
        for n in (5, 20, 60):
            if hs300_close is not None and len(closes) >= n:
                ma = sum(closes[-n:]) / n
                hist["components"][f"dev{n}"].append(round(hs300_close / ma - 1, 6))
            else:
                hist["components"][f"dev{n}"].append(None)
        hist["components"]["amount_total"].append(row["amount_total"])
        hist["components"]["turnover"].append(row["turnover"])

        print(f"{d}: 成交额 {row['amount_total']}亿 换手 {row['turnover']}% "
              f"涨停 {row['limit_up']} 跌停 {row['limit_dn']} "
              f"HS300 {hs300_close}")

    compute.finalize(hist)

    with open(HIST, "w", encoding="utf-8") as fh:
        json.dump(hist, fh, ensure_ascii=False)

    render.render()
    print("更新完成")


if __name__ == "__main__":
    main()
