"""Data models returned by the Viacqua portal client."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any


def _jsonable(value: Any) -> Any:
    if isinstance(value, (date, Decimal)):
        return str(value)
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return value


class _Base:
    def as_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))  # type: ignore[call-overload]


@dataclass(frozen=True)
class MeterReading(_Base):
    """One row of Consumi -> "Tieni sempre sotto controllo i tuoi consumi".

    `reading_m3` is the cumulative meter index (m³); `consumption_m3` is the
    delta since the previous reading as computed by Viacqua.
    """

    pdr: str  # POD/PDR – supply point id
    pde_code: str  # "Codice PDE" (idSede)
    reading_date: date
    reading_m3: int
    consumption_m3: int
    reading_type: str  # Periodica, Apertura, Autolettura, Stimata, ...
    meter_serial: str  # Matricola
    invoice_number: str | None  # Nro Fattura ("-" when not billed yet)
    invoice_date: date | None
    source_pde: str | None = None  # hidden column IdSede_Ori
    source: str | None = None  # hidden column FonteDato ("consorzio")


@dataclass(frozen=True)
class Invoice(_Base):
    """One row of Fatture."""

    number: str
    period: str  # "Competenza al" as YYYYMM
    issue_date: date
    due_date: date | None
    service: str  # "AC" = acqua
    amount: Decimal  # EUR
    paid: bool
    outstanding: Decimal  # "Residuo", EUR
    download_button: str | None  # form field name used to download the PDF (page-local!)
    page: int = 1  # grid page the row was found on (needed to download the PDF)


@dataclass(frozen=True)
class Contract(_Base):
    """One row of Contratti."""

    customer_code: str  # Codice Nominativo
    contract_number: str
    holder: str  # Ragione sociale
    service: str
    year: str
    start_date: date | None
    end_date: date | None
    detail_button: str | None


@dataclass
class ContractDetail(_Base):
    """Contratti -> Vedi dettaglio (ContrattiDettaglioAC.aspx). Free-form key/value tabs."""

    contract: dict[str, str] = field(default_factory=dict)
    pdr: dict[str, str] = field(default_factory=dict)
    cadastral: dict[str, str] = field(default_factory=dict)
    extra_tabs: dict[str, dict[str, str]] = field(default_factory=dict)


@dataclass
class Customer(_Base):
    """Anagrafica."""

    fields: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SelfReadingInfo(_Base):
    """AutoLettura page state: what Viacqua expects for the next self reading."""

    contract_value: str  # value for ctrlAutoLetture1$ddlContratto
    contract_label: str
    reading_type: str | None
    previous_reading_date: date | None
    previous_reading_m3: int | None
    allowed_min_m3: int | None
    allowed_max_m3: int | None
    reading_date: date | None  # date the portal will stamp on the new reading
    message: str | None


@dataclass(frozen=True)
class Activity(_Base):
    """Storico richieste – free text lines."""

    text: str
