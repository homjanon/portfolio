#!/usr/bin/env python3
"""将 Markdown 日报转为新闻播客风格 MP3 音频

   方法：解析 MD 的结构化内容，按板块组织为新闻播报脚本，
   像新闻主播一样逐段朗读，最后用 edge-tts 合成为音频。
"""
import sys, re, os, subprocess, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DEFAULT_VOICE = "zh-CN-YunyangNeural"
DEFAULT_RATE = "+0%"


def parse_md_sections(md_text):
    """解析 MD 为结构化板块列表
    
    按 ## 和 ### 划分板块，同一子板块下的所有内容（表格/段落/列表）合并为一条。
    返回: [(type, title, body_lines)]
    """
    lines = md_text.split('\n')
    blocks = []  # [(type, title, [lines])]
    current_type = None
    current_title = ''
    current_lines = []

    def flush_block():
        nonlocal current_lines
        if current_type and current_lines:
            # 跳过空内容块
            text = '\n'.join(current_lines).strip()
            if text:
                blocks.append((current_type, current_title, current_lines[:]))
            current_lines = []

    for line in lines:
        stripped = line.strip()

        # # 一级标题 — 跳过
        if stripped.startswith('# ') and not stripped.startswith('## '):
            continue

        # ## 二级标题 → 新板块
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

        # ### 三级标题 → 新子板块
        if stripped.startswith('### '):
            flush_block()
            title = stripped[4:].strip()
            current_type = 'subsection'
            current_title = title
            continue

        # 跳过元数据
        if current_type == 'meta':
            continue

        # 分割线
        if stripped in ('---', '***', '___'):
            continue

        # 空行
        if not stripped:
            continue

        current_lines.append(stripped)

    flush_block()
    return blocks


def clean_text(text):
    """清洗单段文本"""
    text = text.replace('**', '').replace('*', '')
    text = text.replace('`', '')
    # 箭头 → 文字
    text = re.sub(r'↑([\d.]+%?)', r'上涨\1', text)
    text = re.sub(r'↓([\d.]+%?)', r'下跌\1', text)
    text = text.replace('↑', '上涨').replace('↓', '下跌')
    # 解码 HTML 实体
    text = text.replace('&gt;', '>').replace('&lt;', '<').replace('&amp;', '&')
    # 估值符号：>80% → 超过80%，<30% → 不足30%
    text = re.sub(r'>(\d+\.?\d*%)', r'超过\1', text)
    text = re.sub(r'<(\d+\.?\d*%)', r'不足\1', text)
    text = re.sub(r'≥', '不低于', text)
    text = re.sub(r'≤', '不高于', text)
    # 清理竖线和装饰线
    text = text.replace('|', '')
    text = re.sub(r'[─\-]{2,}', '', text)
    # 清理多余空格
    text = re.sub(r' +', ' ', text)
    return text.strip('，。、；： \t')


def table_to_narration(rows):
    """将表格行（已解析为单元格列表）转为叙述性文字"""
    if len(rows) < 2:
        return ''
    headers = [h.replace('**', '') for h in rows[0]]
    all_text = ' '.join(headers)

    parts = []

    for row in rows[1:]:
        name = row[0].replace('**', '') if len(row) > 0 else ''
        if not name:
            continue

        # 指数表格：上证指数，收盘点位...涨跌幅...
        # 输出更自然：上证指数报收4043.64，上涨0.37%
        values = []
        for i in range(1, min(len(row), len(headers))):
            cell = row[i].replace('**', '').strip()
            if not cell or cell in ('—', '-', '--', '...', '—', '－', '――'):
                continue
            h = headers[i]
            # 跳过已知的冗余列名
            if h in ('名称', '净值日期', '—'):
                continue
            # 涨跌幅 → 去掉"涨跌幅"前缀（"涨跌幅上涨0.37%" → "上涨0.37%"）
            if h in ('涨跌幅', '涨跌'):
                values.append(cell)
            else:
                values.append(f"{h}{cell}")

        if values:
            parts.append(f"{name}，{'，'.join(values)}")

    text = '。'.join(parts) + '。'
    return clean_text(text)


def block_to_text(lines):
    """将板块内的所有行合并为一段叙述文本"""
    # 分离表格行和非表格行
    table_rows = []
    text_lines = []
    
    for line in lines:
        if line.startswith('|'):
            table_rows.append(line)
        elif line.startswith('- '):
            text_lines.append(line[2:].strip())
        elif re.match(r'^\d+\.\s', line):
            text_lines.append(re.sub(r'^\d+\.\s', '', line))
        elif line.startswith('**查询时间'):
            # 跳过查询时间元数据
            continue
        else:
            text_lines.append(line)

    # 处理表格
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

    # 处理其他文本（过滤页脚元数据）
    other_lines = []
    for line in text_lines:
        # 跳过页脚链接/元数据
        if any(kw in line for kw in ['朗读链接', 'MD 已同步', '数据来源', '发布时间']):
            continue
        if re.match(r'^https?://', line):
            continue
        # 去掉 emoji
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


def build_podcast_script(blocks, date_str):
    """将结构化板块组装为新闻播客 SSML"""

    ssml = ['<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="zh-CN">']

    # ── 开场白 ──
    ssml.append(f'<break time="300ms"/>')
    ssml.append(f'大家早上好。')
    ssml.append(f'<break time="400ms"/>')
    ssml.append(f'今天是{date_str}。')
    ssml.append(f'<break time="300ms"/>')
    ssml.append(f'欢迎收听今日全球金融市场日报。')
    ssml.append(f'<break time="500ms"/>')

    # ── 逐板块播报 ──
    section_count = 0
    # 收集 section 标题，为后续子板块提供上下文
    current_section_title = ''

    for typ, title, lines in blocks:
        # 处理正文
        body = block_to_text(lines)
        if not body:
            continue

        # XML 转义
        body_xml = body.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        body_xml = body_xml.replace('"', '&quot;')

        if typ == 'section':
            section_count += 1
            current_section_title = title
            # 播报板块标题（有子板块时，子板块会先读标题，这里不重复读）
            title_clean = clean_text(title)
            if not any(b[0] == 'subsection' for b in blocks if b[1]):
                # 没有子板块，直接读内容
                title_xml = title_clean.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                ssml.append(f'<break time="500ms"/>')
                ssml.append(f'<prosody rate="slow">{title_xml}。</prosody>')
                ssml.append(f'<break time="300ms"/>')
                ssml.append(f'{body_xml}')
                ssml.append(f'<break time="300ms"/>')

        elif typ == 'subsection':
            # 子板块：先读标题，再读内容
            ssml.append(f'<break time="400ms"/>')
            title_clean = clean_text(title)
            title_xml = title_clean.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            ssml.append(f'<prosody rate="slow">{title_xml}。</prosody>')
            ssml.append(f'<break time="300ms"/>')
            ssml.append(f'{body_xml}')
            ssml.append(f'<break time="300ms"/>')

    # ── 结束语 ──
    ssml.append(f'<break time="500ms"/>')
    ssml.append(f'以上就是今日全球金融市场日报的全部内容，感谢收听，祝您投资顺利。')
    ssml.append(f'<break time="300ms"/>')
    ssml.append('</speak>')

    return '\n'.join(ssml)


def get_date_from_md(md_text):
    """从 MD 中提取日期字符串"""
    m = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日.*?星期([一二三四五六日])', md_text)
    if m:
        return f'{m.group(1)}年{m.group(2)}月{m.group(3)}日，星期{m.group(4)}'
    m2 = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', md_text)
    if m2:
        return f'{m2.group(1)}年{m2.group(2)}月{m2.group(3)}日'
    return '2026年7月4日'


def md_to_news(md_file):
    """读取 MD 文件，返回新闻播客 SSML"""
    with open(md_file, 'r', encoding='utf-8') as f:
        md_text = f.read()

    date_str = get_date_from_md(md_text)
    blocks = parse_md_sections(md_text)

    ssml = build_podcast_script(blocks, date_str)
    return ssml


def generate_mp3(md_file, output_file, voice=DEFAULT_VOICE, rate=DEFAULT_RATE):
    """生成 MP3 音频"""
    print(f"📖 生成新闻播客脚本: {md_file}")
    ssml = md_to_news(md_file)

    # 保存 SSML 到临时文件
    with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False, encoding='utf-8') as f:
        f.write(ssml)
        ssml_file = f.name

    try:
        print(f"🔊 合成音频 (voice={voice}, rate={rate})...")
        cmd = [
            'edge-tts', '--voice', voice, '--rate', rate,
            '--file', ssml_file, '--write-media', output_file,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            print(f"❌ edge-tts 错误: {result.stderr}", file=sys.stderr)
            return False

        size_mb = os.path.getsize(output_file) / (1024 * 1024)
        print(f"✅ MP3: {output_file} ({size_mb:.1f} MB)")
        return True
    except subprocess.TimeoutExpired:
        print(f"❌ 超时 (600s)", file=sys.stderr)
        return False
    except Exception as e:
        print(f"❌ 错误: {e}", file=sys.stderr)
        return False
    finally:
        if os.path.exists(ssml_file):
            os.unlink(ssml_file)


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
