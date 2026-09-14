"""RAWG — PC 사양 보조 출처. 1차 범위에서는 쓰지 않는다.

Steam에 사양이 없는 게임은 RAWG에도 대개 없고(RAWG 사양 데이터의 출처가 Steam),
게임명 검색이라 오매칭 처리가 필요하다. 사양 없는 게임은 unknown으로 둔다.
붙이게 되면 `requirements.minimum`이 Steam과 같은 자유 형식 텍스트라
steam_store.parse_requirements를 그대로 쓸 수 있다.

- 검색: `GET https://api.rawg.io/api/games?key=<키>&search=<게임명>`
- 모든 요청에 `key` 쿼리 파라미터가 필요하다 (없으면 401).
"""
