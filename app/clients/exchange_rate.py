"""가격·하드웨어 담당: USD → KRW 환율. CheapShark의 USD 가격을 원화 정수로 바꿀 때 쓴다.

- Frankfurter(ECB 고시 환율, 키 불필요): `GET https://api.frankfurter.dev/v1/latest?from=USD&to=KRW`
  - 응답: `{"amount": 1.0, "base": "USD", "date": "2026-09-11", "rates": {"KRW": 1342.79}}`
  - 평일 하루 한 번 갱신되므로 프로세스 안에서 한 시간 캐시해도 충분하다.
  - 예전 도메인 `api.frankfurter.app`는 301로 넘어가므로 새 도메인을 직접 쓴다.
- 환율을 받지 못하면 예외를 던진다. 호출자는 원화 변환 근거가 없는 가격을 PriceQuote로 내지 않는다.
"""

import asyncio
import time

import httpx2

FRANKFURTER_URL = "https://api.frankfurter.dev/v1/latest"


class ExchangeRateClient:
    def __init__(self, http: httpx2.AsyncClient, *, cache_ttl_seconds: float = 3600):
        self.http = http
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cached: tuple[float, float] | None = None  # (조회 시각, 환율)
        self._lock = asyncio.Lock()

    async def usd_to_krw(self) -> float:
        """1 USD당 원화. 실패 시 예외."""
        async with self._lock:
            if self._cached and time.monotonic() - self._cached[0] < self.cache_ttl_seconds:
                return self._cached[1]
            response = await self.http.get(FRANKFURTER_URL, params={"from": "USD", "to": "KRW"})
            response.raise_for_status()
            rate = (response.json().get("rates") or {}).get("KRW")
            if not isinstance(rate, int | float) or rate <= 0:
                raise ValueError("환율 응답에 KRW가 없습니다")
            self._cached = (time.monotonic(), float(rate))
            return float(rate)

    async def convert_usd(self, amount_usd: float) -> int:
        """USD 금액을 원화 정수(반올림)로 변환한다."""
        return round(amount_usd * await self.usd_to_krw())
