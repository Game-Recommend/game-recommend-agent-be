"""IGDB — 장르·인원 수·플레이타임·플랫폼 조건으로 후보 게임을 찾는다.

- 인증: Twitch 개발자 앱의 client credentials로 앱 토큰을 받는다
  (`POST https://id.twitch.tv/oauth2/token`).
  요청마다 `Client-ID`와 `Authorization: Bearer <토큰>` 헤더를 싣는다.
- 요청: `POST https://api.igdb.com/v4/<endpoint>`, 본문은 Apicalypse 쿼리
  (예: `fields name, genres; where ...; limit 10;`).
- 초당 4요청 제한이 있다.
- 플레이타임은 `game_time_to_beats`, 온라인 협동 최대 인원은
  `multiplayer_modes.onlinecoopmax`에 있다.
"""
