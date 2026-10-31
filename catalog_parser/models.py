"""Модели данных: категория, товар и сведения со страницы товара."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Category:
    """Категория каталога и абсолютная ссылка на первую страницу её листинга."""

    name: str
    url: str


@dataclass(frozen=True, slots=True)
class Book:
    """Товар каталога.

    `stock_count` и `upc` есть только на странице товара, поэтому заполняются
    в режиме `--details`; без него остаются None.
    """

    title: str
    price: Decimal
    currency: str  # ISO 4217, например "GBP"
    in_stock: bool
    rating: int  # 1–5
    url: str
    image_url: str
    category: str
    stock_count: int | None = None
    upc: str | None = None


@dataclass(frozen=True, slots=True)
class ProductDetails:
    """Данные, которые есть только на странице товара."""

    upc: str | None
    in_stock: bool
    stock_count: int | None
    category: str | None
