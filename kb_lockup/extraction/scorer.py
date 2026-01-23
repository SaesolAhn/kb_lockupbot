"""Rank and score table candidates for lockup relevance"""

from typing import List

from kb_lockup.core.models import TableCandidate
from kb_lockup.core.constants import (
    LOCKUP_KEYWORDS,
    COLUMN_KEYWORDS,
    SECTION_KEYWORDS,
    SCORING_WEIGHTS,
)


# Keywords that indicate a table is NOT a lockup table
NEGATIVE_KEYWORDS = [
    "재무제표",
    "손익계산서",
    "재무상태표",
    "현금흐름표",
    "자본변동표",
    "주석",
    "감사보고서",
    "연결",
    "당기순이익",
    "매출액",
    "영업이익",
    "자산총계",
    "부채총계",
    "자본총계",
    "이익잉여금",
    "주당순이익",
    "배당금",
    "요약재무정보",
    "주요재무",
    "법인세",
]

# Column headers that indicate non-lockup tables
NEGATIVE_HEADERS = [
    "매출",
    "영업이익",
    "당기순이익",
    "자산",
    "부채",
    "자본",
    "이익",
    "비용",
    "손실",
    "세전",
    "세후",
    "전기",
    "당기",
]


class TableScorer:
    """Score and rank table candidates for lockup relevance"""

    def score_table(self, candidate: TableCandidate) -> float:
        """
        Calculate relevance score for a table candidate

        Args:
            candidate: TableCandidate to score

        Returns:
            Score between 0 and 1
        """
        score = 0.0

        # Check table content and context for keywords
        search_text = " ".join([
            candidate.section_title or "",
            candidate.context_text or "",
            candidate.raw_html or "",
        ]).lower()

        # Check for negative signals first (non-lockup tables)
        negative_penalty = self._calculate_negative_score(candidate, search_text)
        if negative_penalty >= 0.5:
            # Highly likely to be non-lockup table
            return 0.0

        # Strong lockup keywords
        for keyword in LOCKUP_KEYWORDS["primary"]:
            if keyword.lower() in search_text:
                score += SCORING_WEIGHTS["strong_keyword"]
                candidate.strong_lockup = True
                break

        # Secondary keywords
        for keyword in LOCKUP_KEYWORDS["secondary"]:
            if keyword.lower() in search_text:
                score += SCORING_WEIGHTS["secondary_keyword"]
                candidate.lockup_signal = True
                break

        # Section match
        for section in SECTION_KEYWORDS:
            if section in (candidate.section_title or ""):
                score += SCORING_WEIGHTS["section_match"]
                break

        # Column header matches
        column_score = self._score_columns(candidate.column_headers)
        score += column_score

        # Row count bonus (more rows = likely data table)
        row_bonus = min(
            candidate.row_count * 0.02,
            SCORING_WEIGHTS["row_count_bonus"],
        )
        score += row_bonus

        # Apply negative penalty
        score = max(0, score - negative_penalty)

        # Normalize to 0-1 range
        max_possible = sum(SCORING_WEIGHTS.values())
        normalized_score = min(score / max_possible, 1.0)

        return round(normalized_score, 3)

    def _calculate_negative_score(
        self,
        candidate: TableCandidate,
        search_text: str,
    ) -> float:
        """Calculate penalty for non-lockup signals"""
        penalty = 0.0

        # Check negative keywords in content
        for keyword in NEGATIVE_KEYWORDS:
            if keyword in search_text:
                penalty += 0.15
                if penalty >= 0.5:
                    return penalty

        # Check negative headers
        headers_text = " ".join(candidate.column_headers).lower()
        for header in NEGATIVE_HEADERS:
            if header in headers_text:
                penalty += 0.2
                if penalty >= 0.5:
                    return penalty

        # Tables with too few columns are likely not lockup tables
        if len(candidate.column_headers) < 3:
            penalty += 0.1

        # Tables with too few rows are likely not lockup tables
        if candidate.row_count < 2:
            penalty += 0.1

        return penalty

    def _score_columns(self, headers: List[str]) -> float:
        """Score based on column header matches"""
        if not headers:
            return 0.0

        score = 0.0
        headers_lower = [h.lower() for h in headers]
        headers_text = " ".join(headers_lower)

        matched_categories = set()

        for category, keywords in COLUMN_KEYWORDS.items():
            for keyword in keywords:
                if keyword in headers_text:
                    matched_categories.add(category)
                    break

        # More matched column types = higher score
        score = len(matched_categories) * SCORING_WEIGHTS["column_match"]

        return min(score, SCORING_WEIGHTS["column_match"] * 3)  # Cap at 3 matches

    def is_strong_lockup(self, candidate: TableCandidate) -> bool:
        """Check if table is definitely a lockup schedule"""
        if candidate.strong_lockup:
            return True

        # Check if it has lockup signals and relevant columns
        if not candidate.lockup_signal:
            return False

        # Must have at least owner and one of: amount, ratio, release_date
        optional = {"amount", "ratio", "release_date"}

        headers_text = " ".join(candidate.column_headers).lower()

        has_required = any(
            kw in headers_text
            for kw in COLUMN_KEYWORDS["owner"]
        )

        has_optional = any(
            any(kw in headers_text for kw in COLUMN_KEYWORDS[col])
            for col in optional
        )

        return has_required and has_optional

    def rank_candidates(
        self,
        candidates: List[TableCandidate],
    ) -> List[TableCandidate]:
        """
        Rank candidates by score

        Args:
            candidates: List of table candidates

        Returns:
            Sorted list with highest scores first
        """
        for candidate in candidates:
            if candidate.score == 0:
                candidate.score = self.score_table(candidate)

        return sorted(candidates, key=lambda c: c.score, reverse=True)
