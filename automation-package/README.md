# 全球金融市场日报 — 自动化任务

> 每日自动生成全球金融市场日报，含A股/港股/美股行情、宏观数据、行业资金流、TOP10新闻，自动配语音并推送至GitHub Pages。

## 架构

```
                   ┌─────────────────┐
                   │ prefetch_data.py │  ← 数据预抓取（akshare全栈）
                   │  11个JSON文件    │
                   └────────┬────────┘
                            ↓
                   ┌─────────────────┐
                   │   LLM 提示词     │  ← task_prompt_v21.txt
                   │  生成 report.md  │
                   └────────┬────────┘
                            ↓
              ┌─────────────┼─────────────┐
              ↓             ↓             ↓
       md_to_reader.py  md_to_mp3.py    GitHub Push
       → daily-report.html  → daily-report.mp3
              ↓
           sw.js (Service Worker)
```

## 文件说明

| 文件 | 说明 |
|------|------|
| `scripts/prefetch_data.py` | 预抓取11个JSON数据源（akshare + 腾讯API + Google News RSS） |
| `prompt/task_prompt_v21.txt` | LLM完整提示词，内含嵌入式prefetch脚本 + 部署指令 |
| `scripts/md_to_reader.py` | Markdown→HTML朗读版转换（含样式+交互） |
| `scripts/md_to_mp3.py` | Markdown→MP3语音合成 |
| `web/sw.js` | PWA Service Worker（离线缓存） |

## 部署方式

### 方式一：自动化任务平台（推荐）

将 `prompt/task_prompt_v21.txt` 全文粘贴至自动化任务（如 CodeBuddy Scheduler）的 LLM 提示词中。
提示词末尾包含嵌入式部署指令（SSH密钥→Git Clone→Push），每日自动执行。

### 方式二：本地运行

```bash
# 1. 安装依赖
pip install akshare requests beautifulsoup4 edge-tts

# 2. 预抓取数据
python scripts/prefetch_data.py

# 3. 将 11 个 JSON 文件路径提供给 LLM，使用 prompt/ 中的提示词生成 report.md

# 4. 生成 HTML
python scripts/md_to_reader.py report.md daily-report.html

# 5. 生成 MP3
python scripts/md_to_mp3.py report.md daily-report.mp3
```

### 方式三：Docker（待补充）

### 数据源说明

| 源 | 内容 | akshare 接口 |
|----|------|-------------|
| 中/港/美股指数 | 5大A股/H股/全球指数 | `stock_zh_index_spot_sina` / `stock_hk_index_spot_sina` |
| 汇率/商品/债券 | USD/CNH、原油、黄金、中美债 | `futures_global_spot_em` / `bond_zh_us_rate` |
| 估值 | 全市场PE、5大指数PE/PB分位 | `stock_market_pe_lg` / 雪球蛋卷API |
| 行业资金 | 申万31行业涨跌幅 + 同花顺90行业资金流 | `index_realtime_sw` / `stock_board_industry_summary_ths` |
| 持仓分红 | 招行A/H、长电分红 + 研报 | `stock_history_dividend_detail` / `stock_hk_dividend_payout_em` |
| QDII溢价 | 40只QDII ETF 溢价率 | `qdii_a_index_jsl` / `qdii_e_index_jsl` |
| 宏观数据 | 中美宏观 + 全球央行利率 | `macro_china_*` / `macro_usa_*` / `macro_bank_*` |
| 新闻 | 全球TOP10（外媒5+国内5） | Google News RSS |
