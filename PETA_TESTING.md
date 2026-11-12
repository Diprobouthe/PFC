# PETA Algorithm — protected development branch

This branch contains **policy-neutral primitives only** for the new Certified Entity
algorithm. It does not enable PETA tournaments or change existing PFC ratings.

## Public code boundaries

- `cert_ratings/peta_core.py`: PFC rating-function delegation, protected starting
  rating, award splitting, and deterministic weighted dividend calculation.
- `cert_ratings/test_peta_core.py`: synthetic tests. All test values are examples,
  **not** the real experimental award values, category boundaries or weights.
- `.github/workflows/peta-core-tests.yml`: isolated Django/PostgreSQL tests.

## Intentionally excluded

The actual PETA experimental rules, award coefficients, class selection,
contribution eligibility parameters, policy seed and cryptographic commitment
salt are not stored in this public repository or in the GitHub Actions logs.
An authorized deployment will need an auditable, immutable policy package from
private storage. A public code repository is **not** a suitable place for a
supposedly hidden policy.

## Next integration stages

1. Add PETA series/event and protected entry snapshots to `cert_ratings` behind
   its own `rating_system` choice and migration; preserve classic Elo behavior.
2. Process each completed tournament match with the same PFC rating formula
   but PETA-only persisted ratings, with pre-match opponent averages.
3. On authoritative event finalization, use independently frozen event stats
   and a private immutable policy to choose award amounts, eligible recipients
   and distribution weights. Record a one-time auditable settlement.
4. Run 8-event replay and PostgreSQL concurrency/idempotency tests.
5. Test staging without sharing the production database. Review a Draft PR;
   do not merge until full end-to-end verification.

**Status:** first safe CI slice only; not a production-ready integration.
