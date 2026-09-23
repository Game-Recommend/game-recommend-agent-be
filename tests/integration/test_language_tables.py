"""출력 언어별 문구 표.

한 언어에만 키를 더하면 그 언어의 요청만 KeyError로 실패하므로 여기서 막는다.
"""

from typing import get_args

import pytest

from app.agent.context import MESSAGES, STAGE_NAMES
from app.agent.prompts import ANSWER_LANGUAGES
from app.agent.runner import WARNINGS
from app.agent.tools import hardware, price, review_score, reviews, search
from app.clients.hardware_assessor import REASONS as ASSESSOR_REASONS
from app.clients.hardware_judge import MINIMUM_LABELS, NOTE_LANGUAGES, STATUS_LABELS
from app.clients.steam_reviews import NO_REVIEWS, SUMMARY_LANGUAGES
from app.clients.steam_store import UNAVAILABLE_REASONS
from app.schemas.common import Language
from app.tools.hardware import REASONS as HARDWARE_REASONS
from app.tools.price import REASONS as PRICE_REASONS

LANGUAGES = set(get_args(Language))

# 언어 → {키: 문장}
MESSAGE_TABLES = {
    "context.MESSAGES": MESSAGES,
    "runner.WARNINGS": WARNINGS,
    "tools.price.REASONS": PRICE_REASONS,
    "tools.hardware.REASONS": HARDWARE_REASONS,
    "steam_store.UNAVAILABLE_REASONS": UNAVAILABLE_REASONS,
    "hardware_assessor.REASONS": ASSESSOR_REASONS,
    "hardware_judge.STATUS_LABELS": STATUS_LABELS,
}
# 언어 → 낱말 하나
WORD_TABLES = {
    "prompts.ANSWER_LANGUAGES": ANSWER_LANGUAGES,
    "hardware_judge.NOTE_LANGUAGES": NOTE_LANGUAGES,
    "hardware_judge.MINIMUM_LABELS": MINIMUM_LABELS,
    "steam_reviews.SUMMARY_LANGUAGES": SUMMARY_LANGUAGES,
    "steam_reviews.NO_REVIEWS": NO_REVIEWS,
}


@pytest.mark.parametrize("name", MESSAGE_TABLES)
def test_every_language_has_the_same_messages(name):
    table = MESSAGE_TABLES[name]
    assert set(table) == LANGUAGES
    assert all(set(messages) == set(table["ko"]) for messages in table.values())


@pytest.mark.parametrize("name", WORD_TABLES)
def test_every_language_has_a_word(name):
    assert set(WORD_TABLES[name]) == LANGUAGES


def test_english_failure_warnings_name_every_stage():
    # 한국어 경고는 단계 이름을 그대로 쓰고, 영어 경고는 이 표로 옮긴다
    tools = (search, price, hardware, review_score, reviews)
    assert {tool.STAGE for tool in tools} | {"미디어"} <= set(STAGE_NAMES["en"])
