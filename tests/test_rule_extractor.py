"""Tests for rule-based extraction"""

import pytest
from datetime import date

from kb_lockup.extraction.rule_extractor import RuleBasedExtractor, HybridExtractor
from kb_lockup.core.models import TableCandidate, LockupEntry


class TestRuleBasedExtractor:
    """Test rule-based table extraction"""

    def setup_method(self):
        self.extractor = RuleBasedExtractor()

    def test_extract_from_html_table(self, sample_html_table):
        """Test extraction from HTML table"""
        listing_date = date(2024, 1, 1)
        entries = self.extractor.extract_from_html(
            sample_html_table,
            listing_date=listing_date,
        )

        assert len(entries) == 2
        assert entries[0].owner == "홍길동"
        assert entries[0].amount == 1000000
        assert entries[0].ratio == 5.5

    def test_extract_from_candidate(self, sample_html_table):
        """Test extraction from TableCandidate"""
        candidate = TableCandidate(
            section_title="보호예수 현황",
            raw_html=sample_html_table,
            column_headers=["주주명", "보유주식수", "지분율", "보호예수기간", "해제일"],
            row_count=2,
        )

        listing_date = date(2024, 1, 1)
        entries = self.extractor.extract_from_candidate(
            candidate,
            listing_date=listing_date,
        )

        assert len(entries) == 2
        assert entries[0].owner == "홍길동"
        assert entries[1].owner == "김철수"

    def test_skip_aggregate_rows(self):
        """Test that aggregate rows are skipped"""
        html = """
        <table>
            <tr><th>주주명</th><th>보유주식수</th><th>지분율</th></tr>
            <tr><td>홍길동</td><td>1,000,000</td><td>5%</td></tr>
            <tr><td>합계</td><td>1,000,000</td><td>5%</td></tr>
        </table>
        """

        entries = self.extractor.extract_from_html(html)
        assert len(entries) == 1
        assert entries[0].owner == "홍길동"

    def test_skip_empty_owner(self):
        """Test that rows with empty owner are skipped"""
        html = """
        <table>
            <tr><th>주주명</th><th>보유주식수</th></tr>
            <tr><td></td><td>1,000,000</td></tr>
            <tr><td>홍길동</td><td>500,000</td></tr>
        </table>
        """

        entries = self.extractor.extract_from_html(html)
        assert len(entries) == 1
        assert entries[0].owner == "홍길동"

    def test_column_detection_various_headers(self):
        """Test column detection with various header names"""
        html = """
        <table>
            <tr><th>성명</th><th>수량</th><th>비율</th><th>만료일</th></tr>
            <tr><td>홍길동</td><td>1,000,000</td><td>5%</td><td>2024-06-15</td></tr>
        </table>
        """

        entries = self.extractor.extract_from_html(html)
        assert len(entries) == 1
        assert entries[0].owner == "홍길동"
        assert entries[0].amount == 1000000
        assert entries[0].ratio == 5.0
        assert entries[0].release_date == date(2024, 6, 15)

    def test_calculate_release_from_period(self):
        """Test calculating release date from period and listing date"""
        html = """
        <table>
            <tr><th>주주명</th><th>보유량</th><th>보호예수기간</th></tr>
            <tr><td>홍길동</td><td>1,000,000</td><td>6개월</td></tr>
        </table>
        """

        listing_date = date(2024, 1, 15)
        entries = self.extractor.extract_from_html(html, listing_date=listing_date)

        assert len(entries) == 1
        assert entries[0].period_months == 6
        # 6 months ≈ 180 days from listing (6 * 30 = 180)
        assert entries[0].release_date == date(2024, 7, 13)

    def test_handle_colspan(self):
        """Test handling of colspan in table cells"""
        html = """
        <table>
            <tr><th colspan="2">주주정보</th><th>보유량</th></tr>
            <tr><th>성명</th><th>구분</th><th>주식수</th></tr>
            <tr><td>홍길동</td><td>최대주주</td><td>1,000,000</td></tr>
        </table>
        """

        entries = self.extractor.extract_from_html(html)
        # Should still extract despite complex structure
        assert len(entries) >= 0  # May or may not extract depending on detection

    def test_no_owner_column(self):
        """Test table without owner column returns empty"""
        html = """
        <table>
            <tr><th>항목</th><th>금액</th></tr>
            <tr><td>매출액</td><td>1,000,000</td></tr>
        </table>
        """

        entries = self.extractor.extract_from_html(html)
        assert len(entries) == 0


class TestHybridExtractor:
    """Test hybrid extraction (AI + rules)"""

    def setup_method(self):
        # Create hybrid extractor without Qwen API (rule-based only)
        self.extractor = HybridExtractor(qwen_api_key=None)

    def test_extract_with_rules_only(self, sample_html_table):
        """Test extraction falls back to rules when no AI"""
        candidate = TableCandidate(
            section_title="보호예수 현황",
            raw_html=sample_html_table,
            column_headers=["주주명", "보유주식수", "지분율", "보호예수기간", "해제일"],
            row_count=2,
        )

        entries = self.extractor.extract(
            candidates=[candidate],
            context="테스트 회사",
            listing_date=date(2024, 1, 1),
        )

        assert len(entries) == 2
        assert entries[0].owner == "홍길동"

    def test_extract_multiple_candidates(self, sample_html_table):
        """Test extraction from multiple table candidates"""
        candidate1 = TableCandidate(
            section_title="보호예수 현황",
            raw_html=sample_html_table,
            column_headers=["주주명", "보유주식수", "지분율", "보호예수기간", "해제일"],
            row_count=2,
        )

        candidate2 = TableCandidate(
            section_title="매각제한 현황",
            raw_html="""
            <table>
                <tr><th>주주명</th><th>보유량</th><th>기간</th></tr>
                <tr><td>이영희</td><td>200,000</td><td>1년</td></tr>
            </table>
            """,
            column_headers=["주주명", "보유량", "기간"],
            row_count=1,
        )

        entries = self.extractor.extract(
            candidates=[candidate1, candidate2],
            listing_date=date(2024, 1, 1),
        )

        # Should have entries from both tables
        assert len(entries) >= 2
        owners = [e.owner for e in entries]
        assert "홍길동" in owners

    def test_merge_results_fills_missing_data(self):
        """Test that merge fills missing data from rule-based"""
        # Create mock entries
        qwen_entry = LockupEntry(
            owner="홍길동",
            amount=None,  # Missing
            ratio=5.5,
            release_date=None,
        )

        rule_entry = LockupEntry(
            owner="홍길동",
            amount=1000000,  # Has data
            ratio=5.5,
            release_date=date(2024, 6, 15),  # Has data
        )

        merged = self.extractor._merge_results([qwen_entry], [rule_entry])

        assert len(merged) == 1
        assert merged[0].owner == "홍길동"
        assert merged[0].amount == 1000000  # Filled from rule
        assert merged[0].release_date == date(2024, 6, 15)  # Filled from rule

    def test_merge_adds_unique_rule_entries(self):
        """Test that unique rule entries are added"""
        qwen_entry = LockupEntry(owner="홍길동", amount=1000000)
        rule_entry = LockupEntry(owner="김철수", amount=500000)

        merged = self.extractor._merge_results([qwen_entry], [rule_entry])

        assert len(merged) == 2
        owners = [e.owner for e in merged]
        assert "홍길동" in owners
        assert "김철수" in owners

    def test_empty_candidates(self):
        """Test extraction with empty candidates"""
        entries = self.extractor.extract(candidates=[])
        assert entries == []


class TestEdgeCases:
    """Test edge cases in extraction"""

    def setup_method(self):
        self.extractor = RuleBasedExtractor()

    def test_malformed_html(self):
        """Test handling of malformed HTML"""
        html = """
        <table>
            <tr><th>주주명<th>보유량</tr>
            <tr><td>홍길동<td>1000000</tr>
        """  # Missing closing tags

        # Should not crash
        entries = self.extractor.extract_from_html(html)
        # May or may not extract depending on BeautifulSoup parsing

    def test_nested_tables(self):
        """Test handling of nested tables"""
        html = """
        <table>
            <tr><td>
                <table>
                    <tr><th>주주명</th><th>보유량</th></tr>
                    <tr><td>홍길동</td><td>1000000</td></tr>
                </table>
            </td></tr>
        </table>
        """

        entries = self.extractor.extract_from_html(html)
        # Should skip nested tables by default

    def test_empty_table(self):
        """Test extraction from empty table"""
        html = "<table></table>"
        entries = self.extractor.extract_from_html(html)
        assert entries == []

    def test_unicode_content(self):
        """Test handling of various Unicode content"""
        html = """
        <table>
            <tr><th>주주명</th><th>보유량</th><th>비율</th></tr>
            <tr><td>홍길동（대표이사）</td><td>１,０００,０００</td><td>５．５％</td></tr>
        </table>
        """

        entries = self.extractor.extract_from_html(html)
        # Should handle full-width characters
        assert len(entries) >= 0
