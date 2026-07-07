# -*- coding: utf-8 -*-
"""페이퍼 트레이딩 — 가상 계좌로 AI 픽을 실제 매매하듯 시뮬레이션.

- 상태(현금·보유종목)를 JSON으로 관리(account.json).
- buy: 당일 BUY 픽을 제안비중만큼 가상 매수(진입가=당일 종가).
- apply_exits: 익절/손절/최대보유일 규칙으로 매도.
- mark_to_market: 보유종목 현재가로 평가액 산출.
- snapshot: 매일 계좌 상태를 기록(equity curve).
실행은 pipeline.run(분석) 결과를 받아 하루치 매매를 처리한다.
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
    "initial_capital": 10_000_000,   # 1000만원
    "take_profit": 10.0,             # +10% 익절
    "stop_loss": -7.0,               # -7% 손절
    "max_hold_days": 15,             # 최대 보유(거래일 근사=달력일)
    "max_positions": 8,              # 동시 보유 최대
    "per_trade_cap_pct": 20.0,       # 종목당 최대 비중
    "fee_pct": 0.2,                  # 매수+매도 왕복 수수료+세금 근사
}


def _load():
    if os.path.isfile(ACCOUNT):
        return json.load(open(ACCOUNT, encoding="utf-8"))
    return {"cash": DEFAULTS["initial_capital"],
            "initial_capital": DEFAULTS["initial_capital"],
            "positions": {},  # code -> {name, shares, entry, entry_date}
            "realized_pnl": 0.0, "trades": []}


def _save(acc):
    os.makedirs(STATE_DIR, exist_ok=True)
    json.dump(acc, open(ACCOUNT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def _price(fdr, code):
    try:
        end = dt.date.today()
        df = fdr.DataReader(code, (end - dt.timedelta(days=12)).strftime("%Y-%m-%d"))
        return float(df["Close"].iloc[-1]) if len(df) else None
    except Exception:
        return None


def run_day(pipeline_out: dict, cfg: dict | None = None, log=print) -> dict:
    """하루치 페이퍼 매매: 매도규칙 적용 → 신규 매수 → 스냅샷."""
    import FinanceDataReader as fdr
    cfg = {**DEFAULTS, **(cfg or {})}
    acc = _load()
    today = pipeline_out["date"]
    fee = cfg["fee_pct"] / 100

    # 1) 보유종목 매도 규칙
    for code in list(acc["positions"].keys()):
        pos = acc["positions"][code]
        cur = _price(fdr, code)
        if not cur:
            continue
        ret = (cur / pos["entry"] - 1) * 100
        held = (dt.date.fromisoformat(today) - dt.date.fromisoformat(pos["entry_date"])).days
        reason = None
        if ret >= cfg["take_profit"]:
            reason = f"익절 +{ret:.1f}%"
        elif ret <= cfg["stop_loss"]:
            reason = f"손절 {ret:.1f}%"
        elif held >= cfg["max_hold_days"]:
            reason = f"보유만기 {held}일 ({ret:+.1f}%)"
        if reason:
            proceeds = pos["shares"] * cur * (1 - fee)
            acc["cash"] += proceeds
            pnl = proceeds - pos["shares"] * pos["entry"]
            acc["realized_pnl"] += pnl
            acc["trades"].append({"date": today, "code": code, "name": pos["name"],
                                  "side": "SELL", "price": cur, "shares": pos["shares"],
                                  "pnl": round(pnl), "reason": reason})
            log(f"  매도 {pos['name']} @ {int(cur):,} — {reason} (실현 {pnl:+,.0f})")
            del acc["positions"][code]

    # 2) 신규 매수 (BUY 픽)
    equity = _equity(acc, fdr)
    for r in pipeline_out.get("buys", []):
        code = r["code"]
        if code in acc["positions"]:
            continue
        if len(acc["positions"]) >= cfg["max_positions"]:
            break
        weight = min(r.get("weight_pct") or 0, cfg["per_trade_cap_pct"]) / 100
        budget = equity * weight
        price = r.get("price")
        if not price or budget < price:
            continue
        shares = int(budget // price)
        if shares <= 0:
            continue
        cost = shares * price * (1 + fee)
        if cost > acc["cash"]:
            shares = int(acc["cash"] / (price * (1 + fee)))
            cost = shares * price * (1 + fee)
        if shares <= 0:
            continue
        acc["cash"] -= cost
        acc["positions"][code] = {"name": r["name"], "shares": shares,
                                  "entry": price, "entry_date": today}
        acc["trades"].append({"date": today, "code": code, "name": r["name"],
                              "side": "BUY", "price": price, "shares": shares,
                              "confidence": r.get("confidence")})
        log(f"  매수 {r['name']} {shares}주 @ {int(price):,} (비중 {weight*100:.0f}%)")

    # 3) 스냅샷
    equity = _equity(acc, fdr)
    snap = {"date": today, "equity": round(equity), "cash": round(acc["cash"]),
            "positions": len(acc["positions"]),
            "total_return_pct": round((equity / acc["initial_capital"] - 1) * 100, 2)}
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(HISTORY, "a", encoding="utf-8") as f:
        f.write(json.dumps(snap, ensure_ascii=False) + "\n")
    _save(acc)
    return {"account": acc, "snapshot": snap}


def _equity(acc, fdr):
    total = acc["cash"]
    for code, pos in acc["positions"].items():
        cur = _price(fdr, code) or pos["entry"]
        total += pos["shares"] * cur
    return total


def status() -> dict:
    """현재 계좌 상태 + 보유종목 평가."""
    import FinanceDataReader as fdr
    acc = _load()
    rows = []
    for code, pos in acc["positions"].items():
        cur = _price(fdr, code) or pos["entry"]
        ret = (cur / pos["entry"] - 1) * 100
        rows.append({"code": code, "name": pos["name"], "shares": pos["shares"],
                     "entry": pos["entry"], "current": cur, "return_pct": round(ret, 2),
                     "value": round(pos["shares"] * cur)})
    equity = acc["cash"] + sum(r["value"] for r in rows)
    return {"cash": round(acc["cash"]), "equity": round(equity),
            "initial": acc["initial_capital"], "realized_pnl": round(acc["realized_pnl"]),
            "total_return_pct": round((equity / acc["initial_capital"] - 1) * 100, 2),
            "positions": rows}
