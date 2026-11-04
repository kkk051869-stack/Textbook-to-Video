"""Order and model sensitivity without treating model consensus as truth."""

from collections import Counter

from textbook2video.research.rq1_preference_judge import PROPOSAL_AXES


def summarize_controlled(
    rows: list[dict], models: list[str], *, proposition_ids: list[str]
) -> dict:
    ids = sorted(proposition_ids)
    if not ids or len(set(ids)) != len(ids) or len(set(models)) != len(models) or not models:
        raise ValueError("plan requires unique nonempty proposition IDs and models")
    indexed = {}
    for row in rows:
        key = (row["proposition_id"], row["model"], row["order"])
        if key[0] not in ids or key[1] not in models or key[2] not in ("forward", "reverse"):
            raise ValueError(f"judgment outside plan: {key}")
        if key in indexed:
            raise ValueError(f"duplicate judgment: {key}")
        indexed[key] = row
    items = []
    for pid in ids:
        group = [
            indexed.get((pid, model, order)) for model in models for order in ("forward", "reverse")
        ]
        valid = [r for r in group if r and r["status"] == "OK" and not r["judgment"]["abstain"]]
        winners = [r["judgment"]["best_action"] for r in valid]
        complete = len(valid) == len(models) * 2
        top1_stable = complete and len(set(winners)) == 1
        signatures = {
            (tuple(r["judgment"]["ranking"]), tuple(sorted(r["judgment"]["rejected_actions"])))
            for r in valid
        }
        stable = top1_stable and len(signatures) == 1
        items.append(
            {
                "proposition_id": pid,
                "status": "MODEL_CONSISTENT_PROXY" if stable else "UNRESOLVED",
                "proxy_best_action": winners[0] if stable else None,
                "valid_judgments": len(valid),
                "top1_consistent_across_model_orders": top1_stable,
                "top1_order_stable_by_model": {
                    model: bool(
                        indexed.get((pid, model, "forward")) in valid
                        and indexed.get((pid, model, "reverse")) in valid
                        and indexed[(pid, model, "forward")]["judgment"]["best_action"]
                        == indexed[(pid, model, "reverse")]["judgment"]["best_action"]
                    )
                    for model in models
                },
                "full_order_stable_by_model": {
                    model: bool(
                        indexed.get((pid, model, "forward")) in valid
                        and indexed.get((pid, model, "reverse")) in valid
                        and indexed[(pid, model, "forward")]["judgment"]["ranking"]
                        == indexed[(pid, model, "reverse")]["judgment"]["ranking"]
                        and set(indexed[(pid, model, "forward")]["judgment"]["rejected_actions"])
                        == set(indexed[(pid, model, "reverse")]["judgment"]["rejected_actions"])
                    )
                    for model in models
                },
            }
        )
    scores = {}
    methods = sorted({m for r in rows for m in r["method_choices"]})
    for model in models:
        for order in ("forward", "reverse"):
            group = [r for r in rows if r["model"] == model and r["order"] == order]
            valid = [r for r in group if r["status"] == "OK" and not r["judgment"]["abstain"]]
            scores[f"{model}/{order}"] = {
                "planned": len(ids),
                "valid_nonabstain": len(valid),
                "not_run": len(ids) - len(group),
                "status_counts": dict(Counter(r["status"] for r in group)),
                "methods": {
                    method: {
                        "proxy_top1_count": sum(
                            r["method_choices"][method] == r["judgment"]["best_action"]
                            for r in valid
                        ),
                        "rejected_count": sum(
                            r["method_choices"][method] in r["judgment"]["rejected_actions"]
                            for r in valid
                        ),
                        "ineligible_count": sum(
                            r["method_choices"][method] not in r["judgment"]["eligible_actions"]
                            for r in valid
                        ),
                        "action_counts_observed_rows": dict(
                            Counter(r["method_choices"][method] for r in group)
                        ),
                    }
                    for method in methods
                },
            }
    return {
        "planned_propositions": len(ids),
        "planned_judgments": len(ids) * len(models) * 2,
        "model_consistent_proxy_count": sum(x["status"] == "MODEL_CONSISTENT_PROXY" for x in items),
        "unresolved_count": sum(x["status"] == "UNRESOLVED" for x in items),
        "items": items,
        "per_model_order": scores,
        "claim": "Model consistency is a proxy, not gold or evidence of learning effects.",
    }


def summarize_blind_proposal_comparison(
    *,
    tasks: list[dict],
    judgments: list[dict],
    judge_models: list[str],
) -> dict:
    """Summarize anonymous proposal rankings without turning them into gold labels."""
    proposition_ids = [str(task["proposition_id"]) for task in tasks]
    if not proposition_ids or len(set(proposition_ids)) != len(proposition_ids):
        raise ValueError("blind comparison requires a fixed unique proposition denominator")
    if not judge_models or len(set(judge_models)) != len(judge_models):
        raise ValueError("blind comparison requires unique Judge model aliases")
    indexed = {}
    for row in judgments:
        key = (row["proposition_id"], row["model"], row["order"])
        if key[0] not in set(proposition_ids) or key[1] not in set(judge_models):
            raise ValueError(f"judgment outside frozen plan: {key}")
        if key[2] not in {"forward", "reverse"} or key in indexed:
            raise ValueError(f"duplicate or invalid judgment identity: {key}")
        indexed[key] = row

    method_ids = sorted(
        {
            method
            for task in tasks
            for method in task.get("method_to_option", {})
        }
    )
    task_by_id = {str(task["proposition_id"]): task for task in tasks}
    proposal_counts = {method: Counter() for method in method_ids}
    axis_scores = {method: {axis: [] for axis in PROPOSAL_AXES} for method in method_ids}
    per_model_order = {}
    for model in judge_models:
        for order in ("forward", "reverse"):
            group = [
                indexed.get((pid, model, order))
                for pid in proposition_ids
            ]
            valid = [
                row
                for row in group
                if row and row.get("status") == "OK" and not row["judgment"].get("abstain")
            ]
            per_model_order[f"{model}/{order}"] = {
                "planned": len(proposition_ids),
                "valid_nonabstain": len(valid),
                "not_run_or_failed": len(proposition_ids) - len(valid),
                "top1_method_counts": dict(
                    Counter(
                        task_by_id[row["proposition_id"]]["option_to_method"][
                            row["judgment"]["best_option_id"]
                        ]
                        for row in valid
                    )
                ),
            }
            for row in group:
                if not row or row.get("status") != "OK":
                    continue
                task = task_by_id[row["proposition_id"]]
                judgment = row["judgment"]
                option_to_method = task["option_to_method"]
                if judgment.get("abstain"):
                    continue
                best = option_to_method[judgment["best_option_id"]]
                proposal_counts[best]["top1"] += 1
                acceptable = set(judgment["acceptable_option_ids"])
                rejected = set(judgment["rejected_option_ids"])
                for option_id, method in option_to_method.items():
                    if option_id in acceptable:
                        proposal_counts[method]["acceptable"] += 1
                    if option_id in rejected:
                        proposal_counts[method]["rejected"] += 1
                    for axis, score in judgment["axis_scores"][option_id].items():
                        axis_scores[method][axis].append(score)

    per_proposition = []
    order_sensitivity = {"planned_model_pairs": 0, "top1_changed": 0, "full_ranking_changed": 0}
    for proposition_id in proposition_ids:
        task = task_by_id[proposition_id]
        valid = [
            indexed.get((proposition_id, model, order))
            for model in judge_models
            for order in ("forward", "reverse")
        ]
        valid = [
            row for row in valid if row and row.get("status") == "OK"
        ]
        top1 = [
            task["option_to_method"][row["judgment"]["best_option_id"]]
            for row in valid
            if not row["judgment"].get("abstain")
        ]
        rankings = [
            tuple(task["option_to_method"][opt] for opt in row["judgment"]["ranking"])
            for row in valid
            if not row["judgment"].get("abstain")
        ]
        acceptable_by_judgment = [
            {
                task["option_to_method"][opt]
                for opt in row["judgment"]["acceptable_option_ids"]
            }
            for row in valid
            if not row["judgment"].get("abstain")
        ]
        top1_by_model_order = {}
        rejected_by_judgment = []
        for row in valid:
            task = task_by_id[row["proposition_id"]]
            judgment = row["judgment"]
            option_to_method = task["option_to_method"]
            top1_by_model_order[f"{row['model']}/{row['order']}"] = (
                None
                if judgment.get("abstain")
                else option_to_method[judgment["best_option_id"]]
            )
            rejected_by_judgment.append(
                sorted(option_to_method[option] for option in judgment["rejected_option_ids"])
            )
        order_pair_changes = {}
        for model in judge_models:
            forward = indexed.get((proposition_id, model, "forward"))
            reverse = indexed.get((proposition_id, model, "reverse"))
            if not (
                forward and reverse
                and forward.get("status") == "OK"
                and reverse.get("status") == "OK"
                and not forward["judgment"].get("abstain")
                and not reverse["judgment"].get("abstain")
            ):
                continue
            order_sensitivity["planned_model_pairs"] += 1
            forward_task = task_by_id[proposition_id]
            forward_judgment = forward["judgment"]
            reverse_judgment = reverse["judgment"]
            top1_changed = (
                forward_task["option_to_method"][forward_judgment["best_option_id"]]
                != forward_task["option_to_method"][reverse_judgment["best_option_id"]]
            )
            ranking_changed = tuple(
                forward_task["option_to_method"][item] for item in forward_judgment["ranking"]
            ) != tuple(
                forward_task["option_to_method"][item] for item in reverse_judgment["ranking"]
            )
            order_pair_changes[model] = {
                "top1_changed": top1_changed,
                "full_ranking_changed": ranking_changed,
            }
            order_sensitivity["top1_changed"] += int(top1_changed)
            order_sensitivity["full_ranking_changed"] += int(ranking_changed)
        per_proposition.append(
            {
                "proposition_id": proposition_id,
                "document_id": task["document_id"],
                "planned_judgments": len(judge_models) * 2,
                "valid_judgments": len(valid),
                "abstentions": sum(
                    bool(row["judgment"].get("abstain")) for row in valid
                ),
                "proxy_top1_methods": top1,
                "top1_by_model_order": top1_by_model_order,
                "acceptable_methods_by_judgment": [
                    sorted(values) for values in acceptable_by_judgment
                ],
                "rejected_methods_by_judgment": rejected_by_judgment,
                "order_pair_changes_by_model": order_pair_changes,
                "top1_stable_across_models_and_orders": bool(
                    len(top1) == len(judge_models) * 2 and len(set(top1)) == 1
                ),
                "full_ranking_stable_across_models_and_orders": bool(
                    len(rankings) == len(judge_models) * 2 and len(set(rankings)) == 1
                ),
                "judge_disagreement_retained": len(set(top1)) > 1 or len(set(rankings)) > 1,
            }
        )
    per_method = {}
    for method in method_ids:
        per_method[method] = {
            "anonymous_judge_top1_count": proposal_counts[method]["top1"],
            "acceptable_count": proposal_counts[method]["acceptable"],
            "rejected_count": proposal_counts[method]["rejected"],
            "axis_mean": {
                axis: round(sum(values) / len(values), 3) if values else None
                for axis, values in axis_scores[method].items()
            },
            "axis_observations": {
                axis: len(values) for axis, values in axis_scores[method].items()
            },
        }
    return {
        "planned_propositions": len(proposition_ids),
        "planned_judgments": len(proposition_ids) * len(judge_models) * 2,
        "valid_judgments": sum(
            row.get("status") == "OK" for row in judgments
        ),
        "abstentions": sum(
            row.get("status") == "OK" and row["judgment"].get("abstain")
            for row in judgments
        ),
        "per_model_order": per_model_order,
        "order_sensitivity": order_sensitivity,
        "per_method": per_method,
        "per_proposition": per_proposition,
        "claim": (
            "LLM/VLM preference and scores are proxy evaluations, not human gold or learning "
            "effects."
        ),
    }


def summarize_canonical_rq1(
    *,
    method_ids: list[str],
    proposition_ids: list[str],
    predictions: list[dict],
    judge_results: list[dict],
    judge_aliases: list[str],
) -> dict:
    """Summarize LLM decision proxies and material outcomes with planned denominators."""
    if not method_ids or not proposition_ids or len(set(method_ids)) != len(method_ids):
        raise ValueError("canonical RQ1 summary requires unique methods and propositions")
    if not judge_aliases or len(set(judge_aliases)) != len(judge_aliases):
        raise ValueError("canonical RQ1 summary requires unique Judge aliases")

    prediction_index = {}
    for row in predictions:
        key = (str(row.get("proposition_id") or ""), str(row.get("method_id") or ""))
        if key in prediction_index:
            raise ValueError(f"duplicate prediction row: {key}")
        prediction_index[key] = row

    per_method: dict[str, dict] = {}
    for method in method_ids:
        planned_rows = [prediction_index.get((prop, method)) for prop in proposition_ids]
        available = [row for row in planned_rows if row and row.get("status") == "OK"]
        actions = Counter(str((row.get("decision") or {}).get("action") or "UNKNOWN") for row in available)
        acquisition = Counter(
            str((((row.get("acquisition") or {}).get("assets") or [{}])[0]).get("status") or "MISSING")
            for row in available
        )
        per_method[method] = {
            "planned": len(proposition_ids),
            "output_available": len(available),
            "missing_or_failed": len(proposition_ids) - len(available),
            "coverage": len(available) / len(proposition_ids),
            "action_counts": dict(sorted(actions.items())),
            "uncertain_count": sum(bool((row.get("decision") or {}).get("uncertain")) for row in available),
            "abstain_count": sum(bool((row.get("decision") or {}).get("abstain")) for row in available),
            "acquisition_status_counts": dict(sorted(acquisition.items())),
        }

    objects_by_proposition: dict[str, set[tuple[str, str]]] = {}
    for row in predictions:
        if row.get("status") != "OK":
            continue
        prop = str(row.get("proposition_id") or "")
        assets = (row.get("acquisition") or {}).get("assets") or []
        asset = assets[0] if assets and isinstance(assets[0], dict) else {}
        object_id = (
            asset.get("catalog_candidate_id")
            or asset.get("source_image_id")
            or asset.get("asset_id")
            or asset.get("best_candidate_id")
        )
        digest = asset.get("sha256")
        if object_id or digest:
            objects_by_proposition.setdefault(prop, set()).add((str(object_id or ""), str(digest or "")))
    object_disagreement = {
        prop: [
            {"object_id": object_id or None, "sha256": digest or None}
            for object_id, digest in sorted(values)
        ]
        for prop, values in sorted(objects_by_proposition.items())
        if len(values) > 1
    }

    judge_index = {}
    for row in judge_results:
        key = (
            str(row.get("proposition_id") or ""),
            str(row.get("judge_alias") or ""),
            str(row.get("display_order") or ""),
        )
        if key in judge_index:
            raise ValueError(f"duplicate Judge result: {key}")
        judge_index[key] = row
    valid_judges = [row for row in judge_results if row.get("status") == "OK"]
    per_method_membership = {
        method: {"judged": 0, "acceptable": 0, "preferred": 0}
        for method in method_ids
    }
    for row in valid_judges:
        judgment = row.get("judgment") or {}
        mapping = row.get("method_to_proposal") or {}
        acceptable = set(judgment.get("acceptable_proposal_ids") or [])
        preferred = set(judgment.get("preferred_proposal_ids") or [])
        for method in method_ids:
            proposal_id = mapping.get(method)
            if proposal_id:
                per_method_membership[method]["judged"] += 1
                per_method_membership[method]["acceptable"] += int(proposal_id in acceptable)
                per_method_membership[method]["preferred"] += int(proposal_id in preferred)

    pair_rows = []
    for prop in proposition_ids:
        for alias in judge_aliases:
            forward = judge_index.get((prop, alias, "forward"))
            reverse = judge_index.get((prop, alias, "reverse"))
            if not forward or not reverse or forward.get("status") != "OK" or reverse.get("status") != "OK":
                continue
            jf, jr = forward.get("judgment") or {}, reverse.get("judgment") or {}
            af, ar = set(jf.get("acceptable_proposal_ids") or []), set(jr.get("acceptable_proposal_ids") or [])
            pf, pr = set(jf.get("preferred_proposal_ids") or []), set(jr.get("preferred_proposal_ids") or [])
            sf, sr = jf.get("strict_ranking_diagnostic"), jr.get("strict_ranking_diagnostic")
            pair_rows.append({
                "proposition_id": prop,
                "judge_alias": alias,
                "acceptable_set_changed": af != ar,
                "preferred_set_changed": pf != pr,
                "assessment_changed": (jf.get("assessment_by_proposal") or {}) != (jr.get("assessment_by_proposal") or {}),
                "strict_ranking_available_both": sf is not None and sr is not None,
                "strict_ranking_changed": sf != sr,
            })

    planned_predictions = len(method_ids) * len(proposition_ids)
    planned_judges = len(judge_aliases) * 2 * len(proposition_ids)
    return {
        "status": "ANALYZED_AS_LLM_PROXY_AND_OBJECTIVE_ENGINEERING_METRICS",
        "human_truth_available": False,
        "human_accuracy_claim": False,
        "planned_method_outputs": planned_predictions,
        "available_method_outputs": sum(item["output_available"] for item in per_method.values()),
        "method_output_coverage": {
            "numerator": sum(item["output_available"] for item in per_method.values()),
            "denominator": planned_predictions,
        },
        "per_method": per_method,
        "candidate_object_disagreement_propositions": object_disagreement,
        "planned_judge_order_slots": planned_judges,
        "valid_judge_order_slots": len(valid_judges),
        "judge_order_slot_coverage": {"numerator": len(valid_judges), "denominator": planned_judges},
        "per_method_judge_membership": {
            method: {
                **counts,
                "acceptable_rate": counts["acceptable"] / counts["judged"] if counts["judged"] else None,
                "preferred_rate": counts["preferred"] / counts["judged"] if counts["judged"] else None,
            }
            for method, counts in per_method_membership.items()
        },
        "valid_forward_reverse_pairs": len(pair_rows),
        "forward_reverse_pair_diagnostics": pair_rows,
        "acceptable_set_changed_pairs": sum(row["acceptable_set_changed"] for row in pair_rows),
        "preferred_set_changed_pairs": sum(row["preferred_set_changed"] for row in pair_rows),
        "assessment_changed_pairs": sum(row["assessment_changed"] for row in pair_rows),
        "strict_ranking_available_pairs": sum(row["strict_ranking_available_both"] for row in pair_rows),
        "strict_ranking_changed_pairs": sum(row["strict_ranking_changed"] for row in pair_rows),
        "interpretation": "LLM Judge outputs are proxies. Repeated aliases/orders are not independent教材 samples or a gold standard.",
    }
