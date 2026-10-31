"""Обход каталога: категории -> страницы листинга -> (опционально) страницы товаров.

Весь каталог обходится по категориям: так категория известна для каждого товара
сразу из листинга, без захода на страницу товара. Число запросов почти то же,
что и при обходе общего листинга `catalogue/page-N.html`.
"""

import difflib
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Protocol

from catalog_parser.http import FetchError
from catalog_parser.models import Book, Category
from catalog_parser.parsers import ParseError, parse_categories, parse_listing, parse_product

logger = logging.getLogger(__name__)

BASE_URL = "https://books.toscrape.com/"


class PageFetcher(Protocol):
    """Всё, что умеет вернуть HTML по URL (HttpClient или заглушка в тестах)."""

    def get_text(self, url: str) -> str: ...


class CategoryNotFoundError(LookupError):
    """Категории с таким названием нет на сайте."""

    def __init__(self, name: str, available: Sequence[str]) -> None:
        self.name = name
        self.suggestions = difflib.get_close_matches(name, available, n=3, cutoff=0.6)
        hint = ""
        if self.suggestions:
            hint = f" Возможно, вы имели в виду: {', '.join(self.suggestions)}."
        super().__init__(
            f"Категория «{name}» не найдена.{hint} Список категорий: --list-categories"
        )


@dataclass(slots=True)
class ScrapeResult:
    """Собранные товары и статистика прогона."""

    books: list[Book] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)  # категории, с которых начат обход
    pages: int = 0  # обработано страниц листинга
    skipped: int = 0  # товаров пропущено из-за ошибок
    failed_pages: int = 0  # страниц листинга, которые не удалось получить
    interrupted: bool = False  # прогон остановлен пользователем (Ctrl+C)


def find_category(categories: Sequence[Category], name: str) -> Category:
    """Ищет категорию по названию без учёта регистра и крайних пробелов."""
    wanted = name.strip().casefold()
    for category in categories:
        if category.name.casefold() == wanted:
            return category
    raise CategoryNotFoundError(name.strip(), [c.name for c in categories])


class CatalogScraper:
    """Собирает товары каталога через переданный `PageFetcher`."""

    def __init__(self, fetcher: PageFetcher, base_url: str = BASE_URL) -> None:
        self._fetcher = fetcher
        self._base_url = base_url
        self._categories: list[Category] | None = None

    def list_categories(self) -> list[Category]:
        """Категории из бокового меню главной страницы (загружаются один раз)."""
        if self._categories is None:
            html = self._fetcher.get_text(self._base_url)
            self._categories = parse_categories(html, self._base_url)
        return self._categories

    def scrape(
        self,
        *,
        category: str | None = None,
        max_pages: int | None = None,
        details: bool = False,
    ) -> ScrapeResult:
        """Обходит одну категорию или весь каталог.

        `max_pages` — общий лимит страниц листинга на прогон. С `details=True`
        для каждого товара загружается его страница (количество на складе, UPC).
        Ctrl+C останавливает обход, уже собранные товары возвращаются.
        """
        categories = self.list_categories()
        targets = [find_category(categories, category)] if category else categories
        result = ScrapeResult()
        try:
            for target in targets:
                if max_pages is not None and result.pages >= max_pages:
                    break
                result.categories.append(target.name)
                self._scrape_category(target, result, max_pages, details)
        except KeyboardInterrupt:
            result.interrupted = True
            logger.warning("Обход прерван пользователем, сохраняю уже собранное")

        if max_pages is not None and result.pages >= max_pages:
            logger.info("Достигнут лимит страниц листинга: --max-pages %d", max_pages)
        return result

    def _scrape_category(
        self, category: Category, result: ScrapeResult, max_pages: int | None, details: bool
    ) -> None:
        url: str | None = category.url
        visited: set[str] = set()
        page_number = 0
        while url is not None and (max_pages is None or result.pages < max_pages):
            if url in visited:
                logger.warning("Ссылка на следующую страницу зациклилась: %s", url)
                return
            visited.add(url)
            page_number += 1
            try:
                page = parse_listing(self._fetcher.get_text(url), url, category=category.name)
            except (FetchError, ParseError) as exc:
                result.failed_pages += 1
                logger.error(
                    "«%s», стр. %d не обработана, категория пропущена: %s",
                    category.name,
                    page_number,
                    exc,
                )
                return

            result.pages += 1
            result.skipped += page.skipped
            for book in page.books:
                if details:
                    detailed = self._with_details(book)
                    if detailed is None:
                        result.skipped += 1
                        continue
                    book = detailed
                result.books.append(book)
            logger.info(
                "«%s», стр. %d: товаров %d (всего собрано %d)",
                category.name,
                page_number,
                len(page.books),
                len(result.books),
            )
            url = page.next_url

    def _with_details(self, book: Book) -> Book | None:
        """Дополняет товар данными его страницы; при ошибке возвращает None."""
        try:
            info = parse_product(self._fetcher.get_text(book.url), book.url)
        except (FetchError, ParseError) as exc:
            logger.warning("Товар «%s» пропущен: не удалось получить детали (%s)", book.title, exc)
            return None
        logger.debug("Детали «%s»: в наличии %s, UPC %s", book.title, info.stock_count, info.upc)
        return replace(
            book,
            in_stock=info.in_stock,
            stock_count=info.stock_count,
            upc=info.upc,
            category=book.category or info.category or "",
        )
