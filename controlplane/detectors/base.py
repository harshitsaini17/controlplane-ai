"""Detector contract, Signal model, and detector exceptions.

Implements 04 §1 (signal model, incl. score_kind per ADR-012), 04 §1.1 (label
taxonomy) and the 04 §2 common contract: `async detect(ctx) -> list[Signal]`,
raising DetectorTimeout / DetectorError rather than hanging.
STUB(phase-1-scaffold): no implementation yet.
"""
