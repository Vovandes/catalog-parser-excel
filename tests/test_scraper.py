"""Обход категорий и страниц на «фальшивом сайте» из настоящих HTML-фикстур."""

import re
from collections.abc import Callable

import pytest

from catalog_parser.http import FetchError
from catalog_parser.scraper import BASE_URL, CatalogScraper, CategoryNotFoundError

TRAVEL_URL = BASE_URL + "catalogue/category/books/travel_2/index.html"
MYSTERY_URL = BASE_URL + "catalogue/category/books/mystery_3/index.html"
MYSTERY_PAGE_2_URL = BASE_URL + "catalogue/category/books/mystery_3/page-2.html"
PRODUCT_RE = re.compile(re.escape(BASE_URL) + r"catalogue/[^/]+_\d+/index\.html")

Loader = Callable[[str], str]


class FakeSite:
    """PageFetcher без сети: страницы по точному URL, любая страница товара — фикстура."""

    def __init__(self, pages: dict[str, str], product_html: str) -> None:
        self.pages = pages
        self.product_html = product_html
        self.failing: set[str] = set()
        self.interrupt_on: str | None = None
        self.requested: list[str] = []

    def get_text(self, url: str) -> str:
        self.requested.append(url)
        if url == self.interrupt_on:
            raise KeyboardInterrupt
        if url in self.failing:
            raise FetchError(url, "HTTP 500; попыток: 4")
        if url in self.pages:
            return self.pages[url]
        if PRODUCT_RE.fullmatch(url):
            return self.product_html
        raise FetchError(url, "HTTP 404")


@pytest.fixture
def site(load_fixture: Loader) -> FakeSite:
    return FakeSite(
        pages={
            BASE_URL: load_fixture("index.html"),
            TRAVEL_URL: load_fixture("category_travel.html"),
            MYSTERY_URL: load_fixture("category_mystery.html"),
            # Вторая страница Mystery: подойдёт любой листинг без ссылки «next».
            MYSTERY_PAGE_2_URL: load_fixture("category_travel.html"),
        },
        product_html=load_fixture("product_a_light_in_the_attic.html"),
    )


def test_scrape_single_category(site: FakeSite) -> None:
    result = CatalogScraper(site).scrape(category="Travel")

    assert len(result.books) == 11
    assert {b.category for b in result.books} == {"Travel"}
    assert result.pages == 1
    assert result.categories == ["Travel"]
    assert site.requested == [BASE_URL, TRAVEL_URL]


def test_category_name_is_case_insensitive(site: FakeSite) -> None:
    result = CatalogScraper(site).scrape(category="  travel ")
    assert len(result.books) == 11


def test_unknown_category_suggests_close_names(site: FakeSite) -> None:
    with pytest.raises(CategoryNotFoundError, match="Travel") as error:
        CatalogScraper(site).scrape(category="Travle")
    assert error.value.suggestions == ["Travel"]


def test_follows_next_page_link(site: FakeSite) -> None:
    result = CatalogScraper(site).scrape(category="Mystery")

    assert result.pages == 2
    assert len(result.books) == 20 + 11
    assert site.requested[-1] == MYSTERY_PAGE_2_URL


def test_max_pages_limits_listing_pages(site: FakeSite) -> None:
    result = CatalogScraper(site).scrape(category="Mystery", max_pages=1)

    assert result.pages == 1
    assert len(result.books) == 20
    assert MYSTERY_PAGE_2_URL not in site.requested


def test_full_catalog_walks_categories_within_page_budget(site: FakeSite) -> None:
    result = CatalogScraper(site).scrape(max_pages=3)

    assert site.requested == [BASE_URL, TRAVEL_URL, MYSTERY_URL, MYSTERY_PAGE_2_URL]
    assert result.categories == ["Travel", "Mystery"]
    assert [b.category for b in result.books].count("Mystery") == 31
    assert len(result.books) == 42


def test_details_add_stock_count_and_upc(site: FakeSite) -> None:
    result = CatalogScraper(site).scrape(category="Travel", details=True)

    assert len(result.books) == 11
    assert len(site.requested) == 2 + 11  # главная + листинг + 11 страниц товаров
    assert {b.stock_count for b in result.books} == {22}
    assert {b.upc for b in result.books} == {"a897fe39b1053632"}
    assert {b.category for b in result.books} == {"Travel"}


def test_failed_product_is_skipped_and_run_continues(
    site: FakeSite, caplog: pytest.LogCaptureFixture
) -> None:
    broken_url = BASE_URL + "catalogue/its-only-the-himalayas_981/index.html"
    site.failing.add(broken_url)

    result = CatalogScraper(site).scrape(category="Travel", details=True)

    assert len(result.books) == 10
    assert result.skipped == 1
    assert broken_url not in {b.url for b in result.books}
    assert "It's Only the Himalayas" in caplog.text and "пропущен" in caplog.text


def test_failed_listing_page_does_not_stop_catalog(site: FakeSite) -> None:
    result = CatalogScraper(site).scrape()  # у фальшивого сайта есть только 2 из 50 категорий

    assert len(result.categories) == 50
    assert result.failed_pages == 48
    assert len(result.books) == 42


def test_stops_on_next_page_loop(site: FakeSite, caplog: pytest.LogCaptureFixture) -> None:
    site.pages[MYSTERY_PAGE_2_URL] = site.pages[MYSTERY_URL]  # «next» снова ведёт на page-2

    result = CatalogScraper(site).scrape(category="Mystery")

    assert result.pages == 2
    assert "зациклилась" in caplog.text


def test_ctrl_c_keeps_collected_books(site: FakeSite) -> None:
    site.interrupt_on = MYSTERY_URL

    result = CatalogScraper(site).scrape()

    assert result.interrupted is True
    assert len(result.books) == 11  # Travel успели собрать
