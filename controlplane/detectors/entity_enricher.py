"""`entity_enricher` enrichment stage (ADR-011).

Implements 04 §2.2: spaCy en_core_web_sm NER over spans of span-bearing
`hallucination.*` signals; a PERSON entity appends `privacy.person` + the
`responsibility` plane to the SAME signal (one-signal rule, FR-DET-005).
Budget <10 ms. Enrichment failure skips + logs; never blocks, not a policy
`fail_mode` class.
STUB(phase-1-scaffold): no implementation yet.
"""
