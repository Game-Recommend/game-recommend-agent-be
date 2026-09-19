"""엔드투엔드 실행 기록에서 문항별 질문 분해 결과를 뽑아 검색 평가의 입력으로 고정한다.

검색 평가는 LLM을 부르지 않는다. 파서가 실제로 낸 조건(예: genres=["Cooperative"],
platforms=["노트북"])을 그대로 입력으로 써야 검색이 그 값을 어떻게 다루는지 볼 수 있다.

    .venv/bin/python evals/search_pool/build_dataset.py \
        evals/agent_e2e/runs/<UTC timestamp> evals/relevance/runs/<UTC timestamp>

실행 기록을 여러 개 줄 수 있다. 엔드투엔드 문항은 대부분 분류가 없거나 하나라, 분류가 여럿이거나
파서가 분류를 지어내는 경우는 관련성 평가(evals/relevance)의 기록에서 가져온다.
"""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# 검색이 읽는 조건만 남긴다. 예산·사양·추천 개수는 검색 뒤의 단계가 쓴다
SEARCH_FIELDS = (
    "genres",
    "excluded_genres",
    "players",
    "connection",
    "play_mode",
    "max_playtime_hours",
    "max_session_minutes",
    "platforms",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run_dirs", type=Path, nargs="+")
    args = parser.parse_args()

    cases = []
    for run_dir in args.run_dirs:
        for line in (run_dir / "results.jsonl").read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if record.get("error"):
                raise SystemExit(f"{record['id']}가 오류로 끝난 기록이다. 오류 없는 실행을 쓴다.")
            conditions = {
                k: v for k, v in record["conditions"].items() if k in SEARCH_FIELDS and v
            }
            cases.append(
                {
                    "id": record["id"],
                    "family": record["family"],
                    "question": record["question"],
                    "conditions": conditions,
                }
            )
    if len({case["id"] for case in cases}) != len(cases):
        raise SystemExit("문항 id가 겹친다")
    payload = {"source_run": ", ".join(run_dir.name for run_dir in args.run_dirs), "cases": cases}
    (ROOT / "dataset.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"{len(cases)}문항 → {ROOT / 'dataset.json'}")


if __name__ == "__main__":
    main()
