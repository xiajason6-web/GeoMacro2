"""Collector: mirror trade — partner-country exports to China.

What this does: pulls monthly export values to China for HS 8486 (semiconductor
manufacturing equipment) and HS 8542 (integrated circuits) from official
statistical APIs, saves every raw API response under data/raw/, records it in
`documents`, then deterministically parses the numbers into `metrics` rows
(entity = China, one row per month, each row pointing at the exact raw
response it came from). No LLM is involved — this is structured numeric data.

Sources:
  - Eurostat Comext (works today, no key): reporters EU27, Netherlands (≈ASML),
    Germany. Values in EUR.
  - US Census (needs free CENSUS_API_KEY in .env — https://api.census.gov/data/key_signup.html):
    skipped with a warning until the key exists.
  - Japan (needs free e-Stat appId — https://www.e-stat.go.jp/en/api/): not yet
    implemented; will be added with a real fixture once the key exists.

How you'd know it broke: each series prints "N months" on success. An API
error crashes loudly. A month that disappears from a previously fetched
series would show up as a shorter range in the printed output and in the
CSV export. Re-running never re-fetches byte-identical data into new rows.
"""

import datetime
import hashlib
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "db" / "tracker.sqlite"
RAW_DIR = REPO_ROOT / "data" / "raw" / "mirror_trade"
USER_AGENT = "ChinaTechFlowsTracker/0.1 (research; contact: jx3@williams.edu)"

BACKFILL_SINCE = "2023-07"  # three years back from July 2026

EUROSTAT_SOURCE = {
    "name": "Eurostat Comext",
    "url": "https://ec.europa.eu/eurostat/web/international-trade-in-goods/database",
    "type": "trade_stats",
    "language": "en",
}
EUROSTAT_API = (
    "https://ec.europa.eu/eurostat/api/comext/dissemination/statistics/1.0/data/DS-045409"
)

# One series per (reporter, HS product). flow=2 is EXPORT; partner=CN is China.
EUROSTAT_SERIES = [
    {"reporter": "EU27_2020", "product": "8486", "metric": "mirror_exports_eu27_hs8486_eur"},
    {"reporter": "EU27_2020", "product": "8542", "metric": "mirror_exports_eu27_hs8542_eur"},
    {"reporter": "NL", "product": "8486", "metric": "mirror_exports_nl_hs8486_eur"},
    {"reporter": "NL", "product": "8542", "metric": "mirror_exports_nl_hs8542_eur"},
    {"reporter": "DE", "product": "8486", "metric": "mirror_exports_de_hs8486_eur"},
    {"reporter": "DE", "product": "8542", "metric": "mirror_exports_de_hs8542_eur"},
]

ESTAT_SOURCE = {
    "name": "Japan Trade Statistics (e-Stat)",
    "url": "https://www.e-stat.go.jp",
    "type": "trade_stats",
    "language": "ja",
}
ESTAT_API = "https://api.e-stat.go.jp/rest/3.0/app/json/getStatsData"

# Japan's 品別国別表 (commodity-by-country) export tables. Dimensions:
#   area 50105 = China; cat01 = HS 9-digit codes (we filter a range and sum);
#   cat02 encodes month x measure — the VALUE (金額) code for month m is
#   140 + 30*m (Jan=170 .. Dec=500), unit thousand yen; time = calendar year.
ESTAT_TABLES = [
    {"stats_data_id": "0003425293", "time_from": "2023000000"},  # 2021-2025 (we filter >=2023)
    {"stats_data_id": "0004049306", "time_from": None},          # 2026
]
ESTAT_CHINA_AREA = "50105"
ESTAT_MONTH_VALUE_CODES = ",".join(str(140 + 30 * m) for m in range(1, 13))

ESTAT_SERIES = [
    {"product": "8486", "metric": "mirror_exports_jp_hs8486_jpy"},
    {"product": "8542", "metric": "mirror_exports_jp_hs8542_jpy"},
]

CENSUS_SOURCE = {
    "name": "US Census International Trade",
    "url": "https://www.census.gov/foreign-trade/",
    "type": "trade_stats",
    "language": "en",
}
CENSUS_API = "https://api.census.gov/data/timeseries/intltrade/exports/hs"
CENSUS_CHINA = "5700"
CENSUS_YEARS = ["2023", "2024", "2025", "2026"]
CENSUS_SERIES = [
    {"product": "8486", "metric": "mirror_exports_us_hs8486_usd"},
    {"product": "8542", "metric": "mirror_exports_us_hs8542_usd"},
]

# UN Comtrade public preview (keyless; hard limits: ONE period per call,
# ~500 calls/day). Covers Korea and Singapore; Taiwan is NOT in Comtrade —
# that gap stays explicit in the ratio's coverage field. Values are USD.
COMTRADE_API = "https://comtradeapi.un.org/public/v1/preview/C/M/HS"
COMTRADE_REPORTERS = [("410", "kr"), ("702", "sg")]
COMTRADE_PRODUCTS = ["8486", "8542"]
COMTRADE_SINCE = "2023-01"
COMTRADE_SOURCE = {
    "name": "UN Comtrade",
    "url": "https://comtradeplus.un.org",
    "type": "trade_stats",
    "language": "en",
}

CHINA_ENTITY = {
    "name_en": "China",
    "name_zh": "中国",
    "ticker": None,
    "exchange": None,
    "entity_type": "country",
    "supply_chain_layer": None,
}


def connect(db_path=DB_PATH):
    conn = sqlite3.connect(db_path, timeout=60)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def load_env():
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


def ensure_source(conn, source):
    conn.execute(
        "INSERT OR IGNORE INTO sources (name, url, type, language)"
        " VALUES (:name, :url, :type, :language)",
        source,
    )
    return conn.execute(
        "SELECT id FROM sources WHERE name = ?", (source["name"],)
    ).fetchone()[0]


def ensure_china_entity(conn):
    conn.execute(
        "INSERT OR IGNORE INTO entities"
        " (name_en, name_zh, ticker, exchange, entity_type, supply_chain_layer)"
        " VALUES (:name_en, :name_zh, :ticker, :exchange, :entity_type, :supply_chain_layer)",
        CHINA_ENTITY,
    )
    return conn.execute(
        "SELECT id FROM entities WHERE name_en = 'China'"
    ).fetchone()[0]


def eurostat_url(series, since=BACKFILL_SINCE):
    return (
        f"{EUROSTAT_API}?format=JSON&freq=M"
        f"&reporter={series['reporter']}&partner=CN&product={series['product']}"
        f"&flow=2&indicators=VALUE_IN_EUROS&sinceTimePeriod={since}"
    )


def parse_eurostat_response(payload):
    """JSON-stat (single series over time) -> list of (period 'YYYY-MM', value).

    The time dimension can include future months with no data yet; only
    indices present in `value` are returned. Deterministic — no guessing.
    """
    time_index = payload["dimension"]["time"]["category"]["index"]
    values = payload["value"]
    out = []
    for period, idx in sorted(time_index.items(), key=lambda kv: kv[1]):
        if str(idx) in values:
            out.append((period, float(values[str(idx)])))
        elif idx in values:  # some deserializers keep int keys
            out.append((period, float(values[idx])))
    return out


def ingest_raw(conn, source_id, url, content, title):
    """Save raw bytes + documents row. Returns (document_id, is_new)."""
    sha = hashlib.sha256(content).hexdigest()
    existing = conn.execute(
        "SELECT id FROM documents WHERE sha256 = ?", (sha,)
    ).fetchone()
    if existing:
        return existing[0], False
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
    raw_path = RAW_DIR / f"{stamp}_{title}.json"
    if raw_path.exists():
        raw_path = raw_path.with_name(f"{raw_path.stem}_{sha[:8]}.json")
    raw_path.write_bytes(content)
    retrieved_at = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    cur = conn.execute(
        "INSERT INTO documents"
        " (source_id, url, retrieved_at, raw_path, sha256, doc_date, title, language)"
        " VALUES (?, ?, ?, ?, ?, NULL, ?, 'en')",
        (source_id, url, retrieved_at, str(raw_path.relative_to(REPO_ROOT)), sha, title),
    )
    return cur.lastrowid, True


def write_metrics(conn, entity_id, metric_name, rows, unit, currency, document_id, note):
    """Insert one metrics row per (period, value), all citing document_id."""
    for period, value in rows:
        conn.execute(
            "INSERT OR IGNORE INTO metrics"
            " (entity_id, metric_name, period, value, unit, currency, document_id,"
            "  extraction_confidence, notes)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, 1.0, ?)",
            (entity_id, metric_name, period, value, unit, currency, document_id, note),
        )


def collect_eurostat(conn):
    source_id = ensure_source(conn, EUROSTAT_SOURCE)
    entity_id = ensure_china_entity(conn)
    for series in EUROSTAT_SERIES:
        url = eurostat_url(series)
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=120)
        resp.raise_for_status()
        title = f"eurostat_{series['reporter']}_hs{series['product']}_exports_to_cn"
        doc_id, is_new = ingest_raw(conn, source_id, url, resp.content, title)
        rows = parse_eurostat_response(resp.json())
        if not is_new:
            print(f"{series['metric']}: unchanged since last fetch ({len(rows)} months)")
            continue
        note = (
            f"{series['reporter']} exports to China, HS {series['product']},"
            " monthly value in euros (Eurostat Comext DS-045409, mirror of"
            " China imports)"
        )
        write_metrics(
            conn, entity_id, series["metric"], rows, "EUR", "EUR", doc_id, note
        )
        first = rows[0][0] if rows else "-"
        last = rows[-1][0] if rows else "-"
        print(f"{series['metric']}: {len(rows)} months ({first} .. {last}), document id={doc_id}")
        time.sleep(1)  # rule 7: be polite between requests
    conn.commit()


def estat_url(table, product, app_id):
    url = (
        f"{ESTAT_API}?appId={app_id}&statsDataId={table['stats_data_id']}"
        f"&cdArea={ESTAT_CHINA_AREA}"
        f"&cdCat01From={product}10000&cdCat01To={product}99999"
        f"&cdCat02={ESTAT_MONTH_VALUE_CODES}"
    )
    if table["time_from"]:
        url += f"&cdTimeFrom={table['time_from']}"
    return url


def parse_estat_response(payload):
    """e-Stat getStatsData JSON -> sorted list of (period 'YYYY-MM', value_jpy).

    Sums across HS 9-digit sub-codes (cat01). Values arrive in thousand yen
    (千円) and are converted to yen here (x1000 — deterministic).

    e-Stat zero-fills months that are not yet published in the current-year
    table (every sub-code '0'), so a month whose total is 0 is treated as
    UNPUBLISHED and dropped — recording it as zero trade would corrupt every
    downstream quarter. A genuine all-zero month for these aggregates does
    not occur.
    """
    data = payload["GET_STATS_DATA"]["STATISTICAL_DATA"]
    if int(data["RESULT_INF"]["TOTAL_NUMBER"]) == 0:
        return []
    values = data["DATA_INF"]["VALUE"]
    if isinstance(values, dict):
        values = [values]
    monthly = {}
    for v in values:
        raw = v["$"]
        if not raw.replace(",", "").isdigit():
            continue  # '-' / suppressed values: missing, not zero
        code = int(v["@cat02"])
        if code < 170 or (code - 140) % 30 != 0:
            continue  # not a monthly VALUE cell (quantities, totals)
        month = (code - 140) // 30
        year = v["@time"][:4]
        period = f"{year}-{month:02d}"
        monthly[period] = monthly.get(period, 0) + int(raw.replace(",", "")) * 1000
    return sorted((p, v) for p, v in monthly.items() if v > 0)


def collect_japan(conn):
    app_id = os.environ.get("ESTAT_APP_ID")
    if not app_id:
        print(
            "Japan: skipped — no ESTAT_APP_ID in .env. Free registration:"
            " https://www.e-stat.go.jp/en/api/"
        )
        return
    source_id = ensure_source(conn, ESTAT_SOURCE)
    entity_id = ensure_china_entity(conn)
    note_tmpl = (
        "Japan exports to China, HS {product}, monthly value in yen"
        " (converted from thousand yen; e-Stat 普通貿易統計 品別国別表,"
        " mirror of China imports)"
    )
    for series in ESTAT_SERIES:
        total_months = 0
        for table in ESTAT_TABLES:
            url = estat_url(table, series["product"], app_id)
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=180)
            resp.raise_for_status()
            title = (
                f"estat_jp_hs{series['product']}_exports_to_cn_"
                f"{table['stats_data_id']}"
            )
            # Never store the appId: strip the credential before the documents
            # table (rule 9). The stored URL is reproducible with any key.
            public_url = url.replace(f"appId={app_id}", "appId=REDACTED")
            doc_id, is_new = ingest_raw(conn, source_id, public_url, resp.content, title)
            rows = parse_estat_response(resp.json())
            total_months += len(rows)
            if is_new:
                # Each month cites exactly the raw response it came from.
                write_metrics(
                    conn, entity_id, series["metric"], rows, "JPY", "JPY",
                    doc_id, note_tmpl.format(product=series["product"]),
                )
                span = f"{rows[0][0]} .. {rows[-1][0]}" if rows else "-"
                print(
                    f"{series['metric']}: {len(rows)} months ({span}),"
                    f" document id={doc_id}"
                )
            else:
                print(
                    f"{series['metric']} [{table['stats_data_id']}]:"
                    f" unchanged since last fetch ({len(rows)} months)"
                )
            time.sleep(1)  # rule 7
    conn.commit()


def parse_census_response(payload):
    """Census JSON (array of arrays, header first) -> [(period, value_usd)].

    Header names the columns; we locate ALL_VAL_MO and time by name rather
    than position so a column reorder can't silently misread values.
    """
    header, rows = payload[0], payload[1:]
    val_idx = header.index("ALL_VAL_MO")
    time_idx = header.index("time")
    return sorted((r[time_idx], float(r[val_idx])) for r in rows)


def collect_us_census(conn):
    key = os.environ.get("CENSUS_API_KEY")
    if not key:
        print(
            "US Census: skipped — no CENSUS_API_KEY in .env. Free signup:"
            " https://api.census.gov/data/key_signup.html"
        )
        return
    source_id = ensure_source(conn, CENSUS_SOURCE)
    entity_id = ensure_china_entity(conn)
    for series in CENSUS_SERIES:
        for year in CENSUS_YEARS:
            url = (
                f"{CENSUS_API}?get=ALL_VAL_MO&E_COMMODITY={series['product']}"
                f"&COMM_LVL=HS4&CTY_CODE={CENSUS_CHINA}&time={year}&key={key}"
            )
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=120)
            resp.raise_for_status()
            title = f"census_us_hs{series['product']}_exports_to_cn_{year}"
            # Rule 9: the stored URL must not contain the API key.
            public_url = url.replace(f"key={key}", "key=REDACTED")
            doc_id, is_new = ingest_raw(conn, source_id, public_url, resp.content, title)
            rows = parse_census_response(resp.json())
            if is_new:
                note = (
                    f"US exports to China, HS {series['product']}, monthly value"
                    " in USD (US Census timeseries/intltrade, mirror of China"
                    " imports)"
                )
                write_metrics(
                    conn, entity_id, series["metric"], rows, "USD", "USD", doc_id, note
                )
                span = f"{rows[0][0]} .. {rows[-1][0]}" if rows else "-"
                print(
                    f"{series['metric']} [{year}]: {len(rows)} months ({span}),"
                    f" document id={doc_id}"
                )
            else:
                print(
                    f"{series['metric']} [{year}]: unchanged since last fetch"
                    f" ({len(rows)} months)"
                )
            time.sleep(1)  # rule 7
    conn.commit()


def comtrade_months():
    """Months from COMTRADE_SINCE through two months ago (publication lag)."""
    out = []
    year, month = (int(x) for x in COMTRADE_SINCE.split("-"))
    today = datetime.date.today()
    last = (today.replace(day=1) - datetime.timedelta(days=1)).replace(day=1)
    last = (last - datetime.timedelta(days=1)).replace(day=1)  # two months back
    current = datetime.date(year, month, 1)
    while current <= last:
        out.append(f"{current.year}-{current.month:02d}")
        current = (current + datetime.timedelta(days=32)).replace(day=1)
    return out


def collect_comtrade(conn):
    source_id = ensure_source(conn, COMTRADE_SOURCE)
    entity_id = ensure_china_entity(conn)
    metric_names = {
        (code, product): f"mirror_exports_{slug}_hs{product}_usd"
        for code, slug in COMTRADE_REPORTERS
        for product in COMTRADE_PRODUCTS
    }
    have = {
        (metric, period)
        for metric, period in conn.execute(
            "SELECT DISTINCT metric_name, period FROM metrics WHERE metric_name IN"
            " (" + ",".join("?" * len(metric_names)) + ")",
            list(metric_names.values()),
        )
    }
    todo = [
        m for m in comtrade_months()
        if any((name, m) not in have for name in metric_names.values())
    ]
    if not todo:
        print("Comtrade KR/SG: up to date")
        return
    print(f"Comtrade KR/SG: querying {len(todo)} months (1 call each, keyless preview)")
    for month in todo:
        period_param = month.replace("-", "")
        url = (
            f"{COMTRADE_API}?reporterCode="
            + ",".join(code for code, _ in COMTRADE_REPORTERS)
            + f"&period={period_param}&partnerCode=156&flowCode=X&cmdCode="
            + ",".join(COMTRADE_PRODUCTS)
        )
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=120)
        if resp.status_code == 429:
            print(f"Comtrade rate limit hit at {month} — stopping; next run resumes here")
            break
        resp.raise_for_status()
        payload = resp.json()
        rows = payload.get("data") or []
        wrote = 0
        doc_id = None
        for row in rows:
            key = (str(row["reporterCode"]), str(row["cmdCode"]))
            metric = metric_names.get(key)
            value = float(row.get("primaryValue") or 0)
            if metric is None or value <= 0:
                continue  # zero/unknown = unpublished, never recorded as zero trade
            if (metric, month) in have:
                continue
            if doc_id is None:
                title = f"comtrade_kr_sg_hs8486_8542_exports_to_cn_{month}"
                doc_id, _ = ingest_raw(conn, source_id, url, resp.content, title)
            note = (
                "exports to China (partner 156), USD, UN Comtrade monthly"
                " (mirror of China imports)"
            )
            write_metrics(conn, entity_id, metric, [(month, value)], "USD", "USD", doc_id, note)
            wrote += 1
        print(f"  {month}: {wrote} series written ({len(rows)} rows returned)")
        conn.commit()
        time.sleep(1.5)  # rule 7 + keyless-tier politeness
    conn.commit()


def main():
    load_env()
    conn = connect()
    collect_eurostat(conn)
    collect_japan(conn)
    collect_us_census(conn)
    collect_comtrade(conn)
    conn.close()


if __name__ == "__main__":
    sys.exit(main())
