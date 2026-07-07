# -*- coding: utf-8 -*-
"""멀티 에이전트 — 증권사 데스크처럼 5인의 전문 애널리스트가 각자 관점으로 평가하고
최종 매수결정 에이전트가 종합한다(TradingAgents 아이디어의 한국형 경량 구현).

비용/속도를 위해 종목당 1회 LLM 호출로 5개 페르소나 의견 + 최종결정을 함께 받는다.
(옵션으로 페르소나별 개별 호출도 가능하게 확장 여지를 남김)
"""
from __future__ import annotations
import json

SPECIALISTS = [
    ("퀀트",       "밸류에이션·수급·모멘텀 지표를 수치로 냉정하게. 과열/저평가를 숫자로 판단."),
    ("성장투자",   "매출·이익 성장성과 산업 사이클(파괴적 혁신, TAM 확대)에 주목. 미래 성장 프리미엄."),
    ("수급",       "거래대금·거래량 급증·외국인/기관 수급, 신고가 돌파 등 단기 수급 강도."),
    ("역발상숏셀러", "가장 비판적. 버블·사이클 피크·단기 과열·실적 미확인 리스크를 파고든다."),
    ("가치투자",   "저평가(저PER/PBR)·안전마진·현금흐름. 비싸면 산업이 좋아도 회피."),
]

_SYSTEM = (
    "당신은 한국 주식 증권사 리서치 데스크를 시뮬레이션하는 다중 애널리스트 엔진이다. "
    "주어진 종목 데이터와 뉴스만 근거로, 각 전문가가 자기 관점에서 독립적으로 판단한다. "
    "환각 금지: 데이터에 없는 수치를 지어내지 말 것. 반드시 지정한 JSON만 출력."
)


def _prompt(stock: dict, feat: dict, news: list[str], target_date: str) -> str:
    specialists_desc = "\n".join(f"- {n}: {d}" for n, d in SPECIALISTS)
    news_block = "\n".join(f"  · {h}" for h in news[:8]) or "  (수집된 뉴스 없음)"
    data = {
        "종목": stock["name"], "코드": stock["code"], "시장": stock.get("market"),
        "종가": stock.get("close"), "등락률%": stock.get("change"),
        "거래대금_억": round((stock.get("amount") or 0) / 1e8, 1),
        "시총_억": round((stock.get("marcap") or 0) / 1e8, 1),
        "기술적피처": feat,
    }
    return f"""[분석 기준일] {target_date}

[종목 데이터]
{json.dumps(data, ensure_ascii=False, indent=1)}

[최근 뉴스 헤드라인]
{news_block}

[전문가 5인] 각자 아래 관점으로 위 데이터를 독립 평가한다.
{specialists_desc}

각 전문가는 action(BUY/HOLD/AVOID), confidence(0~1), reason(한 문장, 데이터 근거)을 낸다.
그다음 '최종 매수결정' 에이전트가 5인 의견을 종합해 결론을 낸다.
- final.action: BUY/HOLD/AVOID
- final.confidence: 0~1
- final.weight_pct: BUY일 때 제안 비중(포트폴리오 현금 대비 %, 0~25), 아니면 0
- final.summary: 결정 사유 2~3문장(핵심 근거 + 리스크)

반드시 아래 JSON만 출력(설명·코드펜스 금지):
{{
 "opinions": [
   {{"specialist":"퀀트","action":"...","confidence":0.0,"reason":"..."}},
   {{"specialist":"성장투자","action":"...","confidence":0.0,"reason":"..."}},
   {{"specialist":"수급","action":"...","confidence":0.0,"reason":"..."}},
   {{"specialist":"역발상숏셀러","action":"...","confidence":0.0,"reason":"..."}},
   {{"specialist":"가치투자","action":"...","confidence":0.0,"reason":"..."}}
 ],
 "final": {{"action":"...","confidence":0.0,"weight_pct":0,"summary":"..."}}
}}"""


def analyze_batch(llm, items: list[tuple], target_date: str) -> list[dict]:
    """여러 종목을 1회 호출로 분석(백테스트 속도용). items=[(stock,feat), ...]
    각 종목에 5인 관점을 내부적으로 반영한 '최종 결정'을 배열로 받는다."""
    rows = []
    for s, feat in items:
        rows.append({"code": s["code"], "name": s["name"],
                     "종가": s.get("close"), "등락률%": s.get("change"),
                     "거래대금_억": round((s.get("amount") or 0) / 1e8, 1),
                     "기술적피처": feat})
    specialists_desc = ", ".join(n for n, _ in SPECIALISTS)
    prompt = f"""[분석 기준일] {target_date}
아래 여러 종목을 각각, 5인 전문가({specialists_desc}) 관점을 내부적으로 종합해 최종 판단하라.
데이터에 없는 수치 지어내기 금지.

[종목들]
{json.dumps(rows, ensure_ascii=False)}

각 종목마다 action(BUY/HOLD/AVOID), confidence(0~1), weight_pct(BUY일때 0~25 아니면 0),
reason(한 문장, 데이터 근거)을 낸다. 아래 JSON만 출력:
{{"decisions":[{{"code":"...","action":"...","confidence":0.0,"weight_pct":0,"reason":"..."}}]}}"""
    try:
        res = llm.json(prompt, system=_SYSTEM)
    except Exception:
        return [{"code": s["code"], "name": s["name"], "error": "batch 분석 실패"} for s, _ in items]
    dmap = {d.get("code"): d for d in res.get("decisions", [])}
    out = []
    for s, feat in items:
        d = dmap.get(s["code"], {})
        out.append({
            "code": s["code"], "name": s["name"], "market": s.get("market"),
            "price": s.get("close"), "change": s.get("change"),
            "amount_eok": round((s.get("amount") or 0) / 1e8, 1), "opinions": [],
            "action": (d.get("action") or "HOLD").upper(),
            "confidence": float(d.get("confidence") or 0),
            "weight_pct": float(d.get("weight_pct") or 0),
            "summary": d.get("reason") or "",
        })
    return out


def analyze(llm, stock: dict, feat: dict, news: list[str], target_date: str) -> dict:
    """종목 1개를 5인 애널리스트 + 최종결정으로 분석 → 결과 dict."""
    prompt = _prompt(stock, feat, news, target_date)
    try:
        res = llm.json(prompt, system=_SYSTEM)
    except Exception as e:
        return {"code": stock["code"], "name": stock["name"], "error": str(e)[:160]}
    final = res.get("final", {}) or {}
    return {
        "code": stock["code"], "name": stock["name"], "market": stock.get("market"),
        "price": stock.get("close"), "change": stock.get("change"),
        "amount_eok": round((stock.get("amount") or 0) / 1e8, 1),
        "opinions": res.get("opinions", []),
        "action": (final.get("action") or "HOLD").upper(),
        "confidence": float(final.get("confidence") or 0),
        "weight_pct": float(final.get("weight_pct") or 0),
        "summary": final.get("summary") or "",
    }
