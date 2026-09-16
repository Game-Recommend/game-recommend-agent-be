import asyncio
import os

import httpx
from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI


# =========================================================
# 1. Steam 리뷰 가져오기
# =========================================================

async def get_steam_reviews(
    app_id: int,
    language: str,
    max_reviews: int = 100
) -> list[dict]:

    url = f"https://store.steampowered.com/appreviews/{app_id}"

    params = {
        "json": 1,
        "language": language,
        "filter": "all",
        "num_per_page": max_reviews,
        "purchase_type": "all"
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            url,
            params=params
        )
        response.raise_for_status()

    data = response.json()

    reviews = []

    for item in data.get("reviews", []):
        text = item.get("review", "").strip()

        # 너무 짧아서 정보량이 적은 리뷰 제거
        if len(text) < 80:
            continue

        reviews.append({
            "text": text,
            "language": item.get("language"),
            "positive": item.get("voted_up"),
            "votes_up": item.get("votes_up", 0),
            "source_url": (
                f"https://store.steampowered.com/"
                f"appreviews/{app_id}?json=1&language={language}"
            )
        })

    return reviews


# =========================================================
# 2. 도움이 된 리뷰 우선 선택
# =========================================================

def select_helpful_reviews(
    reviews: list[dict],
    limit: int
) -> list[dict]:

    return sorted(
        reviews,
        key=lambda x: x["votes_up"],
        reverse=True
    )[:limit]


# =========================================================
# 3. 한국어 우선 + 부족하면 영어 보충
# =========================================================

async def collect_reviews(
    app_id: int,
    target_count: int = 20
) -> list[dict]:

    korean = await get_steam_reviews(
        app_id,
        language="koreana"
    )

    selected = select_helpful_reviews(
        korean,
        target_count
    )

    if len(selected) >= target_count:
        return selected

    english = await get_steam_reviews(
        app_id,
        language="english"
    )

    need = target_count - len(selected)

    selected += select_helpful_reviews(
        english,
        need
    )

    return selected


# =========================================================
# 4. 리뷰 → 한줄평
# =========================================================

async def summarize_reviews(
    game_name: str,
    reviews: list[dict],
    llm: ChatOpenAI
) -> str:

    if not reviews:
        return "리뷰 정보를 충분히 확보하지 못했습니다."

    formatted_reviews = []

    for review in reviews:
        formatted_reviews.append(
            f"""
추천 여부: {"추천" if review["positive"] else "비추천"}
리뷰: {review["text"][:1000]}
"""
        )

    review_text = "\n\n".join(formatted_reviews)

    prompt = f"""
게임 이름: {game_name}

아래 Steam 사용자 리뷰를 종합해서
한국어 한줄평을 작성하세요.

조건:
- 100자 정도
- 가장 많은 리뷰에서 반복된 특징을 우선적으로 반영할 것
- 일부 리뷰에서만 언급된 요소는 중심 내용으로 사용하지 말 것
- 실제로 중요하게 언급되는 핵심 플레이 요소를 우선할 것
- 장점과 단점이 모두 반복적으로 나타날 경우 함께 반영할 것
- 한두 개 리뷰에서만 등장하는 특이한 의견은 대표 평가로 사용하지 말 것
- 게임회사 논란, 가격, DLC, 과금 정책 등은 여러 리뷰에서 반복될 때만 반영할 것
- 제공된 리뷰에 없는 사실을 만들어내지 말 것
- 반드시 한 문장만 출력할 것

리뷰:
{review_text}
"""

    response = await llm.ainvoke(prompt)

    return response.content.strip()


# =========================================================
# 5. LangChain Tool
# =========================================================

@tool
async def summarize_game_reviews(
    games: list[dict]
) -> list[dict]:
    """
    최종 추천된 Steam 게임들의 실제 사용자 리뷰를 수집하고
    게임별 한국어 한줄평을 생성합니다.

    여러 게임의 리뷰 요약이 필요한 경우 게임마다 따로 호출하지 말고,
    모든 게임을 games 리스트에 넣어 한 번만 호출하세요.

    Args:
        games:
            리뷰를 요약할 게임 목록.
            각 게임에는 다음 값이 포함되어야 합니다.
            - igdb_id: IGDB 게임 ID
            - name: 게임 이름
            - steam_app_id: Steam App ID

    Returns:
        게임별 igdb_id, 한줄 리뷰 요약, 리뷰 출처 목록
    """

    llm = ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0
    )

    results = []

    for game in games:

        reviews = await collect_reviews(
            game["steam_app_id"]
        )

        summary = await summarize_reviews(
            game_name=game["name"],
            reviews=reviews,
            llm=llm
        )

        source_urls = []

        for review in reviews:
            source_url = review["source_url"]

            if source_url not in source_urls:
                source_urls.append(source_url)

        results.append({
            "igdb_id": game["igdb_id"],
            "summary": summary,
            "source_urls": source_urls
        })

    return results


# =========================================================
# 6. Tool 자체 테스트
# =========================================================

async def main():

    load_dotenv()

    tool_result = await summarize_game_reviews.ainvoke({
        "games": [
            {
                "igdb_id": 17000,
                "name": "Stardew Valley",
                "steam_app_id": 413150
            },
            {
                "igdb_id": 132181,
                "name": "Resident Evil 4",
                "steam_app_id": 2050650
            }
        ]
    })

    print("=== Review Summary Tool 실행 결과 ===")

    for result in tool_result:
        print(result)


if __name__ == "__main__":
    asyncio.run(main())