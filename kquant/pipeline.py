# -*- coding: utf-8 -*-
"""오케스트레이션 — 스크리닝 → (종목별) 피처+뉴스 → 멀티에이전트 분석 → 랭킹/저장.

영상의 노드 흐름을 코드로: [스크리닝]→[거래대금/시총]→[뉴스]→[5애널리스트]→[최종매수결정]
"""
from __future__ import annotations
import datetime as dt

from . import data, news as newsmod, agents, portfolio
from .llm import LLM


def run(*, market=None, top_n=20, min_marcap=3e11, rank_by="amount",
        name_contains=None, use_news=True, backend="claude", model=None,
        target_date=None, log=print) -> dict:
    target_date = target_date or dt.date.today().strftime("%Y-%m-%d")
    llm = LLM(backend=backend, model=model, log=log)
    log(f"[llm] 백엔드={backend} 모델={llm.model} (저가 우선)")

    log(f"[1/4] 스크리닝 — market={market or '전체'} rank_by={rank_by} top{top_n}"
        + (f" 테마='{name_contains}'" if name_contains else ""))
    universe = data.screen(market=market, top_n=top_n, min_marcap=min_marcap,
                           rank_by=rank_by, name_contains=name_contains)
    log(f"      대상 {len(universe)}종목: " + ", ".join(s["name"] for s in universe[:10])
        + (" …" if len(universe) > 10 else ""))

    results = []
    for i, s in enumerate(universe, 1):
        log(f"[2/4] ({i}/{len(universe)}) {s['name']}({s['code']}) 피처·뉴스 수집")
        feat = data.features(s["code"])
        heads = newsmod.headlines(s["name"]) if use_news else []
        log(f"[3/4] ({i}/{len(universe)}) {s['name']} 5인 애널리스트 분석…")
        r = agents.analyze(llm, s, feat, heads, target_date)
        if r.get("error"):
            log(f"      ⚠ {s['name']} 분석 실패: {r['error']}")
        else:
            log(f"      → {r['action']} (확신 {r['confidence']:.2f}"
                + (f", 비중 {r['weight_pct']:.0f}%" if r['action'] == 'BUY' else "") + ")")
        results.append(r)

    # 랭킹: BUY 우선 + 확신 내림차순
    order = {"BUY": 0, "HOLD": 1, "AVOID": 2}
    results.sort(key=lambda r: (order.get(r.get("action"), 3), -(r.get("confidence") or 0)))
    buys = [r for r in results if r.get("action") == "BUY"]

    log(f"[4/4] 완료 — 매수결정 {len(buys)}종목")
    path = portfolio.save_picks(target_date, results, only_buy=True)
    log(f"      픽 저장: {path}")
    return {"date": target_date, "results": results, "buys": buys, "pick_path": path}


def format_report(out: dict) -> str:
    """텔레그램/콘솔용 마크다운 리포트."""
    lines = [f"# 🤖 멀티에이전트 종목 픽 · {out['date']}", ""]
    buys = out["buys"]
    if not buys:
        lines.append("오늘 매수결정(BUY) 종목 없음.")
    for r in buys:
        lines.append(f"## ✅ {r['name']} ({r['code']})  확신 {r['confidence']:.2f} · 비중 {r['weight_pct']:.0f}%")
        lines.append(f"- 종가 {int(r['price']):,}원 · 등락 {r['change']:+.2f}% · 거래대금 {r['amount_eok']:,.0f}억")
        lines.append(f"- {r['summary']}")
        for o in r.get("opinions", []):
            lines.append(f"  · {o.get('specialist')}: {o.get('action')}({o.get('confidence')}) {o.get('reason')}")
        lines.append("")
    # HOLD/AVOID 요약
    others = [r for r in out["results"] if r.get("action") != "BUY" and not r.get("error")]
    if others:
        lines.append("---")
        lines.append("### 보류/회피")
        for r in others[:15]:
            lines.append(f"- {r['name']}: {r['action']} ({r['confidence']:.2f})")
    return "\n".join(lines)
