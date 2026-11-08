# -*- coding: utf-8 -*-
"""
A-Temperature · render.py
读取 history.json，生成静态单页 index.html（ECharts 图表内嵌数据）。
"""

import json
import os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_HTML = os.path.join(OUT_DIR, "index.html")
HISTORY_JSON = os.path.join(OUT_DIR, "history.json")

COMPONENT_NAMES = [
    ("amount_total", "综合成交额",     "{:,.0f}亿",  "上证(含科创板)+深证主板+创业板合计成交额"),
    ("turnover",     "综合换手率",     "{:.2f}%",    "三板块 Σ成交额/Σ流通市值（市值加权）"),
    ("dev5",         "沪深300·MA5",   "{:+.2f}%",   "沪深300收盘价相对5日均线的偏离度"),
    ("dev20",        "沪深300·MA20",  "{:+.2f}%",   "沪深300收盘价相对20日均线的偏离度"),
    ("dev60",        "沪深300·MA60",  "{:+.2f}%",   "沪深300收盘价相对60日均线的偏离度"),
]


def fmt_temp_color(t):
    if t is None:
        return "#adb5bd", "—"
    if t < 25:
        return "#1c7ed6", "冰点"
    if t < 40:
        return "#74c0fc", "偏冷"
    if t < 60:
        return "#868e96", "中性"
    if t < 75:
        return "#f76707", "偏热"
    return "#e03131", "过热"


def render() -> None:
    with open(HISTORY_JSON, encoding="utf-8") as fh:
        data = json.load(fh)

    latest = data["latest"]
    date_fmt = f"{latest['date'][:4]}-{latest['date'][4:6]}-{latest['date'][6:]}"
    env5 = latest.get("temp_env5")
    env10 = latest.get("temp_env10")
    temp_color, temp_label = fmt_temp_color(env5)

    # 构成指标行
    comp_rows = ""
    for key, name, fmt, desc in COMPONENT_NAMES:
        v = latest.get(key)
        p = data["percentiles_latest"].get(key)
        raw = fmt.format(v) if v is not None else "—"
        pct = f"{p:.0f}" if p is not None else "—"
        bar_w = f"{p:.0f}" if p is not None else "0"
        comp_rows += f"""
        <div class="comp-row">
          <div class="comp-name" title="{desc}">{name}</div>
          <div class="comp-bar"><div class="comp-bar-fill" style="width:{bar_w}%"></div></div>
          <div class="comp-pct">{pct}</div>
          <div class="comp-val">{raw}</div>
        </div>"""

    amt_txt = f"{latest['amount_total']:,.0f}" if latest.get('amount_total') is not None else '—'
    to_txt = f"{latest['turnover']:.2f}%" if latest.get('turnover') is not None else '—'

    payload = json.dumps(data, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>A-Temperature · A股情绪温度</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
<style>
  :root {{
    --bg: #f8f9fa; --card: #ffffff; --ink: #212529; --ink2: #868e96;
    --line: #e9ecef; --red: #e03131; --green: #2f9e44; --accent: #f76707;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
         background: var(--bg); color: var(--ink); padding: 24px 16px 48px; }}
  .wrap {{ max-width: 960px; margin: 0 auto; }}
  header {{ margin-bottom: 20px; }}
  h1 {{ font-size: 22px; letter-spacing: .5px; }}
  h1 .en {{ color: var(--ink2); font-weight: 400; font-size: 15px; margin-left: 8px; }}
  .sub {{ color: var(--ink2); font-size: 13px; margin-top: 6px; }}
  .card {{ background: var(--card); border: 1px solid var(--line); border-radius: 12px;
          padding: 20px 24px; margin-bottom: 16px; }}
  .card h2 {{ font-size: 15px; margin-bottom: 14px; color: var(--ink); }}
  .card h2 .tag {{ font-size: 12px; color: var(--ink2); font-weight: 400; margin-left: 8px; }}

  .hero {{ display: flex; align-items: center; gap: 28px; flex-wrap: wrap; }}
  .temp-big {{ font-size: 56px; font-weight: 700; line-height: 1; color: {temp_color}; }}
  .temp-big small {{ font-size: 18px; font-weight: 400; color: var(--ink2); }}
  .temp-meta {{ font-size: 13px; color: var(--ink2); line-height: 1.8; }}
  .temp-meta b {{ color: var(--ink); font-weight: 600; }}
  .stat-chip {{ background: var(--bg); border-radius: 10px; padding: 10px 16px; text-align: center; }}
  .stat-chip .num {{ font-size: 22px; font-weight: 700; }}
  .stat-chip .lbl {{ font-size: 12px; color: var(--ink2); margin-top: 2px; }}
  .chip-up .num {{ color: var(--red); }}
  .chip-dn .num {{ color: var(--green); }}

  .chart {{ width: 100%; height: 340px; }}

  .comp-row {{ display: grid; grid-template-columns: 140px 1fr 44px 100px;
              align-items: center; gap: 12px; padding: 7px 0; font-size: 13px;
              border-bottom: 1px dashed var(--line); }}
  .comp-row:last-child {{ border-bottom: none; }}
  .comp-name {{ color: var(--ink); }}
  .comp-bar {{ height: 8px; background: var(--bg); border-radius: 4px; overflow: hidden; }}
  .comp-bar-fill {{ height: 100%; background: linear-gradient(90deg, #74c0fc, #f76707, #e03131);
                   border-radius: 4px; }}
  .comp-pct {{ color: var(--ink2); text-align: right; }}
  .comp-val {{ text-align: right; font-weight: 600; }}

  footer {{ color: var(--ink2); font-size: 12px; line-height: 1.9; margin-top: 20px; }}
  footer b {{ color: var(--ink); }}
  .disclaimer {{ text-align: center; color: var(--ink2); font-size: 12px; margin-top: 16px; }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>A-Temperature<span class="en">A股情绪温度 · 每日复盘</span></h1>
    <div class="sub">数据截至 <b>{date_fmt}</b> · 生成于 {data['generated_at']} · 由本地数据湖自动计算</div>
  </header>

  <div class="card">
    <div class="hero">
      <div>
        <div class="temp-big">{env5 if env5 is not None else '—'}<small> /100</small></div>
        <div class="temp-meta">5日环境温度 · <b>{temp_label}</b></div>
      </div>
      <div class="stat-chip"><div class="num">{latest['temp'] if latest['temp'] is not None else '—'}</div><div class="lbl">当日温度</div></div>
      <div class="stat-chip"><div class="num">{env10 if env10 is not None else '—'}</div><div class="lbl">10日环境</div></div>
      <div class="stat-chip"><div class="num">{amt_txt}</div><div class="lbl">成交额(亿)</div></div>
      <div class="stat-chip"><div class="num">{to_txt}</div><div class="lbl">换手率</div></div>
      <div class="stat-chip chip-up"><div class="num">{latest['limit_up']}</div><div class="lbl">涨停</div></div>
      <div class="stat-chip chip-dn"><div class="num">{latest['limit_dn']}</div><div class="lbl">跌停</div></div>
    </div>
  </div>

  <div class="card">
    <h2>01 情绪温度<span class="tag">近两年 · 灰=当日，橙=5日环境，蓝=10日环境</span></h2>
    <div id="chartTemp" class="chart"></div>
    <div style="margin-top:16px">
      <h2 style="margin-bottom:10px">构成指标<span class="tag">分位 = 当前值在近 250 个交易日中的排位</span></h2>
      {comp_rows}
    </div>
  </div>

  <div class="card">
    <h2>02 综合成交量<span class="tag">近两年 · 上证+深证主板+创业板 成交额（亿元）</span></h2>
    <div id="chartAmount" class="chart"></div>
  </div>

  <div class="card">
    <h2>03 综合换手率<span class="tag">近两年 · Σ成交额/Σ流通市值（%）</span></h2>
    <div id="chartTurnover" class="chart"></div>
  </div>

  <div class="card">
    <h2>04 沪深300 与均线<span class="tag">近两年 · 收盘价与 MA5/MA20/MA60</span></h2>
    <div id="chartHS300" class="chart"></div>
  </div>

  <div class="card">
    <h2>05 涨跌停家数<span class="tag">近两年 · 红=涨停，绿=跌停</span></h2>
    <div id="chartLimit" class="chart"></div>
  </div>

  <footer>
    <b>口径说明</b><br>
    样本：{data['meta']['sample']}<br>
    成交量：{data['meta']['amount_rule']}<br>
    换手率：{data['meta']['turnover_rule']}<br>
    均线关系：{data['meta']['dev_rule']}<br>
    温度：{data['meta']['temp_rule']}<br>
    数据源：本地 Tushare parquet 数据湖（日线 + daily_basic）· 沪深300 指数日线
  </footer>
  <div class="disclaimer">本页面由程序按固定规则自动生成，仅供复盘与学习，不构成任何投资建议。</div>
</div>

<script>
const DATA = {payload};
const fmtDate = d => d.slice(0,4) + '-' + d.slice(4,6) + '-' + d.slice(6);

// 近两年窗口
const N = Math.min(DATA.dates.length, 500);
const slice = arr => arr.slice(-N);
const dates = DATA.dates.slice(-N).map(fmtDate);

const axis = {{ axisLabel: {{ color: '#868e96', fontSize: 11 }}, axisLine: {{ lineStyle: {{ color: '#e9ecef' }} }} }};
const legend = {{ top: 0, right: 0, textStyle: {{ color: '#868e96' }} }};

// —— 情绪温度 ——
const c1 = echarts.init(document.getElementById('chartTemp'));
c1.setOption({{
  grid: {{ left: 42, right: 16, top: 24, bottom: 28 }},
  tooltip: {{ trigger: 'axis', valueFormatter: v => v == null ? '—' : v }},
  xAxis: {{ type: 'category', data: dates, ...axis }},
  yAxis: {{ type: 'value', min: 0, max: 100, ...axis }},
  series: [
    {{ name: '当日温度', type: 'line', data: slice(DATA.temp), showSymbol: false,
       lineStyle: {{ color: '#adb5bd', width: 1 }}, itemStyle: {{ color: '#adb5bd' }}, z: 1 }},
    {{ name: '10日环境', type: 'line', data: slice(DATA.temp_env10), showSymbol: false, connectNulls: true,
       lineStyle: {{ color: '#378ADD', width: 1.8 }}, itemStyle: {{ color: '#378ADD' }}, z: 2 }},
    {{ name: '5日环境', type: 'line', data: slice(DATA.temp_env5), showSymbol: false, connectNulls: true,
       lineStyle: {{ color: '#f76707', width: 2.5 }}, itemStyle: {{ color: '#f76707' }}, z: 3 }}
  ],
  legend
}});

// —— 综合成交量（堆叠柱） ——
const c2 = echarts.init(document.getElementById('chartAmount'));
c2.setOption({{
  grid: {{ left: 56, right: 16, top: 24, bottom: 28 }},
  tooltip: {{ trigger: 'axis', valueFormatter: v => v == null ? '—' : v + ' 亿' }},
  xAxis: {{ type: 'category', data: dates, ...axis }},
  yAxis: {{ type: 'value', name: '亿元', ...axis }},
  series: [
    {{ name: '上证', type: 'bar', stack: 'a', data: slice(DATA.amount_sh), itemStyle: {{ color: '#e03131' }} }},
    {{ name: '深证主板', type: 'bar', stack: 'a', data: slice(DATA.amount_sz), itemStyle: {{ color: '#f76707' }} }},
    {{ name: '创业板', type: 'bar', stack: 'a', data: slice(DATA.amount_chx), itemStyle: {{ color: '#378ADD' }} }}
  ],
  legend
}});

// —— 综合换手率 ——
const c3 = echarts.init(document.getElementById('chartTurnover'));
c3.setOption({{
  grid: {{ left: 56, right: 16, top: 24, bottom: 28 }},
  tooltip: {{ trigger: 'axis', valueFormatter: v => v == null ? '—' : v + '%' }},
  xAxis: {{ type: 'category', data: dates, ...axis }},
  yAxis: {{ type: 'value', name: '%', ...axis, scale: true }},
  series: [
    {{ name: '综合换手率', type: 'line', data: slice(DATA.components.turnover), showSymbol: false,
       lineStyle: {{ color: '#7048e8', width: 1.8 }}, itemStyle: {{ color: '#7048e8' }} }}
  ]
}});

// —— 沪深300 与均线 ——
const c4 = echarts.init(document.getElementById('chartHS300'));
c4.setOption({{
  grid: {{ left: 56, right: 16, top: 24, bottom: 28 }},
  tooltip: {{ trigger: 'axis' }},
  xAxis: {{ type: 'category', data: dates, ...axis }},
  yAxis: {{ type: 'value', scale: true, ...axis }},
  series: [
    {{ name: '沪深300', type: 'line', data: slice(DATA.hs300_close), showSymbol: false,
       lineStyle: {{ color: '#212529', width: 1.8 }}, itemStyle: {{ color: '#212529' }}, z: 3 }},
    {{ name: 'MA5', type: 'line', data: slice(DATA.hs300_ma5), showSymbol: false, connectNulls: true,
       lineStyle: {{ color: '#f76707', width: 1 }}, itemStyle: {{ color: '#f76707' }} }},
    {{ name: 'MA20', type: 'line', data: slice(DATA.hs300_ma20), showSymbol: false, connectNulls: true,
       lineStyle: {{ color: '#378ADD', width: 1 }}, itemStyle: {{ color: '#378ADD' }} }},
    {{ name: 'MA60', type: 'line', data: slice(DATA.hs300_ma60), showSymbol: false, connectNulls: true,
       lineStyle: {{ color: '#7048e8', width: 1 }}, itemStyle: {{ color: '#7048e8' }} }}
  ],
  legend
}});

// —— 涨跌停家数 ——
const c5 = echarts.init(document.getElementById('chartLimit'));
c5.setOption({{
  grid: {{ left: 42, right: 16, top: 24, bottom: 28 }},
  tooltip: {{ trigger: 'axis' }},
  xAxis: {{ type: 'category', data: dates, ...axis }},
  yAxis: {{ type: 'value', ...axis }},
  series: [
    {{ name: '涨停', type: 'bar', stack: 'l', data: slice(DATA.limit_up), itemStyle: {{ color: '#e03131' }} }},
    {{ name: '跌停', type: 'bar', stack: 'l', data: slice(DATA.limit_dn), itemStyle: {{ color: '#2f9e44' }} }}
  ],
  legend
}});

window.addEventListener('resize', () => {{ c1.resize(); c2.resize(); c3.resize(); c4.resize(); c5.resize(); }});
</script>
</body>
</html>"""

    with open(INDEX_HTML, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"完成：{INDEX_HTML}")


if __name__ == "__main__":
    render()
