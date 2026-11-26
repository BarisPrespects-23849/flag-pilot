"""Finding flag reads and rewriting them. All sources here are SYNTHETIC snippets."""

import textwrap

import pytest

from flagpilot import refs
from flagpilot.refs import Winner

BUY = Winner(True, "buy_now")
CONTROL = Winner(True, "control")
KNOWN = {"VARIANT_VALUE": {"buy_now"}, "FLAG_NAME": {"my_flag"}}


def source(text: str) -> str:
    return textwrap.dedent(text).lstrip("\n")


def rewritten(text: str, winner=BUY) -> str:
    return refs.rewrite(source(text), "my_flag", winner, KNOWN)


def sites(files: dict[str, str]) -> list[tuple[str, int, str]]:
    hits = [(p, n, line) for p, text in files.items()
            for n, line in enumerate(text.split("\n"), 1) if refs.mentions(line, "my_flag")]
    return [(s.path, s.line, s.kind) for s in refs.find(files, "my_flag", ["app"], hits)]


CHECKOUT = '''
    def label(client, user):
        # Records the exposure.
        flag = client.get_experiment_flag("my_flag", identifier=user)
        if flag.enabled and flag.value == "buy_now":
            return "Buy now"
        return "Checkout"


    def other():
        return 1
'''


@pytest.mark.parametrize("winner, kept, gone", [
    (BUY, "Buy now", "Checkout"), (CONTROL, "Checkout", "Buy now"),
])
def test_keeps_only_the_winning_path(winner, kept, gone):
    assert rewritten(CHECKOUT, winner) == (
        f'def label(client, user):\n    return "{kept}"\n\n\ndef other():\n    return 1\n')
    assert gone not in rewritten(CHECKOUT, winner)


@pytest.mark.parametrize("winner, expected", [
    (BUY, '    a = 1\n    done(a)\n'), (CONTROL, '    a = 2\n    done(a)\n'),
])
def test_if_else_keeps_the_rest_of_the_function(winner, expected):
    code = '''
        def f(c):
            flag = c.get_experiment_flag("my_flag", identifier="u")
            if flag.value == VARIANT_VALUE:
                a = 1
            else:
                a = 2
            done(a)
    '''
    assert rewritten(code, winner) == "def f(c):\n" + expected


def test_elif_chain_and_nested_if():
    code = '''
        def f(c):
            flag = c.get_flag("my_flag")
            if flag.value == "other":
                x()
            elif flag.enabled:
                if flag.value != "control":
                    y()
            else:
                z()
    '''
    assert rewritten(code) == "def f(c):\n    y()\n"
    assert rewritten(code, CONTROL) == "def f(c):\n    pass\n"


def test_statements_between_the_read_and_the_if_are_kept():
    code = '''
        def f(c):
            flag = c.get_flag("my_flag")
            track()
            if flag.enabled:
                x()
    '''
    assert rewritten(code) == "def f(c):\n    track()\n    x()\n"


def test_direct_condition_on_a_bulk_fetch_with_a_constant_name():
    code = '''
        def f(c, config):
            flags = c.get_identity_flags("u")
            if flags.is_feature_enabled(config.FLAG_NAME):
                track()
            end()
    '''
    assert rewritten(code) == (
        'def f(c, config):\n    flags = c.get_identity_flags("u")\n    track()\n    end()\n')


def test_unrelated_conditions_in_the_kept_branch_survive():
    code = '''
        def f(c, admin):
            flag = c.get_flag("my_flag")
            if flag.enabled:
                if admin:
                    x()
    '''
    assert rewritten(code) == "def f(c, admin):\n    if admin:\n        x()\n"


@pytest.mark.parametrize("code, reason", [
    ('def f(c):\n    return c.get_flag("my_flag").value\n', "not an assignment"),
    ('def f(c):\n    x = c.get_flag("my_flag")\n    return x.value\n', "not used by an `if`"),
    ('def f(c):\n    x = c.get_flag("my_flag")\n    log(x)\n    if x.enabled:\n        go()\n',
     "not used by an `if`"),
    ('def f(c):\n    x = c.get_flag("my_flag")\n    if x.enabled:\n        use(x)\n',
     "still used"),
    ('def f(c, a):\n    x = c.get_flag("my_flag")\n    if x.enabled and a:\n        go()\n',
     "cannot tell the value"),
    ('def f(c, a):\n    x = c.get_flag("my_flag")\n    if a:\n        go()\n',
     "not used by an `if`"),
    ('def f(c):\n    x = c.get_flag("my_flag")\n    if x.enabled: go()\n', "same line"),
    ('def f(c, a):\n    if a:\n        go()\n    elif c.is_feature_enabled("my_flag"):\n'
     '        go()\n', "elif"),
])
def test_refuses_shapes_it_cannot_change_safely(code, reason):
    with pytest.raises(refs.Unsupported, match=reason):
        refs.rewrite(code, "my_flag", BUY, {})


def test_finds_reads_names_text_and_dynamic_reads():
    files = {
        "app/a.py": 'x = c.get_experiment_flag("my_flag", identifier=u)\n'
                    "# my_flag is on\n"
                    'NAME = "my_flag"\n'
                    "y = c.get_flag(name)\n",
        "app/b.js": 'flags.hasFeature("my_flag")\n',
        "app/c.py": 'z = "my_flag-copy my_flag_2"\n',  # longer names are not this flag
        "tool/d.py": 'x = c.get_flag("my_flag")\n',  # outside the application code
    }
    assert sites(files) == [
        ("app/a.py", 1, "read"), ("app/a.py", 2, "text"), ("app/a.py", 3, "name"),
        ("app/a.py", 4, "dynamic"), ("app/b.js", 1, "text"),
    ]

