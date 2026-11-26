"""One function behind a throwaway flag, for rehearsing the whole Flag Pilot chain."""


def dress_label(client, user_id: str) -> str:
    # Identifies the user, resolves the flag and records the exposure.
    flag = client.get_experiment_flag("flagpilot-dress", identifier=user_id)
    if flag.enabled and flag.value == "new":
        return "New"
    return "Old"
