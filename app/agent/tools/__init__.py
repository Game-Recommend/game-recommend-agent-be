"""에이전트에 노출하는 Tool 목록. 파일 하나가 도메인 하나이고, 담당자는 TEAM.md를 따른다."""

from langchain_core.tools import BaseTool

from app.agent.tools.hardware import assess_hardware
from app.agent.tools.price import get_prices
from app.agent.tools.review_score import get_review_scores
from app.agent.tools.reviews import summarize_reviews
from app.agent.tools.search import search_games


def build_tools() -> list[BaseTool]:
    return [search_games, get_prices, assess_hardware, summarize_reviews, get_review_scores]
