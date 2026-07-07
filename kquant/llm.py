# -*- coding: utf-8 -*-
"""LLM 백엔드 — 기본은 로컬 claude CLI(키 불필요). 옵션으로 OpenAI/DeepSeek API.

- claude: `claude -p` 헤드리스 호출(사용자 로그인 상태 이용). 비용 0(구독 내).
- openai/deepseek: OPENAI_API_KEY / DEEPSEEK_API_KEY 환경변수 필요.
JSON 응답은 첫 번째 {...} 블록을 견고하게 추출한다.
"""
from __future__ import annotations
import json
import os
import re
import subprocess
import sys

# ── 비용 정책 ──────────────────────────────────────────────
# 백엔드별 '싼 기본 모델'(대량 호출용, tier1). 지정 없으면 이걸로 자동 선택.
CHEAP_DEFAULT = {
    "claude":   "claude-haiku-4-5-20251001",   # 가장 싼 Claude
    "openai":   "gpt-4o-mini",
    "deepseek": "deepseek-chat",               # 원래 저가
}
# 정밀 확인용 '중간가 모델'(tier2, 경계 종목만 소수 호출).
TIER2_DEFAULT = {
    "claude":   "claude-sonnet-4-6",
    "openai":   "gpt-4o-mini",                 # openai는 mini 유지(4o는 고가 차단)
    "deepseek": "deepseek-chat",
}
# 초고가 모델 → 자동 차단(싼 모델로 다운그레이드). sonnet은 tier2로 허용(제외).
_EXPENSIVE = re.compile(
    r"(opus|gpt-4o(?!-mini)|gpt-4-turbo|gpt-4$|gpt-5(?!-nano|-mini)|"
    r"\bo1\b|\bo3\b|reasoner|deepseek-r)", re.I)


def resolve_model(backend: str, requested: str | None, log=print) -> str:
    """지정 모델이 없으면 싼 기본값, 비싸면 자동 다운그레이드."""
    cheap = CHEAP_DEFAULT.get(backend, "")
    if not requested:
        return cheap
    if _EXPENSIVE.search(requested):
        log(f"[llm] ⚠ '{requested}'는 고가 모델 → '{cheap}'로 자동 다운그레이드(비용 보호)")
        return cheap
    return requested


class LLM:
    def __init__(self, backend: str = "claude", model: str | None = None,
                 timeout: int = 180, log=print):
        self.backend = backend
        self.model = resolve_model(backend, model, log=log)
        self.timeout = timeout

    # ── 공개 API ──
    def complete(self, prompt: str, system: str | None = None) -> str:
        if self.backend == "claude":
            return self._claude(prompt, system)
        if self.backend in ("openai", "deepseek"):
            return self._openai_like(prompt, system)
        raise ValueError(f"알 수 없는 backend: {self.backend}")

    def json(self, prompt: str, system: str | None = None) -> dict:
        raw = self.complete(prompt, system)
        return extract_json(raw)

    # ── 백엔드 구현 ──
    def _claude(self, prompt: str, system: str | None) -> str:
        text = prompt if not system else f"{system}\n\n{prompt}"
        cmd = ["claude", "-p"]
        if self.model:
            cmd += ["--model", self.model]
        p = subprocess.run(cmd, input=text, capture_output=True,
                           text=True, timeout=self.timeout)
        if p.returncode != 0:
            raise RuntimeError(f"claude CLI 실패: {p.stderr[:200]}")
        return p.stdout.strip()

    def _openai_like(self, prompt: str, system: str | None) -> str:
        import requests
        if self.backend == "deepseek":
            base = os.environ.get("DEEPSEEK_BASE", "https://api.deepseek.com")
            key = os.environ.get("DEEPSEEK_API_KEY", "")
            model = self.model or "deepseek-chat"
        else:
            base = os.environ.get("OPENAI_BASE", "https://api.openai.com")
            key = os.environ.get("OPENAI_API_KEY", "")
            model = self.model or "gpt-4o-mini"
        if not key:
            raise RuntimeError(f"{self.backend} API 키가 없습니다(환경변수 설정 필요)")
        msgs = ([{"role": "system", "content": system}] if system else []) + \
               [{"role": "user", "content": prompt}]
        r = requests.post(f"{base}/v1/chat/completions",
                          headers={"Authorization": f"Bearer {key}"},
                          json={"model": model, "messages": msgs, "temperature": 0.3},
                          timeout=self.timeout)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()


def extract_json(text: str) -> dict:
    """모델 응답에서 첫 JSON 객체를 추출(코드펜스/설명문 섞여도)."""
    if not text:
        raise ValueError("빈 응답")
    # ```json ... ``` 우선
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    cand = m.group(1) if m else None
    if not cand:
        # 첫 { 부터 균형 맞는 } 까지
        s = text.find("{")
        if s < 0:
            raise ValueError(f"JSON 없음: {text[:120]}")
        depth = 0
        for i in range(s, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    cand = text[s:i + 1]
                    break
    if not cand:
        raise ValueError(f"JSON 파싱 실패: {text[:120]}")
    return json.loads(cand)
