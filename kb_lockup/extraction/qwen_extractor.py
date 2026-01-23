"""Qwen API for variable table layout extraction"""

import json
from typing import List, Optional, Dict, Any
from datetime import date

from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from kb_lockup.config import settings
from kb_lockup.core.models import TableCandidate, LockupEntry
from kb_lockup.core.exceptions import ExtractionError
from kb_lockup.extraction.normalizer import KoreanNormalizer


SYSTEM_PROMPT = """당신은 한국 금융 문서에서 주주 보호예수(lockup) 일정을 추출하는 전문가입니다.

## 추출 대상 정보
다음 정보가 포함된 테이블을 찾아 추출하세요:
- 주주명/성명/보유자 (Shareholder name)
- 보유량/주식수/수량 (Number of shares)
- 지분율/비율 (Ownership percentage)
- 보호예수기간/의무보유기간 (Lock-up period)
- 해제일/매각가능일/만료일 (Release date)
- 비고/사유 (Remarks)

## 출력 형식
다음 JSON 형식으로 반환하세요:
{
  "entries": [
    {
      "owner": "홍길동",
      "amount": 1000000,
      "ratio": 5.5,
      "release_date": "2024-06-15",
      "period_months": 6,
      "remarks": "최대주주"
    }
  ],
  "confidence": 0.9,
  "source_table": "보호예수 현황"
}

## 추출 규칙
1. 테이블의 모든 행을 추출하세요 (일부만 추출하지 마세요)
2. 날짜 형식: YYYY-MM-DD (예: 2024년 6월 15일 → 2024-06-15)
3. 주식수: 정수로 변환 (예: 100만주 → 1000000, 1,234,567주 → 1234567)
4. 지분율: 0-100 사이의 숫자 (예: 5.5% → 5.5)
5. 상대적 날짜(예: "상장일로부터 6개월")는 release_date를 null로, period_months에 개월 수 입력
6. 보호예수/의무보유/매각제한 관련 데이터만 추출 (일반 주주현황 제외)
7. 데이터가 없으면 빈 배열 반환: {"entries": [], "confidence": 0}

## 주의사항
- "최대주주", "특수관계인", "임원" 등은 remarks에 포함
- 합계/소계 행은 제외
- 같은 주주가 여러 번 나오면 각각 별도 항목으로 추출
"""


FALLBACK_PROMPT = """주어진 HTML 테이블에서 보호예수 정보를 추출하세요.

테이블:
{table_html}

컬럼 헤더: {headers}

JSON 형식으로 추출 결과만 반환하세요:
{{"entries": [...], "confidence": 0.0-1.0}}
"""


class QwenTableExtractor:
    """Use Qwen API for table extraction with retry logic and validation"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.api_key = api_key or settings.qwen_api_key
        self.model = model or settings.qwen_model
        self.normalizer = KoreanNormalizer()
        self._extraction_stats = {
            "total_calls": 0,
            "successful": 0,
            "failed": 0,
            "entries_extracted": 0,
        }

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
        listing_date: Optional[date] = None,
    ) -> List[LockupEntry]:
        """
        Extract lockup entries from table candidates using Qwen

        Args:
            table_candidates: List of candidate tables
            context: Additional context about the document
            listing_date: Company listing date for relative date calculation

        Returns:
            List of normalized LockupEntry objects
        """
        if not table_candidates:
            return []

        self._extraction_stats["total_calls"] += 1

        # Build prompt with all candidate tables
        prompt = self._build_prompt(table_candidates, context)

        try:
            entries = self._call_api_with_retry(prompt)

            # Post-process entries
            entries = self._post_process_entries(entries, listing_date)

            # Validate entries
            entries = self._validate_entries(entries)

            self._extraction_stats["successful"] += 1
            self._extraction_stats["entries_extracted"] += len(entries)

            return entries

        except Exception as e:
            logger.error(f"Qwen extraction failed: {e}")
            self._extraction_stats["failed"] += 1

            # Try fallback extraction for each table
            entries = self._fallback_extraction(table_candidates)
            if entries:
                return entries

            raise ExtractionError(f"Qwen API error: {e}")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def _call_api_with_retry(self, prompt: str) -> List[LockupEntry]:
        """Call Qwen API with retry logic"""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=4096,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content
        return self._parse_response(content)

    def _fallback_extraction(
        self,
        candidates: List[TableCandidate],
    ) -> List[LockupEntry]:
        """Fallback extraction for individual tables"""
        all_entries = []

        for candidate in candidates[:2]:  # Try top 2 candidates
            try:
                prompt = FALLBACK_PROMPT.format(
                    table_html=candidate.raw_html[:3000] if candidate.raw_html else "",
                    headers=", ".join(candidate.column_headers),
                )

                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    max_tokens=2048,
                    response_format={"type": "json_object"},
                )

                content = response.choices[0].message.content
                entries = self._parse_response(content)
                all_entries.extend(entries)

            except Exception as e:
                logger.warning(f"Fallback extraction failed for table: {e}")
                continue

        return all_entries

    def _post_process_entries(
        self,
        entries: List[LockupEntry],
        listing_date: Optional[date] = None,
    ) -> List[LockupEntry]:
        """Post-process extracted entries"""
        processed = []

        for entry in entries:
            # Calculate release date from period if not present
            if not entry.release_date and entry.period_months and listing_date:
                from datetime import timedelta
                entry.release_date = listing_date + timedelta(days=entry.period_months * 30)

            # Clean owner name
            if entry.owner:
                entry.owner = self._clean_owner_name(entry.owner)

            # Normalize ratio
            if entry.ratio is not None:
                # Ensure ratio is in percentage form (0-100)
                if entry.ratio > 100:
                    entry.ratio = entry.ratio / 100
                elif entry.ratio < 0:
                    entry.ratio = None

            # Normalize amount
            if entry.amount is not None and entry.amount < 0:
                entry.amount = None

            processed.append(entry)

        return processed

    def _clean_owner_name(self, name: str) -> str:
        """Clean and normalize owner name"""
        # Remove parenthetical notes
        name = name.split("(")[0].strip()

        # Remove common suffixes
        suffixes = ["외", "등", "기타"]
        for suffix in suffixes:
            if name.endswith(suffix):
                name = name[:-len(suffix)].strip()

        return name

    def _validate_entries(self, entries: List[LockupEntry]) -> List[LockupEntry]:
        """Validate and filter extracted entries"""
        valid = []

        for entry in entries:
            # Must have owner
            if not entry.owner or len(entry.owner.strip()) < 2:
                continue

            # Skip aggregate rows
            skip_keywords = ["합계", "소계", "총계", "계", "total", "sum"]
            if any(kw in entry.owner.lower() for kw in skip_keywords):
                continue

            # Must have at least one of: amount, ratio, release_date
            if not any([entry.amount, entry.ratio, entry.release_date, entry.period_months]):
                continue

            # Validate ratio range
            if entry.ratio is not None and (entry.ratio < 0 or entry.ratio > 100):
                entry.ratio = None

            valid.append(entry)

        return valid

    @property
    def stats(self) -> Dict[str, int]:
        """Get extraction statistics"""
        return self._extraction_stats.copy()

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
