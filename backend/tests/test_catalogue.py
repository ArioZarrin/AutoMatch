from __future__ import annotations

import unittest

from backend.catalogue import Catalogue
from backend.domain import ExtractionResult, VehicleRecord


def record(
    vehicle_id: str,
    make: str = "Toyota",
    model: str = "Corolla",
    badge: str = "Ascent",
    transmission: str = "Automatic",
    fuel: str = "Petrol",
    drive: str = "FWD",
    listings: int = 0,
) -> VehicleRecord:
    return VehicleRecord(
        id=vehicle_id,
        make=make,
        model=model,
        badge=badge,
        transmission_type=transmission,
        fuel_type=fuel,
        drive_type=drive,
        listing_count=listings,
    )


def extraction(**overrides: str | None) -> ExtractionResult:
    fields = {
        "make": "Toyota",
        "model": "Corolla",
        "badge": "Ascent",
        "transmission_type": "Automatic",
        "fuel_type": "Petrol",
        "drive_type": "FWD",
    }
    fields.update(overrides)
    return ExtractionResult(vehicle_present=True, is_complete=True, fields=fields)


class CatalogueTests(unittest.TestCase):
    def test_full_exact_match_returns_vehicle(self) -> None:
        catalogue = Catalogue([record("vehicle-1", listings=4)])

        result = catalogue.match(extraction())

        self.assertEqual(result.vehicle_id, "vehicle-1")
        self.assertEqual(result.status, "MATCHED")
        self.assertEqual(result.confidence, 10)

    def test_open_world_values_are_preserved_without_false_match(self) -> None:
        catalogue = Catalogue([record("vehicle-1")])

        result = catalogue.match(
            extraction(
                make="BMW",
                model="X5",
                badge=None,
                transmission_type=None,
                fuel_type=None,
                drive_type=None,
            )
        )

        self.assertIsNone(result.vehicle_id)
        self.assertEqual(result.status, "NO_CATALOGUE_MATCH")
        self.assertEqual(result.fields["make"], "BMW")
        self.assertEqual(result.fields["model"], "X5")

    def test_database_aliases_return_database_canonical_value(self) -> None:
        catalogue = Catalogue(
            [record("vehicle-1")],
            aliases={"badge": {"base model": "Ascent"}},
        )

        result = catalogue.match(extraction(badge="base model"))

        self.assertEqual(result.vehicle_id, "vehicle-1")
        self.assertEqual(result.fields["badge"], "Ascent")

    def test_restricted_fuzzy_match_corrects_a_clear_make_typo(self) -> None:
        catalogue = Catalogue([record("vehicle-1")])

        result = catalogue.match(extraction(make="Toyotaa"))

        self.assertEqual(result.vehicle_id, "vehicle-1")
        self.assertEqual(result.fields["make"], "Toyota")

    def test_technical_synonyms_return_database_values(self) -> None:
        catalogue = Catalogue([record("vehicle-1")])

        result = catalogue.match(
            extraction(
                transmission_type="auto",
                fuel_type="gasoline",
                drive_type="front wheel drive",
            )
        )

        self.assertEqual(result.vehicle_id, "vehicle-1")
        self.assertEqual(result.fields["transmission_type"], "Automatic")
        self.assertEqual(result.fields["fuel_type"], "Petrol")
        self.assertEqual(result.fields["drive_type"], "FWD")

    def test_listing_count_breaks_an_incomplete_query_tie(self) -> None:
        catalogue = Catalogue(
            [
                record("vehicle-low", badge="Ascent", listings=2),
                record("vehicle-high", badge="GXL", listings=12),
            ]
        )

        result = catalogue.match(
            extraction(
                badge=None,
                transmission_type=None,
                fuel_type=None,
                drive_type=None,
            )
        )

        self.assertEqual(result.vehicle_id, "vehicle-high")
        self.assertTrue(result.is_decisive)

    def test_equal_listing_tie_is_reported_as_ambiguous(self) -> None:
        catalogue = Catalogue(
            [
                record("vehicle-a", badge="Ascent", listings=2),
                record("vehicle-b", badge="GXL", listings=2),
            ]
        )

        result = catalogue.match(
            extraction(
                badge=None,
                transmission_type=None,
                fuel_type=None,
                drive_type=None,
            )
        )

        self.assertEqual(result.vehicle_id, "vehicle-a")
        self.assertEqual(result.status, "AMBIGUOUS")
        self.assertFalse(result.is_decisive)


if __name__ == "__main__":
    unittest.main()
