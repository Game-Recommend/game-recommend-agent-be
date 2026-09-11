"""Steam 스토어 — 원화 가격, PC 사양, 리뷰. 키가 필요 없다.

게임명이 아니라 appid로 조회한다. CheapShark 검색 결과의 `steamAppID`로 이을 수 있다.

- 상세: `GET https://store.steampowered.com/api/appdetails?appids=<appid>&cc=kr&l=korean`
  - `price_overview.final`은 원화 ×100 단위다 (2700000 = ₩27,000).
  - `pc_requirements`의 사양은 HTML 문자열이라 비교 전에 텍스트로 풀어야 한다.
- 리뷰: `GET https://store.steampowered.com/appreviews/<appid>?json=1`
  - `query_summary`에 `review_score_desc`(예: "Overwhelmingly Positive"),
    `total_positive`, `total_negative`가 있다.
  - `reviews[].review`가 리뷰 본문이다 — 리뷰 요약(pipeline/review_summarizer.py)의 입력.
"""
