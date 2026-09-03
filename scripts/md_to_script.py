#!/usr/bin/env python3
"""
读取 report.md → 调用 LLM 转换为口语化广播稿 → 输出 script.txt
主模型: Agnes agnes-2.0-flash (AGNES_API_KEY)
次选: NVIDIA MiniMax-M3 (NVIDIA_API_KEY)
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

# 广播稿专用顺序：Agnes 主用 → NVIDIA MiniMax-M3 次 → NVIDIA Nemotron-3 Ultra 550B 兜（与日报一致）
_SCRIPT_ORDER = [
    "Agnes agnes-2.0-flash",
    "NVIDIA MiniMax-M3",
    "NVIDIA Nemotron-3 Ultra 550B",
]
_MODEL_CHAIN = [c for name in _SCRIPT_ORDER
               for c in LLM_CONFIGS if c["name"] == name]

BEIJING = timezone(timedelta(hours=8))
_WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"]

# SYSTEM prompt 含 __TODAY_DATE__ 占位符，由 main() 替换
SYSTEM = """你是一个专业的财经广播稿写手。请将下面这份金融日报改写成一段适合早上通勤收听的财经广播稿。

【通用要求】
- 语言口语化、自然，像财经主播在说话
- 去掉 Markdown 表格、代码块格式，改为自然叙述
- 涨跌用"上涨/下跌"替代箭头
- 开头用当日问候语（如"早上好，今天是X月X日星期X"），结尾用"以上就是今天的财经早报，祝您投资顺利"
- 直接输出广播稿正文，不要额外说明

【完整模式适用】（日报含「一、市场全景 / 二、行业洞察」等章节时）
- 以「每日要闻池」为主轴：即日报「二、行业洞察 → 全球 Top20」的**全部条目**（谷歌精选块 + 联合早报块两块合计，均为要闻池成员），**逐条口语串联播报，全部覆盖**；个别琐碎、话题相近或两板块重叠的条目可**合并为一条播报**（如同一 AI 事件两家媒体各报一条 → 合成一条讲透），合并后整体播报内容须覆盖要闻池绝大多数条目。
- 「一、市场全景」仅开头用一句话总结，不展开表格数字：
  - 美股板块须保留具体涨跌数据（如"纳指下跌1.2%、标普小涨0.3%"），因听众尚不清楚凌晨美股表现
  - A股/港股等板块用定性一句话即可（前一日涨跌听众已知，无需重复数字）
- 「估值水位与情绪」「持仓动态与聚焦」同「QDII 溢价与申购额度监测」一样，**各用一句话带过**（定性概括方向/整体表现，不逐个指数、逐只持仓、逐张表播报具体数字），放在结尾收束。
- 整体时长约 6 分钟，1200-1600 字：开场 → 市场全景一句 → **立即进入要闻池连续播报（占全文绝大部分篇幅）** → 结尾估值/持仓/QDII 各一句收束，不在各附表间反复穿插

【精简模式适用】（日报仅为「全球 Top20 + 深度观察专栏」，无市场行情/估值/持仓/QDII 章节）
- 仅以日报实际存在的「全球 Top20」与「深度观察专栏」为素材，改写为口语播音稿；上方完整模式规则对本模式无效，不要套用、也不要联想任何市场全景 / 行情相关指令。
- 最终呈现须为适合早晨通勤收听的口语播音稿（可基于原文内容，但表达要自然流畅，像财经主播在说话）。
- 禁止播报来源与链接：不得念出"据XX报道""来源：XX"、媒体名（联合早报/财联社/格隆汇等），不得读出 URL/网址、话题标签（#XXX）、"第N条"等编号。
- 严禁编造任何行情数据（美股/A股/港股涨跌、指数点位、估值、QDII 溢价等一律不得出现）。
- 整体时长约 4-5 分钟，800-1100 字

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