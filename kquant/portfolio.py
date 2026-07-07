# -*- coding: utf-8 -*-
"""픽 기록 + 페이퍼 트레이딩 수익률 트래킹.

- save_picks: 분석 결과(BUY)를 날짜별 JSON으로 저장(추천가·비중).
- track: 과거 픽들의 현재가를 조회해 추천가 대비 수익률 산출.
"""
from __future__ import annotations
import datetime as dt
import json
import os

PICK_DIR = os.environ.get("KQ_PICK_DIR",
                          os.path.join(os.path.dirname(os.path.dirname(__file__)), "picks"))


def save_picks(date: str, results: list[dict], only_buy: bool = True) -> str:
    os.makedirs(PICK_DIR, exist_ok=True)
    picks = [r for r in results if (not only_buy or r.get("action") == "BUY")]
    rec = {
        "date": date, "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "picks": [{
            "code": r["code"], "name": r["name"], "entry_price": r.get("price"),
            "confidence": r.get("confidence"), "weight_pct": r.get("weight_pct"),
            "summary": r.get("summary"),
        } for r in picks],
        "all": results,
    }
    path = os.path.join(PICK_DIR, f"{date}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    return path


def track() -> list[dict]:
    """저장된 모든 픽의 현재가 대비 수익률(페이퍼)."""
    import FinanceDataReader as fdr
    if not os.path.isdir(PICK_DIR):
        return []
    out = []
    for fn in sorted(os.listdir(PICK_DIR)):
        if not fn.endswith(".json"):
            continue
        rec = json.load(open(os.path.join(PICK_DIR, fn), encoding="utf-8"))
        for p in rec.get("picks", []):
            entry = p.get("entry_price")
            cur = _last_price(fdr, p["code"])
            ret = round((cur / entry - 1) * 100, 2) if (entry and cur) else None
            out.append({"date": rec["date"], "code": p["code"], "name": p["name"],
                        "entry": entry, "current": cur, "return_pct": ret,
                        "weight_pct": p.get("weight_pct")})
    return out


def _last_price(fdr, code: str):
    try:
        end = dt.date.today()
        df = fdr.DataReader(code, (end - dt.timedelta(days=10)).strftime("%Y-%m-%d"))
        return float(df["Close"].iloc[-1]) if len(df) else None
    except Exception:
        return None
