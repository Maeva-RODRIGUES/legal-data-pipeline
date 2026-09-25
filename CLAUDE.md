# legal-data-pipeline conventions

- Python 3.12; commit messages in English (Conventional Commits).
- Never commit to `main`: work on a branch and open a pull request.
- Never commit `data/` or `.env`; never print an API key.
- Before each commit, `pre-commit run --all-files` and `pytest` must pass.
- Always open files with `encoding="utf-8"` (the dev machine runs Windows).
- Storage: reuse `src/storage/bronze_store.py` and its run log.
- One collector per folder in `src/collector/<source>/`, following the `judilibre/` layout.
- Tests must not hit the network: use `httpx.MockTransport` for HTTP calls and HTML fixtures in `tests/fixtures/`.
- To query the local database, never use `-it` and disable the psql pager:
  `podman exec legal-data-pipeline-postgres-1 psql -U legal -d legal -P pager=off -c "..."`
