#!/usr/bin/env python3
"""将 Markdown 日报转为新闻播报风格 MP3 音频

   策略：先通过 md_to_reader 的 HTML pipeline 得到纯净叙述文本，
   保留标题/正文的结构信息，再组装为新闻播报稿，最后用 edge-tts 合成。
"""
import sys, re, os, subprocess, tempfile

# ── 导入 md_to_reader 的转换函数 ──
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from md_to_reader import md_to_html

DEFAULT_VOICE = "zh-CN-YunyangNeural"
DEFAULT_RATE = "+0%"


def html_to_news_items(html):
    """从叙述性 HTML 中提取 (type, text) 列表（heading/text）"""
    # 去掉 script/style
    html = re.sub(r'<script[^>]*>[\s\S]*?</script>', '', html, flags=re.I)
    html = re.sub(r'<style[^>]*>[\s\S]*?</style>', '', html, flags=re.I)

    # 用标记替换块元素，保留结构信息
    html = re.sub(r'<h2[^>]*>', '\n[HEADING]', html, flags=re.I)
    html = re.sub(r'<h3[^>]*>', '\n[SUBHEADING]', html, flags=re.I)
    html = re.sub(r'</h[23]>', '\n', html, flags=re.I)
    html = re.sub(r'<div class="table-text"[^>]*>', '\n[TEXT]', html, flags=re.I)
    html = re.sub(r'</div>', '\n', html, flags=re.I)
    html = re.sub(r'<p[^>]*>', '\n[TEXT]', html, flags=re.I)
    html = re.sub(r'</p>', '\n', html, flags=re.I)

    # 去掉其他 HTML 标签
    html = re.sub(r'<[^>]+>', '', html)

    # 解析为 items
    items = []
    for line in html.split('\n'):
        line = line.strip()
        if not line:
            continue

        # 识别类型标记
        if line.startswith('[HEADING]'):
            text = line[9:].strip()
            if text:
                items.append(('heading', text))
        elif line.startswith('[SUBHEADING]'):
            text = line[12:].strip()
            if text:
                items.append(('subheading', text))
        elif line.startswith('[TEXT]'):
            text = line[6:].strip()
            if text:
                items.append(('text', text))
        else:
            # 无标记行（可能是残留文本）
            items.append(('text', line))

    # 合并相邻的 text 段落
    merged = []
    for typ, text in items:
        if typ == 'text' and merged and merged[-1][0] == 'text':
            merged[-1] = ('text', merged[-1][1] + ' ' + text)
        else:
            merged.append((typ, text))

    return merged


def build_news_script(items):
    """将结构化 items 组装成新闻播报 SSML"""
    ssml_parts = []
    ssml_parts.append('<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="zh-CN">')

    for i, (typ, text) in enumerate(items):
        # 通用清洗
        text = text.replace('*', '').replace('`', '')
        # 去掉 emoji 和 URL
        text = re.sub(r'[\U0001F300-\U0001FAFF\U0001F600-\U0001F64F\U0001F680-\U0001F6FF'
                      r'\U0001F1E0-\U0001F1FF\u2600-\u26FF\u2700-\u27BF\uFE00-\uFE0F]', '', text)
        text = re.sub(r'https?://\S+', '', text)
        # 箭头 → 文字
        text = re.sub(r'↑([\d.]+%?)', r'上涨\1', text)
        text = re.sub(r'↓([\d.]+%?)', r'下跌\1', text)
        text = text.replace('↑', '上涨').replace('↓', '下跌')
        # 先解码 HTML 实体，再做替换
        text = text.replace('&gt;', '>').replace('&lt;', '<').replace('&amp;', '&')
        text = text.replace('&quot;', '"').replace('&#39;', "'")
        # 估值表述：>80% → 高于80%，<30% → 低于30%
        text = re.sub(r'>(\d+\.?\d*%)', r'高于\1', text)
        text = re.sub(r'<(\d+\.?\d*%)', r'低于\1', text)
        text = re.sub(r'≥', '不低于', text)
        text = re.sub(r'≤', '不高于', text)
        # 清理残留竖线和分隔线
        text = text.replace('|', '')
        text = re.sub(r'──+', '', text)
        # 清理多余空格
        text = re.sub(r' +', ' ', text)
        # 去掉首尾标点
        text = text.strip('，。、；： ')
        # 跳过元数据行（页脚链接等）
        if any(kw in text for kw in ['朗读链接', 'MD 已同步', '数据来源']):
            continue
        # 转义 XML
        text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        text = text.replace('"', '&quot;')

        if typ == 'heading':
            # 主标题：减慢语速 + 较长停顿
            if i == 0:
                ssml_parts.append(f'<prosody rate="medium">{text}</prosody><break time="1s"/>')
            else:
                ssml_parts.append(f'<break time="600ms"/><prosody rate="slow">{text}</prosody><break time="400ms"/>')
        elif typ == 'subheading':
            # 子标题：稍慢 + 中等停顿
            ssml_parts.append(f'<break time="400ms"/><prosody rate="slow">{text}</prosody><break time="300ms"/>')
        else:
            # 正文
            ssml_parts.append(f'<break time="200ms"/>{text}<break time="300ms"/>')

    ssml_parts.append('</speak>')
    return '\n'.join(ssml_parts)


def md_to_news(md_file):
    """读取 MD 文件，返回新闻播报稿 SSML"""
    with open(md_file, 'r', encoding='utf-8') as f:
        md_text = f.read()

    # 先用 md_to_reader 的 pipeline 转为叙述性 HTML
    html_content = md_to_html(md_text)

    # 从 HTML 提取结构化段落
    items = html_to_news_items(html_content)

    # 组装为新闻稿 SSML
    ssml = build_news_script(items)
    return ssml


def generate_mp3(md_file, output_file, voice=DEFAULT_VOICE, rate=DEFAULT_RATE):
    """生成 MP3 音频"""
    print(f"📖 生成新闻稿: {md_file}")
    ssml = md_to_news(md_file)
    total_chars = len(ssml)

    # 保存 SSML 到临时文件
    with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False, encoding='utf-8') as f:
        f.write(ssml)
        ssml_file = f.name

    try:
        print(f"🔊 合成音频 (voice={voice}, rate={rate})...")
        cmd = [
            'edge-tts',
            '--voice', voice,
            '--rate', rate,
            '--file', ssml_file,
            '--write-media', output_file,
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
        if os.path.exists(ssml_file):
            os.unlink(ssml_file)


def main():
    if len(sys.argv) < 2:
        print("用法: python3 md_to_mp3.py <input.md> [output.mp3] [voice]")
        print("语音选项: zh-CN-YunyangNeural (男声新闻·当前默认)")
        print("         zh-CN-XiaoxiaoNeural (女声新闻)")
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
