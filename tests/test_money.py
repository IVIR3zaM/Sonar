import pytest

from sonar.money import parse_basis_points, parse_cents, parse_signed_cents


class TestParseCents:
    @pytest.mark.parametrize(
        "text,expected_cents",
        [
            # Valid: no decimal
            ("240", 24000),
            ("1", 100),
            # Valid: one decimal
            ("240.5", 24050),
            ("1.2", 120),
            # Valid: two decimals
            ("240.50", 24050),
            ("1.23", 123),
            ("0.01", 1),
            # Valid: comma as decimal separator
            ("240,50", 24050),
            ("1,2", 120),
            ("1,23", 123),
            # Valid: with € prefix
            ("€240", 24000),
            ("€240.50", 24050),
            ("€1,23", 123),
            # Valid: with spaces
            (" 240 ", 24000),
            ("  240.50  ", 24050),
            (" € 240 ", 24000),
        ],
        ids=lambda x: f"{x[0]!r}->{x[1]}" if isinstance(x, tuple) else str(x),
    )
    def test_parse_cents_valid(self, text, expected_cents):
        assert parse_cents(text) == expected_cents

    @pytest.mark.parametrize(
        "text",
        [
            # Empty
            "",
            "   ",
            # Thousands separators (more than one decimal separator is invalid)
            "1,234.56",  # comma + dot
            "1.234,56",  # dot + comma
            # Too many decimals
            "240.500",  # 3 decimals
            "1.234",  # 3 decimals
            # Invalid characters
            "abc",
            "240.50.50",  # multiple dots
            "240,50,50",  # multiple commas
            "240.ab",  # non-digit decimal part
            # Zero or negative
            "0",
            "-240",
            "-1.50",
        ],
        ids=lambda x: f"{x!r}",
    )
    def test_parse_cents_invalid(self, text):
        with pytest.raises(ValueError):
            parse_cents(text)


class TestParseBasisPoints:
    @pytest.mark.parametrize(
        "text,expected_bp",
        [
            # Valid: no decimal
            ("3", 300),
            # Valid: one decimal
            ("3.5", 350),
            ("0.99", 99),
            # Valid: two decimals
            ("3.50", 350),
            # Valid: comma as decimal separator
            ("3,50", 350),
            ("3,5", 350),
            # Valid: with % suffix
            ("3%", 300),
            ("3.5%", 350),
            ("3,50%", 350),
            # Valid: with spaces
            (" 3.5 ", 350),
            ("  3.5%  ", 350),
            (" 3,50% ", 350),
        ],
        ids=lambda x: f"{x[0]!r}->{x[1]}" if isinstance(x, tuple) else str(x),
    )
    def test_parse_basis_points_valid(self, text, expected_bp):
        assert parse_basis_points(text) == expected_bp

    @pytest.mark.parametrize(
        "text",
        [
            # Empty
            "",
            "   ",
            # Only percent sign
            "%",
            # Zero or negative
            "0",
            "-1",
            # Invalid characters
            "abc",
            # Too many decimals
            "3.555",
        ],
        ids=lambda x: f"{x!r}",
    )
    def test_parse_basis_points_invalid(self, text):
        with pytest.raises(ValueError):
            parse_basis_points(text)


class TestParseSignedCents:
    @pytest.mark.parametrize(
        "text,expected_cents",
        [
            # Positive, unsigned
            ("12.34", 1234),
            # Negative
            ("-12.34", -1234),
            # Zero, with and without decimals, signed or not
            ("0", 0),
            ("0.00", 0),
            ("-0", 0),
            # Negative with comma decimal separator
            ("-0,5", -50),
            # Negative with surrounding spaces
            (" -1000 ", -100000),
            # Negative with € prefix (sign comes before the currency symbol)
            ("-€5", -500),
        ],
        ids=lambda x: f"{x[0]!r}->{x[1]}" if isinstance(x, tuple) else str(x),
    )
    def test_parse_signed_cents_valid(self, text, expected_cents):
        assert parse_signed_cents(text) == expected_cents

    @pytest.mark.parametrize(
        "text",
        [
            # Empty
            "",
            # Sign with nothing after it
            "-",
            # Doubled sign
            "--5",
            # Invalid characters
            "abc",
            # Too many decimals
            "1.234",
            # Thousands separator (both . and ,)
            "1,234.56",
            "-12.345",
        ],
        ids=lambda x: f"{x!r}",
    )
    def test_parse_signed_cents_invalid(self, text):
        with pytest.raises(ValueError):
            parse_signed_cents(text)
