# kquant-agents

로컬에서 도는 **멀티 에이전트 한국주식 분석/픽 엔진**. 거대한 AI 하나에게 "이 주식 살까?"를 묻는 대신, 실제 증권사 리서치 데스크처럼 **5인의 전문 애널리스트 AI가 각자 관점으로 평가하고 최종 매수결정 에이전트가 종합**한다. ([TradingAgents](https://github.com/TauricResearch/TradingAgents) 아이디어의 한국형 경량 구현)

> ⚠️ **투자 판단 보조 도구입니다.** 산출물은 LLM의 의견이며 수익을 보장하지 않습니다. 실제 매매·손실은 본인 책임. 유료 종목추천 서비스는 국내 유사투자자문 규제 대상일 수 있습니다.

## 파이프라인 (영상의 노드 흐름을 코드로)

```
[스크리닝]  거래대금/시총/등락률 상위 (KOSPI/KOSDAQ, 테마 키워드)
   → [기술적 피처]  모멘텀·변동성·52주고점근접·VCP 수축·거래량급증
   → [뉴스]  종목별 최근 헤드라인(네이버, 베스트에포트)
   → [5인 애널리스트]  퀀트 · 성장투자 · 수급 · 역발상숏셀러 · 가치투자
   → [최종 매수결정]  BUY/HOLD/AVOID + 확신도 + 제안비중
   → [픽 저장]  날짜별 JSON → 페이퍼 수익률 트래킹 / 텔레그램 발송
```

## 구성
- **데이터**: [FinanceDataReader](https://github.com/FinanceData/FinanceDataReader) — 무키, KRX 전종목 거래대금·시총·OHLCV
- **LLM**: 기본 **로컬 `claude` CLI**(키 불필요, 구독 내 비용). 옵션 OpenAI/DeepSeek API
- **에이전트**: 종목당 1회 호출로 5인 의견 + 최종결정(JSON) — 비용·속도 최적화

## 설치
```bash
python3.11 -m venv .venv && . .venv/bin/activate   # 또는 uv venv
pip install -r requirements.txt
# LLM 백엔드: claude CLI 설치·로그인(기본) 또는 OPENAI_API_KEY/DEEPSEEK_API_KEY
```
> KRX 데이터 소스는 **한국 IP에서 안정적**입니다(해외에선 일부 소스 차단 가능).

## 사용
```bash
# 코스피 거래대금 상위 15종목 분석 → 픽 저장 + 콘솔 리포트
python run.py analyze --market KOSPI --top 15

# '반도체' 테마(종목명 필터) 상위 10, 뉴스 포함
python run.py analyze --contains 반도체 --top 10

# 등락률 상위(급등주) 코스닥 20
python run.py analyze --market KOSDAQ --rank-by change --top 20

# 저장된 픽의 페이퍼 수익률 트래킹
python run.py track

# 텔레그램 발송(cokacdir 환경)
KQ_CHAT=<chat> KQ_KEY=<key> python run.py analyze --market KOSPI --top 10 --notify
```

## 산출 예시
```
## ✅ 000660 SK하이닉스  확신 0.72 · 비중 15%
- 종가 215,000원 · 등락 +2.1% · 거래대금 46,388억
- 5인 중 수급·성장 2인 BUY … 단기 급등 리스크는 …
  · 퀀트: HOLD(0.45) ret_60d +108%지만 5일 -18% …
  · 성장투자: BUY(0.58) HBM·AI 사이클 수혜 …
  · 역발상숏셀러: AVOID(0.72) 사이클 피크 후 급락 …
```

## 2티어 모델 전략 (비용 최소 · 정밀도 보강)
- **tier1(저가·대량)**: 전 종목을 싼 모델로 스크리닝 — claude→`haiku`, openai→`gpt-4o-mini`, deepseek→`deepseek-chat`
- **tier2(중간가·경계만)**: BUY 또는 확신 높은 HOLD **경계 종목 소수(기본 최대 5개)**만 `sonnet`으로 재확인 → 결정 교정
- **초고가 차단**: opus / gpt-4o / gpt-4-turbo / o1·o3 / deepseek-r 등은 지정해도 자동 강등

```bash
python run.py analyze --market KOSPI --top 20            # 2티어 기본 ON (haiku×20 + sonnet×≤5)
python run.py analyze --top 20 --no-tier2               # 저가 단일(haiku만)
python run.py analyze --top 20 --tier2-model claude-sonnet-4-6 --max-tier2 3
python run.py analyze --backend deepseek                # deepseek-chat(tier1) + tier2 동일
```
> 예: tier1 haiku가 HOLD로 애매하게 낸 종목을 tier2 sonnet이 더 확신 있게 AVOID/BUY로 교정.

## 매일 자동화 (크론)
`run_daily.sh` = 장마감 후 분석→가상매매→계좌현황(+텔레그램). 평일 16:00 예약 예:
```cron
0 16 * * 1-5 KQ_CHAT=<chat> KQ_KEY=<key> /path/kquant-agents/run_daily.sh >> paper/cron.log 2>&1
```
- flock으로 중복 실행 방지, `KQ_ARGS`로 스크리닝 옵션 조정(기본 `--market KOSPI --top 20`)
- 비밀키는 크론 라인/환경변수로만 주입(소스에 없음)

## 로드맵
- [ ] 펀더멘털(PER/PBR/ROE) 노드 — pykrx/네이버 (한국 IP)
- [ ] 섹터/테마 자동 분류(반도체 공급망 등)
- [ ] 페르소나별 개별 호출 + Bull/Bear 토론 라운드
- [ ] 한국투자증권 KIS OpenAPI 연동 — 페이퍼→실매매
- [ ] 웹 노드 UI(드래그 파이프라인)

## 라이선스
MIT
