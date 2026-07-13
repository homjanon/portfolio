#!/usr/bin/env python3
"""
三市场交易日历判定模块。
供 prefetch_data.py 和 call_llm.py 共享调用。

报告在北京时间 D 05:30 触发，覆盖"昨天至今晨"的收盘：
  - A股参考日 = D-1（北京日期）
  - 美股参考日 = D-1（美国日期，今晨凌晨已收盘）
  - 港股参考日 = D-1（香港日期）

模式判定：a_open OR u_open OR hk_open → 完整模式；三者均假 → 精简模式
兜底：任一日历网络调用失败 → 降级为"看昨天星期几（<=4即视为开市）"
"""

from datetime import datetime, timezone, timedelta


def _china_open(d):
    """A股是否交易日（akshare 交易日历，与 xiaoxu-fear 一致）"""
    try:
        import akshare as ak
        cal = ak.tool_trade_date_hist_sina()
        trade_dates = {str(x)[:10] for x in cal["trade_date"].tolist()}
        return str(d) in trade_dates
    except Exception as e:
        print(f"  ⚠️ A股日历获取失败({e})，降级为周几判定")
        return d.weekday() <= 4  # 周一~五视为开市


def _us_open(d):
    """美股是否交易日（pandas_market_calendars XNYS）"""
    try:
        import pandas_market_calendars as mcal
        xcal = mcal.get_calendar("XNYS")
        sched = xcal.schedule(start_date=str(d), end_date=str(d))
        return len(sched) > 0
    except Exception as e:
        print(f"  ⚠️ 美股日历获取失败({e})，降级为周几判定")
        return d.weekday() <= 4


def _hk_open(d):
    """港股是否交易日（pandas_market_calendars XHKG）"""
    try:
        import pandas_market_calendars as mcal
        xcal = mcal.get_calendar("XHKG")
        sched = xcal.schedule(start_date=str(d), end_date=str(d))
        return len(sched) > 0
    except Exception as e:
        print(f"  ⚠️ 港股日历获取失败({e})，降级为周几判定")
        return d.weekday() <= 4


def market_flags():
    """返回三市场开市标志 + 模式判定。

    Returns:
        dict: {
            "a_open": bool,   # A股昨日是否交易日
            "u_open": bool,   # 美股昨日是否交易日
            "hk_open": bool,  # 港股昨日是否交易日
            "mode": str,      # "完整模式" 或 "精简模式"
            "yesterday": date, # 参考日
        }
    """
    beijing = timezone(timedelta(hours=8))
    yesterday = (datetime.now(beijing) - timedelta(days=1)).date()

    a_open = _china_open(yesterday)
    u_open = _us_open(yesterday)
    hk_open = _hk_open(yesterday)

    mode = "完整模式" if (a_open or u_open or hk_open) else "精简模式"

    return {
        "a_open": a_open,
        "u_open": u_open,
        "hk_open": hk_open,
        "mode": mode,
        "yesterday": yesterday,
    }


if __name__ == "__main__":
    flags = market_flags()
    y = flags["yesterday"]
    print(f"参考日(昨日): {y} 星期{'一二三四五六日'[y.weekday()]}")
    print(f"A股: {'开市' if flags['a_open'] else '休市'}")
    print(f"美股: {'开市' if flags['u_open'] else '休市'}")
    print(f"港股: {'开市' if flags['hk_open'] else '休市'}")
    print(f"模式: {flags['mode']}")
