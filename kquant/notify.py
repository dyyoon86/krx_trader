# -*- coding: utf-8 -*-
"""텔레그램 발송 — cokacdir CLI로 리포트 파일 전송(사용자 미니PC 환경)."""
from __future__ import annotations
import os
import subprocess
import tempfile

COKAC = os.environ.get("COKAC_BIN", "/home/dyyoon/.local/bin/cokacdir")


def send_report(text: str, chat: str, key: str, filename: str = "picks.md") -> bool:
    """텍스트 리포트를 파일로 저장 후 cokacdir --sendfile 로 전송."""
    if not (chat and key and os.path.exists(COKAC)):
        return False
    d = tempfile.mkdtemp(prefix="kq_")
    path = os.path.join(d, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    try:
        subprocess.run([COKAC, "--sendfile", path, "--chat", str(chat), "--key", key],
                       capture_output=True, timeout=60)
        return True
    except Exception:
        return False
