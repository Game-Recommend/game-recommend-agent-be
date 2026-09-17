"""답변 문단의 내용 품질을 보는 LLM 심판.

코드로 볼 수 없는 두 가지만 본다.

1. `grounded` — 답변의 사실 주장이 Tool 결과로 뒷받침되는가. 가격·사양·리뷰 요약을 근거로
   함께 넘기고, 거기에 없는 수치나 단정을 지어냈는지 본다.
2. `linked` — 게임마다 사용자 조건과 연결된 이유를 썼는가.

심판도 틀린다. 점수는 프롬프트에 의존하고 사람이 공인한 정답이 아니다. 자동 정확도(score.py)에
섞지 않고 따로 보고한다. 심판에는 정답 라벨을 주지 않는다(애초에 이 평가셋에는 없다).
"""

from langsmith.wrappers import wrap_openai
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from app.schemas.recommendation import RecommendationResponse

JUDGE_MODEL = "gpt-4o-mini"

JUDGE_SYSTEM = """
당신은 게임 추천 서비스의 답변 문단을 검토한다. 추천 자체가 좋은지는 판단하지 않는다.
아래 두 가지만 본다.

1. grounded: 답변의 사실 주장이 제공된 근거(가격, 사양 판정, 리뷰 요약, 장르)로 뒷받침되는가.
   - 근거에 없는 가격·할인율·출시일·플레이타임·평점 수치를 답변이 말하면 낮은 점수.
   - 근거의 사양 판정과 반대되는 단정("무조건 잘 돌아간다")을 하면 낮은 점수.
   - 근거에 있는 내용을 자연스럽게 요약한 것은 문제가 아니다.

2. linked: 게임마다 사용자가 말한 조건과 연결된 이유가 있는가.
   - 사용자 질문의 조건(예산, 인원, 사양, 장르, 제외 조건)과 각 게임을 잇는 문장이 있으면 높은 점수.
   - "재미있습니다", "인기 게임입니다" 같은 조건과 무관한 일반 칭찬만 있으면 낮은 점수.

각 항목을 1~5로 채점하고 근거를 한국어 한 문장으로 적는다.
5=위반이 전혀 없다, 4=사소한 흠, 3=애매한 주장이 있다, 2=분명한 위반이 하나, 1=여러 위반.
추천이 0개인 경우, 조건에 맞는 후보가 없다고 설명했으면 두 항목 모두 5다.
""".strip()

JUDGE_USER = """
[사용자 질문]
{question}

[추천 근거 - Tool 결과]
{evidence}

[검토할 답변 문단]
{answer}
""".strip()


class JudgeVerdict(BaseModel):
    grounded_score: int = Field(ge=1, le=5, description="근거로 뒷받침되는 정도")
    grounded_reason: str = Field(description="한국어 한 문장")
    linked_score: int = Field(ge=1, le=5, description="조건과 이유가 연결된 정도")
    linked_reason: str = Field(description="한국어 한 문장")


def build_evidence(response: RecommendationResponse) -> str:
    """심판에게 주는 근거. Tool이 실제로 돌려준 값만 넣는다."""
    if not response.games:
        return "추천된 게임이 없다. 경고: " + ("; ".join(response.warnings) or "없음")

    lines = []
    for game in response.games:
        quote = game.price.quote
        price = f"{quote.amount_krw:,}원" if quote else "원화 가격 확인 불가"
        parts = [
            f"- {game.game.name}",
            f"  가격: {price} (판정 {game.price.check.status}: {game.price.check.reason})",
            f"  사양: 판정 {game.hardware.check.status} ({game.hardware.check.reason})",
        ]
        if game.game.genres or game.game.themes:
            labels = ", ".join([*game.game.genres, *game.game.themes])
            parts.append(f"  장르·테마: {labels}")
        if game.game.playtime_hours:
            parts.append(f"  IGDB 완료 시간: {game.game.playtime_hours}시간")
        if game.review and game.review.summary:
            parts.append(f"  리뷰 한줄평: {game.review.summary}")
        lines.append("\n".join(parts))

    conditions = response.conditions.model_dump(exclude_none=True, exclude_defaults=True)
    tail = [f"추출된 조건: {conditions}"]
    if response.warnings:
        tail.append(f"경고: {'; '.join(response.warnings)}")
    return "\n".join([*lines, *tail])


class AnswerJudge:
    def __init__(self, api_key: str, model: str = JUDGE_MODEL):
        # 심판 호출도 LangSmith 트레이스에 이름을 달고 남는다
        self._client = wrap_openai(
            AsyncOpenAI(api_key=api_key, timeout=30, max_retries=1), chat_name="AnswerJudge"
        )
        self.model = model

    async def judge(self, question: str, response: RecommendationResponse) -> JudgeVerdict:
        completion = await self._client.chat.completions.parse(
            model=self.model,
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM},
                {
                    "role": "user",
                    "content": JUDGE_USER.format(
                        question=question,
                        evidence=build_evidence(response),
                        answer=response.answer,
                    ),
                },
            ],
            response_format=JudgeVerdict,
        )
        verdict = completion.choices[0].message.parsed
        if verdict is None:
            raise ValueError("심판이 JudgeVerdict를 돌려주지 않았다")
        return verdict

    async def aclose(self) -> None:
        await self._client.close()
