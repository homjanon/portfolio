#!/usr/bin/env python3
"""把 Markdown 日报转为纯文本叙述 HTML（适合直接朗读）"""
import sys, re, os, datetime

TEMPLATE = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>全球金融市场日报</title>
<style>
:root{--bg:#f8f9fa;--card:#fff;--text:#1a1a2e;--sub:#6b7280;--border:#e5e7eb;--accent:#2563eb;--note-bg:#f0f4ff}
@media(prefers-color-scheme:dark){:root{--bg:#0f172a;--card:#1e293b;--text:#e2e8f0;--sub:#94a3b8;--border:#334155;--accent:#3b82f6;--note-bg:#1e293b}}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;background:var(--bg);color:var(--text);font-size:16px;line-height:1.9;min-height:100dvh;padding:0 0 130px;-webkit-text-size-adjust:100%}
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
.article ul,.article ol{padding-left:22px;margin:8px 0}
.article li{margin:6px 0;line-height:1.8}
.article hr{border:none;border-top:1px solid var(--border);margin:24px 0}
.up{color:#059669;font-weight:600}.down{color:#dc2626;font-weight:600}
@media(prefers-color-scheme:dark){.up{color:#34d399}.down{color:#f87171}}
.speak-active{background:var(--accent);color:#fff;border-radius:4px;padding:0 4px;display:inline}
.player{position:fixed;bottom:0;left:0;right:0;z-index:200;background:var(--card);border-top:1px solid var(--border);padding:10px 16px max(10px,env(safe-area-inset-bottom,10px));box-shadow:0 -2px 12px rgba(0,0,0,.08)}
.player-row{display:flex;align-items:center;gap:10px;max-width:500px;margin:0 auto}
.btn{width:44px;height:44px;border-radius:50%;border:none;font-size:20px;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:all .15s;-webkit-tap-highlight-color:transparent;background:var(--bg);color:var(--text);border:1px solid var(--border)}
.btn:active{transform:scale(.94)}
.btn-play{width:56px;height:56px;font-size:24px;background:var(--accent);color:#fff;border:none;box-shadow:0 3px 10px rgba(37,99,235,.3)}
.btn-sm{width:36px;height:36px;font-size:16px}
.speed{font-size:12px;color:var(--sub);min-width:32px;text-align:center;cursor:pointer;padding:4px 0;user-select:none}
.voice-btn{font-size:12px;color:var(--sub);min-width:48px;text-align:center;cursor:pointer;padding:4px 6px;user-select:none;border-radius:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.voice-btn:active{background:var(--bg)}
.voice-btn.has-voices{color:var(--accent)}
.progress{flex:1;height:4px;background:var(--border);border-radius:2px;overflow:hidden}
.progress-fill{height:100%;background:var(--accent);border-radius:2px;width:0;transition:width .2s linear}
.toast{position:fixed;top:12px;left:50%;transform:translateX(-50%);background:#1f2937;color:#fff;padding:8px 20px;border-radius:20px;font-size:14px;z-index:300;pointer-events:none;opacity:0;transition:opacity .25s}
.toast.show{opacity:1}
@media(prefers-color-scheme:dark){.toast{background:#374151}}
</style>
</head>
<body>
<div class="stale-banner" id="staleBanner">⚠️ 页面可能不是最新内容，请点击右上角刷新</div>
<div class="tip">💡 点 ▶ 开始语音朗读，键盘空格键可暂停/继续</div>
<div class="header">
<h1>📰 全球金融市场日报</h1>
<div class="date" id="reportDate">__DATE__</div>
<button class="refresh-btn" id="refreshBtn" onclick="location.reload(true)">🔄 刷新</button>
</div>
<div class="article" id="articleContent">
__CONTENT__
</div>
<div class="player"><div class="player-row">
<button class="btn btn-sm" id="btnPrev">⏮</button>
<button class="btn btn-sm" id="btnSkipBack">⏪</button>
<button class="btn btn-play" id="btnPlay">▶</button>
<button class="btn btn-sm" id="btnSkipFwd">⏩</button>
<button class="btn btn-sm" id="btnNext">⏭</button>
<span class="voice-btn" id="voiceLabel" title="点击切换朗读音色">🎙️</span>
<span class="speed" id="speedLabel">1×</span>
<div class="progress"><div class="progress-fill" id="progressFill"></div></div>
</div></div>
<div class="toast" id="toast"></div>
<script>
(function(){var a=document.getElementById("articleContent"),b=document.getElementById("btnPlay"),c=document.getElementById("progressFill"),d=document.getElementById("speedLabel"),e=document.getElementById("toast"),vl=document.getElementById("voiceLabel"),f=[],g=0,h=!1,i=1,j=null,k=null,m=[],n=0,o=null;
function P(){m=speechSynthesis.getVoices().filter(function(q){return q.lang.indexOf("zh")===0});if(m.length>0){n=parseInt(localStorage.getItem("ttsVoiceIdx")||"0");if(n>=m.length)n=0;o=m[n];vl.textContent=o.name.length>6?o.name.slice(0,6)+"…":o.name;vl.classList.add("has-voices");vl.title="当前: "+o.name+"（点击切换）"}else{o=null;vl.textContent="🎙️";vl.title="未检测到中文语音"}}
speechSynthesis.addEventListener("voiceschanged",P);P();
vl.addEventListener("click",function(){if(m.length<2)return;n=(n+1)%m.length;o=m[n];vl.textContent=o.name.length>6?o.name.slice(0,6)+"…":o.name;vl.title="当前: "+o.name+"（点击切换）";try{localStorage.setItem("ttsVoiceIdx",String(n))}catch(_){}if(h){if(j){j.onend=null;j.onerror=null}speechSynthesis.cancel();j=null;document.querySelectorAll(".speak-active").forEach(function(q){q.classList.remove("speak-active")});t(g)}});
function l(q){e.textContent=q;e.classList.add("show");clearTimeout(k);k=setTimeout(function(){e.classList.remove("show")},2000)}
function p(){var q=document.createTreeWalker(a,NodeFilter.SHOW_TEXT,{acceptNode:function(r){var s=r.textContent.trim();if(!s)return NodeFilter.FILTER_REJECT;var t=r.parentElement;while(t&&t!==a){if(["SCRIPT","STYLE","CODE","PRE"].indexOf(t.tagName)>=0)return NodeFilter.FILTER_REJECT;t=t.parentElement}return NodeFilter.FILTER_ACCEPT}});f=[];while(q.nextNode()){var u=q.currentNode.textContent.trim();if(u.length>=2)f.push({node:q.currentNode,text:u})}g=0}
function t(q){if(q<0||q>=f.length)return;if(j){j.onend=null;j.onerror=null}speechSynthesis.cancel();j=null;var r=f[q];j=new SpeechSynthesisUtterance(r.text);j.lang="zh-CN";j.rate=i;j.pitch=1;if(o)j.voice=o;document.querySelectorAll(".speak-active").forEach(function(s){s.classList.remove("speak-active")});var u=r.node.parentElement;if(u&&u!==a){u.classList.add("speak-active");u.scrollIntoView({behavior:"smooth",block:"center"})}
j.onend=function(){document.querySelectorAll(".speak-active").forEach(function(s){s.classList.remove("speak-active")});g++;var s=f.length>0?Math.round(g/f.length*100):0;c.style.width=s+"%";if(g<f.length&&h)t(g);else if(g>=f.length){h=!1;b.textContent="▶";l("✅ 朗读完成")}};j.onerror=function(s){if(s.error!=="interrupted"&&s.error!=="canceled")console.warn(s.error)};speechSynthesis.speak(j);c.style.width=f.length>0?Math.round(g/f.length*100)+"%":"0%"}
function C(){if(f.length===0)p();if(f.length===0){l("⚠️ 暂无可朗读内容");return}if(speechSynthesis.paused)speechSynthesis.resume();else if(!speechSynthesis.speaking)t(g);h=!0;b.textContent="⏸"}
function D(){speechSynthesis.pause();h=!1;b.textContent="▶"}
function E(){if(j){j.onend=null;j.onerror=null}speechSynthesis.cancel();j=null;document.querySelectorAll(".speak-active").forEach(function(q){q.classList.remove("speak-active")});h=!1;b.textContent="▶";g=0;c.style.width="0"}
function F(){if(j){j.onend=null;j.onerror=null}speechSynthesis.cancel();j=null;document.querySelectorAll(".speak-active").forEach(function(q){q.classList.remove("speak-active")});g=Math.min(g+1,f.length-1);c.style.width=f.length>0?Math.round(g/f.length*100)+"%":"0%";if(h)t(g)}
function G(){if(j){j.onend=null;j.onerror=null}speechSynthesis.cancel();j=null;document.querySelectorAll(".speak-active").forEach(function(q){q.classList.remove("speak-active")});g=Math.max(g-1,0);c.style.width=f.length>0?Math.round(g/f.length*100)+"%":"0%";if(h)t(g)}
b.addEventListener("click",function(){h?D():C()});document.getElementById("btnNext").addEventListener("click",function(){if(j){j.onend=null;j.onerror=null}speechSynthesis.cancel();j=null;document.querySelectorAll(".speak-active").forEach(function(q){q.classList.remove("speak-active")});g=Math.min(g+3,f.length-1);c.style.width=f.length>0?Math.round(g/f.length*100)+"%":"0%";if(h)t(g)});document.getElementById("btnPrev").addEventListener("click",function(){if(j){j.onend=null;j.onerror=null}speechSynthesis.cancel();j=null;document.querySelectorAll(".speak-active").forEach(function(q){q.classList.remove("speak-active")});g=Math.max(g-3,0);c.style.width=f.length>0?Math.round(g/f.length*100)+"%":"0%";if(h)t(g)});document.getElementById("btnSkipFwd").addEventListener("click",F);document.getElementById("btnSkipBack").addEventListener("click",G);d.addEventListener("click",function(){var q=[0.75,1,1.25,1.5];var r=q.indexOf(i);i=q[(r+1)%q.length];d.textContent=i+"×";if(h&&speechSynthesis.speaking){if(j){j.onend=null;j.onerror=null}speechSynthesis.cancel();j=null;document.querySelectorAll(".speak-active").forEach(function(s){s.classList.remove("speak-active")});t(g)}});
document.addEventListener("keydown",function(q){if(q.target.tagName==="INPUT"||q.target.tagName==="TEXTAREA")return;if(q.key===" "){q.preventDefault();h?D():C()}else if(q.key==="ArrowRight")F();else if(q.key==="ArrowLeft")G();else if(q.key==="Escape")E()});
p();b.addEventListener("touchstart",function(){var q=new SpeechSynthesisUtterance("");q.volume=0;speechSynthesis.speak(q)},{once:!0});setInterval(function(){if(h&&!speechSynthesis.speaking&&!speechSynthesis.pending&&g<f.length)t(g)},4000);
window.addEventListener("beforeunload",function(){if(j){j.onend=null;j.onerror=null}speechSynthesis.cancel()});
(function(){var q=document.getElementById("reportDate");if(!q)return;var r=q.textContent.match(/(\d{4})年(\d{1,2})月(\d{1,2})日/);if(!r)return;var s=new Date(r[1],r[2]-1,r[3]);var t=new Date();t.setHours(0,0,0,0);if(s<t){document.getElementById("staleBanner").classList.add("show");document.getElementById("refreshBtn").classList.add("show")}})();
})();
</script>
</body>
</html>
'''


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
    """表格 → 自然叙述文本"""
    if len(rows) < 2:
        return ""
    headers = [h.replace('**', '') for h in rows[0]]
    data_rows = rows[1:]
    first_header = headers[0] if headers else ""
    all_headers = " ".join(headers)

    # ── 估值表（含 PE/PB/估值）──
    if any(kw in all_headers for kw in ['PE', 'PB', '估值', '市盈率', '市净率']):
        parts = []
        for row in data_rows:
            if len(row) < 2: continue
            name = row[0].replace('**', '')
            pe = _safe(row[1]) if len(row) > 1 else None
            pb = _safe(row[2]) if len(row) > 2 else None
            pos = _safe(row[3]) if len(row) > 3 else None
            details = []
            if pe: details.append(f"市盈率{pe}倍")
            if pb: details.append(f"市净率{pb}倍")
            if pos: details.append(f"估值分位处于{pos}")
            if details:
                parts.append(f"{name}，{'，'.join(details)}")
        return "。".join(parts) + "。"

    # ── 恐慌指数（VIX/VXN）──
    if ("指数" in first_header and len(headers) >= 3
            and any(kw in headers[2] for kw in ['解读', '状态', '区间'])):
        sentences = []
        for row in data_rows:
            if len(row) < 2: continue
            name = row[0].replace('**', '')
            val = _safe(row[1]) if len(row) > 1 else None
            desc = _safe(row[2]) if len(row) > 2 else None
            if val and desc:
                sentences.append(f"{name}报{val}，处于{desc}")
            elif val:
                sentences.append(f"{name}报{val}")
        if sentences:
            return "。".join(sentences) + "。"

    # ── QDII/ETF溢价表 ──
    if any(kw in all_headers for kw in ['ETF代码', '溢价率']):
        parts = []
        for row in data_rows:
            if len(row) < 2: continue
            name = row[0].replace('**', '')
            code = _safe(row[1]) if len(row) > 1 else None
            premium = _safe(row[2]) if len(row) > 2 else None
            text_parts = [name]
            if code: text_parts.append(f"代码{code}")
            if premium: text_parts.append(f"溢价率{_clean(premium)}")
            if len(text_parts) > 1:
                parts.append("，".join(text_parts))
        if parts:
            return "。".join(parts) + "。"

    # ── 场外基金表（代码 + 名称 + 净值）──
    if (len(headers) >= 3 and '代码' in first_header
            and any(kw in headers[1] for kw in ['名称', '基金'])
            and any(kw in all_headers for kw in ['净值', '涨跌'])):
        parts = []
        for row in data_rows:
            if len(row) < 3: continue
            code = row[0].replace('**', '')
            fname = _safe(row[1])
            nav = _safe(row[2]) if len(row) > 2 else None
            change = _safe(row[3]) if len(row) > 3 else None
            text = fname if fname else code
            if code and fname:
                text = f"{fname}（{code}）"
            if nav: text += f"，净值{nav}"
            if change: text += f"，近一周{_clean(change)}"
            if nav or change: parts.append(text)
        if parts:
            return "。".join(parts) + "。"

    # ── 个股持仓表 ──
    if any(kw in first_header for kw in ['持仓', '标的']):
        parts = []
        for row in data_rows:
            if len(row) < 2: continue
            name = row[0].replace('**', '')
            val = _safe(row[1]) if len(row) > 1 else None
            change = _safe(row[2]) if len(row) > 2 else None
            text = name
            if val: text += f"，价格{val}"
            if change: text += f"，{_clean(change)}"
            if val or change: parts.append(text)
        if parts:
            return "。".join(parts) + "。"

    # ── 指数收盘表（A股/美股指数）──
    if any(kw in first_header for kw in ['指数', '标的']):
        sentences = []
        for row in data_rows:
            if len(row) < 2: continue
            name = row[0].replace('**', '')
            val = _safe(row[1]) if len(row) > 1 else None
            change = _safe(row[2]) if len(row) > 2 else None
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
    # arrow → text first (before bold wrapping)
    text = re.sub(r'↑([\d.]+%?)', r'<span class="up">上涨\1</span>', text)
    text = re.sub(r'↓([\d.]+%?)', r'<span class="down">下跌\1</span>', text)
    # standalone arrows without numbers
    text = re.sub(r'(?<!上涨)(?<!下跌)↑(?![\d.])', '上涨', text)
    text = re.sub(r'(?<!上涨)(?<!下跌)↓(?![\d.])', '下跌', text)
    # bold
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    # 保护已生成的标签
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


def md_to_html(text):
    """Markdown → 纯文本叙述 HTML（表格全部转为段落文字）"""
    lines = text.split('\n')
    out = []
    in_table = False
    table_lines = []
    in_list = False
    list_type = 'ul'
    in_quote = False
    first_para = True  # 首段不缩进

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

        # 标题
        if stripped.startswith('### '):
            flush_quote(); flush_table(); flush_list()
            out.append(f'<h3>{_inline(stripped[4:])}</h3>')
        elif stripped.startswith('## '):
            flush_quote(); flush_table(); flush_list()
            out.append(f'<h2>{_inline(stripped[3:])}</h2>')
        elif stripped.startswith('# '):
            flush_quote(); flush_table(); flush_list()
            out.append(f'<h1>{_inline(stripped[2:])}</h1>')

        # 引用
        elif stripped.startswith('> '):
            flush_list(); flush_table()
            if not in_quote:
                out.append('<blockquote>')
                in_quote = True
            out.append(f'<p class="no-indent">{_inline(stripped[2:])}</p>')

        # 表格 → 转为文字段落
        elif stripped.startswith('|'):
            flush_list(); flush_quote()
            table_lines.append(stripped)
            in_table = True

        # 无序列表
        elif stripped.startswith('- '):
            flush_table(); flush_quote()
            if not in_list:
                out.append('<ul>')
                list_type = 'ul'; in_list = True
            out.append(f'<li>{_inline(stripped[2:])}</li>')

        # 有序列表
        elif re.match(r'^\d+\.\s', stripped):
            flush_table(); flush_quote()
            if not in_list:
                out.append('<ol>')
                list_type = 'ol'; in_list = True
            content = re.sub(r'^\d+\.\s', '', stripped)
            out.append(f'<li>{_inline(content)}</li>')

        # 水平线
        elif stripped in ('---', '***', '___'):
            flush_quote(); flush_table(); flush_list()
            out.append('<hr>')

        # 普通段落
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
    else:
        date_str = datetime.datetime.now().strftime('%Y年%m月%d日')

    html_content = md_to_html(md_text)
    html_output = TEMPLATE.replace('__DATE__', date_str).replace('__CONTENT__', html_content)

    with open(html_file, 'w', encoding='utf-8') as f:
        f.write(html_output)

    tables_converted = html_output.count('table-text')
    print(f"✅ 生成朗读用 HTML: {html_file} ({len(html_output)} 字节, {tables_converted} 段表格叙述)")


if __name__ == '__main__':
    main()
