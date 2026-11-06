"""Pure HTML -> model parsers for the Viacqua (blucrm) customer portal.

Everything here is side-effect free so it can be unit-tested against the
fixtures in tests/fixtures/.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from bs4 import BeautifulSoup, Tag

from .models import (
    Activity,
    Contract,
    ContractDetail,
    Customer,
    Invoice,
    MeterReading,
    SelfReadingInfo,
)

LOGIN_USER_FIELD = "boxLogin$Login1$UserName"

_PAGE_RE = re.compile(r"__doPostBack\('([^']+)','Page\$(\d+)'\)")


def soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def _text(node: Tag | None) -> str:
    if node is None:
        return ""
    return " ".join(node.get_text(" ", strip=True).replace("\xa0", " ").split())


def _date(value: str) -> date | None:
    value = value.strip()
    if not value or value == "-":
        return None
    return datetime.strptime(value, "%d/%m/%Y").date()


def _int(value: str) -> int | None:
    value = value.strip().replace(".", "")
    if not value or value == "-":
        return None
    return int(value)


def _eur(value: str) -> Decimal:
    """'1.212,65 €' -> Decimal('1212.65')."""
    cleaned = value.replace("€", "").replace("\xa0", "").strip().replace(".", "").replace(",", ".")
    if not cleaned or cleaned == "-":
        return Decimal("0")
    try:
        return Decimal(cleaned)
    except InvalidOperation as err:
        raise ValueError(f"Not an amount: {value!r}") from err


def decode_cfemail(encoded: str) -> str | None:
    """Decode Cloudflare's e-mail obfuscation (data-cfemail attribute)."""
    try:
        data = bytes.fromhex(encoded)
    except ValueError:
        return None
    if not data:
        return None
    key = data[0]
    return bytes(b ^ key for b in data[1:]).decode("utf-8", "replace")


def _cell_text(td: Tag) -> str:
    cf = td.select_one("[data-cfemail]")
    if cf is not None:
        decoded = decode_cfemail(str(cf["data-cfemail"]))
        if decoded:
            return decoded
    return _text(td)


# --------------------------------------------------------------------------- #
# Generic ASP.NET WebForms helpers
# --------------------------------------------------------------------------- #


def is_login_page(html: str) -> bool:
    return LOGIN_USER_FIELD in html


def login_error(html: str) -> str | None:
    doc = soup(html)
    node = doc.select_one("#boxLogin_Login1_loginerror")
    msg = _text(node)
    return msg or None


def form_fields(html: str) -> dict[str, str]:
    """Return the values a browser would post for the page's main form.

    Submit/image buttons are excluded (add the one you "click" yourself),
    unchecked checkboxes/radios are skipped, disabled controls are skipped.
    """
    doc = soup(html)
    form = doc.find("form")
    if form is None:
        raise ValueError("No <form> in page")
    out: dict[str, str] = {}
    for el in form.find_all(["input", "select", "textarea"]):
        name = el.get("name")
        if not name or el.has_attr("disabled"):
            continue
        if el.name == "input":
            typ = (el.get("type") or "text").lower()
            if typ in {"submit", "image", "button", "reset", "file"}:
                continue
            if typ in {"checkbox", "radio"} and not el.has_attr("checked"):
                continue
            out[name] = el.get("value", "on" if typ in {"checkbox", "radio"} else "")
        elif el.name == "select":
            opt = el.find("option", selected=True) or el.find("option")
            out[name] = opt.get("value", _text(opt)) if opt else ""
        else:
            out[name] = el.get_text()
    return out


def grid_pages(html: str, grid_id: str = "gv") -> tuple[int, list[int]]:
    """Return (current_page, all_known_pages) for an ASP.NET GridView pager."""
    doc = soup(html)
    grid = doc.find(id=grid_id)
    if grid is None:
        return 1, [1]
    pages: set[int] = set()
    current = 1
    for row in grid.find_all("tr"):
        inner = row.find("table")
        if inner is None:
            continue
        for td in inner.find_all("td"):
            a = td.find("a")
            if a is not None:
                m = _PAGE_RE.search(a.get("href", ""))
                if m:
                    pages.add(int(m.group(2)))
            else:
                span = td.find("span")
                if span is not None and _text(span).isdigit():
                    current = int(_text(span))
                    pages.add(current)
    pages.add(current)
    return current, sorted(pages)


def _grid_rows(html: str, grid_id: str = "gv") -> list[Tag]:
    doc = soup(html)
    grid = doc.find(id=grid_id)
    if grid is None:
        return []
    rows: list[Tag] = []
    for tr in grid.find_all("tr", recursive=False) or grid.select(":scope > tbody > tr"):
        if tr.find("th") or tr.find("table"):
            continue  # header / pager
        rows.append(tr)
    return rows


# --------------------------------------------------------------------------- #
# Page parsers
# --------------------------------------------------------------------------- #


def parse_readings(html: str) -> list[MeterReading]:
    """Consumi/ConsumiWebGas.aspx grid `gv`."""
    out: list[MeterReading] = []
    for tr in _grid_rows(html):
        c = [_text(td) for td in tr.find_all("td", recursive=False)]
        if len(c) < 9:
            continue
        inv = c[7] if c[7] not in ("", "-") else None
        out.append(
            MeterReading(
                pdr=c[0],
                pde_code=c[1],
                reading_date=_date(c[2]),  # type: ignore[arg-type]
                reading_m3=_int(c[3]) or 0,
                consumption_m3=_int(c[4]) or 0,
                reading_type=c[5],
                meter_serial=c[6],
                invoice_number=inv,
                invoice_date=_date(c[8]),
                source_pde=(c[9] or None) if len(c) > 9 else None,
                source=(c[10] or None) if len(c) > 10 else None,
            )
        )
    return out


def parse_reading_contracts(html: str) -> dict[str, str]:
    """Contract selector (ddlContratto) on the Consumi page: value -> label."""
    doc = soup(html)
    sel = doc.find("select", attrs={"name": "ddlContratto"})
    if sel is None:
        return {}
    return {o.get("value", ""): _text(o) for o in sel.find_all("option")}


def parse_invoices(html: str, page: int | None = None) -> list[Invoice]:
    """Bollette/VisualizzaBollette.aspx grid `gv`."""
    if page is None:
        page, _ = grid_pages(html)
    out: list[Invoice] = []
    for tr in _grid_rows(html):
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 9:
            continue
        c = [_text(td) for td in tds]
        cb = tds[6].find("input", attrs={"type": "checkbox"})
        btn = tds[8].find("input", attrs={"type": "submit"})
        out.append(
            Invoice(
                number=c[0],
                period=c[1],
                issue_date=_date(c[2]),  # type: ignore[arg-type]
                due_date=_date(c[3]),
                service=c[4],
                amount=_eur(c[5]),
                paid=bool(cb is not None and cb.has_attr("checked")),
                outstanding=_eur(c[7]),
                download_button=btn.get("name") if btn else None,
                page=page,
            )
        )
    return out


def parse_contracts(html: str) -> list[Contract]:
    """Contratti/VisualizzaContratti.aspx grid `gv`."""
    out: list[Contract] = []
    for tr in _grid_rows(html):
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 7:
            continue
        c = [_text(td) for td in tds]
        btn = tds[7].find("input") if len(tds) > 7 else None
        out.append(
            Contract(
                customer_code=c[0],
                contract_number=c[1],
                holder=c[2],
                service=c[3],
                year=c[4],
                start_date=_date(c[5]),
                end_date=_date(c[6]),
                detail_button=btn.get("name") if btn else None,
            )
        )
    return out


def _details_view(table: Tag | None) -> dict[str, str]:
    if table is None:
        return {}
    out: dict[str, str] = {}
    for tr in table.find_all("tr"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) != 2:
            continue
        key = _text(tds[0]).lstrip("- ").strip()
        out[key] = _cell_text(tds[1])
    return out


def parse_contract_detail(html: str) -> ContractDetail:
    """Contratti/ContrattiDettaglioAC.aspx (tabs: Contratti, PDR, Catastali, ...)."""
    doc = soup(html)
    detail = ContractDetail(
        contract=_details_view(doc.find(id="dvContratto")),
        pdr=_details_view(doc.find(id="dvPdr")),
        cadastral=_details_view(doc.find(id="dvCatasto")),
    )
    for tab in ("tabs-4", "tabs-5", "tabs-6"):
        div = doc.find(id=tab)
        if div is None:
            continue
        label_a = doc.find("a", href=f"#{tab}")
        label = _text(label_a) or tab
        tables = div.find_all("table")
        data: dict[str, str] = {}
        for t in tables:
            data.update(_details_view(t))
        if not data and _text(div):
            data["text"] = _text(div)
        if data:
            detail.extra_tabs[label] = data
    return detail


def parse_customer(html: str) -> Customer:
    """Anagrafica/Ricerca_Anagrafica.aspx details view `dv`."""
    return Customer(fields=_details_view(soup(html).find(id="dv")))


def parse_self_reading(html: str) -> SelfReadingInfo:
    """AutoConsumo/AutoLettura.aspx."""
    doc = soup(html)

    def span(suffix: str) -> str:
        return _text(doc.find(id=f"ctrlAutoLetture1_{suffix}"))

    sel = doc.find("select", attrs={"name": "ctrlAutoLetture1$ddlContratto"})
    opt = (sel.find("option", selected=True) or sel.find("option")) if sel else None
    rng = re.findall(r"\d+", span("lblLetturaStimataDescr"))
    max_hidden = doc.find("input", attrs={"name": "ctrlAutoLetture1$HFrangemax"})
    date_input = doc.find("input", attrs={"name": "ctrlAutoLetture1$txtDataLetturaDescr"})
    allowed_max = _int(max_hidden.get("value", "")) if max_hidden else None
    if allowed_max is None and len(rng) > 1:
        allowed_max = int(rng[1])
    return SelfReadingInfo(
        contract_value=opt.get("value", "") if opt else "",
        contract_label=_text(opt) if opt else "",
        reading_type=span("lblTipoLetturaDescr") or None,
        previous_reading_date=_date(span("lblDataLetturaPrecDescr")),
        previous_reading_m3=_int(span("lblLettPrecedenteDescr")),
        allowed_min_m3=int(rng[0]) if rng else None,
        allowed_max_m3=allowed_max,
        reading_date=_date(date_input.get("value", "")) if date_input else None,
        message=span("lblmsgavviso") or None,
    )


def parse_activities(html: str) -> list[Activity]:
    """Attivita/StatoAttivita.aspx – free text separated by <br>."""
    doc = soup(html)
    box = doc.select_one(".elencoAttivita")
    if box is None:
        return []
    lines = [" ".join(s.split()) for s in box.get_text("\n").split("\n")]
    return [Activity(text=line) for line in lines if line]


def logged_in_user(html: str) -> str | None:
    return _text(soup(html).find(id="boxHeader_boxHeader1_lblUtenteCollegato")) or None
