"""Behaviour that only exists while the flag does.

`flagpilot cleanup` deletes this file together with the flag read.
"""

from types import SimpleNamespace

import pytest

from demo.live import live_label

pytestmark = pytest.mark.flag("flagpilot-live")


@pytest.mark.parametrize("enabled, value, label", [
    (True, "new", "New"), (True, "control", "Old"), (False, "new", "Old"),
])
def test_label_follows_the_flag(enabled, value, label):
    asked = []

    def get_experiment_flag(name, identifier):
        asked.append((name, identifier))
        return SimpleNamespace(enabled=enabled, value=value)

    client = SimpleNamespace(get_experiment_flag=get_experiment_flag)
    assert live_label(client, "user-1") == label
    assert asked == [("flagpilot-live", "user-1")]
