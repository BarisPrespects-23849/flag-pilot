"""One function behind a throwaway flag, for the live Flag Pilot demo."""


def live_label(client, user_id: str) -> str:
    # Identifies the user, resolves the flag and records the exposure.
    flag = client.get_experiment_flag("flagpilot-live", identifier=user_id)
    if flag.enabled and flag.value == "new":
        return "New"
    return "Old"
