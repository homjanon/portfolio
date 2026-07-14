#!/usr/bin/env python3
"""
按市场解析「业务日期」与「北京时间收盘标注」——与数据获取完全解耦。

报告锚点：北京时间 05:30 左右触发（实际因 Actions 延迟约 07:10）。
核心问题：在固定锚点下，不同市场的「应取数据的业务日期」不同：
  - A股/港股/日经/韩国/欧洲：当日尚未开盘或早已收盘，取上一个交易日（D-1）。
  - 美股：美东前一交易日已在北京时间今天凌晨完整收盘，取该 session（市场当地业务日期同为 D-1，
          但其收盘落在北京时间"今天凌晨"，标注为「X月X日凌晨」）。

设计要点（遵循工程要求）：
  - 海外用 pandas_market_calendars（本地计算，DST 自动适配，禁止手写时区偏移）。
  - A股用 akshare tool_trade_date_hist_sina（带本地文件缓存，避免每次网络请求）。
  - 方法：
      get_business_date(market) -> 市场当地交易日(date, 如 2026-07-13)
      get_close_label(market)   -> 北京时间收盘标注(str, 如 "7月13日" / "7月14日凌晨")
      report_beijing_str()      -> "2026年7月14日 星期二"
"""

from datetime import datetime, date, timezone, timedelta
import os

BEIJING = timezone(timedelta(hours=8))

# (日历代码, 交易所时区, 当地收盘时刻"HH:MM", 中文名)
MARKETS = {
    "cn": ("XSHG", "Asia/Shanghai",     "15:00", "A股"),
    "hk": ("XHKG", "Asia/Hong_Kong",    "16:00", "港股"),
    "us": ("XNYS", "America/New_York",  "16:00", "美股"),
    "jp": ("XJPX", "Asia/Tokyo",        "15:00", "日经"),
    "kr": ("XKRX", "Asia/Seoul",        "15:30", "韩国"),
    "eu": ("XETR", "Europe/Berlin",     "17:30", "欧洲"),  # STOXX600（法兰克福Xetra，收盘约北京23:30）
}

_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".cache")
_CN_CACHE_FILE = os.path.join(_CACHE_DIR, "cn_trade_dates.json")


def _weekday_cn(d: date) -> str:
    return "一二三四五六日"[d.weekday()]


class MarketDateResolver:
    def __init__(self, report_time: datetime = None):
        # report_time 必须是带时区的北京时间；缺省取当前北京时刻
        self.report_time = report_time or datetime.now(BEIJING)

    # ── A股交易日集合（网络 + 本地文件缓存） ──
    def _cn_trade_dates(self):
        """返回升序的 A股交易日 date 列表；失败降级为空列表。"""
        import json
        # 1) 尝试读本地缓存（1 天内有效）
        try:
            if os.path.exists(_CN_CACHE_FILE):
                with open(_CN_CACHE_FILE, encoding="utf-8") as f:
                    cached = json.load(f)
                if (datetime.now() - datetime.fromisoformat(cached["cached_at"])).days < 1:
                    return [date.fromisoformat(x) for x in cached["dates"]]
        except Exception:
            pass
        # 2) 重新拉取并写回缓存
        try:
            import akshare as ak
            cal = ak.tool_trade_date_hist_sina()
            dates = sorted({date.fromisoformat(str(x)[:10]) for x in cal["trade_date"].tolist()})
            try:
                os.makedirs(_CACHE_DIR, exist_ok=True)
                with open(_CN_CACHE_FILE, "w", encoding="utf-8") as f:
                    json.dump({"cached_at": datetime.now().isoformat(),
                               "dates": [d.isoformat() for d in dates]}, f)
            except Exception:
                pass
            return dates
        except Exception as e:
            print(f"  ⚠️ A股交易日历获取失败({e})，降级为周几判定")
            return []

    # ── 海外日历（本地计算，无网络；DST 由库自动处理） ──
    def _overseas_schedule(self, cal_code):
        import pandas_market_calendars as mcal
        start = (self.report_time - timedelta(days=12)).date()
        end = (self.report_time + timedelta(days=2)).date()
        cal = mcal.get_calendar(cal_code)
        return cal.schedule(start_date=str(start), end_date=str(end))  # market_close 为 UTC

    def _latest_closed_session(self, market):
        """返回 (市场当地交易日 date, 收盘北京时间 datetime)；无则 None。

        判定依据：取『收盘北京时间 ≤ report_time』的最近一个交易日。
        该定义天然适配夏令时（库给出 UTC 收盘，转北京即可），无需手写时区偏移。
        """
        cal_code, tz_name, close_hm, name = MARKETS[market]
        if market == "cn":
            trade_dates = self._cn_trade_dates()
            if not trade_dates:
                return None
            h, m = map(int, close_hm.split(":"))
            for d in reversed(trade_dates):
                close_bj = datetime(d.year, d.month, d.day, h, m, tzinfo=BEIJING)
                if close_bj <= self.report_time:
                    return d, close_bj
            return None
        else:
            try:
                sched = self._overseas_schedule(cal_code)
            except Exception as e:
                print(f"  ⚠️ {name}日历获取失败({e})，降级")
                return None
            from zoneinfo import ZoneInfo
            for sess_date, row in reversed(list(sched.iterrows())):
                close_bj = row["market_close"].astimezone(BEIJING)
                if close_bj <= self.report_time:
                    return sess_date.date(), close_bj
            return None

    def get_business_date(self, market: str) -> date:
        """该市场在 report_time 下应取的『市场当地交易日』。"""
        sess = self._latest_closed_session(market)
        if sess:
            return sess[0]
        # 兜底：从 yesterday 往回找最近一个周一~周五（与 trading_calendar.py 一致）
        d = (self.report_time - timedelta(days=1)).date()
        for _ in range(7):
            if d.weekday() <= 4:
                return d
            d -= timedelta(days=1)
        return (self.report_time - timedelta(days=1)).date()

    def get_close_label(self, market: str) -> str:
        """北京时间收盘标注，如 '7月13日' / '7月14日凌晨'。"""
        sess = self._latest_closed_session(market)
        if not sess:
            bd = self.get_business_date(market)
            return f"{bd.month}月{bd.day}日（约）"
        bd, close_bj = sess
        # 收盘落在北京时间"今天" → 凌晨；否则用市场当地交易日
        if close_bj.date() == self.report_time.date():
            return f"{close_bj.month}月{close_bj.day}日凌晨"
        return f"{bd.month}月{bd.day}日"

    def report_beijing_str(self) -> str:
        d = self.report_time.date()
        return f"{d.year}年{d.month}月{d.day}日 星期{_weekday_cn(d)}"


if __name__ == "__main__":
    r = MarketDateResolver()
    for m in ["cn", "hk", "us", "jp", "kr", "eu"]:
        print(f"{MARKETS[m][3]}: 业务日期={r.get_business_date(m)}  标注={r.get_close_label(m)}")
    print("报告日期:", r.report_beijing_str())
