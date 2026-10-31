"""Выгрузка в Excel: структура листов, оформление и значения."""

from datetime import datetime
from pathlib import Path

import pytest
from openpyxl import load_workbook
from openpyxl.workbook.workbook import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from catalog_parser.excel import (
    PARAMETERS_SHEET,
    PRODUCT_HEADERS,
    PRODUCTS_SHEET,
    SUMMARY_HEADERS,
    SUMMARY_SHEET,
    RunInfo,
    export_to_excel,
    format_duration,
    price_format,
)
from tests.factories import sample_books

RUN = RunInfo(
    started_at=datetime(2026, 10, 31, 12, 0, 0),
    finished_at=datetime(2026, 10, 31, 12, 1, 23),
    command="python -m catalog_parser --category Travel --details",
    parameters={"--category": "Travel", "--details": "да", "--max-pages": "без ограничения"},
    source_url="https://books.toscrape.com/",
    pages=1,
    requests=13,
    skipped=0,
    failed_pages=0,
)


@pytest.fixture
def workbook(tmp_path: Path) -> Workbook:
    path = export_to_excel(sample_books(), tmp_path / "out" / "books.xlsx", RUN)
    assert path.exists()
    return load_workbook(path)


def sheet(workbook: Workbook, name: str) -> Worksheet:
    ws = workbook[name]
    assert isinstance(ws, Worksheet)
    return ws


def row_values(ws: Worksheet, row: int) -> list[object]:
    return [cell.value for cell in ws[row]]


def test_workbook_has_three_sheets(workbook: Workbook) -> None:
    assert workbook.sheetnames == [PRODUCTS_SHEET, SUMMARY_SHEET, PARAMETERS_SHEET]


def test_products_header_is_styled(workbook: Workbook) -> None:
    ws = sheet(workbook, PRODUCTS_SHEET)

    assert row_values(ws, 1) == list(PRODUCT_HEADERS)
    header = ws["A1"]
    assert header.font.bold is True
    assert header.fill.fgColor.rgb == "001F4E78"


def test_products_have_filter_and_frozen_header(workbook: Workbook) -> None:
    ws = sheet(workbook, PRODUCTS_SHEET)

    assert ws.freeze_panes == "A2"
    assert ws.auto_filter.ref == "A1:J6"  # шапка + 5 товаров
    assert ws.max_row == 6


def test_product_row_values_and_formats(workbook: Workbook) -> None:
    ws = sheet(workbook, PRODUCTS_SHEET)

    assert row_values(ws, 2)[:8] == [
        "Its Only the Himalayas", "Travel", 45.17, "GBP", "Да", 19, 2, "a2212481",
    ]  # fmt: skip
    assert ws["C2"].number_format == '0.00 "£"'
    assert ws["E6"].value == "Нет"
    url = "https://books.toscrape.com/catalogue/its-only-the-himalayas_1/index.html"
    assert ws["I2"].value == url
    assert ws["I2"].hyperlink is not None and ws["I2"].hyperlink.target == url
    assert ws["J2"].hyperlink is not None


def test_conditional_formatting_for_rating_and_stock(workbook: Workbook) -> None:
    ws = sheet(workbook, PRODUCTS_SHEET)
    ranges = {str(rule_range.sqref) for rule_range in ws.conditional_formatting}

    assert {"G2:G6", "E2:E6", "F2:F6"} <= ranges


def test_columns_are_sized_by_content(workbook: Workbook) -> None:
    ws = sheet(workbook, PRODUCTS_SHEET)
    widths = {letter: ws.column_dimensions[letter].width for letter in "ABDI"}

    assert widths["A"] > widths["D"]  # название шире кода валюты
    assert widths["I"] <= 60  # длинные ссылки ограничены по ширине
    assert widths["D"] >= 8


def test_summary_sheet_values(workbook: Workbook) -> None:
    ws = sheet(workbook, SUMMARY_SHEET)

    assert row_values(ws, 1) == list(SUMMARY_HEADERS)
    assert row_values(ws, 2) == ["Poetry", 3, 28.55, 10, 51.77, 3]
    assert row_values(ws, 3) == ["Travel", 2, 47.3, 45.17, 49.43, 3]
    assert row_values(ws, 4) == ["Итого", 5, 36.05, 10, 51.77, 3]
    assert ws["A4"].font.bold is True
    assert ws["C2"].number_format == '0.00 "£"'


def test_summary_sheet_header_filter_and_freeze(workbook: Workbook) -> None:
    ws = sheet(workbook, SUMMARY_SHEET)

    assert ws["A1"].font.bold is True
    assert ws.freeze_panes == "A2"
    assert ws.auto_filter.ref == "A1:F3"  # итоговая строка не попадает под фильтр


def test_parameters_sheet(workbook: Workbook) -> None:
    ws = sheet(workbook, PARAMETERS_SHEET)
    params = {row[0]: row[1] for row in ws.iter_rows(min_row=2, values_only=True)}

    assert params["Дата запуска"] == datetime(2026, 10, 31, 12, 0, 0)
    assert params["Время работы"] == "1 мин 23.0 с"
    assert params["Параметр --category"] == "Travel"
    assert params["Команда запуска"] == RUN.command
    assert params["Товаров собрано"] == 5
    assert params["Категорий"] == 2
    assert params["HTTP-запросов"] == 13


def test_empty_export_still_valid(tmp_path: Path) -> None:
    path = export_to_excel([], tmp_path / "empty.xlsx", RUN)
    wb = load_workbook(path)

    assert sheet(wb, PRODUCTS_SHEET).max_row == 1
    assert sheet(wb, SUMMARY_SHEET).max_row == 1


@pytest.mark.parametrize(
    ("currency", "expected"), [("GBP", '0.00 "£"'), ("EUR", '0.00 "€"'), ("XXX", "0.00")]
)
def test_price_format(currency: str, expected: str) -> None:
    assert price_format(currency) == expected


def test_format_duration() -> None:
    assert format_duration(5.25) == "5.2 с"
    assert format_duration(125.0) == "2 мин 5.0 с"
