"""Rank and score table candidates for lockup relevance"""

from typing import List

from kb_lockup.core.models import TableCandidate
from kb_lockup.core.constants import (
    LOCKUP_KEYWORDS,
    COLUMN_KEYWORDS,
    SECTION_KEYWORDS,
    SCORING_WEIGHTS,
)


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

        # Normalize to 0-1 range
        max_possible = sum(SCORING_WEIGHTS.values())
        normalized_score = min(score / max_possible, 1.0)

        return round(normalized_score, 3)

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
        required = {"owner"}
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
