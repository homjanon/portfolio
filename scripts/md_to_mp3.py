#!/usr/bin/env python3
"""将 Markdown 日报转为新闻播客风格 MP3 音频

   方法：解析 MD 的结构化内容，生成纯文本新闻播报脚本，
   用 edge-tts 合成音频（纯文本输入，无 SSML 标签）。
"""
import sys, re, os, subprocess, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DEFAULT_VOICE = "zh-CN-YunyangNeural"
DEFAULT_RATE = "+0%"


def parse_md_sections(md_text):
    """解析 MD 为结构化板块列表
    
    返回: [(type, title, body_lines)]
    """
    lines = md_text.split('\n')
    blocks = []
    current_type = None
    current_title = ''
    current_lines = []

    def flush_block():
        nonlocal current_lines
        if current_type == 'section':
            # section 即使没有正文也输出（作为板块分隔符）
            blocks.append((current_type, current_title, current_lines[:]))
        elif current_type and current_lines:
            text = '\n'.join(current_lines).strip()
            if text:
                blocks.append((current_type, current_title, current_lines[:]))
        current_lines = []

    for line in lines:
        stripped = line.strip()

        if stripped.startswith('# ') and not stripped.startswith('## '):
            continue

        if stripped.startswith('## '):
            flush_block()
            title = stripped[3:].strip()
            if '部署' in title:
                current_type = 'meta'
                current_title = title
                continue
            current_type = 'section'
            current_title = title
            continue

        if stripped.startswith('### '):
            flush_block()
            title = stripped[4:].strip()
            current_type = 'subsection'
            current_title = title
            continue

        if current_type == 'meta':
            continue
        if stripped in ('---', '***', '___'):
            continue
        if not stripped:
            continue

        current_lines.append(stripped)

    flush_block()
    return blocks


_NUM_CN = ['零','一','二','三','四','五','六','七','八','九','十']


def _num_cn(n):
    """数字转中文：1→一, 2→二 ... 10→十"""
    n = int(n)
    return _NUM_CN[n] if 0 <= n <= 10 else str(n)


def _clean_date(text):
    # 7/6（周一）→ 7月6日星期一；7/6(周一) → 7月6日星期一
    text = re.sub(r'(\d{1,2})/(\d{1,2})[（(]周([一二三四五六日])[）)]', r'\1月\2日星期\3', text)
    # 独立的 7/6 → 7月6日（仅当前后不是数字时）
    text = re.sub(r'(?<!\d)(\d{1,2})/(\d{1,2})(?!\d)', r'\1月\2日', text)
    # （周一）→ 星期一，(周一) → 星期一
    text = re.sub(r'[（(]周([一二三四五六日])[）)]', r'星期\1', text)
    return text


def _clean_hashtags(text):
    """移除话题标签中的 # 号（保留文字）"""
    # #AI #芯片 → AI 芯片（#后跟中文或英文单词）
    text = re.sub(r'#([^\s#]+)', r'\1', text)
    # 移除孤立的 #
    text = text.replace('#', '')
    return text


def _merge_sources(source_lines):
    """从来源行中提取媒体名称（去重、去时间），返回简短来源声明"""
    all_names = []
    for s in source_lines:
        # 提取「数据来源：...」或「来源：...」中的内容
        m = re.search(r'[：:]\s*(.+)', s)
        content = m.group(1) if m else s
        # 移除"发布时间"部分
        content = re.sub(r'[|｜]\s*发布时间.*', '', content).strip()
        # 按 | 分割多个来源
        parts = re.split(r'[|｜]', content)
        for part in parts:
            part = part.strip()
            # 去掉时间和日期部分
            name = re.sub(r'\s*\d{4}[-.]\d{1,2}[-.]\d{1,2}.*$', '', part).strip()
            # 去掉末尾标点和多余信息
            name = re.sub(r'[。，、；：*\s]+$', '', name).strip()
            # 只保留媒体名（取前8个汉字）
            name = name[:12]
            if name and name not in all_names and name not in ('数据来源', '来源'):
                all_names.append(name)
    if not all_names:
        return ''
    # 限制数量，保持简洁
    shown = all_names[:6]
    if len(all_names) > 6:
        return '、'.join(shown) + '等'
    return '、'.join(shown)


def clean_text(text):
    """清洗单段文本，输出适合新闻播报的纯文本"""
    # 先去掉数据来源中的网址部分：中文名(域名) → 中文名
    text = re.sub(r'([\u4e00-\u9fff]+)\((?:[a-zA-Z0-9][-a-zA-Z0-9]*\.[a-zA-Z]{2,})\)', r'\1', text)

    # 去掉表情符号（⚠️✅⬆⬇等），避免朗读乱码
    text = re.sub(r'[\U0001F300-\U0001FAFF\U0001F600-\U0001F64F\U0001F680-\U0001F6FF'
                  r'\U0001F1E0-\U0001F1FF\u2600-\u26FF\u2700-\u27BF\uFE00-\uFE0F]', '', text)

    text = text.replace('**', '').replace('*', '')
    text = text.replace('`', '')

    # 箭头转文字
    text = re.sub(r'↑([\d.]+%?)', r'上涨\1', text)
    text = re.sub(r'↓([\d.]+%?)', r'下跌\1', text)
    text = text.replace('↑', '上涨').replace('↓', '下跌')

    # 符号转文字
    text = text.replace('&gt;', '>').replace('&lt;', '<').replace('&amp;', '&')
    text = re.sub(r'>(\d+\.?\d*%)', r'超过\1', text)
    text = re.sub(r'<(\d+\.?\d*%)', r'不足\1', text)

    # 日期格式
    text = _clean_date(text)
    # 话题标签
    text = _clean_hashtags(text)

    # 移除所有数据来源声明（包括内联括号和独立行尾的）
    text = re.sub(r'[（(]\s*数据来源[：:][^）)]*[）)]', '', text)
    text = re.sub(r'[（(]\s*来源[：:][^）)]*[）)]', '', text)
    # 清理竖线、长横线、多余空格
    text = text.replace('|', '')
    text = re.sub(r'[─\-]{2,}', '', text)
    # 括号转顿号或逗号（更适合朗读停顿），移除右括号
    text = text.replace('（', '，').replace('）', '')
    text = text.replace('(', '，').replace(')', '')
    text = re.sub(r'，+', '，', text)  # 去重逗号
    text = re.sub(r' +', ' ', text)
    return text.strip('，。、；： \t')


def table_to_narration(rows):
    """将表格行转为叙述性文字（按表类型智能分发）"""
    if len(rows) < 2:
        return ''
    headers = [h.replace('**', '') for h in rows[0]]
    all_headers = ' '.join(headers)
    first_header = headers[0] if headers else ''

    # ── 估值表（PE/PB/分位/评估）──
    if any(kw in all_headers for kw in ['PE', 'PB', '估值', '市盈率', '市净率']):
        return _valuation_summary(rows, headers)

    # ── 指数收盘表（A股/美股/港股）──
    if ('收盘点位' in all_headers
            or ('指数' in first_header and any(kw in all_headers for kw in ['涨跌幅', '涨跌']))):
        return _index_table_narration(rows, headers)

    # ── 场外基金/持仓表（有代码+净值+涨跌幅）──
    if '代码' in all_headers and ('净值' in all_headers or '涨跌幅' in all_headers or '近周' in all_headers):
        return _fund_table_narration(rows, headers)

    # ── VIX恐慌指数表 ──
    if len(headers) >= 3 and any(kw in headers[2] for kw in ['解读', '状态', '区间']):
        return _vix_table_narration(rows, headers)

    # ── 通用兜底 ──
    return _generic_table_narration(rows, headers)


def _safe(val):
    """过滤缺失值"""
    v = val.replace('**', '').strip()
    if not v or v in ('—', '-', '--', '...', '—', '－', '――'):
        return None
    if re.match(r'^[─\-–—\s]+$', v):
        return None
    return v


def _fix_point_decimal(val):
    """将指数收盘点位中的小数点替换为'点'，避免TTS将'1996.10'误读为1996年10月"""
    # 仅处理看起来像指数点位的数字（整数部分+小数部分）
    m = re.match(r'^(\d{3,5})\.(\d{1,2})$', val)
    if m:
        decimal_part = m.group(2).rstrip('0')
        if decimal_part:
            return f'{m.group(1)}点{decimal_part}'
        else:
            return m.group(1)
    return val


def _find_col(headers, keywords, exclude=None):
    """在表头中查找包含所有关键词的列索引"""
    for i, h in enumerate(headers):
        if all(k in h for k in keywords):
            if exclude is None or exclude not in h:
                return i
    return None


def _valuation_summary(rows, headers):
    """估值表 → 一句话汇总播报，与 HTML 版保持一致"""
    assess_col = _find_col(headers, ['评估']) or _find_col(headers, ['备注']) or _find_col(headers, ['说明'])

    high_risk = []
    high_watch = []
    low_value = []
    dividend = []
    normal = []

    for row in rows[1:]:
        if len(row) < 2:
            continue
        name = row[0].replace('**', '').strip()
        name_simple = re.sub(r'[（(][^)）]*[)）]', '', name).strip()

        assess = ''
        if assess_col is not None and assess_col < len(row):
            raw = _safe(row[assess_col])
            assess = clean_text(raw) if raw else ''

        # 提取股息率
        div_match = re.search(r'股息率约?([\d.]+%)', assess)
        if div_match:
            dividend.append(f'{name_simple}股息率约{div_match.group(1)}')
            continue

        # 分类
        if '极高风险' in assess or '极高估' in assess:
            high_risk.append(name_simple)
        elif '估值偏高' in assess:
            high_watch.append(name_simple)
        elif '偏高' in assess:
            high_watch.append(name_simple)
        elif '极低价值' in assess or '低估' in assess:
            low_value.append(name_simple)
        elif '适中' in assess or '中位' in assess or '正常' in assess:
            normal.append(name_simple)
        else:
            normal.append(name_simple)

    segments = []
    if high_risk:
        segments.append(f"{'、'.join(high_risk)}极高风险")
    if high_watch:
        segments.append(f"{'、'.join(high_watch)}估值偏高")
    if low_value:
        segments.append(f"{'、'.join(low_value)}极低价值区")
    if dividend:
        segments.append('，'.join(dividend))
    if normal:
        segments.append(f"{'、'.join(normal)}估值适中")

    return '估值异动预警：' + '，'.join(segments) + '。'

def _index_table_narration(rows, headers):
    """指数收盘表 →「xx报xxxx，上涨/下跌x%」格式"""
    val_col = _find_col(headers, ['收盘']) or _find_col(headers, ['点位']) or _find_col(headers, ['价格']) or 1
    change_col = _find_col(headers, ['涨跌']) or _find_col(headers, ['涨跌幅']) or 2

    parts = []
    for row in rows[1:]:
        if len(row) < 2:
            continue
        name = row[0].replace('**', '').strip()
        val = _safe(row[val_col]) if val_col < len(row) else None
        change = _safe(row[change_col]) if change_col < len(row) else None

        val_text = ''
        if val:
            val_text = _fix_point_decimal(val)
        change_text = clean_text(change) if change else ''
        # 统一平盘表述
        if change_text in ('平收', '平', '持平'):
            change_text = '平盘'

        if val_text and change_text:
            parts.append(f'{name}报{val_text}，{change_text}')
        elif val_text:
            parts.append(f'{name}报{val_text}')
        elif change_text:
            parts.append(f'{name}{change_text}')

    if parts:
        return '。'.join(parts) + '。'
    return ''


def _fund_table_narration(rows, headers):
    """场外基金/持仓表 →「名称涨/跌x%」格式（无代码、无净值）"""
    code_col = _find_col(headers, ['代码'])
    name_col = _find_col(headers, ['名称']) or _find_col(headers, ['基金'])
    change_col = _find_col(headers, ['涨跌']) or _find_col(headers, ['涨跌幅']) or _find_col(headers, ['近周']) or _find_col(headers, ['收益'])

    parts = []
    for row in rows[1:]:
        if len(row) < 2:
            continue
        # 优先用名称列
        if name_col is not None and name_col < len(row):
            name = row[name_col].replace('**', '').strip()
        else:
            name = row[1].replace('**', '').strip() if len(row) > 1 else row[0].replace('**', '').strip()

        change = ''
        if change_col is not None and change_col < len(row):
            raw = _safe(row[change_col])
            if raw:
                # 先移除括号后缀（如「（日）」），避免 clean_text 把括号转逗号后残留
                raw = re.sub(r'[（(][^)）]*[)）]', '', raw).strip()
                change = clean_text(raw)

        if change:
            # 统一涨跌/平表述
            parts.append(f'{name}{change}')
        elif name:
            parts.append(name)

    if parts:
        text = '。'.join(parts) + '。'
        return text
    return ''


def _vix_table_narration(rows, headers):
    """VIX恐慌指数表"""
    val_col = _find_col(headers, ['数值']) or _find_col(headers, ['最新值']) or 1
    desc_col = _find_col(headers, ['解读']) or _find_col(headers, ['状态']) or _find_col(headers, ['区间']) or 2

    parts = []
    for row in rows[1:]:
        name = row[0].replace('**', '').strip() if len(row) > 0 else ''
        val = _safe(row[val_col]) if val_col < len(row) else None
        desc = _safe(row[desc_col]) if desc_col < len(row) else None

        if val and desc:
            parts.append(f'{name}报{clean_text(val)}，{clean_text(desc)}')
        elif val:
            parts.append(f'{name}报{clean_text(val)}')
        elif desc:
            parts.append(f'{name}{clean_text(desc)}')

    if parts:
        return '。'.join(parts) + '。'
    return ''


def _generic_table_narration(rows, headers):
    """通用表格叙事（兜底）"""
    parts = []
    for row in rows[1:]:
        name = row[0].replace('**', '') if len(row) > 0 else ''
        if not name:
            continue

        values = []
        for i in range(1, min(len(row), len(headers))):
            cell = row[i].replace('**', '').strip()
            if not cell or cell in ('—', '-', '--', '...', '—', '－', '――'):
                continue
            h = headers[i]
            if h in ('名称', '净值日期', '—'):
                continue
            if h in ('涨跌幅', '涨跌', '近周收益'):
                values.append(clean_text(cell))
            else:
                values.append(f'{h}{cell}')

        if values:
            parts.append(f'{name}，{"，".join(values)}')

    text = '。'.join(parts) + '。'
    return clean_text(text)


def block_to_text(lines):
    """将板块内的所有行合并为纯文本"""
    table_rows = []
    text_lines = []

    for line in lines:
        if line.startswith('|'):
            table_rows.append(line)
        elif line.startswith('- '):
            text_lines.append(line[2:].strip())
        elif re.match(r'^\d+\.\s', line):
            # 保留数字编号并转为适合朗读的中文序号："1. 内容" → "一、内容"
            line = re.sub(r'^(\d+)\.\s', lambda m: f'{_num_cn(m.group(1))}、', line)
            text_lines.append(line)
        elif line.startswith('**查询时间'):
            continue
        else:
            text_lines.append(line)

    result = ''
    if table_rows:
        rows = []
        for line in table_rows:
            cells = [c.strip() for c in line.strip('|').split('|')]
            if all(re.match(r'^[-:\s]+$', c) for c in cells):
                continue
            rows.append(cells)
        if rows:
            result = table_to_narration(rows)

    other_lines = []
    source_lines = []  # 收集来源信息，后续统一处理
    for line in text_lines:
        # 过滤元数据行和隐私内容
        if any(kw in line for kw in ['朗读链接', 'MD 已同步', 'IMA', '知识库', '发布时间']):
            continue
        # 过滤估值头部数据来源行
        if line.strip().startswith('**数据来源**') or line.strip().startswith('**来源声明**'):
            continue
        # 收集来源信息（仅独立来源行，不误抓段落内联来源）
        stripped = line.strip()
        if re.match(r'^[> *]*数据来源[：:]', stripped) or stripped.startswith('来源：') or stripped.startswith('来源:'):
            source_lines.append(line)
            continue
        if re.match(r'^https?://', line):
            continue
        line = re.sub(r'[\U0001F300-\U0001FAFF\U0001F600-\U0001F64F\U0001F680-\U0001F6FF'
                      r'\U0001F1E0-\U0001F1FF\u2600-\u26FF\u2700-\u27BF\uFE00-\uFE0F]', '', line)
        # 中美利差精简为一句话：只保留首个完整句
        if '中美利差' in line:
            line = line.split('。', maxsplit=1)[0] + '。'
        line = line.strip()
        if line:
            other_lines.append(line)

    other = ' '.join(other_lines)
    other = clean_text(other)

    if result and other:
        return result + ' ' + other
    return result or other


def _simplify_holdings_text(text):
    """将个人持仓的详细描述简化为「名称+涨跌幅」格式

    输入 text 结构：
      [基金表叙述（来自 _fund_table_narration）] + [个股自由文本]
    输出：
      基金名涨/跌X%。基金名平。个股名涨X%，个股名涨Y%。
    """
    # ── 分离基金叙述与个股文本 ──
    # 基金叙述以「。」分隔的「名称涨/跌X%」片段组成，位于文本前部
    # 个股文本以「A股/港股/美股 —」标记开始
    stock_marker = re.search(r'(?:A股|港股|美股)\s*—', text)
    fund_narration = ''
    stock_text = text

    if stock_marker:
        split_pos = stock_marker.start()
        # 往前找最近的句号作为分割点
        prev_period = text.rfind('。', 0, split_pos)
        if prev_period >= 0:
            fund_narration = text[:prev_period].strip()
            stock_text = text[prev_period + 1:].strip()
        else:
            fund_narration = ''
            stock_text = text[split_pos:].strip()

    # ── 个股简化 ──
    name_code = re.compile(r'(?:A股|港股|美股)\s*—\s*([^，,]{1,30}?)[，,]\s*(\d{5,6})')
    stock_results = []
    pos = 0
    while pos < len(stock_text):
        m = name_code.search(stock_text, pos)
        if not m:
            break
        name = m.group(1).strip()
        after_start = m.end()
        after = stock_text[after_start:after_start + 150]
        chg = re.search(r'(上涨|下跌)\s*([\d.]+%)', after)
        if chg:
            direction = '涨' if '上涨' in chg.group(0) else '跌'
            stock_results.append(f'{name}{direction}{chg.group(2)}')
        else:
            stock_results.append(name)
        pos = after_start

    # ── 合并 ──
    parts = []
    if fund_narration:
        parts.append(fund_narration.rstrip('。'))
    parts.extend(stock_results)

    if parts:
        return '。'.join(parts) + '。'
    return text


def build_podcast_text(blocks, date_str):
    """将结构化板块组装为新闻播客纯文本（不含任何 XML 标签）"""
    lines = []

    # 开场白
    lines.append(f'早上好，今天是{date_str}，以下是最新的金融简报。')
    lines.append('')

    # 逐板块播报
    _SKIP_SECTIONS = ['QDII', '个人持仓']

    for typ, title, block_lines in blocks:
        # 跳过指定板块（HTML 同样跳过）
        if any(kw in title for kw in _SKIP_SECTIONS):
            continue
        if typ == 'section':
            title_clean = clean_text(title)
            lines.append('')
            lines.append(f'—— {title_clean} ——')
            body = block_to_text(block_lines)
            # 个人持仓板块：精简为仅名称+涨跌幅
            if body and any(kw in title for kw in ['持仓', '个人持仓']):
                body = _simplify_holdings_text(body)
            # 估值板块：只保留表格式汇总播报，去掉后续重复的文字描述
            if body and any(kw in title for kw in ['估值']) and '持仓' not in title:
                first_period = body.find('。')
                if first_period > 0:
                    body = body[:first_period + 1]
            if body:
                lines.append('')
                lines.append(body)

        elif typ == 'subsection':
            title_clean = clean_text(title)
            lines.append('')
            lines.append(f'—— {title_clean} ——')
            body = block_to_text(block_lines)
            # 个人持仓板块：精简为仅名称+涨跌幅
            if body and any(kw in title for kw in ['持仓', '个人持仓']):
                body = _simplify_holdings_text(body)
            # 估值板块：只保留表格式汇总播报，去掉后续重复的文字描述
            if body and any(kw in title for kw in ['估值']) and '持仓' not in title:
                first_period = body.find('。')
                if first_period > 0:
                    body = body[:first_period + 1]
            if body:
                lines.append('')
                lines.append(body)

    # 结束语
    lines.append('')
    lines.append('以上就是今天的全部内容，感谢收听，祝您投资顺利。')

    return '\n'.join(lines)


def get_date_from_md(md_text):
    """从 MD 中提取日期字符串"""
    # 匹配「2026年7月5日（周日）」或「2026年7月5日，星期日」
    m = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日.*?(?:星期([一二三四五六日])|[（(]周([一二三四五六日])[）)])', md_text)
    if m:
        weekday = m.group(4) or m.group(5)
        return f'{m.group(1)}年{m.group(2)}月{m.group(3)}日，星期{weekday}'
    m2 = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', md_text)
    if m2:
        return f'{m2.group(1)}年{m2.group(2)}月{m2.group(3)}日'
    return '2026年7月4日'


def md_to_news(md_file):
    """读取 MD 文件，返回新闻播客纯文本"""
    with open(md_file, 'r', encoding='utf-8') as f:
        md_text = f.read()

    date_str = get_date_from_md(md_text)
    blocks = parse_md_sections(md_text)
    return build_podcast_text(blocks, date_str)


def generate_mp3(md_file, output_file, voice=DEFAULT_VOICE, rate=DEFAULT_RATE):
    """生成 MP3（纯文本输入，不含任何 SSML 标签）"""
    print(f"📖 生成新闻播客脚本: {md_file}")
    plain_text = md_to_news(md_file)

    # 检查纯文本是否干净
    if '<' in plain_text and '>' in plain_text:
        # 如果有残留标签，自动清理
        plain_text = re.sub(r'<[^>]+>', '', plain_text)

    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
        f.write(plain_text)
        text_file = f.name

    try:
        print(f"🔊 合成音频 (voice={voice}, rate={rate})...")
        cmd = [
            'edge-tts', '--voice', voice, '--rate', rate,
            '--file', text_file, '--write-media', output_file,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            print(f"❌ edge-tts 错误: {result.stderr}", file=sys.stderr)
            return False

        size_mb = os.path.getsize(output_file) / (1024 * 1024)
        print(f"✅ MP3: {output_file} ({size_mb:.1f} MB)")
        return True
    except subprocess.TimeoutExpired:
        print("❌ 超时 (600s)", file=sys.stderr)
        return False
    except Exception as e:
        print(f"❌ 错误: {e}", file=sys.stderr)
        return False
    finally:
        if os.path.exists(text_file):
            os.unlink(text_file)


def main():
    if len(sys.argv) < 2:
        print("用法: python3 md_to_mp3.py <input.md> [output.mp3] [voice]")
        print("语音: zh-CN-YunyangNeural (男声新闻·默认)")
        print("      zh-CN-XiaoxiaoNeural (女声新闻)")
        sys.exit(1)

    md_file = sys.argv[1]
    mp3_file = sys.argv[2] if len(sys.argv) > 2 else md_file.rsplit('.', 1)[0] + '.mp3'
    voice = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_VOICE

    if not os.path.exists(md_file):
        print(f"❌ 文件不存在: {md_file}", file=sys.stderr)
        sys.exit(1)

    success = generate_mp3(md_file, mp3_file, voice)
    if not success:
        sys.exit(1)


if __name__ == '__main__':
    main()
