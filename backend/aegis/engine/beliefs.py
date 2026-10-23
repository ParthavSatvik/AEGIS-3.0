"""Hidden-state generator. Builds plausible SoH states from documented priors and
legitimately obtained diagnostic results only - never from simulator truth."""
from __future__ import annotations

from ..models import DiagnosticEvidence, DiagnosticResult, HiddenState, ScenarioPublic
from .assessor import Assessment


def _r(x: float) -> float:
    return round(x, 4)


def prior_states(a: Assessment, pub: ScenarioPublic, counterfactual: bool = True) -> list[HiddenState]:
    """States implied by telemetry alone (before any diagnostic evidence)."""
    rs = a.readings["battery_soh"]
    priors = pub.priors["battery_soh"]
    nameplate = pub.nameplate["battery_soh"]
    if rs.status == "fresh":
        return [HiddenState(id="obs", label="Fresh reading", soh=_r(float(rs.value)), weight=1.0, source="observed")]
    if not counterfactual:  # ablation: take the point value at face value, unchallenged
        if rs.status == "stale":
            return [HiddenState(id="obs", label="Stale reading (unchallenged)", soh=_r(float(rs.value)), weight=1.0,
                                source="observed-stale")]
        return [HiddenState(id="nameplate", label="Nameplate assumption", soh=nameplate, weight=1.0,
                            source="nameplate")]
    if rs.status == "stale":
        base = float(rs.value)
        return [HiddenState(id=p.id, label=p.label, soh=_r(min(1.0, base + (p.delta or 0.0))), weight=p.weight,
                            source="prior-stale") for p in priors["stale"]]
    return [HiddenState(id=p.id, label=p.label, soh=_r(p.value), weight=p.weight, source="prior-missing")
            for p in priors["missing"]]


def posterior(priors: list[HiddenState], measured: float, accuracy: float, tag: str = "d") -> list[HiddenState]:
    """States after a conclusive measurement: the measurement interval plus any
    prior state the measurement cannot exclude."""
    keep = [s.model_copy(update={"weight": 0.25}) for s in priors if abs(s.soh - measured) <= accuracy + 1e-9]
    pts = [(f"{tag}-lo", "Measured - accuracy", measured - accuracy, 0.25),
           (f"{tag}-mid", "Measured", measured, 0.5),
           (f"{tag}-hi", "Measured + accuracy", measured + accuracy, 0.25)]
    out = keep + [HiddenState(id=i, label=lb, soh=_r(min(1.0, v)), weight=w, source="diagnostic")
                  for i, lb, v, w in pts]
    tot = sum(s.weight for s in out)
    return [s.model_copy(update={"weight": round(s.weight / tot, 4)}) for s in out]


def current_states(priors: list[HiddenState], evidence: list[DiagnosticResult], t_now: float
                   ) -> tuple[list[HiddenState], list[DiagnosticEvidence]]:
    """Apply the most recent valid conclusive diagnostic. Inconclusive results never remove states."""
    log = []
    states = priors
    latest = None
    for d in evidence:
        ruled = []
        if d.conclusive and d.measured is not None and d.valid_until >= t_now:
            latest = d
            ruled = [p.id for p in priors if abs(p.soh - d.measured) > d.accuracy + 1e-9]
        log.append(DiagnosticEvidence(diagnostic_id=d.diagnostic_id, conclusive=d.conclusive and d.valid_until >= t_now,
                                      measured=d.measured, accuracy=d.accuracy, ruled_out=ruled))
    if latest is not None:
        states = posterior(priors, latest.measured, latest.accuracy)
    return states, log
