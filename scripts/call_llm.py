#!/usr/bin/env python3
"""
调用 LLM 生成日报：
  主模型: NVIDIA GLM-5.2 (NVIDIA_API_KEY)
  兜底: 商汤 DeepSeek-V4-Flash (SENSENOVA_API_KEY)
  最后兜底: NVIDIA Nemotron-3-Ultra-550B (NVIDIA_API_KEY)

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
        "name": "NVIDIA GLM-5.2",
        "api_url": "https://integrate.api.nvidia.com/v1/chat/completions",
        "api_key_env": "NVIDIA_API_KEY",
        "model": "z-ai/glm-5.2",
    },
    {
        "name": "SenseTime DeepSeek-V4-Flash",
        "api_url": "https://token.sensenova.cn/v1/chat/completions",
        "api_key_env": "SENSENOVA_API_KEY",
        "model": "deepseek-v4-flash",
    },
    {
        "name": "NVIDIA Nemotron-3-Ultra-550B",
        "api_url": "https://integrate.api.nvidia.com/v1/chat/completions",
        "api_key_env": "NVIDIA_API_KEY",
        "model": "nvidia/nemotron-3-ultra-550b-a55b",
    },
]


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
    print(f"📦 user 消息: {len(user)} 字符，来自 {len(json_files)} 个 JSON 文件")

    # 3. 主 LLM → 兜底 LLM
    content = None
    for llm in LLM_CONFIGS:
        api_key = os.environ.get(llm["api_key_env"])
        if not api_key:
            print(f"⏭️  跳过 {llm['name']}: 环境变量 {llm['api_key_env']} 未设置")
            continue
        print(f"🤖 调用 {llm['name']} ({llm['model']})...")
        try:
            content = _call_llm(
                llm["api_url"], api_key, llm["model"], system, user,
                extra_headers=llm.get("extra_headers"),
            )
            print(f"✅ {llm['name']} 成功")
            break
        except Exception as e:
            print(f"❌ {llm['name']} 失败: {e}")
            content = None
            continue

    if content is None:
        print("❌ 所有 LLM 均失败，无法生成报告")
        sys.exit(1)

    # 4. 后处理: 移除 markdown 代码块围栏 和 LLM 前置废话
    content = content.strip()
    if content.startswith("```markdown"):
        content = content[len("```markdown"):].strip()
    elif content.startswith("```"):
        content = content[3:].strip()
    if content.endswith("```"):
        content = content[:-3].strip()
    # 删除第一个 # 或 ## 标题之前的所有文字（去掉 LLM 的输出前确认语等废话）
    _heading_match = re.search(r'^#{1,6}\s', content, re.MULTILINE)
    if _heading_match and _heading_match.start() > 0:
        content = content[_heading_match.start():]

    # 删除各板块开头的数据时间戳行（> 数据时间：YYYY-MM-DD HH:MM）
    content = re.sub(r'>\s*数据时间[：:]\s*\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\s*\n?', '', content)

    # 删除顶部的查询时间行（**查询时间**：...）
    content = re.sub(r'\*\*查询时间\*\*[：:][^\n]*\n?', '', content)

    # 5. 写入 report.md
    out_path = "report.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)
    lines = content.count("\n") + 1
    print(f"📝 报告已写入 {out_path} ({len(content)} 字符, {lines} 行)")


if __name__ == "__main__":
    main()