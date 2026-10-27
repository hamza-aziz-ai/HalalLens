# FLOW

How execution travels. Lines marked `<-- changed` were modified by PR #87.

## 1. Public score: `POST /halal-score`

```
browser / client
  -> api/app.py: halal_score()                       rate limit "public_compute" per IP
     -> HalalScoreRequest / FinancialSnapshotPayload  Pydantic, extra="forbid"
        -> _reject_unsupported_amount()               <-- changed: bool / underflowing string rejected
     -> _evaluate_request()                           422 if no market cap supplied
        -> RatioEngine.evaluate()                     ratio_engine/engine.py
           -> _clean() / _non_permissible_income()    <-- changed: finite, non-bool, exact Decimal
           -> _ratio() + _build_computation()         <-- changed: decision is numerator <= threshold * denominator
           -> _aggregate_verdict()                    <-- changed: the ONLY place a verdict is derived
     -> HalalScoreResponse(is_compliant, screen_verdict, ratios, missing_inputs)   <-- changed: nullable + screen_verdict
```

Fails when: a required input is missing or invalid (-> `insufficient-data`), the market cap is missing (-> 422), the per-IP limit is hit (-> 429).

## 2. Stored filing: `GET /filings/{symbol}`

```
api/app.py -> _ensure_filing_evaluation(record)
   - record already has ratios?  -> return stored ratios and stored verdict unchanged   (stale until recomputed)
   - otherwise:
       _snapshot_from_record -> engine.evaluate
       detected = _detect_quality_issues(...)
       reload stored open issues (persistent records only)        <-- changed: BEFORE the verdict pair is final
       final (verdict, is_compliant) = needs-review/None if any blocking issue, else engine verdict   <-- changed
       db.upsert_filing_evaluation(final pair)  ->  record[...] = same pair
```

## 3. Ingestion to evaluation (scheduled)

```
jobs/schedule_ingestion.py -> jobs/ingest_bse.py: crawler -> etl/financial_data_processor.py -> Postgres + MinIO
jobs/schedule_evaluations.py -> jobs/precompute_evaluations.py: run_precompute()
   -> _snapshot_from_record -> engine.evaluate -> build_summary -> upsert_filing_evaluation(evaluation.verdict, evaluation.is_compliant)
jobs/ingest_bse.py::_evaluate_and_store, jobs/ingest_indianapi.py::_evaluate_snapshot, jobs/backfill_evaluations.py::main
   -> same three calls (all four jobs persist the engine's pair; tests/test_job_verdicts.py pins it)
```

## 4. Alerts

`POST /alerts/check` (paid) -> `AlertEngine.process_verdict(symbol, is_compliant)`. `None` returns immediately and leaves the stored baseline alone (`True -> None -> False` flips once). Known gap: the caller supplies `is_compliant`, and every user's entries are scanned.
