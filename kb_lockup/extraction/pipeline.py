"""Extraction pipeline orchestrator"""

import asyncio
from datetime import date
from typing import Optional, List
from dataclasses import dataclass

from loguru import logger

from kb_lockup.config import settings
from kb_lockup.core.models import (
    Company,
    LockupEntry,
    LockupResult,
    ProspectusInfo,
)
from kb_lockup.core.exceptions import ExtractionError
from kb_lockup.dart.api import DartAPI
from kb_lockup.dart.downloader import ProspectusDownloader
from kb_lockup.extraction.table_finder import TableFinder
from kb_lockup.extraction.ai_table_finder import AITableFinder
from kb_lockup.extraction.rule_extractor import RuleBasedExtractor, HybridExtractor
from kb_lockup.storage.database import Database


@dataclass
class ExtractionStats:
    """Statistics from extraction run"""
    companies_processed: int = 0
    documents_processed: int = 0
    tables_found: int = 0
    entries_extracted: int = 0
    ai_extractions: int = 0
    rule_extractions: int = 0
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
        self.use_hybrid = True  # Use hybrid extraction by default

        self._api: Optional[DartAPI] = None
        self._db: Optional[Database] = None
        self._extractor: Optional[HybridExtractor] = None
        self._rule_extractor: Optional[RuleBasedExtractor] = None

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

        # Initialize extractors
        self._rule_extractor = RuleBasedExtractor()

        if self.qwen_api_key:
            self._extractor = HybridExtractor(self.qwen_api_key)
            logger.info("Using hybrid extraction (AI + rules)")
        else:
            logger.info("Using rule-based extraction only (no AI API key)")

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
        Extract lockup data for a single company (aligned with test_lockup_extraction.py)
        """
        logger.info(f"Starting extraction for: {company_name}")

        # Step 1: Find company
        company = await self._find_company(company_name)
        if not company:
            raise ExtractionError(f"Company not found: {company_name}")

        logger.info(f"Found company: {company.corp_name} ({company.corp_code}, stock={company.stock_code})")

        # Step 2: Search for prospectuses
        prospectuses = await self.api.search_prospectuses(
            corp_code=company.corp_code,
            bgn_de=start_date or "20240101",
            end_de=end_date or "20260201",
        )

        if not prospectuses:
            logger.warning(f"No prospectus filings found for {company.corp_name}")
            return LockupResult(company=company, rcept_no="", entries=[], confidence_score=0)

        # Filter to 증권신고서, prioritizing correction filings, exclude problematic types
        targets = [
            p for p in prospectuses 
            if "증권신고서" in p.report_nm 
            and "[발행조건확정]" not in p.report_nm
            and "[첨부정정]" not in p.report_nm
        ]
        targets.sort(key=lambda x: x.rcept_no, reverse=True)
        
        if not targets:
            # Fallback: try 증권신고서 without exclusions
            targets = [p for p in prospectuses if "증권신고서" in p.report_nm]
            targets.sort(key=lambda x: x.rcept_no, reverse=True)
            if not targets:
                logger.warning(f"No 증권신고서 found for {company.corp_name}")
                return LockupResult(company=company, rcept_no="", entries=[], confidence_score=0)

        # Use the most recent valid filing
        target = targets[0]
        logger.info(f"Using: {target.report_nm} ({target.rcept_no})")

        # Check if already processed
        if not force and await self.db.is_prospectus_processed(target.rcept_no):
            logger.info(f"Already processed: {target.rcept_no}, skipping")
            return LockupResult(company=company, rcept_no=target.rcept_no, entries=[], confidence_score=0)

        # Step 3: Download document
        downloader = ProspectusDownloader(self.api)
        content = await downloader.download_document(target.rcept_no)
        logger.info(f"Document: {len(content)} chars")

        # Step 4: AI Table Finding
        ai_finder = AITableFinder()
        tables = ai_finder.find_lockup_tables(content, max_tables=2)
        
        table_method = "ai" if tables else "none"
        self.stats.tables_found += len(tables)

        if not tables:
            logger.warning(f"No lockup tables found in {target.rcept_no}")
            await self.db.mark_prospectus_processed(
                rcept_no=target.rcept_no, corp_code=company.corp_code,
                report_nm=target.report_nm, rcept_dt=target.rcept_dt,
                method="none", tables_found=0,
            )
            return LockupResult(company=company, rcept_no=target.rcept_no, entries=[], confidence_score=0)

        # Step 5: Rule-based extraction from AI-identified tables
        extractor = RuleBasedExtractor()
        all_entries: List[LockupEntry] = []

        for table_tag in tables:
            rows_count = len(table_tag.find_all("tr"))
            logger.info(f"Extracting from table with {rows_count} rows")
            entries = extractor.extract_from_table(table_tag, listing_date=company.listing_date)
            logger.info(f"Got {len(entries)} entries from this table")
            all_entries.extend(entries)

        # Deduplicate
        if all_entries:
            all_entries = self._deduplicate_entries(all_entries)

        self.stats.entries_extracted += len(all_entries)
        self.stats.companies_processed += 1
        self.stats.documents_processed += 1
        if table_method == "ai":
            self.stats.ai_extractions += 1
        else:
            self.stats.rule_extractions += 1

        # Step 6: Save to database (upsert company FIRST for FK)
        await self.db.upsert_company(company)

        if all_entries:
            await self.db.insert_lockup_entries(
                entries=all_entries,
                company_name=company.corp_name,
                stock_code=company.stock_code,
                source_rcept_no=target.rcept_no,
                source_section=tables[0].name if hasattr(tables[0], 'name') else "lockup_table",
                extraction_score=1.0 if table_method == "ai" else 0.5,
            )
            logger.info(f"Inserted {len(all_entries)} entries into database")

        # Mark as processed
        await self.db.mark_prospectus_processed(
            rcept_no=target.rcept_no, corp_code=company.corp_code,
            report_nm=target.report_nm, rcept_dt=target.rcept_dt,
            method=table_method, tables_found=len(tables),
        )

        return LockupResult(
            company=company,
            rcept_no=target.rcept_no,
            section_title=tables[0].name if hasattr(tables[0], 'name') else None,
            entries=all_entries,
            extraction_method=table_method,
            confidence_score=1.0 if all_entries else 0,
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

        # Save company info FIRST to satisfy foreign key constraints
        await self.db.upsert_company(company)

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

        # Extract data using hybrid or rule-based extraction
        entries = []
        confidence = candidates[0].score if candidates else 0
        extraction_method = "none"

        # Try hybrid extraction (AI + rules) first
        if self._extractor and candidates:
            try:
                entries = self._extractor.extract(
                    candidates,
                    context=f"Company: {company.corp_name}, Document: {prospectus.report_nm}",
                    listing_date=company.listing_date,
                )
                extraction_method = "hybrid"
                self.stats.ai_extractions += 1
                logger.info(f"Hybrid extraction: {len(entries)} lockup entries")
            except Exception as e:
                logger.warning(f"Hybrid extraction failed: {e}")

        # Fall back to pure rule-based extraction
        if not entries and self._rule_extractor and candidates:
            try:
                for candidate in candidates:
                    rule_entries = self._rule_extractor.extract_from_candidate(
                        candidate,
                        listing_date=company.listing_date,
                    )
                    entries.extend(rule_entries)
                extraction_method = "rule_based"
                self.stats.rule_extractions += 1
                logger.info(f"Rule-based extraction: {len(entries)} lockup entries")
            except Exception as e:
                logger.error(f"Rule-based extraction failed: {e}")

        # Deduplicate entries by owner
        if entries:
            entries = self._deduplicate_entries(entries)

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
            method=extraction_method,
            tables_found=len(candidates),
        )

        # Company info already saved at start of method
        # await self.db.upsert_company(company)

        return LockupResult(
            company=company,
            rcept_no=prospectus.rcept_no,
            section_title=candidates[0].section_title if candidates else None,
            entries=entries,
            extraction_method=extraction_method,
            confidence_score=confidence,
        )

    def _deduplicate_entries(self, entries: List[LockupEntry]) -> List[LockupEntry]:
        """Remove duplicate entries, keeping the most complete one"""
        seen = {}

        for entry in entries:
            key = entry.owner.lower().strip()

            if key not in seen:
                seen[key] = entry
            else:
                # Keep entry with more data
                existing = seen[key]
                if self._entry_completeness(entry) > self._entry_completeness(existing):
                    seen[key] = entry

        return list(seen.values())

    def _entry_completeness(self, entry: LockupEntry) -> int:
        """Score how complete an entry is"""
        score = 0
        if entry.amount:
            score += 1
        if entry.ratio:
            score += 1
        if entry.release_date:
            score += 2  # More important
        if entry.period_months:
            score += 1
        if entry.remarks:
            score += 0.5
        return score

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
