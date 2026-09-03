#!/usr/bin/env python3
"""
预抓取金融市场数据 — 按板块切分为结构化 JSON 文件。
v37: 市场全景A股/美股/港股改先表格后叙述(与全球/大宗/估值统一)；估值快照删顺序列(8→7)+结论改极简2-4字标签；md_to_reader窄屏缩字；QDII简称修复+11指数固定顺序+对比昨日保持

输出文件（10个，均在 data_*.json，默认当前目录）：
  data_market_cn.json       A股5大指数行情           东财push2 + yfinance兜底
  data_market_hk.json       港股恒生+国企指数         东财push2 + yfinance兜底
  data_market_global.json   美股+全球主要指数         东财push2 + yfinance兜底
  data_forex_rate.json      汇率/商品/中美债券        akshare期货 + 中美债收益率
  data_valuation.json       中美核心指数估值+PE/PB分位 雪球蛋卷API
  data_news.json   全球Top20新闻源    Google News RSS 美国一地(40条→去重,LLM选≤10且互不重复) + 联合早报(按缺口补齐至20)
  data_extra.json           资金面+QDII+涨停/跌停  akshare(汇率/资金流/QDII)  v29: 场外QDII纳指100/标普500可申购大额度

每个文件：{"ts":"...", "ok":true/false, "data":..., "error":"..."}
"""

import json, os, sys, signal, traceback, time, re, requests, xml.etree.ElementTree as ET, html
from datetime import datetime, timezone, timedelta

# lxml 容错解析（Google RSS 偶发未转义字符/HTML错误页时 recover=True 不致整份失败）；不可用时回退严格 ET
try:
    from lxml import etree as LET
except ImportError:
    LET = None

# ── 方案C: curl_cffi HTTP/2 补丁 ──
# 东财 push2 端点需要 HTTP/2，标准 requests 仅支持 HTTP/1.1 会静默断连
# 仅对 eastmoney push2 域名使用 curl_cffi 浏览器模拟，其余请求不受影响
try:
    from curl_cffi import requests as _cffi_req
    _orig_get = requests.get
    _H2_DOMAINS = ("push2.eastmoney.com", "push2his.eastmoney.com", "push2delay.eastmoney.com")
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


# ─── 数据源B2: 东方财富 push2 直连（market-live 同款，指数主源） ──
def _em_quote(secid, fields="f43,f44,f45,f46,f47,f48,f57,f58,f60,f169,f170"):
    """东方财富 push2（push2delay）按 secid 直连取指数最新行情。
    借鉴 market-live：A/港/美/全球统一走 push2delay，数据始终最新（收盘后=最新收盘）。
    返回 dict {名称,代码,最新价,涨跌幅,昨收,今开,最高,最低,成交量,成交额} 或 None。
    """
    try:
        url = ("https://push2delay.eastmoney.com/api/qt/stock/get"
               f"?secid={secid}&fields={fields}&invt=2&fltt=2")
        r = requests.get(url, headers={
            "User-Agent": UA,
            "Referer": "https://quote.eastmoney.com/"}, timeout=15)
        j = r.json()
        d = j.get("data") or {}
        price = _num(d.get("f43"))
        if price is None:
            return None
        return {
            "名称": d.get("f58") or secid,
            "代码": d.get("f57") or secid,
            "最新价": price,
            "涨跌幅": _num(d.get("f170")),
            "昨收": _num(d.get("f60")),
            "今开": _num(d.get("f46")),
            "最高": _num(d.get("f44")),
            "最低": _num(d.get("f45")),
            "成交量": _num(d.get("f47")),
            "成交额": _num(d.get("f48")),
        }
    except Exception as e:
        print(f"    ⚠️ 东财 push2 {secid} 失败: {e}")
        return None

# ─── 数据源D: 雪球蛋卷 API（PE/PB/分位/股息率全覆盖） ────────
def _fetch_danjuan_valuation():
    """雪球蛋卷基金估值API — 返回 PE/PB/分位/股息率 全覆盖数据。
    
    API: danjuanfunds.com/djapi/index_eva/dj
    返回 63 个指数，字段: pe, pb, pe_percentile, pb_percentile, yeild(股息率), eva_type
    
    覆盖目标 11 指数(蛋卷1次返回63个, 仅白名单过滤, 零额外网络):
      红利低波(CSIH30269), 中证红利(SH000922), 中证白酒(SZ399997),
      沪深300(SH000300), 中证500(SH000905), 创业板指(SZ399006),
      科创50(SH000688), 恒生科技(HKHSTECH), 中概互联50(CSIH30533),
      纳斯达克100(NDX), 标普500(SP500)
    (固定显示顺序见 prompt: 红利低波→中证红利→中证白酒→沪深300→中证500→创业板指→科创50→恒生科技→中概互联50→纳斯达克100→标普500)
    """
    try:
        r = requests.get("https://danjuanfunds.com/djapi/index_eva/dj",
                        headers={"User-Agent": UA}, timeout=10)
        items = r.json()["data"]["items"]
        
        targets = {
            "CSIH30269": "红利低波",
            "SH000922":  "中证红利",
            "SZ399997":  "中证白酒",      # 新增(用户指定): 行业指数, 蛋卷63返回内零额外网络
            "SH000300":  "沪深300",
            "SH000905":  "中证500",
            "SZ399006":  "创业板指",
            "SH000688":  "科创50",
            "HKHSTECH":  "恒生科技",
            "CSIH30533": "中概互联50",    # 新增(用户指定): 中概/海外互联, 蛋卷63返回内零额外网络
            "NDX":       "纳斯达克100",   # 补齐纳指100估值(当前仅有价格)
            "SP500":     "标普500",
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
                _d = hist.index[-1]
                result[key] = {"最新价": price, "涨跌幅": chg_pct,
                               "日期": _d.strftime("%Y-%m-%d")}
            elif len(close) == 1:
                price = round(float(close.iloc[-1]), 2)
                _d = hist.index[-1]
                result[key] = {"最新价": price, "涨跌幅": None,
                               "日期": _d.strftime("%Y-%m-%d")}
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
    """上证/深证/沪深300/科创50/创业板指 — 东财push2主源 + yfinance兜底"""
    WANTED = [
        ("上证指数",   "1.000001", "000001.SS"),
        ("深证成指",   "0.399001", "399001.SZ"),
        ("沪深300",    "1.000300", "000300.SS"),
        ("科创50",     "1.000688", "000688.SS"),
        ("创业板指",   "0.399006", "399006.SZ"),
    ]
    rows, yf_map = [], {}
    for name, secid, yf_tk in WANTED:
        q = _em_quote(secid)
        if q and q.get("最新价") is not None:
            rows.append({
                "指数": name, "代码": secid.split(".")[-1],
                "最新价": q["最新价"], "涨跌幅": q["涨跌幅"],
                "今开": q.get("今开"), "最高": q.get("最高"),
                "最低": q.get("最低"), "成交量": q.get("成交量"),
                "成交额": q.get("成交额"), "source": "东财push2",
            })
        else:
            yf_map[name] = yf_tk
    if yf_map:
        yf_data = _yf_fallback(yf_map)
        for name, secid, yf_tk in WANTED:
            if name in yf_map and name in yf_data:
                d = yf_data[name]
                rows.append({"指数": name, "代码": yf_tk,
                             "最新价": d["最新价"], "涨跌幅": d["涨跌幅"],
                             "source": "yfinance兜底"})
            elif name in yf_map:
                rows.append({"指数": name, "代码": yf_tk,
                             "error": "东财+yfinance均失败"})
    return _ok(rows)


# ─── 2. 港股指数行情（不变）──────────────────────────────────
def fetch_market_hk():
    """恒生指数 + 恒生中国企业指数 — 东财push2主源 + yfinance兜底"""
    WANTED = [
        ("恒生指数", "100.HSI", "^HSI"),
        ("恒生中国企业指数", "100.HSCEI", "^HSCE"),
        ("恒生科技指数", "124.HSTECH", "^HSTECH"),
    ]
    rows, yf_map = [], {}
    for name, secid, yf_tk in WANTED:
        q = _em_quote(secid)
        if q and q.get("最新价") is not None:
            rows.append({
                "指数": name, "代码": secid,
                "最新价": q["最新价"], "涨跌幅": q["涨跌幅"],
                "今开": q.get("今开"), "最高": q.get("最高"),
                "最低": q.get("最低"), "source": "东财push2",
            })
        else:
            yf_map[name] = yf_tk
    if yf_map:
        yf_data = _yf_fallback(yf_map)
        for name, secid, yf_tk in WANTED:
            if name in yf_map and name in yf_data:
                d = yf_data[name]
                rows.append({"指数": name, "代码": yf_tk,
                             "最新价": d["最新价"], "涨跌幅": d["涨跌幅"],
                             "source": "yfinance兜底"})
            elif name in yf_map:
                rows.append({"指数": name, "代码": yf_tk,
                             "error": "东财+yfinance均失败"})
    return _ok(rows)


# ─── 3. 全球主要指数（东财push2主源 + yfinance兜底）──
def fetch_market_global():
    """美股(DJI/SPX/IXIC) + 全球(日经/KOSPI/STOXX) — 东财push2主源 + yfinance兜底"""
    WANTED = [
        ("道琼斯工业",   "100.DJIA", "^DJI"),
        ("标普500",      "100.SPX",   "^GSPC"),
        ("纳斯达克综合", "100.NDX",  "^IXIC"),
        ("日经225",      "100.N225",  "^N225"),
        ("KOSPI",        "100.KS11",   "^KS11"),
        ("STOXX 600",    "100.SXXP",   "^SXXP"),
        ("德国DAX",      "100.GDAXI", "^GDAXI"),
        ("英国富时100",  "100.FTSE",  "^FTSE"),
        ("法国CAC40",    "100.FCHI",  "^FCHI"),
    ]
    result, yf_map = {}, {}
    for name, secid, yf_tk in WANTED:
        q = _em_quote(secid)
        if q and q.get("最新价") is not None:
            result[name] = {"名称": name, "代码": secid,
                            "最新价": q["最新价"], "涨跌幅": q["涨跌幅"],
                            "source": "东财push2"}
        else:
            yf_map[name] = yf_tk
    if yf_map:
        yf_data = _yf_fallback(yf_map)
        for name, secid, yf_tk in WANTED:
            if name in yf_map and name in yf_data:
                d = yf_data[name]
                result[name] = {"名称": name, "代码": yf_tk,
                                "最新价": d["最新价"], "涨跌幅": d["涨跌幅"],
                                "source": "yfinance兜底"}
            elif name in yf_map and name not in result:
                result[name] = {"名称": name, "代码": yf_tk,
                                "error": "东财+yfinance均失败", "_stale": True}
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


# ─── 5. 估值数据（东财push2 + yfinance，删新浪）────
def fetch_valuation():
    """A股7大指数价格 + 美股估值 + 恒生科技 + 且慢PE/PB分位"""
    result = {}

    # ── A股指数价格（东财push2，单一来源）──
    a_indices = [
        ("上证指数", "1.000001"), ("深证成指", "0.399001"), ("沪深300", "1.000300"),
        ("科创50", "1.000688"), ("创业板指", "0.399006"),
        ("中证A500", "1.000510"), ("中证红利", "1.000922"),
    ]
    a_list = []
    for name, secid in a_indices:
        q = _em_quote(secid)
        if q and q.get("最新价") is not None:
            a_list.append({"指数": name, "代码": secid.split(".")[-1],
                           "最新价": q["最新价"], "涨跌幅": q["涨跌幅"]})
    result["a_share"] = a_list if a_list else {"error": "东财push2无数据"}

    # ── 美股估值（东财push2主源 → yfinance兜底）──
    us_val_secids = {"纳斯达克100": "100.NDX100", "标普500": "100.SPX"}
    us_val_yf = {"纳斯达克100": "^NDX", "标普500": "^GSPC"}
    _us_val_yf = _yf_fallback(us_val_yf)
    us_list = []
    for name, sym in [("纳斯达克100", ".NDX"), ("标普500", ".INX")]:
        entry = {"指数": name, "ticker": sym}
        q = _em_quote(us_val_secids[name])
        if q and q.get("最新价") is not None:
            entry["最新价"] = q["最新价"]; entry["涨跌幅"] = q["涨跌幅"]; entry["source"] = "东财push2"
        elif name in _us_val_yf:
            d = _us_val_yf[name]
            entry["最新价"] = d["最新价"]; entry["涨跌幅"] = d["涨跌幅"]; entry["source"] = "yfinance"
        else:
            entry["note"] = "数据暂不可得"
        us_list.append(entry)
    result["us"] = us_list

    # ── 恒生科技（东财push2）──
    q_hk = _em_quote("124.HSTECH")
    if q_hk and q_hk.get("最新价") is not None:
        result["hk_tech"] = {"指数":"恒生科技","最新价":q_hk["最新价"],
                             "涨跌幅":q_hk["涨跌幅"],
                             "note": "PE/PB分位需WebSearch（且慢无此指数）"}
    else:
        result["hk_tech"] = {"指数":"恒生科技","note":"需WebSearch"}

    # ── PE/PB分位+股息率: 雪球蛋卷 API ──
    danjuan = _fetch_danjuan_valuation()
    result["danjuan_valuation"] = danjuan if danjuan else {"note": "雪球蛋卷API失败，需WebSearch"}

    return _ok(result)




# ═══════════════════════════════════════════════════════════════
# 🆕 v22 数据源: 新浪汇率 + akshare资金面 + Google News RSS(英+中) + 宏观扩展(核心PCE/BDI/SOX等)
# ═══════════════════════════════════════════════════════════════

def _shorten_qdii_name(name):
    """场外QDII短名：公司名 + 纳指100/标普500 + 小写份额字母(末尾)。规则驱动。

    修复 v35 及以前 bug：旧逻辑仅在"字母位于字符串末尾"时才能提取份额字母，
    而基金全称多为 `…(QDII)C人民币`（份额字母在中间、币种在后），导致：
      - 末尾是"币" → 提取不到份额字母；
      - 公司名未剔除"人民币/美元"与份额字母 → 残留 `C人民币` 截断为 `建信C人`
      → 输出 `建信C人纳指100`（错误）。
    现改为：先剔币种 → 锚定末尾或"X类"提取份额字母(避开 QDII/ETF 内部字母) → 末尾小写。
    """
    s = str(name)
    # 1) 剔除币种（人民币/美元/港币/欧元）
    _cur = re.search(r"(人民币|美元|港币|欧元)", s)
    if _cur:
        s = s.replace(_cur.group(1), "")
    # 2) 提取份额字母 A-E（锚定末尾，或"X类"；避开 QDII 的 D、ETF 的 E 等内部字母）
    _m = re.search(r"([A-Ea-e])\s*类?\s*$", s)   # 末尾(可带"类")
    if not _m:
        _m = re.search(r"([A-Ea-e])\s*类", s)     # 或 "X类"
    _letter = _m.group(1).lower() if _m else ""
    if _m:
        s = s[:_m.start()] + s[_m.end():]
    # 3) 核心标的
    if re.search(r"纳斯达克100|纳指100", s, re.I):
        _core = "纳指100"
    elif re.search(r"纳斯达克", s, re.I):
        _core = "纳指"
    elif re.search(r"标普500|标普", s, re.I):
        _core = "标普500"
    else:
        _core = ""
    # 4) 公司名（剔除核心/冗余词，截前4字）
    _company = re.sub(
        r"纳斯达克100|纳指100|纳斯达克|标普500|标普|QDII|\(.*?\)|（.*?）|ETF|联接|基金|指数|发起|证券|投资|\s+",
        "", s, flags=re.I,
    ).strip()[:4]
    if not _core:
        return _company or str(name)
    return f"{_company}{_core}{_letter}"


def _normalize_qdii_prev(prev):
    """兼容新旧两种 qdii_prev.json 结构，统一规整为 {代码: {...}} 字典。

    旧格式(历史残留, v23~v29 前写入): {"ts":..., "场内ETF":[{代码,溢价率}...], "场外QDII":[{代码,日累计限定金额}...]}
    新格式(v33+ 写入):               {"日期":..., "场内ETF":{代码:{溢价率,日期}}, "场外QDII":{代码:{日累计限定金额,日期}}}
    旧格式的写逻辑已在重构中丢失，仅残留文件；读取端必须兼容，否则 list.get() 会崩。
    """
    _etf_raw = (prev or {}).get("场内ETF", {})
    _qdii_raw = (prev or {}).get("场外QDII", {})

    def _to_dict(raw, key_field="代码"):
        if isinstance(raw, dict):
            return raw
        _out = {}
        if isinstance(raw, list):
            for _item in raw:
                if isinstance(_item, dict) and key_field in _item:
                    _out[_item[key_field]] = _item
        return _out

    return _to_dict(_etf_raw), _to_dict(_qdii_raw)


# ── 热门全球 QDII 关注（固定清单，默认 C 类份额；东财代码 + 内置简称）──
HOT_GLOBAL_QDII = [
    ("002891", "华夏移动互联"),       # 华夏移动互联混合人民币
    ("008254", "华宝致远"),           # 华宝致远混合(QDII)C
    ("014002", "浦银安盛全球"),       # 浦银安盛全球智能科技(QDII)C
    ("015016", "华安德国DAX"),        # 华安德国(DAX)联接(QDII)C
    ("015202", "汇添富全球移动互联"), # 汇添富全球移动互联混合(QDII)人民币C
    ("016702", "银华海外数字经济"),   # 银华海外数字经济量化选股混合发起式(QDII)C
    ("018147", "建信新兴市场"),       # 建信新兴市场混合(QDII)C
    ("008706", "建信富时100"),        # 建信富时100指数(QDII)C人民币
    ("021277", "广发全球精选"),       # 广发全球精选股票(QDII)人民币C
    ("021540", "华安法国CAC40"),      # 华安法国CAC40ETF发起式联接(QDII)C
    ("021842", "国富全球科技互联"),   # 国富全球科技互联混合(QDII)人民币C
]


def fetch_extra():
    """QDII监测(腾讯API实时价+东方财富HTTP净值) + 场外申购额度(Nasdaq100/S&P500可申购大额度 + 热门全球QDII关注) + USD/CNH汇率；资金面/两融/涨跌停已移除"""
    import akshare as ak
    result = {}
    today_str = datetime.now(TZ_CN).strftime("%Y%m%d")

    # ── 1. USD/CNH 汇率（新浪离岸即期 → yfinance → 外汇局中间价末位兜底）──
    # 口径统一：同表 WTI/黄金等均为市场价，汇率也用离岸即期市场价（CNH 24h 交易，
    # 07:00 出报告时可取隔夜最新价；中间价 9:15 才公布且有 ±2% 偏离，不作主价格）
    usdcnh_ok = False

    # 主源：新浪财经 fx_susdcnh（离岸人民币即期，买卖报价中值）
    try:
        _r = requests.get(
            "https://hq.sinajs.cn/list=fx_susdcnh",
            headers={"Referer": "https://finance.sina.com.cn", "User-Agent": UA},
            timeout=15,
        )
        if _r.status_code == 200:
            _m = re.search(r'fx_susdcnh="([^"]*)"', _r.text)
            if _m:
                _parts = _m.group(1).split(",")
                # 0:时间 1:买价 2:卖价 3:昨收 4:成交量 5:最新价 ... 9:名称 ... 末位:日期
                if len(_parts) > 5 and _m.group(1).strip():
                    try:
                        _bid, _ask = float(_parts[1]), float(_parts[2])
                        if _bid > 0 and _ask > 0:
                            result["USD_CNH"] = round((_bid + _ask) / 2, 4)
                            result["USD_CNH_日期"] = _parts[-1] if _parts[-1] else ""
                            result["USD_CNH_时间"] = _parts[0]
                            result["USD_CNH_来源"] = "新浪财经·离岸即期(CNH)"
                            usdcnh_ok = True
                    except (ValueError, IndexError):
                        pass
    except Exception as e:
        print(f"    新浪 USDCNH 失败: {e}")

    # 兜底1：yfinance USDCNH=X（同为离岸即期市场价）
    if not usdcnh_ok:
        yf_fx = _yf_fallback({"USD_CNH": "USDCNH=X"})
        if yf_fx.get("USD_CNH"):
            result["USD_CNH"] = yf_fx["USD_CNH"]["最新价"]
            result["USD_CNH_日期"] = ""
            result["USD_CNH_来源"] = "yfinance·离岸即期(CNH)"
            usdcnh_ok = True

    # 末位兜底：外汇局中间价（官方锚定价、非市场成交价，来源字段明确标注防误导）
    if not usdcnh_ok:
        try:
            _df_fx = ak.currency_boc_safe()
            if _df_fx is not None and len(_df_fx) > 0:
                _latest = _df_fx.iloc[-1]
                _usd_str = str(_latest.get("美元", ""))
                if _usd_str:
                    # 央行中间价以 "元/100外币" 计，如 679.89 → 6.7989
                    result["USD_CNH"] = round(float(_usd_str) / 100.0, 4)
                    result["USD_CNH_日期"] = str(_latest.get("日期", ""))
                    result["USD_CNH_来源"] = "外汇局官方中间价(非市场价)"
                    usdcnh_ok = True
        except Exception as e:
            print(f"    currency_boc_safe 失败: {e}")

    # 注：资金面(南下/北向/涨跌家数)、两融、涨停/跌停 已移除（prompt 不再消费，且为卡顿主因）

    # ── v24方案: QDII监测 — 腾讯API实时价 + 东方财富HTTP净值（不依赖 fund_etf_spot_em）──
    qdii_data = {"场内ETF": [], "场外QDII": [], "场外QDII主动": []}
    # ── 跨运行昨日基准（qdii_prev.json；工作流已 git add 持久化）──
    _repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _prev_path = os.path.join(_repo_root, "qdii_prev.json")
    _prev = {}
    try:
        with open(_prev_path, encoding="utf-8") as _f:
            _prev = json.load(_f)
    except Exception:
        _prev = {}
    _prev_etf, _prev_qdii = _normalize_qdii_prev(_prev)  # 兼容新旧两种结构
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
        _prev_pr = _prev_etf.get(_code, {}).get("溢价率")
        _pr_diff = round(_pr - _prev_pr, 2) if (_pr is not None and _prev_pr is not None) else None
        qdii_data["场内ETF"].append({
            "代码": _code, "名称": _etf_names.get(_code,""),
            "最新价": _mp, "涨跌幅": _cp,
            "最新净值": _nav, "净值日期": _nav_d, "溢价率": _pr,
            "溢价率对比昨日": _pr_diff,
            "溢价率来源": "腾讯价+东方财富净值",
        })
    # 场外QDII申购额度（纳指100/标普500，可申购且额度较大的6条）
    # ── 场外QDII：共用行构建 + 排序（不限购[开放申购]置顶，其余按日累计限额降序）──
    def _mk_qdii_row(_r, _code, _short=None):
        import pandas as pd
        _lim = _r['日累计限定金额']
        _lim_val = round(float(_lim), 2) if pd.notna(_lim) and _lim else 0
        _unlimited = (str(_r['申购状态']) == '开放申购')
        _pv = _prev_qdii.get(_code, {})
        _pv_lim = _pv.get("日累计限定金额")
        _pv_unlimited = _pv.get("不限购", False)
        if _unlimited or _pv_unlimited or _pv_lim is None:
            _diff = None
        else:
            _diff = round(_lim_val - float(_pv_lim), 2)
        return {
            "代码": _code,
            "简称": str(_r['基金简称']),
            "名称_短": _short or _shorten_qdii_name(str(_r['基金简称'])),
            "最新净值": str(_r['最新净值/万份收益']),
            "净值日期": str(_r['最新净值/万份收益-报告时间']),
            "申购状态": str(_r['申购状态']),
            "日累计限定金额": _lim_val,
            "不限购": _unlimited,
            "限额对比昨日": _diff,
        }

    def _qdii_sort_key(x):
        # 不限购置顶（组内按限额降序）；限大额/其余按限额降序
        return (0 if x.get("不限购") else 1, -(x.get("日累计限定金额") or 0))

    try:
        import pandas as pd
        _df = ak.fund_purchase_em()
        _by_code = {str(_r['基金代码']): _r for _, _r in _df.iterrows()}

        # 1) 纳指系/标普系 两组各取前5（类型含 QDII-FOF：天弘标普500发起即为该类型，
        #    v39 前只放行"海外"导致 007721/007722 被过滤、场外表长期无标普500代表）
        _seen = set()
        _picked = []
        for _kw, _grp_cap in [("纳指|纳斯达克100", 5), ("标普500", 5)]:
            _grp = []
            _mask = (
                _df['基金简称'].str.contains(_kw, na=False)
                & _df['基金类型'].str.contains('海外|QDII', na=False)
                & ~_df['基金简称'].str.contains('美元', na=False)
                & (_df['申购状态'] != '场内交易')
                & (_df['申购状态'] != '暂停申购')
            )
            for _, _r in _df[_mask].iterrows():
                _c = str(_r['基金代码'])
                if _c in _seen: continue
                _seen.add(_c)
                _row = _mk_qdii_row(_r, _c)
                _grp.append(_row)
            _grp.sort(key=_qdii_sort_key)
            _picked.extend(_grp[:_grp_cap])
        # 合并后统一排序（不限购置顶→限额降序），各5只共10只
        _picked.sort(key=_qdii_sort_key)
        qdii_data["场外QDII"] = _picked

        # 2) 新增：热门全球 QDII 关注（固定清单，默认 C 类，全部展示，不限购置顶）
        for _code, _short in HOT_GLOBAL_QDII:
            _r = _by_code.get(_code)
            if _r is None:
                qdii_data["场外QDII主动"].append({
                    "代码": _code, "简称": "", "名称_短": _short,
                    "最新净值": "", "净值日期": "", "申购状态": "无数据",
                    "日累计限定金额": 0, "不限购": False, "限额对比昨日": None,
                })
                continue
            qdii_data["场外QDII主动"].append(_mk_qdii_row(_r, _code, _short=_short))
        if qdii_data["场外QDII主动"]:
            qdii_data["场外QDII主动"].sort(key=_qdii_sort_key)
    except Exception as e:
        qdii_data["_场外_error"] = str(e)[:100]
    # ── 写回昨日基准快照（供下次运行对比；工作流已 commit 持久化）──
    try:
        _snap = {
            "日期": today_str,
            "场内ETF": {e["代码"]: {"溢价率": e.get("溢价率"), "日期": today_str} for e in qdii_data["场内ETF"]},
            "场外QDII": {f["代码"]: {"日累计限定金额": f.get("日累计限定金额"), "不限购": f.get("不限购"), "日期": today_str} for f in qdii_data["场外QDII"]},
            "场外QDII主动": {f["代码"]: {"日累计限定金额": f.get("日累计限定金额"), "不限购": f.get("不限购"), "日期": today_str} for f in qdii_data["场外QDII主动"]},
        }
        with open(_prev_path, "w", encoding="utf-8") as _f:
            json.dump(_snap, _f, ensure_ascii=False, indent=2)
    except Exception as _e:
        print(f"    qdii_prev.json 写回失败: {_e}")
    result['QDII_监测'] = qdii_data

    return _ok(result)


# ─── 数据源H/I: Top20 双源(谷歌美国主流+联合早报) + 深度观察(联合早报原文) ──────
# 联合早报 RSS 仅抓取一次并缓存，Top20 后10 与 深度专栏(数据源I) 复用
_ZAOBAI_CACHE = None

def _fetch_zaobao_raw():
    """抓取联合早报·中港台即时 RSS（三实例兜底：hub.slarker.me 主 → rsshub.rssforever.com 备1 → rsshub.ktachibana.party 备2；
    Top20 与 深度观察专栏复用）。顺序尝试，第一个返回**昨天或今天内容**的源即采用并停止（早6点运行，凌晨新闻少，
    前一天内容属正常，仅拦三天前旧缓存/镜像）。每个源无论成败均打印财联社风格状态日志，便于 Actions 排查。"""
    global _ZAOBAI_CACHE
    if _ZAOBAI_CACHE is not None:
        return _ZAOBAI_CACHE
    import email.utils as _eu
    def _bj_date(pub):
        try:
            dt = _eu.parsedate_to_datetime(pub or "")
            if dt is not None:
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(TZ_CN).date()
        except Exception:
            return None
        return None
    # 三实例顺序兜底（同路径换主机）
    SOURCES = [
        "https://hub.slarker.me/zaobao/realtime/china",
        "https://rsshub.rssforever.com/zaobao/realtime/china",
        "https://rsshub.ktachibana.party/zaobao/realtime/china",
    ]
    today_cn = datetime.now(TZ_CN).date()
    yesterday_cn = today_cn - timedelta(days=1)
    notes = []      # 每源状态记录（无论成败）
    _log_prefix = "    [联合早报RSS] 源状态:"
    for url in SOURCES:
        _host = re.sub(r"^https?://", "", url).split("/")[0]
        try:
            # 连接 8s / 读取 25s，避免云环境对不可达主机长时间挂起
            r = requests.get(url, headers={"User-Agent": UA}, timeout=(8, 25))
            if r.status_code != 200:
                notes.append(f"❌ {_host} → HTTP {r.status_code}")
                continue
            tree = ET.fromstring(r.content)
            out = []
            for item in tree.findall(".//item"):
                title_el = item.find("title")
                desc_el = item.find("description")
                link_el = item.find("link")
                pub_el = item.find("pubDate")
                title = title_el.text if title_el is not None else ""
                title = re.sub(r"\s+", " ", title).strip()[:100]
                desc = desc_el.text if desc_el is not None else ""
                desc = re.sub(r"<[^>]+>", " ", desc)
                desc = html.unescape(desc)
                desc = re.sub(r"\s+", " ", desc).strip()
                out.append({
                    "title": title,
                    "desc": desc,
                    "source": "联合早报",
                    "link": link_el.text if link_el is not None else "",
                    "pubDate": pub_el.text if pub_el is not None else "",
                })
            if not out:
                notes.append(f"❌ {_host} → 200但无<item>(疑似HTML错误页)")
                continue
            # 日期校验：至少一个条目为北京时间昨天或今天即可（早6点运行凌晨新闻少，
            # 前一天内容属正常；仅拦三天前旧缓存/镜像）→ 不满足则切备用源
            if not any(_bj_date(it.get("pubDate", "")) in (today_cn, yesterday_cn) for it in out):
                notes.append(f"❌ {_host} → 无昨天/今天内容(疑似旧缓存/镜像)")
                continue
            notes.append(f"✅ {_host} → OK({len(out)}条) 采纳")
            print(_log_prefix, " | ".join(notes))
            _ZAOBAI_CACHE = out
            return out
        except Exception as _e:
            notes.append(f"❌ {_host} → {type(_e).__name__}: {str(_e)[:60]}")
    print(_log_prefix, " | ".join(notes) if notes else "无候选源尝试")
    print("    [联合早报RSS] 全部候选源失败")
    _ZAOBAI_CACHE = []
    return []


def _fetch_rss_other():
    """Top20 双源：谷歌美国一地抓40条(去重,LLM精选≤10且互不重复) + 联合早报最新10条。
    谷歌：仅美国一地(hl=en-US)一次抓40条，失败/空结果指数退避重试3次（应对间歇限流/429/非法XML）；
    解析带 HTTP 状态检查 + lxml recover 容错；主源仍失败则兜底谷歌英国区（同 TOPIC 换 hl=en-GB&gl=GB&ceid=GB:en），
    再失败由财联社/格隆汇补位；
    去重后交给LLM精选≤10(英译中)，LLM 输出条目必须互不重复，候选不足则按实际条数输出由财联社/格隆汇补位；
    早报：联合早报中港台即时（hub.slarker.me 主 + rsshub.rssforever.com 备），取最新10条。"""
    TOPIC = "CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtVnVHZ0pWVXlnQVAB"
    MAX_PER = 40

    def _parse(url):
        r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
        if r.status_code != 200:
            # 429/403 等错误页不再被当 XML 解析（根因 a）
            raise RuntimeError(f"HTTP {r.status_code}")
        # lxml recover 容错：个别非法字符（未转义 & 等）不再导致整份 feed 解析失败（根因 b）
        if LET is not None:
            tree = LET.fromstring(r.content, parser=LET.XMLParser(recover=True))
        else:
            tree = ET.fromstring(r.content)
        out = []
        for item in tree.findall(".//item"):
            source_el = item.find("source")
            source = source_el.text if source_el is not None else ""
            title_el = item.find("title")
            desc_el = item.find("description")
            link_el = item.find("link")
            pub_el = item.find("pubDate")
            title = title_el.text if title_el is not None else ""
            title = re.sub(r"\s*[-–]\s*" + re.escape(source) + r"\s*$", "", title).strip()[:100]
            title = html.unescape(title)
            desc = desc_el.text if desc_el is not None else ""
            desc = re.sub(r"<[^>]+>", " ", desc).strip()[:250]
            desc = html.unescape(desc)
            out.append({
                "title": title,
                "desc": desc,
                "source": source,
                "link": link_el.text if link_el is not None else "",
                "pubDate": pub_el.text if pub_el is not None else "",
                "region": "美国",
            })
            if len(out) >= MAX_PER:
                break
        return out

    # 谷歌：美国一地 30 条；失败或空结果时指数退避重试（2s/4s，共3次），应对间歇限流
    items_google = []
    url = (f"https://news.google.com/rss/topics/{TOPIC}"
           f"?hl=en-US&gl=US&ceid=US:en")
    for _attempt in range(3):
        try:
            items_google = _parse(url)
            if items_google:
                print(f"    [谷歌新闻·美国] 第{_attempt+1}次成功，获取 {len(items_google)} 条")
                break
            print(f"    [谷歌新闻·美国] 第{_attempt+1}次返回空，重试...")
        except Exception as _e:
            print(f"    [谷歌新闻·美国] 第{_attempt+1}次失败: {_e}")
        if _attempt < 2:
            time.sleep(2 * (_attempt + 1))
    else:
        print("    [谷歌新闻·美国] 3 次均失败/为空，尝试英国区兜底...")

    # 谷歌主源（美国区）失败 → 兜底：谷歌英国区（同一商业 TOPIC，换地域参数 hl=en-GB&gl=GB&ceid=GB:en）
    if not items_google:
        _UK_URL = (f"https://news.google.com/rss/topics/{TOPIC}"
                   f"?hl=en-GB&gl=GB&ceid=GB:en")
        for _attempt in range(2):
            try:
                _uk = _parse(_UK_URL)
                if _uk:
                    for _it in _uk:
                        _it["region"] = "英国"
                    items_google = _uk[:MAX_PER]
                    print(f"    [谷歌新闻·英国] 第{_attempt+1}次成功，获取 {len(items_google)} 条")
                    break
                print(f"    [谷歌新闻·英国] 第{_attempt+1}次返回空，重试...")
            except Exception as _e:
                print(f"    [谷歌新闻·英国] 第{_attempt+1}次失败: {_e}")
            if _attempt < 1:
                time.sleep(2)
        if not items_google:
            print("    [谷歌新闻·英国] 兜底也失败，由财联社/格隆汇补位")

    # 标题去重（归一化：去源后缀/标点，仅留字母数字与汉字后小写比对）
    def _norm(t):
        t = re.sub(r"<[^>]+>", " ", t)
        t = re.sub(r"[^\w\u4e00-\u9fff]+", "", t).lower()
        return t
    _raw_cnt = len(items_google)
    seen, deduped = set(), []
    for it in items_google:
        key = _norm(it["title"])
        if key and key not in seen:
            seen.add(key)
            deduped.append(it)
    _dup_cnt = _raw_cnt - len(deduped)
    items_google = deduped
    print(f"    [谷歌新闻·美国] 去重后 {len(items_google)} 条（原始 {_raw_cnt} 条，丢弃重复 {_dup_cnt} 条）")

    # 联合早报：取最新 10 条（feed 已按时间倒序；长文留给深度专栏独立源）
    items_zaobao = _fetch_zaobao_raw()[:10]
    for _z in items_zaobao:
        if len(_z.get("desc", "")) > 300:
            _z["desc"] = _z["desc"][:300] + "…"

    return _ok({
        "total": len(items_google) + len(items_zaobao),
        "google_total": len(items_google),
        "zaobao_total": len(items_zaobao),
        "items_google": items_google,
        "items_zaobao": items_zaobao,
    })


# ─── 数据源I: 联合早报原文 → 深度观察专栏独立源（仅精简模式） ──────
def _fetch_rss_deep():
    """深度观察专栏（仅精简模式消费）：联合早报一源双职责（Top10 + 深度观察候选）。
    从缓存条目的第 11 条起（避开 Top20 前 10，防同条重复+前10已截断到300字）取 ≤10 条
    候选形成 items_deep 数组（保持 feed 时间倒序、不做长度排序；desc 未截断），
    由 LLM 自主选 1 篇原文直出（优先与当日 Top20 互补/不同角度，其次最值得当下阅读）。
    取消 >700 字硬阈值与"取最长"确定性规则（2026-08-30 曾因阈值卡死、又因取最长导致
    连续两天同篇）；三源均不可用（缓存为空）才留空，由 prompt 输出「深度观察：今日暂停」。"""
    zaobao = _fetch_zaobao_raw()
    tail = zaobao[10:]  # 前 10 条留给 Top20 联合早报块
    if not tail:
        # 条目不足 11 条时回退：从全部条目取（feed 时间倒序，最新优先）
        tail = zaobao
    items_deep = tail[:10]
    if items_deep:
        print(f"    [联合早报] 深度观察候选 {len(items_deep)} 条"
              f"（首条《{items_deep[0].get('title', '')[:40]}》…）")
    else:
        print("    [联合早报] 深度观察无候选（三源均不可用），今日暂停")
    # 联合早报三源均不可用则当日深度专栏留空（items_deep=[]），由 prompt 输出「深度观察：今日暂停」
    return _ok({"total": len(items_deep), "items_deep": items_deep})

# ─── 数据源J: 财联社 RSS（多实例兜底：hub.slarker.me 主 + 多个 RSSHub 公共实例备用）────
def _fetch_cls_rss_once(url, source_name="财联社"):
    """抓取单个 RSS 源（财联社 / 格隆汇通用），解析全部 <item>（不过滤当天）。
    source_name 用于标记来源，便于合并后区分与当天过滤容错。
    返回 (items, ok, note)：ok=True 表示成功取到 <item>；note 用于日志诊断（HTTP状态/异常原因）。"""
    def _local(tag):
        return tag.split('}')[-1] if '}' in tag else tag

    def _field(elem, name):
        for child in elem:
            if _local(child.tag) == name:
                return (child.text or '').strip()
        return ''

    try:
        # 连接 8s / 读取 25s，避免云环境对不可达主机长时间挂起
        r = requests.get(url, headers={"User-Agent": UA}, timeout=(8, 25))
        if r.status_code != 200:
            # 非 200（如 503 宕机页、403 屏蔽）记为失败，便于日志定位
            return [], False, f"HTTP {r.status_code}"
        r.encoding = "utf-8"
        root = ET.fromstring(r.content)
        out = []
        for item in root.iter():
            if _local(item.tag) != 'item':
                continue
            title = _field(item, 'title')
            desc = _field(item, 'description')
            pub = _field(item, 'pubDate')
            link = _field(item, 'link')
            cat = _field(item, 'category')
            summary = re.sub(r"<[^>]+>", " ", desc)
            summary = html.unescape(summary)
            summary = re.sub(r"\s+", " ", summary).strip()
            out.append({
                "title": title[:120],
                "summary": summary[:400],
                "pubDate": pub,
                "link": link,
                "category": cat,
                "source": source_name,
            })
        if not out:
            # 返回了 200 但无 <item>（多半是 RSSHub 欢迎页/HTML 错误页）
            return [], False, "200但无<item>(疑似HTML错误页)"
        return out, True, f"OK({len(out)})"
    except Exception as e:
        return [], False, f"{type(e).__name__}: {e}"


# ── 持仓聚焦：行业（概念）关键词池（由核心持仓 + 监督池标的归并）──
# 新闻 title+summary 命中任一关键词即打上对应行业标签 industry_match，
# 数据侧限定 LLM 候选（仅 industry_match 非空条目可用于持仓聚焦），杜绝编造/选无关新闻。
HOLDINGS_INDUSTRY_GROUPS = [
    ("半导体/AI芯片", ["半导体", "芯片", "晶圆", "光刻", "制程", "存储芯片", "DRAM", "NAND", "GPU", "AI芯片", "国产替代", "封测", "中芯国际", "寒武纪", "兆易创新", "北方华创", "三安光电", "澜起科技", "摩尔线程", "豪威", "闻泰"]),
    ("AI算力/光模块", ["光模块", "光通信", "CPO", "AI服务器", "算力", "数据中心", "IDC", "英伟达", "Blackwell", "液冷", "800G", "1.6T", "工业富联", "中际旭创", "新易盛"]),
    ("银行", ["银行", "息差", "净息差", "存款利率", "LPR", "降准", "房贷", "个贷", "信贷", "招行", "招商银行", "农业银行", "工商银行", "宁波银行", "汇丰"]),
    ("券商/金融", ["券商", "证券", "投行", "两融", "印花税", "成交额", "资本市场", "东方财富", "中信证券"]),
    ("电力/公用事业", ["电力", "电网", "特高压", "发电", "绿电", "水电", "电价", "输配电", "长江电力", "三峡", "变压器", "电力设备"]),
    ("红利/高股息", ["红利", "高股息", "股息率", "分红", "回购", "中证红利", "红利低波", "高分红", "险资增持"]),
    ("白酒/消费", ["白酒", "茅台", "五粮液", "泸州老窖", "今世缘", "牛栏山", "动销", "批价", "酒企"]),
    ("新能源/光伏/储能", ["光伏", "组件", "硅料", "硅片", "电池片", "储能", "锂电", "宁德时代", "隆基", "通威", "阳光电源", "爱旭", "钙钛矿", "风电", "海上风电", "装机", "BC电池"]),
    ("汽车/新能源车", ["新能源车", "电动车", "比亚迪", "长安汽车", "三花", "热管理", "智驾", "智能驾驶", "电驱", "整车", "汽车出口", "机器人"]),
    ("消费电子/苹果链", ["消费电子", "苹果", "iPhone", "AI眼镜", "MR", "立讯", "歌尔", "领益", "海康", "安防", "AR/VR", "代工"]),
    ("有色/资源/煤炭", ["铜", "黄金", "有色", "矿业", "紫金", "铜陵", "稀土", "煤炭", "煤价", "神华", "金属价格"]),
    ("化工", ["化工", "MDI", "万华", "农药", "聚氨酯", "化工品", "扬农"]),
    ("医药", ["医药", "创新药", "CXO", "药明", "医疗器械", "鱼跃", "集采", "医保", "GLP-1", "减肥药"]),
    ("航运/物流", ["航运", "油运", "集装箱", "运价", "BDI", "中远海控", "招商南油", "顺丰", "物流", "快递"]),
    ("美股宽基", ["纳斯达克", "纳指", "标普500", "标普", "美股", "美联储", "降息", "美债", "道指", "QQQM", "SPY"]),
]


def fetch_cls_zaobao():
    """财联社 + 格隆汇 RSS 抓取，合并去重后供市场全景简述 + 持仓聚焦。
    两组独立抓取后合并：telegraph 组优先 hub.slarker.me/cls/telegraph，失败切 rsshub.rssforever.com/cls/telegraph，
    depth/1000 组同理；组内命中即止（hub 主 → rsshub 备），某组两级均失败则该组留空（不整体中断）。
    合并后按 title+link 去重，再严格按「北京时间当天」筛选，供 LLM 提炼 A股/港股/美股/全球/大宗 各板块一句话简述 + 持仓聚焦新闻驱动；
    每条新闻按 HOLDINGS_INDUSTRY_GROUPS 预匹配行业标签 industry_match（供持仓聚焦仅选命中行业的条目）。
    两组均不可达才返回 _fail（日报对应板块简述自动留空，不崩）。每个源成败与原因打印到日志便于定位。"""
    import email.utils as _eu
    def _bj_date(pub):
        """解析 RSS pubDate → 北京时间日期；解析失败返回 None。"""
        try:
            dt = _eu.parsedate_to_datetime(pub or "")
            if dt is not None:
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(TZ_CN).date()
        except Exception:
            return None
        return None
    def _norm_title(t):
        """标题归一化：去标点/空白，仅留字母数字与汉字后小写，用于跨源去重。"""
        return re.sub(r"[^\w\u4e00-\u9fff]+", "", t or "").lower()
    # 财联社双组 + 格隆汇单组（主备）；组名→来源标记（用于合并区分与当天过滤容错）
    GROUPS = {
        "telegraph": ("财联社", [
            "https://hub.slarker.me/cls/telegraph",
            "https://rsshub.rssforever.com/cls/telegraph",
        ]),
        "depth": ("财联社", [
            "https://hub.slarker.me/cls/depth/1000",
            "https://rsshub.rssforever.com/cls/depth/1000",
        ]),
        "gelonghui": ("格隆汇", [
            "https://rss.injahow.cn/gelonghui/live",
            "https://rsshub.rssforever.com/gelonghui/live",
        ]),
    }
    MAX_ITEMS = 80  # 保护：当天条目过多时仅取最新 80 条
    today_cn = datetime.now(TZ_CN).date()

    notes = []
    raw_items = []
    for gname, (src_label, urls) in GROUPS.items():
        group_items = None
        for url in urls:
            items, ok, note = _fetch_cls_rss_once(url, src_label)
            notes.append(f"{'✅' if ok else '❌'} [{gname}] {url} → {note}")
            if ok and items:
                group_items = items
                break  # 组内命中即止（主 → 备）
        if group_items:
            raw_items += group_items
            notes.append(f"  ↳ {gname}({src_label}) 采纳 {len(group_items)} 条")
        else:
            notes.append(f"  ↳ {gname}({src_label}) 主备均失败，该组留空")

    if not raw_items:
        print("    [财联社/格隆汇RSS] 全部候选源失败：")
        for n in notes:
            print("      " + n)
        return _fail(Exception("财联社/格隆汇全部RSS源均不可达；" + " | ".join(notes)))

    # 1) 严格按「北京时间当天」筛选（格隆汇缺 pubDate 视为当日保留，live 流天然当日）
    filtered = []
    for it in raw_items:
        bj = _bj_date(it.get("pubDate", ""))
        if bj is None:
            if it.get("source") == "格隆汇":
                filtered.append(it)
            continue
        if bj != today_cn:
            continue
        filtered.append(it)

    # 2) 标题归一化去重（捕捉财联社/格隆汇说同一件事）
    seen = set()
    merged = []
    for it in filtered:
        k = _norm_title(it.get("title", ""))
        if k and k in seen:
            continue
        seen.add(k)
        merged.append(it)

    # 3) 按发布时间倒序，取最新 MAX_ITEMS
    merged.sort(key=lambda x: x.get("pubDate", ""), reverse=True)
    items = merged[:MAX_ITEMS]

    # 4) 持仓聚焦：按行业关键词池预匹配（title+summary 命中即打行业标签）
    for it in items:
        _text = (it.get("title", "") + " " + it.get("summary", ""))
        it["industry_match"] = [g[0] for g in HOLDINGS_INDUSTRY_GROUPS
                                if any(k in _text for k in g[1])]

    print("    [财联社/格隆汇RSS] 源状态: " + " | ".join(notes))
    return _ok({"date": today_cn.isoformat(), "total": len(items),
                "groups": {k: v[1] for k, v in GROUPS.items()}, "items": items})

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
    print(f"═══ 预抓取金融市场数据（v37: 市场全景A股/美股/港股改先表格后叙述 | 估值快照删顺序列(8→7)+结论极简2-4字 | md_to_reader窄屏缩字 | QDII简称修复+11指数固定顺序+对比昨日保持 | 东财push2主源secid修正+yfinance兜底） ═══")
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
            ("data_news.json", _fetch_rss_other, "全球Top20 RSS(美国主流+联合早报)"),
            ("data_deep.json", _fetch_rss_deep, "深度观察源(联合早报原文)"),
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
            modules.append(("data_holdings.json", fetch_holdings, "持仓行情+监督池"))
        # 注：data_fund / data_industry 已停抓（prompt 不再消费）；data_holdings 已恢复（LLM 输入 JSON 11→9）
        # RSS 新闻：始终抓取（深度观察专栏仅精简模式，完整模式不抓 data_deep）
        modules.append(("data_news.json", _fetch_rss_other, "全球Top20 RSS(美国主流+联合早报)"))
        # 财联社当天新闻：供市场全景各板块一句话简述（严格当天，无则留空）
        modules.append(("data_cls_zaobao.json", fetch_cls_zaobao, "财联社RSS(当天→LLM简述)"))
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

