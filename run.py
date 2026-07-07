#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kquant-agents CLI.

예:
  # 코스피 거래대금 상위 15종목 분석 → 픽 저장 + 콘솔 리포트
  python run.py analyze --market KOSPI --top 15

  # '반도체' 테마(종목명 필터) 상위 10, 뉴스 포함
  python run.py analyze --contains 반도체 --top 10

  # 저장된 픽 페이퍼 수익률 트래킹
  python run.py track

  # 텔레그램 발송(환경변수 KQ_CHAT, KQ_KEY 필요)
  python run.py analyze --market KOSPI --top 10 --notify
"""
import argparse
import os
import sys

from kquant import pipeline, portfolio


def main():
    ap = argparse.ArgumentParser(prog="kquant-agents")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("analyze", help="스크리닝→멀티에이전트 분석→픽 저장")
    a.add_argument("--market", choices=["KOSPI", "KOSDAQ"], default=None)
    a.add_argument("--top", type=int, default=15)
    a.add_argument("--min-marcap", type=float, default=3e11, help="최소 시총(원)")
    a.add_argument("--rank-by", choices=["amount", "change", "marcap"], default="amount")
    a.add_argument("--contains", default=None, help="종목명 포함 키워드(간이 테마)")
    a.add_argument("--no-news", action="store_true")
    a.add_argument("--backend", default="claude", choices=["claude", "openai", "deepseek"])
    a.add_argument("--model", default=None, help="tier1 모델(비우면 저가 자동)")
    a.add_argument("--no-tier2", action="store_true", help="2티어 끄기(전부 저가 단일)")
    a.add_argument("--tier2-model", default=None, help="tier2 정밀모델(비우면 sonnet)")
    a.add_argument("--max-tier2", type=int, default=5, help="tier2 재확인 최대 종목수")
    a.add_argument("--notify", action="store_true", help="텔레그램 발송(KQ_CHAT/KQ_KEY)")

    sub.add_parser("track", help="저장된 픽 단순 수익률 조회")

    pp = sub.add_parser("paper", help="가상계좌 페이퍼 트레이딩(분석→매매→스냅샷)")
    pp.add_argument("--market", choices=["KOSPI", "KOSDAQ"], default=None)
    pp.add_argument("--top", type=int, default=20)
    pp.add_argument("--contains", default=None)
    pp.add_argument("--rank-by", choices=["amount", "change", "marcap"], default="amount")
    pp.add_argument("--backend", default="claude", choices=["claude", "openai", "deepseek"])
    pp.add_argument("--no-news", action="store_true")
    pp.add_argument("--notify", action="store_true")

    sub.add_parser("account", help="페이퍼 계좌 현황")

    args = ap.parse_args()

    if args.cmd == "analyze":
        out = pipeline.run(
            market=args.market, top_n=args.top, min_marcap=args.min_marcap,
            rank_by=args.rank_by, name_contains=args.contains,
            use_news=not args.no_news, backend=args.backend, model=args.model,
            two_tier=not args.no_tier2, tier2_model=args.tier2_model,
            max_tier2=args.max_tier2)
        report = pipeline.format_report(out)
        print("\n" + "=" * 60 + "\n" + report)
        if args.notify:
            from kquant import notify
            ok = notify.send_report(report, os.environ.get("KQ_CHAT", ""),
                                    os.environ.get("KQ_KEY", ""),
                                    filename=f"picks_{out['date']}.md")
            print("\n[텔레그램]", "발송 완료" if ok else "발송 실패(KQ_CHAT/KQ_KEY 확인)")

    elif args.cmd == "paper":
        from kquant import paper
        out = pipeline.run(
            market=args.market, top_n=args.top, rank_by=args.rank_by,
            name_contains=args.contains, use_news=not args.no_news, backend=args.backend)
        print("\n── 페이퍼 매매 ──")
        res = paper.run_day(out, log=print)
        snap = res["snapshot"]
        st = paper.status()
        report = _paper_report(out, st, snap)
        print("\n" + "=" * 60 + "\n" + report)
        if args.notify:
            from kquant import notify
            notify.send_report(report, os.environ.get("KQ_CHAT", ""),
                               os.environ.get("KQ_KEY", ""),
                               filename=f"paper_{out['date']}.md")

    elif args.cmd == "account":
        from kquant import paper
        st = paper.status()
        print(f"평가액 {st['equity']:,}원 / 초기 {st['initial']:,}원  "
              f"({st['total_return_pct']:+.2f}%)  현금 {st['cash']:,}  실현손익 {st['realized_pnl']:+,}")
        if st["positions"]:
            print(f"\n{'종목':<12}{'수량':>7}{'진입':>10}{'현재':>10}{'수익률%':>9}{'평가액':>12}")
            for p in st["positions"]:
                print(f"{p['name']:<12}{p['shares']:>7,}{int(p['entry']):>10,}"
                      f"{int(p['current']):>10,}{p['return_pct']:>+9.2f}{p['value']:>12,}")
        else:
            print("보유 종목 없음(전액 현금).")

    elif args.cmd == "track":
        rows = portfolio.track()
        if not rows:
            print("저장된 픽이 없습니다. 먼저 analyze 를 실행하세요.")
            return
        print(f"{'날짜':<12}{'종목':<12}{'추천가':>10}{'현재가':>10}{'수익률%':>9}")
        for r in rows:
            ret = f"{r['return_pct']:+.2f}" if r['return_pct'] is not None else "-"
            print(f"{r['date']:<12}{r['name']:<12}{_n(r['entry']):>10}{_n(r['current']):>10}{ret:>9}")
        vals = [r["return_pct"] for r in rows if r["return_pct"] is not None]
        if vals:
            print(f"\n평균 수익률: {sum(vals)/len(vals):+.2f}%  (승률 {sum(1 for v in vals if v>0)/len(vals)*100:.0f}%)")


def _paper_report(out, st, snap):
    L = [f"# 📄 페이퍼 트레이딩 · {out['date']}", ""]
    L.append(f"평가액 **{st['equity']:,}원** ({st['total_return_pct']:+.2f}%) · "
             f"현금 {st['cash']:,} · 실현손익 {st['realized_pnl']:+,}")
    if st["positions"]:
        L.append("\n## 보유 종목")
        for p in st["positions"]:
            L.append(f"- {p['name']} {p['shares']:,}주 · 진입 {int(p['entry']):,} → "
                     f"현재 {int(p['current']):,} ({p['return_pct']:+.2f}%)")
    else:
        L.append("\n보유 종목 없음(전액 현금).")
    if out["buys"]:
        L.append("\n## 오늘 매수 후보(BUY)")
        for r in out["buys"]:
            L.append(f"- {r['name']} 확신 {r['confidence']:.2f} · 비중 {r['weight_pct']:.0f}%")
    return "\n".join(L)


def _n(x):
    return f"{int(x):,}" if x else "-"


if __name__ == "__main__":
    sys.exit(main())
