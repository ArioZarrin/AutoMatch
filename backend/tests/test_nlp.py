from __future__ import annotations

import unittest

from backend.catalogue import Catalogue
from backend.domain import VehicleRecord
from backend.nlp import NLPExtractor, SPACY_MODEL


RECORDS = [
    VehicleRecord(
        id="toyota-ascent",
        make="Toyota",
        model="Corolla",
        badge="Ascent",
        transmission_type="Automatic",
        fuel_type="Petrol",
        drive_type="FWD",
        listing_count=5,
    ),
    VehicleRecord(
        id="toyota-gxl",
        make="Toyota",
        model="Corolla",
        badge="GXL",
        transmission_type="Manual",
        fuel_type="Petrol",
        drive_type="FWD",
        listing_count=2,
    ),
    VehicleRecord(
        id="ford-ranger",
        make="Ford",
        model="Ranger",
        badge="Wildtrak",
        transmission_type="Automatic",
        fuel_type="Diesel",
        drive_type="4WD",
        listing_count=8,
    ),
]


class NLPExtractorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalogue = Catalogue(
            RECORDS,
            aliases={"badge": {"base grade": "Ascent"}},
        )
        cls.extractor = NLPExtractor()
        cls.extractor.configure(
            cls.catalogue,
            aliases={"badge": {"base grade": "Ascent"}},
        )

    def test_uses_only_the_selected_spacy_model(self) -> None:
        self.assertEqual(self.extractor.model_name, SPACY_MODEL)
        self.assertEqual(SPACY_MODEL, "en_core_web_md")

    def test_exact_catalogue_query_is_complete_and_matches(self) -> None:
        extraction = self.extractor.extract(
            "Toyota Corolla Ascent automatic petrol front wheel drive"
        )
        decision = self.catalogue.match(extraction)

        self.assertTrue(extraction.is_complete)
        self.assertEqual(decision.vehicle_id, "toyota-ascent")
        self.assertEqual(extraction.fields["drive_type"], "FWD")

    def test_database_alias_returns_canonical_value(self) -> None:
        extraction = self.extractor.extract("Toyota Corolla base grade auto")

        self.assertTrue(extraction.is_complete)
        self.assertEqual(extraction.fields["badge"], "Ascent")
        self.assertEqual(extraction.fields["transmission_type"], "Automatic")

    def test_clear_make_typo_uses_restricted_fuzzy_match(self) -> None:
        extraction = self.extractor.extract("Toyotaa Corolla Ascent")

        self.assertTrue(extraction.is_complete)
        self.assertEqual(extraction.fields["make"], "Toyota")

    def test_model_only_inference_is_not_trusted_as_complete(self) -> None:
        extraction = self.extractor.extract("Corolla automatic")

        self.assertEqual(extraction.fields["make"], "Toyota")
        self.assertFalse(extraction.is_complete)

    def test_unknown_badge_forces_hybrid_fallback(self) -> None:
        extraction = self.extractor.extract("Toyota Corolla ZZZ")

        self.assertFalse(extraction.is_complete)

    def test_multiple_vehicle_query_is_not_complete(self) -> None:
        extraction = self.extractor.extract("Toyota Corolla or Ford Ranger")

        self.assertFalse(extraction.is_complete)


if __name__ == "__main__":
    unittest.main()
