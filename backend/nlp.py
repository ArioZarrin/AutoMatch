from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass

import spacy
from rapidfuzz import fuzz, process
from spacy.language import Language
from spacy.matcher import PhraseMatcher
from spacy.tokens import Doc

from .catalogue import FUZZY_MARGIN, FUZZY_MIN_LENGTH, FUZZY_THRESHOLDS, Catalogue
from .domain import IDENTITY_FIELDS, VEHICLE_FIELDS, ExtractionResult


SPACY_MODEL = "en_core_web_md"

CORRECTION_MARKERS = (
    "the actual car is",
    "actual car is",
    "it is actually a",
    "it's actually a",
    "i meant",
    "correction",
)
ENGINE_DONOR_MARKERS = (
    "with engine swap from",
    "engine swap from",
    "engine from",
    "motor from",
)
EXCHANGE_MARKERS = (
    "in exchange for",
    "might swap for",
    "swap for",
    "trade for",
    "trading for",
)
NON_ROAD_PATTERNS = (
    "golf cart",
    "golf buggy",
    "go kart",
    "golf clubs",
    "model car collection",
)

TECHNICAL_PHRASES = {
    "transmission_type": (
        "automatic",
        "auto",
        "manual",
        "man",
        "mt",
        "stick",
        "stick shift",
        "cvt",
        "continuously variable transmission",
        "dct",
        "dual clutch transmission",
    ),
    "fuel_type": (
        "petrol",
        "gasoline",
        "gas",
        "diesel",
        "electric",
        "ev",
        "bev",
        "battery electric",
        "hybrid",
        "hev",
        "plugin hybrid",
        "plug in hybrid",
        "phev",
        "lpg",
        "autogas",
    ),
    "drive_type": (
        "awd",
        "all wheel",
        "all wheel drive",
        "4wd",
        "4x4",
        "four wheel",
        "four wheel drive",
        "fwd",
        "front wheel",
        "front wheel drive",
        "rwd",
        "rear wheel",
        "rear wheel drive",
    ),
}

NOISE_WORDS = {
    "a",
    "an",
    "and",
    "any",
    "buy",
    "buying",
    "car",
    "cars",
    "condition",
    "drive",
    "find",
    "for",
    "from",
    "good",
    "has",
    "have",
    "i",
    "in",
    "is",
    "it",
    "kms",
    "km",
    "like",
    "looking",
    "low",
    "me",
    "my",
    "need",
    "new",
    "of",
    "old",
    "on",
    "or",
    "please",
    "sale",
    "search",
    "sell",
    "selling",
    "show",
    "the",
    "to",
    "used",
    "vehicle",
    "want",
    "with",
}


def normalized_words(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value)).casefold()
    text = "".join(
        character for character in text if not unicodedata.combining(character)
    )
    return " ".join(re.findall(r"[a-z0-9]+", text))


@dataclass(frozen=True, slots=True)
class Mention:
    field: str
    canonical: str
    start: int
    end: int
    method: str
    score: float = 100.0


class NLPExtractor:
    """Database-informed spaCy extraction without query-data training."""

    model_name = SPACY_MODEL

    def __init__(self) -> None:
        self._nlp: Language | None = None
        self._matcher: PhraseMatcher | None = None
        self._match_map: dict[int, tuple[str, str]] = {}
        self._catalogue: Catalogue | None = None
        self._choices: dict[str, dict[str, str]] = {
            field: {} for field in VEHICLE_FIELDS
        }
        self._model_by_make: dict[str, set[str]] = defaultdict(set)
        self._badge_by_make_model: dict[tuple[str, str], set[str]] = defaultdict(set)
        self._makes_by_model: dict[str, set[str]] = defaultdict(set)

    @property
    def configured(self) -> bool:
        return self._matcher is not None and self._catalogue is not None

    def configure(
        self,
        catalogue: Catalogue,
        aliases: Mapping[str, Mapping[str, str]] | None = None,
    ) -> None:
        if self._nlp is None:
            self._nlp = spacy.load(
                self.model_name,
                disable=["tagger", "parser", "attribute_ruler", "lemmatizer"],
            )
            if (
                self._nlp.lang != "en"
                or self._nlp.meta.get("name") != "core_web_md"
                or "ner" not in self._nlp.pipe_names
            ):
                raise RuntimeError(
                    f"Expected the English {self.model_name} pipeline with NER."
                )

        canonical_by_key: dict[str, dict[str, str]] = {
            field: {} for field in VEHICLE_FIELDS
        }
        candidate_aliases: dict[str, dict[str, set[str]]] = {
            field: defaultdict(set) for field in VEHICLE_FIELDS
        }
        pattern_aliases: dict[str, dict[str, set[str]]] = {
            field: defaultdict(set) for field in VEHICLE_FIELDS
        }

        for record in catalogue.records:
            for field in VEHICLE_FIELDS:
                value = record.value(field)
                key = normalized_words(value)
                canonical_by_key[field].setdefault(key, value)
                candidate_aliases[field][key].add(value)
                pattern_aliases[field][value].update({value, key})

        for field, field_aliases in (aliases or {}).items():
            if field not in candidate_aliases:
                continue
            for alias, requested_canonical in field_aliases.items():
                canonical = canonical_by_key[field].get(
                    normalized_words(requested_canonical)
                )
                alias_key = normalized_words(alias)
                if canonical and alias_key:
                    candidate_aliases[field][alias_key].add(canonical)
                    pattern_aliases[field][canonical].update({alias, alias_key})

        for field, phrases in TECHNICAL_PHRASES.items():
            for phrase in phrases:
                resolution = catalogue.resolve({field: phrase})[field]
                if resolution.is_catalogue_value and resolution.value:
                    candidate_aliases[field][normalized_words(phrase)].add(
                        resolution.value
                    )
                    pattern_aliases[field][resolution.value].add(phrase)

        choices = {field: {} for field in VEHICLE_FIELDS}
        for field in VEHICLE_FIELDS:
            for alias, canonical_values in candidate_aliases[field].items():
                if alias and len(canonical_values) == 1:
                    choices[field][alias] = next(iter(canonical_values))

        matcher = PhraseMatcher(self._nlp.vocab, attr="LOWER")
        match_map: dict[int, tuple[str, str]] = {}
        for field in VEHICLE_FIELDS:
            for index, (canonical, field_aliases) in enumerate(
                pattern_aliases[field].items()
            ):
                rule_name = f"AUTOMATCH_{field}_{index}"
                matcher.add(
                    rule_name,
                    [
                        self._nlp.make_doc(alias)
                        for alias in sorted(set(field_aliases))
                        if alias
                    ],
                )
                match_map[self._nlp.vocab.strings[rule_name]] = (field, canonical)

        model_by_make: dict[str, set[str]] = defaultdict(set)
        badge_by_make_model: dict[tuple[str, str], set[str]] = defaultdict(set)
        makes_by_model: dict[str, set[str]] = defaultdict(set)
        for record in catalogue.records:
            make_key = normalized_words(record.make)
            model_key = normalized_words(record.model)
            model_by_make[make_key].add(record.model)
            badge_by_make_model[(make_key, model_key)].add(record.badge)
            makes_by_model[model_key].add(record.make)

        self._catalogue = catalogue
        self._choices = choices
        self._matcher = matcher
        self._match_map = match_map
        self._model_by_make = model_by_make
        self._badge_by_make_model = badge_by_make_model
        self._makes_by_model = makes_by_model

    def extract(self, query: str) -> ExtractionResult:
        if not self.configured or self._nlp is None or self._matcher is None:
            raise RuntimeError("The NLP catalogue index is not configured.")

        segment = self._select_primary_segment(query)
        normalized_segment = normalized_words(segment)
        if any(pattern in normalized_segment for pattern in NON_ROAD_PATTERNS):
            return ExtractionResult(
                vehicle_present=False,
                is_complete=True,
                fields={field: None for field in VEHICLE_FIELDS},
            )

        doc = self._nlp(segment)
        mentions = self._exact_mentions(doc)
        exact_fields = {mention.field for mention in mentions}
        fuzzy_mentions, fuzzy_unresolved = self._fuzzy_mentions(doc, mentions)
        mentions = self._keep_longest_mentions([*mentions, *fuzzy_mentions])
        fields, conflicts, inferred_make = self._resolve_mentions(mentions)

        explicit_identity = {
            mention.field
            for mention in mentions
            if mention.field in IDENTITY_FIELDS
        }
        unresolved = fuzzy_unresolved or self._has_unresolved_ner(doc, mentions)
        vehicle_present = any(value is not None for value in fields.values())
        identity_complete = {"make", "model"}.issubset(explicit_identity)
        is_complete = bool(
            vehicle_present
            and identity_complete
            and not inferred_make
            and not conflicts
            and not unresolved
        )

        # Exact catalogue evidence always wins over a fuzzy mention for a field.
        if exact_fields:
            for field in exact_fields:
                exact_values = {
                    mention.canonical
                    for mention in mentions
                    if mention.field == field and mention.method != "fuzzy"
                }
                if len(exact_values) == 1:
                    fields[field] = next(iter(exact_values))

        return ExtractionResult(
            vehicle_present=vehicle_present,
            is_complete=is_complete,
            fields=fields,
        )

    @staticmethod
    def _select_primary_segment(query: str) -> str:
        segment = " ".join(query.strip().split())
        lowered = segment.casefold()
        correction_positions = [
            (lowered.rfind(marker), marker)
            for marker in CORRECTION_MARKERS
            if marker in lowered
        ]
        if correction_positions:
            position, marker = max(correction_positions)
            segment = segment[position + len(marker) :].strip()
            lowered = segment.casefold()

        for marker in ENGINE_DONOR_MARKERS:
            if marker in lowered:
                segment = segment[: lowered.index(marker)].strip()
                lowered = segment.casefold()
                break

        if re.search(r"\b(sell|selling|offer|offering|my)\b", lowered):
            for marker in EXCHANGE_MARKERS:
                if marker in lowered:
                    segment = segment[: lowered.index(marker)].strip()
                    break
        return segment

    def _exact_mentions(self, doc: Doc) -> list[Mention]:
        assert self._matcher is not None
        mentions = [
            Mention(field, canonical, start, end, "catalogue_exact")
            for match_id, start, end in self._matcher(doc)
            for field, canonical in (self._match_map[match_id],)
        ]

        occupied = {
            (mention.field, mention.start, mention.end) for mention in mentions
        }
        for entity in doc.ents:
            entity_key = normalized_words(entity.text)
            for field in IDENTITY_FIELDS:
                canonical = self._choices[field].get(entity_key)
                key = (field, entity.start, entity.end)
                if canonical and key not in occupied:
                    mentions.append(
                        Mention(field, canonical, entity.start, entity.end, "ner")
                    )
        return self._keep_longest_mentions(mentions)

    @staticmethod
    def _keep_longest_mentions(mentions: list[Mention]) -> list[Mention]:
        unique: dict[tuple[str, str, int, int], Mention] = {}
        priority = {"catalogue_exact": 3, "ner": 2, "fuzzy": 1}
        for mention in mentions:
            key = (mention.field, mention.canonical, mention.start, mention.end)
            current = unique.get(key)
            if current is None or priority[mention.method] > priority[current.method]:
                unique[key] = mention

        kept: list[Mention] = []
        for field in VEHICLE_FIELDS:
            occupied: set[int] = set()
            field_mentions = sorted(
                (mention for mention in unique.values() if mention.field == field),
                key=lambda mention: (
                    -(mention.end - mention.start),
                    mention.start,
                    -mention.score,
                ),
            )
            for mention in field_mentions:
                span = set(range(mention.start, mention.end))
                if span.intersection(occupied):
                    continue
                kept.append(mention)
                occupied.update(span)
        return kept

    def _fuzzy_mentions(
        self, doc: Doc, mentions: list[Mention]
    ) -> tuple[list[Mention], bool]:
        additions: list[Mention] = []
        unresolved = False
        grouped = self._grouped_mentions(mentions)
        occupied = {
            token_index
            for mention in mentions
            for token_index in range(mention.start, mention.end)
        }

        for field in VEHICLE_FIELDS:
            if grouped[field]:
                continue
            choices = self._scoped_choices(field, grouped)
            if not choices:
                continue

            max_words = min(4, max(len(alias.split()) for alias in choices))
            canonical_best: dict[str, Mention] = {}
            near_threshold = False
            for size in range(1, min(max_words, len(doc)) + 1):
                for start in range(0, len(doc) - size + 1):
                    end = start + size
                    if occupied.intersection(range(start, end)):
                        continue
                    phrase = normalized_words(doc[start:end].text)
                    compact = phrase.replace(" ", "")
                    if (
                        len(compact) < FUZZY_MIN_LENGTH
                        or not phrase
                        or all(word in NOISE_WORDS for word in phrase.split())
                        or re.fullmatch(r"(19|20)\d{2}", compact)
                    ):
                        continue
                    hits = process.extract(
                        phrase,
                        choices.keys(),
                        scorer=fuzz.ratio,
                        limit=8,
                    )
                    for alias, score, _ in hits:
                        if score >= FUZZY_THRESHOLDS[field] - 3:
                            near_threshold = True
                        if score < FUZZY_THRESHOLDS[field]:
                            continue
                        canonical = choices[alias]
                        candidate = Mention(
                            field, canonical, start, end, "fuzzy", float(score)
                        )
                        current = canonical_best.get(canonical)
                        if current is None or (
                            candidate.score,
                            candidate.end - candidate.start,
                        ) > (current.score, current.end - current.start):
                            canonical_best[canonical] = candidate

            ranked = sorted(
                canonical_best.values(),
                key=lambda mention: (mention.score, mention.end - mention.start),
                reverse=True,
            )
            if not ranked:
                unresolved = unresolved or (field in IDENTITY_FIELDS and near_threshold)
                continue
            second_score = ranked[1].score if len(ranked) > 1 else 0.0
            if ranked[0].score - second_score >= FUZZY_MARGIN:
                additions.append(ranked[0])
                grouped[field].append(ranked[0].canonical)
            elif field in IDENTITY_FIELDS:
                unresolved = True
        return additions, unresolved

    def _scoped_choices(
        self, field: str, grouped: Mapping[str, list[str]]
    ) -> dict[str, str]:
        allowed: set[str] | None = None
        if field == "model" and len(grouped["make"]) == 1:
            allowed = self._model_by_make.get(normalized_words(grouped["make"][0]))
        elif (
            field == "badge"
            and len(grouped["make"]) == 1
            and len(grouped["model"]) == 1
        ):
            allowed = self._badge_by_make_model.get(
                (
                    normalized_words(grouped["make"][0]),
                    normalized_words(grouped["model"][0]),
                )
            )
        if not allowed:
            return self._choices[field]
        return {
            alias: canonical
            for alias, canonical in self._choices[field].items()
            if canonical in allowed
        }

    @staticmethod
    def _grouped_mentions(mentions: list[Mention]) -> dict[str, list[str]]:
        grouped = {field: [] for field in VEHICLE_FIELDS}
        for mention in mentions:
            if mention.canonical not in grouped[mention.field]:
                grouped[mention.field].append(mention.canonical)
        return grouped

    def _resolve_mentions(
        self, mentions: list[Mention]
    ) -> tuple[dict[str, str | None], list[str], bool]:
        grouped = self._grouped_mentions(mentions)
        fields: dict[str, str | None] = {field: None for field in VEHICLE_FIELDS}
        conflicts: list[str] = []

        if len(grouped["make"]) == 1:
            fields["make"] = grouped["make"][0]
        elif len(grouped["make"]) > 1:
            conflicts.append("multiple_make")

        model_values = grouped["model"]
        if fields["make"]:
            allowed_models = self._model_by_make.get(normalized_words(fields["make"]), set())
            scoped = [value for value in model_values if value in allowed_models]
            if scoped:
                model_values = scoped
        if len(model_values) == 1:
            fields["model"] = model_values[0]
        elif len(model_values) > 1:
            conflicts.append("multiple_model")

        inferred_make = False
        if fields["make"] is None and fields["model"]:
            possible_makes = self._makes_by_model.get(
                normalized_words(fields["model"]), set()
            )
            if len(possible_makes) == 1:
                fields["make"] = next(iter(possible_makes))
                inferred_make = True

        badge_values = grouped["badge"]
        if fields["make"] and fields["model"]:
            allowed_badges = self._badge_by_make_model.get(
                (
                    normalized_words(fields["make"]),
                    normalized_words(fields["model"]),
                ),
                set(),
            )
            scoped = [value for value in badge_values if value in allowed_badges]
            if scoped:
                badge_values = scoped
        if len(badge_values) == 1:
            fields["badge"] = badge_values[0]
        elif len(badge_values) > 1:
            conflicts.append("multiple_badge")

        for field in VEHICLE_FIELDS[3:]:
            values = grouped[field]
            if len(values) == 1:
                fields[field] = values[0]
            elif len(values) > 1:
                conflicts.append(f"multiple_{field}")
        return fields, conflicts, inferred_make

    @staticmethod
    def _has_unresolved_ner(doc: Doc, mentions: list[Mention]) -> bool:
        consumed: set[int] = set()
        for mention in mentions:
            consumed.update(range(mention.start, mention.end))

        for entity in doc.ents:
            if entity.label_ not in {"ORG", "PRODUCT"}:
                continue
            remaining = [
                token
                for token in entity
                if token.i not in consumed
                and normalized_words(token.text) not in NOISE_WORDS
            ]
            if remaining:
                return True

        for token in doc:
            if token.i in consumed or token.is_punct or token.is_space:
                continue
            raw = token.text.strip(".,;:!?()[]{}")
            if len(raw) >= 2 and (
                any(character.isdigit() for character in raw)
                or (raw.isupper() and raw.isalpha())
            ):
                if normalized_words(raw) not in NOISE_WORDS:
                    return True
        return False
