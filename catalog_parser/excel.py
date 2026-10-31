"""Выгрузка в Excel: листы «Товары», «Сводка по категориям» и «Параметры»."""

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook
from openpyxl.cell.cell import Cell, MergedCell
from openpyxl.formatting.rule import CellIsRule, ColorScaleRule, FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from catalog_parser.models import Book
from catalog_parser.summary import CategorySummary, summarize_by_category, summarize_total

type CellValue = str | int | float | Decimal | datetime | None

PRODUCTS_SHEET = "Товары"
SUMMARY_SHEET = "Сводка по категориям"
PARAMETERS_SHEET = "Параметры"

PRODUCT_HEADERS = (
    "Название",
    "Категория",
    "Цена",
    "Валюта",
    "В наличии",
    "Количество, шт.",
    "Рейтинг",
    "UPC",
    "Ссылка на товар",
    "Изображение",
)
SUMMARY_HEADERS = (
    "Категория",
    "Товаров",
    "Средняя цена",
    "Мин. цена",
    "Макс. цена",
    "Средний рейтинг",
)
PARAMETERS_HEADERS = ("Параметр", "Значение")

CURRENCY_SYMBOLS: dict[str, str] = {"GBP": "£", "EUR": "€", "USD": "$"}
DATETIME_FORMAT = "DD.MM.YYYY HH:MM:SS"
RATING_FORMAT = "0.00"
YES, NO = "Да", "Нет"
LOW_STOCK = 5  # остаток, начиная с которого количество подсвечивается

_THIN = Side(style="thin", color="D9D9D9")
_CELL_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_HEADER_FONT = Font(bold=True, color="FFFFFF")
_HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
_HEADER_ALIGNMENT = Alignment(horizontal="center", vertical="center", wrap_text=True)
_TOTAL_FONT = Font(bold=True)
_TOTAL_FILL = PatternFill("solid", fgColor="DDEBF7")
_TOTAL_BORDER = Border(
    top=Side(style="medium", color="1F4E78"), bottom=_THIN, left=_THIN, right=_THIN
)
_GOOD_FILL = PatternFill("solid", fgColor="C6EFCE")
_GOOD_FONT = Font(color="006100")
_BAD_FILL = PatternFill("solid", fgColor="FFC7CE")
_BAD_FONT = Font(color="9C0006")
_WARN_FILL = PatternFill("solid", fgColor="FFEB9C")
_WARN_FONT = Font(color="9C5700")

_MIN_WIDTH = 8
_MAX_WIDTH = 60
_HEADER_PADDING = 4  # кнопка автофильтра в шапке
_BOLD_FACTOR = 1.2  # жирный шрифт шапки шире обычного


@dataclass(frozen=True, slots=True)
class RunInfo:
    """Сведения о прогоне для листа «Параметры»."""

    started_at: datetime
    finished_at: datetime
    command: str
    parameters: Mapping[str, str]  # «--category» -> «Travel» и т. д.
    source_url: str
    pages: int
    requests: int
    skipped: int
    failed_pages: int
    interrupted: bool = False

    @property
    def duration_seconds(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()


def price_format(currency: str) -> str:
    """Числовой формат Excel для цены: GBP -> `0.00 "£"`."""
    symbol = CURRENCY_SYMBOLS.get(currency)
    return f'0.00 "{symbol}"' if symbol else "0.00"


def format_duration(seconds: float) -> str:
    """83.4 -> «1 мин 23.4 с»."""
    minutes, rest = divmod(seconds, 60)
    return f"{int(minutes)} мин {rest:.1f} с" if minutes else f"{rest:.1f} с"


def export_to_excel(books: Sequence[Book], path: Path, run: RunInfo) -> Path:
    """Сохраняет товары, сводку и параметры прогона в .xlsx и возвращает путь к файлу."""
    workbook = Workbook()
    products = workbook.active
    assert products is not None  # у нового Workbook всегда есть активный лист
    products.title = PRODUCTS_SHEET
    _fill_products(products, books)
    _fill_summary(workbook.create_sheet(SUMMARY_SHEET), books)
    _fill_parameters(workbook.create_sheet(PARAMETERS_SHEET), books, run)

    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)
    return path


def _fill_products(ws: Worksheet, books: Sequence[Book]) -> None:
    _write_header(ws, PRODUCT_HEADERS)
    for row, book in enumerate(books, start=2):
        cells = _write_row(
            ws,
            row,
            (
                book.title,
                book.category,
                book.price,
                book.currency,
                YES if book.in_stock else NO,
                book.stock_count,
                book.rating,
                book.upc,
                book.url,
                book.image_url,
            ),
        )
        cells[2].number_format = price_format(book.currency)
        for cell in cells[3:7]:
            cell.alignment = Alignment(horizontal="center")
        for cell in cells[8:10]:
            _make_hyperlink(cell)

    last_row = max(len(books) + 1, 2)
    ws.auto_filter.ref = f"A1:{get_column_letter(len(PRODUCT_HEADERS))}{last_row}"
    ws.freeze_panes = "A2"

    # Рейтинг: красный (1) -> жёлтый (3) -> зелёный (5).
    ws.conditional_formatting.add(
        f"G2:G{last_row}",
        ColorScaleRule(
            start_type="num", start_value=1, start_color="F8696B",
            mid_type="num", mid_value=3, mid_color="FFEB84",
            end_type="num", end_value=5, end_color="63BE7B",
        ),
    )  # fmt: skip
    # Наличие: «Да» зелёным, «Нет» красным.
    ws.conditional_formatting.add(
        f"E2:E{last_row}",
        CellIsRule(operator="equal", formula=[f'"{YES}"'], fill=_GOOD_FILL, font=_GOOD_FONT),
    )
    ws.conditional_formatting.add(
        f"E2:E{last_row}",
        CellIsRule(operator="equal", formula=[f'"{NO}"'], fill=_BAD_FILL, font=_BAD_FONT),
    )
    # Мало на складе (только когда количество известно, т. е. в режиме --details).
    ws.conditional_formatting.add(
        f"F2:F{last_row}",
        FormulaRule(
            formula=[f"AND(ISNUMBER(F2),F2<={LOW_STOCK})"], fill=_WARN_FILL, font=_WARN_FONT
        ),
    )
    # Название и ссылки бывают очень длинными: ограничиваем ширину, значение в ячейке полное.
    _autosize_columns(ws, max_widths={1: 50, 9: 32, 10: 32})


def _fill_summary(ws: Worksheet, books: Sequence[Book]) -> None:
    _write_header(ws, SUMMARY_HEADERS)
    currencies = {book.currency for book in books}
    money = price_format(currencies.pop()) if len(currencies) == 1 else "0.00"

    rows = summarize_by_category(books)
    for row_number, summary in enumerate(rows, start=2):
        _write_summary_row(ws, row_number, summary, money)

    last_data_row = max(len(rows) + 1, 2)
    ws.auto_filter.ref = f"A1:{get_column_letter(len(SUMMARY_HEADERS))}{last_data_row}"
    ws.freeze_panes = "A2"

    total = summarize_total(books)
    if total is not None:
        for cell in _write_summary_row(ws, len(rows) + 2, total, money):
            cell.font, cell.fill, cell.border = _TOTAL_FONT, _TOTAL_FILL, _TOTAL_BORDER
    _autosize_columns(ws)


def _write_summary_row(
    ws: Worksheet, row: int, summary: CategorySummary, money: str
) -> list[Cell]:
    cells = _write_row(
        ws,
        row,
        (
            summary.category,
            summary.count,
            summary.avg_price,
            summary.min_price,
            summary.max_price,
            summary.avg_rating,
        ),
    )
    for cell in cells[2:5]:
        cell.number_format = money
    cells[5].number_format = RATING_FORMAT
    return cells


def _fill_parameters(ws: Worksheet, books: Sequence[Book], run: RunInfo) -> None:
    _write_header(ws, PARAMETERS_HEADERS)
    rows: list[tuple[str, CellValue]] = [
        ("Дата запуска", run.started_at),
        ("Дата завершения", run.finished_at),
        ("Время работы", format_duration(run.duration_seconds)),
        ("Статус", "прерван пользователем" if run.interrupted else "завершён"),
        ("Источник", run.source_url),
        ("Команда запуска", run.command),
        *((f"Параметр {name}", value) for name, value in run.parameters.items()),
        ("Товаров собрано", len(books)),
        ("Категорий", len({book.category for book in books})),
        ("Страниц листинга обработано", run.pages),
        ("HTTP-запросов", run.requests),
        ("Товаров пропущено (ошибки)", run.skipped),
        ("Страниц листинга с ошибкой", run.failed_pages),
    ]
    for row_number, (name, value) in enumerate(rows, start=2):
        name_cell, value_cell = _write_row(ws, row_number, (name, value))
        name_cell.font = Font(bold=True)
        value_cell.alignment = Alignment(horizontal="left")
        if isinstance(value, datetime):
            value_cell.number_format = DATETIME_FORMAT
        if name == "Источник":
            _make_hyperlink(value_cell)
    ws.freeze_panes = "A2"
    _autosize_columns(ws, max_widths={2: 90})


def _write_header(ws: Worksheet, headers: Iterable[str]) -> None:
    for column, title in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=column, value=title)
        cell.font, cell.fill, cell.alignment = _HEADER_FONT, _HEADER_FILL, _HEADER_ALIGNMENT
        cell.border = _CELL_BORDER
    ws.row_dimensions[1].height = 30


def _write_row(ws: Worksheet, row: int, values: Sequence[CellValue]) -> list[Cell]:
    """Записывает строку значений с тонкими границами и возвращает её ячейки."""
    cells = [ws.cell(row=row, column=col, value=value) for col, value in enumerate(values, 1)]
    for cell in cells:
        cell.border = _CELL_BORDER
    return cells


def _make_hyperlink(cell: Cell) -> None:
    if isinstance(cell.value, str) and cell.value:
        cell.hyperlink = cell.value
        cell.style = "Hyperlink"
        cell.border = _CELL_BORDER


def _display_length(cell: Cell | MergedCell) -> int:
    """Примерная ширина значения в символах — так, как его покажет Excel."""
    value = cell.value
    if value is None:
        return 0
    if isinstance(value, datetime):
        return len(DATETIME_FORMAT)
    if isinstance(value, Decimal | float) and "0.00" in cell.number_format:
        return len(f"{value:.2f}") + 2
    return max(len(line) for line in str(value).splitlines() or [""])


def _autosize_columns(ws: Worksheet, max_widths: Mapping[int, int] | None = None) -> None:
    """Ширина колонок по содержимому (с ограничением сверху)."""
    limits = max_widths or {}
    for column, column_cells in enumerate(ws.iter_cols(min_row=1, max_row=ws.max_row), start=1):
        header, *data = column_cells
        header_width = math.ceil(_display_length(header) * _BOLD_FACTOR) + _HEADER_PADDING
        longest = max([header_width, *(_display_length(cell) for cell in data)])
        width = min(max(longest + 2, _MIN_WIDTH), limits.get(column, _MAX_WIDTH))
        ws.column_dimensions[get_column_letter(column)].width = width
