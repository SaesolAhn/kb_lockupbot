"""Identify lockup tables in documents"""

from typing import List, Optional

from loguru import logger

from kb_lockup.core.models import TableCandidate
from kb_lockup.dart.parser import DartParser
from kb_lockup.extraction.scorer import TableScorer


class TableFinder:
    """Find and rank candidate lockup tables in documents"""

    def __init__(self, min_score: float = 0.3):
        """
        Initialize table finder

        Args:
            min_score: Minimum score threshold for table candidates
        """
        self.min_score = min_score
        self.scorer = TableScorer()

    def find_lockup_tables(
        self,
        document_content: str,
        max_candidates: int = 5,
    ) -> List[TableCandidate]:
        """
        Find tables likely to contain lockup information

        Args:
            document_content: XML/HTML document content
            max_candidates: Maximum number of candidates to return

        Returns:
            List of scored TableCandidate objects, sorted by score
        """
        parser = DartParser(document_content)
        all_tables = parser.find_tables()

        if not all_tables:
            logger.warning("No tables found in document")
            return []

        # Score each table
        scored_tables = []
        for table in all_tables:
            score = self.scorer.score_table(table)
            table.score = score

            if score >= self.min_score:
                scored_tables.append(table)

        # Sort by score descending
        scored_tables.sort(key=lambda t: t.score, reverse=True)

        # Limit candidates
        candidates = scored_tables[:max_candidates]

        logger.info(
            f"Found {len(candidates)} lockup table candidates "
            f"(from {len(all_tables)} total tables)"
        )

        return candidates

    def find_best_table(
        self,
        document_content: str,
    ) -> Optional[TableCandidate]:
        """
        Find the single best lockup table candidate

        Args:
            document_content: XML/HTML document content

        Returns:
            Best TableCandidate or None if no suitable table found
        """
        candidates = self.find_lockup_tables(document_content, max_candidates=1)
        return candidates[0] if candidates else None

    def filter_strong_lockup_tables(
        self,
        candidates: List[TableCandidate],
    ) -> List[TableCandidate]:
        """
        Filter to only tables with strong lockup signals

        Args:
            candidates: List of table candidates

        Returns:
            Filtered list with only strong lockup tables
        """
        return [c for c in candidates if c.strong_lockup]
