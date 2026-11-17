"""Translate existing semantic test fixtures to the model-facing VisualPlanV1 wire form."""

import json
from copy import deepcopy


def model_plan_json(fixture):
    if not isinstance(fixture, dict) or "plan_version" in fixture:
        return json.dumps(fixture, ensure_ascii=False)
    if "tool" not in fixture and "name" not in fixture:
        return json.dumps(fixture, ensure_ascii=False)

    operation = fixture.get("tool", fixture.get("name"))
    arguments = deepcopy(fixture.get("arguments"))
    if arguments is None:
        arguments = {key: deepcopy(value) for key, value in fixture.items()
                     if key not in {"tool", "name"}}
    if not isinstance(arguments, dict):
        return json.dumps(fixture, ensure_ascii=False)
    arguments.pop("parent", None)
    arguments.pop("reason", None)
    if operation == "compose":
        composition_keys = {"visual_ids", "axis", "horizontal_free", "vertical_free"}
        composition = {key: arguments.pop(key) for key in list(arguments)
                       if key in composition_keys}
        if composition:
            arguments["composition"] = composition
    return json.dumps({"plan_version": "visual-plan-v1", **arguments}, ensure_ascii=False)
