import pytest

from app.catalog import normalize


@pytest.mark.parametrize(
    "written",
    [
        "It's Only the Himalayas",
        "its only the himalayas",
        "  ITS   ONLY the   Himalayas ",
        "It’s Only the Himalayas",  # apóstrofe curvo
        "It's Only, the Himalayas!",
    ],
)
def test_title_variations_collapse_to_same_key(written):
    assert normalize(written) == "its only the himalayas"


def test_accents_are_removed():
    assert normalize("Café Müller Ñandú") == "cafe muller nandu"


def test_ampersand_matches_and():
    assert normalize("Parks & Treasured Sites") == normalize("parks and treasured sites")


def test_hyphen_and_colon_become_spaces_not_glued_words():
    assert normalize("Sapiens: A Brief-History") == "sapiens a brief history"


def test_different_titles_stay_different():
    assert normalize("Sharp Objects") != normalize("Sharp Object")


def test_only_punctuation_gives_empty_key():
    assert normalize("?!...") == ""
