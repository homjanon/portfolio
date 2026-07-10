#!/usr/bin/env python3
"""
调用 LLM 生成日报：
  主模型: 智谱 GLM-4.7-Flash (ZHIPU_API_KEY)
  兜底: 商汤日日新 DeepSeek-V4-Flash (SENSENOVA_API_KEY)

用法: python3 scripts/call_llm.py
  读取 prompt/daily_report_prompt.txt (system) + data_*.json (user)
  输出: report.md
"""

import os, sys, json, glob, time, requests

PROMPT_PATH = os.path.join(os.path.dirname(__file__), "..", "prompt", "daily_report_prompt.txt")
LLM_CONFIGS = [
    {
        "name": "Zhipu GLM-4.7-Flash",
        "api_url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "api_key_env": "ZHIPU_API_KEY",
        "model": "glm-4.7-flash",
    },
    {
        "name": "SenseTime DeepSeek-V4-Flash",
        "api_url": "https://token.sensenova.cn/v1/chat/completions",
        "api_key_env": "SENSENOVA_API_KEY",
        "model": "deepseek-v4-flash",
    },
]


def _call_llm(api_url, api_key, model, system, user, timeout=180, extra_headers=None):
    """通用 OpenAI 兼容 LLM 调用器，含指数退避重试。"""
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
    for attempt in range(3):
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
                wait = int(resp.headers.get("Retry-After", 5 * (attempt + 1)))
                print(f"    429 限流，等待 {wait}s...")
                time.sleep(wait)
            else:
                resp.raise_for_status()
        except requests.exceptions.Timeout:
            last_exc = "Timeout"
            print(f"    超时 (attempt {attempt+1}/3)")
            if attempt < 2:
                time.sleep(5 * (attempt + 1))
        except Exception as e:
            last_exc = str(e)
            print(f"    失败: {e} (attempt {attempt+1}/3)")
            if attempt < 2:
                time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"LLM 调用失败（3次重试后）: {last_exc}")


def main():
    # 1. 读取 system prompt
    if not os.path.exists(PROMPT_PATH):
        print(f"❌ 未找到 prompt 文件: {PROMPT_PATH}")
        sys.exit(1)
    system = open(PROMPT_PATH, encoding="utf-8").read()
    print(f"📄 读取 prompt: {len(system)} 字符")

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

    # 4. 后处理: 移除 markdown 代码块围栏
    content = content.strip()
    if content.startswith("```markdown"):
        content = content[len("```markdown"):].strip()
    elif content.startswith("```"):
        content = content[3:].strip()
    if content.endswith("```"):
        content = content[:-3].strip()

    # 5. 写入 report.md
    out_path = "report.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)
    lines = content.count("\n") + 1
    print(f"📝 报告已写入 {out_path} ({len(content)} 字符, {lines} 行)")


if __name__ == "__main__":
    main()
