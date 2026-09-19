"""추천 목록 두 개 중 어느 쪽이 질문에 더 맞는지 고르는 LLM 심판.

절대 점수(1~5)는 같은 코드로도 실행마다 0.1~0.3씩 흔들렸다(evals/agent_e2e/REPORT.md). 그래서 한
질문에 대한 두 목록을 나란히 놓고 고르게 한다. 심판에게는 어느 쪽이 에이전트의 목록인지 알리지 않고,
자리(A/B)를 바꿔 두 번 묻는다(score.combine).

심판도 틀린다. 사람이 공인한 정답이 아니며, 같은 후보 풀에서 나온 두 목록의 상대 비교로만 읽는다.
"""

from typing import Literal

from langsmith.wrappers import wrap_openai
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from app.schemas.game import GameCandidate

JUDGE_MODEL = "gpt-4o-mini"
SUMMARY_MAX_CHARS = 300

JUDGE_SYSTEM = """
당신은 게임 추천 서비스의 추천 목록 두 개를 비교한다. 같은 질문에 대한 목록 A와 목록 B다.
사용자의 질문에 드러난 취향·상황·의도에 어느 목록이 더 잘 맞는지만 판단한다.

- 근거는 제공된 게임 정보(분류, 소개, 완료 시간, 가격)다. 게임의 인기나 명성은 기준이 아니다.
- 예산·사양 같은 필수 조건은 두 목록 모두 이미 통과했다. 다시 따지지 않는다.
- 목록 안의 순서와 목록의 자리(A/B)는 의미가 없다.
- 질문의 취향에 맞는 게임이 더 많은 쪽, 어긋나는 게임이 더 적은 쪽이 낫다.
- 두 목록이 질문에 맞는 정도가 비슷하거나, 질문에 고를 기준이 없으면 tie다. 억지로 고르지 않는다.

winner는 "A", "B", "tie" 중 하나다.
reason은 어느 게임이 왜 맞거나 어긋나는지 한국어 한두 문장으로 적는다.
""".strip()

JUDGE_USER = """
[사용자 질문]
{question}

[목록 A]
{list_a}

[목록 B]
{list_b}
""".strip()


class PairVerdict(BaseModel):
    winner: Literal["A", "B", "tie"] = Field(description="질문에 더 맞는 목록")
    reason: str = Field(description="한국어 한두 문장")


def describe_game(game: GameCandidate, amount_krw: int | None) -> str:
    """심판에게 주는 게임 하나의 정보. IGDB와 가격 Tool이 돌려준 값만 넣는다."""
    parts = [f"- {game.name}"]
    if game.genres or game.themes:
        parts.append(f"  분류: {', '.join([*game.genres, *game.themes])}")
    if game.playtime_hours:
        parts.append(f"  완료 시간: {round(game.playtime_hours, 1):g}시간")
    if amount_krw is not None:
        parts.append(f"  가격: {amount_krw:,}원")
    if summary := (game.summary or "").strip():
        if len(summary) > SUMMARY_MAX_CHARS:
            summary = summary[:SUMMARY_MAX_CHARS].rstrip() + "…"
        parts.append(f"  소개: {summary}")
    return "\n".join(parts)


def describe_list(games: list[GameCandidate], amounts: dict[int, int | None]) -> str:
    return "\n".join(describe_game(game, amounts.get(game.igdb_id)) for game in games)


class PairJudge:
    def __init__(self, api_key: str, model: str = JUDGE_MODEL):
        self._client = wrap_openai(
            AsyncOpenAI(api_key=api_key, timeout=30, max_retries=1), chat_name="PairJudge"
        )
        self.model = model

    async def judge(self, question: str, list_a: str, list_b: str) -> PairVerdict:
        completion = await self._client.chat.completions.parse(
            model=self.model,
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM},
                {
                    "role": "user",
                    "content": JUDGE_USER.format(question=question, list_a=list_a, list_b=list_b),
                },
            ],
            response_format=PairVerdict,
        )
        verdict = completion.choices[0].message.parsed
        if verdict is None:
            raise ValueError("심판이 PairVerdict를 돌려주지 않았다")
        return verdict

    async def aclose(self) -> None:
        await self._client.close()
