"""Local Indian equity instrument search and entity resolution.

The search layer translates human company/ticker queries into canonical
Yahoo-compatible NSE/BSE symbols before the existing market-data pipeline runs.
"""

from __future__ import annotations

import csv
import json
import re
import time
import urllib.request
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from tempfile import NamedTemporaryFile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
CACHE_PATH = DATA_DIR / "instrument_master_cache.json"
ALIAS_PATH = PROJECT_ROOT / "app" / "instrument_aliases.json"
NSE_EQUITY_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
CACHE_VERSION = 1
CACHE_TTL_SECONDS = 7 * 24 * 60 * 60

CORPORATE_SUFFIXES = {
    "ltd",
    "limited",
    "company",
    "co",
    "corp",
    "corporation",
    "inc",
    "incorporated",
    "plc",
    "pvt",
    "private",
}
ACRONYM_STOPWORDS = {"and", "of", "the", "for", "to", "in", "india"}
SEARCH_STOPWORDS = {"and", "of", "the", "for", "to", "in"}


@dataclass(frozen=True)
class Instrument:
    symbol: str
    yahoo_symbol: str
    company_name: str
    exchange: str
    instrument_type: str = "EQUITY"
    aliases: tuple[str, ...] = field(default_factory=tuple)
    search_terms: tuple[str, ...] = field(default_factory=tuple)
    source: str = "nse"


@dataclass
class SearchIndex:
    instruments: list[Instrument]
    updated_at: float
    source: str
    exact: dict[str, list[int]]
    token: dict[str, set[int]]
    prefix: dict[str, set[int]]
    verified_aliases: dict[str, set[str]]
    alias_count: int


_INDEX: SearchIndex | None = None


def normalize_query(value: str) -> str:
    text = value.strip().lower()
    text = text.replace("&", " and ")
    text = re.sub(r"\.(ns|bo)\b", r" \1", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def compact_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", normalize_query(value))


def meaningful_tokens(value: str, *, keep_suffixes: bool = False) -> list[str]:
    tokens = [token for token in normalize_query(value).split() if token not in SEARCH_STOPWORDS]
    if keep_suffixes:
        return tokens
    return [token for token in tokens if token not in CORPORATE_SUFFIXES]


def strip_corporate_suffix(value: str) -> str:
    tokens = normalize_query(value).split()
    while tokens and tokens[-1] in CORPORATE_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def acronym(tokens: list[str]) -> str:
    return "".join(token[0] for token in tokens if token and token not in ACRONYM_STOPWORDS).upper()


def generated_aliases(symbol: str, yahoo_symbol: str, company_name: str) -> tuple[str, ...]:
    terms = {
        symbol,
        yahoo_symbol,
        company_name,
        strip_corporate_suffix(company_name),
        compact_text(symbol),
        compact_text(yahoo_symbol),
    }
    full_acronym = acronym(meaningful_tokens(company_name, keep_suffixes=True))
    short_acronym = acronym(meaningful_tokens(company_name))
    for value in (full_acronym, short_acronym):
        if 2 <= len(value) <= 8:
            terms.add(value)
    return tuple(sorted({term for term in terms if term}))


def search_terms_for(symbol: str, yahoo_symbol: str, company_name: str) -> tuple[str, ...]:
    terms = set()
    for value in generated_aliases(symbol, yahoo_symbol, company_name):
        terms.add(normalize_query(value))
        terms.add(compact_text(value))
    terms.update(meaningful_tokens(company_name))
    return tuple(sorted({term for term in terms if term}))


def instrument_record(symbol: str, company_name: str, exchange: str, source: str) -> Instrument:
    suffix = ".NS" if exchange == "NSE" else ".BO"
    yahoo_symbol = f"{symbol.upper()}{suffix}"
    aliases = generated_aliases(symbol.upper(), yahoo_symbol, company_name)
    return Instrument(
        symbol=symbol.upper(),
        yahoo_symbol=yahoo_symbol,
        company_name=company_name.strip(),
        exchange=exchange,
        aliases=aliases,
        search_terms=search_terms_for(symbol.upper(), yahoo_symbol, company_name),
        source=source,
    )


def read_nse_equity_csv(text: str) -> list[Instrument]:
    records: list[Instrument] = []
    reader = csv.DictReader(text.splitlines())
    for row in reader:
        symbol = str(row.get("SYMBOL") or "").strip().upper()
        name = str(row.get("NAME OF COMPANY") or "").strip()
        series = str(row.get(" SERIES") or row.get("SERIES") or "").strip().upper()
        if not symbol or not name or series not in {"EQ", "BE", "BZ", "SM", "ST"}:
            continue
        records.append(instrument_record(symbol, name, "NSE", "nse-official-equity-list"))
        records.append(instrument_record(symbol, name, "BSE", "nse-derived-yahoo-bse-symbol"))
    return records


def download_nse_instruments(timeout: int = 20) -> list[Instrument]:
    request = urllib.request.Request(
        NSE_EQUITY_URL,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/csv,text/plain,*/*",
            "Referer": "https://www.nseindia.com/",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        text = response.read().decode("utf-8", errors="replace")
    return read_nse_equity_csv(text)


def instruments_to_json(instruments: list[Instrument], source: str) -> dict[str, object]:
    return {
        "version": CACHE_VERSION,
        "updated_at": time.time(),
        "source": source,
        "source_url": NSE_EQUITY_URL,
        "instruments": [instrument.__dict__ for instrument in instruments],
    }


def save_cache(instruments: list[Instrument], source: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = instruments_to_json(instruments, source)
    with NamedTemporaryFile("w", encoding="utf-8", dir=DATA_DIR, delete=False) as temp:
        json.dump(payload, temp, ensure_ascii=False, separators=(",", ":"))
        temp_path = Path(temp.name)
    temp_path.replace(CACHE_PATH)


def load_cache() -> tuple[list[Instrument], float, str] | None:
    if not CACHE_PATH.exists():
        return None
    try:
        payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        if payload.get("version") != CACHE_VERSION:
            return None
        instruments = [
            Instrument(
                symbol=str(item["symbol"]),
                yahoo_symbol=str(item["yahoo_symbol"]),
                company_name=str(item["company_name"]),
                exchange=str(item["exchange"]),
                instrument_type=str(item.get("instrument_type") or "EQUITY"),
                aliases=tuple(item.get("aliases") or ()),
                search_terms=tuple(item.get("search_terms") or ()),
                source=str(item.get("source") or "cache"),
            )
            for item in payload.get("instruments", [])
        ]
        return instruments, float(payload.get("updated_at") or 0), str(payload.get("source") or "cache")
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def build_index(instruments: list[Instrument], updated_at: float, source: str) -> SearchIndex:
    exact: dict[str, list[int]] = {}
    token: dict[str, set[int]] = {}
    prefix: dict[str, set[int]] = {}
    verified_aliases = load_verified_aliases()
    alias_count = 0
    for index, instrument in enumerate(instruments):
        terms = set(instrument.search_terms)
        terms.update(normalize_query(alias) for alias in instrument.aliases)
        terms.update(compact_text(alias) for alias in instrument.aliases)
        terms.update({
            normalize_query(instrument.symbol),
            compact_text(instrument.symbol),
            normalize_query(instrument.yahoo_symbol),
            compact_text(instrument.yahoo_symbol),
            normalize_query(instrument.company_name),
            compact_text(instrument.company_name),
        })
        alias_count += len(instrument.aliases)
        for term in terms:
            if not term:
                continue
            exact.setdefault(term, []).append(index)
            for part in term.split():
                if len(part) >= 2:
                    token.setdefault(part, set()).add(index)
                    for size in range(2, min(len(part), 8) + 1):
                        prefix.setdefault(part[:size], set()).add(index)
            compact = compact_text(term)
            if len(compact) >= 2:
                for size in range(2, min(len(compact), 10) + 1):
                    prefix.setdefault(compact[:size], set()).add(index)
    return SearchIndex(instruments, updated_at, source, exact, token, prefix, verified_aliases, alias_count)


def load_verified_aliases() -> dict[str, set[str]]:
    if not ALIAS_PATH.exists():
        return {}
    try:
        payload = json.loads(ALIAS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    aliases: dict[str, set[str]] = {}
    for alias, symbols in payload.items():
        keys = {normalize_query(str(alias)), compact_text(str(alias))}
        values = {str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()}
        for key in keys:
            if key:
                aliases[key] = values
    return aliases


def load_index(*, refresh: bool = False) -> SearchIndex:
    global _INDEX
    if _INDEX and not refresh:
        return _INDEX

    cached = load_cache()
    if not refresh and cached and time.time() - cached[1] <= CACHE_TTL_SECONDS:
        _INDEX = build_index(*cached)
        return _INDEX

    try:
        instruments = download_nse_instruments()
        save_cache(instruments, "nse-official-equity-list")
        _INDEX = build_index(instruments, time.time(), "nse-official-equity-list")
        return _INDEX
    except Exception:
        if cached:
            _INDEX = build_index(*cached)
            return _INDEX
        _INDEX = build_index([], 0, "empty")
        return _INDEX


def exactness_score(instrument: Instrument, query_norm: str, query_compact: str, search_index: SearchIndex) -> int:
    symbol = normalize_query(instrument.symbol)
    yahoo = normalize_query(instrument.yahoo_symbol)
    name = normalize_query(instrument.company_name)
    aliases = {normalize_query(alias) for alias in instrument.aliases}
    alias_compacts = {compact_text(alias) for alias in instrument.aliases}
    verified = search_index.verified_aliases.get(query_norm, set()) | search_index.verified_aliases.get(query_compact, set())
    if instrument.yahoo_symbol.upper() in verified:
        return 1200
    if query_norm == yahoo or query_compact == compact_text(instrument.yahoo_symbol):
        return 1000
    if query_norm == symbol or query_compact == compact_text(instrument.symbol):
        return 980
    if query_norm in aliases or query_compact in alias_compacts:
        return 950
    if query_norm == name or query_compact == compact_text(instrument.company_name):
        return 930
    if symbol.startswith(query_norm) or compact_text(instrument.symbol).startswith(query_compact):
        return 800
    if name.startswith(query_norm) or compact_text(instrument.company_name).startswith(query_compact):
        return 760
    if any(alias.startswith(query_norm) for alias in aliases):
        return 740
    return 0


def ordered_token_score(instrument: Instrument, query_tokens: list[str]) -> int:
    if not query_tokens:
        return 0
    haystack = normalize_query(" ".join([instrument.company_name, instrument.symbol, *instrument.aliases]))
    haystack_tokens = haystack.split()
    cursor = 0
    score = 0
    for token in query_tokens:
        pos = haystack.find(token, cursor)
        if pos == -1:
            if any(part.startswith(token) for part in haystack.split()):
                score += 45
                continue
            if len(token) >= 5 and any(SequenceMatcher(None, token, part).ratio() >= 0.82 for part in haystack_tokens):
                score += 36
                continue
            return 0
        score += 55
        cursor = pos + len(token)
    return min(score, 220)


def fuzzy_score(instrument: Instrument, query_norm: str) -> int:
    if len(compact_text(query_norm)) < 4:
        return 0
    candidates = [
        normalize_query(instrument.company_name),
        strip_corporate_suffix(instrument.company_name),
        normalize_query(instrument.symbol),
    ]
    best = max(SequenceMatcher(None, query_norm, candidate).ratio() for candidate in candidates if candidate)
    if best >= 0.88:
        return 180
    if best >= 0.78:
        return 95
    return 0


def candidate_indices(search_index: SearchIndex, query_norm: str, query_compact: str) -> set[int]:
    candidates: set[int] = set()
    for key in (query_norm, query_compact):
        candidates.update(search_index.exact.get(key, []))
    for token in query_norm.split():
        if token in CORPORATE_SUFFIXES or token in SEARCH_STOPWORDS:
            continue
        if len(token) >= 2:
            candidates.update(search_index.token.get(token, set()))
            candidates.update(search_index.prefix.get(token[: min(len(token), 8)], set()))
    if len(query_compact) >= 2:
        candidates.update(search_index.prefix.get(query_compact[: min(len(query_compact), 10)], set()))
    if len(query_compact) >= 4 and not candidates:
        candidates.update(search_index.prefix.get(query_compact[:2], set()))
    if len(query_compact) >= 4 and not candidates:
        candidates.update(range(len(search_index.instruments)))
    return candidates


def search_instruments(query: str, exchange: str = "NSE", *, limit: int = 10) -> list[dict[str, object]]:
    query_norm = normalize_query(query)
    query_compact = compact_text(query)
    if len(query_compact) < 2:
        return []
    preferred_exchange = exchange.strip().upper()
    if preferred_exchange not in {"NSE", "BSE"}:
        preferred_exchange = "NSE"

    search_index = load_index()
    query_tokens = meaningful_tokens(query_norm)
    candidates = candidate_indices(search_index, query_norm, query_compact)
    scored: list[tuple[int, str, Instrument]] = []
    for idx in candidates:
        instrument = search_index.instruments[idx]
        exact = exactness_score(instrument, query_norm, query_compact, search_index)
        ordered = ordered_token_score(instrument, query_tokens)
        substring = 120 if query_norm and query_norm in normalize_query(instrument.company_name) else 0
        symbol_ratio = SequenceMatcher(None, query_compact, compact_text(instrument.symbol)).ratio() if len(query_compact) >= 4 else 0
        symbol_typo = 230 if symbol_ratio >= 0.86 else 0
        fuzzy = symbol_typo if symbol_typo else 0 if (exact or ordered >= 55 or substring) else fuzzy_score(instrument, query_norm)
        if not any([exact, ordered, fuzzy, substring]):
            continue
        score = exact + ordered + fuzzy + substring
        if instrument.exchange == preferred_exchange:
            score += 35
        if instrument.source.startswith("nse-derived") and preferred_exchange != "BSE":
            score -= 15
        scored.append((score, instrument.yahoo_symbol, instrument))

    ranked = sorted(scored, key=lambda item: (-item[0], item[1]))[:limit]
    return [format_result(instrument, score, search_index) for score, _, instrument in ranked]


def format_result(instrument: Instrument, score: int, search_index: SearchIndex | None = None) -> dict[str, object]:
    confidence = "high" if score >= 900 else "medium" if score >= 300 else "suggestion"
    return {
        "symbol": instrument.yahoo_symbol,
        "baseSymbol": instrument.symbol,
        "yahoo_symbol": instrument.yahoo_symbol,
        "instrument_symbol": instrument.symbol,
        "name": instrument.company_name,
        "company_name": instrument.company_name,
        "exchange": instrument.exchange,
        "type": "Equity",
        "instrument_type": instrument.instrument_type,
        "confidence": confidence,
        "source": instrument.source,
    }


def index_stats() -> dict[str, object]:
    search_index = load_index()
    nse_count = sum(1 for item in search_index.instruments if item.exchange == "NSE")
    bse_count = sum(1 for item in search_index.instruments if item.exchange == "BSE")
    size = CACHE_PATH.stat().st_size if CACHE_PATH.exists() else 0
    return {
        "instrument_count": len(search_index.instruments),
        "nse_count": nse_count,
        "bse_count": bse_count,
        "alias_count": search_index.alias_count,
        "cache_path": str(CACHE_PATH),
        "cache_size_bytes": size,
        "updated_at": search_index.updated_at,
        "source": search_index.source,
    }
