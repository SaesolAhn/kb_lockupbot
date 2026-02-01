import requests
import xml.etree.ElementTree as ET
from datetime import date
from typing import Optional, Dict

class SeibroClient:
    """
    Client for interacting with the SEIBro (seibro.or.kr) "Unstaking Schedule" (의무보유·보호예수/반환) service.
    """

    BASE_URL = "https://seibro.or.kr/websquare/engine/proworks/callServletService.jsp"
    REFERER_URL = "https://seibro.or.kr/websquare/control.jsp?w2xPath=/IPORTAL/user/company/BIP_CNTS01045V.xml&menuNo=284"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": self.REFERER_URL,
            "Content-Type": "application/xml; charset=UTF-8",
            "Accept": "application/xml"
        })
        # Visit the main page to establish session/cookies
        try:
            self.session.get(self.REFERER_URL)
        except Exception as e:
            # Log but continue, maybe not fatal if stateless
            print(f"Warning: Failed to init session: {e}")

    def fetch_protection_returns(
        self,
        start_date: date,
        end_date: date,
        market_type: Optional[str] = None,
        page: int = 1
    ) -> str:
        """
        Fetches the XML response for the "Return Status" (반환실적) tab.
        """

        # Map readable market types to codes
        # Based on UI inspection
        market_code = "" # Default to empty/All if not specified
        if market_type == "유가증권시장":
            market_code = "11"
        elif market_type == "코스닥시장":
            market_code = "12"
        elif market_type == "코넥스시장":
            market_code = "13"
        elif market_type == "기타비상장":
            market_code = "14"

        start_str = start_date.strftime("%Y%m%d")
        end_str = end_date.strftime("%Y%m%d")

        # Pagination: 15 items per page based on inspection
        page_size = 15
        start_idx = (page - 1) * page_size + 1
        end_idx = page * page_size

        # Construct the XML payload
        # Using <reqParam> as identified by browser inspection
        # Headers must include X-Requested-With

        self.session.headers.update({"X-Requested-With": "XMLHttpRequest"})

        payload = f"""<?xml version="1.0" encoding="UTF-8"?>
<reqParam action="dutySafeBuySkedulPListEL1" task="ksd.safe.bip.cnts.Company.process.DutySafedpAdepoPTask">
    <ISSUCO_CUSTNO value=""/>
    <CALTOT_MART_TPCD value="{market_code}"/>
    <DT_TYPE value="1"/>
    <ISSU_TYPE value=""/>
    <DT_TYPE_0 value=""/>
    <DT_TYPE_1 value="1"/>
    <FIRST_SAFEDP_DT1 value=""/>
    <FIRST_SAFEDP_DT2 value=""/>
    <RETURN_DT1 value="{start_str}"/>
    <RETURN_DT2 value="{end_str}"/>
    <START_PAGE value="{start_idx}"/>
    <END_PAGE value="{end_idx}"/>
</reqParam>"""

        response = self.session.post(self.BASE_URL, data=payload.encode("utf-8"))
        response.raise_for_status()

        return response.text

    def get_total_count(
        self,
        start_date: date,
        end_date: date,
        market_type: Optional[str] = None
    ) -> int:
        """
        Fetches the total count of records for the given criteria.
        Uses action="dutySafeBuySkedulListCntEL1".
        """
        market_code = "99"
        if market_type == "유가증권시장":
            market_code = "11"
        elif market_type == "코스닥시장":
            market_code = "12"
        elif market_type == "코넥스시장":
            market_code = "13"
        elif market_type == "기타비상장":
            market_code = "14"

        start_str = start_date.strftime("%Y%m%d")
        end_str = end_date.strftime("%Y%m%d")

        payload = f"""<?xml version="1.0" encoding="UTF-8"?>
<request>
    <action>dutySafeBuySkedulListCntEL1</action>
    <task>ksd.safe.bip.cnts.Company.process.DutySafedpAdepoPTask</task>
    <CALTOT_MART_TPCD value="{market_code}">
        <key>{market_code}</key>
    </CALTOT_MART_TPCD>
    <WT_ISSCO_NM value=""/>
    <DT_TYPE_0 value=""/>
    <DT_TYPE_1 value="1"/>
    <FIRST_SAFEDP_DT1 value=""/>
    <FIRST_SAFEDP_DT2 value=""/>
    <RETURN_DT1 value="{start_str}"/>
    <RETURN_DT2 value="{end_str}"/>
    <W_STD_ISSUE_TPCD value=""/>
</request>"""

        response = self.session.post(self.BASE_URL, data=payload.encode("utf-8"))
        response.raise_for_status()

        # Simple parse to get the count
        try:
            root = ET.fromstring(response.text)
            pass
        except Exception:
            pass

        return response.text  # Temporarily return text to be parsed by the parser module
