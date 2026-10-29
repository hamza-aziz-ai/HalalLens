#!/usr/bin/env python3
"""Download and parse official NSE/BSE bhavcopy files."""

from __future__ import annotations

import csv
import html
import io
import logging
import re
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Dict, Optional

import requests

LOGGER = logging.getLogger("bhavcopy")


class BhavcopyError(RuntimeError):
    """Raised when a bhavcopy file cannot be fetched or parsed."""


def _parse_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


@dataclass
class BSEBhavRecord:
    symbol: str
    isin: str
    close: Optional[float]
    company_name: str
    ticker: str = ""


class BhavcopyClient:
    """Fetch BSE equity bhavcopy and NSE market-cap files."""

    # Current BSE file (UDiFF common format, since 2024); day = YYYYMMDD.
    BSE_UDIFF_URL = (
        "https://www.bseindia.com/download/BhavCopy/Equity/"
        "BhavCopy_BSE_CM_0_0_0_{day}_F_0000.CSV"
    )
    # Legacy BSE file names, kept as fallbacks; day = DDMMYY.
    BSE_URL = "https://www.bseindia.com/download/BhavCopy/Equity/EQ_ISINCODE_{day}.zip"
    # NSE's daily price report zip holds mcapDDMMYYYY.csv; day = DDMMYY.
    NSE_PR_URL = "https://nsearchives.nseindia.com/archives/equities/bhavcopy/pr/PR{day}.zip"
    NSE_URL = "https://archives.nseindia.com/content/equities/mcap/mcap{day}.csv"
    BSE_PAGE = "https://www.bseindia.com/markets/MarketInfo/BhavCopy.aspx"
    HIDDEN_FIELDS = [
        "__VIEWSTATE",
        "__VIEWSTATEGENERATOR",
        "__VIEWSTATEENCRYPTED",
        "__EVENTVALIDATION",
    ]

    def __init__(
        self,
        session: Optional[requests.Session] = None,
        bse_local_dir: Optional[Path] = None,
        nse_local_dir: Optional[Path] = None,
    ):
        self.session = session or requests.Session()
        default_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36"
            ),
            "Referer": self.BSE_PAGE,
            "Origin": "https://www.bseindia.com",
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.7",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Dest": "document",
        }
        self.session.headers.update(default_headers)
        self.session.trust_env = False
        self.bse_local_dir = Path(bse_local_dir).resolve() if bse_local_dir else None
        self.nse_local_dir = Path(nse_local_dir).resolve() if nse_local_dir else None
        self._last_bse_records: Dict[str, BSEBhavRecord] = {}

    def fetch_bse_equity(self, as_of: date) -> Dict[str, BSEBhavRecord]:
        """Return BSE bhavcopy records keyed by SCRIP code."""

        day = as_of.strftime("%d%m%y")
        raw_csv = self._load_local_bse_csv(as_of)
        if raw_csv is None:
            raw_csv = self._download_direct_bse_csv(as_of)
        if raw_csv is None:
            raw_csv = self._download_form_based_bse_csv(as_of)
        records = self._parse_bse_csv(raw_csv, day)
        self._last_bse_records = records
        return records

    def fetch_nse_market_caps(self, as_of: date) -> Dict[str, float]:
        """Return NSE market caps keyed by ISIN (values in INR)."""

        day = as_of.strftime("%d%m%Y")
        csv_text = self._load_local_nse_csv(as_of)
        if csv_text is None:
            csv_text = self._download_nse_market_caps(day)

        reader = csv.DictReader(io.StringIO(csv_text))
        fieldnames = [field or "" for field in (reader.fieldnames or [])]
        cap_field = next(
            (name for name in fieldnames if "cap" in name.lower()),
            None,
        )
        if not cap_field:
            raise BhavcopyError("NSE market-cap file missing cap column")
        multiplier = self._infer_multiplier(cap_field)
        has_isin_col = any("isin" in name.lower() for name in fieldnames)
        name_lookup = self._build_company_lookup() if not has_isin_col else None
        ticker_lookup = (
            {r.ticker.upper(): r for r in self._last_bse_records.values() if r.ticker}
            if not has_isin_col
            else {}
        )

        # Exact matches (an ISIN column, or the NSE symbol equal to the BSE
        # ticker) always win over a fuzzy company-name match, which can point
        # at a different company and would then give it the wrong market cap.
        exact: Dict[str, float] = {}
        fuzzy: Dict[str, float] = {}
        for row in reader:
            value = _parse_float(row.get(cap_field))
            if value is None:
                continue
            isin = self._extract_isin_from_row(row)
            target = exact
            if not isin:
                record = ticker_lookup.get((row.get("Symbol") or "").strip().upper())
                isin = record.isin if record else None
            if not isin and name_lookup:
                isin = self._match_company_to_isin(row, name_lookup)
                target = fuzzy
            if not isin:
                continue
            target[isin] = value * multiplier

        return {**fuzzy, **exact}

    def _extract_csv_from_archive(self, archive: zipfile.ZipFile) -> str:
        csv_name = next((name for name in archive.namelist() if name.lower().endswith(".csv")), None)
        if not csv_name:
            raise BhavcopyError("BSE bhavcopy zip missing CSV")
        return archive.read(csv_name).decode("utf-8", errors="replace")

    def _parse_bse_csv(self, raw: str, day_label: str) -> Dict[str, BSEBhavRecord]:
        reader = csv.DictReader(io.StringIO(raw))
        results: Dict[str, BSEBhavRecord] = {}
        for row in reader:
            # Legacy EQ_ISINCODE columns first, then the UDiFF names.
            code = (row.get("SC_CODE") or row.get("SC CODE") or row.get("FinInstrmId") or "").strip()
            if not code:
                continue
            isin = (
                row.get("ISIN")
                or row.get("ISINCODE")
                or row.get("ISIN CODE")
                or row.get("ISIN_CODE")
                or ""
            ).strip()
            close = _parse_float(
                row.get("CLOSE") or row.get("LAST") or row.get("TD_CLOSING") or row.get("ClsPric")
            )
            company = (row.get("SC_NAME") or row.get("FinInstrmNm") or "").strip()
            results[code] = BSEBhavRecord(
                symbol=code,
                isin=isin,
                close=close,
                company_name=company,
                ticker=(row.get("TckrSymb") or "").strip(),
            )
        if not results:
            raise BhavcopyError(f"BSE bhavcopy {day_label} produced no rows")
        return results

    def _load_local_bse_csv(self, as_of: date) -> Optional[str]:
        if not self.bse_local_dir:
            return None
        day = as_of.strftime("%d%m%y")
        prefix = f"EQ_ISINCODE_{day}"
        udiff = sorted(
            self.bse_local_dir.glob(f"BhavCopy_BSE_CM_0_0_0_{as_of:%Y%m%d}_F_*.[cC][sS][vV]")
        )
        for candidate in udiff:
            csv_data = candidate.read_text(encoding="utf-8", errors="replace")
            if not self._is_csv_empty(csv_data):
                LOGGER.debug("Using local BSE UDiFF csv %s", candidate)
                return csv_data
        # Prefer ZIP files
        for candidate in sorted(self.bse_local_dir.glob(f"{prefix}*.zip")):
            try:
                with zipfile.ZipFile(candidate) as archive:
                    LOGGER.debug("Using local BSE zip %s", candidate)
                    csv_data = self._extract_csv_from_archive(archive)
                    if self._is_csv_empty(csv_data):
                        continue
                    return csv_data
            except Exception as exc:
                LOGGER.warning("Local BSE zip %s invalid: %s", candidate, exc)
        # Fallback to CSVs (e.g., already extracted)
        for candidate in sorted(self.bse_local_dir.glob(f"{prefix}*.csv")):
            try:
                LOGGER.debug("Using local BSE csv %s", candidate)
                csv_data = candidate.read_text(encoding="utf-8")
                if self._is_csv_empty(csv_data):
                    continue
                return csv_data
            except Exception as exc:
                LOGGER.warning("Unable to read local BSE csv %s: %s", candidate, exc)
        return None

    def _download_direct_bse_csv(self, as_of: date) -> Optional[str]:
        day = as_of.strftime("%d%m%y")
        urls = [
            self.BSE_UDIFF_URL.format(day=as_of.strftime("%Y%m%d")),
            self.BSE_URL.format(day=day),
            f"https://www.bseindia.com/download/BhavCopy/Equity/EQ_ISINCODE_{day}_T0.zip",
            f"https://www.bseindia.com/download/BhavCopy/Equity/EQ_ISINCODE_{day}_T0.CSV",
            f"https://www.bseindia.com/download/BhavCopy/Equity/EQ_ISINCODE_{day}.CSV",
            f"https://www.bseindia.com/download/BhavCopy/Equity/EQ_ISINCODE_{day}.ZIP",
        ]
        last_error = None
        for url in urls:
            try:
                response = self.session.get(url, timeout=60)
                if response.status_code == 404:
                    continue
                response.raise_for_status()
            except requests.RequestException as exc:
                last_error = exc
                continue
            if url.lower().endswith(".csv"):
                if self._is_csv_empty(response.text):
                    continue
                return response.text
            try:
                archive = zipfile.ZipFile(io.BytesIO(response.content))
            except zipfile.BadZipFile as exc:
                last_error = exc
                continue
            csv_text = self._extract_csv_from_archive(archive)
            if self._is_csv_empty(csv_text):
                continue
            return csv_text
        if last_error:
            LOGGER.debug("Direct BSE download failed: %s", last_error)
        return None

    def _download_form_based_bse_csv(self, as_of: date) -> str:
        day = as_of.strftime("%d%m%y")
        url = self.BSE_URL.format(day=day)
        tokens = self._retrieve_bse_tokens()
        self._submit_bse_form(tokens, as_of)

        try:
            response = self.session.get(url, timeout=60)
            response.raise_for_status()
        except requests.HTTPError as exc:
            if response.status_code == 403:
                LOGGER.debug("403 from BSE bhavcopy (%s); refreshing session", day)
                tokens = self._retrieve_bse_tokens()
                self._submit_bse_form(tokens, as_of)
                try:
                    response = self.session.get(url, timeout=60)
                    response.raise_for_status()
                except requests.RequestException as retry_exc:
                    raise BhavcopyError(
                        f"Unable to download BSE bhavcopy for {day}: {retry_exc}"
                    ) from retry_exc
            else:
                raise BhavcopyError(
                    f"Unable to download BSE bhavcopy for {day}: {exc}"
                ) from exc
        except requests.RequestException as exc:
            raise BhavcopyError(
                f"Unable to download BSE bhavcopy for {day}: {exc}"
            ) from exc

        try:
            archive = zipfile.ZipFile(io.BytesIO(response.content))
        except zipfile.BadZipFile as exc:
            raise BhavcopyError(f"BSE bhavcopy zip corrupt for {day}") from exc

        return self._extract_csv_from_archive(archive)

    @staticmethod
    def _is_csv_empty(payload: str) -> bool:
        if not payload:
            return True
        lines = [line for line in payload.splitlines() if line.strip()]
        return len(lines) <= 1

    def _load_local_nse_csv(self, as_of: date) -> Optional[str]:
        if not self.nse_local_dir:
            return None
        day = as_of.strftime("%d%m%Y")
        patterns = [
            f"mcap{day}*.csv",
            f"mcap{day}*.xlsx",
            f"MCAP{day}*.csv",
            f"MCAP{day}*.xlsx",
        ]
        for pattern in patterns:
            for candidate in sorted(self.nse_local_dir.glob(pattern)):
                try:
                    suffix = candidate.suffix.lower()
                    if suffix == ".xlsx":
                        return self._read_excel_as_csv(candidate)
                    LOGGER.debug("Using local NSE csv %s", candidate)
                    return candidate.read_text(encoding="utf-8")
                except Exception as exc:
                    LOGGER.warning("Unable to read local NSE file %s: %s", candidate, exc)
        return None

    def _download_nse_market_caps(self, day: str) -> str:
        # day is DDMMYYYY; the price report zip is named with DDMMYY.
        try:
            response = self.session.get(self.NSE_PR_URL.format(day=day[:4] + day[6:]), timeout=60)
            if response.status_code != 404:
                response.raise_for_status()
                with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                    name = next(
                        (n for n in archive.namelist() if n.lower() == f"mcap{day}.csv"), None
                    )
                    if name:
                        return archive.read(name).decode("utf-8", errors="replace")
        except (requests.RequestException, zipfile.BadZipFile) as exc:
            LOGGER.debug("NSE price report unavailable for %s: %s", day, exc)
        urls = [
            self.NSE_URL.format(day=day),
            f"https://archives.nseindia.com/content/equities/mcap/MCAP{day}.csv",
            f"https://archives.nseindia.com/content/equities/mcap/MCAP{day}.xlsx",
        ]
        for url in urls:
            try:
                response = self.session.get(url, timeout=60)
                if response.status_code == 404:
                    continue
                response.raise_for_status()
            except requests.RequestException:
                continue
            if url.lower().endswith(".xlsx"):
                return self._excel_bytes_to_csv(response.content)
            return response.text
        raise BhavcopyError(f"Unable to download NSE mcap file for {day}")

    def _excel_bytes_to_csv(self, payload: bytes) -> str:
        try:
            import pandas as pd
        except ImportError as exc:  # pragma: no cover
            raise BhavcopyError("pandas required to parse NSE Excel file") from exc
        df = pd.read_excel(io.BytesIO(payload))
        return df.to_csv(index=False)

    def _read_excel_as_csv(self, path: Path) -> str:
        try:
            import pandas as pd
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise BhavcopyError(
                f"openpyxl/pandas required to read {path.name}; install pandas."
            ) from exc
        LOGGER.debug("Using local NSE Excel %s", path)
        df = pd.read_excel(path)
        return df.to_csv(index=False)

    def _extract_isin_from_row(self, row: Dict[str, str]) -> Optional[str]:
        for key, value in row.items():
            if key and "isin" in key.lower():
                return (value or "").strip()
        return None

    def _build_company_lookup(self) -> Dict[str, BSEBhavRecord]:
        lookup: Dict[str, BSEBhavRecord] = {}
        for record in self._last_bse_records.values():
            key = self._normalize_company_name(record.company_name)
            if key and key not in lookup:
                lookup[key] = record
        return lookup

    def _normalize_company_name(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        cleaned = value.upper()
        for token in [" LIMITED", " LTD", "LIMITED", "LTD", " CO", " COMPANY", " THE"]:
            cleaned = cleaned.replace(token, "")
        cleaned = re.sub(r"[^A-Z0-9]", "", cleaned)
        return cleaned or None

    def _match_company_to_isin(
        self, row: Dict[str, str], lookup: Dict[str, BSEBhavRecord]
    ) -> Optional[str]:
        company = row.get("Company Name") or row.get("Company") or row.get("Security Name")
        symbol = row.get("Symbol")
        key = self._normalize_company_name(company)
        if key and key in lookup:
            return lookup[key].isin
        if key:
            for candidate_key, record in lookup.items():
                if key.startswith(candidate_key) or candidate_key.startswith(key):
                    return record.isin
        if symbol:
            sym_key = self._normalize_company_name(symbol)
            for record in lookup.values():
                rec_key = self._normalize_company_name(record.company_name)
                if sym_key and rec_key and sym_key in rec_key:
                    return record.isin
        return None

    def _infer_multiplier(self, column_name: str) -> float:
        label = column_name.lower()
        if "lakh" in label or "lac" in label:
            return 1e5
        if "cr" in label or "crore" in label:
            return 1e7
        return 1.0

    def _retrieve_bse_tokens(self) -> Dict[str, str]:
        try:
            response = self.session.get(self.BSE_PAGE, timeout=60)
            response.raise_for_status()
        except requests.RequestException as exc:
            LOGGER.warning("BSE form fetch failed: %s", exc)
            raise BhavcopyError("Unable to load BSE BhavCopy form") from exc

        tokens: Dict[str, str] = {}
        html_doc = response.text
        for name in self.HIDDEN_FIELDS:
            value = self._extract_hidden_value(html_doc, name)
            if value is not None:
                tokens[name] = value

        if "__VIEWSTATE" not in tokens or "__EVENTVALIDATION" not in tokens:
            try:
                from pathlib import Path
                debug_path = Path("cache/bse_form_debug.html")
                debug_path.parent.mkdir(parents=True, exist_ok=True)
                debug_path.write_text(html_doc, encoding="utf-8")
                LOGGER.warning("Wrote BSE form debug dump to %s", debug_path)
            except Exception as exc:  # pragma: no cover - best effort
                LOGGER.debug("Unable to persist BSE form debug HTML: %s", exc)
            raise BhavcopyError("Missing hidden fields in BSE BhavCopy form")
        return tokens

    def _extract_hidden_value(self, html_doc: str, name: str) -> Optional[str]:
        pattern = re.compile(
            r'name="{}"[^\>]*?value="([^"]*)"'.format(re.escape(name)),
            re.IGNORECASE | re.DOTALL,
        )
        match = pattern.search(html_doc)
        if not match:
            return None
        return html.unescape(match.group(1))

    def _submit_bse_form(self, tokens: Dict[str, str], as_of: date) -> None:
        payload = {
            "__EVENTTARGET": "",
            "__EVENTARGUMENT": "",
            "__VIEWSTATE": tokens.get("__VIEWSTATE", ""),
            "__VIEWSTATEGENERATOR": tokens.get("__VIEWSTATEGENERATOR", ""),
            "__VIEWSTATEENCRYPTED": tokens.get("__VIEWSTATEENCRYPTED", ""),
            "__EVENTVALIDATION": tokens.get("__EVENTVALIDATION", ""),
            "ctl00$ContentPlaceHolder1$Debt": "rbteqty",
            "ctl00$ContentPlaceHolder1$fdate1": str(as_of.day),
            "ctl00$ContentPlaceHolder1$fmonth1": str(as_of.month),
            "ctl00$ContentPlaceHolder1$fyear1": str(as_of.year),
            "ctl00$ContentPlaceHolder1$btnSubmit": "Submit",
            "ctl00$ContentPlaceHolder1$DDate": f"{as_of.year}-{as_of.day}-{as_of.month}",
        }

        try:
            response = self.session.post(
                self.BSE_PAGE,
                data=payload,
                timeout=60,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise BhavcopyError("Failed submitting BSE BhavCopy form") from exc
