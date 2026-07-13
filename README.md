# 每日金融日报

基于 GitHub Actions 自动运行的全球金融市场日报生成系统。每日（北京时间 05:30）抓取行情数据后调用 LLM 生成结构化日报，同步输出 Markdown 报告、HTML 朗读版和 MP3 音频，自动部署至 `docs/` 目录并发布到 GitHub Pages。

## 工作流程

```
schedule / workflow_dispatch
        ↓
  prefetch_data.py   ← 按三市场交易日历门控，抓取 data_*.json（数量动态）
        ↓
  call_llm.py        ← 调用 LLM 生成 report.md（不联网，仅基于预抓取 JSON）
        ↓
  md_to_reader.py    ← report.md → daily-report.html（朗读版）
  md_to_script.py    ← report.md → script.txt（广播稿）
  md_to_mp3.py       ← script.txt → daily-report.mp3（音频，Edge TTS）
        ↓
  部署到 docs/ 目录   ← 推送到 main 分支 → GitHub Pages 发布
```

## 触发方式

| 方式 | 说明 |
|------|------|
| **schedule（定时）** | 每日 `30 21 * * *`（UTC 21:30 = 北京时间次日 05:30）— 预留约 80 分钟调度延迟，目标 07:10 前出报告 |
| **workflow_dispatch（手动）** | 支持手动触发，可选 `skip_mp3=true` 跳过音频生成 |

> ⚠️ GitHub Actions schedule 事件存在注册延迟（首次启用或改 cron 后可能延迟数十分钟至 1 小时），若定时未触发可手动运行一次。

## LLM 模型优先级

| 优先级 | 模型 | API 端点 | 环境变量 |
|--------|------|----------|---------|
| ① 主模型 | **NVIDIA GLM-5.2** (`z-ai/glm-5.2`) | `integrate.api.nvidia.com/v1` | `NVIDIA_API_KEY` |
| ② 兜底 | **商汤 DeepSeek-V4-Flash** (`deepseek-v4-flash`) | `token.sensenova.cn/v1` | `SENSENOVA_API_KEY` |
| ③ 最终兜底 | **NVIDIA Nemotron-3-Ultra-550B** (`nvidia/nemotron-3-ultra-550b-a55b`) | `integrate.api.nvidia.com/v1` | `NVIDIA_API_KEY` |

- 三个模型依次尝试，前一个失败自动切换到下一个
- 失败时自动重试（指数退避）
- **LLM 仅基于预抓取的 `data_*.json` 加工，不联网搜索、不调用工具**

## 模式自动判定（三市场交易日历）

报告在北京时间 05:30 触发，覆盖"昨日（D-1）收盘 + 今晨美股凌晨收盘"。由 `scripts/trading_calendar.py` 用真·交易日历判定昨日各市场是否开市（不靠周几二分，可正确处理节假日/调休）：

| 市场 | 日历来源 | 开市判定 |
|------|----------|----------|
| A 股 | akshare `tool_trade_date_hist_sina` | 昨日为 A 股交易日 |
| 美股 | `pandas_market_calendars` XNYS | 昨日为美股交易日 |
| 港股 | `pandas_market_calendars` XHKG | 昨日为港股交易日 |

**模式规则**：

| 条件 | 执行模式 | 抓取模块 |
|------|----------|----------|
| `A股开市 OR 美股开市 OR 港股开市` | **完整模式** | 按开市市场逐模块抓取（休市市场 JSON 不生成）+ 始终抓 RSS 新闻 |
| 三市场均休市（通常周日/周一） | **精简模式** | 仅抓 `data_news_rss.json`（纯新闻：全球 TOP 10 + 深度观察专栏） |

> 任一日历网络获取失败时降级为"看昨天星期几 ≤4 即视为开市"。

## 数据源路由

| 数据类型 | 主数据源 | 门控条件 | 兜底 |
|---------|---------|----------|------|
| A 股指数 | akshare 新浪 `stock_zh_index_spot_sina` | `a_open` | 腾讯财经 / yfinance |
| 港股指数 | akshare 新浪 `stock_hk_index_spot_sina` | `hk_open` | 腾讯财经 / yfinance |
| 美股+全球指数 | akshare 新浪（美股）+ 东财（外围） | `u_open` | 东财走 curl_cffi HTTP/2；否则 yfinance |
| 汇率/商品/债券 | akshare 期货 + 中美债收益率 | 完整模式 | — |
| 估值/PE 分位（6 指数） | 雪球蛋卷 API `danjuanfunds.com/djapi/index_eva/dj` | `a_open` | — |
| 基金净值/溢价 | akshare 天天基金 + 东方财富净值 HTTP | `a_open OR u_open` | — |
| 行业轮动+资金流 | akshare（申万+同花顺+乐咕乐股） | `a_open` | — |
| 个人持仓行情 | 腾讯财经 `qt.gtimg.cn` | `a_open OR u_open` | yfinance |
| 资金面+QDII+涨停/跌停+LPR/PMI | akshare + 东方财富 | `a_open` | — |
| **全球 TOP 10 新闻** | **Google News RSS** | 始终抓 | — |

> **方案 C（curl_cffi HTTP/2 补丁）**：东方财富 `push2.eastmoney.com` / `push2his.eastmoney.com` 需 HTTP/2，标准 `requests` 仅 HTTP/1.1 会静默断连。脚本在顶部注入 `curl_cffi` 浏览器模拟，仅对这两个域名生效，修复全球指数静默降级；其余请求不受影响。运行依赖已包含 `curl_cffi` 与 `pandas_market_calendars`。

## 新闻原文链接

每条新闻末尾的来源媒体名已嵌入原文链接，支持点击跳转：

- **Markdown 报告**（`daily-report.md`）：`（[Reuters](原文链接)）` — 在 GitHub 或 Markdown 查看器中点击媒体名跳转
- **HTML 朗读版**（`daily-report.html`）：`<a href="原文链接">Reuters</a>` — 在浏览器中点击媒体名跳转（新标签页）
- 链接为 Google News 重定向链接，自动跳转至原始文章
- 精简模式与完整模式均支持此功能

## 汇率转换

- 自动抓取 USD/CNH 汇率，首次刷新后缓存当日汇率
- A 股/港股/美股/基金四类资产的盈亏统一以人民币计价

## GitHub Secrets

| Secret | 用途 |
|--------|------|
| `NVIDIA_API_KEY` | NVIDIA NIM API Key（免费） |
| `SENSENOVA_API_KEY` | 商汤科技 API Key（免费） |

## 文件结构

```
.
├── .github/workflows/daily-scheduled.yml   # GitHub Actions 工作流（cron 30 21 * * *）
├── prompt/
│   └── daily_report_prompt.txt             # LLM 系统提示词（含完整/精简模式指令 + 市场门控硬规则）
├── scripts/
│   ├── prefetch_data.py                     # 数据抓取（v30，三市场门控 + curl_cffi HTTP/2 补丁）
│   ├── trading_calendar.py                  # 三市场交易日历判定（A股/美股/港股）
│   ├── call_llm.py                          # LLM 调用（含模式判定 + 模型切换 + 市场标志注入）
│   ├── md_to_reader.py                      # Markdown → HTML（朗读版）
│   ├── md_to_script.py                      # Markdown → 广播稿
│   └── md_to_mp3.py                         # 广播稿 → MP3（Edge TTS）
├── web/
│   └── sw.js                                # Service Worker（离线缓存）
├── docs/                                    # 部署目录（自动生成）
│   ├── daily-report.html                    # HTML 朗读版
│   ├── daily-report.md                      # Markdown 完整报告
│   ├── daily-report.mp3                     # 音频文件
│   └── sw.js                                # 前端 Service Worker
└── README.md
```

## 发布地址

- GitHub Pages：`https://homjanon.github.io/portfolio/`
