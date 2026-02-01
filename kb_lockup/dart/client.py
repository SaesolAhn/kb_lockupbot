import requests
import zipfile
import io
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional
from loguru import logger
from kb_lockup.config import settings

class VartClient:
    """
    VART (Volume Analysis & Retrieval Tool) Client for DART.
    """
    
    BASE_URL = "https://opendart.fss.or.kr/api"
    
    def __init__(self):
        self.api_key = settings.dart_api_key
        if not self.api_key:
            logger.warning("DART API Key missing! VART will fail.")
            
    def get_corp_code(self, company_name: str) -> Optional[str]:
        """Finds corp_code for a given company name using cached XML."""
        cache_path = settings.data_dir / "corpcode.xml"
        
        if not cache_path.exists():
            logger.info("Downloading DART corp_code.xml...")
            url = f"{self.BASE_URL}/corpCode.xml"
            params = {"crtfc_key": self.api_key}
            try:
                resp = requests.get(url, params=params)
                if resp.status_code == 200:
                    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                        zf.extract("CORPCODE.xml", settings.data_dir)
                        (settings.data_dir / "CORPCODE.xml").rename(cache_path)
                else:
                    logger.error(f"Failed to download corp_code: {resp.text}")
                    return None
            except Exception as e:
                 logger.error(f"Network error downloading corp_code: {e}")
                 return None
                 
        try:
            tree = ET.parse(cache_path)
            root = tree.getroot()
            for child in root.findall("list"):
                nm = child.find("corp_name").text.strip()
                # Clean up name if needed (sometimes (joo) etc)
                if nm == company_name:
                    return child.find("corp_code").text.strip()
        except Exception as e:
            logger.error(f"Error parsing corp code XML: {e}")
            
        return None

    def fetch_major_shareholders(self, corp_code: str) -> List[Dict]:
        """
        Fetches 'Major Shareholder' status.
        API: /majorShareholder.json
        """
        if not corp_code: return []
        params = {
            "crtfc_key": self.api_key,
            "corp_code": corp_code,
        }
        try:
            resp = requests.get(f"{self.BASE_URL}/majorShareholder.json", params=params)
            data = resp.json()
            
            if data.get("status") != "000":
                # Only log distinct errors
                msg = data.get('message', '')
                if "조회된 데이터가 없습니다" not in msg:
                     logger.warning(f"DART API Error ({corp_code}): {msg}")
                return []
                
            return data.get("list", [])
        except Exception as e:
            logger.error(f"DART API Request failed: {e}")
            return []
