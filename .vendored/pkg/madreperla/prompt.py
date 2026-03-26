"""Prompt methodology: body templates, interpolation, and variable resolution."""
from __future__ import annotations

from typing import Any

# ── Default Body Templates ───────────────────────────────────────────────────

DEFAULT_PLANNING_BODY = """I'd like to plan some features together and create markdown docs that completely/minimally encapsulate the features... If anything is unclear or ambiguous let's dig into it together and get to a shared place of clarity. as part of this planning - we must discern if the work is ready to be refined into implementation tasks\u2026if so, we need to decide what epic the work will be created in (or if we need to create a new epic).

if the work is ready for refinement, create an epic (if it doesn't already exist) and save the planning doc to docs/planning/epics/<epic-id>.md (moving it from docs/planning/ if relevant info from prior planning docs exists). otherwise create/update the planning docs in docs/planning/. check the issue tracker docs for CLI syntax. commit and push your changes when we're done planning.

the scope of the work I want to plan is:"""

DEFAULT_REFINE_BODY = """I'd like to refine some features together and create straightforward issues that are small in scope with clear acceptance criteria...if applicable we should specify requirements for extending docs and tests in addition to implementing the functionality of the feature. If anything is unclear or ambiguous let's dig into it together and get to a shared place of clarity. as part of this refinement - we should discern what epic the issue(s) will be created in (or if a new epic will be created).

if an epic id is provided, check docs/planning/epics/<epic-id>.md for planning context. after creating issues, update the planning doc to remove items that have been refined into issues \u2014 delete the file if everything has been refined. commit and push your changes when done.

the scope of the work I want to refine is:"""

DEFAULT_ESTIMATE_BODY = """then let's estimate some issues and add your token estimate...you can assume the issues will be implemented by {implementer} unless otherwise specified. check the issue tracker docs for the estimate CLI syntax. we can disregard any existing estimates as they are likely stale!

please estimate each open tasks/subtasks in epic"""

DEFAULT_IMPLEMENT_BODY = """then I'd like you to implement the open tasks/subtasks in an epic and you can leave the epic open when you're finished in case we need to file more issues later

the epic id is:"""

DEFAULT_ONESHOT_BODY = """I'd like to refine some features together and create straightforward issues that are small in scope with clear acceptance criteria...if applicable we should specify requirements for extending docs and tests in addition to implementing the functionality of the feature. If anything is unclear or ambiguous let's dig into it together and get to a shared place of clarity. as part of this refinement - we should discern what epic the issue(s) will be created in (or if a new epic will be created).

we can create the issues in the '1shots' epic...and after we've refined the work and created the issues, go ahead & estimate then implement!

the scope of the work I want to refine is:"""

DEFAULT_EVAL_BODY = """then I'd like you to evaluate the implemented issues in an epic. for each implemented issue:

1. find the code changes: show the issue details \u2014 if it has a `pr_number`, use `gh pr diff <pr_number>`; otherwise `git show <commit>`
2. score each dimension 0-100:
{eval_dimensions}
3. record the evaluation with `{eval_cli_example}` \u2014 the issue tracker auto-closes issues when all scores meet their threshold
4. if you find defects, create a defect ticket linked to the original issue

leave the epic open when you're finished.

the epic id is:"""

DEFAULT_CLEANUP_BODY = """then can you please archive closed epics and closed parent-less issues as well as any children of open epics that do not relate explicitly/implicitly to existing open children

any open epics without open children should be closed but NOT archived \u2014 preserve long-lived collection epics. check the issue tracker docs for which epics to keep open."""

DEFAULT_BODIES: dict[str, str] = {
    "planning": DEFAULT_PLANNING_BODY,
    "refine": DEFAULT_REFINE_BODY,
    "estimate": DEFAULT_ESTIMATE_BODY,
    "implement": DEFAULT_IMPLEMENT_BODY,
    "oneshot": DEFAULT_ONESHOT_BODY,
    "eval": DEFAULT_EVAL_BODY,
    "cleanup": DEFAULT_CLEANUP_BODY,
}


# ── Helpers ──────────────────────────────────────────────────────────────────

_DEFAULT_EVAL_DIMENSIONS: dict[str, dict[str, str]] = {
    "correctness": {"description": "Does it work as specified?"},
    "completeness": {"description": "Are all acceptance criteria met?"},
    "quality": {"description": "Is it clean, maintainable, well-structured?"},
    "testing": {"description": "Are changes adequately tested?"},
    "documentation": {"description": "Are changes documented where needed?"},
}


def _get_eval_dimensions(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve eval dimensions from config for prompt rendering."""
    global_threshold = config.get("eval", {}).get("threshold", 80)
    dims_config = config.get("eval", {}).get("dimensions")

    if dims_config:
        return [
            {
                "name": name,
                "description": (spec or {}).get("description", ""),
                "threshold": (spec or {}).get("threshold", global_threshold),
            }
            for name, spec in dims_config.items()
        ]

    return [
        {"name": name, "description": spec["description"], "threshold": global_threshold}
        for name, spec in _DEFAULT_EVAL_DIMENSIONS.items()
    ]


def _format_eval_dimensions(dims: list[dict[str, Any]]) -> str:
    """Format dimensions as a bulleted list with thresholds and descriptions."""
    lines = []
    for d in dims:
        desc = f": {d['description']}" if d.get("description") else ""
        lines.append(f"   - {d['name']} (threshold: {d['threshold']}){desc}")
    return "\n".join(lines)


def _format_eval_cli_example(dims: list[dict[str, Any]], evaluator: str) -> str:
    """Generate `prl eval` CLI example with --score flags from dimensions."""
    score_flags = " ".join(f"--score {d['name']}=N" for d in dims)
    return f"prl eval <id> --evaluator {evaluator} {score_flags}"


def interpolate_vars(template: str, vars_dict: dict[str, str]) -> str:
    """Replace {key} placeholders in template with values from vars_dict.

    Unknown {key} patterns are left as-is.
    """
    result = template
    for key, value in vars_dict.items():
        result = result.replace("{" + key + "}", value)
    return result


def build_prompt_vars(config: dict[str, Any]) -> dict[str, str]:
    """Build the merged vars dict from config.

    Auto-seeds built-in vars:
        {implementer} — from models.implementer (default: claude-opus-4-6)
        {evaluator} — from models.evaluator (default: claude-opus-4-6)
        {eval_dimensions} — formatted list of eval dimensions with thresholds
        {eval_cli_example} — prl eval CLI example with --score flags

    User vars from prompts.vars override built-ins.
    """
    eval_dims = _get_eval_dimensions(config)
    user_vars = config.get("prompts", {}).get("vars", {})
    # User vars can override evaluator; resolve before embedding in cli example
    evaluator = user_vars.get("evaluator", config.get("models", {}).get("evaluator", "claude-opus-4-6"))

    built_in: dict[str, str] = {
        "implementer": config.get("models", {}).get("implementer", "claude-opus-4-6"),
        "evaluator": evaluator,
        "eval_dimensions": _format_eval_dimensions(eval_dims),
        "eval_cli_example": _format_eval_cli_example(eval_dims, evaluator),
    }
    return {**built_in, **user_vars}


def get_prompt_body(mode: str, config: dict[str, Any]) -> str:
    """Return the interpolated body for a prompt mode.

    Body resolution: config prompts.<mode> override → DEFAULT_*_BODY fallback.
    Vars resolution: prompts.vars (user) overrides built-in vars.
    """
    body = config.get("prompts", {}).get(mode) or DEFAULT_BODIES[mode]
    vars_dict = build_prompt_vars(config)
    return interpolate_vars(body, vars_dict)
