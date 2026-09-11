"""가격·하드웨어 담당: Steam 스토어 상세 API 참고 문서. 실제 연동은 미구현.

게임명이 아니라 appid로 조회한다. GameCandidate.steam_app_id를 사용한다.

- 상세: `GET https://store.steampowered.com/api/appdetails?appids=<appid>&cc=kr&l=korean`
  - `price_overview.final`은 원화 ×100 단위다 (2700000 = ₩27,000).
  - `pc_requirements`의 사양은 HTML 문자열이라 비교 전에 텍스트로 풀어야 한다.
"""
