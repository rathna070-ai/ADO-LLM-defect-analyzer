"""Corrective and preventive actions per root-cause category.

CAPA in the quality-management sense: a *corrective* action addresses the
defects that already escaped, a *preventive* action changes the process so the
category stops recurring. Leadership asks "so what do we do about it", and a
count without a recommended control does not answer that.

Kept as a static mapping rather than asked of the LLM per run: these are
standard process controls for each category, so generating them per defect
would cost tokens to re-derive the same answer and make the deck's advice
vary run to run for no benefit.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Capa:
    corrective: str
    preventive: str
    #: Categories that warrant escalation regardless of volume.
    priority: bool = False


_ACTIONS: dict[str, Capa] = {
    "requirements_gap": Capa(
        "Re-baseline the affected requirements and re-test the impacted flows.",
        "Require BA sign-off and an acceptance-criteria review before dev pickup.",
    ),
    "design_flaw": Capa(
        "Rework the design of the affected component and regression-test dependants.",
        "Add an architect-reviewed design gate for changes to shared components.",
    ),
    "coding_error": Capa(
        "Fix the defect and add a unit test that reproduces it.",
        "Enforce peer review on the hotspot modules and raise the CI coverage threshold.",
    ),
    "data_defect": Capa(
        "Correct the affected records and re-run the impacted jobs.",
        "Add data-validation rules and reconcile reference data before each release.",
    ),
    "integration_defect": Capa(
        "Align the interface contract and re-test the end-to-end flow.",
        "Add contract or schema-validation tests in CI for every integration point.",
    ),
    "configuration_defect": Capa(
        "Correct the environment configuration and verify parity across environments.",
        "Version-control configuration and add automated environment-parity checks.",
    ),
    "build_deployment_defect": Capa(
        "Redeploy with the corrected build or migration and verify post-deploy checks.",
        "Add smoke tests to the deployment pipeline and rehearse rollback each release.",
    ),
    "test_gap": Capa(
        "Add the missing test cases covering the escaped scenario.",
        "Run risk-based test-design review for the area; make it a definition-of-done item.",
    ),
    "third_party_defect": Capa(
        "Apply the vendor fix or an agreed workaround and re-verify.",
        "Pin vendor versions, monitor the integration, and agree an SLA escalation path.",
    ),
    "performance_defect": Capa(
        "Tune the identified bottleneck and re-run the load profile.",
        "Set performance budgets and make load testing a release gate.",
    ),
    "security_defect": Capa(
        "Remediate the vulnerability and re-run a full security scan.",
        "Add SAST/DAST to CI and schedule periodic security review for the area.",
        priority=True,
    ),
    "documentation_defect": Capa(
        "Correct the documentation and notify affected users.",
        "Add a documentation review step to the definition of done.",
    ),
    "process_communication_defect": Capa(
        "Clarify the hand-off and re-confirm ownership with both teams.",
        "Define RACI for cross-team hand-offs and add a hand-off checklist.",
    ),
    "not_a_defect": Capa(
        "Close with the rationale recorded so the decision is auditable.",
        "Tighten triage entry criteria and clarify expected behaviour in test cases.",
    ),
    "unknown": Capa(
        "Route for manual RCA — the work item lacks the detail to classify it.",
        "Make root cause and resolution notes mandatory fields at closure.",
        priority=True,
    ),
}

_FALLBACK = Capa(
    "Review the defects in this category and confirm the root cause.",
    "Define a preventive control once the pattern is understood.",
)


def actions_for(category: str) -> Capa:
    """CAPA for a root-cause category, with a safe fallback for unknown values."""
    return _ACTIONS.get(category, _FALLBACK)


#: Root causes attributable to how the code itself was written — the
#: engineering-quality bucket leadership reads as "our developers' output".
DEV_QUALITY_CATEGORIES = frozenset({"coding_error"})

#: Neither a code-quality nor a process signal, so counted in neither bucket.
#: `not_a_defect` was never a defect (duplicate, works as designed) and
#: `unknown` is unclassified — folding either into "process error" would
#: inflate a number leadership acts on with items that say nothing about the
#: process.
UNATTRIBUTED_CATEGORIES = frozenset({"not_a_defect", "unknown"})


def quality_bucket(category: str) -> str:
    """ "dev_quality", "process_error", or "unattributed" for a category."""
    if category in DEV_QUALITY_CATEGORIES:
        return "dev_quality"
    if category in UNATTRIBUTED_CATEGORIES:
        return "unattributed"
    return "process_error"
