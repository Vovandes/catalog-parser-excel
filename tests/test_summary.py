from decimal import Decimal

import pytest

from catalog_parser.summary import (
    NO_CATEGORY_LABEL,
    TOTAL_LABEL,
    CategorySummary,
    summarize,
    summarize_by_category,
    summarize_total,
)
from tests.factories import make_book, sample_books


def test_summary_by_category_values_and_order() -> None:
    rows = summarize_by_category(sample_books())

    assert rows == [
        # Poetry: 51.77 + 23.88 + 10.00 = 85.65 / 3 = 28.55; рейтинг (3 + 1 + 5) / 3 = 3.0
        CategorySummary("Poetry", 3, Decimal("28.55"), Decimal("10.00"), Decimal("51.77"), 3.0),
        # Travel: (45.17 + 49.43) / 2 = 47.30; рейтинг (2 + 4) / 2 = 3.0
        CategorySummary("Travel", 2, Decimal("47.30"), Decimal("45.17"), Decimal("49.43"), 3.0),
    ]


def test_total_row() -> None:
    total = summarize_total(sample_books())

    assert total == CategorySummary(
        TOTAL_LABEL, 5, Decimal("36.05"), Decimal("10.00"), Decimal("51.77"), 3.0
    )


def test_average_price_is_rounded_half_up() -> None:
    books = [make_book("A", "1.00", 1, "X"), make_book("B", "1.01", 2, "X")]
    assert summarize(books, "X").avg_price == Decimal("1.01")  # 1.005 -> 1.01
    assert summarize(books, "X").avg_rating == 1.5


def test_books_without_category_are_grouped() -> None:
    rows = summarize_by_category([make_book("A", "5.00", 3, "")])
    assert rows[0].category == NO_CATEGORY_LABEL


def test_empty_input() -> None:
    assert summarize_by_category([]) == []
    assert summarize_total([]) is None
    with pytest.raises(ValueError):
        summarize([], "X")
