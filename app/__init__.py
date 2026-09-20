"""앱 패키지. import 시점에 `.env`를 os.environ에 올린다.

`app/config.py`의 Settings는 `.env`를 직접 읽지만, 환경 변수를 그대로 보는 쪽도 있다.

- `app/clients/steam_reviews.py`가 `OPENAI_API_KEY`를 os.environ에서 읽는다
- LangSmith 추적(`LANGSMITH_*`)은 LangChain·langsmith가 환경 변수만 보고 켠다

여기 두면 `app.` 아래 무엇을 먼저 import하든 순서와 무관하게 키가 올라간다.
이미 있는 환경 변수는 덮어쓰지 않으므로 배포 환경(Vercel 등)의 값이 우선한다.
"""

import warnings

from dotenv import load_dotenv

load_dotenv()

# wrap_openai(app/pipeline/query_processing/llm_parser.py 등)가 `.parse()` 응답을 트레이스에
# 남길 때, ParsedChatCompletion.parsed의 선언 타입이 None이라 Pydantic이 호출마다 직렬화 경고를
# 낸다. 추적을 꺼도 나오고 기능에는 영향이 없으나 추천 요청마다 로그를 채우므로 이 경고만 막는다.
warnings.filterwarnings(
    "ignore",
    message="Pydantic serializer warnings",
    category=UserWarning,
    module=r"pydantic\.main",
)
