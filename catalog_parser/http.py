"""HTTP-клиент: общий httpx.Client, таймауты, свой User-Agent, пауза между запросами, повторы."""

import logging
import time
from collections.abc import Callable
from types import TracebackType
from typing import Self

import httpx

from catalog_parser import __version__

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = f"catalog-parser-excel/{__version__} (demo scraper; +https://books.toscrape.com)"
DEFAULT_TIMEOUT = 15.0
DEFAULT_BACKOFF = 1.0
MAX_BACKOFF = 30.0


class FetchError(Exception):
    """Страницу не удалось получить: ответ 4xx или исчерпаны все попытки."""

    def __init__(self, url: str, reason: str) -> None:
        super().__init__(f"{url}: {reason}")
        self.url = url
        self.reason = reason


def is_retryable_status(status_code: int) -> bool:
    """Повторяем запрос при перегрузке (429) и ошибках сервера (5xx)."""
    return status_code == 429 or status_code >= 500


def _parse_retry_after(response: httpx.Response) -> float | None:
    """Значение заголовка Retry-After в секундах (формат с датой не поддерживаем)."""
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


class HttpClient:
    """Синхронный клиент для вежливого обхода сайта.

    - один httpx.Client на весь прогон (keep-alive, общие заголовки и таймауты);
    - пауза `delay` секунд между началом соседних запросов;
    - `retries` повторов с экспоненциальной задержкой при сетевых ошибках,
      таймаутах и ответах 5xx/429 (всего попыток: retries + 1);
    - ответы 4xx (кроме 429) не повторяются.

    `transport`, `sleep` и `clock` подменяются в тестах.
    """

    def __init__(
        self,
        *,
        delay: float = 0.5,
        retries: int = 3,
        timeout: float = DEFAULT_TIMEOUT,
        backoff: float = DEFAULT_BACKOFF,
        max_backoff: float = MAX_BACKOFF,
        user_agent: str = DEFAULT_USER_AGENT,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if delay < 0:
            raise ValueError("delay не может быть отрицательным")
        if retries < 0:
            raise ValueError("retries не может быть отрицательным")
        self._delay = delay
        self._retries = retries
        self._backoff = backoff
        self._max_backoff = max_backoff
        self._sleep = sleep
        self._clock = clock
        self._last_request_at: float | None = None
        self.requests_made = 0
        self._client = httpx.Client(
            headers={"User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml"},
            timeout=httpx.Timeout(timeout),
            follow_redirects=True,
            transport=transport,
            # Сайт отдаёт «Content-Type: text/html» без charset. Читаем строго как UTF-8,
            # иначе «£51.77» превратится в «Â£51.77».
            default_encoding="utf-8",
        )

    def get_text(self, url: str) -> str:
        """GET-запрос с повторами; возвращает тело ответа как строку."""
        attempts = self._retries + 1
        reason = ""
        for attempt in range(1, attempts + 1):
            self._wait_politely()
            retry_after: float | None = None
            try:
                response = self._client.get(url)
            except (httpx.InvalidURL, httpx.UnsupportedProtocol) as exc:
                raise FetchError(url, f"некорректный адрес: {exc}") from exc
            except httpx.TransportError as exc:  # таймауты, обрывы соединения, DNS
                reason = f"{type(exc).__name__}: {exc}"
            else:
                if response.is_success:
                    return response.text
                reason = f"HTTP {response.status_code}"
                if not is_retryable_status(response.status_code):
                    raise FetchError(url, reason)
                retry_after = _parse_retry_after(response)

            if attempt < attempts:
                pause = self._backoff_delay(attempt, retry_after)
                logger.warning(
                    "Попытка %d/%d не удалась (%s): %s. Повтор через %.1f с",
                    attempt,
                    attempts,
                    reason,
                    url,
                    pause,
                )
                self._sleep(pause)

        raise FetchError(url, f"{reason}; попыток: {attempts}")

    def _wait_politely(self) -> None:
        """Выдерживает паузу между запросами и считает их."""
        if self._last_request_at is not None and self._delay > 0:
            remaining = self._delay - (self._clock() - self._last_request_at)
            if remaining > 0:
                self._sleep(remaining)
        self._last_request_at = self._clock()
        self.requests_made += 1

    def _backoff_delay(self, attempt: int, retry_after: float | None) -> float:
        """1, 2, 4, 8... × backoff секунд, но не меньше Retry-After и не больше max_backoff."""
        pause = self._backoff * 2.0 ** (attempt - 1)
        if retry_after is not None:
            pause = max(pause, retry_after)
        return min(pause, self._max_backoff)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
