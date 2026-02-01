
from bs4 import BeautifulSoup, Tag
from kb_lockup.extraction.rule_extractor import RuleBasedExtractor
from kb_lockup.core.models import TableCandidate
from datetime import date

def create_mock_table():
    # Creating a table with merged cells (rowspan) and "short" rows
    html = """
    <table>
        <thead>
            <tr>
                <th>구분</th>
                <th>주주명</th>
                <th>회사와의 관계</th>
                <th>매각제한 물량</th>
                <th>매각제한 기간</th>
            </tr>
        </thead>
        <tbody>
            <!-- Row 1: Full row -->
            <tr>
                <td rowspan="2">최대주주등</td>
                <td rowspan="2">홍길동</td>
                <td rowspan="2">대표이사</td>
                <td>100,000</td>
                <td>상장일로부터 1년</td>
            </tr>
            <!-- Row 2: Short row (visually, but in DOM might differ depending on parser, 
                 usually BeautifulSoup sees it as separate TRs but with fewer cells if rowspan is respected 
                 or just fewer cells in the HTML source) -->
            <tr>
                <!-- merged cells omitted -->
                <td>50,000</td>
                <td>상장일로부터 2년</td>
            </tr>
             <!-- Row 3: Another full row -->
            <tr>
                <td>기타주주</td>
                <td>김철수</td>
                <td>임원</td>
                <td>10,000</td>
                <td>1개월</td>
            </tr>
        </tbody>
    </table>
    """
    return html

def verify():
    html = create_mock_table()
    candidate = TableCandidate(
        raw_html=html,
        section_title="락업 테스트",
        lockup_signal=True
    )
    
    extractor = RuleBasedExtractor()
    try:
        entries = extractor.extract_from_candidate(candidate, listing_date=date(2024, 1, 1))
        
        with open("verification_result.txt", "w") as f:
            f.write(f"Extracted {len(entries)} entries:\n")
            for i, entry in enumerate(entries):
                f.write(f"Entry {i+1}: Owner='{entry.owner}', Relation='{getattr(entry, 'relation', 'N/A')}', Amount={entry.amount}, Period={entry.period_months}\n")
    except Exception as e:
        with open("verification_result.txt", "w") as f:
            f.write(f"Error: {str(e)}")

if __name__ == "__main__":
    verify()
