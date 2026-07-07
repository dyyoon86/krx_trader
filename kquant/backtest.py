# -*- coding: utf-8 -*-
"""백테스트 — 고정 종목 리스트를 과거로 재생(replay)해 AI 픽 + 예약주문 매매 성과 검증.

- point-in-time: 각 거래일 D에서 D까지의 데이터만으로 피처 계산·분석(룩어헤드 방지).
- 리밸런스: LLM 분석은 every 거래일마다(비용 절약), 매도/예약체결은 매 거래일 처리.
- 과거 거래대금 상위 자동선정은 불가(데이터 한계) → 종목은 리스트로 지정.
- 벤치마크: 같은 기간 동일가중 매수후보유(buy&hold) 평균 수익률과 비교.
"""
from __future__ import annotations


def run(tickers, start, end, every=5, backend="claude", model=None,
        cfg=None, log=print) -> dict:
    import datetime as dt
    import FinanceDataReader as fdr
    from . import data, agents, paper, prices
    from .llm import LLM

    ref = fdr.DataReader("005930", start, end)
    days = [d.strftime("%Y-%m-%d") for d in ref.index]
    if not days:
        raise SystemExit("해당 기간 거래일이 없습니다.")
    # 가격 캐시 선로딩(피처용 넉넉히 과거까지) — 네트워크 반복호출 제거
    pre = (dt.date.fromisoformat(days[0]) - dt.timedelta(days=400)).strftime("%Y-%m-%d")
    prices.preload(list(tickers) + ["005930"], pre, end, log=log)
    llm = LLM(backend=backend, model=model, log=log)
    log(f"[백테스트] {days[0]}~{days[-1]} · {len(days)}거래일 · 종목 {len(tickers)}개 · "
        f"{every}일마다 분석 · 모델 {llm.model}")

    nsig = 0
    for i, D in enumerate(days):
        buys = []
        if i % every == 0:
            items = []
            for code in tickers:
                s = data.stock_asof(code, D)
                if not s:
                    continue
                feat = data.features(code, as_of=D)
                if feat.get("error"):
                    continue
                items.append((s, feat))
            if items:
                res = agents.analyze_batch(llm, items, D)   # 1콜로 전 종목
                buys = [r for r in res if r.get("action") == "BUY"]
                if buys:
                    nsig += len(buys)
                    log(f"  [{D}] BUY {len(buys)}: " + ", ".join(b["name"] for b in buys))
        paper.run_day({"date": D, "buys": buys}, cfg=cfg, on_date=D,
                      log=(log if buys else (lambda *_: None)))

    st = paper.status(on=days[-1])
    bench = _benchmark(fdr, tickers, days[0], days[-1])
    trades = st and paper._load().get("trades", [])
    sells = [t for t in (trades or []) if t.get("side") == "SELL"]
    wins = [t for t in sells if (t.get("pnl") or 0) > 0]
    return {
        "period": (days[0], days[-1]), "trading_days": len(days),
        "signals": nsig, "sells": len(sells),
        "win_rate": round(len(wins) / len(sells) * 100, 1) if sells else None,
        "total_return_pct": st["total_return_pct"], "equity": st["equity"],
        "realized_pnl": st["realized_pnl"], "positions": st["positions"],
        "benchmark_pct": bench,
    }


def _benchmark(fdr, tickers, start, end) -> float | None:
    """동일가중 buy&hold 평균 수익률(%)."""
    rets = []
    for code in tickers:
        try:
            df = fdr.DataReader(code, start, end)
            if len(df) >= 2:
                rets.append(float(df["Close"].iloc[-1]) / float(df["Close"].iloc[0]) - 1)
        except Exception:
            pass
    return round(sum(rets) / len(rets) * 100, 2) if rets else None
