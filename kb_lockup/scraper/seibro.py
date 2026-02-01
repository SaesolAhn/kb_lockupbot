
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional
from loguru import logger
from kb_lockup.db.engine import get_db_session
from kb_lockup.models.orm import SeibroUnstakingSchedule
from sqlalchemy.dialects.sqlite import insert

class SeibroClient:
    URL = "https://seibro.or.kr/websquare/engine/proworks/callServletService.jsp"
    REFERER_URL = "https://seibro.or.kr/websquare/control.jsp?w2xPath=/IPORTAL/user/company/BIP_CNTS01041V.xml&menuNo=285"
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": self.REFERER_URL,
            "Content-Type": "application/xml; charset=UTF-8",
            "Accept": "application/xml",
            "X-Requested-With": "XMLHttpRequest"
        })
        # Init session
        try:
            self.session.get(self.REFERER_URL)
        except Exception as e:
            logger.warning(f"Failed to init session: {e}")

    def fetch_data(self, start_date: date, end_date: date, market_code: str) -> str:
        s_str = start_date.strftime("%Y%m%d")
        e_str = end_date.strftime("%Y%m%d")
        
        # XML Payload
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
    <RETURN_DT1 value="{s_str}"/>
    <RETURN_DT2 value="{e_str}"/>
    <START_PAGE value="1"/>
    <END_PAGE value="1500"/>
</reqParam>"""
        try:
            resp = self.session.post(self.URL, data=payload)
            return resp.text
        except Exception as e:
            logger.error(f"Request failed: {e}")
            return ""

def parse_xml(content: str) -> List[Dict]:
    if not content: return []
    rows = []
    try:
        root = ET.fromstring(content)
        # Handle <vector> root
        vectors = []
        if root.tag == "vector":
            vectors.append(root)
        else:
            vectors = root.findall(".//vector")
            
        for vec in vectors:
            for data in vec.findall("data"):
                # Nested result
                res = data.find("result")
                target = res if res is not None else data
                
                def val(tag): 
                    n = target.find(tag)
                    return n.attrib.get("value") if n is not None else None
                
                short_code = val("SHOTN_ISIN") or val("REP_ISIN_CD")
                if not short_code: continue
                
                rows.append({
                    "short_code": short_code.strip(),
                    "company_name": (val("REP_SECN_NM") or "").strip(),
                    "stock_type": val("SECN_KACD") or "",
                    "issue_type": val("ISSU_FORM") or "",
                    "market_type": val("CALTOT_MART_TPCD") or "",
                    "deposit_date": _parse_date(val("FIRST_SAFEDP_DT")),
                    "deposit_shares": _parse_int(val("SAFEDP_QTY") or val("ORG_NRETURN_QTY")),
                    "return_date": _parse_date(val("RETURN_DT")),
                    "return_shares": _parse_int(val("RETURN_QTY")),
                    "reason": val("DUTY_SAFEDP_RACD") or "",
                    "total_shares": _parse_int(val("ISSU_QTY"))
                })
    except Exception as e:
        logger.error(f"Parse error: {e}")
    return rows

def _parse_date(s):
    if not s: return None
    try: return datetime.strptime(s, "%Y%m%d").date()
    except: return None
    
def _parse_int(s):
    if not s: return 0
    try: return int(s.replace(",",""))
    except: return 0


from kb_lockup.scraper.enrich import Enricher

class SeibroScraper:
    def __init__(self):
        self.enricher = Enricher()

    def run(self, start: date, end: date):
        client = SeibroClient()
        all_data = []
        # KOSPI=11, KOSDAQ=12, KONEX=13 
        for market in ["11", "12", "13"]: 
            # We fetch more pages if needed, but client limits to 1500 per page which is usually enough for a month.
            raw = client.fetch_data(start, end, market)
            data = parse_xml(raw)
            logger.info(f"Market {market}: Found {len(data)} rows")
            all_data.extend(data)
            
        # Enrich
        if all_data:
            logger.info("Enriching data with updated stock prices...")
            all_data = self.enricher.enrich_rows(all_data)
            self.save_to_db(all_data)
            
    def save_to_db(self, rows):
        with get_db_session() as session:
            for r in rows:
                if not r['short_code'] or not r['return_date']: continue
                
                # Check required fields for model
                row_data = {
                    "short_code": r.get('short_code'),
                    "company_name": r.get('company_name'),
                    "stock_type": r.get('stock_type'),
                    "issue_type": r.get('issue_type'),
                    "market_type": r.get('market_type'),
                    "deposit_date": r.get('deposit_date'),
                    "deposit_shares": r.get('deposit_shares'),
                    "return_date": r.get('return_date'),
                    "return_shares": r.get('return_shares'),
                    "reason": r.get('reason'),
                    "total_shares": r.get('total_shares'),
                    "stake_portion_pct": r.get('stake_portion_pct'),
                    "stock_current_price_krw": r.get('stock_current_price_krw'),
                    "current_stake_value_million_krw": r.get('current_stake_value_million_krw')
                }

                stmt = insert(SeibroUnstakingSchedule).values(**row_data)
                do_update = stmt.on_conflict_do_update(
                    index_elements=['short_code', 'return_date', 'deposit_date', 'return_shares'],
                    set_={
                        "company_name": stmt.excluded.company_name,
                        "stock_type": stmt.excluded.stock_type,
                        "market_type": stmt.excluded.market_type,
                        "reason": stmt.excluded.reason,
                        "stake_portion_pct": stmt.excluded.stake_portion_pct,
                        "stock_current_price_krw": stmt.excluded.stock_current_price_krw,
                        "current_stake_value_million_krw": stmt.excluded.current_stake_value_million_krw,
                        "updated_at": datetime.now()
                    }
                )
                session.execute(do_update)
            logger.info(f"Upserted {len(rows)} rows.")

if __name__ == "__main__":
    # Test run: Fetch 3 years from today
    today = date.today()
    end_target = today + timedelta(days=365*3)
    
    s = SeibroScraper()
    # Just run for this month + next 3 years? 
    # The user said "3 years from today". 
    # API might be heavy, but let's default the test to a wider range or just keep test small.
    # But I should update the 'run_daily' logic ideally, which is inside `main.py` -> `scraper/crawler` (which calls `SeibroScraper.run`)
    # Wait, `crawler.py` was removed. `main.py` calls `SeibroScraper.run` directly with CLI args.
    # So I will just update the test block here to reflect capability.
    s.run(today, end_target)
