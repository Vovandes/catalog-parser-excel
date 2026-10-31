import socket

import pytest

import catalog_parser


def test_package_has_version() -> None:
    assert catalog_parser.__version__.count(".") == 2


def test_network_is_blocked_in_tests() -> None:
    with pytest.raises(RuntimeError, match="запрещены"):
        socket.create_connection(("books.toscrape.com", 443), timeout=1)
