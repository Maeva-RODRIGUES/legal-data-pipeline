from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .index import ALIAS
from .query import TOP_K, format_boost

MODES = ("number", "title")
TITLE_SOURCE = "adlc-opendata"  # Judilibre n'a pas de titre
GROUPS = {
    "has_text": "texte",
    "ambiguous_title": "titre ambigu",
    "ambiguous_number": "numéro ambigu",
}
TITLE_WIDTH = 80


@dataclass(frozen=True)
class Target:
    doc_id: str
    source: str
    decision_number: str | None
    title: str | None
    has_text: bool
    ambiguous_title: bool
    ambiguous_number: bool


@dataclass(frozen=True)
class Result:
    target: Target
    rank: int | None  # None : absente du top 10
    total_hits: int


@dataclass(frozen=True)
class Metrics:
    sample_size: int
    hit_at_1: float | None  # None : échantillon vide
    hit_at_10: float | None
    mrr: float | None


@dataclass
class Evaluation:
    mode: str
    title_boost: float | None  # None pour number
    results: list[Result]

    @property
    def metrics(self) -> Metrics:
        return compute_metrics([result.rank for result in self.results])

    @property
    def label(self) -> str:
        if self.title_boost is None:
            return self.mode
        return f"{self.mode} (boost {format_boost(self.title_boost)})"


def title_key(title: str | None) -> str | None:
    """Titre sans espaces autour, apostrophe typographique ramenée à ' (même analyse à l'index)."""
    if title is None:
        return None
    return title.strip().replace("’", "'") or None


def number_key(number: str | None) -> str | None:
    """Numéro en minuscules, comme le normaliseur folded du mapping."""
    if number is None:
        return None
    return number.strip().lower() or None


def ambiguous(keys: Iterable[str | None]) -> set[str]:
    counts = Counter(key for key in keys if key is not None)
    return {key for key, n in counts.items() if n > 1}


def build_targets(
    silver_keys: Iterable[Mapping[str, Any]], sample_rows: Iterable[Mapping[str, Any]]
) -> list[Target]:
    """Ambiguïtés calculées sur tout Silver, pas sur le seul échantillon."""
    silver_keys = list(silver_keys)
    titles = ambiguous(title_key(row["title"]) for row in silver_keys)
    numbers = ambiguous(number_key(row["decision_number"]) for row in silver_keys)
    return [
        Target(
            doc_id=f"{row['source']}|{row['external_id']}",
            source=row["source"],
            decision_number=row["decision_number"],
            title=row["title"],
            has_text=row["has_text"],
            ambiguous_title=title_key(row["title"]) in titles,
            ambiguous_number=number_key(row["decision_number"]) in numbers,
        )
        for row in sample_rows
    ]


def targets_for(targets: Iterable[Target], mode: str) -> list[Target]:
    if mode == "number":
        return [t for t in targets if number_key(t.decision_number) is not None]
    if mode == "title":
        return [t for t in targets if t.source == TITLE_SOURCE and title_key(t.title) is not None]
    raise ValueError(f"mode inconnu : {mode}")


def extract_rank(response: Mapping[str, Any], doc_id: str) -> tuple[int | None, int]:
    """Rang (à partir de 1) de doc_id dans le top 10, et nombre total de résultats."""
    hits = response["hits"]
    total = hits["total"]
    if total["relation"] != "eq":
        raise ValueError(f"total de résultats inexact : {total['value']} ({total['relation']})")
    ids = [hit["_id"] for hit in hits["hits"][:TOP_K]]
    rank = ids.index(doc_id) + 1 if doc_id in ids else None
    return rank, total["value"]


def compute_metrics(ranks: Sequence[int | None]) -> Metrics:
    n = len(ranks)
    if n == 0:
        return Metrics(0, None, None, None)
    found = [rank for rank in ranks if rank is not None]
    return Metrics(
        sample_size=n,
        hit_at_1=sum(rank == 1 for rank in found) / n,
        hit_at_10=len(found) / n,
        mrr=sum(1 / rank for rank in found) / n,
    )


def group_metrics(results: Sequence[Result]) -> dict[tuple[str, bool], Metrics]:
    """Métriques par groupe et par valeur ; un groupe vide reste présent (sample_size 0)."""
    return {
        (group, value): compute_metrics(
            [result.rank for result in results if getattr(result.target, group) is value]
        )
        for group in GROUPS
        for value in (True, False)
    }


def format_share(value: float | None) -> str:
    return "-" if value is None else f"{value:.3f}".replace(".", ",")


def format_metrics(metrics: Metrics) -> str:
    return (
        f"hit@1 = {format_share(metrics.hit_at_1)} ; "
        f"hit@10 = {format_share(metrics.hit_at_10)} ; "
        f"MRR = {format_share(metrics.mrr)}"
    )


def format_rank(rank: int | None) -> str:
    return "absente" if rank is None else str(rank)


def truncate(text: str | None, width: int = TITLE_WIDTH) -> str:
    text = (text or "").strip()
    return text if len(text) <= width else text[: width - 1] + "…"


def format_report(index_name: str, evaluations: Sequence[Evaluation]) -> str:
    doc_ids = {result.target.doc_id for e in evaluations for result in e.results}
    lines = [f"Index {index_name} (alias {ALIAS}), {len(doc_ids)} décision(s) évaluée(s)"]
    for evaluation in evaluations:
        metrics = evaluation.metrics
        lines.append(
            f"{evaluation.label} : {metrics.sample_size} cherchée(s) ; {format_metrics(metrics)}"
        )
        for (group, value), group_m in group_metrics(evaluation.results).items():
            answer = "oui" if value else "non"
            lines.append(
                f"  {GROUPS[group]} {answer} : {group_m.sample_size} ; {format_metrics(group_m)}"
            )
    lines.extend(format_misses("number", "numéro", evaluations))
    lines.extend(format_misses("title", "titre", evaluations))
    return "\n".join(lines)


def format_misses(mode: str, label: str, evaluations: Sequence[Evaluation]) -> list[str]:
    """Décisions absentes du top 10 pour au moins une évaluation du mode, rang par évaluation."""
    selected = [e for e in evaluations if e.mode == mode]
    if not selected:
        return []
    ranks: dict[str, list[int | None]] = {}
    targets: dict[str, Target] = {}
    for column, evaluation in enumerate(selected):
        for result in evaluation.results:
            targets[result.target.doc_id] = result.target
            ranks.setdefault(result.target.doc_id, [None] * len(selected))[column] = result.rank
    missed = [doc_id for doc_id, row in ranks.items() if None in row]
    title = f"Décisions absentes du top 10 par {label}"
    if not missed:
        return [f"{title} : aucune"]
    headers = ["numéro", *(e.label for e in selected), "titre"]
    rows = [
        [
            targets[doc_id].decision_number or "-",
            *(format_rank(rank) for rank in ranks[doc_id]),
            truncate(targets[doc_id].title),
        ]
        for doc_id in missed
    ]
    widths = [max(len(row[i]) for row in [headers, *rows]) for i in range(len(headers) - 1)]
    return [f"{title} ({len(missed)}) :", *(format_row(row, widths) for row in [headers, *rows])]


def format_row(row: Sequence[str], widths: Sequence[int]) -> str:
    """Colonnes alignées, titre en dernier sans largeur fixe."""
    cells = [cell.ljust(width) for cell, width in zip(row[:-1], widths, strict=True)]
    return "  " + "  ".join([*cells, row[-1]]).rstrip()
