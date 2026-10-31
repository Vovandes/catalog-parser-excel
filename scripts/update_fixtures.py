"""Скачивает настоящие HTML-страницы books.toscrape.com в tests/fixtures/.

Запускается вручную и редко: тесты работают только с сохранёнными копиями.

    python scripts/update_fixtures.py
"""

import time
from pathlib import Path

import httpx

BASE_URL = "https://books.toscrape.com/"
FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

# имя файла фикстуры -> путь страницы на сайте
PAGES: dict[str, str] = {
    "index.html": "index.html",
    "catalogue_page_2.html": "catalogue/page-2.html",
    "category_travel.html": "catalogue/category/books/travel_2/index.html",
    "category_mystery.html": "catalogue/category/books/mystery_3/index.html",
    "product_a_light_in_the_attic.html": "catalogue/a-light-in-the-attic_1000/index.html",
}


def main() -> None:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": "catalog-parser-excel fixtures updater"}
    with httpx.Client(base_url=BASE_URL, headers=headers, timeout=20.0) as client:
        for filename, path in PAGES.items():
            response = client.get(path)
            response.raise_for_status()
            # Сохраняем байты как есть, без перекодирования.
            (FIXTURES_DIR / filename).write_bytes(response.content)
            content_type = response.headers.get("content-type")
            print(f"{filename}: {len(response.content)} байт, {content_type}")
            time.sleep(0.5)


if __name__ == "__main__":
    main()
