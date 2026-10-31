"""Повторы, паузы и кодировка HttpClient. Транспорт подменён httpx.MockTransport."""

from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest

from catalog_parser.http import DEFAULT_USER_AGENT, FetchError, HttpClient

URL = "https://books.toscrape.com/index.html"
Handler = Callable[[httpx.Request], httpx.Response]


class FakeClock:
    """Часы и sleep без реального ожидания: sleep сдвигает время вперёд."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def responses(*items: httpx.Response | Exception) -> tuple[Handler, list[httpx.Request]]:
    """Обработчик, отдающий ответы по очереди, и список полученных запросов."""
    queue: Iterator[httpx.Response | Exception] = iter(items)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        item = next(queue)
        if isinstance(item, Exception):
            raise item
        return item

    return handler, seen


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def make_client(clock: FakeClock) -> Iterator[Callable[..., HttpClient]]:
    created: list[HttpClient] = []

    def _make(handler: Handler, **kwargs: Any) -> HttpClient:
        options: dict[str, Any] = {"delay": 0, "retries": 3, "sleep": clock.sleep, "clock": clock}
        options.update(kwargs)
        client = HttpClient(transport=httpx.MockTransport(handler), **options)
        created.append(client)
        return client

    yield _make
    for client in created:
        client.close()


def test_retries_after_500_and_returns_body(
    make_client: Callable[..., HttpClient], clock: FakeClock
) -> None:
    handler, seen = responses(httpx.Response(500), httpx.Response(200, text="ok"))
    client = make_client(handler)

    assert client.get_text(URL) == "ok"
    assert len(seen) == 2
    assert clock.sleeps == [1.0]  # первая экспоненциальная задержка


def test_gives_up_after_all_attempts(
    make_client: Callable[..., HttpClient], clock: FakeClock
) -> None:
    handler, seen = responses(*[httpx.Response(503)] * 4)
    client = make_client(handler, retries=3)

    with pytest.raises(FetchError, match="HTTP 503; попыток: 4"):
        client.get_text(URL)
    assert len(seen) == 4
    assert clock.sleeps == [1.0, 2.0, 4.0]  # экспонента между попытками


def test_retries_network_errors_and_timeouts(make_client: Callable[..., HttpClient]) -> None:
    request = httpx.Request("GET", URL)
    handler, seen = responses(
        httpx.ConnectError("connection refused", request=request),
        httpx.ReadTimeout("timed out", request=request),
        httpx.Response(200, text="ok"),
    )
    client = make_client(handler)

    assert client.get_text(URL) == "ok"
    assert len(seen) == 3


def test_429_respects_retry_after(make_client: Callable[..., HttpClient], clock: FakeClock) -> None:
    handler, _ = responses(
        httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200, text="ok")
    )
    client = make_client(handler)

    assert client.get_text(URL) == "ok"
    assert clock.sleeps == [7.0]


def test_backoff_is_capped(make_client: Callable[..., HttpClient], clock: FakeClock) -> None:
    handler, _ = responses(*[httpx.Response(500)] * 4)
    client = make_client(handler, backoff=10.0, max_backoff=15.0)

    with pytest.raises(FetchError):
        client.get_text(URL)
    assert clock.sleeps == [10.0, 15.0, 15.0]


def test_client_error_is_not_retried(make_client: Callable[..., HttpClient]) -> None:
    handler, seen = responses(httpx.Response(404))
    client = make_client(handler)

    with pytest.raises(FetchError, match="HTTP 404"):
        client.get_text(URL)
    assert len(seen) == 1


def test_sends_custom_user_agent(make_client: Callable[..., HttpClient]) -> None:
    handler, seen = responses(httpx.Response(200, text="ok"))
    make_client(handler).get_text(URL)

    assert seen[0].headers["User-Agent"] == DEFAULT_USER_AGENT
    assert DEFAULT_USER_AGENT.startswith("catalog-parser-excel/")


def test_decodes_utf8_without_charset_header(make_client: Callable[..., HttpClient]) -> None:
    body = "<p class='price_color'>£51.77</p>".encode()
    handler, _ = responses(httpx.Response(200, content=body, headers={"Content-Type": "text/html"}))

    assert "£51.77" in make_client(handler).get_text(URL)


def test_waits_between_requests(make_client: Callable[..., HttpClient], clock: FakeClock) -> None:
    handler, _ = responses(*[httpx.Response(200, text="ok")] * 3)
    client = make_client(handler, delay=0.5)

    client.get_text(URL)  # первый запрос — без паузы
    clock.now += 0.2  # между запросами прошло 0.2 с, ждать осталось 0.3 с
    client.get_text(URL)
    client.get_text(URL)

    assert clock.sleeps == pytest.approx([0.3, 0.5])
    assert client.requests_made == 3


def test_rejects_negative_settings() -> None:
    with pytest.raises(ValueError):
        HttpClient(retries=-1)
    with pytest.raises(ValueError):
        HttpClient(delay=-0.1)
