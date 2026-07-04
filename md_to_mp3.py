#!/usr/bin/env python3
"""将 Markdown 日报转为 MP3 音频文件（使用 Edge-TTS 微软神经网络语音）"""
import sys, re, os, subprocess, json, tempfile

# ── 语音配置 ──
# zh-CN-YunyangNeural: 男声新闻专业稳重
# zh-CN-XiaoxiaoNeural: 女声新闻温暖亲切
# 可在此切换
DEFAULT_VOICE = "zh-CN-YunyangNeural"
DEFAULT_RATE = "+0%"      # 语速，+0% 正常，+10% 稍快，-10% 稍慢
DEFAULT_VOLUME = "+0%"    # 音量


def _clean_text(text):
    """清洗 MD 文本为纯叙述文字，适合 TTS 朗读"""
    # 去掉代码块
    text = re.sub(r'```[\s\S]*?```', '', text)
    # 去掉行内代码
    text = re.sub(r'`[^`]+`', '', text)
    # 去掉 markdown 链接 [text](url) → text
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    # 去掉图片 ![alt](url)
    text = re.sub(r'!\[([^\]]*)\]\([^)]+\)', r'\1', text)
    # 去掉 HTML 标签
    text = re.sub(r'<[^>]+>', '', text)
    # 去掉加粗/斜体标记
    text = text.replace('**', '').replace('*', '')
    # 替换箭头符号
    text = text.replace('↑', '上涨').replace('↓', '下跌')
    # 替换特殊符号
    text = text.replace('—', '——').replace('–', '至')
    # 统一空格
    text = re.sub(r' +', ' ', text)
    return text.strip()


def _extract_sections(md_text):
    """提取 MD 文本中的主要段落，返回纯文本块列表"""
    lines = md_text.split('\n')
    paragraphs = []
    current = []

    in_table = False
    table_rows = []
    in_list = False
    list_items = []

    def flush_table():
        nonlocal table_rows
        if not table_rows:
            return
        # 将表格转为一段叙述文字
        rows = []
        for line in table_rows:
            cells = [c.strip().replace('**', '') for c in line.strip('|').split('|')]
            if all(re.match(r'^[-:\s]+$', c) for c in cells):
                continue
            rows.append(cells)
        table_rows = []
        if rows and len(rows) > 1:
            headers = rows[0]
            text_parts = []
            for row in rows[1:]:
                parts = []
                for i, cell in enumerate(row):
                    if i < len(headers) and cell and cell not in ('—', '-', '--', '...'):
                        parts.append(f"{headers[i]}{cell}")
                if parts:
                    text_parts.append('，'.join(parts))
            if text_parts:
                text = '。'.join(text_parts) + '。'
                paragraphs.append(('text', text))

    def flush_list():
        nonlocal list_items
        if list_items:
            text = '，'.join(list_items) + '。'
            paragraphs.append(('text', text))
            list_items = []

    for line in lines:
        stripped = line.strip()

        if not stripped:
            flush_table()
            flush_list()
            if current:
                text = ' '.join(current)
                paragraphs.append(('text', text))
                current = []
            continue

        # 标题
        if stripped.startswith('#'):
            flush_table()
            flush_list()
            if current:
                text = ' '.join(current)
                paragraphs.append(('text', text))
                current = []
            level = len(stripped) - len(stripped.lstrip('#'))
            title = stripped.strip('#').strip()
            paragraphs.append(('heading', title))
            continue

        # 表格
        if stripped.startswith('|'):
            flush_list()
            if current:
                text = ' '.join(current)
                paragraphs.append(('text', text))
                current = []
            table_rows.append(stripped)
            in_table = True
            continue
        else:
            flush_table()

        # 列表项
        if stripped.startswith('- ') or stripped.startswith('* '):
            flush_table()
            content = stripped[2:].strip()
            list_items.append(content)
            in_list = True
            continue
        elif re.match(r'^\d+\.\s', stripped):
            flush_table()
            content = re.sub(r'^\d+\.\s', '', stripped)
            list_items.append(content)
            in_list = True
            continue
        else:
            flush_list()

        # 分割线
        if stripped in ('---', '***', '___'):
            continue

        # 普通段落
        current.append(stripped)

    # 收尾
    flush_table()
    flush_list()
    if current:
        text = ' '.join(current)
        paragraphs.append(('text', text))

    return paragraphs


def md_to_paragraphs(md_file):
    """读取 MD 文件并返回清洗后的段落列表"""
    with open(md_file, 'r', encoding='utf-8') as f:
        md_text = f.read()

    sections = _extract_sections(md_text)
    result = []
    for typ, text in sections:
        cleaned = _clean_text(text)
        if cleaned and len(cleaned) >= 5:
            result.append((typ, cleaned))
    return result


def paragraphs_to_ssml(paragraphs):
    """将段落列表转为 SSML 格式"""
    ssml_parts = ['<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="zh-CN">']

    for typ, text in paragraphs:
        # 转义 XML 特殊字符
        text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')
        if typ == 'heading':
            # 标题添加停顿
            ssml_parts.append(f'<break time="500ms"/><prosody rate="slow">{text}</prosody><break time="300ms"/>')
        elif typ == 'text':
            # 普通段落
            ssml_parts.append(f'<break time="200ms"/>{text}<break time="300ms"/>')

    ssml_parts.append('</speak>')
    return '\n'.join(ssml_parts)


def generate_mp3(paragraphs, output_file, voice=DEFAULT_VOICE, rate=DEFAULT_RATE):
    """使用 edge-tts 生成 MP3"""
    ssml = paragraphs_to_ssml(paragraphs)

    # 保存 SSML 到临时文件
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False, encoding='utf-8') as f:
        f.write(ssml)
        ssml_file = f.name

    try:
        cmd = [
            'edge-tts',
            '--voice', voice,
            '--rate', rate,
            '--file', ssml_file,
            '--write-media', output_file,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            print(f"edge-tts error: {result.stderr}", file=sys.stderr)
            return False
        return True
    finally:
        if os.path.exists(ssml_file):
            os.unlink(ssml_file)


def main():
    if len(sys.argv) < 2:
        print("用法: python3 md_to_mp3.py <input.md> [output.mp3] [voice]")
        sys.exit(1)

    md_file = sys.argv[1]
    mp3_file = sys.argv[2] if len(sys.argv) > 2 else md_file.rsplit('.', 1)[0] + '.mp3'
    voice = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_VOICE

    if not os.path.exists(md_file):
        print(f"❌ 文件不存在: {md_file}", file=sys.stderr)
        sys.exit(1)

    print(f"📖 读取: {md_file}")
    paragraphs = md_to_paragraphs(md_file)
    total_chars = sum(len(t) for _, t in paragraphs)
    print(f"📝 提取 {len(paragraphs)} 段叙述文本，共 {total_chars} 字符")

    print(f"🔊 生成音频 (voice={voice})...")
    success = generate_mp3(paragraphs, mp3_file, voice)

    if success and os.path.exists(mp3_file):
        size_mb = os.path.getsize(mp3_file) / (1024 * 1024)
        duration_guess = total_chars / 4 / 60  # 约每分钟 240 字
        print(f"✅ 生成 MP3: {mp3_file} ({size_mb:.1f} MB, 约 {duration_guess:.0f} 分钟)")
    else:
        print(f"❌ 生成失败", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
