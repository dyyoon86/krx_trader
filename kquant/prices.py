# -*- coding: utf-8 -*-
"""가격 캐시 — 백테스트 시 FDR 네트워크 반복호출 제거(종목별 전체기간 1회만 로드).

armed 상태면 data.features / paper._ohlc 가 네트워크 대신 이 캐시를 슬라이스한다.
"""
from __future__ import annotations
import datetime as dt

_CACHE: dict = {}
_ARMED = False


def preload(codes, start, end, log=print):
    global _ARMED
    import FinanceDataReader as fdr
    for c in codes:
        try:
            _CACHE[c] = fdr.DataReader(c, start, end)
        except Exception:
            _CACHE[c] = None
    _ARMED = True
    log(f"[prices] {len([v for v in _CACHE.values() if v is not None])}/{len(codes)}종목 가격 캐시 완료")


def armed() -> bool:
    return _ARMED


def hist_until(code, as_of):
    """as_of(포함) 이하 OHLCV DataFrame. 캐시 미스면 None."""
    df = _CACHE.get(code)
    if df is None:
        return None
    end = dt.date.fromisoformat(as_of) if isinstance(as_of, str) else as_of
    return df[df.index.date <= end]


def ohlc_on(code, on):
    """on(포함) 이하 마지막 거래일 OHLC dict. 없으면 None."""
    h = hist_until(code, on) if on else _CACHE.get(code)
    if h is None or len(h) == 0:
        return None
    r = h.iloc[-1]
    return {"open": float(r["Open"]), "high": float(r["High"]),
            "low": float(r["Low"]), "close": float(r["Close"]),
            "change": float(r.get("Change", 0)), "volume": float(r["Volume"])}
