from __future__ import annotations

import argparse
import os
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import psycopg
from dotenv import load_dotenv
from elasticsearch import Elasticsearch
from psycopg import IsolationLevel
from psycopg.rows import dict_row

from src.storage.bronze_store import BronzeStore

from .findability import (
    Evaluation,
    Result,
    Target,
    build_targets,
    extract_rank,
    format_report,
    targets_for,
)
from .index import ALIAS, ElasticsearchIndexClient, IndexClient
from .query import number_query, search_body, title_query
from .rebuild import previous_index

SOURCE = "search-eval"
DATE_TYPE = "evaluation"
DEFAULT_BOOSTS = [3.0]
MAX_BOOST = Decimal("1000")  # title_boost NUMERIC(5,2)

# Spec : 200 décisions ADLC tirées par md5, plus les ADLC sans texte, les décisions à numéro
# partagé (même clé que number_key) et toutes les décisions Judilibre.
SAMPLE_SQL = """WITH picked AS (
    (SELECT source, external_id FROM silver.decisions
     WHERE source = 'adlc-opendata'
     ORDER BY md5(external_id) LIMIT 200)
    UNION
    SELECT source, external_id FROM silver.decisions
    WHERE source = 'adlc-opendata' AND (text IS NULL OR btrim(text) = '')
    UNION
    SELECT source, external_id FROM silver.decisions
    WHERE lower(btrim(decision_number)) IN (
        SELECT lower(btrim(decision_number)) FROM silver.decisions
        WHERE decision_number IS NOT NULL
        GROUP BY 1 HAVING count(*) > 1)
    UNION
    SELECT source, external_id FROM silver.decisions
    WHERE source = 'judilibre'
)
SELECT d.source, d.external_id, d.decision_number, d.title,
       d.text IS NOT NULL AND btrim(d.text) <> '' AS has_text
FROM picked JOIN silver.decisions d USING (source, external_id)
ORDER BY d.source, d.external_id"""
KEYS_SQL = "SELECT source, title, decision_number FROM silver.decisions"
INSERT_RUN_SQL = """INSERT INTO search.findability_runs
    (run_id, index_name, mode, title_boost, sample_size, hit_at_1, hit_at_10, mrr)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING eval_id"""
INSERT_RESULT_SQL = """INSERT INTO search.findability_results
    (eval_id, run_id, mode, title_boost, doc_id, has_text, ambiguous_title, ambiguous_number,
     rank, total_hits)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""

Search = Callable[[dict[str, Any]], Mapping[str, Any]]


def boost_arg(text: str) -> float:
    """Boost strictement positif, sous 1000, deux décimales au plus (NUMERIC(5,2))."""
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise argparse.ArgumentTypeError(f"boost invalide : {text}") from None
    exponent = value.as_tuple().exponent
    if not value.is_finite() or not 0 < value < MAX_BOOST or exponent < -2:
        raise argparse.ArgumentTypeError(
            f"boost invalide : {text} (entre 0 et 1000 exclus, deux décimales au plus)"
        )
    return float(value)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Évaluation de la findability de l'index -> search.findability_*"
    )
    parser.add_argument(
        "--title-boost",
        type=boost_arg,
        nargs="+",
        default=DEFAULT_BOOSTS,
        help="poids du titre dans le mode title (défaut : 3)",
    )
    args = parser.parse_args(argv)
    args.title_boost = list(dict.fromkeys(args.title_boost))  # doublons retirés, ordre gardé
    return args


def load_targets(conn: psycopg.Connection) -> list[Target]:
    """Clés de tout Silver et échantillon sur un même instantané, en lecture seule."""
    conn.isolation_level = IsolationLevel.REPEATABLE_READ  # connexion au repos : start_run
    conn.read_only = True
    try:
        with conn.transaction(force_rollback=True), conn.cursor(row_factory=dict_row) as cur:
            silver_keys = cur.execute(KEYS_SQL).fetchall()
            sample_rows = cur.execute(SAMPLE_SQL).fetchall()
    finally:
        conn.read_only = False
        conn.isolation_level = None
    return build_targets(silver_keys, sample_rows)


def evaluate(
    search: Search, targets: Sequence[Target], mode: str, boost: float | None = None
) -> Evaluation:
    """Une recherche par décision du mode ; boost ignoré pour number."""
    title_boost = boost if mode == "title" else None
    results = []
    for target in targets_for(targets, mode):
        if mode == "number":
            query = number_query(target.decision_number)
        else:
            query = title_query(target.title, title_boost)
        rank, total_hits = extract_rank(search(search_body(query)), target.doc_id)
        results.append(Result(target, rank, total_hits))
    return Evaluation(mode, title_boost, results)


def evaluate_all(
    search: Search, targets: Sequence[Target], boosts: Sequence[float]
) -> list[Evaluation]:
    return [
        evaluate(search, targets, "number"),
        *(evaluate(search, targets, "title", boost) for boost in boosts),
    ]


def alias_index(client: IndexClient) -> str:
    """Index derrière l'alias ; erreur si l'alias manque, est un index ou a plusieurs cibles."""
    name = previous_index(client)
    if name is None:
        raise ValueError(f"l'alias {ALIAS} n'existe pas : lancer d'abord src.search.run")
    return name


def check_alias_unchanged(client: IndexClient, index_name: str) -> None:
    """Un alias basculé pendant l'évaluation mélangerait deux index : le run échoue."""
    current = alias_index(client)
    if current != index_name:
        raise RuntimeError(
            f"l'alias {ALIAS} a basculé pendant l'évaluation : {index_name} -> {current}"
        )


def run_params(run_id: int, index_name: str, evaluation: Evaluation) -> tuple[Any, ...]:
    metrics = evaluation.metrics
    return (
        run_id,
        index_name,
        evaluation.mode,
        evaluation.title_boost,
        metrics.sample_size,
        metrics.hit_at_1,
        metrics.hit_at_10,
        metrics.mrr,
    )


def result_params(eval_id: int, run_id: int, evaluation: Evaluation) -> list[tuple[Any, ...]]:
    return [
        (
            eval_id,
            run_id,
            evaluation.mode,
            evaluation.title_boost,
            result.target.doc_id,
            result.target.has_text,
            result.target.ambiguous_title,
            result.target.ambiguous_number,
            result.rank,
            result.total_hits,
        )
        for result in evaluation.results
    ]


def store_results(
    conn: psycopg.Connection, run_id: int, index_name: str, evaluations: Sequence[Evaluation]
) -> None:
    """Insère sans valider : finish_run valide résultats et fin de run ensemble."""
    with conn.cursor() as cur:
        for evaluation in evaluations:
            eval_id = cur.execute(
                INSERT_RUN_SQL, run_params(run_id, index_name, evaluation)
            ).fetchone()[0]
            cur.executemany(INSERT_RESULT_SQL, result_params(eval_id, run_id, evaluation))


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()
    args = parse_args(argv)
    store = BronzeStore(os.environ["DATABASE_URL"])
    es = Elasticsearch(os.environ["ELASTICSEARCH_URL"], request_timeout=60)
    client = ElasticsearchIndexClient(es)

    def search(body: dict[str, Any]) -> Mapping[str, Any]:
        return es.search(index=ALIAS, body=body).body

    try:
        index_name = alias_index(client)  # alias absent : échec avant d'ouvrir un run
        today = date.today()
        run_id = store.start_run(SOURCE, today, today, DATE_TYPE)
        counts = {"fetched": 0, "new": 0, "changed": 0}
        print(f"Run {run_id} : évaluation de l'index {index_name} (alias {ALIAS})")
        try:
            targets = load_targets(store.conn)
            counts["fetched"] = len(targets)
            evaluations = evaluate_all(search, targets, args.title_boost)
            check_alias_unchanged(client, index_name)
            store_results(store.conn, run_id, index_name, evaluations)
            counts["new"] = sum(len(evaluation.results) for evaluation in evaluations)
        except Exception as exc:
            store.conn.rollback()
            store.finish_run(run_id, "failed", counts, error=str(exc)[:1000])
            raise
        store.finish_run(run_id, "success", counts)
    finally:
        store.close()
        es.close()

    print(format_report(index_name, evaluations))
    return 0  # les seuils relèvent des contrôles qualité


if __name__ == "__main__":
    raise SystemExit(main())
