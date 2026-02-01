"""DART OpenAPI client with rate limiting and retry logic"""

import asyncio
from datetime import datetime, date
from typing import Optional, List
import time

import httpx
from loguru import logger
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from kb_lockup.config import settings
from kb_lockup.core.models import Company, ProspectusInfo
from kb_lockup.core.exceptions import DartAPIError, RateLimitError, DocumentNotFoundError


class RateLimiter:
    """Simple rate limiter for API calls"""

    def __init__(self, max_calls: int, period: float = 1.0):
        """
        Args:
            max_calls: Maximum calls allowed per period
            period: Time period in seconds
        """
        self.max_calls = max_calls
        self.period = period
        self._calls: List[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until a call is allowed"""
        async with self._lock:
            now = time.monotonic()

            # Remove old calls outside the window
            self._calls = [t for t in self._calls if now - t < self.period]

            if len(self._calls) >= self.max_calls:
                # Wait until oldest call expires
                sleep_time = self.period - (now - self._calls[0])
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
                self._calls = self._calls[1:]

            self._calls.append(time.monotonic())


class DartAPI:
    """
    DART OpenAPI client for:
    - Company list retrieval
    - Document search
    - Document content fetch
    """

    BASE_URL = "https://opendart.fss.or.kr/api"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.dart_api_key
        if not self.api_key:
            raise ValueError("DART API key is required")

        self._client: Optional[httpx.AsyncClient] = None
        self._corp_codes: Optional[dict] = None
        self._corp_codes_by_stock: Optional[dict] = None

        # Rate limiter: ~10 requests per second (conservative for daily limit)
        self._rate_limiter = RateLimiter(max_calls=10, period=1.0)
        self._request_count = 0

    async def __aenter__(self):
        self._client = httpx.AsyncClient(timeout=settings.dart_timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._client:
            await self._client.aclose()

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("DartAPI must be used as async context manager")
        return self._client

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.RequestError, httpx.HTTPStatusError)),
        reraise=True,
    )
    async def _request(self, endpoint: str, params: dict) -> dict:
        """Make API request with rate limiting, retry logic, and error handling"""
        # Apply rate limiting
        await self._rate_limiter.acquire()

        params["crtfc_key"] = self.api_key
        url = f"{self.BASE_URL}/{endpoint}"

        try:
            self._request_count += 1
            logger.debug(f"DART API request #{self._request_count}: {endpoint}")

            response = await self.client.get(url, params=params)
            response.raise_for_status()

            # Handle different response types
            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type:
                data = response.json()

                # Check DART API status codes
                status = data.get("status")
                if status == "013":
                    # 조회된 데이타가 없습니다 - No data found
                    logger.debug(f"No data found for {endpoint}")
                    return {"list": []}
                elif status == "010":
                    raise DocumentNotFoundError(params.get("rcept_no", "unknown"))
                elif status == "020":
                    # 요청 제한을 초과하였습니다 - Rate limit exceeded
                    logger.warning("DART API rate limit exceeded")
                    raise RateLimitError()
                elif status and status != "000":
                    raise DartAPIError(
                        f"DART API error: {data.get('message', 'Unknown error')}",
                        status_code=int(status),
                        response=str(data),
                    )
                return data
            else:
                # Binary response (ZIP files)
                return {"content": response.content}

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error {e.response.status_code} for {endpoint}")
            raise DartAPIError(
                f"HTTP error: {e.response.status_code}",
                status_code=e.response.status_code,
            )
        except httpx.RequestError as e:
            logger.error(f"Request error for {endpoint}: {e}")
            raise DartAPIError(f"Request error: {str(e)}")

    async def load_corp_codes(self) -> dict:
        """Load corporation code list from DART"""
        if self._corp_codes is not None:
            return self._corp_codes

        import zipfile
        import io
        import xml.etree.ElementTree as ET

        logger.info("Loading DART corporation codes...")
        response = await self._request("corpCode.xml", {})

        # Response is a ZIP file containing corpCode.xml
        with zipfile.ZipFile(io.BytesIO(response["content"])) as zf:
            with zf.open("CORPCODE.xml") as f:
                tree = ET.parse(f)
                root = tree.getroot()

        self._corp_codes = {}
        self._corp_codes_by_stock = {}

        for item in root.findall("list"):
            corp_code = item.findtext("corp_code")
            corp_name = item.findtext("corp_name")
            stock_code = item.findtext("stock_code")
            stock_code = stock_code.strip() if stock_code and stock_code.strip() else None

            if corp_code and corp_name:
                data = {
                    "corp_code": corp_code,
                    "corp_name": corp_name,
                    "stock_code": stock_code,
                }
                self._corp_codes[corp_name] = data

                # Also index by stock code for faster lookup
                if stock_code:
                    self._corp_codes_by_stock[stock_code] = data

        listed_count = len(self._corp_codes_by_stock)
        logger.info(f"Loaded {len(self._corp_codes)} corporations ({listed_count} listed)")
        return self._corp_codes

    async def get_corp_code(self, company_name: str) -> Optional[Company]:
        """Find corporation by name (exact or fuzzy match)"""
        corp_codes = await self.load_corp_codes()

        # Exact match first
        if company_name in corp_codes:
            data = corp_codes[company_name]
            return Company(
                corp_code=data["corp_code"],
                corp_name=data["corp_name"],
                stock_code=data["stock_code"],
            )

        # Fuzzy match - contains
        matches = [
            (name, data)
            for name, data in corp_codes.items()
            if company_name in name or name in company_name
        ]

        if matches:
            # Return best match (shortest name containing query)
            name, data = min(matches, key=lambda x: len(x[0]))
            return Company(
                corp_code=data["corp_code"],
                corp_name=data["corp_name"],
                stock_code=data["stock_code"],
            )

        return None

    async def get_corp_by_stock_code(self, stock_code: str) -> Optional[Company]:
        """Find corporation by stock code (fast indexed lookup)"""
        await self.load_corp_codes()

        # Normalize stock code (pad with zeros if needed)
        stock_code = stock_code.strip().zfill(6)

        data = self._corp_codes_by_stock.get(stock_code)
        if data:
            return Company(
                corp_code=data["corp_code"],
                corp_name=data["corp_name"],
                stock_code=data["stock_code"],
            )
        return None

    async def get_company_info(self, corp_code: str) -> Optional[dict]:
        """
        Get detailed company information

        Returns dict with: corp_name, stock_code, ceo_nm, corp_cls,
        adres, hm_url, ir_url, phn_no, fax_no, est_dt, acc_mt
        """
        try:
            data = await self._request("company.json", {"corp_code": corp_code})
            return data
        except DartAPIError as e:
            if "010" in str(e):  # No data
                return None
            raise

    async def search_company(self, query: str) -> List[Company]:
        """
        Search companies by name (supports partial matching)

        Returns list of matching Company objects
        """
        await self.load_corp_codes()

        query_lower = query.lower()
        matches = []

        for name, data in self._corp_codes.items():
            if query_lower in name.lower():
                matches.append(Company(
                    corp_code=data["corp_code"],
                    corp_name=data["corp_name"],
                    stock_code=data["stock_code"],
                ))

        # Sort by relevance (exact match first, then by name length)
        matches.sort(key=lambda c: (
            0 if c.corp_name.lower() == query_lower else 1,
            len(c.corp_name),
        ))

        return matches[:20]  # Limit results

    async def search_prospectuses(
        self,
        corp_code: str,
        bgn_de: Optional[str] = None,
        end_de: Optional[str] = None,
    ) -> List[ProspectusInfo]:
        """
        Search for 증권신고서 (prospectus) filings

        Args:
            corp_code: DART corporation code
            bgn_de: Start date (YYYYMMDD)
            end_de: End date (YYYYMMDD)
        """
        params = {
            "corp_code": corp_code,
            "pblntf_ty": "C",  # 발행공시 (증권신고서)
        }

        if bgn_de:
            params["bgn_de"] = bgn_de
        else:
            # Default to 3 years lookback if not specified
            from datetime import timedelta
            params["bgn_de"] = (date.today() - timedelta(days=1095)).strftime("%Y%m%d")

        if end_de:
            params["end_de"] = end_de

        data = await self._request("list.json", params)

        results = []
        for item in data.get("list", []):
            try:
                results.append(
                    ProspectusInfo(
                        rcept_no=item["rcept_no"],
                        corp_code=corp_code,
                        report_nm=item["report_nm"],
                        rcept_dt=datetime.strptime(item["rcept_dt"], "%Y%m%d").date(),
                    )
                )
            except (KeyError, ValueError) as e:
                logger.warning(f"Skipping malformed prospectus item: {e}")

        return results

    async def get_document(self, rcept_no: str) -> bytes:
        """Download document as ZIP file"""
        response = await self._request("document.xml", {"rcept_no": rcept_no})
        return response["content"]

    async def get_document_xml(self, rcept_no: str, doc_index: int = 0) -> str:
        """
        Get document as parsed XML/HTML content

        Args:
            rcept_no: DART receipt number
            doc_index: Index of document in ZIP (0 = main document)
        """
        import zipfile
        import io

        content = await self.get_document(rcept_no)

        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            names = zf.namelist()
            if not names:
                raise DocumentNotFoundError(rcept_no)

            # Find XML/HTML file
            target_file = None
            for name in names:
                if name.endswith((".xml", ".html", ".htm")):
                    if doc_index == 0:
                        target_file = name
                        break
                    doc_index -= 1

            if not target_file:
                target_file = names[0]

            with zf.open(target_file) as f:
                return f.read().decode("utf-8", errors="replace")

    async def search_filings(
        self,
        corp_code: Optional[str] = None,
        bgn_de: Optional[str] = None,
        end_de: Optional[str] = None,
        pblntf_ty: Optional[str] = None,
        last_reprt_at: str = "N",
        page_count: int = 100,
    ) -> List[dict]:
        """
        Search all filings with various filters

        Args:
            corp_code: Filter by corporation (optional)
            bgn_de: Start date YYYYMMDD
            end_de: End date YYYYMMDD
            pblntf_ty: Filing type (A=정기공시, B=주요사항, C=발행공시, etc.)
            last_reprt_at: Y=only final reports, N=all
            page_count: Results per page (max 100)
        """
        params = {
            "last_reprt_at": last_reprt_at,
            "page_count": str(page_count),
        }

        if corp_code:
            params["corp_code"] = corp_code
        if bgn_de:
            params["bgn_de"] = bgn_de
        if end_de:
            params["end_de"] = end_de
        if pblntf_ty:
            params["pblntf_ty"] = pblntf_ty

        data = await self._request("list.json", params)
        return data.get("list", [])

    async def get_ipo_prospectuses(
        self,
        bgn_de: Optional[str] = None,
        end_de: Optional[str] = None,
    ) -> List[ProspectusInfo]:
        """
        Search for IPO-related prospectus filings across all companies

        Args:
            bgn_de: Start date YYYYMMDD (default: 1 year ago)
            end_de: End date YYYYMMDD (default: today)
        """
        from datetime import timedelta

        if not bgn_de:
            bgn_de = (date.today() - timedelta(days=365)).strftime("%Y%m%d")
        if not end_de:
            end_de = date.today().strftime("%Y%m%d")

        # Search for 증권신고서(지분증권) filings
        params = {
            "bgn_de": bgn_de,
            "end_de": end_de,
            "pblntf_ty": "I",  # 발행공시
            "page_count": "100",
        }

        data = await self._request("list.json", params)

        results = []
        for item in data.get("list", []):
            # Filter for IPO-related reports
            report_nm = item.get("report_nm", "")
            if "증권신고서" in report_nm and "지분증권" in report_nm:
                try:
                    results.append(
                        ProspectusInfo(
                            rcept_no=item["rcept_no"],
                            corp_code=item.get("corp_code", ""),
                            report_nm=report_nm,
                            rcept_dt=datetime.strptime(item["rcept_dt"], "%Y%m%d").date(),
                        )
                    )
                except (KeyError, ValueError) as e:
                    logger.warning(f"Skipping malformed item: {e}")

        logger.info(f"Found {len(results)} IPO prospectuses")
        return results

    @property
    def request_count(self) -> int:
        """Get total number of API requests made"""
        return self._request_count
