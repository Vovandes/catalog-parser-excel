"""Общие фикстуры тестов. Сеть в тестах запрещена целиком."""

import socket
from collections.abc import Callable
from pathlib import Path
from typing import NoReturn

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Любая попытка открыть сетевое соединение валит тест."""

    def guard(*args: object, **kwargs: object) -> NoReturn:
        raise RuntimeError("Сетевые запросы в тестах запрещены")

    monkeypatch.setattr(socket.socket, "connect", guard)
    monkeypatch.setattr(socket.socket, "connect_ex", guard)
    monkeypatch.setattr(socket, "create_connection", guard)


@pytest.fixture
def load_fixture() -> Callable[[str], str]:
    """Возвращает функцию чтения HTML-фикстуры по имени файла."""

    def _load(name: str) -> str:
        return (FIXTURES_DIR / name).read_text(encoding="utf-8")

    return _load
