from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from custom_components.viacqua.api import parsers

FIX = Path(__file__).parent / "fixtures"


def load(name: str) -> str:
    return (FIX / f"{name}.html").read_text()


def test_login_page_detection():
    assert parsers.is_login_page(load("login"))
    assert not parsers.is_login_page(load("home"))
    assert parsers.login_error(load("login")) is None


def test_login_form_fields():
    f = parsers.form_fields(load("login"))
    assert {"__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION"} <= f.keys()
    assert "boxLogin$Login1$UserName" in f
    assert "boxLogin$Login1$LoginButton" not in f  # submit buttons excluded
    assert "boxLogin$Login1$RememberMe" not in f  # unchecked


def test_logged_in_user():
    assert parsers.logged_in_user(load("home")) == "ROSSI MARIO"


def test_readings_page1():
    rows = parsers.parse_readings(load("consumi_p1"))
    assert len(rows) == 10
    r = rows[0]
    assert r.pdr == "0502400000000001"
    assert r.reading_date == date(2026, 7, 17)
    assert r.reading_m3 == 857
    assert r.consumption_m3 == 78
    assert r.reading_type == "Periodica"
    assert r.invoice_number == "768076"
    assert r.invoice_date == date(2026, 8, 13)
    unbilled = next(x for x in rows if x.reading_date == date(2023, 12, 31))
    assert unbilled.invoice_number is None and unbilled.invoice_date is None
    assert parsers.grid_pages(load("consumi_p1")) == (1, [1, 2])
    assert parsers.parse_reading_contracts(load("consumi_p1")) == {"201919000001": "2019-19000001"}


def test_readings_page2():
    rows = parsers.parse_readings(load("consumi_p2"))
    assert len(rows) == 9
    assert rows[-1].reading_type == "Apertura"
    assert rows[-1].reading_m3 == 0
    assert parsers.grid_pages(load("consumi_p2")) == (2, [1, 2])


def test_readings_are_consistent():
    rows = parsers.parse_readings(load("consumi_p1")) + parsers.parse_readings(load("consumi_p2"))
    dates = [r.reading_date for r in rows]
    assert dates == sorted(dates, reverse=True)


def test_invoices():
    inv = parsers.parse_invoices(load("bollette_p1"))
    assert len(inv) == 10
    first = inv[0]
    assert first.number == "768076"
    assert first.period == "202607"
    assert first.issue_date == date(2026, 8, 13)
    assert first.due_date == date(2026, 9, 14)
    assert first.amount == Decimal("212.65")
    assert first.outstanding == Decimal("159.49")
    assert first.paid is False
    assert first.download_button == "gv$ctl02$btnDownload"
    assert first.page == 1
    assert inv[1].paid is True
    assert parsers.grid_pages(load("bollette_p1")) == (1, [1, 2, 3])


def test_invoices_last_page():
    inv = parsers.parse_invoices(load("bollette_p3"))
    assert len(inv) == 8
    assert inv[-1].number == "328782"
    assert all(i.page == 3 for i in inv)
    assert inv[0].download_button == "gv$ctl02$btnDownload"  # page-relative names


def test_contracts():
    (c,) = parsers.parse_contracts(load("contratti"))
    assert c.contract_number == "19000001"
    assert c.start_date == date(2019, 3, 30)
    assert c.end_date is None
    assert c.detail_button == "gv$ctl02$btnDettaglio"


def test_contract_detail():
    d = parsers.parse_contract_detail(load("contratto_dettaglio"))
    assert d.contract["Stato contratto"] == "Aperto"
    assert d.contract["Periodicità fatturazione"] == "TRIMESTRALE"
    assert d.contract["Volume Annuale"] == "84"
    assert d.pdr["PDR"] == "0502400000000001"
    assert d.pdr["Data Inizio"] == "30/03/2019"
    assert d.cadastral["Codice Catastale"] == "L840"


def test_customer():
    c = parsers.parse_customer(load("anagrafica"))
    assert c.fields["Nominativo"] == "ROSSI MARIO"
    assert c.fields["Servizio"] == "ACQUA"


def test_self_reading():
    s = parsers.parse_self_reading(load("autolettura"))
    assert s.contract_value == "2019-19000001N"
    assert s.previous_reading_date == date(2026, 7, 17)
    assert s.previous_reading_m3 == 857
    assert (s.allowed_min_m3, s.allowed_max_m3) == (857, 905)
    assert s.reading_type == "Periodica"


def test_activities():
    a = parsers.parse_activities(load("storico"))
    assert [x.text for x in a] == [
        "Richiesta di Sepa evasa il 12/18/2019 alle ore 8:21 AM",
        "Richiesta di Sepa rifiutata il 12/16/2019 alle ore 5:32 PM",
    ]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("212,65 €", Decimal("212.65")), ("1.212,65 €", Decimal("1212.65")), ("0,00", Decimal("0")), ("", Decimal("0"))],
)
def test_eur(raw, expected):
    assert parsers._eur(raw) == expected


def test_cfemail():
    # "a@b.it" xor 0x42
    key = 0x42
    enc = f"{key:02x}" + "".join(f"{ord(c) ^ key:02x}" for c in "a@b.it")
    assert parsers.decode_cfemail(enc) == "a@b.it"
