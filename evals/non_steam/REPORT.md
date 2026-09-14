# 비Steam 폴백 실측 결과

2026-09-14 16:26 KST, PCGamingWiki·CheapShark·Frankfurter를 실제로 호출하고 C03·C04는 `.env`의 `gpt-4o-mini`로 판정했다.
결과 파일은 `runs/baseline/`이며 데이터셋 SHA-256은 `783b0f0b…`이다.

같은 날 먼저 돌린 v2(사양 출처 RAWG)와 비교해 사양 출처를 PCGamingWiki로 바꾼 근거를 남긴다.
v2 실행 결과 파일은 보존하지 않았고, 수치는 당시 `summary.json`에서 옮겨 적었다.

## 사양 출처 교체 근거 (v2 RAWG → v3 PCGamingWiki)

같은 20개 게임에 대한 결과다. 두 출처 모두 정규화한 제목의 정확 일치(리다이렉트 포함)만 인정했다.

| 항목 | RAWG (v2) | PCGamingWiki (v3) |
|---|---|---|
| 제목 매칭 | 18/20 | 19/20 (미매칭 1건은 음성 대조군) |
| 매칭 중 최소 사양 보유 | 5/18 (27.8%) | 18/19 (94.7%) |
| 최소 사양 보유 시 4개 항목(OS·CPU·GPU·RAM) 모두 파싱 | 5/5 | 16/18 |
| 필요한 API 키 | RAWG 키 | 없음 |
| 출처 링크 | 없음 | 페이지 URL, 다수 페이지에 공식 사양 페이지 링크 |

RAWG가 사양을 주지 못한 LoL, 발로란트, 포트나이트, 로블록스, 하스스톤, 알란 웨이크 2, 킹덤하츠 3 등이 모두 채워졌다.
Fortnite는 RAWG 등록명('Fortnite Battle Royale')이 달라 못 찾았는데 PCGamingWiki는 'Fortnite'로 등록돼 있어
기대값을 매칭으로 정정했다(W05). Alan Wake 2는 'Alan Wake II'로 리다이렉트되며 `redirects=1`로 처리됐다.

이 결과로 RAWG 클라이언트와 `RAWG_API_KEY`를 제거했다. 사양 폴백은 PCGamingWiki 한 단계다.

## 집계 (v3)

| 축 | 결과 |
|---|---|
| PCGamingWiki 기대 매칭 6건 일치 | 6/6 |
| **매칭 중 최소 사양 보유** | **18/19** (Teamfight Tactics만 템플릿 없음) |
| 항목별 파싱: OS / CPU / GPU / RAM | 18 / 18 / 16 / 18 |
| 가격 15건 통과 | 15/15 |
| 가격 결과 분포 | free 6, quoted 4, omitted 5, unavailable 0 |
| USD→KRW 환율 | 1342.79 (Frankfurter, 2026-09-11 고시) |
| 판정 일관성 5건 (파싱 항목 동일 + 상태 동일 + 기대 일치) | 5/5 |
| LLM 판정 실패 | 0/2 |
| 외부 API 오류 | 0 |

## 관찰

**GPU가 빠진 2건은 데이터 문제다.** Roblox와 Legends of Runeterra는 위키 템플릿 자체에 `minGPU`가 없다.
저사양 게임이라 개발사 공식 사양에도 GPU 항목이 없다. 사용자가 GPU 조건을 걸면 "비교할 공통 GPU·CPU 항목 없음"으로
`unknown`이 되는데, CPU·RAM은 비교되므로 판정 규칙상 올바른 결과다.

**대안 부품 결합이 판정기 입력에 그대로 들어간다.** PCGamingWiki는 `minGPU`, `minGPU2`, `minGPU3`를 따로 주는데
클라이언트가 " or "로 이어 붙인다. 원신은 "Nvidia GeForce GTX 1050 or Intel Iris Xe"가 되어, 판정기 프롬프트의
"여러 개면 가장 낮은 것과 비교" 규칙이 그대로 적용된다. Steam 원문의 "A or B" 표기와 형식이 같다.

**판정 일관성은 유지된다.** 위키 링크(`[[...]]`), `<ref>`, `{{ii}}` 아이콘 템플릿, 외부 링크가 섞인 템플릿을 넣어도
Steam HTML과 네 항목이 같게 파싱됐고 판정 상태도 모두 같았다.

**가격 폴백은 v2와 동일하다.** 무료 표 6건 0원, CheapShark 정확 일치 4건(Alan Wake 2,001원 / Alan Wake 2 67,126원 /
Deluxe 28,185원 / Tarkov 46,984원), 생략 5건, `unavailable` 0건.

## 한계와 다음 단계

- PCGamingWiki는 커뮤니티 위키라 항목 갱신 시점이 페이지마다 다르다. 이 수치는 2026-09-14 기준이다.
  `notes`의 공식 출처 링크는 아직 응답에 싣지 않고 페이지 URL만 `source_url`로 남긴다.
- 매칭은 정규화 제목의 정확 일치와 리다이렉트만 인정한다. 검색(opensearch)은 대소문자·기호 차이만 흡수한다.
- Windows 템플릿만 쓴다. macOS·Linux 사양은 Steam 폴백과 같은 이유로 판정하지 않는다.
- `evals/price_hardware/test_eval.py`의 검사 3건은 이번 변경과 무관하게 실패한다(v2 라벨 변경 이후 갱신되지 않음).
  기존 담당자가 정리해야 한다.
