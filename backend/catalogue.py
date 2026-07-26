from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Mapping

from rapidfuzz import fuzz, process

from .domain import (
    FIELD_WEIGHTS,
    IDENTITY_FIELDS,
    VEHICLE_FIELDS,
    ExtractionResult,
    FieldResolution,
    MatchDecision,
    VehicleRecord,
)


FUZZY_THRESHOLDS = {
    "make": 92.0,
    "model": 90.0,
    "badge": 86.0,
    "transmission_type": 94.0,
    "fuel_type": 94.0,
    "drive_type": 94.0,
}
FUZZY_MARGIN = 4.0
FUZZY_MIN_LENGTH = 4

TECHNICAL_EQUIVALENTS = {
    "transmission_type": (
        {"automatic", "auto", "at"},
        {"manual", "man", "mt", "stick", "stickshift"},
        {"cvt", "continuouslyvariable", "continuouslyvariabletransmission"},
        {"dct", "dualclutch", "dualclutchtransmission"},
    ),
    "fuel_type": (
        {"petrol", "gasoline", "gas"},
        {"diesel"},
        {"electric", "ev", "bev", "batteryelectric"},
        {"hybrid", "hev"},
        {"pluginhybrid", "phev", "plugin"},
        {"lpg", "autogas"},
    ),
    "drive_type": (
        {"awd", "allwheel", "allwheeldrive"},
        {"4wd", "4x4", "fourwheel", "fourwheeldrive"},
        {"fwd", "frontwheel", "frontwheeldrive"},
        {"rwd", "rearwheel", "rearwheeldrive"},
    ),
}


def normalize(value: str) -> str:
    text = unicodedata.normalize("NFKD", value).casefold()
    text = "".join(character for character in text if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", "", text)


def clean_open_world_value(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(str(value).strip().split())
    return cleaned or None


class Catalogue:
    def __init__(
        self,
        records: Iterable[VehicleRecord],
        aliases: Mapping[str, Mapping[str, str]] | None = None,
    ) -> None:
        self.records = tuple(records)
        self._all_indices = frozenset(range(len(self.records)))
        self._index: dict[str, dict[str, frozenset[int]]] = {}
        self._values: dict[str, dict[str, str]] = {}

        for field in VEHICLE_FIELDS:
            positions: dict[str, set[int]] = defaultdict(set)
            values: dict[str, str] = {}
            for index, record in enumerate(self.records):
                value = record.value(field)
                key = normalize(value)
                positions[key].add(index)
                values.setdefault(key, value)
            self._index[field] = {
                key: frozenset(indices) for key, indices in positions.items()
            }
            self._values[field] = values

        self._aliases: dict[str, dict[str, str]] = {field: {} for field in VEHICLE_FIELDS}
        for field, field_aliases in (aliases or {}).items():
            if field not in self._aliases:
                continue
            self._aliases[field].update(
                {
                    normalize(alias): canonical
                    for alias, canonical in field_aliases.items()
                    if normalize(alias)
                }
            )

    def resolve(self, fields: Mapping[str, str | None]) -> dict[str, FieldResolution]:
        resolutions: dict[str, FieldResolution] = {}
        identity_scope = self._all_indices

        for field in VEHICLE_FIELDS:
            raw = clean_open_world_value(fields.get(field))
            if raw is None:
                resolutions[field] = FieldResolution(None, None, False, "missing")
                continue

            scope = identity_scope if field in {"model", "badge"} and identity_scope else self._all_indices
            available = self._available_values(field, scope)
            resolution = self._resolve_value(field, raw, available)
            resolutions[field] = resolution

            if field in IDENTITY_FIELDS and resolution.is_catalogue_value and resolution.value:
                identity_scope = identity_scope.intersection(
                    self._index[field][normalize(resolution.value)]
                )

        return resolutions

    def match(self, extraction: ExtractionResult) -> MatchDecision:
        resolutions = self.resolve(extraction.fields)
        output_fields = {field: resolutions[field].value for field in VEHICLE_FIELDS}

        if not extraction.vehicle_present:
            return MatchDecision(
                vehicle_id=None,
                confidence=10 if extraction.is_complete else 6,
                status="NO_VEHICLE",
                is_complete=extraction.is_complete,
                is_decisive=extraction.is_complete,
                fields=output_fields,
            )

        provided = [field for field in VEHICLE_FIELDS if resolutions[field].raw is not None]
        identity_provided = [field for field in IDENTITY_FIELDS if resolutions[field].raw is not None]
        if not provided or not identity_provided:
            return MatchDecision(
                vehicle_id=None,
                confidence=self._incomplete_confidence(resolutions, extraction.is_complete),
                status="INCOMPLETE",
                is_complete=extraction.is_complete,
                is_decisive=False,
                fields=output_fields,
            )

        candidates = set(self._all_indices)
        for field in provided:
            resolution = resolutions[field]
            if not resolution.is_catalogue_value or not resolution.value:
                candidates.clear()
                break
            candidates.intersection_update(self._index[field][normalize(resolution.value)])

        if not candidates:
            return MatchDecision(
                vehicle_id=None,
                confidence=self._no_match_confidence(resolutions, extraction.is_complete),
                status="NO_CATALOGUE_MATCH",
                is_complete=extraction.is_complete,
                is_decisive=extraction.is_complete,
                fields=output_fields,
            )

        ranked = sorted(
            (self.records[index] for index in candidates),
            key=lambda record: (-record.listing_count, record.id),
        )
        winner = ranked[0]
        unique = len(ranked) == 1
        listing_breaks_tie = len(ranked) > 1 and winner.listing_count > ranked[1].listing_count
        decisive = unique or listing_breaks_tie
        status = "MATCHED" if decisive else "AMBIGUOUS"
        return MatchDecision(
            vehicle_id=winner.id,
            confidence=self._match_confidence(resolutions, extraction.is_complete, ranked),
            status=status,
            is_complete=extraction.is_complete,
            is_decisive=decisive,
            fields=output_fields,
        )

    def _available_values(self, field: str, scope: frozenset[int]) -> dict[str, str]:
        if scope == self._all_indices:
            return self._values[field]
        return {
            key: canonical
            for key, canonical in self._values[field].items()
            if self._index[field][key].intersection(scope)
        }

    def _resolve_value(
        self, field: str, raw: str, available: Mapping[str, str]
    ) -> FieldResolution:
        key = normalize(raw)
        if not key:
            return FieldResolution(raw, raw, False, "open_world")
        if key in available:
            return FieldResolution(raw, available[key], True, "exact")

        database_alias = self._aliases[field].get(key)
        if database_alias:
            canonical_key = normalize(database_alias)
            if canonical_key in available:
                return FieldResolution(raw, available[canonical_key], True, "alias")

        equivalent = self._technical_equivalent(field, key, available)
        if equivalent:
            return FieldResolution(raw, equivalent, True, "alias")

        if len(key) >= FUZZY_MIN_LENGTH and available:
            matches = process.extract(
                key,
                available.keys(),
                scorer=fuzz.WRatio,
                limit=2,
                score_cutoff=FUZZY_THRESHOLDS[field],
            )
            if matches:
                best_key, best_score, _ = matches[0]
                second_score = matches[1][1] if len(matches) > 1 else 0.0
                if best_score - second_score >= FUZZY_MARGIN:
                    return FieldResolution(raw, available[best_key], True, "fuzzy")

        return FieldResolution(raw, raw, False, "open_world")

    @staticmethod
    def _technical_equivalent(
        field: str, key: str, available: Mapping[str, str]
    ) -> str | None:
        for group in TECHNICAL_EQUIVALENTS.get(field, ()):
            if key not in group:
                continue
            for equivalent in group:
                if equivalent in available:
                    return available[equivalent]
        return None

    @staticmethod
    def _evidence_score(resolutions: Mapping[str, FieldResolution]) -> float:
        score = 0.0
        for field, weight in FIELD_WEIGHTS.items():
            resolution = resolutions[field]
            if not resolution.is_catalogue_value:
                continue
            score += weight
            if resolution.method == "fuzzy":
                score -= 0.4
            elif resolution.method == "alias":
                score -= 0.1
        return score

    def _match_confidence(
        self,
        resolutions: Mapping[str, FieldResolution],
        is_complete: bool,
        ranked: list[VehicleRecord],
    ) -> int:
        score = self._evidence_score(resolutions)
        if len(ranked) == 1:
            score += 0.5
        elif ranked[0].listing_count == ranked[1].listing_count:
            score -= 1.0
        else:
            score -= 0.5
        if not is_complete:
            score -= 1.0
        return self._bounded_score(score)

    def _no_match_confidence(
        self, resolutions: Mapping[str, FieldResolution], is_complete: bool
    ) -> int:
        provided_count = sum(resolution.raw is not None for resolution in resolutions.values())
        open_world_count = sum(
            resolution.method == "open_world" for resolution in resolutions.values()
        )
        score = 5.0 + min(3.0, provided_count * 0.65) + min(1.0, open_world_count * 0.5)
        if is_complete:
            score += 1.0
        return self._bounded_score(score)

    def _incomplete_confidence(
        self, resolutions: Mapping[str, FieldResolution], is_complete: bool
    ) -> int:
        score = min(4.0, self._evidence_score(resolutions))
        if not is_complete:
            score -= 1.0
        return self._bounded_score(score)

    @staticmethod
    def _bounded_score(score: float) -> int:
        return int(round(max(0.0, min(10.0, score))))
