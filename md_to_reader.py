#!/usr/bin/env python3
"""把 Markdown 日报转为纯文本叙述 HTML（适合直接朗读）"""
import sys, re, os, datetime

TEMPLATE = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
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
<div class="stale-banner" id="staleBanner"></div>
<div class="tip">💡 点 ▶ 开始语音朗读，键盘空格键可暂停/继续；检测到旧版时页面自动刷新</div>
<div class="header">
<h1>📰 全球金融市场日报</h1>
<div class="date" id="reportDate">__DATE__</div>
<button class="refresh-btn" id="refreshBtn" onclick="window.location.href=window.location.pathname+'?_='+Date.now()">🔄 刷新</button>
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
(function(){var q=document.getElementById("reportDate");if(!q)return;var r=q.textContent.match(/(\d{4})年(\d{1,2})月(\d{1,2})日/);if(!r)return;var s=new Date(r[1],r[2]-1,r[3]);var t=new Date();t.setHours(0,0,0,0);if(s<t){var b=document.getElementById("staleBanner"),btn=document.getElementById("refreshBtn");b.textContent="⏳ 已检测旧版内容，正在自动刷新...";b.classList.add("show");btn.classList.add("show");setTimeout(function(){window.location.href=window.location.pathname+"?_="+Date.now()},1500)}})();
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
        # 如果是 4 列拆分格式且有备注列，调整
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
            # PE 分位
            used_summary = False
            if pe_pct_col is not None and pe_pct_col < len(row):
                pct = _safe(row[pe_pct_col])
                if pct: details.append(f"PE分位{pct}")
            elif pos_col is not None and pos_col < len(row) and pos_col != (pb_pct_col or -1):
                pct = _safe(row[pos_col])
                if pct:
                    details.append(f"PE分位{pct}")
                    used_summary = True
            # PB 分位
            if pb_pct_col is not None and pb_pct_col < len(row):
                pct = _safe(row[pb_pct_col])
                if pct: details.append(f"PB分位{pct}")
            elif not used_summary and pos_col is not None and pos_col < len(row) and pos_col != (pe_pct_col or -1):
                pct = _safe(row[pos_col])
                if pct:
                    details.append(f"PB分位{pct}")
                    used_summary = True
            # 汇总估值结论（与已使用过的不同才输出）
            if not used_summary and pos_col is not None and pos_col < len(row):
                pos = _safe(row[pos_col])
                if pos and len(pos) < 20:
                    details.append(f"估值{pos}")
            # 备注
            if notes_col is not None and notes_col < len(row):
                note = row[notes_col].replace('**', '').strip()
                if note and not any(kw in all_headers for kw in ['备注']):
                    pass
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


def md_to_html(text):
    """Markdown → 纯文本叙述 HTML（表格全部转为段落文字）"""
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
