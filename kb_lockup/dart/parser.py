"""DART document parsing utilities"""

from typing import List, Optional, Tuple, Dict, Any
import re

from bs4 import BeautifulSoup, Tag
from loguru import logger

from kb_lockup.core.models import TableCandidate
from kb_lockup.core.constants import SECTION_KEYWORDS, LOCKUP_KEYWORDS, COLUMN_KEYWORDS


class DartParser:
    """Parse DART XML/HTML documents to extract table candidates"""

    def __init__(self, content: str):
        """
        Initialize parser with document content

        Args:
            content: XML or HTML document content
        """
        # Clean up common DART document issues
        content = self._preprocess_content(content)
        self.soup = BeautifulSoup(content, "lxml")
        self.content = content
        self._table_cache: Dict[int, TableCandidate] = {}

    def _preprocess_content(self, content: str) -> str:
        """Clean up DART document content"""
        # Remove XML declarations that may cause parsing issues
        content = re.sub(r'<\?xml[^>]*\?>', '', content)

        # Fix common encoding issues
        content = content.replace('\xa0', ' ')  # Non-breaking space

        # Remove CDATA sections
        content = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', content, flags=re.DOTALL)

        return content

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

    def parse_table_to_rows(self, table: Tag) -> List[List[str]]:
        """
        Parse HTML table into list of rows

        Args:
            table: BeautifulSoup table element

        Returns:
            List of rows, each row is a list of cell values
        """
        rows = []

        for tr in table.find_all("tr"):
            cells = []
            for cell in tr.find_all(["th", "td"]):
                # Handle colspan
                colspan = int(cell.get("colspan", 1))
                text = cell.get_text(strip=True)
                text = self._clean_cell_text(text)
                cells.append(text)

                # Add empty cells for colspan
                for _ in range(colspan - 1):
                    cells.append("")

            if cells:  # Skip empty rows
                rows.append(cells)

        return rows

    def _clean_cell_text(self, text: str) -> str:
        """Clean text extracted from table cell"""
        # Remove extra whitespace
        text = " ".join(text.split())

        # Remove common artifacts
        text = text.replace("\n", " ")
        text = text.replace("\t", " ")

        return text.strip()

    def table_to_dict(self, table: Tag) -> List[Dict[str, str]]:
        """
        Convert HTML table to list of dictionaries

        Args:
            table: BeautifulSoup table element

        Returns:
            List of dicts with column headers as keys
        """
        rows = self.parse_table_to_rows(table)

        if len(rows) < 2:
            return []

        # First row as headers
        headers = rows[0]
        data = []

        for row in rows[1:]:
            if len(row) >= len(headers):
                row_dict = {}
                for i, header in enumerate(headers):
                    if header:  # Skip empty headers
                        row_dict[header] = row[i] if i < len(row) else ""
                if row_dict:
                    data.append(row_dict)

        return data

    def find_lockup_sections(self) -> List[Tuple[str, Tag]]:
        """
        Find sections specifically about lockup/보호예수

        Returns:
            List of (section_title, section_element) tuples
        """
        sections = []

        # Search for lockup keywords in text nodes
        all_keywords = LOCKUP_KEYWORDS["primary"] + LOCKUP_KEYWORDS["secondary"]

        for keyword in all_keywords:
            # Find all text containing the keyword
            matches = self.soup.find_all(
                string=lambda text: text and keyword in text
            )

            for match in matches:
                # Get the parent element that contains this text
                parent = match.find_parent(["div", "section", "p", "td", "th", "span"])
                if parent:
                    # Find enclosing section
                    section = self._find_enclosing_section(parent)
                    if section and (keyword, section) not in sections:
                        sections.append((keyword, section))

        return sections

    def _find_enclosing_section(self, element: Tag) -> Optional[Tag]:
        """Find the enclosing section/div for an element"""
        # Walk up the tree to find a suitable container
        for parent in element.parents:
            if parent.name in ["div", "section", "article"]:
                return parent
            if parent.name == "body":
                break
        return element.parent

    def get_tables_in_section(self, section: Tag) -> List[Tag]:
        """Get all tables within a section"""
        return section.find_all("table", recursive=True)

    def analyze_table_structure(self, table: Tag) -> Dict[str, Any]:
        """
        Analyze table structure to understand its layout

        Returns:
            Dict with structure info: headers, row_count, col_count, merged_cells, etc.
        """
        rows = table.find_all("tr")

        structure = {
            "row_count": len(rows),
            "col_count": 0,
            "has_header": False,
            "headers": [],
            "merged_cells": False,
            "nested_tables": False,
        }

        if not rows:
            return structure

        # Check first row for headers
        first_row = rows[0]
        header_cells = first_row.find_all("th")

        if header_cells:
            structure["has_header"] = True
            structure["headers"] = [c.get_text(strip=True) for c in header_cells]
        else:
            # First row might still be headers even if using <td>
            first_cells = first_row.find_all("td")
            structure["headers"] = [c.get_text(strip=True) for c in first_cells]

        # Calculate column count (accounting for colspan)
        max_cols = 0
        for row in rows:
            cols = 0
            for cell in row.find_all(["th", "td"]):
                cols += int(cell.get("colspan", 1))
            max_cols = max(max_cols, cols)

        structure["col_count"] = max_cols

        # Check for merged cells
        for row in rows:
            for cell in row.find_all(["th", "td"]):
                if cell.get("colspan") or cell.get("rowspan"):
                    structure["merged_cells"] = True
                    break

        # Check for nested tables
        if table.find("table"):
            structure["nested_tables"] = True

        return structure

    def identify_column_types(self, headers: List[str]) -> Dict[str, str]:
        """
        Identify what type of data each column contains

        Returns:
            Dict mapping header to column type (owner, amount, ratio, release_date, period)
        """
        column_types = {}

        for header in headers:
            header_lower = header.lower()

            for col_type, keywords in COLUMN_KEYWORDS.items():
                for keyword in keywords:
                    if keyword in header_lower:
                        column_types[header] = col_type
                        break

        return column_types

    def extract_tables_with_context(self) -> List[Dict[str, Any]]:
        """
        Extract all tables with their surrounding context

        Returns:
            List of dicts with table, context, section_title, etc.
        """
        results = []

        for i, table in enumerate(self.soup.find_all("table")):
            # Skip nested tables (already processed as part of parent)
            if table.find_parent("table"):
                continue

            context = self._get_table_context(table, chars=1000)
            section_title = self._extract_section_title(context)
            structure = self.analyze_table_structure(table)

            results.append({
                "index": i,
                "table": table,
                "raw_html": str(table),
                "context": context,
                "section_title": section_title,
                "structure": structure,
                "column_types": self.identify_column_types(structure["headers"]),
            })

        return results
