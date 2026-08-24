#!/usr/bin/env python3
"""
调用 LLM 生成日报：
  主模型: Agnes agnes-2.0-flash (AGNES_API_KEY)
  次选: NVIDIA MiniMax-M3 (NVIDIA_API_KEY)
  兜底: NVIDIA Nemotron-3 Ultra 550B (NVIDIA_API_KEY)

用法: python3 scripts/call_llm.py
  读取 prompt/daily_report_prompt.txt (system) + data_*.json (user)
  输出: report.md
"""

import os, sys, json, glob, time, requests, re
from datetime import datetime, timezone, timedelta

PROMPT_PATH = os.path.join(os.path.dirname(__file__), "..", "prompt", "daily_report_prompt.txt")
BEIJING = timezone(timedelta(hours=8))
_WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"]
LLM_CONFIGS = [
    {
        "name": "Agnes agnes-2.0-flash",
        "api_url": "https://apihub.agnes-ai.com/v1/chat/completions",
        "api_key_env": "AGNES_API_KEY",
        "model": "agnes-2.0-flash",
    },
    {
        "name": "NVIDIA MiniMax-M3",
        "api_url": "https://integrate.api.nvidia.com/v1/chat/completions",
        "api_key_env": "NVIDIA_API_KEY",
        "model": "minimaxai/minimax-m3",
    },
    {
        "name": "NVIDIA Nemotron-3 Ultra 550B",
        "api_url": "https://integrate.api.nvidia.com/v1/chat/completions",
        "api_key_env": "NVIDIA_API_KEY",
        "model": "nvidia/nemotron-3-ultra-550b-a55b",
    },
]


def _dedup_top20_links(text):
    """Top20 块内同链接去重：同一原文链接（news.google.com 重定向）重复出现时仅保留第一条，
    并重新连续编号（删除后不产生断号）。防御 LLM 幻觉复制（把同一条候选输出两遍）。
    """
    # 仅处理含「全球 Top20」的板块
    if 'Top20' not in text:
        return text
    # 逐条新闻行形如：N. **标题**：内容。（[媒体](链接)） 或 N. **标题**：内容（[媒体](链接)）
    line_re = re.compile(
        r'^(\d+)\.\s+\*\*([^*]+)\*\*[：:](.*?)（\[[^\]]+\]\(([^)]+)\)）\s*$',
        re.MULTILINE
    )
    seen_links = set()
    seq = [0]
    removed = [0]
    def _repl(m):
        link = m.group(4)
        if link in seen_links:
            removed[0] += 1
            return ''  # 删除整行
        seen_links.add(link)
        seq[0] += 1
        # 仅替换行首序号（保留 **标题**/正文/媒体名/链接原样）
        return re.sub(r'^\d+\.\s+', f'{seq[0]}. ', m.group(0), count=1)
    out = line_re.sub(_repl, text)
    # 清理删除后留下的空行
    out = re.sub(r'\n{3,}', '\n\n', out)
    if removed[0]:
        print(f"  🧹 Top20 同链接去重：移除 {removed[0]} 条重复新闻（已重新编号）")
    return out


def _call_llm(api_url, api_key, model, system, user, timeout=90, extra_headers=None):
    """通用 OpenAI 兼容 LLM 调用器，含快速退避重试。

    单模型最多尝试 MAX_ATTEMPTS=2 次（失败2次即切下一个模型）；
    重试间隔短（2s/4s），请求超时 90s，避免单次挂起拖慢整体生成。
    """
    headers = {"Authorization": f"Bearer {api_key}"}
    if extra_headers:
        headers.update(extra_headers)
    payload = {
        "model": model,
        "temperature": 0.3,
            "max_tokens": 12000,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    last_exc = None
    MAX_ATTEMPTS = 2  # 失败2次即切下一模型
    for attempt in range(MAX_ATTEMPTS):
        try:
            resp = requests.post(
                api_url,
                headers=headers,
                json=payload,
                timeout=timeout,
            )
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"]
            elif resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 2 * (attempt + 1)))
                print(f"    429 限流，等待 {wait}s...")
                time.sleep(wait)
            else:
                # 非 200：打印状态码与响应体前 600 字符，便于定位（如 401 密钥无效 / 404 模型不可用 / 模型已下线）
                _body = resp.text[:600] if isinstance(resp.text, str) else ""
                print(f"    ⚠️ HTTP {resp.status_code} 响应: {_body}")
                resp.raise_for_status()
        except requests.exceptions.Timeout:
            last_exc = "Timeout"
            print(f"    ⏱ 超时 (attempt {attempt+1}/{MAX_ATTEMPTS}, 请求超时 {timeout}s)")
        except Exception as e:
            last_exc = str(e)
            print(f"    ⚠️ 失败: {e} (attempt {attempt+1}/{MAX_ATTEMPTS})")
        # 仅非末次尝试后退避，避免最终失败后多余等待
        if attempt < MAX_ATTEMPTS - 1:
            _backoff = 2 * (attempt + 1)  # 2s, 4s
            print(f"    ↳ {_backoff}s 后重试")
            time.sleep(_backoff)
    raise RuntimeError(f"LLM 调用失败（{MAX_ATTEMPTS}次后切换下一模型）: {last_exc}")


def main():
    # 1. 读取 system prompt
    if not os.path.exists(PROMPT_PATH):
        print(f"❌ 未找到 prompt 文件: {PROMPT_PATH}")
        sys.exit(1)
    system = open(PROMPT_PATH, encoding="utf-8").read()
    print(f"📄 读取 prompt: {len(system)} 字符")

    # 1a. 注入当前报告日期（今天，不是昨天）到 prompt
    _now = datetime.now(BEIJING)
    _report_date_str = f"{_now.year}年{_now.month}月{_now.day}日 星期{_WEEKDAYS[_now.weekday()]}"
    system = system.replace("__REPORT_DATE__", _report_date_str)

    # 1b. 模式自动判定（三市场交易日历）
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from trading_calendar import market_flags
    flags = market_flags()
    mode = flags["mode"]
    system = system.replace("__MODE__", mode)
    # 注入三市场开市标志，供 prompt 感知哪些市场有数据
    system = system.replace("__A_OPEN__",  "是" if flags["a_open"]  else "否")
    system = system.replace("__U_OPEN__",  "是" if flags["u_open"]  else "否")
    system = system.replace("__HK_OPEN__", "是" if flags["hk_open"] else "否")

    # 1c. 收盘日期标注（MarketDateResolver：按市场解析业务日期 + 北京时间收盘标注）
    _labels = {
        "A_CLOSE": "前一日", "HK_CLOSE": "前一日",
        "US_CLOSE": "当日凌晨", "GLOBAL_CLOSE": "前一日",
    }
    try:
        from market_date_resolver import MarketDateResolver
        _resolver = MarketDateResolver()
        _labels.update({
            "A_CLOSE": _resolver.get_close_label("cn"),
            "HK_CLOSE": _resolver.get_close_label("hk"),
            "US_CLOSE": _resolver.get_close_label("us"),
            "GLOBAL_CLOSE": _resolver.get_close_label("jp"),  # 日经/韩国/欧洲同为前一日
        })
    except Exception as e:
        print(f"  ⚠️ 收盘标注解析失败({e})，使用兜底标注")
    system = system.replace("__A_CLOSE__", _labels["A_CLOSE"])
    system = system.replace("__HK_CLOSE__", _labels["HK_CLOSE"])
    system = system.replace("__US_CLOSE__", _labels["US_CLOSE"])
    system = system.replace("__GLOBAL_CLOSE__", _labels["GLOBAL_CLOSE"])
    print(f"🏷️ 收盘标注: A={_labels['A_CLOSE']} HK={_labels['HK_CLOSE']} US={_labels['US_CLOSE']} 全球={_labels['GLOBAL_CLOSE']} | 报告日期={_report_date_str}")

    y = flags["yesterday"]
    print(f"📋 执行模式: {mode}（参考日 {y} 星期{'一二三四五六日'[y.weekday()]}，"
          f"A股:{'✅' if flags['a_open'] else '❌'} 美股:{'✅' if flags['u_open'] else '❌'} 港股:{'✅' if flags['hk_open'] else '❌'}）")

    # 2. 读取所有 data_*.json 作为 user 消息
    blocks = []
    json_files = sorted(glob.glob("data_*.json"))
    if not json_files:
        print("⚠️ 未找到 data_*.json 文件，user 消息将为空")
    for fp in json_files:
        try:
            with open(fp, encoding="utf-8") as f:
                content = f.read()
            blocks.append(
                f"## 预抓取数据: {os.path.basename(fp)}\n```json\n{content}\n```"
            )
            print(f"  📊 加载 {os.path.basename(fp)} ({len(content)} 字符)")
        except Exception as e:
            blocks.append(f"## {fp} 读取失败: {e}")
            print(f"  ⚠️  {fp} 读取失败: {e}")

    user = "\n\n".join(blocks)
    # input-size guardrail: if over threshold, drop least-critical blocks by priority (graceful degrade)
    _MAX_USER = 120000
    if len(user) > _MAX_USER:
        import re as _re
        def _pri(b):
            for k, v in (("data_market", 100), ("data_valuation", 95), ("data_news", 85),
                          ("data_holdings", 70), ("data_extra", 60), ("data_deep", 50)):
                if k in b:
                    return v
            return 80
        def _bn(b):
            m = _re.search(r"## 预抓取数据: (\S+)", b)
            return m.group(1) if m else "?"
        _sorted = sorted(blocks, key=_pri)
        _kept, _cur, _drop = [], 0, []
        for b in _sorted:
            if _cur + len(b) <= _MAX_USER or not _kept:
                _kept.append(b); _cur += len(b)
            else:
                _drop.append(_bn(b))
        if _drop:
            print(f"  [warn] input > {_MAX_USER} chars, dropped low-priority blocks: {', '.join(_drop)}")
        blocks = sorted(_kept, key=lambda x: user.find(x))
        user = "\n\n".join(blocks)
    print(f"📦 user 消息: {len(user)} 字符，来自 {len(json_files)} 个 JSON 文件")

    # 3. 主 LLM → 兜底 LLM（含"近空输出"校验：过短视为失败，自动切下一模型）
    MIN_CHARS = 500  # 报告有效最低字符数；低于此判定为失败，避免空白被静默提交
    content = None
    for llm in LLM_CONFIGS:
        api_key = os.environ.get(llm["api_key_env"])
        if not api_key:
            print(f"⏭️  跳过 {llm['name']}: 环境变量 {llm['api_key_env']} 未设置")
            continue
        print(f"🤖 调用 {llm['name']} ({llm['model']})...")
        try:
            raw = _call_llm(
                llm["api_url"], api_key, llm["model"], system, user,
                extra_headers=llm.get("extra_headers"),
            )
        except Exception as e:
            print(f"❌ {llm['name']} 调用异常: {e}")
            content = None
            continue
        if not raw or not raw.strip():
            print(f"❌ {llm['name']} 返回空内容，视为失败")
            content = None
            continue
        # 后处理: 移除 markdown 代码块围栏 和 LLM 前置废话
        c = raw.strip()
        if c.startswith("```markdown"):
            c = c[len("```markdown"):].strip()
        elif c.startswith("```"):
            c = c[3:].strip()
        if c.endswith("```"):
            c = c[:-3].strip()
        # 删除第一个 # 或 ## 标题之前的所有文字（去掉 LLM 的输出前确认语等废话）
        _heading_match = re.search(r'^#{1,6}\s', c, re.MULTILINE)
        if _heading_match and _heading_match.start() > 0:
            c = c[_heading_match.start():]
        # 删除各板块开头的数据时间戳行（> 数据时间：YYYY-MM-DD HH:MM）
        c = re.sub(r'>\s*数据时间[：:]\s*\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\s*\n?', '', c)
        # 删除顶部的查询时间行（**查询时间**：...）
        c = re.sub(r'\*\*查询时间\*\*[：:][^\n]*\n?', '', c)
        # 删除底部「数据来源」/「来源声明」声明行（prompt 已禁止输出，此处兜底，与阅读版 md_to_reader 对齐）
        # 兼容 **数据来源**： 与 数据来源： 两种写法（粗体标记可能夹在关键词与冒号之间）
        c = re.sub(r'(?m)^\s*\*?\*?数据来源\*?\*?\s*[：:].*$\n?', '', c)
        c = re.sub(r'(?m)^\s*\*?\*?来源声明\*?\*?\s*[：:].*$\n?', '', c)
        if len(c) < MIN_CHARS:
            print(f"❌ {llm['name']} 输出过短 ({len(c)} 字符 < {MIN_CHARS})，视为失败，切换下一模型")
            content = None
            continue
        content = c
        # Top20 同链接去重（防 LLM 幻觉复制同一条新闻；对 HTML/广播稿链路无副作用）
        content = _dedup_top20_links(content)
        print(f"✅ {llm['name']} 成功（{len(content)} 字符）")
        break

    if content is None:
        print("❌ 所有 LLM 均失败或输出过短，无法生成报告，终止以免提交空白")
        sys.exit(1)

    # 4. 写入 report.md
    out_path = "report.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)
    lines = content.count("\n") + 1
    print(f"📝 报告已写入 {out_path} ({len(content)} 字符, {lines} 行)")


if __name__ == "__main__":
    main()