"""CheapShark — 여러 PC 스토어의 최저가. 키가 필요 없다. 1차 범위에서는 쓰지 않는다.

Steam에 가격이 없는 경우(무료·미출시·구매 불가)는 모두 steam_store.py에서 이유를 확인할 수 있어
가격 폴백으로는 쓸 데가 없다. 세일 표시나 가격 상한 사전 검색이 필요해지면 검토한다.

- 검색: `GET https://www.cheapshark.com/api/1.0/games?title=<게임명>`
  - `cheapest`는 USD다. 원화 예산 비교는 steam_store.py의 원화 가격이 직접적이다.
    원화 변환 근거가 없으면 PriceQuote로 반환하지 않는다.
  - `steamAppID`가 함께 와서 Steam 조회로 이을 수 있다.
- 설명적인 User-Agent 헤더(예: "game-recommend-be/0.1")가 없으면 요청을 거부한다.
"""
