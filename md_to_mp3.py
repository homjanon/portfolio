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
    """将表格行转为叙述性文字"""
    if len(rows) < 2:
        return ''
    headers = [h.replace('**', '') for h in rows[0]]

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
            if h in ('涨跌幅', '涨跌'):
                values.append(cell)
            else:
                values.append(f"{h}{cell}")

        if values:
            parts.append(f"{name}，{'，'.join(values)}")

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
        # 过滤元数据行
        if any(kw in line for kw in ['朗读链接', 'MD 已同步', '发布时间']):
            continue
        # 收集来源信息（合并简化）
        if '数据来源' in line or line.startswith('来源：') or line.startswith('来源:'):
            source_lines.append(line)
            continue
        if re.match(r'^https?://', line):
            continue
        line = re.sub(r'[\U0001F300-\U0001FAFF\U0001F600-\U0001F64F\U0001F680-\U0001F6FF'
                      r'\U0001F1E0-\U0001F1FF\u2600-\u26FF\u2700-\u27BF\uFE00-\uFE0F]', '', line)
        line = line.strip()
        if line:
            other_lines.append(line)

    other = ' '.join(other_lines)
    other = clean_text(other)

    if result and other:
        return result + ' ' + other
    return result or other


def build_podcast_text(blocks, date_str):
    """将结构化板块组装为新闻播客纯文本（不含任何 XML 标签）"""
    lines = []
    all_source_lines = []  # 收集全篇来源信息

    # 开场白
    lines.append(f'早上好，今天是{date_str}，以下是最新的金融简报。')
    lines.append('')

    # 逐板块播报
    for typ, title, block_lines in blocks:
        if typ == 'section':
            # 收集来源信息
            for bl in block_lines:
                if '数据来源' in bl or bl.startswith('来源：') or bl.startswith('来源:'):
                    all_source_lines.append(bl)
            title_clean = clean_text(title)
            lines.append('')
            lines.append(f'—— {title_clean} ——')
            body = block_to_text(block_lines)
            if body:
                lines.append('')
                lines.append(body)

        elif typ == 'subsection':
            # 收集来源信息
            for bl in block_lines:
                if '数据来源' in bl or bl.startswith('来源：') or bl.startswith('来源:'):
                    all_source_lines.append(bl)
            title_clean = clean_text(title)
            lines.append('')
            lines.append(f'—— {title_clean} ——')
            body = block_to_text(block_lines)
            if body:
                lines.append('')
                lines.append(body)

    # 统一添加来源声明（去重、简化）
    if all_source_lines:
        sources = _merge_sources(all_source_lines)
        if sources:
            lines.append('')
            lines.append(f'以上内容来源：{sources}。')

    # 结束语
    lines.append('')
    lines.append('以上就是今日全球金融市场日报的全部内容，感谢收听，祝您投资顺利。')

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
