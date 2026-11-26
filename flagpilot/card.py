"""The deterministic plain-English decision card."""

import json

from flagpilot.recommend import ACTIVE, SHIP_CONTROL, SHIP_VARIANT


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    widths = [max(len(row[i]) for row in [header, *rows]) for i in range(len(header))]
    return ["  " + "  ".join(c.ljust(w) for c, w in zip(row, widths)).rstrip()
            for row in [header, *rows]]


def _percent(value: float | None, signed: bool = False) -> str:
    if value is None:
        return "-"
    return f"{value:+.0%}" if signed else f"{value:.1%}"


def _value(rule: dict) -> str:
    value = rule["value"]
    if value is None:
        return "unknown"
    if rule["rule"] == "chance_to_win":
        return _percent(value)
    if rule["rule"] == "excluded_identities":
        return _percent(value)
    if rule["rule"] == "srm":
        return f"p={value:.3g} ({rule['source']})"
    return str(value)


def _summary(decision: dict) -> str:
    verdict = decision["verdict"]
    if verdict == SHIP_VARIANT:
        arm = next(a for a in decision["arms"] if a["key"] == decision["winner"])
        return (f"Ship '{decision['winner']}': it has a {_percent(arm['chance_to_win'])} chance "
                "to beat control, and every rule passes.")
    if verdict == SHIP_CONTROL:
        return "Ship control: no variant is likely to beat it, and every rule passes."
    status = decision["experiment"]["status"]
    if status not in ACTIVE:
        return f"Nothing to ship: the experiment is '{status}'."
    failed = ", ".join(r["rule"] for r in decision["rules"] if not r["passed"])
    return f"Do not ship yet. Not passing: {failed}."


def render(decision: dict) -> str:
    experiment, data = decision["experiment"], decision["data"]
    lines = [
        f"Experiment {experiment['id']}: {experiment['name']} "
        f"({experiment['status']}), flag {experiment['flag']}",
        f"VERDICT: {decision['verdict']}",
        _summary(decision),
        f"Data: results as of {data['results_as_of']}, "
        f"exposures as of {data['exposures_as_of']}",
        "",
    ]
    rows = []
    for arm in decision["arms"]:
        lift = "-"
        if arm["lift"] is not None:
            lift = (f"{_percent(arm['lift'], True)} ({_percent(arm['ci_low'], True)} to "
                    f"{_percent(arm['ci_high'], True)})")
        chance = "baseline" if arm["key"] == "control" else _percent(arm["chance_to_win"])
        rows.append([arm["key"], str(arm["identities"]), str(arm["conversions"]),
                     _percent(arm["rate"]), chance, lift])
    lines += _table(["Arm", "Identities", "Conversions", "Rate", "Chance to win",
                     "Relative lift (interval)"], rows)
    lines += ["", "Rules"]
    lines += _table(
        ["#", "Rule", "Value", "Needs", "Result", "Detail"],
        [[str(i), r["rule"], _value(r), r["threshold"], "PASS" if r["passed"] else "FAIL",
          r["detail"]] for i, r in enumerate(decision["rules"], 1)],
    )
    lines.append("")
    call = decision["ship_call"]
    if call:
        lines += ["`flagpilot ship` would call:", f"  {call['method']} {call['path']}",
                  f"  {json.dumps(call['body'])}"]
    else:
        lines.append("`flagpilot ship` would make no call.")
    if decision["verdict"] == SHIP_CONTROL:
        lines.append("Warning: only the 'variant' decision of complete/ has been smoke-tested.")
    lines += [f"Dashboard: {decision['dashboard']}", f"Note: {decision['note']}."]
    return "\n".join(lines)
