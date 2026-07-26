from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


VEHICLE_FIELDS = (
    "make",
    "model",
    "badge",
    "transmission_type",
    "fuel_type",
    "drive_type",
)
IDENTITY_FIELDS = ("make", "model", "badge")
FIELD_WEIGHTS = {
    "make": 2.0,
    "model": 2.5,
    "badge": 2.0,
    "transmission_type": 1.2,
    "fuel_type": 1.1,
    "drive_type": 1.2,
}


VehicleFields = dict[str, str | None]
MatchStatus = Literal[
    "MATCHED",
    "NO_CATALOGUE_MATCH",
    "NO_VEHICLE",
    "AMBIGUOUS",
    "INCOMPLETE",
]


@dataclass(frozen=True, slots=True)
class VehicleRecord:
    id: str
    make: str
    model: str
    badge: str
    transmission_type: str
    fuel_type: str
    drive_type: str
    listing_count: int = 0

    def value(self, field: str) -> str:
        return getattr(self, field)


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    vehicle_present: bool
    is_complete: bool
    fields: VehicleFields


@dataclass(frozen=True, slots=True)
class FieldResolution:
    raw: str | None
    value: str | None
    is_catalogue_value: bool
    method: Literal["missing", "exact", "alias", "fuzzy", "open_world"]


@dataclass(frozen=True, slots=True)
class MatchDecision:
    vehicle_id: str | None
    confidence: int
    status: MatchStatus
    is_complete: bool
    is_decisive: bool
    fields: VehicleFields
