"""
Тесты текстовых утилит. Покрытие критичных регулярок и нормализации.
"""

from teacherfactory.text_utils import (
    COMPETENCY_RE,
    LIST_INTENT_RE,
    SPECIALTY_CODE_RE,
    normalize_code,
    tokenize,
)

# ─── COMPETENCY_RE ────────────────────────────────────────────────────────────


class TestCompetencyRegex:
    def test_finds_standard_ok(self):
        assert COMPETENCY_RE.findall("ОК 01") == ["ОК 01"]

    def test_finds_compact_ok(self):
        assert COMPETENCY_RE.findall("ОК01") == ["ОК01"]

    def test_finds_pk_with_subindex(self):
        assert COMPETENCY_RE.findall("ПК 1.2.3") == ["ПК 1.2.3"]

    def test_finds_multiple_in_one_string(self):
        codes = COMPETENCY_RE.findall("ОК 01, ОК 04, ПК 1.6")
        assert codes == ["ОК 01", "ОК 04", "ПК 1.6"]

    def test_does_not_match_latin_ok(self):
        """Latin 'OK' не должно матчиться — только кириллическое ОК."""
        assert COMPETENCY_RE.findall("OK 01 PK 1.2") == []

    def test_does_not_match_unrelated_text(self):
        assert COMPETENCY_RE.findall("Студенты изучают Python") == []


# ─── LIST_INTENT_RE ──────────────────────────────────────────────────────────


class TestListIntentRegex:
    def test_matches_perechisli(self):
        assert LIST_INTENT_RE.search("перечисли все ОК")

    def test_matches_spisok(self):
        assert LIST_INTENT_RE.search("дай мне список")

    def test_matches_full_question(self):
        assert LIST_INTENT_RE.search("какие дисциплины у направления 09.01.03")

    def test_case_insensitive(self):
        assert LIST_INTENT_RE.search("ПЕРЕЧИСЛИ ВСЁ")

    def test_does_not_match_specific_question(self):
        assert not LIST_INTENT_RE.search("что значит ОК 01")


# ─── SPECIALTY_CODE_RE ───────────────────────────────────────────────────────


class TestSpecialtyCodeRegex:
    def test_matches_standard_code(self):
        m = SPECIALTY_CODE_RE.search("Специальность 09.01.03")
        assert m is not None
        assert m.group() == "09.01.03"

    def test_matches_two_digit_section(self):
        m = SPECIALTY_CODE_RE.search("10.02.05")
        assert m is not None

    def test_does_not_match_date(self):
        """Версии типа 1.2.3 и даты 01.05.26 не должны матчиться."""
        assert SPECIALTY_CODE_RE.search("1.2.3") is None


# ─── tokenize ────────────────────────────────────────────────────────────────


class TestTokenize:
    def test_lowercases(self):
        assert tokenize("ВЕРХ") == ["верх"]

    def test_splits_on_whitespace(self):
        assert tokenize("a b c") == ["a", "b", "c"]

    def test_normalizes_ok_compact(self):
        assert tokenize("ОК01") == tokenize("ОК 01")

    def test_normalizes_pk_with_subindex(self):
        assert tokenize("ПК1.2") == tokenize("ПК 1.2")

    def test_does_not_split_mid_word(self):
        """Слово 'компетенции' не должно разваливаться на буквы."""
        assert tokenize("компетенции") == ["компетенции"]

    def test_empty(self):
        assert tokenize("") == []

    def test_only_whitespace(self):
        assert tokenize("   \n\t ") == []


# ─── normalize_code ──────────────────────────────────────────────────────────


class TestNormalizeCode:
    def test_strips_spaces(self):
        assert normalize_code("ОК 01") == "ОК01"

    def test_idempotent(self):
        assert normalize_code(normalize_code("ОК 01")) == "ОК01"

    def test_preserves_dots_in_pk(self):
        assert normalize_code("ПК 1.2") == "ПК1.2"

    def test_works_on_full_text(self):
        normalized = normalize_code("Указаны ОК 01 и ОК 02")
        assert "ОК01" in normalized
        assert "ОК02" in normalized
