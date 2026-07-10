#!/usr/bin/env python3
"""
读取 report.md → 调用 LLM 转换为口语化广播稿 → 输出 script.txt
主模型: 商汤日日新 DeepSeek-V4-Flash (SENSENOVA_API_KEY)
兜底: LLM 失败时直接复制 report.md 作为 script.txt
"""
import os, sys, requests

REPORT_PATH = sys.argv[1] if len(sys.argv) > 1 else "report.md"
OUTPUT_PATH = sys.argv[2] if len(sys.argv) > 2 else "script.txt"
API_URL = "https://token.sensenova.cn/v1/chat/completions"
API_KEY = os.environ.get("SENSENOVA_API_KEY")
MODEL = "deepseek-v4-flash"

SYSTEM = """你是一个专业的财经广播稿写手。请将下面这份金融日报改写成一段适合早上通勤收听的财经广播稿。

要求：
- 语言口语化、自然，像财经主播在说话
- 去掉 Markdown 表格、代码块格式，改为自然叙述
- 保留关键数据，用口语表达（如"上证指数收报3996点，下跌1%"）
- 涨跌用"上涨/下跌"替代箭头
- 整体时长约 3 分钟，600-800 字
- 开头用当日问候语（如"早上好，今天是X月X日星期X"）
- 结尾用"以上就是今天的财经早报，祝您投资顺利"
- 直接输出广播稿正文，不要额外说明"""


def main():
    if not API_KEY:
        print("⚠️ SENSENOVA_API_KEY 未设置，直接复制原文")
        return _fallback()

    if not os.path.exists(REPORT_PATH):
        print(f"❌ 未找到 {REPORT_PATH}")
        sys.exit(1)

    report = open(REPORT_PATH, encoding="utf-8").read()
    print(f"📄 读取日报: {len(report)} 字符")

    try:
        resp = requests.post(
            API_URL,
            headers={"Authorization": f"Bearer {API_KEY}"},
            json={
                "model": MODEL,
                "temperature": 0.3,
                "max_tokens": 2048,
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": f"请转换以下日报为广播稿：\n\n{report}"},
                ],
            },
            timeout=300,
        )
        if resp.status_code != 200:
            print(f"❌ LLM 失败({resp.status_code})，原文兜底")
            return _fallback()

        script = resp.json()["choices"][0]["message"]["content"].strip()
        # 去掉可能的代码围栏
        if script.startswith("```"):
            script = script.split("\n", 1)[-1] if "\n" in script else script[3:]
        if script.endswith("```"):
            script = script.rsplit("```", 1)[0].strip()

        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            f.write(script)
        print(f"✅ 广播稿已生成: {len(script)} 字符 → {OUTPUT_PATH}")

    except Exception as e:
        print(f"❌ 转换失败: {e}，原文兜底")
        _fallback()


def _fallback():
    """兜底：直接复制 report.md 作为 script.txt"""
    if os.path.exists(REPORT_PATH):
        import shutil
        shutil.copy2(REPORT_PATH, OUTPUT_PATH)
        print(f"⚠️ 兜底: 复制 {REPORT_PATH} → {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
