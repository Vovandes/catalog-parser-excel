"""Разбор настоящих страниц сайта из tests/fixtures/."""

from collections.abc import Callable
from decimal import Decimal

import pytest

from catalog_parser.models import Book, Category
from catalog_parser.parsers import (
    ParseError,
    parse_availability,
    parse_categories,
    parse_listing,
    parse_price,
    parse_product,
    parse_rating,
)

BASE = "https://books.toscrape.com/"
INDEX_URL = BASE + "index.html"
PAGE_2_URL = BASE + "catalogue/page-2.html"
TRAVEL_URL = BASE + "catalogue/category/books/travel_2/index.html"
MYSTERY_URL = BASE + "catalogue/category/books/mystery_3/index.html"
MYSTERY_PAGE_2_URL = BASE + "catalogue/category/books/mystery_3/page-2.html"
PRODUCT_URL = BASE + "catalogue/a-light-in-the-attic_1000/index.html"

Loader = Callable[[str], str]


def travel_books(load_fixture: Loader) -> list[Book]:
    return parse_listing(load_fixture("category_travel.html"), TRAVEL_URL).books


@pytest.mark.parametrize(
    ("fixture", "url", "expected"),
    [
        ("index.html", INDEX_URL, 20),
        ("catalogue_page_2.html", PAGE_2_URL, 20),
        ("category_mystery.html", MYSTERY_URL, 20),
        ("category_travel.html", TRAVEL_URL, 11),
    ],
)
def test_books_count_on_page(load_fixture: Loader, fixture: str, url: str, expected: int) -> None:
    page = parse_listing(load_fixture(fixture), url)
    assert len(page.books) == expected
    assert page.skipped == 0


def test_full_title_taken_from_title_attribute(load_fixture: Loader) -> None:
    titles = [book.title for book in parse_listing(load_fixture("index.html"), INDEX_URL).books]

    assert titles[0] == "A Light in the Attic"  # в тексте ссылки: «A Light in the ...»
    assert "Sapiens: A Brief History of Humankind" in titles
    assert not any(title.endswith("...") for title in titles)


def test_html_entities_and_unicode_in_title(load_fixture: Loader) -> None:
    titles = [b.title for b in travel_books(load_fixture)]

    assert titles[0] == "It's Only the Himalayas"  # &#39; в исходнике
    assert "Full Moon over Noah’s Ark: An Odyssey to Mount Ararat and Beyond" in titles


def test_price_is_number_and_currency_is_separate(load_fixture: Loader) -> None:
    book = parse_listing(load_fixture("index.html"), INDEX_URL).books[0]

    assert book.price == Decimal("51.77")
    assert book.currency == "GBP"
    assert book.in_stock is True
    assert book.stock_count is None  # точное количество есть только на странице товара


def test_rating_from_css_class(load_fixture: Loader) -> None:
    ratings = [b.rating for b in travel_books(load_fixture)]

    assert ratings == [2, 4, 3, 2, 3, 2, 1, 4, 1, 3, 5]


@pytest.mark.parametrize(
    ("fixture", "url", "book_url", "image_url"),
    [
        (
            "index.html",
            INDEX_URL,
            BASE + "catalogue/a-light-in-the-attic_1000/index.html",
            BASE + "media/cache/2c/da/2cdad67c44b002e7ead0cc35693c0e8b.jpg",
        ),
        (
            "catalogue_page_2.html",
            PAGE_2_URL,
            BASE + "catalogue/in-her-wake_980/index.html",
            BASE + "media/cache/5d/72/5d72709c6a7a9584a4d1cf07648bfce1.jpg",
        ),
        (
            "category_travel.html",
            TRAVEL_URL,
            BASE + "catalogue/its-only-the-himalayas_981/index.html",
            BASE + "media/cache/27/a5/27a53d0bb95bdd88288eaf66c9230d7e.jpg",
        ),
    ],
)
def test_links_are_absolute(
    load_fixture: Loader, fixture: str, url: str, book_url: str, image_url: str
) -> None:
    books = parse_listing(load_fixture(fixture), url).books

    assert books[0].url == book_url
    assert books[0].image_url == image_url
    assert all(b.url.startswith(BASE) and b.image_url.startswith(BASE) for b in books)


@pytest.mark.parametrize(
    ("fixture", "url", "expected_next"),
    [
        ("index.html", INDEX_URL, BASE + "catalogue/page-2.html"),
        ("catalogue_page_2.html", PAGE_2_URL, BASE + "catalogue/page-3.html"),
        ("category_mystery.html", MYSTERY_URL, MYSTERY_PAGE_2_URL),
        ("category_travel.html", TRAVEL_URL, None),
    ],
)
def test_next_page_url(
    load_fixture: Loader, fixture: str, url: str, expected_next: str | None
) -> None:
    assert parse_listing(load_fixture(fixture), url).next_url == expected_next


def test_listing_assigns_given_category(load_fixture: Loader) -> None:
    books = parse_listing(load_fixture("category_travel.html"), TRAVEL_URL, category="Travel").books
    assert {b.category for b in books} == {"Travel"}


def test_broken_product_is_skipped_with_log(
    load_fixture: Loader, caplog: pytest.LogCaptureFixture
) -> None:
    html = load_fixture("index.html").replace('<p class="price_color">£51.77</p>', "", 1)

    page = parse_listing(html, INDEX_URL)

    assert len(page.books) == 19
    assert page.skipped == 1
    assert "A Light in the Attic" not in [b.title for b in page.books]
    assert "Товар №1" in caplog.text and "пропущен" in caplog.text


def test_parse_categories(load_fixture: Loader) -> None:
    categories = parse_categories(load_fixture("index.html"), INDEX_URL)

    assert len(categories) == 50
    assert categories[0] == Category("Travel", TRAVEL_URL)
    assert categories[1] == Category("Mystery", MYSTERY_URL)
    assert "Books" not in {c.name for c in categories}
    assert "Sequential Art" in {c.name for c in categories}


def test_parse_product_page_details(load_fixture: Loader) -> None:
    details = parse_product(load_fixture("product_a_light_in_the_attic.html"), PRODUCT_URL)

    assert details.upc == "a897fe39b1053632"
    assert details.in_stock is True
    assert details.stock_count == 22
    assert details.category == "Poetry"


def test_parse_product_without_product_block_fails() -> None:
    with pytest.raises(ParseError):
        parse_product("<html><body><p>Not found</p></body></html>", PRODUCT_URL)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("\n    In stock (22 available)\n", (True, 22)),
        ("In stock (1 available)", (True, 1)),
        ("In stock", (True, None)),
        ("Out of stock", (False, 0)),
    ],
)
def test_parse_availability(text: str, expected: tuple[bool, int | None]) -> None:
    assert parse_availability(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("£51.77", (Decimal("51.77"), "GBP")),
        ("£1,234.50", (Decimal("1234.50"), "GBP")),
        ("Â£13.99", (Decimal("13.99"), "GBP")),  # даже если кодировку где-то испортили
        ("€10", (Decimal("10"), "EUR")),
    ],
)
def test_parse_price(text: str, expected: tuple[Decimal, str]) -> None:
    assert parse_price(text) == expected


@pytest.mark.parametrize("text", ["51.77", "£", ""])
def test_parse_price_rejects_garbage(text: str) -> None:
    with pytest.raises(ParseError):
        parse_price(text)


def test_parse_rating_words_and_unknown() -> None:
    assert parse_rating(["star-rating", "One"]) == 1
    assert parse_rating(["star-rating", "Five"]) == 5
    with pytest.raises(ParseError):
        parse_rating(["star-rating", "Zero"])
