from datetime import datetime, date
from typing import List, Dict, Optional, Any
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
import re

def parse_protection_table(content: str) -> List[Dict[str, Any]]:
    """
    Parses the response from SEIBro.
    It attempts to parse as XML first (API response), and falls back to HTML table parsing (if raw page).

    Args:
        content: Raw string content (XML or HTML).

    Returns:
        List of dictionaries with parsed data.
    """
    if not content:
        return []

    # Try XML parsing first (API response style)
    if content.strip().startswith("<?xml") or "<vector" in content:
        try:
            return _parse_xml_data(content)
        except ET.ParseError:
            pass

    # Fallback to HTML parsing
    return _parse_html_table(content)

def _parse_xml_data(xml_content: str) -> List[Dict[str, Any]]:
    """Parses the WebSquare XML data format."""
    rows = []
    try:
        root = ET.fromstring(xml_content)

        vectors = root.findall(".//vector")

        # If root IS the vector (common in direct XML response)
        if root.tag == "vector":
            vectors.append(root)

        for vec in vectors:
             for data_node in vec.findall("data"):
                 row = _extract_xml_row(data_node)
                 if row:
                     rows.append(row)

    except Exception as e:
        # Log error in production
        print(f"XML Parsing error: {e}")
        pass

    return rows

def _extract_xml_row(data_node: ET.Element) -> Optional[Dict[str, Any]]:
    """Extracts a single row from XML data node."""

    # Handle nested <result> tag if present (common in WebSquare)
    result_node = data_node.find("result")
    search_node = result_node if result_node is not None else data_node

    # Helper to get value directly from child tag
    def get_val(tag_name):
        node = search_node.find(tag_name)
        return node.attrib.get("value") if node is not None else None

    # Short Code: SHOTN_ISIN observed in response
    short_code = get_val("SHOTN_ISIN") or get_val("REP_ISIN_CD") or get_val("STD_SHRT_ISIN_CD") or get_val("ISIN_CD")
    if not short_code: return None

    # Company Name: REP_SECN_NM observed
    company_name = get_val("REP_SECN_NM") or get_val("ISSCO_NM") or get_val("KOR_SECN_NM")

    # Dates
    deposit_date_str = get_val("FIRST_SAFEDP_DT") or get_val("WRT_EXPT_DT")
    return_date_str = get_val("RETURN_DT") or get_val("DERE_DT")

    # Shares
    deposit_shares_str = get_val("SAFEDP_QTY") or get_val("ORG_NRETURN_QTY") or get_val("WRT_EXPT_SHR_CNT")

    return_shares_str = get_val("RETURN_QTY") or get_val("DERE_SHR_CNT")

    total_shares_str = get_val("ISSU_QTY") or get_val("TOT_ISSUE_QTY") or get_val("LIST_SHR_CNT")

    if not company_name or not return_date_str:
        return None

    return {
        "short_code": short_code.strip(),
        "company_name": company_name.strip(),
        "stock_type": get_val("SECN_KACD") or get_val("SECN_KND_NM") or "",
        "issue_type": get_val("ISSU_FORM") or get_val("ISS_FORM_NM") or "",
        "market_type": get_val("CALTOT_MART_TPCD") or get_val("CALTOT_MART_TP_NM") or get_val("MART_TP_NM") or "",
        "deposit_date": _parse_date(deposit_date_str),
        "deposit_shares": _parse_int(deposit_shares_str),
        "return_date": _parse_date(return_date_str),
        "return_shares": _parse_int(return_shares_str),
        "reason": get_val("DUTY_SAFEDP_RACD") or get_val("SAFEDP_RSN_NM") or get_val("DERE_RSN_CN") or "",
        "total_shares": _parse_int(total_shares_str)
    }

def _parse_html_table(html_content: str) -> List[Dict[str, Any]]:
    """Parses HTML table using BeautifulSoup as per user instruction."""
    soup = BeautifulSoup(html_content, 'html.parser')
    rows = []

    # Locate table by header content
    target_table = None
    for table in soup.find_all('table'):
        text = table.get_text()
        if "단축코드" in text and "반환주식수" in text:
            target_table = table
            break

    if not target_table:
        return []

    # Skip header and parse rows
    trs = target_table.find_all('tr')
    for tr in trs:
        tds = tr.find_all('td')
        if not tds:
            continue

        # Helper to get text safely
        def txt(idx):
            if idx < len(tds):
                return tds[idx].get_text(strip=True)
            return ""

        # Verify it's not a header row
        if "단축코드" in txt(0):
            continue

        try:
            row_data = {
                "short_code": txt(0),
                "company_name": txt(1),
                "stock_type": txt(2),
                "issue_type": txt(3),
                "market_type": txt(4),
                "deposit_date": _parse_date(txt(5)),
                "deposit_shares": _parse_int(txt(6)),
                "return_date": _parse_date(txt(7)),
                "return_shares": _parse_int(txt(8)),
                "reason": txt(9),
                "total_shares": _parse_int(txt(10))
            }
            rows.append(row_data)
        except Exception:
            continue

    return rows

def _parse_date(date_str: Optional[str]) -> Optional[date]:
    if not date_str:
        return None
    date_str = date_str.strip()
    # Handle YYYY/MM/DD or YYYYMMDD
    try:
        if "/" in date_str:
            return datetime.strptime(date_str, "%Y/%m/%d").date()
        if len(date_str) == 8 and date_str.isdigit():
            return datetime.strptime(date_str, "%Y%m%d").date()
    except ValueError:
        pass
    return None

def _parse_int(num_str: Optional[str]) -> Optional[int]:
    if not num_str:
        return None
    try:
        clean = num_str.replace(",", "").strip()
        if not clean: return None
        return int(clean)
    except ValueError:
        return None
