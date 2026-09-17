import asyncio
import sys

from langsmith.wrappers import wrap_openai
from openai import AsyncOpenAI

from app.config import get_settings
from app.pipeline.query_processing.conditions import GameConditions
from app.pipeline.query_processing.prompts import (
    QUERY_PARSER_SYSTEM,
    QUERY_PARSER_USER,
)


class LLMQueryParser:
    async def parse(self, question: str) -> GameConditions:
        api_key = get_settings().openai_api_key
        if not api_key:
            raise ValueError("OPENAI_API_KEY가 설정되지 않았습니다.")

        # wrap_openai: LANGSMITH_TRACING이 켜져 있으면 이 호출이 트레이스의 자식 run으로
        # 남는다. 꺼져 있으면 아무 일도 하지 않는다.
        async with AsyncOpenAI(api_key=api_key) as raw:
            client = wrap_openai(raw, chat_name="QueryParser")
            completion = await client.chat.completions.parse(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": QUERY_PARSER_SYSTEM},
                    {
                        "role": "user",
                        "content": QUERY_PARSER_USER.format(question=question),
                    },
                ],
                response_format=GameConditions,
            )

        parsed = completion.choices[0].message.parsed
        if parsed is None:
            raise ValueError("Input LLM이 GameConditions를 반환하지 않았습니다.")

        return GameConditions.model_validate(parsed.model_dump())


async def main() -> None:
    question = " ".join(sys.argv[1:]).strip()
    if not question:
        raise ValueError("검사할 게임 추천 질문을 명령어 뒤에 입력하세요.")

    conditions = await LLMQueryParser().parse(question)
    print(conditions.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())
