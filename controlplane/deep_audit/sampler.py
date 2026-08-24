"""Sampled hand-off from the hot path to the deep lane.

Implements 02 §3/§4 (in-process asyncio queue per ADR-006) driven by policy
`sampling.deep_audit_rate`. Nothing on the hot path awaits this lane
(NFR-P-003).
STUB(phase-1-scaffold): no implementation yet.
"""
