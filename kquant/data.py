# -*- coding: utf-8 -*-
"""데이터 레이어 — FinanceDataReader 기반 한국 주식 유니버스/스크리닝/기술적 피처.

KRX 전체 상장목록에서 거래대금·시총·등락률을 한 번에 받아 스크리닝하고,
개별 종목의 최근 OHLCV에서 모멘텀/변동성/52주 고점근접(VCP성) 등을 계산한다.
(사용자 한국 미니PC에서 실행 권장 — 해외 IP는 일부 소스가 막힐 수 있음)
"""
from __future__ import annotations
import datetime as dt
import functools
import re

import FinanceDataReader as fdr

# 스크리닝에서 제외할 이름 패턴(스팩·우선주·리츠·ETN 등)
_EXCLUDE = re.compile(r"(스팩|제\d+호|우$|우[BC]$|\d우$|리츠|ETN|ETF)")


@functools.lru_cache(maxsize=2)
def load_universe() -> "list[dict]":
    """KRX 전 종목 스냅샷. 각 dict: code,name,market,close,amount(거래대금),
    marcap(시총),change(등락률%),volume,shares."""
    df = fdr.StockListing("KRX")
    rows = []
    for _, r in df.iterrows():
        name = str(r.get("Name") or "")
        if not name or _EXCLUDE.search(name):
            continue
        try:
            rows.append({
                "code": str(r["Code"]).zfill(6),
                "name": name,
                "market": r.get("Market"),
                "close": _num(r.get("Close")),
                "amount": _num(r.get("Amount")),      # 거래대금(원)
                "marcap": _num(r.get("Marcap")),       # 시가총액(원)
                "change": _num(r.get("ChagesRatio")),  # 등락률(%)  (FDR 철자 그대로)
                "volume": _num(r.get("Volume")),
                "shares": _num(r.get("Stocks")),
            })
        except Exception:
            continue
    return rows


def screen(market: str | None = None, top_n: int = 20,
           min_marcap: float = 3e11, rank_by: str = "amount",
           name_contains: str | None = None) -> "list[dict]":
    """유니버스에서 조건 필터 후 rank_by 상위 top_n.
    market: 'KOSPI'|'KOSDAQ'|None(전체) / min_marcap: 최소 시총(원, 기본 3000억)
    rank_by: 'amount'(거래대금)|'change'(등락률)|'marcap'
    name_contains: 종목명 포함 키워드(간이 테마 필터)"""
    uni = list(load_universe())
    if market:
        uni = [s for s in uni if s["market"] == market]
    if min_marcap:
        uni = [s for s in uni if (s["marcap"] or 0) >= min_marcap]
    if name_contains:
        uni = [s for s in uni if name_contains in s["name"]]
    uni = [s for s in uni if (s["amount"] or 0) > 0]
    uni.sort(key=lambda s: s.get(rank_by) or 0, reverse=True)
    return uni[:top_n]


def by_tickers(items) -> "list[dict]":
    """종목코드 또는 종목명 리스트 → 유니버스에서 해당 종목 dict(관심종목/항상포함용)."""
    if not items:
        return []
    if isinstance(items, str):
        items = [x.strip() for x in items.replace(",", " ").split() if x.strip()]
    uni = load_universe()
    by_code = {s["code"]: s for s in uni}
    by_name = {s["name"]: s for s in uni}
    out = []
    for it in items:
        it = str(it).strip()
        s = by_code.get(it.zfill(6)) or by_name.get(it)
        if s:
            out.append(s)
    return out


def stock_asof(code: str, as_of: str) -> dict | None:
    """백테스트용 — 특정일 기준 종목 스냅샷(name/close/change/amount 근사)."""
    uni = {s["code"]: s for s in load_universe()}
    name = uni.get(code, {}).get("name") or code
    market = uni.get(code, {}).get("market")
    from . import prices
    if prices.armed():
        o = prices.ohlc_on(code, as_of)
        if not o:
            return None
        return {"code": code, "name": name, "market": market, "close": o["close"],
                "change": round(o["change"] * 100, 2),
                "amount": o["close"] * o["volume"], "marcap": None}
    end = dt.date.fromisoformat(as_of)
    try:
        df = fdr.DataReader(code, (end - dt.timedelta(days=12)).strftime("%Y-%m-%d"), as_of)
        if df is None or len(df) == 0:
            return None
        r = df.iloc[-1]
        close = float(r["Close"])
        return {"code": code, "name": name, "market": market, "close": close,
                "change": round(float(r.get("Change", 0)) * 100, 2),
                "amount": close * float(r["Volume"]), "marcap": None}
    except Exception:
        return None


def features(code: str, days: int = 180, as_of: str | None = None) -> dict:
    """개별 종목 기술적 피처 — 최근 days일 OHLCV에서 계산.
    as_of 지정 시 그 날짜까지만 사용(백테스트 룩어헤드 방지)."""
    end = dt.date.fromisoformat(as_of) if as_of else dt.date.today()
    start = end - dt.timedelta(days=int(days * 1.6) + 10)
    from . import prices
    if as_of and prices.armed():                 # 백테스트: 캐시 슬라이스
        df = prices.hist_until(code, as_of)
        if df is not None:
            df = df.tail(days + 60)
        if df is None or len(df) < 20:
            return {"error": "데이터 부족(캐시)"}
    else:
        try:
            df = fdr.DataReader(code, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        except Exception as e:
            return {"error": f"OHLCV 조회 실패: {e}"}
    if df is None or len(df) < 20:
        return {"error": "데이터 부족"}
    c = df["Close"]
    v = df["Volume"]
    last = float(c.iloc[-1])
    def ret(n):
        return round((last / float(c.iloc[-n - 1]) - 1) * 100, 2) if len(c) > n else None
    hi52 = float(c.tail(min(len(c), 250)).max())
    lo52 = float(c.tail(min(len(c), 250)).min())
    ma20 = float(c.tail(20).mean())
    ma60 = float(c.tail(60).mean()) if len(c) >= 60 else None
    vol20 = float(c.pct_change().tail(20).std() * 100)          # 일간변동성%
    volsurge = round(float(v.iloc[-1]) / float(v.tail(20).mean()), 2) if v.tail(20).mean() else None
    # VCP성: 최근 변동성이 직전 대비 수축했는가
    recent_vol = float(c.pct_change().tail(10).std() * 100)
    prior_vol = float(c.pct_change().iloc[-30:-10].std() * 100) if len(c) >= 30 else None
    contraction = (round(recent_vol / prior_vol, 2) if prior_vol else None)
    return {
        "price": round(last, 1),
        "ret_1d": ret(1), "ret_5d": ret(5), "ret_20d": ret(20), "ret_60d": ret(60),
        "high_52w": round(hi52, 1), "low_52w": round(lo52, 1),
        "pct_from_52w_high": round((last / hi52 - 1) * 100, 2),
        "pct_from_52w_low": round((last / lo52 - 1) * 100, 2),
        "ma20": round(ma20, 1), "ma60": round(ma60, 1) if ma60 else None,
        "above_ma20": last > ma20, "above_ma60": (last > ma60) if ma60 else None,
        "daily_vol_20d_pct": round(vol20, 2),
        "volume_surge_x": volsurge,           # 최근 거래량 / 20일평균
        "vcp_contraction": contraction,       # <1 이면 변동성 수축(VCP성)
    }


def _num(x):
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None
