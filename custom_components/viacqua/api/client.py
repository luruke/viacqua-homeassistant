"""Async client for the Viacqua customer portal (https://sol.viacqua.it).

The portal is an ASP.NET WebForms app ("blucrm" CRM). There is no JSON API:
every action is a GET of an .aspx page or a form POST-back carrying the
page's __VIEWSTATE / __EVENTVALIDATION. Authentication is a forms-auth
cookie set by the login POST. See docs/API.md for the full map.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import aiohttp

from . import parsers
from .models import (
    Activity,
    Contract,
    ContractDetail,
    Customer,
    Invoice,
    MeterReading,
    SelfReadingInfo,
)

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://sol.viacqua.it/CRM_20_Multi/"
LOGIN_PATH = "Ingresso_Home.aspx"
HOME_PATH = "Home/Edit_Home.aspx"
READINGS_PATH = "Consumi/ConsumiWebGas.aspx?id=19"
INVOICES_PATH = "Bollette/VisualizzaBollette.aspx?id=17"
CONTRACTS_PATH = "Contratti/VisualizzaContratti.aspx?id=24"
CUSTOMER_PATH = "Anagrafica/Ricerca_Anagrafica.aspx?id=3"
SELF_READING_PATH = "AutoConsumo/AutoLettura.aspx?id=22"
ACTIVITIES_PATH = "Attivita/StatoAttivita.aspx?id=25"
LOGOUT_PATH = "Login/LogOut.aspx"

# The site is "optimised for IE9"; any modern UA works.
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; viacqua-homeassistant)",
    "Accept-Language": "it-IT,it;q=0.9",
}


class ViacquaError(Exception):
    """Generic portal error."""


class ViacquaAuthError(ViacquaError):
    """Bad credentials or the session could not be (re)established."""


@dataclass
class _Page:
    url: str
    html: str


class ViacquaClient:
    """Stateful client. Re-logs in transparently when the session expires."""

    def __init__(
        self,
        username: str,
        password: str,
        session: aiohttp.ClientSession | None = None,
        base_url: str = BASE_URL,
    ) -> None:
        self._username = username
        self._password = password
        self._base = base_url
        self._own_session = session is None
        # The auth cookie must be stored per-client: give the client its own jar
        # when we create the session. (In HA use async_create_clientsession().)
        self._session = session or aiohttp.ClientSession(
            headers=DEFAULT_HEADERS, cookie_jar=aiohttp.CookieJar()
        )
        self._logged_in = False
        self.display_name: str | None = None

    async def close(self) -> None:
        if self._own_session:
            await self._session.close()

    async def __aenter__(self) -> ViacquaClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    # ------------------------------------------------------------------ #
    # low level
    # ------------------------------------------------------------------ #

    def _url(self, path: str) -> str:
        return path if path.startswith("http") else self._base + path

    async def _request(self, method: str, url: str, data: dict[str, str] | None = None) -> _Page:
        async with self._session.request(
            method, url, data=data, allow_redirects=True, headers=DEFAULT_HEADERS
        ) as resp:
            resp.raise_for_status()
            html = await resp.text(errors="replace")
            return _Page(str(resp.url), html)

    async def login(self) -> None:
        page = await self._request("GET", self._url(LOGIN_PATH))
        fields = parsers.form_fields(page.html)
        fields.update(
            {
                "__EVENTTARGET": "",
                "__EVENTARGUMENT": "",
                "boxLogin$Login1$UserName": self._username,
                "boxLogin$Login1$Password": self._password,
                "boxLogin$Login1$RememberMe": "on",
                "boxLogin$Login1$LoginButton": "Entra",
            }
        )
        # Login POST -> 302 Home/landingPage.aspx -> 302 Home/Edit_Home.aspx
        result = await self._request("POST", self._url(LOGIN_PATH), fields)
        if parsers.is_login_page(result.html):
            msg = parsers.login_error(result.html) or "login rejected"
            raise ViacquaAuthError(msg)
        self._logged_in = True
        self.display_name = parsers.logged_in_user(result.html)
        _LOGGER.debug("Logged in as %s (landed on %s)", self.display_name, result.url)

    async def _get(self, path: str) -> _Page:
        if not self._logged_in:
            await self.login()
        page = await self._request("GET", self._url(path))
        if parsers.is_login_page(page.html):  # session expired -> redirected to login
            self._logged_in = False
            await self.login()
            page = await self._request("GET", self._url(path))
            if parsers.is_login_page(page.html):
                raise ViacquaAuthError("Session lost right after login")
        return page

    async def _postback(
        self,
        page: _Page,
        target: str = "",
        argument: str = "",
        extra: dict[str, str] | None = None,
    ) -> _Page:
        """Replay an ASP.NET postback from `page` (same URL)."""
        fields = parsers.form_fields(page.html)
        fields["__EVENTTARGET"] = target
        fields["__EVENTARGUMENT"] = argument
        if extra:
            fields.update(extra)
        result = await self._request("POST", page.url, fields)
        if parsers.is_login_page(result.html):
            self._logged_in = False
            raise ViacquaAuthError("Session expired during postback")
        return result

    async def _all_grid_pages(self, path: str) -> list[_Page]:
        first = await self._get(path)
        pages = [first]
        current = first
        seen = {1}
        while True:
            cur, known = parsers.grid_pages(current.html)
            nxt = next((p for p in known if p > cur and p not in seen), None)
            if nxt is None:
                break
            current = await self._postback(current, "gv", f"Page${nxt}")
            seen.add(nxt)
            pages.append(current)
        return pages

    # ------------------------------------------------------------------ #
    # high level
    # ------------------------------------------------------------------ #

    async def get_readings(self) -> list[MeterReading]:
        """All meter readings (whole history, all grid pages), newest first.

        Only the currently selected contract is returned; if you have several
        contracts use `get_readings_for_contract`.
        """
        out: list[MeterReading] = []
        for page in await self._all_grid_pages(READINGS_PATH):
            out.extend(parsers.parse_readings(page.html))
        return out

    async def get_reading_contracts(self) -> dict[str, str]:
        page = await self._get(READINGS_PATH)
        return parsers.parse_reading_contracts(page.html)

    async def get_readings_for_contract(self, contract_value: str) -> list[MeterReading]:
        first = await self._get(READINGS_PATH)
        page = await self._postback(first, "ddlContratto", "", {"ddlContratto": contract_value})
        out = parsers.parse_readings(page.html)
        seen = {1}
        while True:
            cur, known = parsers.grid_pages(page.html)
            nxt = next((p for p in known if p > cur and p not in seen), None)
            if nxt is None:
                return out
            page = await self._postback(page, "gv", f"Page${nxt}")
            seen.add(nxt)
            out.extend(parsers.parse_readings(page.html))

    async def get_invoices(self) -> list[Invoice]:
        """All invoices (all grid pages), newest first."""
        out: list[Invoice] = []
        for page in await self._all_grid_pages(INVOICES_PATH):
            out.extend(parsers.parse_invoices(page.html))
        return out

    async def download_invoice_pdf(self, invoice: Invoice) -> tuple[str, bytes]:
        """Return (filename, pdf_bytes) for an invoice from `get_invoices()`.

        Clicking "Scarica" POSTs the grid page; the server answers with a 302 to
        Download.aspx?f=<opaque token> which streams the PDF.
        """
        if not invoice.download_button:
            raise ViacquaError(f"Invoice {invoice.number} has no PDF")
        page = await self._get(INVOICES_PATH)
        if invoice.page != 1:
            page = await self._postback(page, "gv", f"Page${invoice.page}")
        # Re-locate the row (control names are page-relative: gv$ctl02.. per page)
        btn = next(
            (i.download_button for i in parsers.parse_invoices(page.html) if i.number == invoice.number),
            None,
        )
        if btn is None:
            raise ViacquaError(f"Invoice {invoice.number} not found on page {invoice.page}")
        fields = parsers.form_fields(page.html)
        fields.update({"__EVENTTARGET": "", "__EVENTARGUMENT": "", btn: "Scarica"})
        async with self._session.post(page.url, data=fields, allow_redirects=True) as resp:
            resp.raise_for_status()
            body = await resp.read()
            if not body.startswith(b"%PDF"):
                raise ViacquaError("Download did not return a PDF")
            cd = resp.headers.get("Content-Disposition", "")
            filename = cd.split("filename=")[-1].strip('"; ') if "filename=" in cd else f"{invoice.number}.pdf"
            return filename, body

    async def get_contracts(self) -> list[Contract]:
        page = await self._get(CONTRACTS_PATH)
        return parsers.parse_contracts(page.html)

    async def get_contract_detail(self, contract: Contract | None = None) -> ContractDetail:
        """Contract/PDR/cadastral details. Defaults to the first contract."""
        page = await self._get(CONTRACTS_PATH)
        contracts = parsers.parse_contracts(page.html)
        if not contracts:
            raise ViacquaError("No contracts")
        target = contract or contracts[0]
        btn = next(
            (c.detail_button for c in contracts if c.contract_number == target.contract_number),
            None,
        )
        if btn is None:
            raise ViacquaError(f"Contract {target.contract_number} not found")
        # Button POST -> 302 ContrattiDettaglioAC.aspx?par=<opaque token>
        result = await self._postback(page, extra={btn: "Vedi dettaglio"})
        return parsers.parse_contract_detail(result.html)

    async def get_customer(self) -> Customer:
        page = await self._get(CUSTOMER_PATH)
        return parsers.parse_customer(page.html)

    async def get_self_reading_info(self) -> SelfReadingInfo:
        page = await self._get(SELF_READING_PATH)
        return parsers.parse_self_reading(page.html)

    async def submit_self_reading(self, reading_m3: int, *, confirm: bool = False) -> str:
        """Submit a self reading (autolettura). UNTESTED against the live site.

        Pass confirm=True to actually send it; otherwise this only validates the
        value against the allowed range and returns a dry-run message.
        """
        page = await self._get(SELF_READING_PATH)
        info = parsers.parse_self_reading(page.html)
        if info.allowed_min_m3 is not None and reading_m3 < info.allowed_min_m3:
            raise ViacquaError(f"Reading {reading_m3} below allowed minimum {info.allowed_min_m3}")
        if info.allowed_max_m3 is not None and reading_m3 > info.allowed_max_m3:
            raise ViacquaError(f"Reading {reading_m3} above allowed maximum {info.allowed_max_m3}")
        if not confirm:
            return f"dry-run: would submit {reading_m3} m³ for {info.contract_label}"
        result = await self._postback(
            page,
            extra={
                "ctrlAutoLetture1$txtLettura": str(reading_m3),
                "ctrlAutoLetture1$btnConfermaLettura": "Conferma",
            },
        )
        after = parsers.parse_self_reading(result.html)
        return after.message or "submitted (no message returned)"

    async def get_activities(self) -> list[Activity]:
        page = await self._get(ACTIVITIES_PATH)
        return parsers.parse_activities(page.html)

    async def logout(self) -> None:
        if self._logged_in:
            await self._request("GET", self._url(LOGOUT_PATH))
            self._logged_in = False
