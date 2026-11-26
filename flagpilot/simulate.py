"""Send SIMULATED users through the checkout experiment.

The users and their purchase rates are made up here. Flagsmith assigns the arms and
computes the results, but the behaviour behind them is simulated: say so in any demo.

Dry-run is the default and sends nothing.

    python -m flagpilot.simulate [--users 400] [--apply --approved-by NAME]
"""

import argparse
import logging
import random
import sys
from collections import Counter

from flagsmith import EventProcessorConfig, Flagsmith

from flagpilot import audit, config, provision

TIER = 2  # writes into the experiment's data


# The SDK logs this for each failed attempt, including ones a retry then delivers.
# A batch that is finally lost or held back logs a different warning as well.
RETRY_WARNING = "Failed to send "


class DeliveryError(RuntimeError):
    pass


class _SdkWarnings(logging.Handler):
    """The SDK only logs failed or dropped events, so collect those log records."""

    def __init__(self):
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def make_client(events_api_url: str | None = None, api_url: str | None = None,
                environment_key: str | None = None) -> Flagsmith:
    events = {"events_api_url": events_api_url} if events_api_url else {}
    return Flagsmith(
        environment_key=environment_key or config.server_key(),
        api_url=api_url,
        enable_events=True,
        event_processor_config=EventProcessorConfig(max_buffer_items=1, **events),
    )


def user_ids(count: int, prefix: str) -> list[str]:
    return [f"{prefix}-{n:05d}" for n in range(1, count + 1)]


def simulate(
    client: Flagsmith,
    ids: list[str],
    rates: dict[str, float],
    seed: int,
    sent: Counter | None = None,
    sdk_warnings: list[str] | None = None,
) -> Counter:
    """Return counts of what was delivered, per arm. Raises on the first lost event.

    Pass `sent` and `sdk_warnings` to keep the partial counts if the run fails.
    """
    warnings = _SdkWarnings()
    if sdk_warnings is not None:
        warnings.messages = sdk_warnings
    sdk_log = logging.getLogger("flagsmith")
    sdk_log.addHandler(warnings)
    sent = Counter() if sent is None else sent

    def flush() -> None:
        # max_buffer_items=1 also caps the buffer at one event, so each event must
        # be delivered before the next is tracked, or the older one is dropped.
        client.flush_events()
        problems = [m for m in warnings.messages if not m.startswith(RETRY_WARNING)]
        if problems:
            raise DeliveryError(f"Event delivery problem: {problems[0]}")

    try:
        for user_id in ids:
            flag = client.get_experiment_flag(config.FLAG_NAME, identifier=user_id)
            enrolled = flag.enabled and getattr(flag, "experiment", None)
            if not (enrolled and flag.experiment.in_experiment and flag.variant):
                sent["not_enrolled"] += 1
                continue
            flush()
            arm = flag.value
            sent[f"exposed:{arm}"] += 1
            if random.Random(f"{seed}:{user_id}").random() < rates[arm]:
                client.track_event(config.CONVERSION_EVENT, identifier=user_id)
                flush()
                sent[f"converted:{arm}"] += 1
    finally:
        client.close()
        sdk_log.removeHandler(warnings)
    return sent


def experiment_is_running() -> bool:
    return any(
        e["name"] == config.EXPERIMENT_NAME and e["status"] == "running"
        for e in provision.experiments()
    )


def probability(text: str) -> float:
    value = float(text)
    if not 0 <= value <= 1:
        raise argparse.ArgumentTypeError("must be between 0 and 1")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--users", type=int, default=400)
    parser.add_argument("--prefix", default="sim-user")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--control-rate", type=probability, default=0.10)
    parser.add_argument("--variant-rate", type=probability, default=0.16)
    parser.add_argument("--apply", action="store_true", help="send real traffic")
    parser.add_argument("--approved-by", help="who approved this run (required with --apply)")
    args = parser.parse_args(argv)
    if args.apply and not args.approved_by:
        parser.error("--apply requires --approved-by")
    if args.users < 1:
        parser.error("--users must be at least 1")

    rates = {config.CONTROL_VALUE: args.control_rate, config.VARIANT_VALUE: args.variant_rate}
    ids = user_ids(args.users, args.prefix)
    plan = {
        "flag": config.FLAG_NAME,
        "event": config.CONVERSION_EVENT,
        "users": args.users,
        "identifiers": [ids[0], ids[-1]],
        "simulated_purchase_rates": rates,
        "seed": args.seed,
    }
    log = dict(action="simulate_traffic", tier=TIER, method="SDK",
               path=f"simulate {config.FLAG_NAME}", body=plan)
    print(f"{'APPLY' if args.apply else 'DRY-RUN'}  tier {TIER}  simulated traffic: {plan}")
    if not args.apply:
        audit.record(**log, dry_run=True, status="planned")
        return 0

    if not experiment_is_running():
        print(f"BLOCKED: experiment '{config.EXPERIMENT_NAME}' is not running.", file=sys.stderr)
        audit.record(**log, dry_run=False, approved_by=args.approved_by, status="blocked")
        return 1
    sent: Counter = Counter()
    sdk_warnings: list[str] = []
    status = "failed"
    try:
        simulate(make_client(), ids, rates, args.seed, sent, sdk_warnings)
        status = "success"
    finally:
        audit.record(**log, dry_run=False, approved_by=args.approved_by, status=status)
        print(f"{status}. delivered: {dict(sorted(sent.items()))}")
        print(f"SDK warnings: {len(sdk_warnings)}")
        for message, count in Counter(sdk_warnings).most_common(10):
            print(f"  {count}x {message}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
