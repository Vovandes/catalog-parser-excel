"""Командная строка: `python -m catalog_parser [опции]`."""

import argparse
import io
import logging
import subprocess
import sys
from collections.abc import Sequence
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from catalog_parser import __version__
from catalog_parser.excel import RunInfo, export_to_excel, format_duration
from catalog_parser.http import FetchError, HttpClient
from catalog_parser.parsers import ParseError
from catalog_parser.scraper import BASE_URL, CatalogScraper, CategoryNotFoundError, ScrapeResult

logger = logging.getLogger("catalog_parser")

PROG = "python -m catalog_parser"
DEFAULT_OUTPUT_DIR = Path("output")
DEFAULT_LOG_FILE = Path("logs") / "parser.log"
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
CONSOLE_FORMAT = "%(asctime)s %(levelname)-7s %(message)s"
FILE_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_INTERRUPTED = 130

EPILOG = f"""примеры:
  {PROG} --list-categories
  {PROG} --category "Travel" --details --output docs/example_travel.xlsx
  {PROG} --max-pages 3 --delay 1 --retries 5
"""


def _positive_int(text: str) -> int:
    value = _convert(int, text)
    if value < 1:
        raise argparse.ArgumentTypeError(f"нужно целое число ≥ 1, получено {text!r}")
    return value


def _non_negative_int(text: str) -> int:
    value = _convert(int, text)
    if value < 0:
        raise argparse.ArgumentTypeError(f"нужно целое число ≥ 0, получено {text!r}")
    return value


def _non_negative_float(text: str) -> float:
    value = _convert(float, text)
    if value < 0:
        raise argparse.ArgumentTypeError(f"нужно число ≥ 0, получено {text!r}")
    return value


def _positive_float(text: str) -> float:
    value = _convert(float, text)
    if value <= 0:
        raise argparse.ArgumentTypeError(f"нужно число > 0, получено {text!r}")
    return value


def _convert[T: (int, float)](kind: type[T], text: str) -> T:
    try:
        return kind(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"некорректное число: {text!r}") from None


def _xlsx_path(text: str) -> Path:
    path = Path(text)
    if path.suffix.lower() != ".xlsx":
        raise argparse.ArgumentTypeError(f"файл вывода должен иметь расширение .xlsx: {text!r}")
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Парсер каталога books.toscrape.com с выгрузкой в оформленный Excel.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    target = parser.add_mutually_exclusive_group()
    target.add_argument(
        "--category",
        metavar="НАЗВАНИЕ",
        help='одна категория по названию, например "Travel" (без параметра — весь каталог)',
    )
    target.add_argument(
        "--list-categories", action="store_true", help="вывести список категорий и выйти"
    )
    parser.add_argument(
        "--max-pages", type=_positive_int, metavar="N", help="лимит страниц листинга на прогон"
    )
    parser.add_argument(
        "--details",
        action="store_true",
        help="заходить на страницу каждого товара за точным количеством и UPC",
    )
    parser.add_argument(
        "--output",
        type=_xlsx_path,
        metavar="ФАЙЛ.xlsx",
        help="файл вывода (по умолчанию output/books_<дата>_<время>.xlsx)",
    )
    parser.add_argument(
        "--delay",
        type=_non_negative_float,
        default=0.5,
        metavar="СЕК",
        help="пауза между запросами, секунд (по умолчанию: %(default)s)",
    )
    parser.add_argument(
        "--retries",
        type=_non_negative_int,
        default=3,
        metavar="N",
        help="число повторов при сетевых ошибках, таймаутах, 5xx и 429 (по умолчанию: %(default)s)",
    )
    parser.add_argument(
        "--timeout",
        type=_positive_float,
        default=15.0,
        metavar="СЕК",
        help="таймаут одного запроса, секунд (по умолчанию: %(default)s)",
    )
    parser.add_argument(
        "--log-level",
        type=str.upper,
        choices=LOG_LEVELS,
        default="INFO",
        help="уровень логирования (по умолчанию: %(default)s)",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=DEFAULT_LOG_FILE,
        metavar="ФАЙЛ",
        help="файл лога (по умолчанию: %(default)s)",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def default_output_path(now: datetime) -> Path:
    """output/books_2026-10-31_12-00-05.xlsx — время в имени, чтобы не затирать прошлые прогоны."""
    return DEFAULT_OUTPUT_DIR / f"books_{now:%Y-%m-%d_%H-%M-%S}.xlsx"


def setup_logging(level: str, log_file: Path) -> None:
    """Лог в консоль (stderr) и в файл с ротацией. Повторный вызов заменяет обработчики."""
    close_logging()
    log_file.parent.mkdir(parents=True, exist_ok=True)

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(CONSOLE_FORMAT, datefmt="%H:%M:%S"))
    file_handler = RotatingFileHandler(
        log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter(FILE_FORMAT))

    logger.setLevel(level)
    logger.addHandler(console)
    logger.addHandler(file_handler)


def close_logging() -> None:
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    _make_console_safe()
    setup_logging(args.log_level, args.log_file)
    try:
        with HttpClient(delay=args.delay, retries=args.retries, timeout=args.timeout) as client:
            scraper = CatalogScraper(client)
            if args.list_categories:
                return _print_categories(scraper)
            return _run(args, raw_argv, scraper, client)
    except CategoryNotFoundError as exc:
        logger.error("%s", exc)
        return EXIT_ERROR
    except (FetchError, ParseError) as exc:
        logger.error("Не удалось загрузить главную страницу каталога: %s", exc)
        return EXIT_ERROR
    except KeyboardInterrupt:
        logger.warning("Остановлено пользователем")
        return EXIT_INTERRUPTED
    finally:
        close_logging()


def _run(
    args: argparse.Namespace, raw_argv: list[str], scraper: CatalogScraper, client: HttpClient
) -> int:
    started_at = datetime.now().replace(microsecond=0)
    output: Path = args.output or default_output_path(started_at)
    logger.info(
        "Старт: %s, лимит страниц: %s, детали: %s",
        f"категория «{args.category}»" if args.category else "весь каталог",
        args.max_pages or "нет",
        "да" if args.details else "нет",
    )

    result = scraper.scrape(category=args.category, max_pages=args.max_pages, details=args.details)
    if not result.books:
        logger.error("Не собрано ни одного товара, файл не создан")
        return EXIT_ERROR

    run = RunInfo(
        started_at=started_at,
        finished_at=datetime.now().replace(microsecond=0),
        command=f"{PROG} {subprocess.list2cmdline(raw_argv)}".strip(),
        parameters=_describe_parameters(args, output),
        source_url=BASE_URL,
        pages=result.pages,
        requests=client.requests_made,
        skipped=result.skipped,
        failed_pages=result.failed_pages,
        interrupted=result.interrupted,
    )
    path = _save(result, output, run)
    logger.info(
        "Готово: товаров %d, категорий %d, страниц листинга %d, HTTP-запросов %d, "
        "пропущено %d, время %s",
        len(result.books),
        len({book.category for book in result.books}),
        result.pages,
        client.requests_made,
        result.skipped,
        format_duration(run.duration_seconds),
    )
    logger.info("Excel сохранён: %s", path)
    return EXIT_INTERRUPTED if result.interrupted else EXIT_OK


def _save(result: ScrapeResult, output: Path, run: RunInfo) -> Path:
    """Сохраняет Excel; если файл открыт в Excel и заблокирован — пишет рядом под другим именем."""
    try:
        return export_to_excel(result.books, output, run)
    except PermissionError:
        fallback = output.with_name(f"{output.stem}_{datetime.now():%H-%M-%S}{output.suffix}")
        logger.warning("Файл %s занят (открыт в Excel?), сохраняю в %s", output, fallback)
        return export_to_excel(result.books, fallback, run)


def _describe_parameters(args: argparse.Namespace, output: Path) -> dict[str, str]:
    return {
        "--category": args.category or "весь каталог",
        "--max-pages": str(args.max_pages) if args.max_pages else "без ограничения",
        "--details": "да" if args.details else "нет",
        "--output": str(output),
        "--delay": f"{args.delay:g} с",
        "--retries": str(args.retries),
        "--timeout": f"{args.timeout:g} с",
        "--log-level": args.log_level,
    }


def _print_categories(scraper: CatalogScraper) -> int:
    categories = scraper.list_categories()
    for number, category in enumerate(categories, start=1):
        print(f"{number:>3}. {category.name}")
    print(f"Всего категорий: {len(categories)}")
    return EXIT_OK


def _make_console_safe() -> None:
    """Символы вроде «£» или «é» не должны ронять вывод в консоль с кодировкой cp1251/cp866."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors="backslashreplace")
