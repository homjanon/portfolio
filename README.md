# 每日金融日报
基于 Cloudflare Worker（qdii-dispatch）自动调度的全球金融市场日报生成系统。每日北京时间 06:30 由 Cloudflare 触发 `workflow_dispatch`（GitHub 侧不再配置 schedule），抓取行情数据后调用 LLM 生成结构化日报，同步输出 Markdown 报告、HTML 朗读版和 MP3 音频，自动部署至 `docs/`（最新报告 + `docs/archive/` 下按日期归档的 30 天历史）并发布到 GitHub Pages。

## 工作流程

```
Cloudflare qdii-dispatch → workflow_dispatch
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
| **workflow_dispatch（定时·单通道）** | 每日北京时间 06:30 由 Cloudflare Worker `qdii-dispatch`（心跳每5分钟）调 GitHub API 触发，绕开 Actions 共享 cron 队列的调度延迟/偶发漏触发 |
| **workflow_dispatch（手动）** | 支持手动触发，可选 `skip_mp3=true` 跳过音频生成 |

> 触发链路：Cloudflare 心跳（每 5 分钟）→ 北京 06:30 到点 → `workflow_dispatch` → Actions 运行。GitHub 侧不使用 schedule（单通道触发），漏跑可手动 `/trigger?repo=portfolio&key=...` 补一次。

## 日报 LLM 模型优先级

| 优先级 | 模型 | API 端点 | 环境变量 |
|--------|------|----------|---------|
| ① 主模型 | **Agnes agnes-2.5-flash** (`agnes-2.5-flash`) | `apihub.agnes-ai.com/v1` | `AGNES_API_KEY` |
| ② 次选 | **Google Gemini 3.8 Flash** (`gemini-3.8-flash`) | `generativelanguage.googleapis.com/v1beta/openai` | `GEMINI_API_KEY` |
| ③ 备选 | **商汤 SenseNova DeepSeek-V4-Flash** (`deepseek-v4-flash`) | `token.sensenova.cn/v1` | `SENSENOVA_API_KEY` |
| ④ 兜底 | **Google Gemini 3.5 Flash-Lite** (`gemini-3.5-flash-lite`) | `generativelanguage.googleapis.com/v1beta/openai` | `GEMINI_API_KEY` |

- 四个模型依次尝试，前一个失败（异常或输出 <500 字符判为近空）自动切换到下一个
- 失败时自动重试（指数退避）；**但 403/404/410 属永久性错误，不重试、立即切换下一模型**
- 商汤后端带 `reasoning_effort=low` 轻思考（实测 12s→2.6s 且 content 稳定非空）

> **⚠️ 架构提示**：四层跨 3 个平台（Agnes/新加坡 → Google/美国 → 商汤/国内 → Google/美国）。**②④ 两层共用 `GEMINI_API_KEY`（同一配额池），Gemini 侧限流或故障会连废两层**——第 ③层商汤夹在中间作隔离。
>
> **Agnes 2.5 能力规格**：上下文 512K、最大输出 65.5K，现价输入/输出均 `$0 / 1M tokens`（刊例价 $0.05 / $0.15）。`_call_llm` 响应字段兼容 `content or reasoning_content or reasoning`（商汤 deepseek-v4-flash 的 content 常为空、答案在 `reasoning_content`，缺兼容时该层会静默失效）。
>
> **⚠️ 推理模型避坑**：推理档模型（如 `agnes-3.0-flash`）在长日报（58K tokens 输入）下单次生成耗时远超 Actions 的 90s 上限 → **主模型须用非推理档（现为 `agnes-2.5-flash`）**。`_call_llm` 保留 `enable_thinking` 关闭机制与 `max_tokens=16000`，供后续接入更快推理模型时复用。
>
> **⚠️ Gemini 3 系无法关闭思考**（官方明确）→ `_THINKING_OFF_BACKENDS`（发 `enable_thinking=false`）对其**无效**，唯一降延迟杠杆是 `reasoning_effort`。
>
> **免费档实测要点**（Google，规模 system 15,426 + user 58,667 ≈ 74K 字符，即线上真实量级）：`gemini-3.8-flash` 长输入 **25.0s** 最快 → ② 层；`gemini-3.5-flash-lite` **6/6 通过、14.5–24.1s** → ④ 层；`gemini-3.5-flash` / `3.6-flash` 需 50–65s 逼近 90s 上限，未采用；`gemini-3-flash-preview` 两轮全 503，已排除。免费档 503「high demand」拥堵率长输入约 **42%**，由 `_call_llm` 的 2 次重试 + 下层兜底覆盖。
>
> **⚠️ 改模型必读**：`scripts/md_to_script.py` 的 `_MODEL_CHAIN` 按 `name` 从 `LLM_CONFIGS` 精确匹配取值，**两处名字必须同步改**，对不上会被静默跳过（不报错，直接少一层兜底）。

- **LLM 仅基于预抓取的 `data_*.json` 加工，不联网搜索、不调用工具**

## 模式自动判定（三市场交易日历）
报告在北京时间约 06:30 由 Cloudflare 触发生成（GitHub 侧不再有 schedule），覆盖"昨日（D-1）收盘 + 今晨美股凌晨收盘"。由 `scripts/trading_calendar.py` 用真·交易日历判定昨日各市场是否开市（不靠周几二分，可正确处理节假日/调休）：

| 市场 | 日历来源 | 开市判定 |
|------|----------|----------|
| A 股 | akshare `tool_trade_date_hist_sina` | 昨日为 A 股交易日 |
| 美股 | `pandas_market_calendars` XNYS | 昨日为美股交易日 |
| 港股 | `pandas_market_calendars` XHKG | 昨日为港股交易日 |
**模式规则**：

| 条件 | 执行模式 | 抓取模块 |
|------|----------|----------|
| `A股开市 OR 美股开市 OR 港股开市` | **完整模式** | 按开市市场逐模块抓取（休市市场 JSON 不生成）+ 始终抓 RSS 新闻 |
| 三市场均休市（通常周日/周一） | **精简模式** | 仅抓 `data_news.json`（Top20：谷歌美国20条→LLM去重精选10条,剔除后从候选内补位 + 联合早报最新10,统一六实例兜底；两块独立互不补位）+ `data_deep.json`（深度观察专栏·**法广中文** `/rfi/cn` 单源（取最新 10 条）；**先按关键词硬筛「非中美」与非文章条目，再由 LLM 选 1 篇中国/美国之外的第三方深度文章原文直出**；无合格候选则今日暂停） |

> 任一日历网络获取失败时降级为"看昨天星期几 ≤4 即视为开市"。
> **收盘日期标注（MarketDateResolver）**：报告「一、市场全景」各市场收盘均按真实交易日历标注业务日期与北京时间收盘时刻，由 `scripts/market_date_resolver.py` 的 `MarketDateResolver` 在 LLM 调用前注入。A股/港股/日经/韩国/欧洲取上一交易日（如 `A股收盘（7月13日）`），美股取美东前一交易日但于北京时间今天凌晨收盘（如 `美股收盘（7月14日凌晨）`）。海外用 `pandas_market_calendars`（DST 自动适配，禁止手写时区偏移），A股用 `tool_trade_date_hist_sina`（本地文件缓存，避免每次网络请求）。美股另做新鲜度校验：若 akshare 实际返回日期早于解析业务日期，置 `_stale` 提示数据可能滞后。**全球/港股指数新鲜度闸门**：各指数走多源取数链（全球指数：东财 push2delay → 新浪 `znb_` → akshare → yfinance；A股/港股/美股：腾讯 → 东财 → 新浪 → yfinance），结果带「数据日期」与本批最新值比对——落后 ≤3 天视为休市正常，真滞后则重挑源/标 `_stale`（拦截「旧值当新值写进报告」）。

## 数据源路由

| 数据类型 | 主数据源 | 门控条件 | 兜底 |
|---------|---------|----------|------|
| A 股指数 | **腾讯财经 `qt.gtimg.cn`**（批量，`sh000001` 等） | `a_open` | 东财 push2（push2delay，0.6s 限速） → 新浪 `s_sh000001` → yfinance（`000001.SS` 等） |
| 港股指数 | **腾讯财经**（`hkHSI` / `hkHSCEI` / `hkHSTECH`） | `hk_open` | 东财 push2（`100.HSI`/`100.HSCEI`/`124.HSTECH`） → 新浪 `rt_hk*` → yfinance（`^HSI` / `^HSCE` / **`HSTECH.HK`**） |
| 美股指数 | **腾讯财经**（`usDJI`/`usINX`/`usIXIC`/`usNDX`） | `u_open` | 东财 push2 → 新浪 `gb_$dji` 等 → yfinance |
| 全球指数（日经/KOSPI/STOXX600/DAX/富时/CAC） | **东财 push2delay**（`100.N225`/`100.KS11`/`100.SXXP`/`100.GDAXI`/`100.FTSE`/`100.FCHI`） | `u_open` | 新浪 `znb_*`（日期取 `[6]`） → akshare `index_global_spot_em`（东财 clist，与 push2delay 属不同端点） → yfinance（`^N225`/`^KS11`/`^STOXX`/`^GDAXI`/`^FTSE`/`^FCHI`）。⚠️ STOXX600 在新浪（`znb_SXXP` 陈旧）与 akshare 清单中均无有效代码 → 实际双源（东财 + yfinance）；单条失败只标该指数暂不可得，不影响其余 |
| 汇率/商品/债券 | **新浪外盘期货 `hf_`**（`hf_CL`/`hf_OIL`/`hf_GC`/`hf_SI`，一次批量取，详见下方「原油／贵金属取数口径」）→ 新浪缺失时以 akshare `futures_global_spot_em` 的 `00Y`（当月连续）兜底（**布伦特不用该兜底**）+ 中美债收益率 | 完整模式 | — |
| 估值/PE 分位（11 指数，固定顺序） | 雪球蛋卷 API `danjuanfunds.com/djapi/index_eva/dj`（1 次返回 63，白名单 11） | `a_open` | — |
| 个人持仓行情 | 腾讯财经 `qt.gtimg.cn` | `a_open OR u_open` | yfinance |
| QDII监测+USD/CNH汇率 | 腾讯API+东方财富(净值)+新浪外汇(fx_susdcnh离岸即期市场价，买卖中值；→yfinance USDCNH=X兜底→外汇局中间价末位兜底并标注非市场价，场外QDII：纳指/标普各取5只(含QDII-FOF) + 热门全球QDII固定清单11只，均不限购置顶) | `a_open` | — |
| **全球 Top20 新闻** | **Google News 美国一地（20条全量交LLM去重精选10条,剔除后从候选内补位；解析带 HTTP 状态检查 + lxml recover 容错，429/非法XML不整份失败；失败/空结果指数退避重试3次，仍失败兜底谷歌英国区 hl=en-GB&gl=GB&ceid=GB:en，同 TOPIC 换地域参数）+ 联合早报 RSS（统一六实例兜底，最新10）；两块独立互不补位** | 始终抓 | `data_news.json` + `data_cls_zaobao.json` |
| **深度观察专栏（仅精简模式）** | **单源：法广中文** `/rfi/cn`（统一实例池兜底，但为深度源启用 **desc 中位长度门槛 ≥700 字**：不达标继续试下一实例、全不达标取最长者并告警——根治“锁死导语版实例”；取最新 10 条）。**选源依据**：法广各可用实例返回的均为全文（中位 1025–1289 字）。**代码侧先硬筛**：标题含涉中美词（中国/美国/中美/台海/港澳/新疆/西藏/南海/白宫/中南海/习近平/特朗普…含「对美」「两强相争」等隐性词）或非文章条目（播音节目表）一律剔除，超长文（>6000 字）不入池；**再由 LLM 做语义精筛并选 1 篇「中国与美国之外」的第三方深度文章原文直出**（零改写；LLM 须排除标题干净但主题涉华涉美的条目，如《纽伦堡文革60周年研讨会对文革的反思》；合规候选均不够深度时降级选其中话题性最强的一篇；全部涉中美则今日暂停） | 仅精简模式 | `data_deep.json`（`items_deep` 数组） |
| **市场全景各板块一段简述（50–100字）+ 持仓聚焦（按持仓行业关键词预匹配 `industry_match`，仅命中行业的新闻入选，所有标的行业命中即入选）** | **财联社 + 格隆汇 RSS 合并抓取（财联社 telegraph + 格隆汇两组均走统一六实例兜底（命中即止），格隆汇另以 rss.injahow.cn（.cn 专属实例，实测仅支持格隆汇）为首选；合并后标题归一化去重、北京当天筛选，格隆汇缺 pubDate 视为当日保留；LLM 优先采用标题含板块关键词的条目直接复用收盘情况，否则综合最相关若干条写成 50–100 字一段、丰富该市场最新情况）** | 完整模式 | 无当天新闻则留空（不编造） |

> **📐 报告骨架（固定模板）**：报告的 H1 标题、查询时间行、导语标签、**全部章节标题、块标签（`**📌 谷歌精选**` / `**📌 联合早报**`）、表格表头**均已固定，作为硬约束写入 `prompt/daily_report_prompt.txt` 文末「## ▸ 报告骨架（固定模板 · 逐字复制）」一节（完整/精简两套骨架）——LLM 只负责**填数据与写文字**，格式一律不变。`scripts/md_to_reader.py` 内置**骨架校验**（`_verify_skeleton`，只告警不阻断）：核对必需标题是否齐全、是否出现骨架外的二级标题、是否命中历史漂移写法（如 `### 【谷歌精选】`、H1 写成「全球金融日报」、查询时间行写成「查询时间：北京时间 …」），**格式漂移当天即可从 Actions 日志发现**。
> **统一 RSSHub 实例池（全项目共用）**：所有 RSS 源（Top20 双源、财联社、格隆汇、联合早报）均按以下 6 实例顺序兜底、**命中即止**，并打印逐源状态日志（✅采纳/❌失败原因）：
> `hub.slarker.me → rsshub.rssforever.com → rsshub.umzzz.com → rsshub.isrss.com → rsshub.ktachibana.party → rsshub-balancer.virworks.moe`
> ⚠️ **深度观察专栏是例外**：各实例对同一条目返回的 `desc` 深浅不一（部分实例只给导语、部分给全文），沿用「命中即止」会锁死在导语版实例上、导致专栏只输出文章开头 → **深度源改用独立实例顺序（`rsshub.umzzz.com` 首选）+ `desc` 中位 ≥700 字门槛**：不达标继续试下一实例，全不达标则取最长者并打印降级告警。
> 例外：**格隆汇**以 `rss.injahow.cn`（.cn 专属实例，实测仅支持格隆汇路由）为**首选**，失败后再走上述统一池；财联社路由在 rss.injahow.cn 与 rsshub.umzzz.com 上不可用（503/超时，实测），由池内其余实例覆盖。单实例超时已收紧为 (8s连接, 15s读取)。
> **方案 C（curl_cffi HTTP/2 补丁）**：东方财富 `push2.eastmoney.com` / `push2delay.eastmoney.com` / `push2his.eastmoney.com` 需 HTTP/2，标准 `requests` 仅 HTTP/1.1 会静默断连。脚本在顶部注入 `curl_cffi` 浏览器模拟，仅对这些域名生效，保障指数主源稳定；其余请求不受影响。运行依赖已包含 `curl_cffi` 与 `pandas_market_calendars`。
> **原油／贵金属取数口径**：4 个品种（WTI原油 / 布伦特原油 / COMEX黄金 / COMEX白银）统一走**新浪外盘期货 `hf_`**（`hq.sinajs.cn/list=hf_CL,hf_OIL,hf_GC,hf_SI`，一次批量取），取到的是**连续/近月价**。
> - **字段**：`[0]`现价、`[7]`昨结、`[8]`今开、`[12]`日期、`[13]`名称；涨跌幅 = `([0]−[7])/[7]×100`（`[7]`=昨结经「东财涨跌幅三重反推」验证：WTI 92.16 / 黄金 4318.58 / 白银 64.966 全部吻合）。
> - **兜底**：新浪缺失时，以 akshare `futures_global_spot_em()` 的 `00Y`（当月连续）合约补齐 —— **布伦特除外**：该源未提供布伦特当月连续合约，可退化的合约均为远月（与真实近月相差约 20 美元、随换月持续漂移），取数不可信 → 布伦特**宁缺勿错**，缺失时报告按既定规则显示「数据暂不可得」。
> - **防静默失败**：「布伦特原油」已列入**缺失字段检查列表** —— 该字段取数失败会导致报告少一行，不做检查不易察觉。

## QDII 与 ETF 监测板块格式规范
日报「QDII 溢价与申购额度监测」子板块呈现三张表（场内 ETF 溢价 + 场外 QDII 申购额度 + 热门全球 QDII 关注），格式约定如下：

### 场内 ETF 溢价率表（5 列）

| ETF | 代码 | 溢价率 | 对比昨日溢价 | 评估 |
|-----|------|-------|------------|------|

- 始终列 6 只核心 ETF（纳指/标普 500 各 3 只），代码写死于 `prefetch_data.py`。
- `对比昨日溢价`：今日溢价率 − 昨日溢价率，由代码计算（`qdii_prev.json` 跨运行快照留存昨日基准），首日留空。
- `评估` 列用短标签：**✓**（±1% 内）/ **△溢价**（>3%）/ **▽折价**（>2%），严禁长句。

### 场外 QDII 申购额度表（简称列）

| 简称 | 代码 | 最新净值 | 申购状态 | 日累计限额 | 对比昨日限额 |
|------|------|---------|---------|-----------|------------|

- **选基规则**：纳指100系与标普500系（关键词「纳指/纳斯达克100」合并一组、「标普500」一组；基金类型放行 `海外|QDII`，覆盖 QDII-FOF 如天弘标普500发起）**两组各取限额较大的 5 只，共 10 只**。
- 「简称」列由 `prefetch_data.py::_shorten_qdii_name()` 自动生成（字段 `名称_短`），**基金公司名完整保留**。
- **统一短名格式**：`公司名 + 纳指100/标普500 + 小写份额字母`，例：`建信纳指100c`、`大成纳指100a`、`易方达标普500a`。
- 纯规则驱动（清理 `(QDII)`/币种/`ETF联接`/`发起` 等），零硬编码映射；份额字母锚定**末尾或"X类"**提取（避开 QDII/ETF 内部字母误判），**小写置末尾**，支持 A–E（覆盖 A/C/D/E 等）。
- `对比昨日限额`：今日限额 − 昨日限额（单位元），由 `qdii_prev.json` 跨运行计算，首日/新进前 10 留空。
- **排序：不限购（申购状态=开放申购）置顶，其余按日累计限额从大到小**；「日累计限额」列不限购显示「不限购」，其余显示数字。
- **表格下方保留一行评估**（额度/申购状态维度，单行短句含数字，如「场外QDII额度整体收紧：3只下调（最大↓8000元），无不限购」；禁投资建议用语；无数据则写「今日无场外QDII额度数据」）。场外按净值申购无溢价数据，**不适用溢价评估**。

### 热门全球 QDII 关注表（固定清单，默认 C 类）

| 简称 | 代码 | 最新净值 | 申购状态 | 日累计限额 | 对比昨日限额 |
|------|------|---------|---------|-----------|------------|

- 固定 11 只清单写死于 `prefetch_data.py::HOT_GLOBAL_QDII`（含内置简称：华夏移动互联、华宝致远、浦银安盛全球、华安德国DAX、汇添富全球移动互联、银华海外数字经济、建信新兴市场、建信富时100、广发全球精选、华安法国CAC40、国富全球科技互联）；
- 数据来自 `data_extra.json` → "QDII_监测" → "场外QDII主动"，**不限购置顶、其余按日累计限额降序**；申购状态如实展示（含暂停申购），无数据标「无数据」，严禁编造。
- **表格下方保留一行评估**（申购状态分布+额度维度，单行短句含数字，如「热门QDII申购偏紧：1只暂停申购（浦银安盛全球）、5只限大额，额度最高1万元（广发全球精选）」；禁投资建议用语；无数据则写「今日无热门QDII数据」）。

## 全球 Top20 组合规则（谷歌 + 联合早报，各固定 10 条）
日报「全球 Top20」由两个独立数据源构成，**两块独立互不补位，谷歌块与联合早报块各固定输出 10 条**：

### 第 1 块：谷歌精选（10 条）

- 数据源：`data_news.json` 的 `items_google`（Google News 美国一地一次抓 20 条）。
- `items_google` 的 20 条**全量交 LLM（数据侧不去重）**；LLM **去重并精选 10 条**不同角度的重要新闻（英译中），每条标题/链接必须互不重复（同一事件的多篇报道只选一篇）。
- **只能从 `items_google` 中选择，严禁使用任何其他来源**（财联社/格隆汇/联合早报/其他 JSON）填充或替换。
- **剔除任何一条后必须立即从 `items_google` 剩余候选补位，始终凑满 10 条**；仅当候选本身不足 10 条时才按实际条数输出，禁止硬凑。

### 第 2 块：联合早报（10 条）

- 数据源：`data_news.json` 的 `items_zaobao`（联合早报·中港台即时 RSS 最新 10 条，统一六实例兜底）。
- 中文直用，无需翻译；固定为 Top20 次块（中港台视角）。
- **必须逐条全量输出全部 10 条**，不得以「与前文重复」「信息增量不足」等理由删减（两块为独立信源，跨块不互去重）。

### 边界规则

- **某块完全无条目时**，该块标签与内容一并省略（不输出占位说明）；只要该块有条目，块标签必须原样输出。
- **财联社/格隆汇不进入 Top20**，仅用于「市场全景简述」与「持仓聚焦」（见 `data_cls_zaobao.json`）。
- 完整模式与精简模式规则一致（prompt 两处同步约束）。

## 新闻原文链接
每条新闻末尾的来源媒体名已嵌入原文链接，支持点击跳转：

- **Markdown 报告**（`daily-report.md`）：`（[Reuters](原文链接)）` — 在 GitHub 或 Markdown 查看器中点击媒体名跳转
- **HTML 朗读版**（`daily-report.html`）：`<a href="原文链接">Reuters</a>` — 在浏览器中点击媒体名跳转（新标签页）
- 链接为 Google News 重定向链接，自动跳转至原始文章
- 精简模式与完整模式均支持此功能

## 今日定性导语（HTML 朗读版）
Markdown 顶部的 `**今日定性导语**：<正文>`（单行格式，位于 H1 标题块内）会在 `md_to_reader.py` 中被单独抽取，渲染为文章顶部带左侧强调色边框的高亮卡片 `<p class="lede">`，并保留粗体标签。该段落在主流程中随 `title` 块被跳过，故由 `_extract_lede()` 置顶注入，避免 HTML 朗读版丢失导语（与 Markdown 报告保持一致）。
**今日定性导语为报告固定开头板块（完整模式 / 精简模式均必出）**：完整模式先用一句话梳理当日市场涨跌全景，再列 3–5 条新闻主线；精简模式（纯新闻日）以当日新闻要点为主线列 3–5 条新闻主线，融合市场与新闻做通篇归纳。

## 汇率转换

- 自动抓取 USD/CNH 汇率（**离岸即期市场价 CNH**：新浪 fx_susdcnh 买卖报价中值，24h 实时；与报告「大宗商品与汇率」表同口径。外汇局中间价仅作末位兜底且明确标注），首次刷新后缓存当日汇率
- A 股/港股/美股/基金四类资产的盈亏统一以人民币计价

## GitHub Secrets

| Secret | 用途 |
|--------|------|
| `AGNES_API_KEY` | Agnes API Key（免费）；日报+广播稿主选 Agnes agnes-2.5-flash（`apihub.agnes-ai.com/v1`） |
| `GEMINI_API_KEY` | Google AI Studio API Key（免费层）；**日报+广播稿第 ②层 Gemini 3.8 Flash 与第 ④层 Gemini 3.5 Flash-Lite 共用本 key**（`generativelanguage.googleapis.com/v1beta/openai`），在 AI Studio → API Keys 生成。⚠️ 两层同 key = 同一配额池 |
| `SENSENOVA_API_KEY` | 商汤日日新 API Key；日报+广播稿次选 DeepSeek-V4-Flash（`token.sensenova.cn/v1`），已在 douban-tracker / xueqiu-tracker 实测 |
| ~~`NVIDIA_API_KEY`~~ | **已弃用**：本模型链不含 NVIDIA 模型，不再使用该 Secret（可自行删除） |

> **⚠️ 新增 Secret 后必须回 workflow 注入（否则静默失效）**：仅在 Settings → Secrets and variables → Actions 添加 Secret 是**不够的**——Secret 必须在 `.github/workflows/daily-scheduled.yml` 中需要该 Key 的 step（「调用 LLM 生成日报」「转换日报为广播稿」）的 `env:` 段显式注入才会成为容器内环境变量：
>
> ```yaml
> env:
>   AGNES_API_KEY:     ${{ secrets.AGNES_API_KEY }}
>   GEMINI_API_KEY:    ${{ secrets.GEMINI_API_KEY }}
>   SENSENOVA_API_KEY: ${{ secrets.SENSENOVA_API_KEY }}
> ```
>
> 漏注入时脚本 `os.environ.get()` 读不到该变量，只会打印「⏭️ 跳过 <模型>: 环境变量 XXX 未设置」并**静默落到下一层兜底**（不报错、不中断）。曾踩此坑：Secret 已设置但 workflow 未注入，链路实际少一层；多层同时失败时会导致当日无日报产出。**排查口诀：日志里出现「跳过 … 未设置」= workflow env 漏注入，而不是 Secret 没配。**

## 广播稿转换（md_to_script）模型链
`scripts/md_to_script.py` 将 `report.md` 转为口语化广播稿 `script.txt`，复用 `call_llm.py` 的 `LLM_CONFIGS` 与 `_call_llm`（单一数据源）。`SYSTEM` 提示词按 **【通用要求】/【完整模式适用】/【精简模式适用】** 三块分域，**完整模式的行情指令（市场全景、美股涨跌数据、QDII）只作用于完整模式，从源头隔离泄漏**：

- **完整模式**（含「一、市场全景 / 二、行业洞察」章节）：走 LLM 链路（约 6 分钟，1200–1600 字），以**「全球 Top20 每日要闻池」为主轴**（谷歌精选块 + 联合早报块全部条目逐条串联，琐碎/重叠条目可合并，整体覆盖绝大多数）；「一、市场全景」每个板块一句话（美股保留具体涨跌、A股/港股定性）；**估值水位与情绪、持仓动态与聚焦、QDII 监测（含场内 ETF 溢价、场外 QDII 额度、热门全球 QDII 关注等表）均仅结尾一句带过**。
- **精简模式**（纯新闻日，仅「全球 Top20 + 深度观察专栏」）：仍走 LLM 链路（约 4–5 分钟，800–1100 字），**仅以 Top20 + 深度观察为素材改写为口语播音稿**；与完整模式行情指令隔离（不套用、不联想市场全景/行情）；**禁止播报来源媒体名 / URL / 话题标签 / 序号**，**严禁编造任何行情数据**；可基于原文但须为适合收听的播音稿。

| 优先级 | 模型 | 密钥 | 说明 |
|--------|------|------|------|
| ① 主用 | Agnes agnes-2.5-flash | `AGNES_API_KEY` | 默认主模型 |
| ② 次选 | Google Gemini 3.8 Flash | `GEMINI_API_KEY` | 主模型异常或近空（<500字符）即切换 |
| ③ 备选 | 商汤 SenseNova DeepSeek-V4-Flash | `SENSENOVA_API_KEY` | 本层异常或近空（<500字符）即切换 |
| ④ 兜底 | Google Gemini 3.5 Flash-Lite | `GEMINI_API_KEY` | 前序模型连续报错 2 次（`_call_llm` 内部重试）仍未产出有效内容即切换 |
| 末路 | 复制原文 | — | 三模型全失败，直接复制 `report.md` 为 `script.txt`，避免 workflow 中断 |

**MP3 完整性防护**（`md_to_mp3.py`）：Edge TTS 合成后用 `ffprobe` 校验时长（预期 ≈ 广播稿字数 ÷ 4.5 秒；阈值 = max(60s, 预期×0.6)），**疑似截断（时长过短）则删除并自动重试 1 次，仍截断则不部署**，杜绝"部分音频上线"。广播稿 `script.txt` 随报告入库为 `docs/daily-script.txt`，便于核对每日实际播报文本。

> 日报与广播稿模型链相互独立、结构一致：均为 **Agnes 2.5 主 → Gemini 3.8 Flash 次 → 商汤 SenseNova DeepSeek-V4-Flash 备 → Gemini 3.5 Flash-Lite 兜**（见 `scripts/call_llm.py` 的 `LLM_CONFIGS` 与 `scripts/md_to_script.py` 的 `_SCRIPT_ORDER`）。

## 文件结构

```
.
├── .github/workflows/daily-scheduled.yml   # 由 Cloudflare qdii-dispatch 触发（北京 06:30 · 无 schedule）
├── prompt/
│   └── daily_report_prompt.txt             # LLM 系统提示词（含完整/精简模式指令 + 市场门控硬规则）
├── scripts/
│   ├── prefetch_data.py                     # 数据抓取（市场全景+估值+QDII/ETF+新闻；新闻：Google News 美国单地20条(失败指数退避重试3次)→全量交LLM去重精选10条+块内补位 + 联合早报最新10(统一六实例兜底,命中即止+逐源状态日志；源校验放宽为昨天或今天内容) 双源 Top20，两块独立互不补位；data_deep.json 深度观察(仅精简模式抓取):**单源**=/rfi/cn(法广中文);**深度源专用**实例顺序(umzzz 首选)+desc 中位≥700字门槛(防锁死导语版实例,全不达标取最长者并告警),取最新10条,desc为去标签后完整正文并附source/desc_len;**代码侧先硬筛**标题含涉中美词/非文章条目(播音表)/超长文(>6000字),再由LLM语义精筛并选1篇中国美国之外的第三方深度文原文直出(零改写,须排除标题干净但主题涉中美者,长文不设上限,合规候选均不够深度则降级选其中话题性最强一篇,全部涉中美则今日暂停)；data_cls_zaobao.json 取财联社+格隆汇 RSS 合并(财联社 telegraph 与格隆汇均走统一六实例兜底(格隆汇以 rss.injahow.cn 为 cn 专属首选)；合并标题归一化去重+北京当天筛选,格隆汇缺pubDate保留)当天新闻供市场全景各板块一段简述（50–100字）+持仓聚焦(按持仓行业关键词预匹配industry_match)；data_holdings.json 取腾讯API持仓核心标的行情(价格+涨跌幅,6只)供「持仓动态与聚焦」板块；已停抓 data_fund/data_industry
│   ├── market_date_resolver.py             # 按市场解析业务日期 + 北京时间收盘标注（MarketDateResolver）
│   ├── trading_calendar.py                  # 三市场交易日历判定（A股/美股/港股）
│   ├── call_llm.py                          # LLM 调用（含模式判定 + 模型切换 + 永久性错误快切 + 市场标志注入 + 输入体积护栏 + Top20 同链接去重：防 LLM 幻觉复制重复新闻，删除后重新连续编号）
│   ├── md_to_reader.py                      # Markdown → HTML（朗读版；表格与文本按 MD 原始顺序交错渲染，修复 QDII 等表格错位；纯加粗行 **xxx** 识别为 h4 小标题）
│   ├── md_to_script.py                      # Markdown → 广播稿（注入 __TODAY_DATE__ 防日期错）
│   └── md_to_mp3.py                         # 广播稿 → MP3（Edge TTS，含 ffprobe 时长校验 + 截断自动重试）
├── web/
│   └── sw.js                                # Service Worker（离线缓存）
├── docs/                                    # 部署目录（自动生成）
│   ├── daily-report.html                    # HTML 朗读版
│   ├── daily-report.md                      # Markdown 完整报告
│   ├── daily-report.mp3                     # 音频文件
│   ├── daily-script.txt                     # 广播稿文本（script.txt 入库）
│   ├── archive/                             # 历史日报归档（YYYY-MM-DD.md，保留 30 天，workflow 自动清理）
│   └── sw.js                                # 前端 Service Worker
└── README.md

```

## 发布地址

- GitHub Pages：`https://homjanon.github.io/portfolio/`