# 질문 가공: Input LLM

사용자의 게임 추천 질문을 `GameConditions`로 변환하는 단계입니다. 게임 검색이나 추천 답변 생성은 이 단계에서 수행하지 않습니다.

## 파일별 역할

| 파일 | 역할 |
| --- | --- |
| `parser.py` | 질문 가공 객체가 따라야 하는 `parse(question) -> GameConditions` 비동기 계약 |
| `llm_parser.py` | OpenAI를 호출해 계약을 구현한 `LLMQueryParser`와 직접 실행용 CLI |
| `conditions.py` | 질문 가공 결과이자 후속 게임 검색 도구의 입력 모델 |
| `prompts.py` | 조건 추출 규칙과 사용자 질문 전달 형식 |

**실제 Input LLM의 호출·실행·동작 확인은 `llm_parser.py`를 기준으로 합니다.** `parser.py`는 구현체가 아니라 인터페이스 계약입니다.

## 실행

저장소 루트의 `.env`에 `OPENAI_API_KEY`를 설정하고 의존성을 설치한 뒤, 저장소 루트에서 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m app.pipeline.query_processing.llm_parser "RTX 3060과 시스템 RAM 16GB인 PC에서 친구 한 명과 온라인 협동으로 할 어드벤처 게임을 추천해줘. 공포 게임은 제외하고 3만 원 이하, 전체 플레이타임 30시간 이하로 30개 찾아줘."
```

`llm_parser.py`는 현재 `gpt-4o-mini`를 사용합니다. 실행 결과는 `GameConditions`의 JSON입니다.

```json
{
  "hardware": {
    "cpu": null,
    "gpu": "RTX 3060",
    "ram_gb": 16.0,
    "os": null,
    "raw_text": "RTX 3060과 시스템 RAM 16GB인 PC"
  },
  "genres": ["Adventure"],
  "excluded_genres": ["Horror"],
  "preferences": [],
  "players": 2,
  "connection": "online",
  "play_mode": "cooperative",
  "max_price_krw": 30000,
  "max_playtime_hours": 30.0,
  "max_session_minutes": null,
  "platforms": ["PC"],
  "recommendation_count": 30
}
```

LLM의 자유 텍스트 응답을 그대로 전달하지 않고, OpenAI의 구조화된 응답을 `GameConditions`로 검증합니다. API 호출 실패나 유효하지 않은 응답은 예외로 전달합니다.

## 조건 해석 규칙

- 질문에 없는 조건은 `null` 또는 빈 목록으로 둡니다. 추천 개수를 말하지 않으면 `recommendation_count=3`이며 허용 범위는 1~30개입니다.
- `hardware`에는 명시된 CPU 모델, GPU 모델, **시스템 RAM** 용량, OS만 기록합니다. 원문의 관련 표현은 `raw_text`에 보존합니다. GPU의 VRAM 용량을 시스템 RAM으로 기록하지 않습니다.
- `genres`와 `excluded_genres`는 서비스의 **통합 게임 분류**입니다. `Adventure`, `Shooter` 같은 IGDB 장르뿐 아니라 `Horror`, `Fantasy` 같은 테마 성격의 값도 들어갈 수 있습니다. `themes`와 `excluded_themes` 필드는 사용하지 않습니다.
- `"친구 한 명과"`는 사용자 포함 `players=2`입니다. 인원수가 없는 `"친구랑"`은 `players=null`입니다. 친구와 플레이한다는 이유만으로 협동 또는 온라인 플레이를 추정하지 않습니다.
- `"3만 원 이하"`는 `max_price_krw=30000`, `"3만 원 미만"`은 `29999`입니다. `"무료 게임만"`은 `0`이고, `"무료면 좋겠다"`는 가격 제한이 아닌 `preferences`에 기록합니다.
- 게임 **전체 완료 시간**은 `max_playtime_hours`, 한 판 또는 한 번의 **세션 시간**은 `max_session_minutes`에 기록합니다.
- `PC`처럼 플랫폼을 명시하면 하드웨어 정보의 유무와 관계없이 `platforms`에 기록합니다.

## 후속 도구와의 연결

`LLMQueryParser.parse(question)`의 반환값을 게임 검색 단계에 전달합니다. 검색 담당 구현은 `genres`와 `excluded_genres`의 이름을 그대로 IGDB `genres` 필터에 넣지 말고, 각 값에 대응하는 IGDB 장르 또는 테마 필드와 ID를 확인해 변환해야 합니다. Input LLM은 IGDB ID를 생성하지 않습니다.

현재 모델은 `genres`에 **좋아하는 분류**와 **반드시 포함해야 하는 분류**를 함께 담습니다. 후속 검색에서 두 표현을 다른 강도로 취급해야 한다면, 검색 담당자와 계약을 조정해 별도 필드를 추가해야 합니다.

## 확인 범위

위 실행 명령은 실제 LLM 응답의 구조와 조건 추출을 확인합니다. 이 실행만으로 IGDB 필터 적용, 가격 확인 또는 최종 추천 결과까지 검증되지는 않습니다.
