"""리뷰 담당: steam 리뷰 수집 + web fallback + llm 요약

GameCandidate.steam_app_id로 리뷰를 조회한다. 
steam review가 충분하지 않을 경우 tavily 웹검색으로 보충
- 리뷰: `GET https://store.steampowered.com/appreviews/<appid>?json=1`
  - `query_summary`에 `review_score_desc`(예: "Overwhelmingly Positive"),
    `total_positive`, `total_negative`가 있다.
  - `reviews[].review`가 리뷰 본문이다 — 리뷰 요약(tools/review_summary.py)의 입력.
  최종출력은 reviewsummaryclient 계약에 맞춰 list[reviewsummary]형태로 반환
"""

##steam만

import asyncio
import os

import httpx2 as httpx
from dotenv import load_dotenv
from openai import AsyncOpenAI

from app.schemas.game import GameCandidate
from app.schemas.review import ReviewSummary

load_dotenv()

class SteamReviewSummaryClient:
    """steam리뷰를 우선 사용하여 게임별 한줄평을 생성한다"""

    def __init__(self, *, max_concurrency: int = 4):

        self.llm = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.model = "gpt-4o-mini"
        self._semaphore = asyncio.Semaphore(max_concurrency)



##1. steam review 가져오기


    async def _get_steam_reviews(
        self,
        app_id: int, 
        language: str, 
        max_reviews:int = 50
        )->list[dict]:
        url = f"https://store.steampowered.com/appreviews/{app_id}"

        params = {
        "json" : 1,
        "language" : language,
        "filter":"all",
        "num_per_page":max_reviews,
        "purchase_type" : "all"
    }

    #요청 파라미터
    #json으로 응답을 받고 language는 한국어 또는 영어를 지정하기 위함
    #filter는 특정 기간이나 최근 리뷰만 보지 않고 전체 리뷰 범위를 대상으로 가져옴
    #num_per_page는 max_reviews는 최대 100이니까 그 중에서 좋은 리뷰만 추리는 구조
    #steam 구매자 여부 등으로 너무 좁게 제한하지 않고 전체 리뷰를 보기 위해 사용

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

            if len(text) < 80: ##짧은 리뷰를 버리는건 정보량이 너무 적음
                continue

            reviews.append({
            "text" : text,
            "source":"steam", ##web에서 가져온거랑 분리
            "language":item.get("language"),
            "positive": item.get("voted_up"), #추천 비추천 여부
            "votes_up" : item.get("votes_up", 0), #유저가 이 리뷰가 도움이 됐다 라고 평가한 수
            "source_url":(
                f"https://store.steampowered.com/"
                f"appreviews/{app_id}?json=1&language={language}"
            )
          })

        return reviews

##votes_up 순인 이유
##2. 도움이 된 순으로 선별

    async def _select_helpful_reviews(
        self,
        reviews: list[dict],
        limit: int = 10
        )->list[dict]:
      return sorted(
        reviews,
        key = lambda x: (
            x["votes_up"]
        ),
        reverse = True
      )[:limit]

#랜덤으로 20개 안뽑고 votes_up순으로 뽑냐면
#리뷰가 100개이지만 모든 리뷰 품질이 같지 않아서 사용자들이 도움이 됐다고 펴가한 리뷰 우선

# 한국어->영어 보충
    async def _collect_steam_reviews(
        self,
        app_id: int,
        target_count: int = 20
)->list[dict]:
    #한국어
      korean = await self._get_steam_reviews(
        app_id,
        language="koreana",
        max_reviews=100
    )
    #서비스 최종 출력이 한국어이기 때문에 한국어 리뷰가 충분하면
    #굳이 영어를 섞지 않는게 좋음

    #max_reviews는 후보군의 크기이고
    #target_count = 20은 실제로 llm에 넣을 리뷰 개수

      selected = await self._select_helpful_reviews(
        korean, 
        target_count
    )

    ##즉, steam_review100개 수집한 다음
    #필터링하고 votes_up정렬을 해서 20개 선택함
    #100개 전부 llm에 넣으면 토큰증가/비용증가
    #처리시간증가/중복의견많음/노이즈 증가


      if len(selected) >= target_count:
        return selected

    #한국어가 20개보다 부족하면 
    
      english = await self._get_steam_reviews(
            app_id,
            language= "english",
            max_reviews=100
        )
    #영어를 가져옴

      need = target_count - len(selected)
      selected += await self._select_helpful_reviews(
        english, need
    )
    #필요한 만큼 보충

      return selected


##다 가져오기
    async def _collect_all_reviews(
        self,
        steam_app_id : int,
        target_count: int = 20,
        min_steam_reviews:int = 5
)->list[dict]:
      

        return await self._collect_steam_reviews(
            steam_app_id,
            target_count=target_count
        )
    #min_steam_reviews로 나눈 이유는 19개여도 웹검색하면 비효율적이라서
    #20개가 이상적인 최대 리뷰 수이고 5개는 스팀만으로 요약 가능한 최소 기준

##리뷰 요약하기
#리뷰 하나당 최대 1000자로 자르는데 1. 토큰비용 2. 극단적으로 긴 리뷰 하나가 전체 프롬프트 지배 방지
#3. 보통 리뷰의 핵심내용은 앞쪽에도 충분히 담김
#20*1000자면 꽤 많은 정보이면서 무제한 입력 방지


##steam과 web을 분리한 이유는 steam은 추천/비추천이라는 명시적 구조 가짐
#but, web은 그런 필드가 없음
#web에 억지로 positive/negative붙이면 감성분석 필요
    async def _summarize_reviews(
        self,
    game_name: str,
    reviews: list[dict]
):
        if not reviews:
          return "리뷰 정보를 충분히 확보하지 못했습니다."
        formatted_reviews = []

        for review in reviews:

            if review["source"] == "steam":
                formatted_reviews.append(
                    f"""
출처: Steam
추천 여부: {"추천" if review["positive"] else "비추천"}
리뷰: {review["text"][:1000]}
"""
            )

            else:
              formatted_reviews.append(
                f"""
출처: Web
리뷰: {review["text"][:1000]}
"""
            )

        review_text = "\n\n".join(formatted_reviews)

        prompt = f"""
    게임 이름: {game_name}

아래 사용자 리뷰 및 웹 리뷰를 종합해서
한국어 한줄평을 작성하세요.

조건:
- 100자 정도
- 가장 많은 리뷰에서 반복된 특징을 우선적으로 반영할 것
- 일부 리뷰에서만 언급된 요소는 한줄평의 중심 내용으로 사용하지 말 것
- 해당 게임에서 실제로 중요하게 언급되는 핵심 플레이 요소를 우선할 것
- 전투, 탐험, 스토리, 난이도 등의 요소를 억지로 포함하지 말 것
- 장점과 단점이 모두 반복적으로 나타날 경우 함께 반영할 것
- 한두 개 리뷰에서만 등장하는 특이한 의견은 대표 평가로 사용하지 말 것
- 게임회사 논란, 가격, DLC, 과금 정책 등 일시적인 이슈는 여러 리뷰에서 반복될 때만 반영할 것
- 제공된 리뷰에 없는 사실을 만들어내지 말 것
- 반드시 한 문장만 출력할 것

리뷰:
{review_text}
"""

        response = await self.llm.responses.create(
           model = self.model,
           input = prompt,
        )
        return response.output_text.strip()

##로직 설명
##steam 리뷰 최대 100개 받고 80자 미만 제거, votes_up 높은 순 정렬
##상위 20개, 한국어 부족하면 영어 보충
##리뷰 당 최대 1000자만 llm에 전달
##100자 내외 한줄평

#프롬프트에서 특정요소를 억지로 포함하지 말라고 한 이유
#스타듀밸리같은 게임은 전투가 핵심이 아닌데 억지로 표현을 넣으면 안되기 때문에
#해당 게임에서 실제로 중요하게 언급되는 핵심 플레이 요소
#로 바꾸면 장르가 달라도 일반화가 잘됨
#장/단점이 모두 반복적으로 나타날 경우 함께 반영한다는데
#단점 리뷰 하나만 있다고 무조건 단점을 넣으면 대표성이 깨질 수 잇음
#그래서 반복될때만 반영하게 함
#회사 논란/가격/dlc 이슈를 낮게 보는 이유는
#우리의 목적은 게임 플레이 추천이기 때문
#제공된 리뷰에 없는 사실을 만들어내지 말것
#은 llm은 이미 게임을 알고있지만 리뷰밖 지식을 끌어오지 못하도록 함



    async def _summarize_one(
        self, game: GameCandidate
)->ReviewSummary:
        async with self._semaphore:
            reviews = await self._collect_all_reviews(
                steam_app_id = game.steam_app_id
        )

            summary = await self._summarize_reviews(
                game_name = game.name,
                reviews = reviews
        )

            source_urls = []

            for review in reviews:
                source_url = review.get("source_url")

                if(
                source_url
                and source_url not in source_urls
            ):
                    source_urls.append(source_url)

            return ReviewSummary(
                igdb_id=game.igdb_id,
                summary=summary,
                source_urls=source_urls
            )

    async def summarize(
        self, games: list[GameCandidate]
)->list[ReviewSummary]:
        valid_games = [game for game in games if game.steam_app_id is not None]

        return list(
            await asyncio.gather(*(self._summarize_one(game) for game in valid_games))
        )