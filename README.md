# 每日金融日报

基于 GitHub Actions 自动运行的全球金融市场日报生成系统。每日抓取行情数据后调用 LLM 生成结构化日报，同步输出 Markdown 报告、HTML 朗读版和 MP3 音频，自动部署至 `docs/` 目录。

## 工作流程

```
schedule / workflow_dispatch
        ↓
  prefetch_data.py   ← 抓取 10 类数据 JSON
        ↓
  call_llm.py        ← 调用 LLM 生成 report.md
        ↓
  md_to_reader.py    ← report.md → daily-report.html（朗读版）
  md_to_script.py    ← report.md → script.txt（广播稿）
  md_to_mp3.py       ← script.txt → daily-report.mp3（音频）
        ↓
  部署到 docs/ 目录   ← 推送到 main 分支
```

## 触发方式

| 方式 | 说明 |
|------|------|
| **schedule（定时）** | 每日 UTC 06:00（北京时间 14:00）— 临时调早验证中，验证后改回 UTC 01:00（北京时间 09:00） |
| **workflow_dispatch（手动）** | 支持手动触发，可选 `skip_mp3=true` 跳过音频生成 |

> ⚠️ 因 GitHub Actions schedule 事件存在注册延迟，若定时未触发可手动运行一次。

## LLM 模型优先级

| 优先级 | 模型 | API 端点 | 环境变量 |
|--------|------|----------|---------|
| ① 主模型 | **NVIDIA GLM-5.2** (`z-ai/glm-5.2`) | `integrate.api.nvidia.com/v1` | `NVIDIA_API_KEY` |
| ② 兜底 | **商汤 DeepSeek-V4-Flash** (`deepseek-v4-flash`) | `token.sensenova.cn/v1` | `SENSENOVA_API_KEY` |
| ③ 最终兜底 | **NVIDIA Nemotron-3-Ultra-550B** (`nvidia/nemotron-3-ultra-550b-a55b`) | `integrate.api.nvidia.com/v1` | `NVIDIA_API_KEY` |

- 三个模型依次尝试，前一个失败自动切换到下一个
- 失败时自动重试 3 次（指数退避）

## 模式自动判定

根据**北京时间**自动选择执行模式：

| 星期（北京时间） | 执行模式 | 说明 |
|-----------------|---------|------|
| 周二 ~ 周六 | **完整模式** | 全部板块：市场全景 + 行业洞察 |
| 周日 / 周一 | **精简模式** | 仅行业洞察（全球 TOP 10 + 资金回顾 + 深度观察专栏） |

> 周六对应美股周五收盘数据、A 股周五收盘数据，有行情数据可展示，故执行完整模式。
> 周一全球主要市场均休市（A 股/港股周末、美股周日盘），无新鲜行情，执行精简模式。

## 数据源路由

| 数据类型 | 主数据源 | 兜底 |
|---------|---------|------|
| A 股指数 | 腾讯财经 API | — |
| 港股指数 | 腾讯财经 API | — |
| 美股+全球指数 | akshare 新浪 | yfinance |
| 汇率/商品/债券 | akshare 新浪+期货 | — |
| 估值/PE 分位 | 雪球蛋卷 API | — |
| 基金净值/溢价 | akshare 天天基金 | 东方财富历史净值 |
| 行业轮动+资金流 | akshare（申万+同花顺+乐咕乐股） | — |
| 个人持仓行情 | 腾讯财经 API | — |
| **全球 TOP 10 新闻** | **Google News RSS** | — |
| 资金面+QDII 监测 | akshare + 东方财富 | — |

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
| `NVIDIA_API_KEY` | NVIDIA NIM API Key（免费，有效期 12 个月） |
| `SENSENOVA_API_KEY` | 商汤科技 API Key（免费） |

## 文件结构

```
.
├── .github/workflows/daily-newsletter.yml   # GitHub Actions 工作流
├── prompt/
│   └── daily_report_prompt.txt              # LLM 系统提示词
├── scripts/
│   ├── prefetch_data.py                     # 数据抓取（10 类 JSON）
│   ├── call_llm.py                          # LLM 调用（含模式判定+模型切换）
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
