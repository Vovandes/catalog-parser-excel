"""Готовые товары для тестов сводки и выгрузки."""

from decimal import Decimal

from catalog_parser.models import Book

BASE = "https://books.toscrape.com/catalogue/"


def make_book(
    title: str,
    price: str,
    rating: int,
    category: str,
    *,
    in_stock: bool = True,
    stock_count: int | None = None,
    upc: str | None = None,
) -> Book:
    slug = title.lower().replace(" ", "-")
    return Book(
        title=title,
        price=Decimal(price),
        currency="GBP",
        in_stock=in_stock,
        rating=rating,
        url=f"{BASE}{slug}_1/index.html",
        image_url=f"https://books.toscrape.com/media/cache/{slug}.jpg",
        category=category,
        stock_count=stock_count,
        upc=upc,
    )


def sample_books() -> list[Book]:
    """Две категории: Travel (2 товара) и Poetry (3 товара)."""
    return [
        make_book("Its Only the Himalayas", "45.17", 2, "Travel", stock_count=19, upc="a2212481"),
        make_book("Full Moon over Noahs Ark", "49.43", 4, "Travel", stock_count=15, upc="feb7cc77"),
        make_book("A Light in the Attic", "51.77", 3, "Poetry", stock_count=22, upc="a897fe39"),
        make_book("Olio", "23.88", 1, "Poetry", stock_count=3, upc="94b0bb1e"),
        make_book("Out of Print", "10.00", 5, "Poetry", in_stock=False, stock_count=0),
    ]
