"""Чистые функции разбора HTML-страниц books.toscrape.com в dataclass-модели.

Функции не ходят в сеть: на вход — HTML и URL страницы, от которого
строятся абсолютные ссылки.
"""

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from catalog_parser.models import Book, Category, ProductDetails

logger = logging.getLogger(__name__)

RATING_WORDS: dict[str, int] = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}
CURRENCY_CODES: dict[str, str] = {"£": "GBP", "€": "EUR", "$": "USD"}

_AMOUNT_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_AVAILABLE_RE = re.compile(r"\((\d+)\s+available\)", re.IGNORECASE)


class ParseError(ValueError):
    """Нужный элемент не найден на странице или имеет неожиданный формат."""


@dataclass(frozen=True, slots=True)
class ListingPage:
    """Результат разбора одной страницы листинга."""

    books: list[Book]
    next_url: str | None
    skipped: int = 0


def parse_price(text: str) -> tuple[Decimal, str]:
    """«£51.77» -> (Decimal("51.77"), "GBP")."""
    currency = next((code for symbol, code in CURRENCY_CODES.items() if symbol in text), None)
    if currency is None:
        raise ParseError(f"не удалось определить валюту в цене {text!r}")
    match = _AMOUNT_RE.search(text)
    if match is None:
        raise ParseError(f"не удалось найти сумму в цене {text!r}")
    try:
        return Decimal(match.group().replace(",", "")), currency
    except InvalidOperation as exc:
        raise ParseError(f"некорректная сумма в цене {text!r}") from exc


def parse_rating(css_classes: Iterable[str]) -> int:
    """Рейтинг из CSS-классов: ["star-rating", "Three"] -> 3."""
    for css_class in css_classes:
        if css_class in RATING_WORDS:
            return RATING_WORDS[css_class]
    raise ParseError(f"рейтинг не найден в классах {list(css_classes)!r}")


def parse_availability(text: str) -> tuple[bool, int | None]:
    """Наличие и количество из текста.

    «In stock (22 available)» -> (True, 22); «In stock» -> (True, None);
    «Out of stock» -> (False, 0).
    """
    normalized = " ".join(text.split()).lower()
    if not normalized:
        raise ParseError("пустой текст наличия")
    in_stock = normalized.startswith("in stock")
    match = _AVAILABLE_RE.search(normalized)
    if match is not None:
        return in_stock, int(match.group(1))
    return in_stock, None if in_stock else 0


def parse_listing(html: str, page_url: str, category: str = "") -> ListingPage:
    """Товары со страницы листинга (каталог или категория) и ссылка на следующую страницу.

    Товар с битой разметкой пропускается с предупреждением в логе, остальные разбираются.
    """
    soup = _make_soup(html)
    books: list[Book] = []
    skipped = 0
    for position, article in enumerate(soup.select("article.product_pod"), start=1):
        try:
            books.append(_parse_product_pod(article, page_url, category))
        except ParseError as exc:
            skipped += 1
            logger.warning("Товар №%d на странице %s пропущен: %s", position, page_url, exc)
    return ListingPage(books=books, next_url=_next_page_url(soup, page_url), skipped=skipped)


def parse_categories(html: str, page_url: str) -> list[Category]:
    """Список категорий из бокового меню (без корневой «Books»)."""
    soup = _make_soup(html)
    links = soup.select("div.side_categories ul.nav-list > li > ul > li > a")
    if not links:
        raise ParseError("список категорий не найден")
    return [
        Category(name=_clean_text(link), url=urljoin(page_url, _attr(link, "href")))
        for link in links
    ]


def parse_product(html: str, page_url: str) -> ProductDetails:
    """UPC, наличие с количеством и категория со страницы товара."""
    soup = _make_soup(html)
    product = _select_one(soup, "article.product_page")

    info: dict[str, str] = {}
    for row in product.select("table tr"):
        header, value = row.find("th"), row.find("td")
        if header is not None and value is not None:
            info[_clean_text(header)] = _clean_text(value)

    availability = info.get("Availability") or _clean_text(
        _select_one(product, "p.availability")
    )
    in_stock, stock_count = parse_availability(availability)

    # Хлебные крошки: Home / Books / <Категория> / <Товар без ссылки>.
    crumbs = soup.select("ul.breadcrumb > li > a")
    category = _clean_text(crumbs[-1]) if len(crumbs) >= 3 else None

    return ProductDetails(
        upc=info.get("UPC") or None,
        in_stock=in_stock,
        stock_count=stock_count,
        category=category,
    )


def _parse_product_pod(article: Tag, page_url: str, category: str) -> Book:
    link = _select_one(article, "h3 a")
    price, currency = parse_price(_clean_text(_select_one(article, "p.price_color")))
    in_stock, stock_count = parse_availability(_clean_text(_select_one(article, "p.availability")))
    image = _select_one(article, "div.image_container img")
    return Book(
        # Текст ссылки обрезан многоточием, полное название — в атрибуте title.
        title=_attr(link, "title"),
        price=price,
        currency=currency,
        in_stock=in_stock,
        rating=parse_rating(_select_one(article, "p.star-rating").get_attribute_list("class")),
        url=urljoin(page_url, _attr(link, "href")),
        image_url=urljoin(page_url, _attr(image, "src")),
        category=category,
        stock_count=stock_count,
    )


def _next_page_url(soup: BeautifulSoup, page_url: str) -> str | None:
    link = soup.select_one("ul.pager li.next a")
    return urljoin(page_url, _attr(link, "href")) if link is not None else None


def _make_soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def _select_one(root: Tag, selector: str) -> Tag:
    found = root.select_one(selector)
    if found is None:
        raise ParseError(f"не найден элемент {selector!r}")
    return found


def _attr(tag: Tag, name: str) -> str:
    value = tag.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ParseError(f"у <{tag.name}> нет атрибута {name!r}")
    return value.strip()


def _clean_text(tag: Tag) -> str:
    return " ".join(tag.get_text().split())
