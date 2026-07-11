#!/usr/bin/env python3
"""把 Markdown 日报转为 HTML — 保留5个核心表格、智能去粗、简洁设计"""
import sys, re, os, datetime, subprocess

# ============================================================
# CSS + HTML 模板（完全重设计）
# ============================================================
TEMPLATE = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<link rel="icon" href="data:,">
<title>全球金融市场日报</title>
<style>
:root{
  --bg:#fafafa;--card:#fff;--text:#1a1a2e;--sub:#6b7280;--muted:#9ca3af;
  --border:#e5e7eb;--accent:#2563eb;--note-bg:#f4f6fb;
  --table-hdr:#f1f5f9;--table-stripe:#fafbfc;
}
@media(prefers-color-scheme:dark){
  :root{
    --bg:#0f172a;--card:#1e293b;--text:#e2e8f0;--sub:#94a3b8;--muted:#64748b;
    --border:#334155;--accent:#3b82f6;--note-bg:#1e293b;
    --table-hdr:#1e293b;--table-stripe:#1a2332;
  }
}
*{margin:0;padding:0;box-sizing:border-box}
body{
  font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
  background:var(--bg);color:var(--text);font-size:16px;line-height:1.7;
  min-height:100dvh;padding:0 0 150px;-webkit-text-size-adjust:100%
}
.header{
  background:var(--card);border-bottom:1px solid var(--border);
  padding:18px 16px;text-align:center
}
.header h1{font-size:18px;font-weight:600;margin-bottom:2px;letter-spacing:.02em}
.header .date{font-size:12px;color:var(--sub)}

.article{max-width:680px;margin:0 auto;padding:16px 16px}

.article h2{
  font-size:17px;font-weight:600;margin:32px 0 10px;
  padding-bottom:4px;border-bottom:2px solid var(--accent);color:var(--text)
}
.article h3{
  font-size:15px;font-weight:600;margin:22px 0 6px;color:var(--accent)
}
.article h4{font-size:14px;font-weight:600;margin:16px 0 4px;color:var(--text)}

.article p{margin:10px 0}
.article p.lede{
  font-size:15px;line-height:1.8;padding:10px 14px;
  background:var(--note-bg);border-radius:10px;border-left:3px solid var(--accent)
}
.article p.lede strong{color:var(--accent)}

.article blockquote{
  border-left:3px solid var(--border);padding:6px 14px;margin:8px 0;
  color:var(--sub);font-size:14px;line-height:1.7;border-radius:0 8px 8px 0
}

/* ---- 表格 ---- */
.data-table{
  width:100%;border-collapse:collapse;font-size:13px;margin:10px 0 16px;
  border-radius:8px;overflow:hidden;border:1px solid var(--border)
}
.data-table thead th{
  background:var(--table-hdr);padding:7px 9px;text-align:left;
  font-weight:500;color:var(--sub);font-size:12px;border-bottom:2px solid var(--border);
  white-space:nowrap
}
.data-table thead th:first-child{text-align:left}
.data-table tbody td{
  padding:6px 9px;border-bottom:1px solid var(--border);vertical-align:middle
}
.data-table tbody tr:last-child td{border-bottom:none}
.data-table tbody tr:nth-child(even){background:var(--table-stripe)}
.data-table .num{text-align:right;font-variant-numeric:tabular-nums}
.data-table .label{color:var(--sub);font-size:12px}

.table-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:0 -16px;padding:0 16px}

/* ---- 涨跌颜色 ---- */
.up{color:#dc2626!important;font-weight:600}
.down{color:#059669!important;font-weight:600}
@media(prefers-color-scheme:dark){.up{color:#f87171!important}.down{color:#34d399!important}}

/* ---- 卡片 ---- */
.card{
  background:var(--note-bg);border-radius:10px;padding:12px 14px;margin:12px 0;
  border:1px solid var(--border);font-size:14px;line-height:1.7
}
.card .card-title{font-size:13px;font-weight:600;color:var(--accent);margin-bottom:6px}
.card p{margin:4px 0}

/* ---- 新闻列表 ---- */
.news-list{counter-reset:news;list-style:none;padding:0;margin:10px 0}
.news-list li{
  counter-increment:news;padding:8px 0 8px 32px;position:relative;
  border-bottom:1px solid var(--border);font-size:14px;line-height:1.7
}
.news-list li:last-child{border-bottom:none}
.news-list li::before{
  content:counter(news);position:absolute;left:0;top:9px;
  width:20px;height:20px;border-radius:50%;background:var(--accent);
  color:#fff;font-size:11px;font-weight:600;text-align:center;line-height:20px
}
@media(prefers-color-scheme:dark){.news-list li::before{color:var(--bg)}}

.news-list li strong{font-weight:600;color:var(--text)}
.news-list .tag{
  display:inline-block;font-size:11px;padding:1px 6px;border-radius:3px;
  margin-left:4px;font-weight:500
}
.tag-bullish{background:#fef2f2;color:#dc2626}
.tag-bearish{background:#ecfdf5;color:#059669}
@media(prefers-color-scheme:dark){
  .tag-bullish{background:#3b1111;color:#f87171}
  .tag-bearish{background:#0a2e1a;color:#34d399}
}

/* ---- 持仓 ---- */
.holding-item{
  display:flex;align-items:baseline;gap:6px;padding:4px 0;
  font-size:14px;flex-wrap:wrap
}
.holding-item .name{font-weight:500;min-width:80px}
.holding-item .price{color:var(--sub);font-variant-numeric:tabular-nums}
.holding-item .chg{font-weight:600;font-variant-numeric:tabular-nums}

/* ---- 分隔 ---- */
hr{border:none;border-top:1px solid var(--border);margin:20px 0}

.source-note{font-size:12px;color:var(--muted);margin:16px 0 8px;text-align:center}

/* ---- 提示条 ---- */
.tip{
  background:#e8f5e9;color:#2e7d32;font-size:12px;padding:5px 14px;
  text-align:center;border-bottom:1px solid #c8e6c9
}
@media(prefers-color-scheme:dark){.tip{background:#1b3a1b;color:#81c784;border-color:#2e4a2e}}

/* ---- 音频播放器 ---- */
.player{
  position:fixed;bottom:0;left:0;right:0;z-index:200;
  background:var(--card);border-top:1px solid var(--border);
  padding:8px 16px max(8px,env(safe-area-inset-bottom,8px));
  box-shadow:0 -2px 12px rgba(0,0,0,.06)
}
.player-row{display:flex;align-items:center;gap:8px;max-width:680px;margin:0 auto}
.btn-play{
  width:44px;height:44px;border-radius:50%;border:none;font-size:18px;cursor:pointer;
  display:flex;align-items:center;justify-content:center;flex-shrink:0;
  transition:all .15s;-webkit-tap-highlight-color:transparent;
  background:var(--accent);color:#fff;box-shadow:0 2px 8px rgba(37,99,235,.2)
}
.btn-play:active{transform:scale(.92)}
.player-time{font-size:11px;color:var(--sub);min-width:34px;text-align:center;font-variant-numeric:tabular-nums}
.progress-wrap{flex:1;height:28px;display:flex;align-items:center;cursor:pointer;min-width:50px}
.progress-track{width:100%;height:4px;background:var(--border);border-radius:2px;overflow:hidden}
.progress-fill{height:100%;background:var(--accent);border-radius:2px;width:0}
.progress-thumb{
  position:absolute;top:50%;width:14px;height:14px;border-radius:50%;
  background:var(--accent);border:2px solid #fff;transform:translate(-50%,-50%);
  opacity:0;transition:opacity .12s;pointer-events:none;box-shadow:0 1px 4px rgba(0,0,0,.2)
}
.progress-wrap:active .progress-thumb{opacity:1}
@media(prefers-color-scheme:dark){.progress-thumb{border-color:var(--card)}}
.player-sub{display:flex;align-items:center;justify-content:center;gap:6px;margin-top:2px}
.speed-btn{background:none;border:none;color:var(--sub);font-size:11px;cursor:pointer;padding:2px 5px;border-radius:3px}
.speed-btn.active{color:var(--accent);font-weight:600}
.voice-label{font-size:10px;color:var(--sub)}
</style>
</head>
<body>
<div class="tip">点击 ▶ 播放音频日报（微软 AI 语音播报）</div>
<div class="header">
<h1>全球金融市场日报</h1>
<div class="date">__DATE__</div>
</div>
<div class="article">
__CONTENT__
</div>
<div class="player">
<div class="player-row">
<button class="btn-play" id="btnPlay">▶</button>
<span class="player-time" id="currentTime">00:00</span>
<div class="progress-wrap" id="progressWrap">
<div class="progress-track"><div class="progress-fill" id="progressFill"></div></div>
</div>
<span class="player-time" id="totalTime" data-duration="__DURATION__">__DURATION_FMT__</span>
</div>
<div class="player-sub">
<button class="speed-btn" data-speed="0.8">0.8x</button>
<button class="speed-btn active" data-speed="1.0">1x</button>
<button class="speed-btn" data-speed="1.25">1.25x</button>
<button class="speed-btn" data-speed="1.5">1.5x</button>
</div>
</div>
__PLAYER_SCRIPT__
</body>
</html>'''

PLAYER_JS = r'''<script>
(function(){
var btn=document.getElementById('btnPlay');
var cf=document.getElementById('currentTime');
var tf=document.getElementById('totalTime');
var pf=document.getElementById('progressFill');
var pw=document.getElementById('progressWrap');
var speeds=document.querySelectorAll('.speed-btn');
var playing=false,pos=0,rate=1;

function fmt(t){var m=Math.floor(t/60),s=Math.floor(t%60);return String(m).padStart(2,'0')+':'+String(s).padStart(2,'0')}

// 从 data-duration 取编译时预读的时长（ffprobe），若为0则后续靠 loadedmetadata 更新
var dur=parseFloat(tf.getAttribute('data-duration'))||0;
if(dur>0){tf.textContent=fmt(dur)}

// 提前创建 Audio 并加载元数据，不依赖点击播放
var a=new Audio();a.src='daily-report.mp3';a.preload='metadata';
a.addEventListener('loadedmetadata',function(){dur=a.duration;tf.textContent=fmt(dur);upd()});
a.addEventListener('timeupdate',function(){if(!playing)return;pos=a.currentTime;upd();if(pos>=dur-0.1){pause();pos=dur;upd()}});
a.addEventListener('ended',function(){playing=false;btn.textContent='\u25B6';pos=dur;upd()});

function upd(){if(!dur)return;var p=pos/dur;pf.style.width=(p*100)+'%';cf.textContent=fmt(pos)}

function doPlay(){a.playbackRate=rate;a.currentTime=pos;a.play().then(function(){playing=true;btn.textContent='\u23F8'}).catch(function(){})}
function pause(){a.pause();playing=false;btn.textContent='\u25B6'}

btn.addEventListener('click',function(){if(playing)pause();else doPlay()});

pw.addEventListener('click',function(e){
if(!dur)return;var rect=pw.getBoundingClientRect();
var x=e.clientX-rect.left;var p=Math.max(0,Math.min(1,x/rect.width));
pos=p*dur;a.currentTime=pos;upd()});

speeds.forEach(function(b){b.addEventListener('click',function(){
speeds.forEach(function(s){s.classList.remove('active')});
b.classList.add('active');rate=parseFloat(b.dataset.speed);
if(a){a.playbackRate=rate}})});

setInterval(function(){if(!playing)return;pos=a.currentTime;upd()},250)
})();</script>'''

# ============================================================
# 表格识别：这些标题下的表格渲染为 HTML <table>
# ============================================================
TABLE_SECTION_KW = [
    'A股收盘', '美股收盘', '港股收盘',
    '场内ETF溢价率', '场外QDII申购额度', 'QDII',
]


# ============================================================
# Smart Debold: 只保留涨跌方向加粗，其余去粗
# ============================================================
def _smart_inline(text):
    """处理行内 **加粗**：仅保留涨跌方向，其余去粗返回纯文本"""

    def _replace(m):
        content = m.group(1).strip()

        # 保留：↑/↓ + 百分比 方向标记
        if re.search(r'[↑↓][\d.]+%', content):
            cls = 'up' if '↑' in content else 'down'
            return f'<strong class="{cls}">{content}</strong>'

        # 保留：涨/跌 + 百分比（中文方向）
        if re.search(r'(上涨|涨幅|大涨|飙升)[\d.]+%', content):
            return f'<strong class="up">{content}</strong>'
        if re.search(r'(下跌|跌幅|重挫|暴跌)[\d.]+%', content):
            return f'<strong class="down">{content}</strong>'

        # 保留：独立方向词
        if content in ('上涨', '下跌', '大涨', '重挫', '飙升', '暴跌',
                       '净买入', '净卖出', '领涨', '领跌'):
            cls = 'up' if content in ('上涨', '大涨', '飙升', '净买入', '领涨') else 'down'
            return f'<strong class="{cls}">{content}</strong>'

        # 保留：QDII 溢价评估标签
        if content in ('极高溢价，严禁买入', '高溢价，警惕风险', '明显溢价，谨慎参与'):
            return f'<strong class="down">{content}</strong>'

        # 去粗：纯数字、名称、普通百分比等
        return content

    return re.sub(r'\*\*(.+?)\*\*', _replace, text)


def _markdown_to_html_inline(text):
    """将已去粗的文本中残余 ** 转为 <strong>，处理链接等"""
    # 残余 ** 转为 strong（不分类，因为方向类已在 _smart_inline 中处理并保留 class）
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    # 处理 markdown 链接 [text](url) → <a>
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2" target="_blank" rel="noopener">\1</a>', text)
    return text


# ============================================================
# 表格渲染
# ============================================================
def _parse_table_rows(lines):
    """从 markdown 表格行列表解析出 [header_row, ...data_rows]"""
    rows = []
    for line in lines:
        line = line.strip()
        if not line.startswith('|'):
            continue
        cells = [c.strip() for c in line.strip('|').split('|')]
        # 跳过全分隔符行 (|:---|:---|)
        if all(re.match(r'^[-:\s]+$', c) for c in cells):
            continue
        rows.append(cells)
    return rows


def _table_to_html(rows):
    """渲染为 HTML <table>"""
    if not rows:
        return ''

    headers = rows[0]
    data_rows = rows[1:]

    html = '<div class="table-wrap"><table class="data-table">\n'
    html += '<thead><tr>\n'
    for i, h in enumerate(headers):
        # 表头自身也去粗（不含涨跌方向）
        h_clean = re.sub(r'\*\*(.+?)\*\*', r'\1', h)
        align = 'num' if i >= 1 else ''
        html += f'<th class="{align}">{h_clean}</th>\n'
    html += '</tr></thead>\n<tbody>\n'

    for row in data_rows:
        html += '<tr>\n'
        for i, cell in enumerate(row):
            # 智能去粗
            cell_html = _smart_inline(cell)
            # 残余 ** 转 strong
            cell_html = _markdown_to_html_inline(cell_html)
            # QDII 风险评估标签：加粗+红色警示
            if cell_html.strip() in ('极高溢价，严禁买入', '高溢价，警惕风险', '明显溢价，谨慎参与'):
                cell_html = f'<strong class="down">{cell_html}</strong>'
            # 对齐
            cls = 'label' if i == 0 else 'num'
            html += f'<td class="{cls}">{cell_html}</td>\n'
        html += '</tr>\n'

    html += '</tbody>\n</table>\n</div>\n'
    return html


def _table_to_div(rows):
    """表格 → 文字叙述（非保留表格的兜底渲染）"""
    if not rows:
        return ''
    headers = rows[0]
    data_rows = rows[1:]

    parts = []
    for row in data_rows:
        name = re.sub(r'\*\*', '', row[0]) if row else ''
        if not name:
            continue
        values = []
        for i in range(1, min(len(row), len(headers))):
            cell = row[i]
            h = headers[i]
            # 去粗
            cell = re.sub(r'\*\*(.+?)\*\*', r'\1', cell)
            if not cell or cell in ('—', '-', '--', '...'):
                continue
            values.append(f'{h} {cell}')
        if values:
            parts.append(f'{name}：{"，".join(values)}')

    if not parts:
        return ''
    return '<p class="no-indent">' + '；'.join(parts) + '</p>'


def _should_render_table(title):
    """判断该板块是否应渲染为 HTML 表格"""
    title_clean = re.sub(r'\*\*', '', title)
    for kw in TABLE_SECTION_KW:
        if kw in title_clean:
            return True
    return False


# ============================================================
# MD 解析
# ============================================================
def parse_md_sections(md_text):
    """解析 MD 为 (type, title, lines) 板块列表"""
    lines = md_text.split('\n')
    blocks = []
    buf = []
    cur_title = ''
    cur_type = 'preamble'

    for line in lines:
        if line.startswith('# ') and not line.startswith('## '):
            if buf:
                blocks.append((cur_type, cur_title, buf))
            cur_title = line[2:].strip()
            cur_type = 'title'
            buf = []
        elif line.startswith('## '):
            if buf:
                blocks.append((cur_type, cur_title, buf))
            cur_title = line[3:].strip()
            cur_type = 'section'
            buf = []
        elif line.startswith('### '):
            if buf:
                blocks.append((cur_type, cur_title, buf))
                buf = []
            cur_title = line[4:].strip()
            cur_type = 'subsection'
        elif line.startswith('#### '):
            if buf:
                blocks.append((cur_type, cur_title, buf))
                buf = []
            cur_title = line[5:].strip()
            cur_type = 'subsubsection'
        elif line.startswith('##### '):
            if buf:
                blocks.append((cur_type, cur_title, buf))
                buf = []
            cur_title = line[6:].strip()
            cur_type = 'subsubsection'
        else:
            buf.append(line)

    if buf:
        blocks.append((cur_type, cur_title, buf))

    return blocks


# ============================================================
# 板块 → HTML 渲染
# ============================================================
def _render_text_line(line):
    """渲染单行文本为 HTML"""
    stripped = line.strip()
    if not stripped:
        return ''

    # 过滤来源声明行（硬编码 source-note 替代，避免重复）
    plain = re.sub(r'\*{1,3}', '', stripped).strip()
    if plain.startswith('数据来源') or plain.startswith('来源声明'):
        return ''
    # 跳过注说明段落（如 *注：涨跌幅使用...*）
    if re.match(r'\*?注[：:]', stripped):
        return ''

    # 过滤各板块的数据时间戳（已由 call_llm.py 后处理清除，此处双重保险）
    if re.match(r'>\s*数据时间[：:]\s*\d{4}-\d{2}-\d{2}', stripped):
        return ''
    if re.match(r'\*\*查询时间\*\*[：:]', stripped):
        return ''

    # 引用块
    if stripped.startswith('> '):
        content = stripped[2:].strip()
        # 跳过数据来源/注说明的引用块
        content_plain = re.sub(r'\*{1,3}', '', content).strip()
        if content_plain.startswith('数据来源') or content_plain.startswith('来源声明') or content_plain.startswith('注：') or content_plain.startswith('注:'):
            return ''
        content = _smart_inline(content)
        content = _markdown_to_html_inline(content)
        return f'<blockquote>{content}</blockquote>'

    # 无序列表
    if stripped.startswith('- ') or stripped.startswith('* '):
        content = stripped[2:].strip()
        content = _smart_inline(content)
        content = _markdown_to_html_inline(content)
        return f'<li>{content}</li>'

    # 有序列表
    m = re.match(r'^(\d+)\.\s+(.*)', stripped)
    if m:
        content = m.group(2)
        content = _smart_inline(content)
        content = _markdown_to_html_inline(content)
        return f'<li>{content}</li>'

    # 水平线
    if stripped in ('---', '***', '___'):
        return '<hr>'

    # 普通段落
    content = _smart_inline(stripped)
    content = _markdown_to_html_inline(content)
    return f'<p>{content}</p>'


def _is_table_line(line):
    return line.strip().startswith('|')


def block_to_html(lines, title='', level='section'):
    """板块 → HTML 片段"""
    if not lines:
        return ''

    # 收集表格和文本行
    table_groups = []  # [(table_lines, preceding_title)]
    text_groups = []   # [list of text lines]
    current_text = []
    current_table = []

    for line in lines:
        if _is_table_line(line):
            if current_text:
                text_groups.append(current_text)
                current_text = []
            current_table.append(line)
        else:
            if current_table:
                table_groups.append((current_table, title))
                current_table = []
            current_text.append(line)

    if current_table:
        table_groups.append((current_table, title))
    if current_text:
        text_groups.append(current_text)

    html_parts = []

    # 处理标题
    tag_map = {
        'section': 'h2', 'subsection': 'h3',
        'subsubsection': 'h4', 'title': 'h1',
    }
    tag = tag_map.get(level, 'h2')
    title_clean = re.sub(r'\*\*', '', title).strip()

    # 跳过 QDII 和个人持仓板块的标题（HTML 不公开个人持仓）
    _SKIP_HTML_SECTIONS = ['个人持仓', '持仓']

    if title_clean:
        if any(kw in title_clean for kw in _SKIP_HTML_SECTIONS):
            return ''  # 整块跳过
        html_parts.append(f'<{tag}>{title_clean}</{tag}>')

    # 交错渲染：表格和文本按它们在 MD 中的顺序出现
    # 简化：先渲染表格组，再渲染文本组
    for tbl_lines, tbl_title in table_groups:
        rows = _parse_table_rows(tbl_lines)
        if not rows:
            continue
        if _should_render_table(tbl_title):
            html_parts.append(_table_to_html(rows))
        else:
            html_parts.append(_table_to_div(rows))

    for text_group in text_groups:
        # 检测有序列表块
        is_ordered_list = any(
            re.match(r'^\d+\.\s', l.strip()) for l in text_group if l.strip()
        )
        is_unordered_list = any(
            l.strip().startswith(('- ', '* ')) for l in text_group if l.strip()
        )

        if is_ordered_list:
            html_parts.append('<ol class="news-list">')
            for line in text_group:
                rendered = _render_text_line(line)
                if rendered:
                    html_parts.append(rendered)
            html_parts.append('</ol>')
        elif is_unordered_list:
            # 个人持仓特殊处理：转为卡片样式
            if any('持仓' in kw for kw in [title_clean]):
                html_parts.append('<div class="card">')
                html_parts.append('<div class="card-title">持仓快照</div>')
                for line in text_group:
                    stripped = line.strip()
                    if stripped.startswith('- '):
                        content = stripped[2:]
                        content = _smart_inline(content)
                        content = _markdown_to_html_inline(content)
                        html_parts.append(f'<div class="holding-item">{content}</div>')
                    else:
                        rendered = _render_text_line(line)
                        if rendered:
                            html_parts.append(rendered)
                html_parts.append('</div>')
            else:
                html_parts.append('<ul>')
                for line in text_group:
                    rendered = _render_text_line(line)
                    if rendered:
                        html_parts.append(rendered)
                html_parts.append('</ul>')
        else:
            in_lede = False
            for i, line in enumerate(text_group):
                rendered = _render_text_line(line)
                if not rendered:
                    continue
                stripped = line.strip()
                # 定性导语段落特殊处理：标签行跳过，下一行作lede卡片
                if '定性导语' in stripped:
                    in_lede = True
                    continue
                if in_lede:
                    content = _smart_inline(stripped)
                    content = _markdown_to_html_inline(content)
                    html_parts.append(f'<p class="lede">{content}</p>')
                    in_lede = False
                else:
                    html_parts.append(rendered)

    return '\n'.join(html_parts)


# ============================================================
# 主流程
# ============================================================
def _extract_date(md_text):
    """从 MD 中提取日期"""
    m = re.search(
        r'(\d{4})年(\d{1,2})月(\d{1,2})日.*?(?:星期([一二三四五六日])|[（(]周([一二三四五六日])[）)])',
        md_text
    )
    if m:
        weekday = m.group(4) or m.group(5)
        return f'{m.group(1)}年{m.group(2)}月{m.group(3)}日 星期{weekday}'
    m2 = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', md_text)
    if m2:
        return f'{m2.group(1)}年{m2.group(2)}月{m2.group(3)}日'
    return datetime.datetime.now().strftime('%Y年%m月%d日')


def _extract_data_time(md_text):
    """从 LLM 来源行提取数据抓取时间戳，转为 ISO 日期格式。
    匹配: '数据获取时间：北京时间 2026年7月11日 18:22'
           '查询时间：北京时间 2026年7月11日 18:22'"""
    m = re.search(
        r'(?:数据获取时间|查询时间)[：:]\s*(?:北京时间\s*)?'
        r'(\d{4})年(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})',
        md_text
    )
    if m:
        return f'{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d} {int(m.group(4)):02d}:{int(m.group(5)):02d}'
    return ''


def md_to_html(md_file):
    """读取 MD 文件，返回完整 HTML 字符串"""
    with open(md_file, 'r', encoding='utf-8') as f:
        md_text = f.read()

    date_str = _extract_date(md_text)
    data_time = _extract_data_time(md_text)  # 从 LLM 来源行提取数据抓取时间戳
    blocks = parse_md_sections(md_text)

    body_parts = []
    for typ, title, block_lines in blocks:
        # 跳过 H1 标题块（已在 HTML header 模板中显示）
        if typ == 'title' or typ == 'preamble':
            continue
        fragment = block_to_html(block_lines, title, typ)
        if fragment:
            body_parts.append(fragment)

    body_html = '\n\n'.join(body_parts)

    # 用 ffprobe 预读 MP3 时长
    mp3_path = md_file.replace('report.md', 'daily-report.mp3')
    dur_sec = 0.0
    if not os.path.exists(mp3_path):
        mp3_path = 'daily-report.mp3'
    if os.path.exists(mp3_path):
        try:
            r = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                 '-of', 'csv=p=0', mp3_path],
                capture_output=True, text=True, timeout=5
            )
            if r.returncode == 0 and r.stdout.strip():
                dur_sec = float(r.stdout.strip())
        except Exception:
            pass
    dur_fmt = f'{int(dur_sec//60):02d}:{int(dur_sec%60):02d}'

    html = TEMPLATE
    html = html.replace('__DATE__', date_str)
    html = html.replace('__DURATION__', f'{dur_sec:.1f}')
    html = html.replace('__DURATION_FMT__', dur_fmt)
    html = html.replace('__CONTENT__', body_html)
    html = html.replace('__PLAYER_SCRIPT__', PLAYER_JS)

    return html


def main():
    if len(sys.argv) < 2:
        print("用法: python3 md_to_reader.py <report.md> [daily-report.html]")
        sys.exit(1)

    md_file = sys.argv[1]
    html_file = sys.argv[2] if len(sys.argv) > 2 else 'daily-report.html'

    if not os.path.exists(md_file):
        print(f"❌ 文件不存在: {md_file}")
        sys.exit(1)

    print(f"📖 读取: {md_file}")
    html = md_to_html(md_file)
    with open(html_file, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"✅ 输出: {html_file} ({len(html)} 字符)")


if __name__ == '__main__':
    main()