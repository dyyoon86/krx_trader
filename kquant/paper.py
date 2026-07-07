# -*- coding: utf-8 -*-
"""페이퍼 트레이딩 — 실전(예약주문) 모델로 시뮬레이션.

핵심(현실화):
- 매수: 분석은 장마감 후 → 픽을 '예약'해두고 **다음날 개장가**에 체결.
- 익절/손절: 증권사 지정가·스톱 예약주문처럼, 그날 **고가가 익절가 도달**하면 익절가에,
  **저가가 손절가 도달**하면 손절가에 체결(장중 자동체결 근사). 같은 날 둘 다 닿으면
  보수적으로 손절 우선.
- 만기: 보유 max_hold일 초과 시 그날 종가로 청산.
상태(현금·보유·예약)는 account.json, 일별 스냅샷은 history.jsonl.
"""
from __future__ import annotations
import datetime as dt
import json
import os

STATE_DIR = os.environ.get("KQ_PAPER_DIR",
                           os.path.join(os.path.dirname(os.path.dirname(__file__)), "paper"))
ACCOUNT = os.path.join(STATE_DIR, "account.json")
HISTORY = os.path.join(STATE_DIR, "history.jsonl")

DEFAULTS = {
    "initial_capital": 10_000_000,
    "take_profit": 10.0,     # +10% 익절
    "stop_loss": -7.0,       # -7% 손절
    "max_hold_days": 15,
    "max_positions": 8,
    "per_trade_cap_pct": 20.0,
    "fee_pct": 0.2,
}


def _load():
    if os.path.isfile(ACCOUNT):
        acc = json.load(open(ACCOUNT, encoding="utf-8"))
    else:
        acc = {"cash": DEFAULTS["initial_capital"],
               "initial_capital": DEFAULTS["initial_capital"],
               "positions": {}, "realized_pnl": 0.0, "trades": []}
    acc.setdefault("pending_buys", [])   # 다음 개장가 체결 대기(예약)
    return acc


def _save(acc):
    os.makedirs(STATE_DIR, exist_ok=True)
    json.dump(acc, open(ACCOUNT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def _ohlc(fdr, code):
    """최근 거래일 OHLC(open/high/low/close). 실패 시 None."""
    try:
        end = dt.date.today()
        df = fdr.DataReader(code, (end - dt.timedelta(days=15)).strftime("%Y-%m-%d"))
        if df is None or len(df) == 0:
            return None
        r = df.iloc[-1]
        return {"open": float(r["Open"]), "high": float(r["High"]),
                "low": float(r["Low"]), "close": float(r["Close"])}
    except Exception:
        return None


def _equity(acc, fdr, field="close"):
    total = acc["cash"]
    for code, pos in acc["positions"].items():
        o = _ohlc(fdr, code)
        px = o[field] if o else pos["entry"]
        total += pos["shares"] * px
    return total


def run_day(pipeline_out: dict, cfg: dict | None = None, log=print) -> dict:
    import FinanceDataReader as fdr
    cfg = {**DEFAULTS, **(cfg or {})}
    acc = _load()
    today = pipeline_out["date"]
    fee = cfg["fee_pct"] / 100

    # ── 1) 예약 매수 체결(어제 픽) — 오늘 개장가 ──
    if acc["pending_buys"]:
        equity = _equity(acc, fdr, "open")
        still = []
        for pb in acc["pending_buys"]:
            code = pb["code"]
            if code in acc["positions"]:
                continue
            if len(acc["positions"]) >= cfg["max_positions"]:
                still.append(pb); continue
            o = _ohlc(fdr, code)
            if not o:
                still.append(pb); continue          # 데이터 없으면 예약 유지
            entry = o["open"]
            weight = min(pb.get("weight_pct") or 0, cfg["per_trade_cap_pct"]) / 100
            budget = min(equity * weight, acc["cash"])
            shares = int(budget // (entry * (1 + fee)))
            if shares <= 0:
                continue
            cost = shares * entry * (1 + fee)
            acc["cash"] -= cost
            acc["positions"][code] = {"name": pb["name"], "shares": shares,
                                      "entry": entry, "entry_date": today}
            acc["trades"].append({"date": today, "code": code, "name": pb["name"],
                                  "side": "BUY", "price": entry, "shares": shares})
            log(f"  매수(개장가) {pb['name']} {shares}주 @ {int(entry):,}")
        acc["pending_buys"] = still

    # ── 2) 보유종목 익절/손절/만기 (장중 고저 기반) ──
    for code in list(acc["positions"].keys()):
        pos = acc["positions"][code]
        o = _ohlc(fdr, code)
        if not o:
            continue
        entry = pos["entry"]
        tp_price = entry * (1 + cfg["take_profit"] / 100)
        sl_price = entry * (1 + cfg["stop_loss"] / 100)
        held = (dt.date.fromisoformat(today) - dt.date.fromisoformat(pos["entry_date"])).days
        fill = reason = None
        if o["low"] <= sl_price:                      # 손절 우선(보수적)
            fill, reason = sl_price, f"손절 {cfg['stop_loss']:.0f}%"
        elif o["high"] >= tp_price:
            fill, reason = tp_price, f"익절 +{cfg['take_profit']:.0f}%"
        elif held >= cfg["max_hold_days"]:
            fill, reason = o["close"], f"만기 {held}일"
        if fill:
            proceeds = pos["shares"] * fill * (1 - fee)
            pnl = proceeds - pos["shares"] * entry
            acc["cash"] += proceeds
            acc["realized_pnl"] += pnl
            ret = (fill / entry - 1) * 100
            acc["trades"].append({"date": today, "code": code, "name": pos["name"],
                                  "side": "SELL", "price": fill, "shares": pos["shares"],
                                  "pnl": round(pnl), "reason": reason})
            log(f"  매도 {pos['name']} @ {int(fill):,} — {reason} ({ret:+.1f}%, 실현 {pnl:+,.0f})")
            del acc["positions"][code]

    # ── 3) 오늘 BUY 픽을 '내일 개장가' 예약 ──
    held_codes = set(acc["positions"]) | {p["code"] for p in acc["pending_buys"]}
    for r in pipeline_out.get("buys", []):
        if r["code"] in held_codes:
            continue
        acc["pending_buys"].append({"code": r["code"], "name": r["name"],
                                    "weight_pct": r.get("weight_pct"), "pick_date": today})
        log(f"  예약 매수 {r['name']} (다음 개장가, 비중 {r.get('weight_pct',0):.0f}%)")

    # ── 4) 스냅샷(종가 평가) ──
    equity = _equity(acc, fdr, "close")
    snap = {"date": today, "equity": round(equity), "cash": round(acc["cash"]),
            "positions": len(acc["positions"]), "pending": len(acc["pending_buys"]),
            "total_return_pct": round((equity / acc["initial_capital"] - 1) * 100, 2)}
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(HISTORY, "a", encoding="utf-8") as f:
        f.write(json.dumps(snap, ensure_ascii=False) + "\n")
    _save(acc)
    return {"account": acc, "snapshot": snap}


def status() -> dict:
    import FinanceDataReader as fdr
    acc = _load()
    rows = []
    for code, pos in acc["positions"].items():
        o = _ohlc(fdr, code)
        cur = o["close"] if o else pos["entry"]
        ret = (cur / pos["entry"] - 1) * 100
        rows.append({"code": code, "name": pos["name"], "shares": pos["shares"],
                     "entry": pos["entry"], "current": cur, "return_pct": round(ret, 2),
                     "value": round(pos["shares"] * cur)})
    equity = acc["cash"] + sum(r["value"] for r in rows)
    return {"cash": round(acc["cash"]), "equity": round(equity),
            "initial": acc["initial_capital"], "realized_pnl": round(acc["realized_pnl"]),
            "total_return_pct": round((equity / acc["initial_capital"] - 1) * 100, 2),
            "positions": rows, "pending": acc.get("pending_buys", [])}
