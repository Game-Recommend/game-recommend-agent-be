"""리뷰 담당: Steam 리뷰 API 참고 문서. 실제 연동은 미구현.

GameCandidate.steam_app_id로 리뷰를 조회한다. 가격·사양 API는 steam_store.py에서 담당한다.

- 리뷰: `GET https://store.steampowered.com/appreviews/<appid>?json=1`
  - `query_summary`에 `review_score_desc`(예: "Overwhelmingly Positive"),
    `total_positive`, `total_negative`가 있다.
  - `reviews[].review`가 리뷰 본문이다 — 리뷰 요약(tools/review_summary.py)의 입력.
"""
