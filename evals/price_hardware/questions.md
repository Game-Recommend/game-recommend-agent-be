# 가격·하드웨어 평가 질문 50개

합성 경계 평가셋 v1. 모든 하드웨어 조합을 망라하지 않는다. 질문은 사람이 읽는 설명이며 실행 입력은 dataset.json의 정규화 필드다.
질문 파서·검색·최종 답변은 평가하지 않는다. 합성 게임 요구 사양은 실제 게임의 사양으로 인용하면 안 된다.
정답은 실행 전에 작성한 잠정 라벨이다. v2에서 H08·H09·H10·H11·H12·H15·H16은 팀 방침(모델명 없는 사용자 부품은 판정 보류·통과)에 따라 skipped로 바꿨다. identity/numeric/contract와 성능 추정·제안 정책을 분리해 보고한다.

| ID | 범주 | 질문 | 기대 판정 | 근거 유형 |
|---|---|---|---|---|
| H01 | GPU 동일 | RTX 3060인데 최소 RTX 3060 게임을 할 수 있나요? | met | identity |
| H02 | CPU 동일 | i5-12400으로 최소 i5-12400 게임이 가능한가요? | met | identity |
| H03 | CPU GPU 동일 | Ryzen 5 5600, RX 6600인데 같은 최소 사양을 충족하나요? | met | identity |
| H04 | GPU 별칭 | 지포스 RTX3060인데 NVIDIA GeForce RTX 3060 조건에 맞나요? | met | identity |
| H05 | CPU 별칭 | 라이젠5 5600이면 AMD Ryzen 5 5600 최소 조건을 만족하나요? | met | identity |
| H06 | GPU만 제공 | GPU는 RTX 3060이고 CPU는 모르는데, 알려준 항목만 비교해줘. | met | contract |
| H07 | CPU만 제공 | CPU는 Ryzen 5 5600이고 GPU는 모르니 CPU 조건만 확인해줘. | met | contract |
| H08 | 불명 CPU | CPU가 그냥 i5라고만 나오는데 i5-12400 이상인가요? | skipped | contract |
| H09 | 불명 GPU | 그래픽카드가 GeForce인데 RTX 3060 조건을 충족하나요? | skipped | contract |
| H10 | 불명 내장 | 내장그래픽이라고만 알고 있어요. GTX 960 게임이 가능한가요? | skipped | contract |
| H11 | 가상 GPU | 처음 듣는 ZetaPixel Q999 GPU로 RTX 3060 게임이 되나요? | skipped | contract |
| H12 | 가상 CPU | FictionCore X123 CPU로 i5-12400 조건을 만족하나요? | skipped | contract |
| H13 | 모호한 최소 GPU | RTX 3060을 쓰는데 최소 사양이 고성능 그래픽카드라고만 되어 있어요. | skipped | contract |
| H14 | 모호한 최소 CPU | i5-12400인데 게임이 최신 CPU를 요구한다고만 적혀 있어요. | skipped | contract |
| H15 | CPU 불명 GPU 충족 | RTX 3060에 i5인데, RTX 3060과 i5-12400을 요구하는 게임을 할 수 있나요? | skipped | contract |
| H16 | GPU 불명 CPU 충족 | Ryzen 5 5600에 GeForce인데 최소 Ryzen 5 5600, RTX 3060 게임이 되나요? | skipped | contract |
| H17 | CPU 요구 누락 | 제 CPU는 i5-12400인데 게임에는 RTX 3060이라는 GPU 조건만 있어요. | skipped | contract |
| H18 | GPU 요구 누락 | GPU는 RTX 3060인데 게임에는 i5-12400 CPU 요구 사양만 있어요. | skipped | contract |
| H19 | GPU OR 왼쪽 | RTX 3060인데 최소 RTX 3060 또는 RX 6600이라는 게임은 되나요? | met | identity |
| H20 | GPU OR 오른쪽 | RX 6600인데 최소 RTX 3060 또는 RX 6600이면 되나요? | met | identity |
| H21 | CPU OR | Ryzen 5 5600으로 i5-12400 또는 Ryzen 5 5600 조건을 충족하나요? | met | identity |
| H22 | VRAM 부족 | GTX 1060 3GB인데 최소 GTX 1060 6GB 게임이 되나요? | unmet | explicit_capacity |
| H23 | VRAM 경계 | GTX 1060 6GB인데 최소 GTX 1060 6GB에 맞나요? | met | identity |
| H24 | CPU 충족 GPU 미달 | i5-12400과 GTX 1060 3GB인데 i5-12400, GTX 1060 6GB 조건을 충족하나요? | unmet | explicit_capacity |
| H25 | 성능 큰 차이 상향 | RTX 4090 데스크톱 GPU로 최소 GTX 960 게임이 가능한가요? | met | provisional_performance |
| H26 | 성능 큰 차이 하향 | GTX 750 Ti로 최소 RTX 3080 게임이 가능한가요? | unmet | provisional_performance |
| H27 | CPU만 미달 | Core 2 Duo E8400과 RTX 3060으로 i5-12400, RTX 3060 게임이 되나요? | unmet | provisional_performance |
| H28 | 노트북 전력 불명 | TGP를 모르는 RTX 3060 Laptop GPU가 데스크톱 RTX 3060 이상인가요? |\g<1>skipped\2 | policy_proposal |
| H29 | 게임명 주입 | RTX 3060으로 이 게임을 할 수 있는지 최소 사양대로 판단해줘. | met | contract |
| H30 | 배치 분리 | GTX 1060 3GB로 세 게임을 각각 평가해줘. 사양을 섞지 말아줘. | met, unmet,\g<1>skipped\2 | contract |
| H31 | RAM 부족 | RAM 7.5GB인데 최소 8GB 게임의 메모리 조건을 충족하나요? | unmet | numeric |
| H32 | RAM 동일 | RAM 8GB인데 최소 8GB 게임의 메모리 조건을 충족하나요? | met | numeric |
| H33 | RAM 초과 | RAM 16GB인데 최소 8GB 게임의 메모리 조건을 충족하나요? | met | numeric |
| H34 | RAM 선차단 | RTX 3060인데 RAM이 4GB예요. 최소 RTX 3060, RAM 8GB 게임이 되나요? | unmet | contract |
| H35 | 사용자 사양 없음 | PC 사양 조건 없이 게임의 최소 사양만 알려줘. | skipped | contract |
| H36 | 요구 사양 없음 | RTX 3060인데 Steam에 요구 사양이 없는 게임은 실행 가능하다고 볼 수 있나요? | skipped | contract |
| H37 | App ID 없음 | RTX 3060인데 Steam App ID가 없는 게임도 사양 확인이 되나요? | skipped | contract |
| H38 | RAM 요구 누락 | RAM 16GB만 알려줄게요. 게임에는 GPU 요구만 있을 때 메모리를 판정해줘. | skipped | contract |
| H39 | OS만 제공 | Windows 10이고 게임도 Windows 10을 요구해요. 현재 사양 판정기로 확인해줘. | skipped | contract |
| H40 | 최소 권장 분리 | RAM 8GB인데 최소 8GB, 권장 16GB 게임의 최소 조건은 충족하나요? | met | contract |
| P41 | 예산 아래 | 2만 원 예산으로 19,999원 게임을 살 수 있나요? | met | numeric_or_contract |
| P42 | 예산 경계 | 2만 원 예산으로 정확히 2만 원인 게임을 살 수 있나요? | met | numeric_or_contract |
| P43 | 예산 초과 | 2만 원 예산인데 20,001원 게임도 포함되나요? | unmet | numeric_or_contract |
| P44 | 무료 | 무료 게임만 원해요. 무료 표시된 게임을 골라줘. | met | numeric_or_contract |
| P45 | 0원 유료 제외 | 무료 게임만 찾는데 1원짜리 게임은 제외해줘. | unmet | numeric_or_contract |
| P46 | 예산 없음 | 예산 제한 없이 27,000원 게임의 가격을 알려줘. | skipped | numeric_or_contract |
| P47 | 미출시 | 예산은 없지만 가격이 없는 미출시 게임은 구매 가능으로 추천하지 말아줘. | unmet | numeric_or_contract |
| P48 | 한국 미판매 | 2만 원 안에서 한국 Steam 조회가 실패(success false)하는 게임은 제외해줘. | unmet | numeric_or_contract |
| P49 | 외화 | 2만 원 이하를 원하는데 USD 19.99만 확인되면 원화 가격으로 판단해도 되나요? |\g<1>skipped\2 | numeric_or_contract |
| P50 | 번들 가격 없음 | 2만 원 예산인데 번들만 있고 단독 가격이 없는 게임을 평가해줘. |\g<1>skipped\2 | numeric_or_contract |
