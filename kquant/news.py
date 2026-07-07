# -*- coding: utf-8 -*-
"""종목 뉴스 헤드라인 — 네이버 검색(무키) 베스트에포트. 실패해도 파이프라인은 진행."""
from __future__ import annotations
import re
import html
import requests

_UA = {"User-Agent": "Mozilla/5.0 (kquant-agents)"}


def headlines(name: str, limit: int = 8) -> list[str]:
    """네이버 뉴스 검색 결과 제목 리스트(베스트에포트)."""
    try:
        url = "https://search.naver.com/search.naver"
        r = requests.get(url, params={"where": "news", "query": f"{name} 주가"},
                         headers=_UA, timeout=8)
        r.raise_for_status()
        # 뉴스 제목 후보 추출(클래스명이 자주 바뀌므로 넓게)
        titles = re.findall(r'title="([^"]{6,80})"[^>]*class="news_tit"', r.text)
        if not titles:
            titles = re.findall(r'class="news_tit"[^>]*title="([^"]{6,80})"', r.text)
        out, seen = [], set()
        for t in titles:
            t = html.unescape(re.sub(r"<[^>]+>", "", t)).strip()
            if t and t not in seen:
                seen.add(t); out.append(t)
            if len(out) >= limit:
                break
        return out
    except Exception:
        return []
