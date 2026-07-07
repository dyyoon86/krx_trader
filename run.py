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
    a.add_argument("--model", default=None)
    a.add_argument("--notify", action="store_true", help="텔레그램 발송(KQ_CHAT/KQ_KEY)")

    sub.add_parser("track", help="저장된 픽 페이퍼 수익률")

    args = ap.parse_args()

    if args.cmd == "analyze":
        out = pipeline.run(
            market=args.market, top_n=args.top, min_marcap=args.min_marcap,
            rank_by=args.rank_by, name_contains=args.contains,
            use_news=not args.no_news, backend=args.backend, model=args.model)
        report = pipeline.format_report(out)
        print("\n" + "=" * 60 + "\n" + report)
        if args.notify:
            from kquant import notify
            ok = notify.send_report(report, os.environ.get("KQ_CHAT", ""),
                                    os.environ.get("KQ_KEY", ""),
                                    filename=f"picks_{out['date']}.md")
            print("\n[텔레그램]", "발송 완료" if ok else "발송 실패(KQ_CHAT/KQ_KEY 확인)")

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


def _n(x):
    return f"{int(x):,}" if x else "-"


if __name__ == "__main__":
    sys.exit(main())
