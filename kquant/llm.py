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


class LLM:
    def __init__(self, backend: str = "claude", model: str | None = None,
                 timeout: int = 180):
        self.backend = backend
        self.model = model
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
