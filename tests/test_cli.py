"""Разбор аргументов и сквозной прогон main() на фикстурах через httpx.MockTransport."""

import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from openpyxl import load_workbook

from catalog_parser import cli
from catalog_parser.http import HttpClient
from tests.conftest import FIXTURES_DIR

BASE = "https://books.toscrape.com/"
ROUTES = {
    BASE: "index.html",
    BASE + "catalogue/category/books/travel_2/index.html": "category_travel.html",
}
PRODUCT_RE = re.compile(re.escape(BASE) + r"catalogue/[^/]+_\d+/index\.html")
PRODUCT_FIXTURE = "product_a_light_in_the_attic.html"

Handler = Callable[[httpx.Request], httpx.Response]


def fixture_site(request: httpx.Request) -> httpx.Response:
    """Отвечает настоящими страницами из фикстур; остальное — 404."""
    url = str(request.url)
    name = ROUTES.get(url) or (PRODUCT_FIXTURE if PRODUCT_RE.fullmatch(url) else None)
    if name is None:
        return httpx.Response(404)
    return httpx.Response(200, content=(FIXTURES_DIR / name).read_bytes())


@pytest.fixture
def use_site(monkeypatch: pytest.MonkeyPatch) -> Callable[[Handler], None]:
    """Подменяет HttpClient в cli на клиент с MockTransport и без реальных пауз."""

    def _use(handler: Handler) -> None:
        def factory(**kwargs: Any) -> HttpClient:
            transport = httpx.MockTransport(handler)
            return HttpClient(transport=transport, sleep=lambda _: None, **kwargs)

        monkeypatch.setattr(cli, "HttpClient", factory)

    return _use


def test_defaults() -> None:
    args = cli.parse_args([])

    assert args.category is None
    assert args.list_categories is False
    assert args.max_pages is None
    assert args.details is False
    assert args.output is None
    assert args.delay == 0.5
    assert args.retries == 3
    assert args.log_level == "INFO"
    assert args.log_file == Path("logs/parser.log")


def test_all_options() -> None:
    args = cli.parse_args(
        [
            "--category", "Travel", "--max-pages", "2", "--details",
            "--output", "out/books.xlsx", "--delay", "0", "--retries", "5",
            "--timeout", "30", "--log-level", "debug",
        ]
    )  # fmt: skip

    assert args.category == "Travel"
    assert args.max_pages == 2
    assert args.details is True
    assert args.output == Path("out/books.xlsx")
    assert args.delay == 0.0
    assert args.retries == 5
    assert args.timeout == 30.0
    assert args.log_level == "DEBUG"


@pytest.mark.parametrize(
    "argv",
    [
        ["--max-pages", "0"],
        ["--max-pages", "two"],
        ["--retries", "-1"],
        ["--delay", "-0.5"],
        ["--timeout", "0"],
        ["--log-level", "VERBOSE"],
        ["--output", "books.csv"],
        ["--category", "Travel", "--list-categories"],
    ],
)
def test_invalid_arguments_exit_with_code_2(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as error:
        cli.parse_args(argv)
    assert error.value.code == 2


def test_default_output_path_contains_date() -> None:
    path = cli.default_output_path(datetime(2026, 10, 31, 12, 0, 5))
    assert path == Path("output") / "books_2026-10-31_12-00-05.xlsx"


def test_main_end_to_end_without_network(tmp_path: Path, use_site: Callable[..., None]) -> None:
    use_site(fixture_site)
    output = tmp_path / "travel.xlsx"
    log_file = tmp_path / "logs" / "parser.log"

    code = cli.main(
        ["--category", "Travel", "--details", "--output", str(output),
         "--delay", "0", "--log-file", str(log_file)]
    )  # fmt: skip

    assert code == cli.EXIT_OK
    ws = load_workbook(output)["Товары"]
    assert ws.max_row == 1 + 11
    assert ws["B2"].value == "Travel"
    assert ws["F2"].value == 22  # количество со страницы товара
    log_text = log_file.read_text(encoding="utf-8")
    assert "Готово: товаров 11" in log_text


def test_main_lists_categories(
    tmp_path: Path, use_site: Callable[..., None], capsys: pytest.CaptureFixture[str]
) -> None:
    use_site(fixture_site)

    code = cli.main(["--list-categories", "--log-file", str(tmp_path / "parser.log")])

    out = capsys.readouterr().out
    assert code == cli.EXIT_OK
    assert "  1. Travel" in out
    assert "Всего категорий: 50" in out


def test_main_unknown_category_fails(
    tmp_path: Path, use_site: Callable[..., None], caplog: pytest.LogCaptureFixture
) -> None:
    use_site(fixture_site)

    code = cli.main(["--category", "Cooking", "--log-file", str(tmp_path / "parser.log")])

    assert code == cli.EXIT_ERROR
    assert "Категория «Cooking» не найдена" in caplog.text


def test_main_site_down_fails_gracefully(
    tmp_path: Path, use_site: Callable[..., None], caplog: pytest.LogCaptureFixture
) -> None:
    use_site(lambda request: httpx.Response(503))
    output = tmp_path / "never.xlsx"

    code = cli.main(
        ["--retries", "1", "--output", str(output), "--log-file", str(tmp_path / "parser.log")]
    )

    assert code == cli.EXIT_ERROR
    assert not output.exists()
    assert "HTTP 503" in caplog.text
