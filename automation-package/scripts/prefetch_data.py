#!/usr/bin/env python3
"""
预抓取金融市场数据 — 按板块切分为结构化 JSON 文件。
v22: +申万实时涨跌幅+同花顺资金流+中美宏观+全球央行利率+QDII溢价+分红+研报+中英文双源RSS+PMI尾行bug修复+宏观扩展

输出文件（11个，均在 /workspace/data_*.json）：
  data_market_cn.json       A股5大指数行情           akshare新浪 → 腾讯API
  data_market_hk.json       港股恒生+国企指数         akshare新浪 → 腾讯API
  data_market_global.json   全球主要指数              akshare新浪(美股)+东财(全球) → 腾讯API
  data_forex_rate.json      汇率/商品/中美债券        akshare期货 + 债券
  data_valuation.json       中美核心指数估值+PE/PB分位 雪球蛋卷API + akshare
  data_fund.json            基金净值+净值估算+ETF溢价  akshare天天基金
  data_industry.json        🆕 申万31行业涨跌幅+同花顺90行业资金流+全市场PE  akshare(申万+同花顺+乐咕乐股)
  data_holdings.json        🆕 个人持仓+监督池行情+分红+研报  腾讯API + akshare(分红+研报)
  data_news_rss.json        全球TOP10新闻源          Google News RSS 英文(9外媒白名单) + 中文(国内财经媒体)
  data_extra.json           🆕 全球宏观+QDII+资金面   akshare(美国18+项宏观+全球央行利率+QDII溢价+欧洲CPI+BDI/SOX)
  data_macro.json           🆕 中国宏观数据           akshare(LPR/PMI/CPI/M2/社融/GDP/贸易差额)

每个文件：{"ts":"...", "ok":true/false, "data":..., "error":"..."}
"""

import json, os, sys, traceback, time, re, requests, xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

OUT_DIR = "/workspace"
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

    raw = _tencent_quote("sh000001,sz399001,sh000300,sh000688,sz399006")
    if raw:
        tencent_map = {"上证指数":"000001","深证成指":"399001",
                       "沪深300":"000300","科创50":"000688","创业板指":"399006"}
        rows = []
        for qc, v in raw.items():
            if v["name"] in tencent_map:
                rows.append({
                    "指数": v["name"], "代码": tencent_map[v["name"]],
                    "最新价": v["price"], "涨跌幅": v["change_pct"],
                    "成交量": v["volume"], "今开": v["open"],
                    "最高": v["high"], "最低": v["low"],
                })
        if rows:
            return _ok(rows)
    return _fail("A股指数数据全部不可用")


# ─── 2. 港股指数行情（不变）──────────────────────────────────
def fetch_market_hk():
    """恒生指数 + 恒生中国企业指数"""
    df = _akshare_sina_hk_index()
    if df is not None:
        rows = []
        for _, r in df.iterrows():
            name = str(r.get("名称","")).strip()
            if name in ("恒生指数","恒生中国企业指数"):
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
        if len(rows) >= 2:
            return _ok(rows)

    raw = _tencent_quote("hkHSI,hkHSCEI")
    name_map = {"HSI":"恒生指数","HSCEI":"恒生中国企业指数"}
    rows = [{"指数":name_map[k],"代码":k,"最新价":v["price"],
             "涨跌幅":v["change_pct"],"今开":v["open"],
             "最高":v["high"],"最低":v["low"]}
            for k,v in raw.items() if k in name_map]
    if len(rows) >= 2:
        return _ok(rows)
    return _fail("港股指数数据全部不可用")


# ─── 3. 全球主要指数（v19重写：akshare新浪美股 + 东财全球 + 腾讯兜底）──
def fetch_market_global():
    """美股(DJI/SPX/IXIC) + 日经/KOSPI/STOXX"""
    result = {}

    # ── 美股三大指数: akshare新浪 ──
    us_map = {".DJI": "道琼斯工业", ".INX": "标普500", ".IXIC": "纳斯达克综合"}
    for sym, name in us_map.items():
        data = _akshare_sina_us_index(sym)
        if data:
            result[name] = {"代码": sym, "最新价": data["close"], "涨跌幅": data["change_pct"],
                           "今开": data["open"], "最高": data["high"], "最低": data["low"],
                           "source": "akshare新浪"}
        else:
            result[name] = {"代码": sym, "note": "WebSearch备用"}

    # 腾讯API兜底美股
    if any("note" in result.get(n, {}) for n in us_map.values()):
        raw = _tencent_quote("usDJI,usIXIC,usSPX")
        tencent_name = {"DJI":"道琼斯工业","IXIC":"纳斯达克综合","SPX":"标普500"}
        for qc, v in raw.items():
            name = tencent_name.get(qc)
            if name and "note" in result.get(name, {}):
                result[name] = {"代码": us_map[[k for k,v2 in us_map.items() if v2==name][0]],
                               "最新价": v["price"], "涨跌幅": v["change_pct"],
                               "今开": v["open"], "最高": v["high"], "最低": v["low"],
                               "source": "腾讯API"}

    # ── 全球指数: akshare东财 ──
    df = _ak_eastmoney("index_global_spot_em")
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

    # 标记缺失
    for label in global_targets.values():
        if label not in result:
            result[label] = {"名称": label, "note": "WebSearch备用"}

    return _ok(result)


# ─── 4. 汇率/商品/债券（v19重写：akshare期货 + 债券，移除yfinance）───
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

    # ── 债券收益率: akshare bond_zh_us_rate ──
    try:
        import akshare as ak
        df = ak.bond_zh_us_rate()
        if df is not None and len(df) > 0:
            last = df.iloc[-1]
            result["CN10Y"] = {"名称": "10Y中国国债收益率", "最新值": _num(last.get("中国国债收益率10年")),
                              "日期": str(last.iloc[0]), "source": "akshare"}
            result["US10Y"] = {"名称": "10Y美国国债收益率", "最新值": _num(last.get("美国国债收益率10年")),
                              "日期": str(last.iloc[0]), "source": "akshare"}
    except: pass

    # ── USD/CNH: 无免费API，标记 ──
    result["USD/CNH"] = {"名称": "美元/离岸人民币", "note": "WebSearch备用"}

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

    # ── A股指数价格（akshare新浪 → 腾讯API兜底）──
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

    if len(a_list) < 5:
        codes = "sh000001,sz399001,sh000300,sh000688,sz399006,sh000510,sh000922"
        raw = _tencent_quote(codes)
        name_map = {"上证指数":"000001","深证成指":"399001","沪深300":"000300",
                    "科创50":"000688","创业板指":"399006","中证A500":"000510","中证红利":"000922"}
        a_list = [{"指数":v["name"],"代码":name_map[v["name"]],
                   "最新价":v["price"],"涨跌幅":v["change_pct"]}
                  for qc,v in raw.items() if v["name"] in name_map]

    result["a_share"] = a_list if a_list else {"error": "无数据"}

    # ── 美股估值（akshare新浪 NDX + SPX）──
    us_list = []
    us_targets = [(".NDX","纳斯达克100"), (".INX","标普500")]
    for sym, name in us_targets:
        data = _akshare_sina_us_index(sym)
        entry = {"指数": name, "ticker": sym}
        if data:
            entry["最新价"] = data["close"]
            entry["涨跌幅"] = data["change_pct"]
        else:
            entry["note"] = "数据暂不可得"
        entry["source"] = "akshare新浪"
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

# ─── 数据源G: 新浪USD/CNH 即期汇率 ─────────────────────────
def _sina_fx_usdcnh():
    """获取USD/CNH离岸人民币即期汇率"""
    try:
        r = requests.get("https://hq.sinajs.cn/list=fx_susdcnh",
            headers={"Referer": "https://finance.sina.com.cn/", "User-Agent": UA}, timeout=10)
        r.encoding = "gbk"
        # var hq_str_fx_susdcnh="时间,最新价,昨收,开盘,成交量,最高,最低,今开,..."
        m = re.search(r'"([^"]*)"', r.text)
        if m:
            parts = m.group(1).split(",")
            if len(parts) >= 2:
                return {"USD_CNH": float(parts[1])} if parts[1] else None
    except: pass
    return None


def fetch_extra():
    """v22: 汇率+资金面+涨跌(保留) + 美国宏观18+项 + 全球央行利率 + QDII溢价 + 欧洲CPI + BDI/SOX"""
    import akshare as ak
    result = {}
    today_str = datetime.now(TZ_CN).strftime("%Y%m%d")

    # ── 1. USD/CNH 汇率（新浪，保留）──
    fx = _sina_fx_usdcnh()
    result["USD_CNH"] = fx["USD_CNH"] if fx else None

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

    # ── 🆕 5. 美国宏观12+项指标（v22: +核心PCE/消费者信心/工业产出/ISM非制造业/BDI）──
    us_macro = {}
    us_functions = {
        '非农': lambda: ak.macro_usa_non_farm(),
        '失业率': lambda: ak.macro_usa_unemployment_rate(),
        'CPI月率': lambda: ak.macro_usa_cpi_monthly(),
        '核心CPI月率': lambda: ak.macro_usa_core_cpi_monthly(),
        'PPI': lambda: ak.macro_usa_ppi(),
        '核心PPI': lambda: ak.macro_usa_core_ppi(),
        'ISM制造业PMI': lambda: ak.macro_usa_ism_pmi(),
        'ISM非制造业PMI': lambda: ak.macro_usa_ism_non_pmi(),
        '零售销售月率': lambda: ak.macro_usa_retail_sales(),
        'ADP就业': lambda: ak.macro_usa_adp_employment(),
        '初请失业金': lambda: ak.macro_usa_initial_jobless(),
        'GDP': lambda: ak.macro_usa_gdp_monthly(),
        '美联储利率': lambda: ak.macro_bank_usa_interest_rate(),
        # v22 新增
        '核心PCE': lambda: ak.macro_usa_core_pce_price(),
        '密歇根消费者信心': lambda: ak.macro_usa_michigan_consumer_sentiment(),
        '工业产出月率': lambda: ak.macro_usa_industrial_production(),
        '新屋开工': lambda: ak.macro_usa_house_starts(),
        '耐用品订单': lambda: ak.macro_usa_durable_goods_orders(),
        'EIA原油库存': lambda: ak.macro_usa_eia_crude_rate(),
        'Markit制造业PMI': lambda: ak.macro_usa_pmi(),
    }
    for label, fn in us_functions.items():
        try:
            df = fn()
            if df is not None and len(df) > 0:
                latest = df.dropna(subset=['今值']).tail(1)
                if len(latest) > 0:
                    r = latest.iloc[0]
                    us_macro[label] = {
                        '今值': str(r.get('今值', 'N/A')),
                        '预测值': str(r.get('预测值', 'N/A')),
                        '前值': str(r.get('前值', 'N/A')),
                        '日期': str(r.get('日期', '')),
                    }
        except Exception as e:
            us_macro[label] = {'error': str(e)[:100]}
    # 🕐 v22: 过滤 — 仅保留近1个月内公布的数据
    _cutoff = datetime.now().replace(tzinfo=None) - timedelta(days=30)
    for _k in list(us_macro.keys()):
        _d = us_macro[_k].get('日期', '')
        try:
            if '-' in _d:
                _dt = datetime.strptime(_d, '%Y-%m-%d')
            else:
                _dt = datetime.strptime(_d, '%Y-%m')
        except:
            _dt = datetime(2000, 1, 1)  # 无法解析→视为陈旧
        if _dt < _cutoff:
            del us_macro[_k]
    result['美国宏观'] = us_macro

    # ── 🆕 6. 全球央行利率 ──
    global_rates = {}
    rate_functions = {
        '欧央行': lambda: ak.macro_bank_euro_interest_rate(),
        '日央行': lambda: ak.macro_bank_japan_interest_rate(),
        '英央行': lambda: ak.macro_bank_english_interest_rate(),
    }
    for label, fn in rate_functions.items():
        try:
            df = fn()
            if df is not None and len(df) > 0:
                latest = df.dropna(subset=['今值']).tail(1)
                if len(latest) > 0:
                    r = latest.iloc[0]
                    global_rates[label] = {
                        '利率': str(r.get('今值', 'N/A')),
                        '日期': str(r.get('日期', '')),
                    }
        except Exception as e:
            global_rates[label] = {'error': str(e)[:100]}
    result['全球央行利率'] = global_rates

    # ── 🆕 7. QDII ETF溢价率（集思录 JSL）──
    try:
        import pandas as pd
        df_a = ak.qdii_a_index_jsl()
        df_e = ak.qdii_e_index_jsl()
        df_all = pd.concat([df_a, df_e])
        qdii_list = []
        for _, r in df_all.iterrows():
            premium = r.get('溢价率')
            if premium is None or premium == '-' or (isinstance(premium, float) and pd.isna(premium)):
                premium = r.get('T-1溢价率', 'N/A')
            qdii_list.append({
                '代码': str(r['代码']),
                '名称': str(r['名称']),
                '现价': str(r.get('现价', '')),
                '净值': str(r.get('净值', r.get('T-2净值', ''))),
                '净值日期': str(r.get('净值日期', r.get('估值日期', ''))),
                '溢价率': str(premium) if premium is not None else 'N/A',
                '涨幅': str(r.get('涨幅', '')),
            })
        result['QDII_溢价'] = qdii_list
        result['QDII_总数'] = len(qdii_list)
    except Exception as e:
        result['_QDII_error'] = str(e)[:100]
        result['QDII_溢价'] = []

    # ── 🆕 8. 欧洲CPI/GDP ──
    eu_macro = {}
    eu_functions = {
        '欧元区CPI年率': lambda: ak.macro_euro_cpi_yoy(),
        '欧元区GDP年率': lambda: ak.macro_euro_gdp_yoy(),
    }
    for label, fn in eu_functions.items():
        try:
            df = fn()
            if df is not None and len(df) > 0:
                latest = df.dropna(subset=['今值']).tail(1)
                if len(latest) > 0:
                    r = latest.iloc[0]
                    eu_macro[label] = {
                        '今值': str(r.get('今值', 'N/A')),
                        '预测值': str(r.get('预测值', 'N/A')),
                        '前值': str(r.get('前值', 'N/A')),
                        '日期': str(r.get('日期', '')),
                    }
        except Exception as e:
            eu_macro[label] = {'error': str(e)[:100]}
    result['欧洲宏观'] = eu_macro

    # ── 🆕 v22: 全球先行指标（BDI航运 + SOX半导体）──
    import pandas as _pd_bdi
    for key, label, fn in [
        ('BDI', '波罗的海干散货指数', lambda: ak.macro_shipping_bdi()),
        ('SOX', '费城半导体指数', lambda: ak.macro_global_sox_index()),
    ]:
        try:
            df = fn()
            if df is not None and len(df) > 0:
                if '最新值' in df.columns:
                    val = df.iloc[-1]['最新值']
                else:
                    val = df.iloc[-1, -1]  # 兜底取最后一列
                try:
                    val_f = float(val)
                    result[key] = str(round(val_f, 2)) if not _pd_bdi.isna(val_f) else 'N/A'
                except (ValueError, TypeError):
                    result[key] = str(val)
                result[f'{key}_日期'] = str(df.iloc[-1]['日期']) if '日期' in df.columns else ''
            else:
                result[key] = 'N/A'
        except Exception as e:
            result[key] = f'error: {str(e)[:60]}'

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
            pub_el = item.find("pubDate")
            title = title_el.text if title_el is not None else ""
            title = re.sub(r"\s*[-–|]\s*" + re.escape(source) + r"\s*$", "", title).strip()
            desc = desc_el.text if desc_el is not None else ""
            desc = re.sub(r"<[^>]+>", " ", desc).strip()[:200]
            result.append({
                "title": title,
                "desc": desc,
                "source": source,
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
    """个人持仓(招行A/H/长电/563020/QQQM/SPY) + 监督池批量行情"""
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
        if qc in stock_map:
            result[qc] = {
                **stock_map[qc],
                "最新价": v["price"],
                "涨跌幅": v["change_pct"],
            }

    # 标记缺失
    for code, info in stock_map.items():
        if code not in result:
            result[code] = {**info, "error": "腾讯API无数据"}

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


# ═══════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════
def main():
    print(f"═══ 预抓取金融市场数据（v22: +申万实时+同花顺资金+中美宏观+全球利率+QDII溢价+分红+研报+宏观扩展） ═══")
    print(f"时间: {_ts()}\n")

    modules = [
        ("data_market_cn.json",      fetch_market_cn,      "A股指数"),
        ("data_market_hk.json",      fetch_market_hk,      "港股指数"),
        ("data_market_global.json",  fetch_market_global,  "全球指数"),
        ("data_forex_rate.json",     fetch_forex_rate,     "汇率/商品/债券"),
        ("data_valuation.json",      fetch_valuation,      "估值数据"),
        ("data_fund.json",           fetch_fund,           "基金净值/溢价"),
        ("data_industry.json",       fetch_industry,       "申万+同花顺行业"),
        ("data_holdings.json",       fetch_holdings,       "持仓行情+分红+研报"),
        ("data_news_rss.json",       _fetch_rss_news,      "全球TOP10 RSS新闻(英+中)"),
        ("data_extra.json",          fetch_extra,          "全球宏观+QDII+资金面"),
        ("data_macro.json",          fetch_macro,          "中国宏观数据"),
    ]

    successes = 0
    for fname, func, label in modules:
        print(f"▶ [{label}] {fname} ...", end=" ", flush=True)
        try:
            result = func()
            _write(fname, result)
            if result.get("ok"): successes += 1
            else: print("  ⚠️")
        except Exception as e:
            print("  ❌")
            traceback.print_exc()
            _write(fname, _fail(e))
        time.sleep(1)

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

