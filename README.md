# A-Temperature

A股情绪温度 · 每日复盘单页。

- **在线页面**：https://ellis-zjz.github.io/A-Temperature/
- **更新机制**：GitHub Actions 每个交易日 18:50（北京时间）自动运行 `update_daily.py`，
  从 Tushare Pro 拉取当日日线截面，增量计算指标并重新渲染页面。
- **指标口径**：详见页面底部说明。数据由程序按固定规则生成，仅供复盘与学习，**不构成任何投资建议**。

## 本地全量重算（可选）

`compute.py` 依赖本地 Tushare parquet 数据湖，仅开发环境使用；
线上更新走 `update_daily.py` + Tushare API，不需要数据湖。
