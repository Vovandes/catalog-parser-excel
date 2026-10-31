"""Агрегаты по категориям для листа «Сводка по категориям»."""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from catalog_parser.models import Book

TOTAL_LABEL = "Итого"
NO_CATEGORY_LABEL = "Без категории"
_CENT = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class CategorySummary:
    """Строка сводки: число товаров, цены и средний рейтинг."""

    category: str
    count: int
    avg_price: Decimal
    min_price: Decimal
    max_price: Decimal
    avg_rating: float


def summarize(books: Sequence[Book], label: str) -> CategorySummary:
    """Сводка по непустому набору товаров."""
    if not books:
        raise ValueError("нельзя построить сводку по пустому списку товаров")
    prices = [book.price for book in books]
    count = len(books)
    return CategorySummary(
        category=label,
        count=count,
        avg_price=(sum(prices, Decimal(0)) / count).quantize(_CENT, rounding=ROUND_HALF_UP),
        min_price=min(prices),
        max_price=max(prices),
        avg_rating=round(sum(book.rating for book in books) / count, 2),
    )


def summarize_by_category(books: Sequence[Book]) -> list[CategorySummary]:
    """Сводка по каждой категории: сначала самые крупные, при равенстве — по алфавиту."""
    groups: dict[str, list[Book]] = defaultdict(list)
    for book in books:
        groups[book.category or NO_CATEGORY_LABEL].append(book)
    rows = [summarize(items, name) for name, items in groups.items()]
    return sorted(rows, key=lambda row: (-row.count, row.category.casefold()))


def summarize_total(books: Sequence[Book]) -> CategorySummary | None:
    """Итоговая строка по всем товарам (None, если товаров нет)."""
    return summarize(books, TOTAL_LABEL) if books else None
