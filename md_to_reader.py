#!/usr/bin/env python3
"""把 Markdown 日报转为朗读优化 HTML"""
import sys, re, os, datetime

TEMPLATE = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>全球金融市场日报</title>
<style>
:root{--bg:#f8f9fa;--card:#fff;--text:#1a1a2e;--sub:#6b7280;--border:#e5e7eb;--accent:#2563eb;--highlight:#fef3c7;--active:#dbeafe;--table-head:#f1f5f9}
@media(prefers-color-scheme:dark){:root{--bg:#0f172a;--card:#1e293b;--text:#e2e8f0;--sub:#94a3b8;--border:#334155;--accent:#3b82f6;--highlight:#3d2e00;--active:#1e3a5f;--table-head:#1e293b}}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;background:var(--bg);color:var(--text);font-size:16px;line-height:1.75;min-height:100dvh;padding:0 0 120px;-webkit-text-size-adjust:100%}
.tip{background:#fef3c7;color:#92400e;font-size:13px;padding:8px 14px;text-align:center;border-bottom:1px solid #fde68a}
@media(prefers-color-scheme:dark){.tip{background:#422006;color:#fde68a;border-color:#78350f}}
.header{background:var(--card);border-bottom:1px solid var(--border);padding:18px 16px;text-align:center;position:relative}
.header h1{font-size:20px;font-weight:700;margin-bottom:4px}
.header .date{font-size:13px;color:var(--sub);margin-bottom:8px}
.mode-toggle{display:inline-flex;align-items:center;gap:6px;background:var(--bg);border:1px solid var(--border);border-radius:20px;padding:6px 16px;font-size:13px;color:var(--sub);cursor:pointer;transition:all .15s}
.mode-toggle.active{background:var(--accent);color:#fff;border-color:var(--accent)}
.refresh-btn{position:absolute;right:16px;top:12px;background:var(--accent);color:#fff;border:none;padding:6px 14px;border-radius:20px;font-size:13px;cursor:pointer;display:none}
.refresh-btn.show{display:block}
.stale-banner{background:#fef3c7;color:#92400e;font-size:13px;padding:6px 14px;text-align:center;display:none}
.stale-banner.show{display:block}
@media(prefers-color-scheme:dark){.stale-banner{background:#422006;color:#fde68a}}
.article{max-width:720px;margin:0 auto;padding:16px}
.article h2{font-size:18px;margin:28px 0 12px;padding-bottom:6px;border-bottom:2px solid var(--accent);display:inline-block}
.article h3{font-size:16px;margin:18px 0 8px;color:var(--accent)}
.article h4{font-size:15px;margin:14px 0 6px}
.article p{margin:8px 0}
/* 表格样式 */
.article table{width:100%;border-collapse:collapse;margin:10px 0 16px;font-size:14px;border-radius:8px;overflow:hidden}
.article th{background:var(--table-head);font-weight:600;text-align:left;padding:8px 10px;font-size:13px;color:var(--sub);border-bottom:2px solid var(--border)}
.article td{padding:8px 10px;border-bottom:1px solid var(--border)}
.article tr:last-child td{border-bottom:none}
/* 朗读模式：隐藏表格，显示文字版 */
.read-mode table{display:none}
.tts-text{display:none;margin:10px 0;padding:10px 14px;background:var(--table-head);border-radius:8px;font-size:15px;line-height:1.9;color:var(--text)}
.read-mode .tts-text{display:block}
/* 通用 */
.article strong{color:var(--accent);font-weight:700}
.article blockquote{border-left:3px solid var(--accent);padding:8px 14px;margin:10px 0;background:var(--table-head);border-radius:0 8px 8px 0;color:var(--sub);font-size:14px}
.article ul,.article ol{padding-left:22px;margin:8px 0}
.article li{margin:4px 0}
.article hr{border:none;border-top:1px solid var(--border);margin:20px 0}
.up{color:#059669;font-weight:600} .down{color:#dc2626;font-weight:600}
@media(prefers-color-scheme:dark){.up{color:#34d399}.down{color:#f87171}}
.speak-active{background:var(--active)!important;border-radius:6px;padding:2px 8px;margin:-2px -8px;display:inline-block;transition:background .2s}
.player{position:fixed;bottom:0;left:0;right:0;z-index:200;background:var(--card);border-top:1px solid var(--border);padding:10px 16px max(10px,env(safe-area-inset-bottom,10px));box-shadow:0 -2px 12px rgba(0,0,0,.08)}
.player-row{display:flex;align-items:center;gap:10px;max-width:500px;margin:0 auto}
.btn{width:44px;height:44px;border-radius:50%;border:none;font-size:20px;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:all .15s;-webkit-tap-highlight-color:transparent;background:var(--bg);color:var(--text);border:1px solid var(--border)}
.btn:active{transform:scale(.94)}
.btn-play{width:56px;height:56px;font-size:24px;background:var(--accent);color:#fff;border:none;box-shadow:0 3px 10px rgba(37,99,235,.3)}
.btn-sm{width:36px;height:36px;font-size:16px}
.speed{font-size:12px;color:var(--sub);min-width:32px;text-align:center;cursor:pointer;padding:4px 0;user-select:none}
.progress{flex:1;height:4px;background:var(--border);border-radius:2px;overflow:hidden}
.progress-fill{height:100%;background:var(--accent);border-radius:2px;width:0;transition:width .2s linear}
.toast{position:fixed;top:12px;left:50%;transform:translateX(-50%);background:#1f2937;color:#fff;padding:8px 20px;border-radius:20px;font-size:14px;z-index:300;pointer-events:none;opacity:0;transition:opacity .25s}
.toast.show{opacity:1}
@media(prefers-color-scheme:dark){.toast{background:#374151}}
</style>
</head>
<body>
<div class="stale-banner" id="staleBanner">⚠️ 页面可能不是最新内容，请点击右上角刷新</div>
<div class="tip">💡 点击 🎧 朗读模式 切换语音友好版本，再点 ▶ 开始播放</div>
<div class="header">
<h1>📰 全球金融市场日报</h1>
<div class="date" id="reportDate">__DATE__</div>
<button class="mode-toggle" id="modeToggle" onclick="toggleReadMode()">🎧 朗读模式</button>
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
<span class="speed" id="speedLabel">1×</span>
<div class="progress"><div class="progress-fill" id="progressFill"></div></div>
</div></div>
<div class="toast" id="toast"></div>
<script>
function toggleReadMode(){
  var a=document.getElementById("articleContent");
  var b=document.getElementById("modeToggle");
  a.classList.toggle("read-mode");
  b.classList.toggle("active");
  b.textContent=a.classList.contains("read-mode")?"🎧 浏览模式":"🎧 朗读模式";
  // Stop current speech if any
  speechSynthesis.cancel();
  document.getElementById("btnPlay").textContent="▶";
  document.querySelectorAll(".speak-active").forEach(function(e){e.classList.remove("speak-active")});
}
(function(){var a=document.getElementById("articleContent"),b=document.getElementById("btnPlay"),c=document.getElementById("progressFill"),d=document.getElementById("speedLabel"),e=document.getElementById("toast"),f=[],g=0,h=!1,i=1,j=null,k=null;
function l(m){e.textContent=m;e.classList.add("show");clearTimeout(k);k=setTimeout(function(){e.classList.remove("show")},2000)}
function n(){var m=document.createTreeWalker(a,NodeFilter.SHOW_TEXT,{acceptNode:function(o){var p=o.textContent.trim();if(!p)return NodeFilter.FILTER_REJECT;var q=o.parentElement;while(q&&q!==a){if(["SCRIPT","STYLE","CODE","PRE"].indexOf(q.tagName)>=0)return NodeFilter.FILTER_REJECT;q=q.parentElement}return NodeFilter.FILTER_ACCEPT}});f=[];var r={};while(m.nextNode()){var s=m.currentNode.textContent.trim();if(s.length>=4&&!r[s]){r[s]=!0;f.push({node:m.currentNode,text:s})}}g=0}
function t(u){if(u<0||u>=f.length)return;if(j){j.onend=null;j.onerror=null}speechSynthesis.cancel();j=null;var v=f[u];j=new SpeechSynthesisUtterance(v.text);j.lang="zh-CN";j.rate=i;j.pitch=1;var w=document.querySelectorAll(".speak-active");for(var x=0;x<w.length;x++)w[x].classList.remove("speak-active");var y=v.node.parentElement;if(y&&y!==a){y.classList.add("speak-active");y.scrollIntoView({behavior:"smooth",block:"center"})}
j.onend=function(){var z=document.querySelectorAll(".speak-active");for(var A=0;A<z.length;A++)z[A].classList.remove("speak-active");g++;var B=f.length>0?Math.round(g/f.length*100):0;c.style.width=B+"%";if(g<f.length&&h)t(g);else if(g>=f.length){h=!1;b.textContent="▶";l("✅ 朗读完成")}};j.onerror=function(B){if(B.error!=="interrupted"&&B.error!=="canceled")console.warn(B.error)};speechSynthesis.speak(j);var B=f.length>0?Math.round(g/f.length*100):0;c.style.width=B+"%"}
function C(){if(f.length===0)n();if(f.length===0){l("⚠️ 暂无可朗读内容");return}if(speechSynthesis.paused)speechSynthesis.resume();else if(!speechSynthesis.speaking)t(g);h=!0;b.textContent="⏸"}
function D(){speechSynthesis.pause();h=!1;b.textContent="▶"}
function E(){if(j){j.onend=null;j.onerror=null}speechSynthesis.cancel();j=null;document.querySelectorAll(".speak-active").forEach(function(m){m.classList.remove("speak-active")});h=!1;b.textContent="▶";g=0;c.style.width="0"}
function F(){if(j){j.onend=null;j.onerror=null}speechSynthesis.cancel();j=null;document.querySelectorAll(".speak-active").forEach(function(m){m.classList.remove("speak-active")});g=Math.min(g+1,f.length-1);var m=f.length>0?Math.round(g/f.length*100):0;c.style.width=m+"%";if(h)t(g)}
function G(){if(j){j.onend=null;j.onerror=null}speechSynthesis.cancel();j=null;document.querySelectorAll(".speak-active").forEach(function(m){m.classList.remove("speak-active")});g=Math.max(g-1,0);var m=f.length>0?Math.round(g/f.length*100):0;c.style.width=m+"%";if(h)t(g)}
b.addEventListener("click",function(){h?D():C()});document.getElementById("btnNext").addEventListener("click",function(){if(j){j.onend=null;j.onerror=null}speechSynthesis.cancel();j=null;document.querySelectorAll(".speak-active").forEach(function(m){m.classList.remove("speak-active")});g=Math.min(g+3,f.length-1);var m=f.length>0?Math.round(g/f.length*100):0;c.style.width=m+"%";if(h)t(g)});document.getElementById("btnPrev").addEventListener("click",function(){if(j){j.onend=null;j.onerror=null}speechSynthesis.cancel();j=null;document.querySelectorAll(".speak-active").forEach(function(m){m.classList.remove("speak-active")});g=Math.max(g-3,0);var m=f.length>0?Math.round(g/f.length*100):0;c.style.width=m+"%";if(h)t(g)});document.getElementById("btnSkipFwd").addEventListener("click",F);document.getElementById("btnSkipBack").addEventListener("click",G);d.addEventListener("click",function(){var m=[0.75,1,1.25,1.5];var o=m.indexOf(i);i=m[(o+1)%m.length];d.textContent=i+"×";if(h&&speechSynthesis.speaking){if(j){j.onend=null;j.onerror=null}speechSynthesis.cancel();j=null;document.querySelectorAll(".speak-active").forEach(function(p){p.classList.remove("speak-active")});t(g)}});
document.addEventListener("keydown",function(m){if(m.target.tagName==="INPUT"||m.target.tagName==="TEXTAREA")return;if(m.key===" "){m.preventDefault();h?D():C()}else if(m.key==="ArrowRight")F();else if(m.key==="ArrowLeft")G();else if(m.key==="Escape")E()});
n();b.addEventListener("touchstart",function(){var m=new SpeechSynthesisUtterance("");m.volume=0;speechSynthesis.speak(m)},{once:!0});setInterval(function(){if(h&&!speechSynthesis.speaking&&!speechSynthesis.pending&&g<f.length)t(g)},4000);
window.addEventListener("beforeunload",function(){if(j){j.onend=null;j.onerror=null}speechSynthesis.cancel()});
(function(){var r=document.getElementById("reportDate");if(!r)return;var m=r.textContent.match(/(\d{4})年(\d{1,2})月(\d{1,2})日/);if(!m)return;var rd=new Date(m[1],m[2]-1,m[3]);var td=new Date();td.setHours(0,0,0,0);if(rd<td){document.getElementById("staleBanner").classList.add("show");document.getElementById("refreshBtn").classList.add("show")}})();
})();
</script>
</body>
</html>
'''


def _extract_table_data(table_lines):
    """从 markdown 表格行提取数据"""
    rows = []
    for line in table_lines:
        line = line.strip()
        if not line.startswith('|'):
            continue
        cells = [c.strip() for c in line.strip('|').split('|')]
        # 跳过分隔行
        if all(re.match(r'^[-:]+$', c) for c in cells):
            continue
        rows.append(cells)
    return rows


def _table_to_text(rows, section_name=""):
    """将表格数据转为朗读友好的叙述文本"""
    if len(rows) < 2:
        return ""
    
    headers = rows[0]
    data_rows = rows[1:]
    
    # 检测表格类型并生成对应文本
    first_header = headers[0] if headers else ""
    all_headers = " ".join(headers)
    
    # 估值表格（headers 含 PE/PB/估值）—— 必须最先检查
    if any(kw in all_headers for kw in ['PE', 'PB', '估值', '市盈率', '市净率']):
        parts = []
        for row in data_rows:
            if len(row) < 2: continue
            name = row[0].replace('**', '')
            pe = _safe(row[1]) if len(row) > 1 else None
            pb = _safe(row[2]) if len(row) > 2 else None
            pos = _safe(row[3]) if len(row) > 3 else None
            text = name
            if pe: text += f"市盈率{pe}"
            if pb: text += f"，市净率{pb}"
            if pos: text += f"，估值处于{pos}"
            if text != name: parts.append(text)
        return "。".join(parts) + "。" if parts else ""

    # QDII/ETF溢价表格（headers 含 ETF代码/溢价）
    if any(kw in all_headers for kw in ['ETF代码', '溢价率']):
        parts = []
        for row in data_rows:
            if len(row) < 2: continue
            name = row[0].replace('**', '')
            val = _safe(row[1]) if len(row) > 1 else None
            extra = _safe(row[2]) if len(row) > 2 else None
            text = name
            if val: text += f"，{val}"
            if extra: text += f"，{extra}"
            parts.append(text)
        return "。".join(parts) + "。" if parts else ""

    # 持仓表格
    if any(kw in first_header for kw in ['持仓', '标的', '代码']):
        parts = []
        for row in data_rows:
            if len(row) < 2: continue
            name = row[0].replace('**', '')
            val = _safe(row[1]) if len(row) > 1 else None
            change = _safe(row[2]) if len(row) > 2 else None
            text = name
            if val: text += f"，当前价格{val}"
            if change: text += f"，{_clean(change)}"
            if val or change: parts.append(text)
        return "。".join(parts) + "。" if parts else ""

    # 指数收盘表格（如 A 股/美股指数、恐慌指数）
    if any(kw in first_header for kw in ['指数', '标的']):
        sentences = []
        for row in data_rows:
            if len(row) < 2:
                continue
            name = row[0].replace('**', '')
            val = _safe(row[1]) if len(row) > 1 else None
            change = _safe(row[2]) if len(row) > 2 else None
            # 恐慌指数：数值 → 解读
            extra = _safe(row[3]) if len(row) > 3 else None
            
            if val and change:
                c = _clean(change)
                # 如果 val 是描述性文字（如"盘中创新高后回落"），直接嵌入
                if len(val) > 10:
                    sentences.append(f"{name}{val}，{c}")
                else:
                    sentences.append(f"{name}报收{val}，{c}")
            elif val and extra:
                # 恐慌指数格式：指数 + 数值 + 解读
                sentences.append(f"{name}{val}，处于{extra}")
            elif val:
                sentences.append(f"{name}报收{val}")
            elif change:
                c = _clean(change)
                sentences.append(f"{name}{c}")
            # 跳过全空行
        if sentences:
            return "。".join(sentences) + "。"
        return ""

    # 通用表格
    parts = []
    for row in data_rows:
        sentence_parts = []
        for i, cell in enumerate(row):
            v = _safe(cell)
            if v and i < len(headers):
                h = headers[i].replace('**', '')
                sentence_parts.append(f"{h}：{v}")
        if sentence_parts:
            parts.append("，".join(sentence_parts))
    if parts:
        return "。".join(parts) + "。"
    return ""


def _clean(text):
    """清理文本中的 markdown 标记，保留涨跌"""
    text = text.replace('**', '')
    text = text.replace('↑', '上涨').replace('↓', '下跌')
    return text

def _safe( val):
    """处理缺失值"""
    v = val.replace('**', '').strip()
    if not v or v in ('—', '-', '--', '...', '—', '－', '――'):
        return None
    # 如果值本身看起来不像有意义的数据（如纯标点）
    if re.match(r'^[─\-–—\s]+$', v):
        return None
    return v


def md_to_html(text):
    """Markdown → 朗读优化 HTML"""
    lines = text.split('\n')
    out = []
    in_table = False
    table_lines = []
    in_list = False
    list_type = 'ul'
    in_quote = False

    def flush_table():
        nonlocal in_table, table_lines
        if not table_lines:
            return
        rows = _extract_table_data(table_lines)
        # 生成表格 HTML
        if rows:
            out.append('<table>')
            # 表头
            out.append('<thead><tr>')
            for h in rows[0]:
                out.append(f'<th>{_inline(h)}</th>')
            out.append('</tr></thead><tbody>')
            for row in rows[1:]:
                out.append('<tr>')
                for cell in row:
                    out.append(f'<td>{_inline(cell)}</td>')
                out.append('</tr>')
            out.append('</tbody></table>')
            
            # 生成朗读版文本
            tts = _table_to_text(rows)
            if tts:
                out.append(f'<div class="tts-text">📢 {tts}</div>')
        
        table_lines = []
        in_table = False

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
            flush_quote()
            flush_table()
            flush_list()
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
            out.append(f'<p>{_inline(stripped[2:])}</p>')

        # 表格
        elif stripped.startswith('|'):
            flush_list(); flush_quote()
            table_lines.append(stripped)
            in_table = True

        # 无序列表
        elif stripped.startswith('- '):
            flush_table(); flush_quote()
            if not in_list:
                out.append('<ul>')
                list_type = 'ul'
                in_list = True
            out.append(f'<li>{_inline(stripped[2:])}</li>')

        # 有序列表
        elif re.match(r'^\d+\.\s', stripped):
            flush_table(); flush_quote()
            if not in_list:
                out.append('<ol>')
                list_type = 'ol'
                in_list = True
            content = re.sub(r'^\d+\.\s', '', stripped)
            out.append(f'<li>{_inline(content)}</li>')

        # 水平线
        elif stripped in ('---', '***', '___'):
            flush_quote(); flush_table(); flush_list()
            out.append('<hr>')

        # 普通段落
        else:
            flush_table(); flush_quote(); flush_list()
            out.append(f'<p>{_inline(stripped)}</p>')

    # 收尾
    flush_quote(); flush_table(); flush_list()

    return '\n'.join(out)


def _inline(text):
    """处理行内元素"""
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'(↑[\d.]+%?)', r'<span class="up">\1</span>', text)
    text = re.sub(r'(↓[\d.]+%?)', r'<span class="down">\1</span>', text)
    # 保护已生成的 HTML 标签
    text = text.replace('&', '&amp;')
    for tag in ['strong', 'span']:
        text = text.replace(f'&lt;{tag}', f'␂{tag}')
        text = text.replace(f'&lt;/{tag}&gt;', f'␂/{tag}␂')
    text = text.replace('<', '&lt;').replace('>', '&gt;')
    for tag in ['strong', 'span']:
        text = text.replace(f'␂{tag}', f'<{tag}')
        text = text.replace(f'␂/{tag}␂', f'</{tag}>')
    return text


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

    tts_count = html_output.count('tts-text')
    print(f"✅ 生成朗读 HTML: {html_file} ({len(html_output)} 字节, {tts_count} 个朗读段落)")


if __name__ == '__main__':
    main()
