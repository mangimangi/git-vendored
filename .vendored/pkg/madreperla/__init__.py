"""madreperla — prompt methodology engine for prl.

Public API:
    get_prompt_body(mode, config) — Return interpolated body for a prompt mode.
    interpolate_vars(template, vars_dict) — Replace {key} placeholders in template.
    build_prompt_vars(config) — Build merged vars dict from config.
"""
from .prompt import get_prompt_body, get_prompt_resume_body, interpolate_vars, build_prompt_vars
