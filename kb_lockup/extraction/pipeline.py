"""Extraction pipeline orchestrator"""

import asyncio
from datetime import date
from typing import Optional, List, Tuple
from dataclasses import dataclass

from loguru import logger

from kb_lockup.config import settings
from kb_lockup.core.models import (
    Company,
    LockupEntry,
    LockupResult,
    ProspectusInfo,
    TableCandidate,
)
from kb_lockup.core.exceptions import ExtractionError, DartAPIError
from kb_lockup.dart.api import DartAPI
from kb_lockup.dart.parser import DartParser
from kb_lockup.dart.downloader import ProspectusDownloader
from kb_lockup.extraction.table_finder import TableFinder
from kb_lockup.extraction.qwen_extractor import QwenTableExtractor
from kb_lockup.extraction.scorer import TableScorer
from kb_lockup.storage.database import Database


@dataclass
class ExtractionStats:
    """Statistics from extraction run"""
    companies_processed: int = 0
    documents_processed: int = 0
    tables_found: int = 0
    entries_extracted: int = 0
    errors: int = 0


class ExtractionPipeline:
    """
    Orchestrates the full extraction workflow:
    1. Find company in DART
    2. Search for prospectus filings
    3. Download and parse documents
    4. Find lockup tables
    5. Extract data with Qwen
    6. Store results in database
    """

    def __init__(
        self,
        dart_api_key: Optional[str] = None,
        qwen_api_key: Optional[str] = None,
        db_path: Optional[str] = None,
    ):
        self.dart_api_key = dart_api_key or settings.dart_api_key
        self.qwen_api_key = qwen_api_key or settings.qwen_api_key
        self.db_path = db_path

        self._api: Optional[DartAPI] = None
        self._db: Optional[Database] = None
        self._extractor: Optional[QwenTableExtractor] = None

        self.stats = ExtractionStats()

    async def __aenter__(self):
        await self.setup()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup()

    async def setup(self) -> None:
        """Initialize components"""
        self._api = DartAPI(self.dart_api_key)
        await self._api.__aenter__()

        from pathlib import Path
        self._db = Database(Path(self.db_path) if self.db_path else None)
        await self._db.connect()
        await self._db.init_schema()

        if self.qwen_api_key:
            self._extractor = QwenTableExtractor(self.qwen_api_key)

        logger.info("Extraction pipeline initialized")

    async def cleanup(self) -> None:
        """Cleanup resources"""
        if self._api:
            await self._api.__aexit__(None, None, None)
        if self._db:
            await self._db.close()

    @property
    def api(self) -> DartAPI:
        if not self._api:
            raise RuntimeError("Pipeline not initialized")
        return self._api

    @property
    def db(self) -> Database:
        if not self._db:
            raise RuntimeError("Pipeline not initialized")
        return self._db

    async def extract_company(
        self,
        company_name: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        force: bool = False,
    ) -> LockupResult:
        """
        Extract lockup data for a single company

        Args:
            company_name: Company name or stock code
            start_date: Search start date (YYYYMMDD)
            end_date: Search end date (YYYYMMDD)
            force: Re-extract even if already processed

        Returns:
            LockupResult with extracted entries
        """
        logger.info(f"Starting extraction for: {company_name}")

        # Step 1: Find company
        company = await self._find_company(company_name)
        if not company:
            raise ExtractionError(f"Company not found: {company_name}")

        logger.info(f"Found company: {company.corp_name} ({company.corp_code})")

        # Step 2: Search for prospectuses
        prospectuses = await self.api.search_prospectuses(
            corp_code=company.corp_code,
            bgn_de=start_date,
            end_de=end_date,
        )

        if not prospectuses:
            logger.warning(f"No prospectus filings found for {company.corp_name}")
            return LockupResult(
                company=company,
                rcept_no="",
                entries=[],
                confidence_score=0,
            )

        logger.info(f"Found {len(prospectuses)} prospectus filings")

        # Step 3: Process each prospectus
        all_entries = []
        best_result: Optional[LockupResult] = None
        best_score = 0.0

        for prospectus in prospectuses:
            # Check if already processed
            if not force and await self.db.is_prospectus_processed(prospectus.rcept_no):
                logger.debug(f"Skipping already processed: {prospectus.rcept_no}")
                continue

            try:
                result = await self._process_prospectus(company, prospectus)

                if result.entries:
                    all_entries.extend(result.entries)

                    if result.confidence_score > best_score:
                        best_score = result.confidence_score
                        best_result = result

                self.stats.documents_processed += 1

            except Exception as e:
                logger.error(f"Failed to process {prospectus.rcept_no}: {e}")
                self.stats.errors += 1

                # Record failed processing
                await self.db.mark_prospectus_processed(
                    rcept_no=prospectus.rcept_no,
                    corp_code=company.corp_code,
                    report_nm=prospectus.report_nm,
                    rcept_dt=prospectus.rcept_dt,
                    method="qwen",
                    tables_found=0,
                    error=str(e),
                )

        self.stats.companies_processed += 1
        self.stats.entries_extracted += len(all_entries)

        # Return best result or create one from all entries
        if best_result:
            best_result.entries = all_entries  # Include all entries
            return best_result

        return LockupResult(
            company=company,
            rcept_no=prospectuses[0].rcept_no if prospectuses else "",
            entries=all_entries,
            confidence_score=best_score,
        )

    async def _find_company(self, query: str) -> Optional[Company]:
        """Find company by name or stock code"""
        # Try stock code first (if 6 digits)
        if query.isdigit() and len(query) <= 6:
            company = await self.api.get_corp_by_stock_code(query.zfill(6))
            if company:
                return company

        # Try company name
        return await self.api.get_corp_code(query)

    async def _process_prospectus(
        self,
        company: Company,
        prospectus: ProspectusInfo,
    ) -> LockupResult:
        """Process a single prospectus document"""
        logger.info(f"Processing: {prospectus.report_nm} ({prospectus.rcept_no})")

        # Download document
        downloader = ProspectusDownloader(self.api)
        content = await downloader.download_document(prospectus.rcept_no)

        # Find lockup tables
        table_finder = TableFinder(min_score=settings.min_extraction_score)
        candidates = table_finder.find_lockup_tables(content, max_candidates=3)

        self.stats.tables_found += len(candidates)

        if not candidates:
            logger.warning(f"No lockup tables found in {prospectus.rcept_no}")
            return LockupResult(
                company=company,
                rcept_no=prospectus.rcept_no,
                entries=[],
                confidence_score=0,
            )

        # Extract with Qwen if available
        entries = []
        confidence = candidates[0].score if candidates else 0

        if self._extractor and candidates:
            try:
                entries = self._extractor.extract_tables(
                    candidates,
                    context=f"Company: {company.corp_name}, Document: {prospectus.report_nm}",
                )
                logger.info(f"Extracted {len(entries)} lockup entries")
            except Exception as e:
                logger.error(f"Qwen extraction failed: {e}")
                # Fall back to no extraction
                entries = []

        # Store results
        if entries:
            await self.db.insert_lockup_entries(
                entries=entries,
                company_name=company.corp_name,
                stock_code=company.stock_code,
                source_rcept_no=prospectus.rcept_no,
                source_section=candidates[0].section_title if candidates else None,
                extraction_score=confidence,
            )

        # Mark as processed
        await self.db.mark_prospectus_processed(
            rcept_no=prospectus.rcept_no,
            corp_code=company.corp_code,
            report_nm=prospectus.report_nm,
            rcept_dt=prospectus.rcept_dt,
            method="qwen" if self._extractor else "tables_only",
            tables_found=len(candidates),
        )

        # Save company info
        await self.db.upsert_company(company)

        return LockupResult(
            company=company,
            rcept_no=prospectus.rcept_no,
            section_title=candidates[0].section_title if candidates else None,
            entries=entries,
            extraction_method="qwen" if self._extractor else "tables_only",
            confidence_score=confidence,
        )

    async def extract_batch(
        self,
        company_names: List[str],
        concurrency: int = 3,
    ) -> List[LockupResult]:
        """
        Extract lockup data for multiple companies

        Args:
            company_names: List of company names or stock codes
            concurrency: Max concurrent extractions
        """
        results = []
        semaphore = asyncio.Semaphore(concurrency)

        async def process_one(name: str) -> Optional[LockupResult]:
            async with semaphore:
                try:
                    return await self.extract_company(name)
                except Exception as e:
                    logger.error(f"Failed to extract {name}: {e}")
                    self.stats.errors += 1
                    return None

        tasks = [process_one(name) for name in company_names]
        completed = await asyncio.gather(*tasks)

        results = [r for r in completed if r is not None]

        logger.info(
            f"Batch extraction complete: {len(results)}/{len(company_names)} successful"
        )

        return results

    async def extract_recent_ipos(
        self,
        days: int = 90,
    ) -> List[LockupResult]:
        """
        Extract lockup data from recent IPO prospectuses

        Args:
            days: Look back period in days
        """
        from datetime import timedelta

        end_date = date.today()
        start_date = end_date - timedelta(days=days)

        logger.info(f"Searching for IPO prospectuses from {start_date} to {end_date}")

        prospectuses = await self.api.get_ipo_prospectuses(
            bgn_de=start_date.strftime("%Y%m%d"),
            end_de=end_date.strftime("%Y%m%d"),
        )

        results = []
        for prospectus in prospectuses:
            # Get company info
            company = await self.api.get_corp_code(prospectus.corp_code)
            if not company:
                # Create minimal company object
                company = Company(
                    corp_code=prospectus.corp_code,
                    corp_name=prospectus.report_nm.split("증권신고서")[0].strip(),
                )

            try:
                result = await self._process_prospectus(company, prospectus)
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to process IPO {prospectus.rcept_no}: {e}")
                self.stats.errors += 1

        return results

    def get_stats(self) -> dict:
        """Get extraction statistics"""
        return {
            "companies_processed": self.stats.companies_processed,
            "documents_processed": self.stats.documents_processed,
            "tables_found": self.stats.tables_found,
            "entries_extracted": self.stats.entries_extracted,
            "errors": self.stats.errors,
            "api_requests": self.api.request_count if self._api else 0,
        }


async def run_extraction(
    company_name: str,
    dart_api_key: Optional[str] = None,
    qwen_api_key: Optional[str] = None,
) -> LockupResult:
    """
    Convenience function to run extraction for a single company

    Usage:
        result = await run_extraction("삼성전자")
        for entry in result.entries:
            print(f"{entry.owner}: {entry.amount} shares")
    """
    async with ExtractionPipeline(dart_api_key, qwen_api_key) as pipeline:
        return await pipeline.extract_company(company_name)
