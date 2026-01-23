"""Rule-based table extraction as fallback"""

from typing import List, Optional, Dict
from datetime import date

from bs4 import BeautifulSoup, Tag
from loguru import logger

from kb_lockup.core.models import LockupEntry, TableCandidate
from kb_lockup.core.constants import COLUMN_KEYWORDS
from kb_lockup.extraction.normalizer import KoreanNormalizer


class RuleBasedExtractor:
    """
    Rule-based extraction for lockup tables when AI extraction is unavailable.

    Uses column header detection and pattern matching to extract data.
    """

    def __init__(self):
        self.normalizer = KoreanNormalizer()

    def extract_from_candidate(
        self,
        candidate: TableCandidate,
        listing_date: Optional[date] = None,
    ) -> List[LockupEntry]:
        """
        Extract lockup entries from a table candidate using rules

        Args:
            candidate: TableCandidate with raw HTML
            listing_date: Company listing date for relative date calculation

        Returns:
            List of LockupEntry objects
        """
        if not candidate.raw_html:
            return []

        soup = BeautifulSoup(candidate.raw_html, "lxml")
        table = soup.find("table")

        if not table:
            return []

        return self.extract_from_table(table, listing_date)

    def extract_from_table(
        self,
        table: Tag,
        listing_date: Optional[date] = None,
    ) -> List[LockupEntry]:
        """
        Extract lockup entries from a BeautifulSoup table

        Args:
            table: BeautifulSoup table element
            listing_date: Company listing date
        """
        rows = self._parse_table_rows(table)

        if len(rows) < 2:
            return []

        # Identify column mappings from headers
        headers = rows[0]
        column_map = self._identify_columns(headers)

        if column_map.get("owner") is None:
            logger.debug("No owner column found, skipping table")
            return []

        entries = []

        for row in rows[1:]:
            entry = self._extract_row(row, column_map, listing_date)
            if entry:
                entries.append(entry)

        logger.info(f"Rule-based extraction: {len(entries)} entries from {len(rows)-1} rows")
        return entries

    def _parse_table_rows(self, table: Tag) -> List[List[str]]:
        """Parse table into list of rows"""
        rows = []

        for tr in table.find_all("tr"):
            cells = []
            for cell in tr.find_all(["th", "td"]):
                colspan = int(cell.get("colspan", 1))
                text = cell.get_text(strip=True)
                text = " ".join(text.split())  # Normalize whitespace
                cells.append(text)

                # Handle colspan
                for _ in range(colspan - 1):
                    cells.append("")

            if cells and any(cells):  # Skip completely empty rows
                rows.append(cells)

        return rows

    def _identify_columns(self, headers: List[str]) -> Dict[str, int]:
        """
        Identify column indices for each data type

        Returns:
            Dict mapping column type to column index
        """
        column_map = {}

        for i, header in enumerate(headers):
            header_lower = header.lower()

            for col_type, keywords in COLUMN_KEYWORDS.items():
                if col_type in column_map:
                    continue  # Already found this type

                for keyword in keywords:
                    if keyword in header_lower:
                        column_map[col_type] = i
                        break

        logger.debug(f"Column mapping: {column_map}")
        return column_map

    def _extract_row(
        self,
        row: List[str],
        column_map: Dict[str, int],
        listing_date: Optional[date],
    ) -> Optional[LockupEntry]:
        """Extract a single entry from a row"""
        try:
            # Get owner (required)
            owner_idx = column_map.get("owner")
            if owner_idx is None or owner_idx >= len(row):
                return None

            owner = row[owner_idx].strip()
            if not owner or len(owner) < 2:
                return None

            # Skip aggregate rows
            skip_keywords = ["합계", "소계", "총계", "계", "합 계"]
            if any(kw in owner for kw in skip_keywords):
                return None

            # Get amount
            amount = None
            amount_idx = column_map.get("amount")
            if amount_idx is not None and amount_idx < len(row):
                amount = self.normalizer.normalize_amount(row[amount_idx])

            # Get ratio
            ratio = None
            ratio_idx = column_map.get("ratio")
            if ratio_idx is not None and ratio_idx < len(row):
                ratio = self.normalizer.normalize_ratio(row[ratio_idx])

            # Get release date
            release_date = None
            date_idx = column_map.get("release_date")
            if date_idx is not None and date_idx < len(row):
                release_date = self.normalizer.normalize_date(
                    row[date_idx],
                    listing_date=listing_date,
                )

            # Get period
            period_months = None
            period_idx = column_map.get("period")
            if period_idx is not None and period_idx < len(row):
                period_months = self.normalizer.normalize_period(row[period_idx])

            # Calculate release date from period if not directly available
            if not release_date and period_months and listing_date:
                from datetime import timedelta
                release_date = listing_date + timedelta(days=period_months * 30)

            # Must have at least owner and one other field
            if not any([amount, ratio, release_date, period_months]):
                return None

            return LockupEntry(
                owner=owner,
                amount=amount,
                ratio=ratio,
                release_date=release_date,
                period_months=period_months,
            )

        except Exception as e:
            logger.warning(f"Failed to extract row: {e}")
            return None

    def extract_from_html(
        self,
        html_content: str,
        listing_date: Optional[date] = None,
    ) -> List[LockupEntry]:
        """
        Extract from raw HTML content by finding all tables

        Args:
            html_content: HTML string
            listing_date: Company listing date
        """
        soup = BeautifulSoup(html_content, "lxml")
        all_entries = []

        for table in soup.find_all("table"):
            # Skip nested tables
            if table.find_parent("table"):
                continue

            entries = self.extract_from_table(table, listing_date)
            all_entries.extend(entries)

        return all_entries


class HybridExtractor:
    """
    Combines AI and rule-based extraction for best results

    Uses Qwen for primary extraction, falls back to rule-based
    for validation or when AI fails.
    """

    def __init__(self, qwen_api_key: Optional[str] = None):
        self.rule_extractor = RuleBasedExtractor()
        self.qwen_extractor = None

        if qwen_api_key:
            try:
                from kb_lockup.extraction.qwen_extractor import QwenTableExtractor
                self.qwen_extractor = QwenTableExtractor(qwen_api_key)
            except Exception as e:
                logger.warning(f"Qwen extractor not available: {e}")

    def extract(
        self,
        candidates: List[TableCandidate],
        context: Optional[str] = None,
        listing_date: Optional[date] = None,
    ) -> List[LockupEntry]:
        """
        Extract lockup entries using hybrid approach

        1. Try Qwen extraction first
        2. Fall back to rule-based if Qwen fails
        3. Cross-validate results when possible
        """
        qwen_entries = []
        rule_entries = []

        # Try Qwen extraction
        if self.qwen_extractor:
            try:
                qwen_entries = self.qwen_extractor.extract_tables(
                    candidates,
                    context=context,
                    listing_date=listing_date,
                )
                logger.info(f"Qwen extracted {len(qwen_entries)} entries")
            except Exception as e:
                logger.warning(f"Qwen extraction failed: {e}")

        # Always run rule-based as backup/validation
        for candidate in candidates:
            entries = self.rule_extractor.extract_from_candidate(
                candidate,
                listing_date=listing_date,
            )
            rule_entries.extend(entries)

        logger.info(f"Rule-based extracted {len(rule_entries)} entries")

        # Combine results
        if qwen_entries and rule_entries:
            return self._merge_results(qwen_entries, rule_entries)
        elif qwen_entries:
            return qwen_entries
        else:
            return rule_entries

    def _merge_results(
        self,
        qwen_entries: List[LockupEntry],
        rule_entries: List[LockupEntry],
    ) -> List[LockupEntry]:
        """
        Merge and deduplicate results from both extractors

        Prefers Qwen results but fills in missing data from rule-based
        """
        # Build lookup by owner name
        rule_lookup = {e.owner.lower(): e for e in rule_entries}

        merged = []
        seen_owners = set()

        for entry in qwen_entries:
            owner_key = entry.owner.lower()

            # Check if rule-based has additional data
            rule_entry = rule_lookup.get(owner_key)
            if rule_entry:
                # Fill in missing fields from rule-based
                if entry.amount is None and rule_entry.amount:
                    entry.amount = rule_entry.amount
                if entry.ratio is None and rule_entry.ratio:
                    entry.ratio = rule_entry.ratio
                if entry.release_date is None and rule_entry.release_date:
                    entry.release_date = rule_entry.release_date

            merged.append(entry)
            seen_owners.add(owner_key)

        # Add rule-based entries that weren't in Qwen results
        for entry in rule_entries:
            if entry.owner.lower() not in seen_owners:
                merged.append(entry)

        return merged
