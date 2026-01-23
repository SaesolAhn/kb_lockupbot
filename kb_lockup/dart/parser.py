"""DART document parsing utilities"""

from typing import List, Optional, Tuple
import re

from bs4 import BeautifulSoup
from loguru import logger

from kb_lockup.core.models import TableCandidate
from kb_lockup.core.constants import SECTION_KEYWORDS, LOCKUP_KEYWORDS


class DartParser:
    """Parse DART XML/HTML documents to extract table candidates"""

    def __init__(self, content: str):
        """
        Initialize parser with document content

        Args:
            content: XML or HTML document content
        """
        self.soup = BeautifulSoup(content, "lxml")
        self.content = content

    def find_sections(self) -> List[Tuple[str, str]]:
        """
        Find document sections that may contain lockup tables

        Returns:
            List of (section_title, section_content) tuples
        """
        sections = []

        # Look for section headers
        for keyword in SECTION_KEYWORDS:
            # Find elements containing the keyword
            elements = self.soup.find_all(
                string=lambda text: text and keyword in text
            )

            for elem in elements:
                # Get parent section
                parent = elem.find_parent(["div", "section", "table", "p"])
                if parent:
                    # Get surrounding content
                    section_content = self._get_section_content(parent)
                    sections.append((keyword, section_content))

        return sections

    def _get_section_content(self, element) -> str:
        """Extract content from section element and its siblings"""
        content_parts = [str(element)]

        # Get following siblings until next section header
        for sibling in element.find_next_siblings():
            # Check if this is a new section
            text = sibling.get_text() if sibling.name else str(sibling)
            if any(kw in text for kw in SECTION_KEYWORDS):
                break
            content_parts.append(str(sibling))

            # Limit content size
            if len("".join(content_parts)) > 50000:
                break

        return "".join(content_parts)

    def find_tables(self) -> List[TableCandidate]:
        """
        Find all tables in document and create candidates

        Returns:
            List of TableCandidate objects
        """
        candidates = []
        tables = self.soup.find_all("table")

        for i, table in enumerate(tables):
            candidate = self._analyze_table(table, i)
            if candidate:
                candidates.append(candidate)

        logger.info(f"Found {len(candidates)} table candidates")
        return candidates

    def _analyze_table(self, table, index: int) -> Optional[TableCandidate]:
        """Analyze a single table element"""
        # Get table context (surrounding text)
        context = self._get_table_context(table)

        # Get column headers
        headers = []
        header_row = table.find("tr")
        if header_row:
            for cell in header_row.find_all(["th", "td"]):
                text = cell.get_text(strip=True)
                if text:
                    headers.append(text)

        # Count data rows
        rows = table.find_all("tr")
        row_count = max(0, len(rows) - 1)  # Exclude header row

        # Check for lockup signals
        table_text = table.get_text()
        lockup_signal = any(
            kw in table_text
            for kw in LOCKUP_KEYWORDS["primary"] + LOCKUP_KEYWORDS["secondary"]
        )
        strong_lockup = any(kw in table_text for kw in LOCKUP_KEYWORDS["primary"])

        # Get section title from context
        section_title = self._extract_section_title(context)

        return TableCandidate(
            section_title=section_title or f"Table {index + 1}",
            context_text=context[:500] if context else None,
            raw_html=str(table),
            lockup_signal=lockup_signal,
            strong_lockup=strong_lockup,
            column_headers=headers,
            row_count=row_count,
        )

    def _get_table_context(self, table, chars: int = 500) -> str:
        """Get text surrounding a table for context"""
        context_parts = []

        # Previous siblings
        prev = table.find_previous_sibling()
        if prev:
            text = prev.get_text(strip=True)
            context_parts.append(text[-chars:])

        # Following siblings
        next_elem = table.find_next_sibling()
        if next_elem:
            text = next_elem.get_text(strip=True)
            context_parts.append(text[:chars])

        return " ".join(context_parts)

    def _extract_section_title(self, context: str) -> Optional[str]:
        """Extract section title from context text"""
        for keyword in SECTION_KEYWORDS:
            if keyword in context:
                return keyword

        # Try to find a title pattern
        patterns = [
            r"([가-힣\s]+현황)",
            r"([가-힣\s]+내역)",
            r"(\d+\.\s*[가-힣]+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, context)
            if match:
                return match.group(1).strip()

        return None

    def extract_text(self) -> str:
        """Extract all text from document"""
        return self.soup.get_text(separator="\n", strip=True)
