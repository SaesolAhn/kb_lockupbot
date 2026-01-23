"""Qwen API for variable table layout extraction"""

import json
from typing import List, Optional

from loguru import logger

from kb_lockup.config import settings
from kb_lockup.core.models import TableCandidate, LockupEntry
from kb_lockup.core.exceptions import ExtractionError
from kb_lockup.extraction.normalizer import KoreanNormalizer


SYSTEM_PROMPT = """You are an expert at extracting shareholder lockup schedules from Korean financial documents.

Extract tables containing:
- 주주명/성명 (Shareholder name)
- 보유량/주식수 (Share amount)
- 지분율 (Ownership ratio %)
- 보호예수/의무보유 기간 (Lock period)
- 해제일/매각가능일 (Release date)

Return a JSON array of lockup entries with the following structure:
[
  {
    "owner": "주주명",
    "amount": 1234567,
    "ratio": 12.34,
    "release_date": "2024-06-15",
    "period_months": 6,
    "remarks": "비고 내용"
  }
]

Rules:
1. Extract ALL rows from the lockup table, not just the first few
2. Convert Korean date formats to ISO format (YYYY-MM-DD)
3. Convert share amounts to integers (remove 주, 만주 etc.)
4. Convert ratios to float percentages (0-100)
5. If a date is relative (e.g., "상장일로부터 6개월"), leave release_date as null and set period_months
6. Return empty array [] if no lockup data found
7. Only include actual lockup/보호예수 entries, not general shareholder lists
"""


class QwenTableExtractor:
    """Use Qwen API for table extraction"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.api_key = api_key or settings.qwen_api_key
        self.model = model or settings.qwen_model
        self.normalizer = KoreanNormalizer()

        if not self.api_key:
            raise ValueError("Qwen API key is required")

        from openai import OpenAI
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=settings.qwen_base_url,
        )

    def extract_tables(
        self,
        table_candidates: List[TableCandidate],
        context: Optional[str] = None,
    ) -> List[LockupEntry]:
        """
        Extract lockup entries from table candidates using Qwen

        Args:
            table_candidates: List of candidate tables
            context: Additional context about the document

        Returns:
            List of normalized LockupEntry objects
        """
        if not table_candidates:
            return []

        # Build prompt with all candidate tables
        prompt = self._build_prompt(table_candidates, context)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            return self._parse_response(content)

        except Exception as e:
            logger.error(f"Qwen extraction failed: {e}")
            raise ExtractionError(f"Qwen API error: {e}")

    def _build_prompt(
        self,
        candidates: List[TableCandidate],
        context: Optional[str],
    ) -> str:
        """Build extraction prompt with table content"""
        parts = ["다음 문서에서 보호예수/의무보유 정보를 추출해주세요.\n"]

        if context:
            parts.append(f"문서 정보: {context}\n")

        for i, candidate in enumerate(candidates, 1):
            parts.append(f"\n=== 테이블 {i}: {candidate.section_title} ===")
            if candidate.context_text:
                parts.append(f"맥락: {candidate.context_text[:200]}")
            parts.append(candidate.raw_html or "")

        parts.append("\n\nJSON 형식으로 추출 결과를 반환해주세요.")

        return "\n".join(parts)

    def _parse_response(self, content: str) -> List[LockupEntry]:
        """Parse Qwen response into LockupEntry objects"""
        try:
            data = json.loads(content)

            # Handle different response structures
            if isinstance(data, list):
                entries = data
            elif isinstance(data, dict):
                entries = data.get("entries", data.get("lockups", data.get("data", [])))
            else:
                logger.warning(f"Unexpected response type: {type(data)}")
                return []

            results = []
            for item in entries:
                try:
                    entry = LockupEntry(
                        owner=item.get("owner", ""),
                        amount=self._safe_int(item.get("amount")),
                        ratio=self._safe_float(item.get("ratio")),
                        release_date=self.normalizer.parse_date(
                            item.get("release_date")
                        ) if item.get("release_date") else None,
                        period_months=self._safe_int(item.get("period_months")),
                        remarks=item.get("remarks"),
                    )

                    if entry.owner:  # Only include entries with owner
                        results.append(entry)

                except Exception as e:
                    logger.warning(f"Failed to parse entry: {e}")

            logger.info(f"Extracted {len(results)} lockup entries")
            return results

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            return []

    @staticmethod
    def _safe_int(value) -> Optional[int]:
        """Safely convert to int"""
        if value is None:
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _safe_float(value) -> Optional[float]:
        """Safely convert to float"""
        if value is None:
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None
