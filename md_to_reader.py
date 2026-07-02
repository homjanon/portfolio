#!/usr/bin/env python3
"""把 Markdown 日报转为自包含朗读 HTML"""
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
.header .date{font-size:13px;color:var(--sub)}
.refresh-btn{position:absolute;right:16px;top:50%;transform:translateY(-50%);background:var(--accent);color:#fff;border:none;padding:8px 14px;border-radius:20px;font-size:13px;cursor:pointer;display:none;transition:all .15s}
.refresh-btn.show{display:block}
.refresh-btn:active{transform:translateY(-50%) scale(.95)}
.stale-banner{background:#fef3c7;color:#92400e;font-size:13px;padding:6px 14px;text-align:center;display:none}
.stale-banner.show{display:block}
@media(prefers-color-scheme:dark){.stale-banner{background:#422006;color:#fde68a}}
.article{max-width:720px;margin:0 auto;padding:16px}
.article h2{font-size:18px;margin:28px 0 12px;padding-bottom:6px;border-bottom:2px solid var(--accent);display:inline-block}
.article h3{font-size:16px;margin:18px 0 8px;color:var(--accent)}
.article h4{font-size:15px;margin:14px 0 6px}
.article p{margin:8px 0}
.article table{width:100%;border-collapse:collapse;margin:10px 0 16px;font-size:14px;border-radius:8px;overflow:hidden}
.article th{background:var(--table-head);font-weight:600;text-align:left;padding:8px 10px;font-size:13px;color:var(--sub);border-bottom:2px solid var(--border)}
.article td{padding:8px 10px;border-bottom:1px solid var(--border)}
.article tr:last-child td{border-bottom:none}
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
<div class="tip">💡 在浏览器中打开此页即可朗读（微信内长按 → 在浏览器中打开）</div>
<div class="stale-banner" id="staleBanner">⚠️ 页面可能不是最新内容，请点击刷新</div>
<div class="header"><h1>📰 全球金融市场日报</h1><div class="date">__DATE__</div><button class="refresh-btn" id="refreshBtn" onclick="location.reload(true)">🔄 刷新</button></div>
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
n();b.addEventListener("touchstart",function(){var m=new SpeechSynthesisUtterance("");m.volume=0;speechSynthesis.speak(m)},{once:!0});setInterval(function(){if(h&&!speechSynthesis.speaking&&!speechSynthesis.pending&&g<f.length)t(g)},4000);window.addEventListener("beforeunload",function(){if(j){j.onend=null;j.onerror=null}speechSynthesis.cancel()});
(function(){var r=document.getElementById("reportDate");if(!r)return;var m=r.textContent.match(/(\d{4})年(\d{1,2})月(\d{1,2})日/);if(!m)return;var rd=new Date(m[1],m[2]-1,m[3]);var td=new Date();td.setHours(0,0,0,0);if(rd<td){document.getElementById("staleBanner").classList.add("show");document.getElementById("refreshBtn").classList.add("show")}})();
})();
</script>
</body>
</html>
'''


def md_to_html(text):
    """极简 Markdown → HTML 转换"""
    lines = text.split('\n')
    out = []
    in_table = False
    in_list = False
    in_quote = False

    for line in lines:
        stripped = line.strip()

        # 跳过空行
        if not stripped:
            if in_quote:
                out.append('</blockquote>')
                in_quote = False
            if in_table:
                out.append('</tbody></table>')
                in_table = False
            if in_list:
                out.append('</ul>')
                in_list = False
            continue

        # 标题
        if stripped.startswith('### '):
            if in_quote: out.append('</blockquote>'); in_quote = False
            if in_table: out.append('</tbody></table>'); in_table = False
            if in_list: out.append('</ul>'); in_list = False
            out.append(f'<h3>{_inline(stripped[4:])}</h3>')
        elif stripped.startswith('## '):
            if in_quote: out.append('</blockquote>'); in_quote = False
            if in_table: out.append('</tbody></table>'); in_table = False
            if in_list: out.append('</ul>'); in_list = False
            out.append(f'<h2>{_inline(stripped[3:])}</h2>')
        elif stripped.startswith('# '):
            if in_quote: out.append('</blockquote>'); in_quote = False
            if in_table: out.append('</tbody></table>'); in_table = False
            if in_list: out.append('</ul>'); in_list = False
            out.append(f'<h1>{_inline(stripped[2:])}</h1>')

        # 引用
        elif stripped.startswith('> '):
            if in_list: out.append('</ul>'); in_list = False
            if in_table: out.append('</tbody></table>'); in_table = False
            if not in_quote:
                out.append('<blockquote>')
                in_quote = True
            out.append(f'<p>{_inline(stripped[2:])}</p>')

        # 表格
        elif stripped.startswith('|'):
            if in_list: out.append('</ul>'); in_list = False
            if in_quote: out.append('</blockquote>'); in_quote = False
            cells = [c.strip() for c in stripped.strip('|').split('|')]
            # 跳过分隔行
            if all(re.match(r'^[-:]+$', c) for c in cells):
                continue
            if not in_table:
                out.append('<table><thead><tr>')
                for c in cells:
                    out.append(f'<th>{_inline(c)}</th>')
                out.append('</tr></thead><tbody>')
                in_table = True
                in_table_header = True
            else:
                out.append('<tr>')
                for c in cells:
                    out.append(f'<td>{_inline(c)}</td>')
                out.append('</tr>')

        # 无序列表
        elif stripped.startswith('- '):
            if in_table: out.append('</tbody></table>'); in_table = False
            if in_quote: out.append('</blockquote>'); in_quote = False
            if not in_list:
                out.append('<ul>')
                in_list = True
            out.append(f'<li>{_inline(stripped[2:])}</li>')

        # 有序列表
        elif re.match(r'^\d+\.\s', stripped):
            if in_table: out.append('</tbody></table>'); in_table = False
            if in_quote: out.append('</blockquote>'); in_quote = False
            if not in_list:
                out.append('<ol>')
                in_list = True
            content = re.sub(r'^\d+\.\s', '', stripped)
            out.append(f'<li>{_inline(content)}</li>')

        # 水平线
        elif stripped in ('---', '***', '___'):
            if in_table: out.append('</tbody></table>'); in_table = False
            if in_quote: out.append('</blockquote>'); in_quote = False
            if in_list: out.append('</ul>'); in_list = False
            out.append('<hr>')

        # 普通段落
        else:
            if in_table: out.append('</tbody></table>'); in_table = False
            if in_quote: out.append('</blockquote>'); in_quote = False
            if in_list: out.append('</ul>'); in_list = False
            out.append(f'<p>{_inline(stripped)}</p>')

    # 收尾
    if in_quote: out.append('</blockquote>')
    if in_table: out.append('</tbody></table>')
    if in_list: out.append('</ul>')

    return '\n'.join(out)


def _inline(text):
    """处理行内元素：粗体、涨跌箭头"""
    # 粗体 **text**
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    # 上涨 ↑ 标记
    text = re.sub(r'(↑[\d.]+%?)', r'<span class="up">\1</span>', text)
    # 下跌 ↓ 标记
    text = re.sub(r'(↓[\d.]+%?)', r'<span class="down">\1</span>', text)
    # 转义 HTML
    text = text.replace('&', '&amp;').replace('<strong>', '␂STRONG␂').replace('</strong>', '␂/STRONG␂')
    text = text.replace('<span', '␂SPAN').replace('</span>', '␂/SPAN␂')
    text = text.replace('<', '&lt;').replace('>', '&gt;')
    text = text.replace('␂STRONG␂', '<strong>').replace('␂/STRONG␂', '</strong>')
    text = text.replace('␂SPAN', '<span').replace('␂/SPAN␂', '</span>')
    return text


def main():
    if len(sys.argv) < 2:
        print("用法: python3 md_to_reader.py <input.md> [output.html]")
        sys.exit(1)

    md_file = sys.argv[1]
    html_file = sys.argv[2] if len(sys.argv) > 2 else md_file.rsplit('.', 1)[0] + '.html'

    with open(md_file, 'r', encoding='utf-8') as f:
        md_text = f.read()

    # 提取日期
    date_match = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日.*?星期([一二三四五六日])', md_text)
    if date_match:
        date_str = f'{date_match.group(1)}年{date_match.group(2)}月{date_match.group(3)}日 星期{date_match.group(4)}'
    else:
        date_str = datetime.datetime.now().strftime('%Y年%m月%d日')

    # 转换内容
    html_content = md_to_html(md_text)
    html_output = TEMPLATE.replace('__DATE__', date_str).replace('__CONTENT__', html_content)

    with open(html_file, 'w', encoding='utf-8') as f:
        f.write(html_output)

    print(f"✅ 生成朗读 HTML: {html_file} ({len(html_output)} 字节)")


if __name__ == '__main__':
    main()
