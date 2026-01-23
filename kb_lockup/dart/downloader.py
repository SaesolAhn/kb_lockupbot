"""Prospectus document fetcher"""

import asyncio
from datetime import datetime
from typing import List, Optional
from pathlib import Path

from loguru import logger

from kb_lockup.dart.api import DartAPI
from kb_lockup.core.models import Company, ProspectusInfo
from kb_lockup.core.exceptions import DartAPIError


class ProspectusDownloader:
    """Download and manage prospectus documents from DART"""

    def __init__(self, api: DartAPI, cache_dir: Optional[Path] = None):
        self.api = api
        self.cache_dir = cache_dir or Path("data/cache/documents")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    async def find_prospectuses(
        self,
        company: Company,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[ProspectusInfo]:
        """
        Find all prospectus filings for a company

        Args:
            company: Company object with corp_code
            start_date: Start date YYYYMMDD (default: 1 year ago)
            end_date: End date YYYYMMDD (default: today)
        """
        if not start_date:
            # Default to 1 year lookback
            from datetime import timedelta
            start = datetime.now() - timedelta(days=365)
            start_date = start.strftime("%Y%m%d")

        if not end_date:
            end_date = datetime.now().strftime("%Y%m%d")

        logger.info(
            f"Searching prospectuses for {company.corp_name} "
            f"({start_date} ~ {end_date})"
        )

        prospectuses = await self.api.search_prospectuses(
            corp_code=company.corp_code,
            bgn_de=start_date,
            end_de=end_date,
        )

        logger.info(f"Found {len(prospectuses)} prospectus filings")
        return prospectuses

    async def download_document(
        self,
        rcept_no: str,
        use_cache: bool = True,
    ) -> str:
        """
        Download document content

        Args:
            rcept_no: DART receipt number
            use_cache: Whether to use cached content

        Returns:
            Document content as string
        """
        cache_file = self.cache_dir / f"{rcept_no}.xml"

        # Check cache
        if use_cache and cache_file.exists():
            logger.debug(f"Using cached document: {rcept_no}")
            return cache_file.read_text(encoding="utf-8")

        # Download from DART
        logger.info(f"Downloading document: {rcept_no}")
        content = await self.api.get_document_xml(rcept_no)

        # Cache the content
        cache_file.write_text(content, encoding="utf-8")

        return content

    async def download_batch(
        self,
        prospectuses: List[ProspectusInfo],
        concurrency: int = 3,
        delay: float = 1.0,
    ) -> dict:
        """
        Download multiple documents with rate limiting

        Args:
            prospectuses: List of prospectus info
            concurrency: Max concurrent downloads
            delay: Delay between requests in seconds

        Returns:
            Dict mapping rcept_no to content
        """
        results = {}
        semaphore = asyncio.Semaphore(concurrency)

        async def download_one(info: ProspectusInfo):
            async with semaphore:
                try:
                    content = await self.download_document(info.rcept_no)
                    results[info.rcept_no] = content
                except DartAPIError as e:
                    logger.error(f"Failed to download {info.rcept_no}: {e}")
                    results[info.rcept_no] = None
                await asyncio.sleep(delay)

        tasks = [download_one(info) for info in prospectuses]
        await asyncio.gather(*tasks)

        success_count = sum(1 for v in results.values() if v is not None)
        logger.info(f"Downloaded {success_count}/{len(prospectuses)} documents")

        return results

    def clear_cache(self, older_than_days: Optional[int] = None) -> int:
        """
        Clear cached documents

        Args:
            older_than_days: Only clear files older than this many days

        Returns:
            Number of files deleted
        """
        deleted = 0

        for file in self.cache_dir.glob("*.xml"):
            if older_than_days:
                from datetime import timedelta
                age = datetime.now() - datetime.fromtimestamp(file.stat().st_mtime)
                if age < timedelta(days=older_than_days):
                    continue

            file.unlink()
            deleted += 1

        logger.info(f"Cleared {deleted} cached documents")
        return deleted
