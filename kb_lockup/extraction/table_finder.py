"""Identify lockup tables in documents"""

from typing import List, Optional

from loguru import logger

from kb_lockup.core.models import TableCandidate
from kb_lockup.core.constants import LOCKUP_KEYWORDS
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

        # First try to find tables in lockup-specific sections
        lockup_tables = self._find_tables_in_lockup_sections(parser)

        # Also get all tables as fallback
        all_tables = parser.find_tables()

        if not all_tables and not lockup_tables:
            logger.warning("No tables found in document")
            return []

        # Combine and deduplicate (lockup section tables get priority)
        seen_html = set()
        combined_tables = []

        for table in lockup_tables:
            html_hash = hash(table.raw_html[:500] if table.raw_html else "")
            if html_hash not in seen_html:
                seen_html.add(html_hash)
                # Boost score for tables found in lockup sections
                table.score = min(1.0, (table.score or 0) + 0.15)
                combined_tables.append(table)

        for table in all_tables:
            html_hash = hash(table.raw_html[:500] if table.raw_html else "")
            if html_hash not in seen_html:
                seen_html.add(html_hash)
                combined_tables.append(table)

        # Score each table
        scored_tables = []
        for table in combined_tables:
            if table.score is None or table.score == 0:
                table.score = self.scorer.score_table(table)

            if table.score >= self.min_score:
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

    def _find_tables_in_lockup_sections(
        self,
        parser: DartParser,
    ) -> List[TableCandidate]:
        """Find tables within sections that mention lockup"""
        lockup_tables = []

        # Find lockup sections
        sections = parser.find_lockup_sections()

        for keyword, section in sections:
            tables = parser.get_tables_in_section(section)

            for table in tables:
                # Skip nested tables
                if table.find_parent("table"):
                    continue

                # Analyze the table
                structure = parser.analyze_table_structure(table)
                context = parser._get_table_context(table)

                candidate = TableCandidate(
                    section_title=keyword,
                    context_text=context[:500] if context else None,
                    raw_html=str(table),
                    lockup_signal=True,
                    strong_lockup=any(
                        kw in keyword for kw in LOCKUP_KEYWORDS["primary"]
                    ),
                    column_headers=structure["headers"],
                    row_count=max(0, structure["row_count"] - 1),
                )

                lockup_tables.append(candidate)

        return lockup_tables

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

    def find_tables_by_headers(
        self,
        document_content: str,
        required_headers: List[str],
    ) -> List[TableCandidate]:
        """
        Find tables that contain specific column headers

        Args:
            document_content: XML/HTML document content
            required_headers: List of required header keywords

        Returns:
            List of matching TableCandidate objects
        """
        parser = DartParser(document_content)
        all_tables = parser.find_tables()

        matches = []
        for table in all_tables:
            headers_text = " ".join(table.column_headers).lower()
            if all(h.lower() in headers_text for h in required_headers):
                table.score = self.scorer.score_table(table)
                matches.append(table)

        return sorted(matches, key=lambda t: t.score, reverse=True)
