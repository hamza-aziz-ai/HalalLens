# DECISIONS

One entry per decision, newest last. Model for every entry below: Claude Sonnet 5.5 (`claude-sonnet-5-5`), 2026-10-27, with Codex (ChatGPT) as the second opinion where noted. Rejected options live in [ALTERNATIVES.md](ALTERNATIVES.md).

## D-001: The engine owns a three-state verdict
- **Date:** 2026-10-27   Model: Claude Sonnet 5.5 + Codex review
- **Context:** The engine returned a boolean and skipped missing ratios, so one computed passing ratio gave `is_compliant=True`. Five copies of "derive the verdict from the boolean" existed (API, two ingest jobs, backfill, precompute).
- **Options:**
  1. keep the boolean, patch each copy
  2. add a fourth "borderline" state
  3. engine returns `compliant` / `non-compliant` / `insufficient-data`, consumers read it.
- **Chosen:** 3.
- **Why:** The DB already stores those strings; fixing it once removes the copies. Unknown is not a failure, so `is_compliant` is nullable.
- **Trade-off:** Nullable `is_compliant` breaks Boolean-only clients; UI and API had to change together.
- **Revisit if:** a scholar wants a "needs scholarly review" band beyond data quality.

## D-002: All five ratios and all three income parts are required
- **Context:** Which inputs may be missing before a filing can be called compliant?
- **Options:**
  1. three canonical ratios required
  2. all five required
  3. any one computed ratio.
- **Chosen:** 2, with prohibited income needing base + interest + dividend known (explicit zero counts).
- **Why:** Never a false pass; narrowing the set is a methodology decision, not a bug fix. SS21 backs 30/30/5 but not the 67%/49% gates.
- **Trade-off:** Many filings become `insufficient-data` until extraction improves. Unmeasured.
- **Revisit if:** the dry run shows the product unusable *and* a scholar approves a narrower set (one constant, `REQUIRED_RATIOS`).

## D-003: Exact decisions with Decimal in an explicit context
- **Context:** Floats put `(0.1+0.2)/6` above an exact 5%; Decimal's default 28 digits rounded away a `1e-30` income.
- **Chosen:** `numerator <= threshold * denominator` in a module-level 1500-digit context (no division, no ambient context); inputs bounded to finite values within float range; thresholds validated.
- **Why:** Boundary cases are the ones users care about. 1500 digits holds any sum in the supported domain exactly.
- **Trade-off:** Adapters still reduce values to float; integer exactness is engine-local only.
- **Revisit if:** inputs ever arrive as arbitrary-precision decimals.

## D-004: LLM narration bypassed on screening paths  (SUPERSEDED by D-010)
- **Date:** 2026-10-27   Model: Claude Sonnet 5.5 + Codex review
- **Context:** A model can echo the right status while its prose says the opposite; no keyword filter closes that (Codex produced counterexamples).
- **Chosen (then):** `NarrationEngine` always returned the rule-based narration; LLM code kept.
- **Why superseded:** the bypass removed an advertised feature without the maintainer deciding it. See D-010.

## D-005: One shared `coerce_amount` for untrusted numbers
- **Chosen:** `ratio_engine/amounts.py`; bool, NaN/inf and underflowing strings become unknown, exact zeros stay zero. API, jobs, ETL, vendor mapper and cache runner delegate to it.
- **Why:** Repo rule: fix once in the shared function. A boolean became a verified zero income in four places.
- **Trade-off:** Behaviour changes for malformed inputs (now unknown). Numeric JSON literals already decoded to 0.0 are outside the guarantee.

## D-006: `main` is protected by a ruleset; auto-merge is narrow
- **Chosen:** PR + `backend`/`ui`/`secrets` required, squash only, owner bypass. Auto-merge only for Dependabot minor/patch of GitHub Actions and UI dev deps.
- **Why:** Python packages touch ETL scaling and verdict logic; tests do not yet prove dependency bumps safe there.
- **Revisit if:** the verdict golden table and ETL fixtures cover those libraries.

## D-007: release-please with Conventional Commit PR titles
- **Chosen:** Release PR from squash-merge titles; `build:`/`ci:`/`docs:` do not release; no `!` / `BREAKING CHANGE` footers while below 1.0 (they would bump the major).
- **Trade-off:** Release PRs opened by the default token do not run CI.

## D-008: Pin the Python minor version only
- **Context:** `python_full_version = "3.14.6"` made `pipenv install --deploy` abort when `python:3.14-slim` moved to 3.14.10, breaking image builds.
- **Chosen:** `python_version = "3.14"`; hashes in `Pipfile.lock` still pin every dependency.

## D-009: Remove unused heavy dependencies
- **Chosen:** Dropped torch (CUDA index), langchain*, ollama, playwright, firecrawl-py, ghostscript, bs4 (nothing imports them); pytest/pandas-stubs moved to dev.
- **Why:** CI time, image size, attack surface. Camelot 2.0.0 needs only `pypdfium2`.

## D-010: Restore the optional LLM mode with a best-effort guard
- **Date:** 2026-10-27   Model: Claude Sonnet 5.5
- **Context:** The maintainer reviewed D-004 and chose to keep the LLM mode, accepting weaker consistency. Codex had said this is acceptable only under an explicit, weaker contract.
- **Options:**
  1. keep it bypassed
  2. restore with a guard, UI caveat and honest docs
  3. LLM only for non-decisive commentary.
- **Chosen:** 2 (maintainer's decision).
- **Why:** The mode is advertised and opt-in (`NARRATOR_MODE=llm`, default `rule_based`); the engine verdict and the badge stay authoritative.
- **How:** The model is asked only about `compliant` / `non-compliant`; it must repeat the verdict in `screen_verdict`; summary/verdict/bullets pass a keyword check; the label shown is the engine's; any doubt or error falls back to rule-based; `insufficient-data` never reaches the model; the UI shows an AI-generated caveat.
- **Trade-off:** Not a guarantee. A paraphrase the word lists miss can still contradict the verdict (a test documents that ceiling).
- **Revisit if:** a user is shown contradicting text, or a structured per-claim validation against the ratio facts is built (then the caveat can go).
