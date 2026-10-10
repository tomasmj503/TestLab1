"""Emparejado aproximado de títulos (D2 de DISENO.md).

Casos I01-I06 vienen del plan de medición; las series imitan títulos reales del sitio
("Saga, Volume 5", "Fruits Basket, Vol. 9"), donde un tipeo podría confundir un volumen con otro.
"""
import pytest

from tests.pages import book, make_catalog

TITLES = [
    "A Light in the Attic",
    "Sapiens: A Brief History of Humankind",
    "Sharp Objects",
    "It's Only the Himalayas",
    "The Light of the Fireflies",
    "The Hobbit",
    "The Road to Little Dribbling",
    "Saga, Volume 3 (Saga: Collected Editions #3)",
    "Saga, Volume 5 (Saga: Collected Editions #5)",
    "Fruits Basket, Vol. 7 (Fruits Basket #7)",
    "Fruits Basket, Vol. 9 (Fruits Basket #9)",
    "Good in Bed (Cannie Shapiro #1)",
    "Life",
    "Life of Pi",
    "Dracula",
]
CATALOG = make_catalog({"Books": [book(title, "10.00") for title in TITLES]})


def found(query: str) -> str | None:
    result = CATALOG.find_book(query)
    return result.title if result else None


# ---- I01-I06 ----------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("case", "query", "expected"),
    [
        ("I01", "A Light in the ...", "A Light in the Attic"),
        ("I02", "Sapiens: A Brief History ...", "Sapiens: A Brief History of Humankind"),
        ("I03", "Sharp Objcts", "Sharp Objects"),
        ("I04", "Its Only the Himalyas", "It's Only the Himalayas"),
        ("I05", "The ...", None),  # varios libros empiezan con "The": ambiguo
        ("I06", "Libro que no existe", None),
    ],
)
def test_public_i_cases(case, query, expected):
    assert found(query) == expected, case


# ---- series parecidas: nunca el volumen equivocado --------------------------------------

def test_series_typo_still_picks_the_right_volume():
    assert found("Fruits Baskt, Vol. 9 (Fruits Basket #9)") == "Fruits Basket, Vol. 9 (Fruits Basket #9)"
    assert found("Sagaa, Volume 3 (Saga: Collected Editions #3)") == "Saga, Volume 3 (Saga: Collected Editions #3)"


def test_series_volume_that_does_not_exist_is_not_found_not_a_neighbour():
    # El volumen 8 no existe: queda justo entre el 7 y el 9, así que no se elige ninguno.
    assert found("Fruits Basket, Vol. 8 (Fruits Basket #8)") is None


def test_series_truncation_needs_enough_text_to_be_unique():
    assert found("Saga, Volume 5 ...") == "Saga, Volume 5 (Saga: Collected Editions #5)"
    assert found("Saga, Volume ...") is None
    assert found("Fruits Basket ...") is None


# ---- regla de seguridad: palabra suelta -------------------------------------------------

@pytest.mark.parametrize("query", ["Sharp", "Sapiens", "sharp"])
def test_bare_single_word_is_not_found(query):
    assert found(query) is None


def test_single_word_with_ellipsis_is_a_declared_truncation():
    assert found("Sharp ...") == "Sharp Objects"
    assert found("Sharp…") == "Sharp Objects"  # puntos suspensivos en un solo carácter


def test_single_word_exact_title_still_works():
    assert found("Dracula") == "Dracula"
    assert found("dracula") == "Dracula"


def test_exact_title_wins_even_when_it_is_the_start_of_another():
    assert found("Life") == "Life"
    assert found("Life of") == "Life of Pi"


def test_two_words_are_enough_to_use_the_start():
    assert found("The Light") == "The Light of the Fireflies"


# ---- otros bordes -----------------------------------------------------------------------

@pytest.mark.parametrize("query", ["", "   ", "...", "?!"])
def test_empty_or_punctuation_only_is_not_found(query):
    assert found(query) is None


def test_too_short_queries_are_not_compared_by_similarity():
    assert found("Drakula") is None  # 7 letras: por debajo del mínimo de 8


def test_known_false_positive_gone_cannie_shapiro():
    """Documenta un límite conocido, no un acierto.

    "gone cannie shapiro 1" no es un título real, pero su cola coincide con la de
    "Good in Bed (Cannie Shapiro #1)" y el parecido (0.857) pasa justo el mínimo de 0.85.
    Si se endurece la regla, esta prueba debe cambiar a `is None`.
    """
    assert found("gone cannie shapiro 1") == "Good in Bed (Cannie Shapiro #1)"
