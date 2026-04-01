"""app.py のユニットテスト."""

from app import COMPANIES, format_oku, format_percent


class TestFormatOku:
    def test_none(self):
        assert format_oku(None) == "N/A"

    def test_small(self):
        assert format_oku(500e8) == "500億円"

    def test_trillion(self):
        assert format_oku(1500e8) == "1.5兆円"

    def test_zero(self):
        assert format_oku(0) == "0億円"


class TestFormatPercent:
    def test_none(self):
        assert format_percent(None) == "N/A"

    def test_normal(self):
        assert format_percent(0.123) == "12.3%"

    def test_zero(self):
        assert format_percent(0) == "0.0%"

    def test_negative(self):
        assert format_percent(-0.05) == "-5.0%"


class TestCompaniesData:
    def test_all_have_required_fields(self):
        for code, meta in COMPANIES.items():
            assert "name" in meta, f"{code} missing name"
            assert "tier" in meta, f"{code} missing tier"
            assert "avg_salary_man" in meta, f"{code} missing avg_salary_man"

    def test_ticker_format(self):
        for code in COMPANIES:
            assert code.endswith(".T"), f"{code} should end with .T"

    def test_salary_reasonable(self):
        for code, meta in COMPANIES.items():
            assert 300 <= meta["avg_salary_man"] <= 3000, (
                f"{code} salary {meta['avg_salary_man']} out of range"
            )
