# -*- coding: utf-8 -*-
"""
A-Temperature · render.py
读取 history.json，生成静态单页 index.html（ECharts 图表内嵌数据）。
"""

import json
import os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_JSON = os.path.join(OUT_DIR, "history.json")
INDEX_HTML = os.path.join(OUT_DIR, "index.html")

COMPONENT_NAMES = [
    ("up_ratio",   "上涨家数占比",   "{:.1%}",  "全A上涨家数占有效样本比例"),
    ("limit_diff", "涨停减跌停",     "{:.0f}",  "涨停家数 − 跌停家数"),
    ("broke_rate", "炸板率（反向）", "{:.1%}",  "盘中触板未封住 / 曾涨停总数，取反向"),
    ("yday_avg",   "昨涨停今涨幅",   "{:.2f}%", "昨日涨停股今日平均涨幅"),
    ("max_streak", "最高连板",       "{:.0f}板", "当日市场最高连续涨停天数"),
    ("promo",      "首板晋级率",     "{:.1%}",  "昨日首板今日二板比例"),
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

    # 六项指标行
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

  .comp-row {{ display: grid; grid-template-columns: 140px 1fr 44px 90px;
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
      <div class="stat-chip chip-up"><div class="num">{latest['limit_up']}</div><div class="lbl">涨停</div></div>
      <div class="stat-chip chip-dn"><div class="num">{latest['limit_dn']}</div><div class="lbl">跌停</div></div>
      <div class="stat-chip"><div class="num">{latest['broke_rate']:.1%}</div><div class="lbl">炸板率</div></div>
      <div class="stat-chip"><div class="num">{latest['up_ratio']:.1%}</div><div class="lbl">上涨占比</div></div>
    </div>
  </div>

  <div class="card">
    <h2>01 情绪温度<span class="tag">近两年 · 灰=当日，橙=5日环境，蓝=10日环境</span></h2>
    <div id="chartTemp" class="chart"></div>
    <div style="margin-top:16px">
      <h2 style="margin-bottom:10px">六项构成<span class="tag">分位 = 当前值在近 250 个交易日中的排位</span></h2>
      {comp_rows}
    </div>
  </div>

  <div class="card">
    <h2>02 涨跌停家数<span class="tag">近两年 · 红=涨停，绿=跌停</span></h2>
    <div id="chartLimit" class="chart"></div>
  </div>

  <footer>
    <b>口径说明</b><br>
    样本：{data['meta']['sample']}<br>
    涨跌停：{data['meta']['limit_rule']}<br>
    炸板：{data['meta']['broke_rule']}<br>
    温度：{data['meta']['temp_rule']}<br>
    数据源：本地 Tushare parquet 数据湖（日线）
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
  legend: {{ top: 0, right: 0, textStyle: {{ color: '#868e96' }} }}
}});

// —— 涨跌停家数 ——
const c2 = echarts.init(document.getElementById('chartLimit'));
c2.setOption({{
  grid: {{ left: 42, right: 16, top: 24, bottom: 28 }},
  tooltip: {{ trigger: 'axis' }},
  xAxis: {{ type: 'category', data: dates, ...axis }},
  yAxis: {{ type: 'value', ...axis }},
  series: [
    {{ name: '涨停', type: 'bar', stack: 'l', data: slice(DATA.limit_up), itemStyle: {{ color: '#e03131' }} }},
    {{ name: '跌停', type: 'bar', stack: 'l', data: slice(DATA.limit_dn), itemStyle: {{ color: '#2f9e44' }} }}
  ],
  legend: {{ top: 0, right: 0, textStyle: {{ color: '#868e96' }} }}
}});

window.addEventListener('resize', () => {{ c1.resize(); c2.resize(); }});
</script>
</body>
</html>"""

    with open(INDEX_HTML, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"完成：{INDEX_HTML}")


if __name__ == "__main__":
    render()
