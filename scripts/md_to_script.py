#!/usr/bin/env python3
"""
读取 report.md → 调用 LLM 转换为口语化广播稿 → 输出 script.txt
主模型: Agnes agnes-2.0-flash (AGNES_API_KEY)
次选: NVIDIA Llama 4 Maverick 17B (NVIDIA_API_KEY)
兜底: NVIDIA Nemotron-3 Ultra 550B (NVIDIA_API_KEY)
LLM 失败时直接复制 report.md 作为 script.txt

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

# 广播稿专用顺序：Agnes 主用 → NVIDIA Llama 4 Maverick 17B 次 → NVIDIA Nemotron-3 Ultra 550B 兜（与日报一致）
_SCRIPT_ORDER = [
    "Agnes agnes-2.0-flash",
    "NVIDIA Llama 4 Maverick 17B",
    "NVIDIA Nemotron-3 Ultra 550B",
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
- **整体以「二、行业洞察」的新闻资讯为主轴**（Top20 全球新闻、持仓聚焦、深度专栏），用口语串联、强调新闻叙事，而非罗列数据
- **「一、市场全景」每个板块仅用一句话总结**，不展开表格数字：
  - **美股板块**的一句话须保留具体涨跌数据（如"纳指下跌1.2%、标普小涨0.3%"），因为听众尚不清楚凌晨美股表现；
  - A股/港股等板块用定性一句话即可（前一日涨跌听众已知，无需重复数字）
- **「QDII 溢价与申购额度监测」**（位于「二、行业洞察」内）仅在结尾用**一句话简单带过**，不展开
- 涨跌用"上涨/下跌"替代箭头
- 整体时长约 6 分钟，1200-1600 字
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
    """依次尝试模型链，首个「有效（≥500字符且非异常）」即返回广播稿文本；全失败返回 None。

    _call_llm 内部已含 2 次重试（range(2)），故某模型连续报错 2 次即视为
    失败并切下一模型。此外对「近空输出」( < 500 字符 ) 也判失败切下一模型，
    与日报 call_llm.py 行为一致，避免广播稿被空壳内容占用。
    """
    user = f"请转换以下日报为广播稿：\n\n{report}"
    _MIN = 500
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
            text = text.strip()
            if len(text) < _MIN:
                print(f"  ❌ {cfg['name']} 输出过短 ({len(text)} 字符 < {_MIN})，切换下一模型")
                continue
            return text
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