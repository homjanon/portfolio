#!/usr/bin/env python3
"""把 Markdown 日报转为纯文本叙述 HTML（内嵌原生音频播放器，播放预生成的 MP3）"""
import sys, re, os, datetime

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
<!-- build=__BUILD__ -->
<style>
:root{--bg:#f8f9fa;--card:#fff;--text:#1a1a2e;--sub:#6b7280;--border:#e5e7eb;--accent:#2563eb;--note-bg:#f0f4ff}
@media(prefers-color-scheme:dark){:root{--bg:#0f172a;--card:#1e293b;--text:#e2e8f0;--sub:#94a3b8;--border:#334155;--accent:#3b82f6;--note-bg:#1e293b}}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;background:var(--bg);color:var(--text);font-size:16px;line-height:1.9;min-height:100dvh;padding:0 0 150px;-webkit-text-size-adjust:100%}
.header{background:var(--card);border-bottom:1px solid var(--border);padding:18px 16px;text-align:center;position:relative}
.header h1{font-size:20px;font-weight:700;margin-bottom:4px}
.header .date{font-size:13px;color:var(--sub);margin-bottom:8px}
.refresh-btn{position:absolute;right:16px;top:14px;background:var(--accent);color:#fff;border:none;padding:6px 14px;border-radius:20px;font-size:13px;cursor:pointer;display:none}
.refresh-btn.show{display:block}
.stale-banner{background:#fef3c7;color:#92400e;font-size:13px;padding:6px 14px;text-align:center;display:none}
.stale-banner.show{display:block}
@media(prefers-color-scheme:dark){.stale-banner{background:#422006;color:#fde68a}}
.tip{background:#e8f5e9;color:#2e7d32;font-size:13px;padding:6px 14px;text-align:center;border-bottom:1px solid #c8e6c9}
@media(prefers-color-scheme:dark){.tip{background:#1b3a1b;color:#81c784;border-color:#2e4a2e}}
.article{max-width:700px;margin:0 auto;padding:20px 16px}
.article h2{font-size:18px;margin:32px 0 10px;padding-bottom:4px;border-bottom:2px solid var(--accent)}
.article h3{font-size:16px;margin:22px 0 6px;color:var(--accent)}
.article p{margin:10px 0;text-indent:2em}
.article p.no-indent{text-indent:0}
.article .table-text{margin:8px 0;padding:8px 12px;background:var(--note-bg);border-radius:8px;font-size:15px;line-height:2;text-indent:0}
.article strong{color:var(--accent);font-weight:700}
.article blockquote{border-left:3px solid var(--accent);padding:8px 14px;margin:10px 0;background:var(--note-bg);border-radius:0 8px 8px 0;color:var(--sub);font-size:14px}
.article .source{font-size:12px;color:var(--sub);margin:2px 0 10px;text-indent:0;font-style:normal}
.article ul,.article ol{padding-left:22px;margin:8px 0}
.article li{margin:6px 0;line-height:1.8}
.article hr{border:none;border-top:1px solid var(--border);margin:24px 0}
.up{color:#059669;font-weight:600}.down{color:#dc2626;font-weight:600}
@media(prefers-color-scheme:dark){.up{color:#34d399}.down{color:#f87171}}
.player{position:fixed;bottom:0;left:0;right:0;z-index:200;background:var(--card);border-top:1px solid var(--border);padding:10px 16px max(10px,env(safe-area-inset-bottom,10px));box-shadow:0 -2px 12px rgba(0,0,0,.08)}
.player-row{display:flex;align-items:center;gap:8px;max-width:500px;margin:0 auto}
.btn-play{width:48px;height:48px;border-radius:50%;border:none;font-size:20px;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:all .15s;-webkit-tap-highlight-color:transparent;background:var(--accent);color:#fff;box-shadow:0 2px 8px rgba(37,99,235,.25)}
.btn-play:active{transform:scale(.92)}
.player-time{font-size:11px;color:var(--sub);min-width:36px;text-align:center;white-space:nowrap;font-variant-numeric:tabular-nums}
.progress-wrap{flex:1;height:32px;display:flex;align-items:center;cursor:pointer;position:relative;min-width:60px}
.progress-track{width:100%;height:4px;background:var(--border);border-radius:2px;overflow:hidden;position:relative}
.progress-fill{height:100%;background:var(--accent);border-radius:2px;width:0;transition:none}
.progress-thumb{position:absolute;top:50%;width:14px;height:14px;border-radius:50%;background:var(--accent);border:2px solid #fff;transform:translate(-50%,-50%);opacity:0;transition:opacity .12s;pointer-events:none;box-shadow:0 1px 4px rgba(0,0,0,.2)}
.progress-wrap:hover .progress-thumb,.progress-wrap:active .progress-thumb{opacity:1}
@media(prefers-color-scheme:dark){.progress-thumb{border-color:var(--card)}}
.player-sub{display:flex;align-items:center;justify-content:center;gap:8px;margin-top:2px}
.speed-btn{background:none;border:none;color:var(--sub);font-size:11px;cursor:pointer;padding:2px 6px;border-radius:3px;transition:all .12s}
.speed-btn.active{color:var(--accent);font-weight:600}
.speed-btn:hover{background:var(--note-bg)}
.voice-label{font-size:10px;color:var(--sub);padding:2px 4px}
</style>
</head>
<body>
<div class="stale-banner" id="staleBanner"></div>
<div class="tip">💡 点击 ▶ 播放音频日报（微软 AI 语音播报），暂停/续播/拖动进度条均可</div>
<div class="header">
<h1>📰 全球金融市场日报</h1>
<div class="date" id="reportDate">__DATE__</div>
<button class="refresh-btn" id="refreshBtn" onclick="window.location.href=window.location.pathname+'?_='+Date.now()">🔄 刷新</button>
</div>
<div class="article" id="articleContent">
__CONTENT__
</div>
<div class="player">
<div class="player-row">
<button class="btn-play" id="btnPlay">▶</button>
<span class="player-time" id="currentTime">00:00</span>
<div class="progress-wrap" id="progressWrap">
<div class="progress-track"><div class="progress-fill" id="progressFill"></div></div>
<div class="progress-thumb" id="progressThumb"></div>
</div>
<span class="player-time" id="totalTime">00:00</span>
</div>
<div class="player-sub">
<button class="speed-btn" data-speed="0.8">0.8×</button>
<button class="speed-btn active" data-speed="1">1×</button>
<button class="speed-btn" data-speed="1.2">1.2×</button>
<button class="speed-btn" data-speed="1.5">1.5×</button>
</div>
</div>
<audio id="audioPlayer" preload="auto" src="daily-report.mp3?__MP3VER__"></audio>
<script>
(function(){var p=document.getElementById("btnPlay"),a=document.getElementById("audioPlayer"),c=document.getElementById("progressFill"),t=document.getElementById("progressThumb"),w=document.getElementById("progressWrap"),ct=document.getElementById("currentTime"),tt=document.getElementById("totalTime"),sb=document.querySelectorAll(".speed-btn");
function fmt(s){if(!s||!isFinite(s))return"00:00";var m=Math.floor(s/60),sec=Math.floor(s%60);return(m<10?"0":"")+m+":"+(sec<10?"0":"")+sec}
function upd(){var d=a.duration||0,n=a.currentTime||0;var pct=d>0?(n/d*100):0;c.style.width=pct+"%";if(t)t.style.left=pct+"%";ct.textContent=fmt(n);if(d)tt.textContent=fmt(d)}
a.addEventListener("loadedmetadata",function(){tt.textContent=fmt(a.duration||0);upd()});
a.addEventListener("timeupdate",upd);
a.addEventListener("ended",function(){p.textContent="▶"});
a.addEventListener("pause",function(){p.textContent="▶"});
a.addEventListener("play",function(){p.textContent="⏸"});
p.addEventListener("click",function(){if(a.paused){a.play()["catch"](function(e){console.warn(e)})}else{a.pause()}});
function doSeek(e){var r=w.getBoundingClientRect(),x=(e.clientX||0)-r.left,pct=Math.max(0,Math.min(1,x/r.width));c.style.width=(pct*100)+"%";if(t)t.style.left=(pct*100)+"%";if(a.duration){a.currentTime=pct*a.duration;ct.textContent=fmt(a.currentTime)}}
w.addEventListener("click",function(e){doSeek(e)});
var drag=false;
w.addEventListener("mousedown",function(e){drag=true;doSeek(e)});
document.addEventListener("mousemove",function(e){if(drag){doSeek(e)}});
document.addEventListener("mouseup",function(){drag=false});
w.addEventListener("touchstart",function(e){drag=true;var touch=e.touches[0];doSeek({clientX:touch.clientX})});
document.addEventListener("touchmove",function(e){if(drag){var touch=e.touches[0];doSeek({clientX:touch.clientX});e["default"]()}},{passive:false});
document.addEventListener("touchend",function(){drag=false});
// 倍速切换
sb.forEach(function(btn){btn.addEventListener("click",function(){sb.forEach(function(b){b.classList.remove("active")});btn.classList.add("active");a.playbackRate=parseFloat(btn.getAttribute("data-speed"))})});
// 键盘快捷键
document.addEventListener("keydown",function(e){if(e.target.tagName==="INPUT"||e.target.tagName==="TEXTAREA")return;if(e.key===" "){e["default"]();if(a.paused){a.play()["catch"](function(){})}else{a.pause()}}else if(e.key==="ArrowRight"){a.currentTime=Math.min(a.currentTime+10,a.duration||a.currentTime)}else if(e.key==="ArrowLeft"){a.currentTime=Math.max(a.currentTime-10,0)}});
// 过期检测
(function(){var q=document.getElementById("reportDate");if(!q)return;var r=q.textContent.match(/(\d{4})年(\d{1,2})月(\d{1,2})日/);if(!r)return;var s=new Date(r[1],r[2]-1,r[3]);var d=new Date();d.setHours(0,0,0,0);if(s<d){var b=document.getElementById("staleBanner"),btn=document.getElementById("refreshBtn");b.textContent="⏳ 已检测旧版内容，正在自动刷新...";b.classList.add("show");btn.classList.add("show");setTimeout(function(){window.location.href=window.location.pathname+"?_="+Date.now()},1500)}})();
})();
</script>
<script>
// 注册 Service Worker：强制网络刷新 HTML
if('serviceWorker' in navigator){navigator.serviceWorker.register('sw.js').then(function(reg){console.log('SW registered')})["catch"](function(e){console.warn('SW failed:',e)})}
</script>
</body>
</html>'''


def _safe(val):
    """过滤缺失值"""
    v = val.replace('**', '').strip()
    if not v or v in ('—', '-', '--', '...', '—', '－', '――'):
        return None
    if re.match(r'^[─\-–—\s]+$', v):
        return None
    return v


def _clean(text):
    """清理 markdown：去加粗、↑→上涨、↓→下跌"""
    text = text.replace('**', '')
    text = text.replace('↑', '上涨').replace('↓', '下跌')
    return text


def _table_to_text(rows):
    """表格 → 自然叙述文本（通过表头关键词智能映射列位置）"""
    if len(rows) < 2:
        return ""
    headers = [h.replace('**', '') for h in rows[0]]
    data_rows = rows[1:]
    all_headers = " ".join(headers)
    first_header = headers[0] if headers else ""

    def _col_idx(keywords, exclude_kw=None):
        """在 headers 中查找包含某关键词的列索引"""
        kws = keywords if isinstance(keywords, (list, tuple)) else [keywords]
        for i, h in enumerate(headers):
            if all(k in h for k in kws):
                if exclude_kw and exclude_kw in h:
                    continue
                return i
        return None

    # ── 估值表（PE/PB 多列格式）──
    if any(kw in all_headers for kw in ['PE', 'PB', '估值', '市盈率', '市净率']):
        pe_col = _col_idx('PE', '分位') or _col_idx('市盈') or None
        pe_pct_col = _col_idx(['PE', '分位']) or _col_idx(['PE', '历史']) or None
        pb_col = _col_idx('PB', '分位') or _col_idx('市净') or None
        pb_pct_col = _col_idx(['PB', '分位']) or _col_idx(['PB', '历史']) or None
        pos_col = _col_idx('分位') or _col_idx('历史分位') or None
        notes_col = _col_idx('备注') or None
        parts = []
        for row in data_rows:
            name = row[0].replace('**', '') if len(row) > 0 else ''
            details = []
            if pe_col is not None and pe_col < len(row):
                pe = _safe(row[pe_col])
                if pe: details.append(f"市盈率{pe}倍")
            if pb_col is not None and pb_col < len(row):
                pb = _safe(row[pb_col])
                if pb: details.append(f"市净率{pb}倍")
            used_summary = False
            if pe_pct_col is not None and pe_pct_col < len(row):
                pct = _safe(row[pe_pct_col])
                if pct: details.append(f"PE分位{pct}")
            elif pos_col is not None and pos_col < len(row) and pos_col != (pb_pct_col or -1):
                pct = _safe(row[pos_col])
                if pct:
                    details.append(f"PE分位{pct}")
                    used_summary = True
            if pb_pct_col is not None and pb_pct_col < len(row):
                pct = _safe(row[pb_pct_col])
                if pct: details.append(f"PB分位{pct}")
            elif not used_summary and pos_col is not None and pos_col < len(row) and pos_col != (pe_pct_col or -1):
                pct = _safe(row[pos_col])
                if pct:
                    details.append(f"PB分位{pct}")
                    used_summary = True
            if not used_summary and pos_col is not None and pos_col < len(row):
                pos = _safe(row[pos_col])
                if pos and len(pos) < 20:
                    details.append(f"估值{pos}")
            if details:
                parts.append(f"{name}，{'，'.join(details)}")
        if parts:
            return "。".join(parts) + "。"

    # ── 恐慌指数（VIX/VXN）──
    if (headers and len(headers) >= 3
            and any(kw in headers[2] for kw in ['解读', '状态', '区间'])):
        val_col = _col_idx('数值') or _col_idx('最新值') or 1
        desc_col = _col_idx('解读') or _col_idx('状态') or _col_idx('区间') or 2
        sentences = []
        for row in data_rows:
            name = row[0].replace('**', '') if len(row) > 0 else ''
            val = _safe(row[val_col]) if len(row) > val_col else None
            desc = _safe(row[desc_col]) if len(row) > desc_col else None
            if val and desc:
                sentences.append(f"{name}报{val}，{desc}")
            elif val:
                sentences.append(f"{name}报{val}")
        if sentences:
            return "。".join(sentences) + "。"

    # ── QDII/ETF溢价表 ──
    if any(kw in all_headers for kw in ['ETF', '溢价率']):
        code_col = _col_idx('代码') or _col_idx('ETF代码') or 1
        premium_col = _col_idx('溢价') or _col_idx('溢价率') or 2
        parts = []
        for row in data_rows:
            name = row[0].replace('**', '') if len(row) > 0 else ''
            code = _safe(row[code_col]) if len(row) > code_col else None
            premium = _safe(row[premium_col]) if len(row) > premium_col else None
            text_parts = [name]
            if code: text_parts.append(f"代码{code}")
            if premium: text_parts.append(f"溢价率{_clean(premium)}")
            if len(text_parts) > 1:
                parts.append("，".join(text_parts))
        if parts:
            return "。".join(parts) + "。"

    # ── 场外基金表（代码 + 名称 + 净值）──
    code_col = _col_idx('代码')
    name_col = _col_idx('名称') or _col_idx('基金')
    if code_col is not None and code_col == 0 and name_col is not None:
        nav_col = _col_idx('净值') or _col_idx('最新净值') or 2
        change_col = _col_idx('日涨跌') or _col_idx('涨跌幅') or _col_idx('涨跌') or 3
        parts = []
        for row in data_rows:
            code = row[0].replace('**', '') if len(row) > 0 else ''
            fname = _safe(row[1]) if len(row) > 1 else None
            nav = _safe(row[nav_col]) if len(row) > nav_col else None
            change = _safe(row[change_col]) if len(row) > change_col else None
            text = fname if fname else code
            if code and fname:
                text = f"{fname}（{code}）"
            if nav: text += f"，净值{nav}"
            if change: text += f"，近周{_clean(change)}"
            if nav or change: parts.append(text)
        if parts:
            return "。".join(parts) + "。"

    # ── 个股持仓表 ──
    code_col = _col_idx('代码')
    price_col = _col_idx('价') or _col_idx('收盘价') or _col_idx('价格') or _col_idx('最新价') or 1
    change_col = _col_idx('涨跌') or _col_idx('涨跌幅') or (price_col + 1 if price_col is not None else 2)
    if '标的' in first_header or '持仓' in first_header or ('代码' in all_headers and price_col != 0):
        parts = []
        for row in data_rows:
            if len(row) < 2: continue
            name = row[0].replace('**', '')
            if code_col is not None and code_col > 0 and code_col < len(row):
                code = row[code_col].replace('**', '')
                name = f"{name}（{code}）"
            price = _safe(row[price_col]) if len(row) > price_col else None
            change = _safe(row[change_col]) if len(row) > change_col else None
            text = name
            if price: text += f"，价格{price}"
            if change: text += f"，{_clean(change)}"
            if price or change: parts.append(text)
        if parts:
            return "。".join(parts) + "。"

    # ── 指数收盘表（A股/美股指数）──
    if any(kw in first_header for kw in ['指数', '标的']):
        val_col = _col_idx('点位') or _col_idx('收盘价') or _col_idx('收盘点位') or _col_idx('价格') or 1
        change_col = _col_idx('涨跌') or _col_idx('涨跌幅') or 2
        sentences = []
        for row in data_rows:
            if len(row) < 2: continue
            name = row[0].replace('**', '')
            val = _safe(row[val_col]) if len(row) > val_col else None
            change = _safe(row[change_col]) if len(row) > change_col else None
            if val and change:
                c = _clean(change)
                if re.search(r'\d', val):
                    sentences.append(f"{name}报收{val}，{c}")
                else:
                    sentences.append(f"{name}，{val}，{c}")
            elif val:
                sentences.append(f"{name}报收{val}")
            elif change:
                sentences.append(f"{name}{_clean(change)}")
        if sentences:
            return "。".join(sentences) + "。"

    # ── 通用表 ──
    parts = []
    for row in data_rows:
        snippet = []
        for i, cell in enumerate(row):
            v = _safe(cell)
            if v and i < len(headers):
                snippet.append(f"{headers[i]}{v}")
        if snippet:
            parts.append("，".join(snippet))
    if parts:
        return "。".join(parts) + "。"
    return ""


def _inline(text):
    """行内元素：**加粗** → <strong>，↑↓ → 上涨/下跌（无箭头，适合朗读）"""
    text = re.sub(r'↑([\d.]+%?)', r'<span class="up">上涨\1</span>', text)
    text = re.sub(r'↓([\d.]+%?)', r'<span class="down">下跌\1</span>', text)
    text = re.sub(r'(?<!上涨)(?<!下跌)↑(?![\d.])', '上涨', text)
    text = re.sub(r'(?<!上涨)(?<!下跌)↓(?![\d.])', '下跌', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    idx = 0
    protected = []
    def _protect(m):
        nonlocal idx
        ph = f'\x00{idx}\x00'
        protected.append(m.group(0))
        idx += 1
        return ph
    text = re.sub(r'</?(?:strong|span)(?:\s[^>]*)?>', _protect, text)
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    for i, tag in enumerate(protected):
        text = text.replace(f'\x00{i}\x00', tag)
    return text


def _collapse_list_blank_lines(text):
    """合并列表项之间的空行以及数据来源行（MD 中列表项之间有空行或来源行时会被拆成多个列表）"""
    lines = text.split('\n')
    result = []
    i = 0
    while i < len(lines):
        result.append(lines[i])
        current = lines[i].strip()
        # 当前行为列表项
        if re.match(r'^\d+\.\s', current) or current.startswith('- '):
            current_is_ol = bool(re.match(r'^\d+\.\s', current))
            current_is_ul = current.startswith('- ')
            # 查看后续空行或数据来源行后的下一行是否同类列表项
            j = i + 1
            while j < len(lines) and (not lines[j].strip() or re.match(r'^\s+\*?数据来源', lines[j]) or re.match(r'^\s+\*?来源[：:]', lines[j])):
                j += 1
            if j < len(lines):
                next_line = lines[j].strip()
                next_is_ol = bool(re.match(r'^\d+\.\s', next_line))
                next_is_ul = next_line.startswith('- ')
                if (current_is_ol and next_is_ol) or (current_is_ul and next_is_ul):
                    # 跳过中间的空白行和来源行，让两个列表项连在同一个列表中
                    i = j
                    continue
        i += 1
    return '\n'.join(result)


def md_to_html(text):
    """Markdown → 纯文本叙述 HTML（表格全部转为段落文字）"""
    # 先预处理：合并被空行分隔的同类列表项
    text = _collapse_list_blank_lines(text)
    lines = text.split('\n')
    out = []
    in_table = False
    table_lines = []
    in_list = False
    list_type = 'ul'
    in_quote = False
    first_para = True

    def flush_table():
        nonlocal in_table, table_lines
        if not table_lines:
            return
        rows = []
        for line in table_lines:
            line = line.strip()
            if not line.startswith('|'):
                continue
            cells = [c.strip() for c in line.strip('|').split('|')]
            if all(re.match(r'^[-:]+$', c) for c in cells):
                continue
            rows.append(cells)
        table_lines = []
        in_table = False
        if rows:
            tts = _table_to_text(rows)
            if tts:
                tts_safe = tts.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                out.append(f'<div class="table-text">{tts_safe}</div>')

    def flush_list():
        nonlocal in_list, list_type
        if in_list:
            out.append(f'</{list_type}>')
            in_list = False

    def flush_quote():
        nonlocal in_quote
        if in_quote:
            out.append('</blockquote>')
            in_quote = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            flush_quote(); flush_table(); flush_list()
            continue

        if stripped.startswith('### '):
            flush_quote(); flush_table(); flush_list()
            out.append(f'<h3>{_inline(stripped[4:])}</h3>')
        elif stripped.startswith('## '):
            flush_quote(); flush_table(); flush_list()
            out.append(f'<h2>{_inline(stripped[3:])}</h2>')
        elif stripped.startswith('# '):
            flush_quote(); flush_table(); flush_list()
            out.append(f'<h1>{_inline(stripped[2:])}</h1>')

        elif stripped.startswith('> '):
            flush_list(); flush_table()
            if not in_quote:
                out.append('<blockquote>')
                in_quote = True
            out.append(f'<p class="no-indent">{_inline(stripped[2:])}</p>')

        elif stripped.startswith('|'):
            flush_list(); flush_quote()
            table_lines.append(stripped)
            in_table = True

        elif stripped.startswith('- '):
            flush_table(); flush_quote()
            if not in_list:
                out.append('<ul>')
                list_type = 'ul'; in_list = True
            out.append(f'<li>{_inline(stripped[2:])}</li>')

        elif re.match(r'^\d+\.\s', stripped):
            flush_table(); flush_quote()
            if not in_list:
                out.append('<ol>')
                list_type = 'ol'; in_list = True
            content = re.sub(r'^\d+\.\s', '', stripped)
            out.append(f'<li>{_inline(content)}</li>')

        elif stripped in ('---', '***', '___'):
            flush_quote(); flush_table(); flush_list()
            out.append('<hr>')

        elif stripped.startswith('*') and ('数据来源' in stripped or stripped.startswith('*来源：') or stripped.startswith('*来源:')):
            flush_table(); flush_list(); flush_quote()
            content = stripped.strip('* ').strip()
            out.append(f'<p class="source">{content}</p>')

        else:
            flush_table(); flush_quote(); flush_list()
            cls = 'no-indent' if first_para else ''
            out.append(f'<p class="{cls}">{_inline(stripped)}</p>')
            first_para = False

    flush_quote(); flush_table(); flush_list()
    return '\n'.join(out)


def main():
    if len(sys.argv) < 2:
        print("用法: python3 md_to_reader.py <input.md> [output.html]")
        sys.exit(1)

    md_file = sys.argv[1]
    html_file = sys.argv[2] if len(sys.argv) > 2 else md_file.rsplit('.', 1)[0] + '.html'

    with open(md_file, 'r', encoding='utf-8') as f:
        md_text = f.read()

    date_match = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日.*?星期([一二三四五六日])', md_text)
    if date_match:
        date_str = f'{date_match.group(1)}年{date_match.group(2)}月{date_match.group(3)}日 星期{date_match.group(4)}'
        date_tag = f'{date_match.group(1)}{date_match.group(2).zfill(2)}{date_match.group(3).zfill(2)}'
    else:
        now = datetime.datetime.now()
        date_str = now.strftime('%Y年%m月%d日')
        date_tag = now.strftime('%Y%m%d')

    html_content = md_to_html(md_text)
    html_output = TEMPLATE.replace('__DATE__', date_str).replace('__CONTENT__', html_content)
    html_output = html_output.replace('__MP3VER__', date_tag)
    html_output = html_output.replace('__BUILD__', datetime.datetime.now().strftime('%Y%m%d%H%M'))

    with open(html_file, 'w', encoding='utf-8') as f:
        f.write(html_output)

    tables_converted = html_output.count('table-text')
    print(f"✅ 生成朗读用 HTML: {html_file} ({len(html_output)} 字节, {tables_converted} 段表格叙述)")


if __name__ == '__main__':
    main()
