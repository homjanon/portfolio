#!/usr/bin/env python3
"""
读取 report.md → 调用 LLM 转换为口语化广播稿 → 输出 script.txt
主模型: 商汤日日新 DeepSeek-V4-Flash (SENSENOVA_API_KEY)
兜底: LLM 失败时直接复制 report.md 作为 script.txt

⚠️ 日期注入：SYSTEM prompt 末尾注入 __TODAY_DATE__ 占位符，
main() 中替换为真实当前日期（北京时间）。确保 LLM 使用正确的
当前日期作为开场问候语，而非从 report.md 正文的数据日期推断。
"""
import os, sys, requests
from datetime import datetime, timezone, timedelta

REPORT_PATH = sys.argv[1] if len(sys.argv) > 1 else "report.md"
OUTPUT_PATH = sys.argv[2] if len(sys.argv) > 2 else "script.txt"

# 复用日报生成的模型链与通用调用器（单一数据源，避免重复维护）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from call_llm import LLM_CONFIGS, _call_llm

# 广播稿专用顺序：DeepSeek 主用 → GLM 兜底 → Nemotron 最后兜底
# （与 call_llm.py 日报生成顺序刻意相反：广播稿保持 DeepSeek 主用）
_SCRIPT_ORDER = [
    "SenseTime DeepSeek-V4-Flash",
    "NVIDIA GLM-5.2",
    "NVIDIA Nemotron-3-Ultra-550B",
]
_MODEL_CHAIN = [c for name in _SCRIPT_ORDER
               for c in LLM_CONFIGS if c["name"] == name]

BEIJING = timezone(timedelta(hours=8))
_WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"]

# SYSTEM prompt 含 __TODAY_DATE__ 占位符，由 main() 替换
SYSTEM = """你是一个专业的财经广播稿写手。请将下面这份金融日报改写成一段适合早上通勤收听的财经广播稿。

要求：
- 语言口语化、自然，像财经主播在说话
- 去掉 Markdown 表格、代码块格式，改为自然叙述
- 保留关键数据，用口语表达（如"上证指数收报3996点，下跌1%"）
- 涨跌用"上涨/下跌"替代箭头
- 整体时长约 3 分钟，600-800 字
- 开头用当日问候语（如"早上好，今天是X月X日星期X"）
- 结尾用"以上就是今天的财经早报，祝您投资顺利"
- 直接输出广播稿正文，不要额外说明

### 当前日期（此为报告生成日的真实日期，必须用于开场问候语）
__TODAY_DATE__"""


def _today_str():
    """返回今日日期字符串，如 '7月17日 星期五'"""
    now = datetime.now(BEIJING)
    return f"{now.month}月{now.day}日 星期{_WEEKDAYS[now.weekday()]}"


def _convert(system, report):
    """依次尝试模型链，首个成功即返回广播稿文本；全失败返回 None。

    _call_llm 内部已含 2 次重试（range(2)），故某模型连续报错 2 次即视为
    失败并切下一模型——天然实现「报错两次切换」语义（如 DeepSeek 报错两次切 GLM）。
    """
    user = f"请转换以下日报为广播稿：\n\n{report}"
    for cfg in _MODEL_CHAIN:
        api_key = os.environ.get(cfg["api_key_env"])
        if not api_key:
            print(f"  ⏭️  跳过 {cfg['name']}: 环境变量 {cfg['api_key_env']} 未设置")
            continue
        try:
            print(f"  🔄 尝试 {cfg['name']}...")
            text = _call_llm(cfg["api_url"], api_key, cfg["model"],
                             system, user, timeout=300)
            # 去除可能的代码围栏
            if text.startswith("```"):
                text = text.split("\n", 1)[-1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text.rsplit("```", 1)[0].strip()
            return text.strip()
        except Exception as e:
            print(f"  ❌ {cfg['name']} 失败({e})，切换下一模型")
            continue
    return None


def main():
    if not os.path.exists(REPORT_PATH):
        print(f"❌ 未找到 {REPORT_PATH}")
        sys.exit(1)

    report = open(REPORT_PATH, encoding="utf-8").read()
    print(f"📄 读取日报: {len(report)} 字符")

    # 注入真实当前日期，替换占位符（确保 LLM 不使用数据日期作为问候语）
    system = SYSTEM.replace("__TODAY_DATE__", _today_str())
    print(f"📅 注入当日问候日期: {_today_str()}")

    script = _convert(system, report)
    if script:
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            f.write(script)
        print(f"✅ 广播稿已生成: {len(script)} 字符 → {OUTPUT_PATH}")
    else:
        print("⚠️ 所有模型均失败，原文兜底")
        _fallback()


def _fallback():
    """兜底：直接复制 report.md 作为 script.txt"""
    if os.path.exists(REPORT_PATH):
        import shutil
        shutil.copy2(REPORT_PATH, OUTPUT_PATH)
        print(f"⚠️ 兜底: 复制 {REPORT_PATH} → {OUTPUT_PATH}")


if __name__ == "__main__":
    main()