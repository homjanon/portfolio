#!/usr/bin/env python3
"""
预抓取金融市场数据 — 按板块切分为结构化 JSON 文件。
v30: 每模块120s超时机制 + QDII场外纳指100/标普500可申购大额度

输出文件（10个，均在 data_*.json，默认当前目录）：
  data_market_cn.json       A股5大指数行情           akshare新浪
  data_market_hk.json       港股恒生+国企指数         akshare新浪
  data_market_global.json   全球主要指数              akshare新浪(美股)+东财(外围)
  data_forex_rate.json      汇率/商品/中美债券        akshare期货 + 中美债收益率
  data_valuation.json       中美核心指数估值+PE/PB分位 雪球蛋卷API
  data_fund.json            基金净值+净值估算+ETF溢价  akshare天天基金
  data_industry.json        申万31行业涨跌幅+同花顺90行业资金流+全市场PE  akshare
  data_holdings.json        个人持仓+监督池行情+分红+研报  腾讯API + akshare(分红+研报)
  data_news_rss.json        全球TOP10新闻源          Google News RSS 英文+中文
  data_extra.json           资金面+QDII+涨停/跌停  akshare(汇率/资金流/QDII)  v29: 场外QDII纳指100/标普500可申购大额度

每个文件：{"ts":"...", "ok":true/false, "data":..., "error":"..."}
"""

import json, os, sys, signal, traceback, time, re, requests, xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

# ── 方案C: curl_cffi HTTP/2 补丁 ──
# 东财 push2 端点需要 HTTP/2，标准 requests 仅支持 HTTP/1.1 会静默断连
# 仅对 eastmoney push2 域名使用 curl_cffi 浏览器模拟，其余请求不受影响
try:
    from curl_cffi import requests as _cffi_req
    _orig_get = requests.get
    _H2_DOMAINS = ("push2.eastmoney.com", "push2his.eastmoney.com")
    def _patched_get(url, **kw):
        if any(d in url for d in _H2_DOMAINS):
            try:
                return _cffi_req.get(url, impersonate="chrome", **kw)
            except Exception:
                pass
        return _orig_get(url, **kw)
    requests.get = _patched_get
    print("✅ curl_cffi HTTP/2 补丁已启用（东财 push2 端点）")
except ImportError:
    print("⚠️ curl_cffi 未安装，东财全球指数可能降级到 yfinance")

# 全局抑制 tqdm 进度条，避免 GitHub Actions 日志超限
os.environ["AKSHARE_DISABLE_PROGRESS"] = "1"
os.environ["TQDM_DISABLE"] = "1"
try:
    import tqdm
    # 所有 tqdm 实例强制 disable=True
    _orig_tqdm = tqdm.tqdm
    tqdm.tqdm = lambda *a, disable=True, **kw: _orig_tqdm(*a, disable=True, **kw)
except ImportError:
    pass

OUT_DIR = os.environ.get("PREFETCH_OUT_DIR", os.getcwd())
TZ_CN = timezone(timedelta(hours=8))
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

def _ts():
    return datetime.now(TZ_CN).strftime("%Y-%m-%d %H:%M:%S")

def _ok(payload):
    return {"ts": _ts(), "ok": True, "data": payload}

def _fail(reason):
    return {"ts": _ts(), "ok": False, "error": str(reason)}

def _write(name, obj):
    path = os.path.join(OUT_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    sz = os.path.getsize(path)
    st = "✅" if obj.get("ok") else "⚠️"
    print(f"  {st} {path} ({sz} bytes)")
    return path

def _num(v):
    if v is None: return None
    try: v = float(v); return round(v, 4) if abs(v) < 1e6 else round(v, 2)
    except: return None

def _load_qdii_prev():
    """读取上一运行日的 QDII 快照（对比昨日用）。不存在/损坏返回 None。
    注意：data_*.json 被 .gitignore 排除、不跨运行留存，故独立文件 qdii_prev.json
    承担跨运行持久化职责（由 _save_qdii_snapshot 写入、工作流提交）。"""
    path = os.path.join(OUT_DIR, "qdii_prev.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def _save_qdii_snapshot(qdii_data):
    """把当日 QDII 基准存为快照，供下一运行日作为「昨天」对比基准。"""
    snap = {
        "ts": _ts(),
        "场内ETF": [{"代码": e.get("代码"), "溢价率": e.get("溢价率")}
                    for e in qdii_data.get("场内ETF", [])],
        "场外QDII": [{"代码": e.get("代码"), "日累计限定金额": e.get("日累计限定金额")}
                     for e in qdii_data.get("场外QDII", [])],
    }
    path = os.path.join(OUT_DIR, "qdii_prev.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=2)

def _shorten_qdii_name(full_name):
    """将东财场外 QDII 基金全称缩写为短名。

    统一格式：公司名 + 纳指100/标普500 + 小写份额字母(a/c/d)。
    例：建信纳斯达克100指数(QDII)C人民币 → 建信纳指100c
        大成纳斯达克100ETF联接(QDII)A人民币 → 大成纳指100a

    规则：提取份额字母(转小写) + 指数名标准化 + 清括号/ETF联接/币种后缀；
         基金公司名（易方达/建信/广发…）**完整保留，绝不缩写**。
    纯规则驱动、零硬编码映射，动态列表可复用。"""
    if not full_name:
        return ""
    s = full_name.strip()
    # ① 提取 (QDII)X / (LOF)X 份额后缀字母（任意英文份额 A/B/C/D/E…，转小写）
    _suffix = ""
    _m = re.search(r'\((?:QDII|LOF)[^)]*\)\s*([A-Za-z])', s)
    if _m:
        _suffix = _m.group(1).lower()
    # ② 指数名称标准化（带「指数」后缀优先，break 后不再重复匹配）
    #    同时覆盖裸词（如联接基金全称「纳斯达克100ETF联接」不含「指数」二字）
    _idx_map = [
        ("纳斯达克100指数", "纳指100"),
        ("纳斯达克100",     "纳指100"),
        ("标普500指数",     "标普500"),
        ("标普500",         "标普500"),
        ("纳斯达克指数",    "纳指综"),
        ("道琼斯指数",      "道指"),
    ]
    for _long, _short in _idx_map:
        if _long in s:
            s = s.replace(_long, _short)
            break
    # ③ 清理 (QDII)/(LOF) 括号 + 份额字母 + 币种后缀（一次移除）；
    #    清理 "ETF联接"/"ETF" 等多余词（东财联接基金全称含此，否则会残留导致超长）；
    #    我们的筛选已排除美元，实际仅人民币；仍兼容清理任意币种。
    #    ★ 基金公司名（易方达/建信/广发…）保持完整，不缩写
    s = re.sub(r'\s*\((?:QDII|LOF)[^)]*\)\s*[A-Za-z]?\s*(?:人民币|美元|港元)?', '', s)
    s = re.sub(r'\s*ETF\s*联接\s*', '', s)
    s = re.sub(r'\s*ETF\s*', '', s)
    s = re.sub(r'\s*指数\s*$', '', s)
    s = re.sub(r'\s+', '', s)
    # ④ 拼接份额字母（清理后均 ≤10 字符，无需截断）
    return s + _suffix

# ═══════════════════════════════════════════════════════════════
# 数据源层
# ═══════════════════════════════════════════════════════════════

# ─── 数据源A: 腾讯API（最可靠兜底，支持A股/港股/美股） ─────
def _tencent_quote(codes_str):
    """获取腾讯行情，返回 {短code: {...}}，永不抛异常。
    支持 sh/sz (A股)、hk (港股)、us (美股) 三种前缀。"""
    try:
        url = f"https://qt.gtimg.cn/q={codes_str}"
        r = requests.get(url, headers={"User-Agent": UA}, timeout=15)
        r.encoding = "gbk"
        result = {}
        for line in r.text.strip().split(";"):
            line = line.strip()
            if not line or "=" not in line: continue
            parts = line.split('"')
            if len(parts) < 2: continue
            fields = parts[1].split("~")
            if len(fields) < 35: continue
            code = fields[2]
            result[code] = {
                "name": fields[1],
                "price": _num(fields[3]),
                "prev_close": _num(fields[4]),
                "open": _num(fields[5]),
                "volume": _num(fields[6]),
                "high": _num(fields[33]),
                "low": _num(fields[34]),
                "change": _num(fields[31]),
                "change_pct": _num(fields[32]),
            }
        return result
    except:
        return {}

# ─── 数据源B: akshare 新浪系列 ──────────────────────────────
def _akshare_sina_index_spot():
    """akshare新浪A股指数行情，带重试"""
    import akshare as ak
    for attempt in range(3):
        try:
            df = ak.stock_zh_index_spot_sina()
            if df is not None and len(df) > 0:
                return df
        except:
            if attempt < 2: time.sleep(2)
    return None

def _akshare_sina_hk_index():
    """akshare新浪港股指数"""
    import akshare as ak
    for attempt in range(3):
        try:
            df = ak.stock_hk_index_spot_sina()
            if df is not None and len(df) > 0:
                return df
        except:
            if attempt < 2: time.sleep(2)
    return None

def _akshare_sina_us_index(symbol):
    """akshare新浪美股指数 (DJI/SPX/IXIC/NDX)，只取最后2天数据"""
    import akshare as ak
    try:
        df = ak.index_us_stock_sina(symbol=symbol)
        if df is not None and len(df) >= 2:
            last = df.iloc[-1]
            prev = df.iloc[-2]
            c = float(last["close"]); p = float(prev["close"])
            return {
                "close": round(c, 2),
                "prev_close": round(p, 2),
                "change_pct": round((c - p) / p * 100, 2),
                "open": float(last["open"]), "high": float(last["high"]),
                "low": float(last["low"]), "volume": int(last["volume"]),
                "date": str(last["date"]) if "date" in df.columns else None,
            }
    except:
        pass
    return None

# ─── 数据源C: akshare 东财系列（任务环境可用，沙箱可能被墙） ─
def _ak_eastmoney(func_name, **kwargs):
    """尝试执行akshare东财来源函数，失败返回None"""
    import akshare as ak
    try:
        func = getattr(ak, func_name, None)
        if func is None: return None
        df = func(**kwargs)
        time.sleep(1.5)
        return df
    except:
        return None

# ─── 数据源D: 雪球蛋卷 API（PE/PB/分位/股息率全覆盖） ────────
def _fetch_danjuan_valuation():
    """雪球蛋卷基金估值API — 返回 PE/PB/分位/股息率 全覆盖数据。
    
    API: danjuanfunds.com/djapi/index_eva/dj
    返回 63 个指数，字段: pe, pb, pe_percentile, pb_percentile, yeild(股息率), eva_type
    
    覆盖目标 6 指数:
      沪深300(SH000300), 创业板(SZ399006), 红利低波(CSIH30269),
      恒生科技(HKHSTECH), 标普500(SP500), 中证红利(SH000922)
    """
    try:
        r = requests.get("https://danjuanfunds.com/djapi/index_eva/dj",
                        headers={"User-Agent": UA}, timeout=10)
        items = r.json()["data"]["items"]
        
        targets = {
            "SH000300":  "沪深300",
            "SZ399006":  "创业板指",
            "CSIH30269": "红利低波",
            "HKHSTECH":  "恒生科技",
            "SP500":     "标普500",
            "SH000922":  "中证红利",
        }
        
        result = {}
        for item in items:
            code = item.get("index_code", "")
            if code in targets:
                yeild_val = item.get("yeild")
                result[code] = {
                    "名称": targets[code],
                    "PE": round(item["pe"], 2) if item.get("pe") and item["pe"] > 0 else None,
                    "PB": round(item["pb"], 2) if item.get("pb") and item["pb"] > 0 else None,
                    "PE分位": round(item["pe_percentile"] * 100, 2) if item.get("pe_percentile") is not None else None,
                    "PB分位": round(item["pb_percentile"] * 100, 2) if item.get("pb_percentile") is not None else None,
                    "股息率": round(yeild_val * 100, 2) if yeild_val is not None else None,
                    "评估": item.get("eva_type", ""),
                    "source": "雪球蛋卷API",
                }
        
        print(f"    雪球蛋卷: {len(result)}/{len(targets)} 个指数")
        return result
    except Exception as e:
        print(f"    雪球蛋卷API失败: {e}")
        return {}


# ─── 数据源E: yfinance 统一兜底 ──────────────────────────────
def _yf_fallback(ticker_map):
    """统一 yfinance 兜底函数，在其他数据源返回空/错误时调用。
    
    ticker_map: dict {输出key: yfinance ticker字符串}
      如 {"日经225": "^N225", "KOSPI": "^KS11", "QQQM": "QQQM"}
    
    返回 dict {输出key: {"最新价": float, "涨跌幅": float}} 
    全部失败返回空dict，永不抛异常。
    
    yfinance Ticker.history() 输出列: Open, High, Low, Close, Volume
    需 ≥2 个交易日计算涨跌幅。
    """
    if not ticker_map:
        return {}
    try:
        import yfinance as yf
    except ImportError:
        return {}
    
    result = {}
    for idx, (key, ticker) in enumerate(ticker_map.items()):
        try:
            if idx > 0:
                time.sleep(1.5)  # 避免 yfinance 频率限制
            tk = yf.Ticker(ticker)
            hist = tk.history(period="5d", auto_adjust=True)
            if hist is None or hist.empty:
                continue
            close = hist['Close'].dropna()
            if len(close) >= 2:
                price = round(float(close.iloc[-1]), 2)
                prev = round(float(close.iloc[-2]), 2)
                chg_pct = round((price - prev) / prev * 100, 2)
                result[key] = {"最新价": price, "涨跌幅": chg_pct}
            elif len(close) == 1:
                price = round(float(close.iloc[-1]), 2)
                result[key] = {"最新价": price, "涨跌幅": None}
        except:
            pass
    
    if result:
        items_str = ", ".join(f"{k}={v.get('最新价', '?')}" for k, v in result.items())
        print(f"    yfinance兜底[{', '.join(result.keys())}]: {items_str}")
    return result


# ═══════════════════════════════════════════════════════════════
# 业务模块
# ═══════════════════════════════════════════════════════════════

# ─── 1. A股指数行情（不变）───────────────────────────────────
def fetch_market_cn():
    """上证/深证/沪深300/科创50/创业板指"""
    WANTED = [("上证指数","000001"), ("深证成指","399001"),
              ("沪深300","000300"), ("科创50","000688"), ("创业板指","399006")]

    df = _akshare_sina_index_spot()
    if df is not None and len(df) >= 5:
        rows = []
        for name, code in WANTED:
            match = df[df["名称"].str.strip() == name]
            if len(match) > 0:
                r = match.iloc[0]
                prev = _num(r.get("昨收"))
                chg = _num(r.get("涨跌额"))
                pct = round((float(chg)/float(prev))*100,2) if chg and prev and float(prev)>0 else None
                rows.append({
                    "指数": name, "代码": code,
                    "最新价": _num(r.get("最新价")),
                    "涨跌幅": pct,
                    "成交量": _num(r.get("成交量")),
                    "成交额": _num(r.get("成交额")),
                    "今开": _num(r.get("今开")),
                    "最高": _num(r.get("最高")),
                    "最低": _num(r.get("最低")),
                })
        if len(rows) >= 4:
            return _ok(rows)

    # 新浪API失败 → yfinance 兜底（只兜底上证指数 000001.SS）
    yf_cn = _yf_fallback({"上证指数": "000001.SS"})
    rows = []
    for n, c in WANTED:
        if n == "上证指数" and yf_cn.get("上证指数"):
            d = yf_cn["上证指数"]
            rows.append({"指数": n, "代码": c,
                        "最新价": d["最新价"], "涨跌幅": d["涨跌幅"],
                        "source": "yfinance兜底"})
        else:
            rows.append({"指数": n, "代码": c, "error": "新浪API无数据"})
    return _ok(rows)


# ─── 2. 港股指数行情（不变）──────────────────────────────────
def fetch_market_hk():
    """恒生指数 + 恒生中国企业指数 + 恒生科技指数（数据源直接返回，零额外开销）"""
    df = _akshare_sina_hk_index()
    if df is not None:
        rows = []
        for _, r in df.iterrows():
            name = str(r.get("名称","")).strip()
            if name in ("恒生指数","恒生中国企业指数","恒生科技指数"):
                prev = _num(r.get("昨收"))
                chg = _num(r.get("涨跌额"))
                pct = round((float(chg)/float(prev))*100,2) if chg and prev and float(prev)>0 else None
                rows.append({
                    "指数": name, "代码": str(r.get("代码","")),
                    "最新价": _num(r.get("最新价")),
                    "涨跌幅": pct,
                    "今开": _num(r.get("今开")),
                    "最高": _num(r.get("最高")),
                    "最低": _num(r.get("最低")),
                })
        if len(rows) >= 3:
            return _ok(rows)

    # 新浪API失败 → yfinance 兜底
    yf_hk = _yf_fallback({"恒生指数": "^HSI", "恒生中国企业指数": "^HSCE", "恒生科技指数": "^HSTECH"})
    rows = []
    for name, yf_key in [("恒生指数", "恒生指数"), ("恒生中国企业指数", "恒生中国企业指数"), ("恒生科技指数", "恒生科技指数")]:
        if yf_hk.get(yf_key):
            d = yf_hk[yf_key]
            rows.append({"指数": name, "代码": yf_key,
                        "最新价": d["最新价"], "涨跌幅": d["涨跌幅"],
                        "source": "yfinance兜底"})
        else:
            rows.append({"指数": name, "code": name, "error": "全部数据源不可用"})
    return _ok(rows)


# ─── 3. 全球主要指数（akshare新浪美股 + 东财全球）──
def fetch_market_global():
    """美股(DJI/SPX/IXIC) + 日经/KOSPI/STOXX"""
    result = {}

    # ── 美股三大指数: yfinance 优先 → akshare新浪兜底 ──
    us_map = {".DJI": "道琼斯工业", ".INX": "标普500", ".IXIC": "纳斯达克综合"}
    us_yf = {"道琼斯工业": "^DJI", "标普500": "^GSPC", "纳斯达克综合": "^IXIC"}

    # P2: 美股业务日期新鲜度校验（解析预期业务日期，与 akshare 实际返回日期比对）
    _us_resolver = None
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from market_date_resolver import MarketDateResolver
        _us_resolver = MarketDateResolver()
    except Exception as e:
        print(f"    (美股新鲜度校验初始化失败，跳过: {e})")

    # 一次性取三大指数 yfinance（美东收盘后约 2-3h 即有完整日线，早报时段应已就绪）
    _us_yf_data = _yf_fallback(us_yf)

    for sym, name in us_map.items():
        # ① 优先 yfinance
        if name in _us_yf_data:
            d = _us_yf_data[name]
            result[name] = {"代码": us_yf[name], "最新价": d["最新价"], "涨跌幅": d["涨跌幅"],
                           "source": "yfinance"}
            continue
        # ② 兜底 akshare 新浪
        data = _akshare_sina_us_index(sym)
        if data:
            entry = {"代码": sym, "最新价": data["close"], "涨跌幅": data["change_pct"],
                     "今开": data["open"], "最高": data["high"], "最低": data["low"],
                     "source": "akshare新浪兜底"}
            # 新鲜度校验：新浪源（含明确日期）比对；实际日期早于预期 → 滞后
            if _us_resolver and data.get("date"):
                _expected = str(_us_resolver.get_business_date("us"))
                if data["date"] < _expected:
                    entry["_stale"] = True
                    entry["_expected_date"] = _expected
                    print(f"    ⚠️ 美股 {name} 新浪兜底数据日期 {data['date']} < 预期 {_expected}（滞后）")
            result[name] = entry
        else:
            result[name] = {"代码": sym, "error": "美股数据源均不可用"}

    # ── 全球指数: akshare东财 → yfinance兜底 ──
    df = _ak_eastmoney("index_global_spot_em")
    global_yf = {"日经225": "^N225", "KOSPI": "^KS11", "STOXX": "^STOXX"}
    global_targets = {"日经225": "日经225", "韩国KOSPI": "KOSPI", "STOXX": "STOXX 600"}
    if df is not None and len(df) > 0:
        for _, r in df.iterrows():
            try:
                n = str(r.iloc[1]) if len(r.columns) > 1 else str(r.iloc[0])
                for kw, label in global_targets.items():
                    if kw in n:
                        result[label] = {"名称": n, "最新价": _num(r.iloc[2]) if len(r.columns) > 2 else None,
                                        "涨跌幅": _num(r.iloc[3]) if len(r.columns) > 3 else None,
                                        "source": "akshare东财"}
                        break
            except: pass

    # 外围 yfinance 兜底
    global_missing = {label: global_yf[label] for label in global_yf
                      if label not in result
                      or (label in result and result[label].get("error"))
                      or result[label].get("最新价") is None}
    if global_missing:
        for label, data in _yf_fallback(global_missing).items():
            result[label] = {"名称": label, "最新价": data["最新价"],
                            "涨跌幅": data["涨跌幅"], "source": "yfinance兜底"}

    # 标记完全缺失
    all_labels = list(us_map.values()) + list(global_targets.values())
    for label in all_labels:
        if label not in result:
            result[label] = {"名称": label, "error": "全部数据源不可用"}

    return _ok(result)


# ─── 4. 汇率/商品/债券（akshare期货 + FRED DGS10）───
def fetch_forex_rate():
    """原油(WTI)/黄金(COMEX)/CNH汇率/中美债券收益率"""
    result = {}

    # ── 大宗商品: akshare futures_global_spot_em ──
    try:
        import akshare as ak
        df = ak.futures_global_spot_em()
        if df is not None and len(df) > 0:
            # 找最近到期的主力合约
            targets = {"NYMEX原油": ["CL"], "COMEX黄金": ["GC"],
                       "布伦特原油": ["B"], "COMEX白银": ["SI"]}
            found = {}
            for _, r in df.iterrows():
                try:
                    code = str(r.get("代码",""))
                    name = str(r.get("名称",""))
                    price = _num(r.get("最新价")); chg = _num(r.get("涨跌幅"))
                    for label, prefixes in targets.items():
                        if label in found: continue
                        if label == "布伦特原油" and code.startswith("B"):
                            found[label] = {"名称": name, "代码": code, "最新价": price, "涨跌幅": chg}
                        elif code.startswith(tuple(prefixes)) and "00Y" in code:  # 主连
                            found[label] = {"名称": name, "代码": code, "最新价": price, "涨跌幅": chg}
                except: pass

            if found.get("NYMEX原油"):
                result["WTI原油"] = {**found["NYMEX原油"], "source": "akshare期货"}
            if found.get("COMEX黄金"):
                result["COMEX黄金"] = {**found["COMEX黄金"], "source": "akshare期货"}
            if found.get("布伦特原油"):
                result["布伦特原油"] = {**found["布伦特原油"], "source": "akshare期货"}
            if found.get("COMEX白银"):
                result["COMEX白银"] = {**found["COMEX白银"], "source": "akshare期货"}
    except Exception as e:
        print(f"    期货数据获取失败: {e}")

    # ── 债券收益率: CN10Y + US10Y 同一来源 akshare bond_zh_us_rate ──
    try:
        import akshare as ak
        df = ak.bond_zh_us_rate()
        if df is not None and len(df) > 0:
            last = df.iloc[-1]
            result["CN10Y"] = {"名称": "10Y中国国债收益率", "最新值": _num(last.get("中国国债收益率10年")),
                              "日期": str(last.iloc[0]), "source": "akshare"}
            result["US10Y"] = {"名称": "10Y美国国债收益率", "最新值": _num(last.get("美国国债收益率10年")),
                              "日期": str(last.iloc[0]), "source": "akshare(bond_zh_us_rate)"}
            print(f"    中美10Y: CN={result['CN10Y']['最新值']}, US={result['US10Y']['最新值']}")
    except Exception as e:
        print(f"    bond_zh_us_rate 失败: {e}")
        for k in ["CN10Y", "US10Y"]:
            if k not in result:
                result[k] = {"note": "数据暂不可得"}

    # ── USD/CNH: 由 fetch_extra 获取 ──

    # 标记缺失
    for k in ["WTI原油","COMEX黄金","CN10Y","US10Y"]:
        if k not in result or "最新价" not in result.get(k, {}):
            if k not in result:
                result[k] = {}
            if "最新价" not in result.get(k, {}) and "最新值" not in result.get(k, {}):
                result[k]["note"] = "WebSearch备用"

    return _ok(result)


# ─── 5. 估值数据（v19重写：akshare新浪 + 腾讯 + 且慢 WebFetch）────
def fetch_valuation():
    """A股7大指数价格 + 美股估值 + 恒生科技 + 且慢PE/PB分位"""
    result = {}

    # ── A股指数价格（akshare新浪，单一来源）──
    a_indices = [("上证指数","000001"),("深证成指","399001"),("沪深300","000300"),
                 ("科创50","000688"),("创业板指","399006"),
                 ("中证A500","000510"),("中证红利","000922")]
    a_list = []

    df = _akshare_sina_index_spot()
    if df is not None:
        for name, code in a_indices:
            match = df[df["名称"].str.strip() == name]
            if len(match) > 0:
                r = match.iloc[0]
                prev = _num(r.get("昨收")); chg = _num(r.get("涨跌额"))
                pct = round((float(chg)/float(prev))*100,2) if chg and prev and float(prev)>0 else None
                a_list.append({"指数":name,"代码":code,"最新价":_num(r.get("最新价")),
                               "涨跌幅":pct})

    result["a_share"] = a_list if a_list else {"error": "新浪API无数据"}

    # ── 美股估值（yfinance 优先 → akshare新浪兜底）──
    us_list = []
    us_targets = [(".NDX","纳斯达克100"), (".INX","标普500")]
    us_val_yf = {"纳斯达克100": "^NDX", "标普500": "^GSPC"}
    _us_val_yf = _yf_fallback(us_val_yf)
    for sym, name in us_targets:
        entry = {"指数": name, "ticker": sym}
        if name in _us_val_yf:
            d = _us_val_yf[name]
            entry["最新价"] = d["最新价"]
            entry["涨跌幅"] = d["涨跌幅"]
            entry["source"] = "yfinance"
        else:
            data = _akshare_sina_us_index(sym)
            if data:
                entry["最新价"] = data["close"]
                entry["涨跌幅"] = data["change_pct"]
                entry["source"] = "akshare新浪兜底"
            else:
                entry["note"] = "数据暂不可得"
        us_list.append(entry)
    result["us"] = us_list

    # ── 恒生科技（akshare新浪港股指数）──
    df_hk = _akshare_sina_hk_index()
    if df_hk is not None:
        for _, r in df_hk.iterrows():
            if str(r.get("名称","")).strip() == "恒生科技指数":
                result["hk_tech"] = {"指数":"恒生科技","最新价":_num(r.get("最新价")),
                                     "涨跌幅":_num(r.get("涨跌幅")),
                                     "note": "PE/PB分位需WebSearch（且慢无此指数）"}
                break
    if "hk_tech" not in result:
        result["hk_tech"] = {"指数":"恒生科技","note":"需WebSearch"}

    # ── PE/PB分位+股息率: 雪球蛋卷 API ──
    danjuan = _fetch_danjuan_valuation()
    result["danjuan_valuation"] = danjuan if danjuan else {"note": "雪球蛋卷API失败，需WebSearch"}

    return _ok(result)


# ─── 6. 基金净值+估值+ETF溢价（v23: 删020602，保留QDII参考）───
def fetch_fund():
    """QDII ETF净值估算参考（020602已换为563020场内ETF，走腾讯API）"""
    result = {}

    try:
        import akshare as ak
        df_est = ak.fund_value_estimation_em(symbol="QDII")
        if df_est is not None and len(df_est) > 0:
            qdii_list = []
            for _, r in df_est.iterrows():
                name = str(r.iloc[2]) if len(r) > 2 else ""
                if any(kw in name for kw in ["纳指","纳斯达克","标普500","标普"]):
                    qdii_list.append({
                        "基金名称": name,
                        "基金代码": str(r.iloc[1]) if len(r) > 1 else "",
                        "估算净值": _num(r.iloc[3] if len(r) > 3 else None),
                        "估算增长率": _num(r.iloc[4] if len(r) > 4 else None),
                        "公布净值": _num(r.iloc[5] if len(r) > 5 else None),
                    })
            if qdii_list:
                result["qdii_etf_reference"] = qdii_list
    except: pass

    return _ok(result)


# ─── 7. 申万行业+资金流+全市场PE（v21重写）─────────────────
def fetch_industry():
    """v21: 申万31行业实时涨跌幅 + 同花顺90行业资金流 + 全市场PE"""
    import akshare as ak
    result = {}

    # 1. 申万一级行业实时行情 → 计算涨跌幅TOP3/BOTTOM3
    try:
        df_sw = ak.index_realtime_sw(symbol='一级行业')
        if df_sw is not None and len(df_sw) > 0:
            df_sw['涨跌幅'] = ((df_sw['最新价'] - df_sw['昨收盘']) / df_sw['昨收盘'] * 100).round(2)
            df_sorted = df_sw.sort_values('涨跌幅', ascending=False)

            industries = []
            for _, row in df_sorted.iterrows():
                industries.append({
                    '名称': row['指数名称'],
                    '代码': row['指数代码'],
                    '最新价': round(float(row['最新价']), 2),
                    '涨跌幅': row['涨跌幅'],
                    '成交额_亿': round(float(row['成交额']), 2),
                })
            result['申万行业'] = industries
            result['申万TOP3'] = industries[:3]
            result['申万BOTTOM3'] = industries[-3:][::-1]
    except Exception as e:
        result['申万行业'] = []
        result['_申万_error'] = str(e)

    # 2. 同花顺行业板块 → 资金流向净流入TOP5/BOTTOM5
    try:
        df_ths = ak.stock_board_industry_summary_ths()
        if df_ths is not None and len(df_ths) > 0:
            df_by_inflow = df_ths.sort_values('净流入', ascending=False)

            top5 = []
            for _, r in df_by_inflow.head(5).iterrows():
                top5.append({
                    '板块': r['板块'],
                    '涨跌幅': round(float(r['涨跌幅']), 2),
                    '净流入_亿': round(float(r['净流入']), 2),
                    '总成交额_亿': round(float(r['总成交额']), 2),
                })

            bottom5 = []
            for _, r in df_by_inflow.tail(5).iterrows():
                bottom5.append({
                    '板块': r['板块'],
                    '涨跌幅': round(float(r['涨跌幅']), 2),
                    '净流入_亿': round(float(r['净流入']), 2),
                    '总成交额_亿': round(float(r['总成交额']), 2),
                })

            total_inflow = round(float(df_ths['净流入'].sum()), 2)

            result['资金_净流入TOP5'] = top5
            result['资金_净流出TOP5'] = bottom5
            result['资金_全市场净流入_亿'] = total_inflow
            result['资金_行业总数'] = len(df_ths)
    except Exception as e:
        result['_资金流_error'] = str(e)

    # 3. 全市场PE（乐咕乐股，日更）
    try:
        df_pe = ak.stock_market_pe_lg(symbol='上证A股')
        if df_pe is not None and len(df_pe) > 0:
            latest_pe = df_pe.dropna(subset=['市盈率']).tail(1)
            if len(latest_pe) > 0:
                r = latest_pe.iloc[0]
                result['全市场PE'] = {
                    'PE': round(float(r['市盈率']), 2),
                    '总市值_亿': round(float(r['总市值']), 2),
                    '日期': str(r['日期']),
                    '来源': '乐咕乐股(日更)',
                }
    except Exception as e:
        result['_PE_error'] = str(e)

    return _ok(result)


# ═══════════════════════════════════════════════════════════════
# 🆕 v22 数据源: 新浪汇率 + akshare资金面 + Google News RSS(英+中) + 宏观扩展(核心PCE/BDI/SOX等)
# ═══════════════════════════════════════════════════════════════

def fetch_extra():
    """v29: 资金面 + QDII监测(腾讯API实时价+东方财富HTTP净值) + 场外申购额度(Nasdaq100/S&P500可申购大额度)"""
    import akshare as ak
    result = {}
    today_str = datetime.now(TZ_CN).strftime("%Y%m%d")

    # ── 1. USD/CNH 汇率（akshare 外汇局中间价 → yfinance 兜底）──
    usdcnh_ok = False
    try:
        _df_fx = ak.currency_boc_safe()
        if _df_fx is not None and len(_df_fx) > 0:
            _latest = _df_fx.iloc[-1]
            _usd_str = str(_latest.get("美元", ""))
            if _usd_str:
                # 央行中间价以 "元/100外币" 计，如 679.89 → 6.7989
                result["USD_CNH"] = round(float(_usd_str) / 100.0, 4)
                result["USD_CNH_日期"] = str(_latest.get("日期", ""))
                result["USD_CNH_来源"] = "akshare 外汇局中间价"
                usdcnh_ok = True
    except Exception as e:
        print(f"    currency_boc_safe 失败: {e}")

    if not usdcnh_ok:
        yf_fx = _yf_fallback({"USD_CNH": "USDCNH=X"})
        if yf_fx.get("USD_CNH"):
            result["USD_CNH"] = yf_fx["USD_CNH"]["最新价"]
            result["USD_CNH_来源"] = "yfinance兜底"

    # ── 2. 南下/北向资金 + 涨跌家数（保留）──
    try:
        df = ak.stock_hsgt_fund_flow_summary_em()
        if df is not None and len(df) > 0:
            latest = df[df["交易日"] == today_str]
            if len(latest) == 0:
                latest = df.tail(4)
            south_sum = 0.0; north_sum = 0.0; up_cnt = 0; down_cnt = 0
            for _, r in latest.iterrows():
                direction = str(r.get("资金方向", ""))
                net = float(r.get("成交净买额", 0) or 0)
                if direction == "南向": south_sum += net
                elif direction == "北向": north_sum += net
                up_cnt += int(r.get("上涨数", 0) or 0)
                down_cnt += int(r.get("下跌数", 0) or 0)
            result["南下资金_净买入_亿"] = round(south_sum, 2) if south_sum else None
            result["北向资金_净买入_亿"] = round(north_sum, 2) if north_sum else None
            result["上涨家数"] = up_cnt if up_cnt else None
            result["下跌家数"] = down_cnt if down_cnt else None
            if up_cnt and down_cnt:
                result["涨跌比"] = round(up_cnt / max(down_cnt, 1), 2)
    except Exception as e:
        result["_资金流_error"] = str(e)

    # ── 3. 两融余额（保留）──
    try:
        sh = ak.macro_china_market_margin_sh()
        sz = ak.macro_china_market_margin_sz()
        if sh is not None and len(sh) > 0:
            result["沪市_融资融券余额_亿"] = round(float(sh.iloc[-1]["融资融券余额"]) / 1e8, 2)
        if sz is not None and len(sz) > 0:
            result["深市_融资融券余额_亿"] = round(float(sz.iloc[-1]["融资融券余额"]) / 1e8, 2)
    except: pass

    # ── 4. 涨停/跌停数（保留）──
    try:
        zt = ak.stock_zt_pool_em(date=today_str)
        result["涨停数"] = len(zt) if zt is not None else None
    except: result["涨停数"] = None
    try:
        dt = ak.stock_zt_pool_dtgc_em(date=today_str)
        result["跌停数"] = len(dt) if dt is not None else None
    except: result["跌停数"] = None

    # ── v24方案: QDII监测 — 腾讯API实时价 + 东方财富HTTP净值（不依赖 fund_etf_spot_em）──
    qdii_data = {"场内ETF": [], "场外QDII": []}
    # 加载昨日 QDII 基准，用于计算「对比昨日」列（跨运行快照）
    _prev = _load_qdii_prev() or {}
    _prev_etf = {e["代码"]: e.get("溢价率") for e in _prev.get("场内ETF", []) if e.get("代码")}
    _prev_qdii = {e["代码"]: e.get("日累计限定金额") for e in _prev.get("场外QDII", []) if e.get("代码")}
    _etf_set = {"513100","513500","159941","159659","159612","513650"}
    _etf_names = {
        "513100":"纳指ETF国泰","513500":"标普500ETF博时",
        "159941":"纳指ETF广发","159659":"纳斯达克100ETF招商",
        "159612":"标普500ETF国泰","513650":"标普500ETF南方",
    }
    # 腾讯API批量查询ETF实时价
    _etf_q = ",".join(
        f"sh{c}" if c.startswith(("51","56","58")) else f"sz{c}" for c in _etf_set
    )
    _etf_raw = _tencent_quote(_etf_q)
    for _code in _etf_set:
        _mp = None; _cp = None
        if _code in _etf_raw:
            _mp = _etf_raw[_code]["price"]
            _cp = _etf_raw[_code]["change_pct"]
        else:
            for _k, _v in _etf_raw.items():
                if _k.startswith(_code):
                    _mp = _v["price"]; _cp = _v["change_pct"]; break
        _nav = None; _nav_d = None
        try:
            # 东方财富直连 HTTP API 获取净值
            _nav_url = f"https://api.fund.eastmoney.com/f10/lsjz?fundCode={_code}&pageIndex=1&pageSize=2"
            _nav_resp = requests.get(_nav_url,
                headers={"User-Agent": UA, "Referer": "https://fund.eastmoney.com/"}, timeout=10)
            _nav_resp.encoding = "utf-8"
            _nav_j = _nav_resp.json()
            _nav_rows = _nav_j.get("Data", {}).get("LSJZList", [])
            if _nav_rows:
                _nav_last = _nav_rows[-1]
                _nav = round(float(_nav_last.get("DWJZ", 0)), 4)
                _nav_d = str(_nav_last.get("FSRQ", ""))
        except Exception as _nav_e:
            print(f"      东方财富净值API失败({_code}): {_nav_e}")
        _pr = round((_mp - _nav) / _nav * 100, 2) if _mp and _nav and _nav > 0 else None
        _prev_pr = _prev_etf.get(_code)
        _pr_delta = round(_pr - _prev_pr, 2) if (_pr is not None and _prev_pr is not None) else None
        qdii_data["场内ETF"].append({
            "代码": _code, "名称": _etf_names.get(_code,""),
            "最新价": _mp, "涨跌幅": _cp,
            "最新净值": _nav, "净值日期": _nav_d, "溢价率": _pr,
            "溢价率对比昨日": _pr_delta,
            "溢价率来源": "腾讯价+东方财富净值",
        })
    # 场外QDII申购额度（纳指100/标普500，可申购且额度较大的6条）
    try:
        import pandas as pd
        _df = ak.fund_purchase_em()
        _qdii_kw = ["纳指","纳斯达克100","标普500"]
        _seen = set()
        for _kw in _qdii_kw:
            _mask = (
                _df['基金简称'].str.contains(_kw, na=False)
                & _df['基金类型'].str.contains('海外', na=False)
                & ~_df['基金简称'].str.contains('美元', na=False)
                & (_df['申购状态'] != '场内交易')
                & (_df['申购状态'] != '暂停申购')
            )
            for _, _r in _df[_mask].iterrows():
                _c = str(_r['基金代码'])
                if _c in _seen: continue
                _seen.add(_c)
                _lim = _r['日累计限定金额']
                qdii_data["场外QDII"].append({
                    "代码": _c,
                    "简称": str(_r['基金简称']),
                    "名称_短": _shorten_qdii_name(str(_r['基金简称'])),
                    "最新净值": str(_r['最新净值/万份收益']),
                    "净值日期": str(_r['最新净值/万份收益-报告时间']),
                    "申购状态": str(_r['申购状态']),
                    "日累计限定金额": round(float(_lim), 2) if pd.notna(_lim) and _lim else 0,
                })
    except Exception as e:
        qdii_data["_场外_error"] = str(e)[:100]
    # 按日累计限定金额降序排列（大额度优先），最多6条
    if qdii_data["场外QDII"]:
        qdii_data["场外QDII"].sort(key=lambda x: x["日累计限定金额"], reverse=True)
        qdii_data["场外QDII"] = qdii_data["场外QDII"][:6]
    # 计算每只场外QDII相对昨日的限额变化（按代码匹配，今日有/昨日无则留空）
    for _e in qdii_data["场外QDII"]:
        _c = _e.get("代码"); _lim = _e.get("日累计限定金额")
        _prev_lim = _prev_qdii.get(_c)
        _e["限额对比昨日"] = round(_lim - _prev_lim, 2) if (_lim is not None and _prev_lim is not None) else None
    result['QDII_监测'] = qdii_data
    # 留存当日 QDII 基准，供下一运行日对比（跨运行持久化）
    _save_qdii_snapshot(qdii_data)

    return _ok(result)


# ─── 数据源H: Google News RSS → 英文9外媒 + 中文国内财经 ──────
def _fetch_rss_news():
    """v22: 全球TOP10新闻 — 英文前5条(9外媒) + 中文后5条(国内财经)"""
    ALLOWED_EN = {
        "Bloomberg", "Reuters", "Financial Times", "WSJ", "Wall Street Journal",
        "CNBC", "Yahoo Finance", "Forbes", "Barron's", "Fortune"
    }
    ALLOWED_CN = {
        "证券时报", "第一财经", "东方财富", "新华网", "华尔街见闻",
        "21财经", "财联社", "金融界", "中证网", "人民网", "人民网财经",
    }
    URL_EN = ("https://news.google.com/rss/topics/"
              "CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtVnVHZ0pWVXlnQVAB"
              "?hl=en-US&gl=US&ceid=US:en")
    URL_CN = ("https://news.google.com/rss/topics/"
              "CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtVnVHZ0pWVXlnQVAB"
              "?hl=zh-CN&gl=CN")

    def _parse(url, allowed, max_items=15):
        r = requests.get(url, headers={"User-Agent": UA}, timeout=15)
        tree = ET.fromstring(r.content)
        result = []
        for item in tree.findall(".//item"):
            source_el = item.find("source")
            source = source_el.text if source_el is not None else ""
            if source not in allowed:
                continue
            title_el = item.find("title")
            desc_el = item.find("description")
            link_el = item.find("link")
            pub_el = item.find("pubDate")
            title = title_el.text if title_el is not None else ""
            title = re.sub(r"\s*[-–|]\s*" + re.escape(source) + r"\s*$", "", title).strip()[:100]
            desc = desc_el.text if desc_el is not None else ""
            desc = re.sub(r"<[^>]+>", " ", desc).strip()[:600]
            result.append({
                "title": title,
                "desc": desc,
                "source": source,
                "link": link_el.text if link_el is not None else "",
                "pubDate": pub_el.text if pub_el is not None else "",
            })
            if len(result) >= max_items:
                break
        return result

    try:
        items_en = _parse(URL_EN, ALLOWED_EN, 15)
        items_cn = _parse(URL_CN, ALLOWED_CN, 15)
        return _ok({
            "total_en": len(items_en),
            "total_cn": len(items_cn),
            "items_en": items_en,
            "items_cn": items_cn,
        })
    except Exception as e:
        return _fail(f"RSS新闻抓取失败: {e}")


# ─── 8. 个人持仓标的行情 + 监督池行情（v23: +563020 + 监督池批量）───
def fetch_holdings():
    """个人持仓(招行A/H/长电/563020/QQQM/SPY) + 监督池批量行情
    美股通过腾讯API获取，自动截取交易所后缀(.OQ/.AM等)匹配stock_map"""
    raw = _tencent_quote("sh600036,hk03968,sh600900,sh563020,usQQQM,usSPY")
    result = {}

    stock_map = {
        "600036": {"名称":"招商银行A","市场":"A股"},
        "03968":  {"名称":"招商银行H","市场":"港股"},
        "600900": {"名称":"长江电力","市场":"A股"},
        "563020": {"名称":"红利低波ETF易方达","市场":"A股","备注":"ETF"},
        "QQQM":   {"名称":"QQQM","市场":"美股","备注":"纳斯达克100 ETF"},
        "SPY":    {"名称":"SPY","市场":"美股","备注":"标普500 ETF"},
    }
    for qc, v in raw.items():
        # 直接匹配（A股/港股）
        if qc in stock_map:
            result[qc] = {
                **stock_map[qc],
                "最新价": v["price"],
                "涨跌幅": v["change_pct"],
            }
        # 美股后缀截取: "QQQM.OQ"→"QQQM", "SPY.AM"→"SPY"
        elif "." in qc:
            _bare = qc.split(".")[0]
            if _bare in stock_map:
                result[_bare] = {
                    **stock_map[_bare],
                    "最新价": v["price"],
                    "涨跌幅": v["change_pct"],
                }

    # 标记缺失
    for code, info in stock_map.items():
        if code not in result:
            result[code] = {**info, "error": "腾讯API无数据"}

    # QQQM/SPY yfinance 兜底
    yf_needed = {}
    for code in ["QQQM", "SPY"]:
        if code in result and result[code].get("error"):
            yf_needed[code] = code  # yfinance ticker 与 code 相同
    if yf_needed:
        yf_data = _yf_fallback(yf_needed)
        for code, data in yf_data.items():
            if code in stock_map:
                result[code] = {**stock_map[code],
                                "最新价": data["最新价"],
                                "涨跌幅": data["涨跌幅"],
                                "source": "yfinance兜底"}

    # 🆕 v21: A股分红历史
    dividend_a = {}
    try:
        import akshare as ak
        for code, label in [("600036", "招商银行A"), ("600900", "长江电力")]:
            try:
                df_div = ak.stock_history_dividend_detail(symbol=code, indicator='分红')
                if df_div is not None and len(df_div) > 0:
                    latest = df_div.iloc[0]
                    div_info = {
                        '公告日期': str(latest['公告日期']),
                        '派息': str(latest['派息']),
                        '进度': str(latest['进度']),
                    }
                    ex_date = latest.get('除权除息日')
                    if ex_date and str(ex_date) != 'NaT':
                        div_info['除权除息日'] = str(ex_date)
                    reg_date = latest.get('股权登记日')
                    if reg_date and str(reg_date) != 'NaT':
                        div_info['股权登记日'] = str(reg_date)
                    dividend_a[label] = div_info
            except: pass
    except: pass
    result['分红_A股'] = dividend_a

    # 🆕 v21: H股分红历史
    dividend_h = {}
    try:
        import akshare as ak
        df_hk = ak.stock_hk_dividend_payout_em(symbol='03968')
        if df_hk is not None and len(df_hk) > 0:
            latest = df_hk.iloc[0]
            dividend_h['招商银行H'] = {
                '公告日期': str(latest['最新公告日期']),
                '分红方案': str(latest['分红方案']),
                '分配类型': str(latest['分配类型']),
                '除净日': str(latest['除净日']),
                '发放日': str(latest.get('发放日', 'N/A')),
            }
    except: pass
    result['分红_H股'] = dividend_h

    # 🆕 v21: 研报评级（招商银行A，最新3份）
    reports = []
    try:
        import akshare as ak
        df_rpt = ak.stock_research_report_em(symbol='600036')
        if df_rpt is not None and len(df_rpt) > 0:
            for _, r in df_rpt.head(3).iterrows():
                reports.append({
                    '机构': str(r.get('机构', '')),
                    '评级': str(r.get('东财评级', '')),
                    '日期': str(r.get('日期', '')),
                })
    except: pass
    result['研报_招商银行A'] = reports

    # ── 🆕 v23: 监督池批量行情（腾讯API）──
    _watchlist = {
        "600900": {"名称":"长江电力","市场":"A股"},          # 个人持仓已在上面，但监督池也保留
        "002050": {"名称":"三花智控","市场":"A股"},
        "688256": {"名称":"寒武纪","市场":"A股"},
        "601975": {"名称":"招商南油","市场":"A股"},
        "300308": {"名称":"中际旭创","市场":"A股"},
        "hk06809": {"名称":"澜起科技","市场":"港股"},
        "300502": {"名称":"新易盛","市场":"A股"},
        "600116": {"名称":"三峡水利","市场":"A股"},
        "hk00005": {"名称":"汇丰控股","市场":"港股"},
        "688795": {"名称":"摩尔线程-U","市场":"A股"},
        "603259": {"名称":"药明康德","市场":"A股"},
        "601088": {"名称":"中国神华","市场":"A股"},
        "300750": {"名称":"宁德时代","市场":"A股"},
        "601919": {"名称":"中远海控","市场":"A股"},
        "002594": {"名称":"比亚迪","市场":"A股"},
        "000651": {"名称":"格力电器","市场":"A股"},
        "600362": {"名称":"江西铜业","市场":"A股"},
        "601288": {"名称":"农业银行","市场":"A股"},
        "600030": {"名称":"中信证券","市场":"A股"},
        "002142": {"名称":"宁波银行","市场":"A股"},
        "000568": {"名称":"泸州老窖","市场":"A股"},
        "300059": {"名称":"东方财富","市场":"A股"},
        "601899": {"名称":"紫金矿业","市场":"A股"},
        "688981": {"名称":"中芯国际","市场":"A股"},
        "000625": {"名称":"长安汽车","市场":"A股"},
        "002600": {"名称":"领益智造","市场":"A股"},
        "601138": {"名称":"工业富联","市场":"A股"},
        "603369": {"名称":"今世缘","市场":"A股"},
        "000858": {"名称":"五粮液","市场":"A股"},
        "600519": {"名称":"贵州茅台","市场":"A股"},
        "603986": {"名称":"兆易创新","市场":"A股"},
        "603501": {"名称":"豪威集团","市场":"A股"},
        "300274": {"名称":"阳光电源","市场":"A股"},
        "300124": {"名称":"汇川技术","市场":"A股"},
        "600732": {"名称":"爱旭股份","市场":"A股"},
        "601012": {"名称":"隆基绿能","市场":"A股"},
        "600486": {"名称":"扬农化工","市场":"A股"},
        "002371": {"名称":"北方华创","市场":"A股"},
        "002475": {"名称":"立讯精密","市场":"A股"},
        "600438": {"名称":"通威股份","市场":"A股"},
        "600745": {"名称":"*ST闻泰","市场":"A股"},
        "002241": {"名称":"歌尔股份","市场":"A股"},
        "600312": {"名称":"平高电气","市场":"A股"},
        "601615": {"名称":"明阳智能","市场":"A股"},
        "000400": {"名称":"许继电气","市场":"A股"},
        "600585": {"名称":"海螺水泥","市场":"A股"},
        "000860": {"名称":"顺鑫农业","市场":"A股"},
        "000630": {"名称":"铜陵有色","市场":"A股"},
        "600703": {"名称":"三安光电","市场":"A股"},
        "000063": {"名称":"中兴通讯","市场":"A股"},
        "002223": {"名称":"鱼跃医疗","市场":"A股"},
        "601398": {"名称":"工商银行","市场":"A股"},
        "002352": {"名称":"顺丰控股","市场":"A股"},
        "600309": {"名称":"万华化学","市场":"A股"},
        "002415": {"名称":"海康威视","市场":"A股"},
    }
    # 构建腾讯API查询串
    _prefix_map = {}   # query_code → bare_code (API内部code)
    _bare_to_wl = {}   # bare_code → watchlist_key
    for _wc in _watchlist:
        _m = _watchlist[_wc]["市场"]
        if _m == "港股":
            _code_str = _wc        # hk06809
            _bare = _wc[2:]        # 06809 — 腾讯API返回的裸code
        elif _m == "美股":
            _code_str = f"us{_wc}"
            _bare = _wc
        elif _wc.startswith("6") or _wc.startswith("688"):
            _code_str = f"sh{_wc}"
            _bare = _wc
        else:
            _code_str = f"sz{_wc}"
            _bare = _wc
        _prefix_map[_code_str] = _bare
        _bare_to_wl[_bare] = _wc
    _wl_raw = _tencent_quote(",".join(_prefix_map.keys()))
    _wl_result = {}
    for _bare, _sc in _bare_to_wl.items():
        if _bare in _wl_raw:
            _v = _wl_raw[_bare]
            _wl_result[_sc] = {
                **_watchlist[_sc],
                "最新价": _v["price"],
                "涨跌幅": _v["change_pct"],
            }
        else:
            _wl_result[_sc] = {**_watchlist[_sc], "error": "腾讯API无数据"}
    # 澜起科技兜底: 如果HK6809没数据，试688008（科创板）
    if "hk06809" in _wl_result and _wl_result["hk06809"].get("error"):
        _fallback = _tencent_quote("sh688008")
        if "688008" in _fallback:
            _v = _fallback["688008"]
            _wl_result["688008"] = {"名称":"澜起科技","市场":"A股","最新价":_v["price"],"涨跌幅":_v["change_pct"]}
            del _wl_result["hk06809"]
    result['监督池'] = _wl_result

    return _ok(result)


# ─── 🆕 9. 中国宏观数据（v21新增）─────────────────────────
def fetch_macro():
    """v21: 中国宏观7项指标最新值"""
    import akshare as ak
    result = {}

    # LPR
    try:
        df = ak.macro_china_lpr()
        if df is not None and len(df) > 0:
            latest = df.tail(1).iloc[0]
            result['LPR_1Y'] = str(latest.get('LPR1Y', 'N/A'))
            result['LPR_5Y'] = str(latest.get('LPR5Y', 'N/A'))
            result['LPR_日期'] = str(latest.get('TRADE_DATE', ''))
    except Exception as e:
        result['_lpr_error'] = str(e)[:100]

    # PMI（数据按月份倒序：index 0 = 最新）
    try:
        df = ak.macro_china_pmi()
        if df is not None and len(df) > 0:
            latest = df.iloc[0]  # 最新行
            result['PMI_制造业'] = str(latest.get('制造业-指数', 'N/A'))
            result['PMI_非制造业'] = str(latest.get('非制造业-指数', 'N/A'))
            result['PMI_日期'] = str(latest.get('月份', ''))
    except: pass

    # CPI年率
    try:
        df = ak.macro_china_cpi_yearly()
        if df is not None and len(df) > 0:
            latest = df.dropna(subset=['今值']).tail(1)
            if len(latest) > 0:
                r = latest.iloc[0]
                result['CPI年率'] = str(r.get('今值', 'N/A'))
                result['CPI_日期'] = str(r.get('日期', ''))
    except: pass

    # M2货币供应
    try:
        df = ak.macro_china_money_supply()
        if df is not None and len(df) > 0:
            latest = df.tail(1).iloc[0]
            result['M2同比'] = str(latest.get('货币和准货币(M2)-同比增长', 'N/A'))
    except: pass

    # 社融
    try:
        df = ak.macro_china_shrzgm()
        if df is not None and len(df) > 0:
            latest = df.tail(1).iloc[0]
            result['社融增量_亿'] = str(latest.get('社会融资规模增量', 'N/A'))
    except: pass

    # GDP年率
    try:
        df = ak.macro_china_gdp_yearly()
        if df is not None and len(df) > 0:
            latest = df.dropna(subset=['今值']).tail(1)
            if len(latest) > 0:
                r = latest.iloc[0]
                result['GDP年率'] = str(r.get('今值', 'N/A'))
                result['GDP_日期'] = str(r.get('日期', ''))
    except: pass

    # 贸易差额
    try:
        df = ak.macro_china_trade_balance()
        if df is not None and len(df) > 0:
            latest = df.dropna(subset=['今值']).tail(1)
            if len(latest) > 0:
                r = latest.iloc[0]
                result['贸易差额_亿美元'] = str(r.get('今值', 'N/A'))
    except: pass

    return _ok(result)


# ─── 每模块超时机制（防止单个 API 卡死整条流水线）───
_MODULE_TIMEOUT = 120  # 秒

class _ModuleTimeout(Exception):
    pass

def _timeout_handler(signum, frame):
    raise _ModuleTimeout("模块执行超时")


# ═══════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════
def main():
    print(f"═══ 预抓取金融市场数据（v30: 每模块120s超时 | QDII场外纳指100/标普500） ═══")
    print(f"时间: {_ts()}\n")

    # 三市场交易日历判定（共享模块）
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from trading_calendar import market_flags
    flags = market_flags()
    a_open = flags["a_open"]
    u_open = flags["u_open"]
    hk_open = flags["hk_open"]
    is_simple = (flags["mode"] == "精简模式")

    if is_simple:
        # 精简模式：三市场均休市，仅执行 RSS 新闻模块
        modules = [
            ("data_news_rss.json", _fetch_rss_news, "全球TOP10 RSS新闻(英+中)"),
        ]
        print(f"📋 精简模式（三市场均休市）: 仅执行 {len(modules)} 个模块（纯新闻）")
    else:
        # 完整模式：按市场开市情况逐模块门控
        modules = []
        if a_open:
            modules.append(("data_market_cn.json",   fetch_market_cn,   "A股指数"))
        if hk_open:
            modules.append(("data_market_hk.json",   fetch_market_hk,   "港股指数"))
        if u_open:
            modules.append(("data_market_global.json", fetch_market_global, "全球指数"))
        # 汇率/商品/债券：24h 市场，完整模式即抓
        modules.append(("data_forex_rate.json",  fetch_forex_rate,  "汇率/商品/债券"))
        if a_open:
            modules.append(("data_valuation.json", fetch_valuation,  "估值数据"))
        if a_open or u_open:
            modules.append(("data_fund.json",       fetch_fund,       "基金净值/溢价"))
        if a_open:
            modules.append(("data_industry.json",    fetch_industry,   "申万+同花顺行业"))
        if a_open or u_open:
            modules.append(("data_holdings.json",    fetch_holdings,   "持仓行情+分红+研报"))
        # RSS 新闻：始终抓取
        modules.append(("data_news_rss.json",       _fetch_rss_news,  "全球TOP10 RSS新闻(英+中)"))
        if a_open:
            modules.append(("data_extra.json",       fetch_extra,      "资金面+QDII+涨停/跌停"))
        status = f"A股:{'✅' if a_open else '❌'} 美股:{'✅' if u_open else '❌'} 港股:{'✅' if hk_open else '❌'}"
        print(f"📋 完整模式: 执行 {len(modules)} 个模块 ({status})")

    successes = 0
    signal.signal(signal.SIGALRM, _timeout_handler)

    for fname, func, label in modules:
        print(f"▶ [{label}] {fname} ...", end=" ", flush=True)
        signal.alarm(_MODULE_TIMEOUT)
        try:
            result = func()
            signal.alarm(0)
            _write(fname, result)
            if result.get("ok"): successes += 1
            else: print("  ⚠️")
        except _ModuleTimeout:
            signal.alarm(0)
            print(f"  ⏰ 超时（>{_MODULE_TIMEOUT}s）")
            _write(fname, _fail(f"模块执行超过{_MODULE_TIMEOUT}s，已跳过"))
        except Exception as e:
            signal.alarm(0)
            print("  ❌")
            traceback.print_exc()
            _write(fname, _fail(e))
        time.sleep(1)
        signal.alarm(0)  # 确保清理

    total = len(modules)
    print(f"\n═══ 完成: {successes}/{total} 个文件成功 ═══")
    if successes == total:
        print("✅ 全部成功，LLM可直接读取JSON数据")
    elif successes >= total - 1:
        print("⚠️ 仅1个文件失败，LLM可用WebSearch补充")
    else:
        print("⚠️ 多个模块失败，建议检查网络后重试")


if __name__ == "__main__":
    main()

