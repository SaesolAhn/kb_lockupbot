"""Tests for extraction module"""

import pytest
from datetime import date

from kb_lockup.extraction.table_finder import TableFinder
from kb_lockup.extraction.scorer import TableScorer
from kb_lockup.core.models import TableCandidate


class TestTableScorer:
    """Test table scoring"""

    def setup_method(self):
        self.scorer = TableScorer()

    def test_score_with_strong_keyword(self):
        """Test scoring with primary lockup keyword"""
        candidate = TableCandidate(
            section_title="보호예수 현황",
            raw_html="<table>보호예수 관련 내용</table>",
            column_headers=["주주명", "보유량", "지분율"],
            row_count=5,
        )

        score = self.scorer.score_table(candidate)
        assert score > 0.5
        assert candidate.strong_lockup is True

    def test_score_with_secondary_keyword(self):
        """Test scoring with secondary keyword"""
        candidate = TableCandidate(
            section_title="매도제한 내역",
            raw_html="<table>매도제한</table>",
            column_headers=["성명", "수량"],
            row_count=3,
        )

        score = self.scorer.score_table(candidate)
        assert score > 0.2
        assert candidate.lockup_signal is True

    def test_score_irrelevant_table(self):
        """Test scoring for non-lockup table"""
        candidate = TableCandidate(
            section_title="재무제표",
            raw_html="<table>매출액, 영업이익</table>",
            column_headers=["항목", "금액"],
            row_count=10,
        )

        score = self.scorer.score_table(candidate)
        assert score < 0.3

    def test_is_strong_lockup(self):
        """Test strong lockup detection"""
        # Strong lockup
        candidate1 = TableCandidate(
            section_title="의무보유 현황",
            raw_html="<table>의무보유</table>",
            column_headers=["주주명", "보유량", "해제일"],
            strong_lockup=True,
            lockup_signal=True,
            row_count=5,
        )
        assert self.scorer.is_strong_lockup(candidate1) is True

        # Not strong (missing keywords)
        candidate2 = TableCandidate(
            section_title="주주 현황",
            raw_html="<table>주주 목록</table>",
            column_headers=["성명", "주식수"],
            row_count=5,
        )
        assert self.scorer.is_strong_lockup(candidate2) is False


class TestTableFinder:
    """Test table finding"""

    def test_find_tables_in_html(self, sample_prospectus_content):
        """Test finding tables in HTML content"""
        finder = TableFinder(min_score=0.1)
        candidates = finder.find_lockup_tables(sample_prospectus_content)

        assert len(candidates) > 0

    def test_find_best_table(self, sample_prospectus_content):
        """Test finding the best lockup table"""
        finder = TableFinder(min_score=0.1)
        best = finder.find_best_table(sample_prospectus_content)

        # Should find a table with lockup signal
        assert best is not None
        assert best.lockup_signal or best.strong_lockup

    def test_filter_strong_lockup(self):
        """Test filtering to strong lockup tables only"""
        finder = TableFinder()

        candidates = [
            TableCandidate(
                section_title="보호예수",
                strong_lockup=True,
                lockup_signal=True,
                row_count=5,
            ),
            TableCandidate(
                section_title="일반 표",
                strong_lockup=False,
                lockup_signal=False,
                row_count=10,
            ),
        ]

        filtered = finder.filter_strong_lockup_tables(candidates)
        assert len(filtered) == 1
        assert filtered[0].section_title == "보호예수"


class TestColumnDetection:
    """Test column header detection"""

    def test_detect_owner_column(self):
        """Test detecting owner/shareholder columns"""
        scorer = TableScorer()

        # Test with various owner column names
        for header in ["주주명", "성명", "보유자", "주주"]:
            candidate = TableCandidate(
                section_title="테스트",
                column_headers=[header, "금액"],
                row_count=1,
            )
            score = scorer._score_columns(candidate.column_headers)
            assert score > 0

    def test_detect_amount_column(self):
        """Test detecting share amount columns"""
        scorer = TableScorer()

        for header in ["보유량", "주식수", "수량", "보유주식수"]:
            candidate = TableCandidate(
                section_title="테스트",
                column_headers=["주주", header],
                row_count=1,
            )
            score = scorer._score_columns(candidate.column_headers)
            assert score > 0

    def test_detect_release_date_column(self):
        """Test detecting release date columns"""
        scorer = TableScorer()

        for header in ["해제일", "매각가능일", "만료일"]:
            candidate = TableCandidate(
                section_title="테스트",
                column_headers=["주주", header],
                row_count=1,
            )
            score = scorer._score_columns(candidate.column_headers)
            assert score > 0
