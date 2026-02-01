"""AI-powered lockup table identification using Qwen API"""

import json
from typing import List, Optional, Tuple

from bs4 import BeautifulSoup, Tag
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from kb_lockup.config import settings


# Keywords that indicate a table is NOT a lockup table
FINANCIAL_KEYWORDS = [
    "재무제표", "손익계산서", "재무상태표", "현금흐름표",
    "자본변동표", "감사보고서", "요약재무정보",
]

IRRELEVANT_KEYWORDS = [
    "스톡옵션", "주식매수선택권", "전환사채", "신주인수권",
    "배당금", "임원보수", "자금사용", "자금의사용",
]

# Keywords that indicate lockup-related content
LOCKUP_KEYWORDS = ["보호예수", "의무보유", "매각제한", "유통제한", "lockup", "유통가능"]


TABLE_IDENTIFICATION_PROMPT = """한국 증권신고서에서 보호예수(lockup) 테이블을 식별하세요.

## 보호예수 테이블의 특징
- "주주명", "성명", "보유자명", "보유자", "취득자" 중 하나의 컬럼
- "매각제한기간", "보호예수기간", "의무보유기간", "의무보유 기간" 중 하나의 컬럼
- "매각제한 물량", "주식수", "보유수량", "보유주식수", "취득수량", "의무보유주식수", "유통가능물량" 중 하나의 컬럼
- 주주별로 보호예수 기간과 수량이 행으로 나열
- "상장일로부터 X개월" 같은 기간 표현
- 표 제목이나 문맥에 "유통가능주식 현황", "유통제한 및 유통가능", "공모 후 유통가능" 등이 포함될 수 있음 (가장 중요)

## 이것은 보호예수 테이블이 아닙니다
- 단순 주주 현황 (보호예수 기간/의무보유 정보 없음)
- 재무제표, 손익계산서
- 공모 배정/청약 현황
- 스톡옵션/주식매수선택권
- 자금사용 계획

## 테이블 목록
{table_summaries}

중요: "유통가능주식 현황" 또는 "유통제한" 관련 제목을 가진 테이블은 모든 보호예수 정보를 포함하는 마스터 테이블일 가능성이 높으므로 최우선으로 선택하세요.

## 응답 (JSON)
{{"selected_tables": [테이블 번호], "reasoning": "선택 이유"}}

보호예수 테이블이 없으면:
{{"selected_tables": [], "reasoning": "보호예수 관련 테이블 없음"}}"""


class AITableFinder:
    """Use Qwen AI to identify lockup tables in DART prospectus documents.

    Flow:
    1. Extract all candidate tables (top-level + nested lockup tables)
    2. Pre-filter obvious non-candidates
    3. Build compact summaries
    4. Ask AI which tables contain lockup info
    5. Deduplicate similar tables
    6. Return selected Tag objects for rule-based extraction
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.api_key = api_key or settings.qwen_api_key
        self.model = model or settings.qwen_model

        if not self.api_key:
            raise ValueError("Qwen API key is required for AI table finding")

        from openai import OpenAI
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=settings.qwen_base_url_v1,
        )

    def find_lockup_tables(
        self,
        html_content: str,
        max_tables: int = 3,
    ) -> List[Tag]:
        """
        Find lockup table(s) in HTML document using AI identification.

        Returns list of BeautifulSoup Tag objects for the identified lockup tables.
        Falls back to marker-based search if AI fails.
        """
        soup = BeautifulSoup(html_content, "lxml")

        # Step 1: Extract all candidate tables (including nested lockup tables)
        all_tables = self._extract_candidate_tables(soup)
        logger.info(f"Found {len(all_tables)} candidate tables in document")

        if not all_tables:
            return []

        # Step 2: Pre-filter obvious non-candidates
        candidates = self._pre_filter(all_tables)
        logger.info(f"Pre-filter: {len(all_tables)} -> {len(candidates)} candidates")

        if not candidates:
            logger.info("No candidates after pre-filter, trying fallback")
            return self._fallback_marker_search(soup)

        # Step 3: If too many candidates, apply secondary keyword filter
        if len(candidates) > 40:
            narrowed = [
                (t, i) for t, i in candidates
                if any(kw in t.get_text() for kw in LOCKUP_KEYWORDS)
            ]
            if narrowed:
                candidates = narrowed
                logger.info(f"Secondary filter: -> {len(candidates)} candidates")

        # Step 4: Build compact summaries
        summaries = self._build_summaries(candidates)

        # Step 5: Ask AI
        try:
            selected_indices = self._ask_ai(summaries)
        except Exception as e:
            logger.warning(f"AI table identification failed: {e}, using fallback")
            return self._fallback_marker_search(soup)

        # Step 6: Collect selected tables
        selected = []
        for idx in selected_indices[:max_tables]:
            if 0 <= idx < len(candidates):
                table_tag, _ = candidates[idx]
                selected.append(table_tag)

        if not selected:
            logger.info("AI found no lockup tables, trying fallback")
            return self._fallback_marker_search(soup)

        # Step 7: Deduplicate similar tables
        result = self._deduplicate_tables(selected)
        logger.info(f"AI identified {len(result)} lockup table(s) (after dedup)")
        return result

    def _extract_candidate_tables(self, soup: BeautifulSoup) -> List[Tag]:
        """Extract candidate tables: top-level tables + nested lockup tables.

        Some documents embed lockup data tables inside footnote cells.
        We extract these nested tables as separate candidates.
        """
        tables = []

        for table in soup.find_all("table"):
            parent_table = table.find_parent("table")
            if not parent_table:
                # Top-level table
                tables.append(table)
            else:
                # Nested table - include if it looks lockup-related
                # Check full text for keywords, not just headers
                text = table.get_text()
                # Use broader keywords for nested tables
                keywords = ["보유자", "의무보유", "유통가능", "매각제한", "보호예수", "취득자", "주식수", "기간"]
                if any(kw in text for kw in keywords):
                    tables.append(table)

        return tables

    def _pre_filter(self, tables: List[Tag]) -> List[Tuple[Tag, int]]:
        """Remove obvious non-candidates. Returns (tag, original_index) pairs."""
        candidates = []

        for i, table in enumerate(tables):
            rows = table.find_all("tr", recursive=False)
            # For tables without direct tr children, try recursive
            if not rows:
                rows = table.find_all("tr")

            # Skip tiny tables (but allow 2-row tables for small lockup tables)
            if len(rows) < 2:
                continue

            # Skip very large layout tables
            if len(rows) > 2000:
                continue

            # Skip single-cell wrapper tables
            cells = table.find_all(["td", "th"])
            if len(cells) <= 2:
                continue

            text = table.get_text()

            # Skip tables dominated by financial keywords
            if sum(1 for kw in FINANCIAL_KEYWORDS if kw in text) >= 2:
                continue

            # Skip tables dominated by irrelevant keywords
            if sum(1 for kw in IRRELEVANT_KEYWORDS if kw in text) >= 2:
                continue

            candidates.append((table, i))

        return candidates

    def _build_summaries(self, candidates: List[Tuple[Tag, int]]) -> str:
        """Build compact text summaries for AI input."""
        parts = []

        for local_idx, (table, _) in enumerate(candidates):
            rows = table.find_all("tr")

            # Headers from first 2 rows (handles multi-row headers)
            header_texts = []
            for row in rows[:2]:
                cells = row.find_all(["th", "td"])
                row_cells = [c.get_text(strip=True) for c in cells]
                row_cells = [h for h in row_cells if h]
                if row_cells:
                    header_texts.append(" | ".join(row_cells[:10]))

            # First 3 data rows
            data_preview = []
            for row in rows[2:5]:
                cells = row.find_all(["td", "th"])
                row_text = [c.get_text(strip=True)[:30] for c in cells]
                row_text = [t for t in row_text if t]
                if row_text:
                    data_preview.append(" | ".join(row_text[:10]))

            # Section context
            context = self._get_context_before(table)
            row_count = len(rows) - 1

            summary = f"[테이블 {local_idx}] 행수:{row_count}, 섹션:{context[:200]}\n"
            for h in header_texts:
                summary += f"  헤더: {h[:120]}\n"
            for j, d in enumerate(data_preview):
                summary += f"  행{j+1}: {d[:120]}\n"

            parts.append(summary)

        return "\n".join(parts)

    def _get_context_before(self, table: Tag) -> str:
        """Get text from elements preceding the table."""
        context_parts = []
        for prev in table.previous_siblings:
            if hasattr(prev, "get_text"):
                text = prev.get_text(strip=True)
                if text:
                    context_parts.insert(0, text)
                    if len(" ".join(context_parts)) > 200:
                        break
            elif isinstance(prev, str) and prev.strip():
                context_parts.insert(0, prev.strip())
        return " ".join(context_parts)[-200:] if context_parts else ""

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=2, max=8),
        reraise=True,
    )
    def _ask_ai(self, summaries: str) -> List[int]:
        """Call Qwen API to identify lockup tables."""
        prompt = TABLE_IDENTIFICATION_PROMPT.format(table_summaries=summaries)

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=1024,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content
        
        try:
            with open("ai_debug.log", "a", encoding="utf-8") as f:
                f.write(f"\n--- RESPONSE ---\n{content}\n----------------\n")
        except Exception:
            pass
            
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            logger.error(f"Unparseable AI response: {content}")
            raise

        selected = data.get("selected_tables", [])
        reasoning = data.get("reasoning", "")
        logger.info(f"AI reasoning: {reasoning}")
        logger.info(f"AI selected tables: {selected}")

        return [int(i) for i in selected]

    def _deduplicate_tables(self, tables: List[Tag]) -> List[Tag]:
        """Remove duplicate tables that have the same content.

        DART documents often repeat the same table in original and
        amendment sections. We compare text content to deduplicate.
        """
        if len(tables) <= 1:
            return tables

        unique = [tables[0]]
        seen_texts = [self._get_table_fingerprint(tables[0])]

        for table in tables[1:]:
            fp = self._get_table_fingerprint(table)
            if not any(self._fingerprints_similar(fp, s) for s in seen_texts):
                unique.append(table)
                seen_texts.append(fp)

        if len(unique) < len(tables):
            logger.info(f"Dedup: {len(tables)} -> {len(unique)} tables")

        return unique

    def _get_table_fingerprint(self, table: Tag) -> str:
        """Get a fingerprint for deduplication: normalized table content."""
        # Use entire table text for more robust deduplication
        text = table.get_text(strip=True)
        # Remove whitespace to handle formatting differences
        return "".join(text.split())

    def _fingerprints_similar(self, fp1: str, fp2: str) -> bool:
        """Check if two fingerprints represent the same table."""
        if not fp1 or not fp2:
            return False
        # If one is a prefix of the other or they share > 80% content
        # If one is a prefix of the other or they share > 80% content
        shorter = min(len(fp1), len(fp2))
        if shorter == 0:
            return False
        # Higher threshold for strict deduplication
        common = sum(1 for a, b in zip(fp1, fp2) if a == b)
        return common / shorter > 0.95

    def _fallback_marker_search(self, soup: BeautifulSoup) -> List[Tag]:
        """Fallback: marker-based search for lockup tables."""
        lockup_markers = [
            "상장 후 유통가능 및 매각제한 물량",
            "매각제한 물량",
            "보호예수 현황",
            "의무보유 현황",
            "매각제한 주식",
            "의무보유확약",
        ]

        for marker in lockup_markers:
            matches = soup.find_all(string=lambda text: text and marker in text)
            for m in matches:
                parent = m.find_parent(["td", "th", "p", "span", "div"])
                if not parent:
                    continue

                parent_table = parent.find_parent("table")
                if parent_table:
                    next_table = parent_table.find_next_sibling("table")
                    if not next_table:
                        next_table = parent_table.find_next("table")
                        if next_table == parent_table:
                            next_table = None

                    if next_table and self._looks_like_lockup_table(next_table):
                        logger.info(f"Fallback found lockup table via marker: '{marker}'")
                        return [next_table]

                next_table = parent.find_next("table")
                if next_table and self._looks_like_lockup_table(next_table):
                    logger.info(f"Fallback found lockup table via marker: '{marker}'")
                    return [next_table]

        return []

    def _looks_like_lockup_table(self, table: Tag) -> bool:
        """Quick check if a table looks like a lockup table."""
        text = ""
        for tr in table.find_all("tr")[:5]:
            text += tr.get_text()
        return (
            "주주" in text or "관계" in text or "성명" in text
            or "보유자" in text or "취득자" in text
        )
