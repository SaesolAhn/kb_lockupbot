"""Rule-based table extraction as fallback"""

from typing import List, Optional, Dict, Any, Tuple
from datetime import date, timedelta
import re

from bs4 import BeautifulSoup, Tag
from loguru import logger

from kb_lockup.core.models import LockupEntry, TableCandidate
from kb_lockup.core.constants import COLUMN_KEYWORDS
from kb_lockup.extraction.normalizer import KoreanNormalizer


class RuleBasedExtractor:
    """
    Rule-based extraction for lockup tables.
    
    Implements:
    1. Dynamic Header Mapping (Anchor System)
    2. Stateful Context Propagation (handling merged cells)
    3. Smart Indexing for Partial Rows
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
        """
        rows = self._parse_table_rows(table)
        if len(rows) < 2:
            return []

        # 1. Dynamic Header Mapping (The Anchor System)
        # Scan the first few rows to find the header
        header_row_idx, anchors = self._find_anchors(rows)
        
        if not anchors:
            logger.debug("Required anchors not found in table")
            return []

        entries = []
        
        # 2. Stateful Context Propagation
        persistent_metadata = {
            "category": "",
            "owner": "",
            "relation": ""
        }

        # Iterate through data rows
        for i in range(header_row_idx + 1, len(rows)):
            row = rows[i]
            
            # Skip empty rows
            if not any(row):
                continue
                
            # Skip summary rows (normalize spaces for matching)
            row_start = " ".join(row[:3]).replace(" ", "")
            if any(kw in row_start for kw in ["소계", "합계", "총계"]):
                continue

            # Determine if this is a "Full Row" or "Short Row"
            # We use the anchors to decide. 
            # If the row length matches the header length roughly, it's likely a full row (or close to it)
            # But the most robust way described is:
            # "If a row contains a Shareholder Name: Update the dictionary"
            
            current_metadata = persistent_metadata.copy()
            
            # Check for Name anchor presence in this row
            name_idx = anchors.get("name")
            relation_idx = anchors.get("relation")
            category_idx = anchors.get("category") # Optional
            
            # Heuristic: If row has enough cells to cover the name index, and that cell is not empty/numeric
            # likely it's a full row or at least contains the name.
            # However, with merged cells, the HTML parser might return empty strings for subsequent rows
            # or fewer cells if we are processing raw TRs.
            # parser.py's parse_table_to_rows handles rowspan by inserting empty strings.
            # So "Short Row" in our list of lists representation means empty strings in the merged columns.
            
            # Update metadata if values exist at the anchor positions
            if name_idx is not None and name_idx < len(row):
                val = row[name_idx].strip()
                if val:
                    # New shareholder found
                    current_metadata["owner"] = val
                    persistent_metadata["owner"] = val
                    
                    # Update other metadata only when name changes (usually they go together)
                    if category_idx is not None and category_idx < len(row):
                        cat_val = row[category_idx].strip()
                        if cat_val:
                            persistent_metadata["category"] = cat_val
                        current_metadata["category"] = persistent_metadata["category"]
                        
                    if relation_idx is not None and relation_idx < len(row):
                        rel_val = row[relation_idx].strip()
                        if rel_val:
                            persistent_metadata["relation"] = rel_val
                        current_metadata["relation"] = persistent_metadata["relation"]
            
            # If we still don't have an owner, something is wrong or it's a continuation of previous without proper structure
            if not current_metadata["owner"]:
                continue

            # 3. Smart Indexing for Partial Rows
            # Extract Quantity and Period
            # Strategy: Find the period cell first (most distinctive), then locate qty
            period_val = ""
            qty_val = ""

            # Try to find Period column dynamically in this row
            found_period_idx = -1
            for c_idx, cell in enumerate(row):
                if self._is_period_string(cell):
                    period_val = cell
                    found_period_idx = c_idx
                    break

            if found_period_idx != -1:
                # Find quantity: look left for a numeric cell that's NOT a percentage
                # Search up to 8 cols left to handle tables with many columns between qty and period
                for offset in range(1, min(found_period_idx + 1, 8)):
                    candidate = row[found_period_idx - offset].strip()
                    if candidate and not candidate.endswith("%") and candidate != "-":
                        # Check if it looks like a number
                        cleaned = candidate.replace(",", "").replace("주", "")
                        if cleaned.isdigit() or re.match(r"[\d,.]+", cleaned):
                            qty_val = candidate
                            break
            else:
                # Fallback to fixed anchors
                p_anchor = anchors.get("period")
                q_anchor = anchors.get("qty")
                if p_anchor is not None and p_anchor < len(row):
                    period_val = row[p_anchor]
                if q_anchor is not None and q_anchor < len(row):
                    qty_val = row[q_anchor]

            # 4. Data Normalization and Entry Creation
            if qty_val or period_val:
                entry = self._create_entry(
                    current_metadata, 
                    qty_val, 
                    period_val, 
                    listing_date
                )
                if entry:
                    entries.append(entry)

        return entries

    def _find_anchors(self, rows: List[List[str]]) -> Tuple[int, Dict[str, int]]:
        """
        Scan header rows to find column indices.
        Handles multi-row headers by scanning ALL header rows (up to 5)
        and accumulating anchors across them.
        Returns: (last_header_row_index, anchors_dict)
        """
        anchors: Dict[str, int] = {}
        first_header_idx = -1
        last_header_idx = -1

        # Scan first 5 rows for header keywords
        for i in range(min(5, len(rows))):
            row = rows[i]
            row_text = "".join(row).replace(" ", "")

            # Check if this row looks like a header
            is_header = False

            # A row with numeric values (amounts, percentages) is data, not header
            has_numeric = any(
                re.match(r"^[\d,]+\.?\d*%?$", c.strip()) and len(c.strip()) > 2
                for c in row if c.strip()
            )

            if not has_numeric:
                # Only rows without numeric data can be headers
                if any(kw in row_text for kw in ["주주명", "성명", "매각제한", "보호예수", "보유주식", "유통가능"]):
                    is_header = True
                # Check for header keyword that needs exact context (avoid matching 최대주주)
                elif "관계" in row_text and "회사" in row_text:
                    is_header = True
                # Sub-header continuation (주식수, 지분율, etc.)
                elif first_header_idx >= 0 and i <= first_header_idx + 3:
                    non_empty = [c for c in row if c.strip()]
                    if non_empty and all(
                        not c.replace(",", "").replace(".", "").replace("%", "").isdigit()
                        for c in non_empty
                    ):
                        is_header = True

            if not is_header:
                if first_header_idx >= 0:
                    break  # We've passed the header section
                continue

            if first_header_idx < 0:
                first_header_idx = i
            last_header_idx = i

            for idx, cell in enumerate(row):
                clean = cell.replace(" ", "").replace("\n", "")
                if not clean:
                    continue

                # Shareholder Name Anchor
                if "name" not in anchors and (
                    "주주명" in clean or "성명" in clean
                    or "보유자명" in clean or "보유자" in clean  # Relaxed from == to in
                    or "취득자" in clean
                ):
                    anchors["name"] = idx

                # Relationship Anchor
                if "relation" not in anchors and "관계" in clean:
                    anchors["relation"] = idx

                # Category Anchor
                if "category" not in anchors and "구분" in clean:
                    anchors["category"] = idx

                # Quantity Anchor — multiple patterns for real-world tables
                if "qty" not in anchors:
                    if "매각제한" in clean and ("물량" in clean or "주식수" in clean or "수량" in clean):
                        anchors["qty"] = idx
                    elif "보유주식" in clean:  # Matches "보유주식수", "매출후 보유주식수"
                        anchors["qty"] = idx
                    elif "의무보유" in clean and "주식수" in clean:
                        anchors["qty"] = idx
                    elif "의무보유주식수" in clean:
                        anchors["qty"] = idx
                    elif "취득수량" in clean:
                        anchors["qty"] = idx

                # Period Anchor
                if "period" not in anchors:
                    if "매각제한기간" in clean or "보호예수기간" in clean or "의무보유기간" in clean:
                        anchors["period"] = idx
                    elif "기간" in clean and "행사기간" not in clean:  # Catches "의무보유 기간", "매각제한 기간"
                        anchors["period"] = idx
                    elif "비고" in clean: # Fallback: Sometimes period is in Remarks/Note column
                        anchors["period"] = idx

        # Minimum requirements: Name
        if "name" in anchors:
            return last_header_idx, anchors

        return -1, {}

    def _is_period_string(self, text: str) -> bool:
        """Check if string looks like a lockup period"""
        text = text.replace(" ", "")
        return "상장일" in text or "개월" in text or ("년" in text and "주년" not in text)

    def _create_entry(
        self, 
        metadata: Dict[str, str], 
        qty_str: str, 
        period_str: str,
        listing_date: Optional[date]
    ) -> Optional[LockupEntry]:
        """Create LockupEntry from raw strings"""
        
        # Data Normalization
        qty = self.normalizer.normalize_amount(qty_str)
        period_months = self.normalizer.normalize_period(period_str)
        
        listing_date = listing_date or date.today() # Fallback if not provided, though bad practice
        
        release_date = None
        if period_months is not None:
             release_date = listing_date + timedelta(days=period_months * 30)
        
        # If we have at least period or quantity
        if qty is not None or period_months is not None:
            return LockupEntry(
                owner=metadata["owner"],
                amount=qty,
                period_months=period_months,
                release_date=release_date,
                category=metadata.get("category"),
                relation=metadata.get("relation"),
                remarks=period_str # Store original period string as remarks
            )
        return None

    def _parse_table_rows(self, table: Tag) -> List[List[str]]:
        """Parse table into list of rows with full colspan/rowspan expansion.

        Produces a grid where every row has the same number of columns.
        Cells spanned by rowspan are filled with empty strings in subsequent rows.
        """
        trs = table.find_all("tr")
        if not trs:
            return []

        # First pass: determine grid dimensions
        # pending_rowspans tracks cells that still need to be filled from previous rows
        # Key: (row_idx, col_idx), Value: text (empty string for spanned cells)
        pending: Dict[Tuple[int, int], str] = {}
        raw_rows: List[List[str]] = []

        for row_idx, tr in enumerate(trs):
            cells_in_row: List[Tuple[int, str]] = []  # (col_idx, text)
            col_cursor = 0
            cell_elements = tr.find_all(["th", "td"])

            for cell in cell_elements:
                # Skip columns occupied by rowspan from previous rows
                while (row_idx, col_cursor) in pending:
                    col_cursor += 1

                colspan = int(cell.get("colspan", 1))
                rowspan = int(cell.get("rowspan", 1))
                text = " ".join(cell.get_text(strip=True).split())

                # Place this cell and its colspan expansions
                for c in range(colspan):
                    actual_col = col_cursor + c
                    cells_in_row.append((actual_col, text if c == 0 else ""))

                    # Register rowspan for subsequent rows
                    if rowspan > 1:
                        for r in range(1, rowspan):
                            pending[(row_idx + r, actual_col)] = ""

                col_cursor += colspan

            # Also check if there are any remaining pending cells after the last real cell
            # (shouldn't normally happen but be safe)

            raw_rows.append(cells_in_row)

        # Second pass: build uniform grid
        # Determine max columns
        max_cols = 0
        for row_idx, cell_list in enumerate(raw_rows):
            cols_from_cells = max((c + 1 for c, _ in cell_list), default=0)
            cols_from_pending = max(
                (c + 1 for (r, c) in pending if r == row_idx), default=0
            )
            max_cols = max(max_cols, cols_from_cells, cols_from_pending)

        rows: List[List[str]] = []
        for row_idx, cell_list in enumerate(raw_rows):
            row = [""] * max_cols
            for col, text in cell_list:
                if col < max_cols:
                    row[col] = text
            # Pending (rowspan) cells stay as empty strings — this is intentional
            # so the stateful context propagation handles them
            rows.append(row)

        return rows

    # Legacy method support if needed, or just let it handle things
    def extract_from_html(self, html_content: str, listing_date: Optional[date] = None) -> List[LockupEntry]:
        soup = BeautifulSoup(html_content, "lxml")
        all_entries = []
        for table in soup.find_all("table"):
            if table.find_parent("table"): continue
            all_entries.extend(self.extract_from_table(table, listing_date))
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
