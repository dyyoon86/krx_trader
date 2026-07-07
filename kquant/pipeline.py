# -*- coding: utf-8 -*-
"""오케스트레이션 — 스크리닝 → (종목별) 피처+뉴스 → 멀티에이전트 분석 → 랭킹/저장.

영상의 노드 흐름을 코드로: [스크리닝]→[거래대금/시총]→[뉴스]→[5애널리스트]→[최종매수결정]
"""
from __future__ import annotations
import datetime as dt

from . import data, news as newsmod, agents, portfolio
from .llm import LLM, TIER2_DEFAULT


def run(*, market=None, top_n=20, min_marcap=3e11, rank_by="amount",
        name_contains=None, include=None, use_news=True, backend="claude", model=None,
        target_date=None, two_tier=True, tier2_model=None,
        max_tier2=5, escalate_min_conf=0.45, log=print) -> dict:
    target_date = target_date or dt.date.today().strftime("%Y-%m-%d")
    llm = LLM(backend=backend, model=model, log=log)     # tier1(저가)
    log(f"[llm] tier1={llm.model} (저가 대량)"
        + (f" · tier2={tier2_model or TIER2_DEFAULT.get(backend)} (경계 정밀)" if two_tier else ""))

    log(f"[1/4] 스크리닝 — market={market or '전체'} rank_by={rank_by} top{top_n}"
        + (f" 테마='{name_contains}'" if name_contains else ""))
    universe = data.screen(market=market, top_n=top_n, min_marcap=min_marcap,
                           rank_by=rank_by, name_contains=name_contains)
    # 관심종목(항상 포함) — 시장·거래대금과 무관하게 합류(중복 제거)
    forced = data.by_tickers(include)
    have = {s["code"] for s in universe}
    added = [s for s in forced if s["code"] not in have]
    if added:
        universe += added
        log(f"      + 관심종목 {len(added)}개 포함: " + ", ".join(s["name"] for s in added))
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
        r["tier"] = 1
        r["_feat"] = feat; r["_news"] = heads; r["_stock"] = s   # tier2 재분석용(임시)
        results.append(r)

    # ── tier2: 경계 종목만 중간가 모델로 정밀 재확인 ──
    if two_tier:
        cand = [r for r in results if not r.get("error") and (
            r["action"] == "BUY" or
            (r["action"] == "HOLD" and r["confidence"] >= escalate_min_conf))]
        order0 = {"BUY": 0, "HOLD": 1}
        cand.sort(key=lambda r: (order0.get(r["action"], 2), -r["confidence"]))
        cand = cand[:max_tier2]
        if cand:
            t2 = LLM(backend=backend, model=(tier2_model or TIER2_DEFAULT.get(backend)), log=log)
            log(f"[3.5] tier2 정밀 재확인 {len(cand)}종목 → {t2.model}")
            for r in cand:
                r2 = agents.analyze(t2, r["_stock"], r["_feat"], r["_news"], target_date)
                if r2.get("error"):
                    continue
                log(f"      ⇧ {r['name']}: tier1 {r['action']}({r['confidence']:.2f}) "
                    f"→ tier2 {r2['action']}({r2['confidence']:.2f})")
                r2["tier"] = 2; r2["tier1_action"] = r["action"]
                results[results.index(r)] = r2

    for r in results:                 # 임시 필드 제거
        for k in ("_feat", "_news", "_stock"):
            r.pop(k, None)

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
        tier = " · 🔬tier2확정" if r.get("tier") == 2 else ""
        lines.append(f"## ✅ {r['name']} ({r['code']})  확신 {r['confidence']:.2f} · 비중 {r['weight_pct']:.0f}%{tier}")
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
