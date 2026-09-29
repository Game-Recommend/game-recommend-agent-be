"""LangGraph Studio 진입점. `make studio`(`langgraph dev`)가 langgraph.json을 읽고
여기의 `graph`를 띄운다.

`app/main.py`처럼 `.env` 설정으로 추천기를 한 번 조립하고, 운영과 같은 그래프를 내보낸다
(`AgentRecommender.studio_graph`). Studio에서 한 번 돌리면 `/recommend` 한 건과 같이 OpenAI·IGDB·
Steam을 실제로 부른다. 공유 클라이언트는 닫지 않는다. 개발 서버가 내려가면 프로세스와 함께 정리된다.

`.env`는 `make studio`가 서버를 띄우기 전에 올리고, 이미 있는 환경 변수는 덮어쓰지 않는다
(`python -m dotenv run --no-override`). langsmith는 서버가 시작할 때 환경 변수를 읽어 캐시한다.
그래서 여기서 `app/__init__.py`의 `load_dotenv()`로 처음 올리면 키는 들어가도 LangSmith 추적은
켜지지 않는다. `langgraph dev`를 직접 치면 그렇게 된다. langgraph.json의 `env`는 셸 환경 변수를
덮어써서 `LANGSMITH_TRACING=false make studio`가 듣지 않으므로 쓰지 않는다.

서버는 이 파일을 이벤트 루프 밖의 스레드에서 import한다. 그래서 여기서 HTTP 클라이언트를 만들어도
langgraph dev의 동기 I/O 검사에 걸리지 않는다.
"""

from app.assembly import assemble, missing_settings
from app.config import get_settings

assembled = assemble()
if assembled is None:
    missing = ", ".join(missing_settings(get_settings()))
    raise RuntimeError(f"필수 설정이 비어 있습니다: {missing}")
graph = assembled.recommender.studio_graph()
