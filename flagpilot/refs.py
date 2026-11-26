"""Find where application code reads a flag, and rewrite it to one fixed behaviour.

Python files are read with `ast`; `git grep` is the cross-check. The rewriter handles a
read that feeds an `if` it can decide from the winning value. Anything else is reported
as needing a manual edit: it never guesses.
"""

import ast
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from flagpilot import repo

READ_METHODS = ("get_experiment_flag", "get_flag", "get_feature_value", "is_feature_enabled")
BULK_METHODS = ("get_identity_flags", "get_environment_flags")


class Unsupported(RuntimeError):
    """The code is not in a shape the rewriter can change safely."""


@dataclass(frozen=True)
class Site:
    path: str
    line: int
    kind: str  # read, name, text (found by grep only), bulk, dynamic, unparsed
    code: str

    @property
    def is_reference(self) -> bool:
        return self.kind != "bulk"


def mentions(text: str, flag: str) -> bool:
    """True if `text` names the flag itself, not a longer name that contains it."""
    return re.search(rf"(?<![A-Za-z0-9_-]){re.escape(flag)}(?![A-Za-z0-9_-])", text) is not None


def within(path: str, folders: list[str]) -> bool:
    return any(path == f or path.startswith(f.rstrip("/") + "/") for f in folders)


def load(root: Path, ref: str | None = None) -> dict[str, str]:
    """Path -> text for the working tree (tracked and untracked), or for a git ref."""
    if ref:
        names = repo.git(root, "ls-tree", "-r", "-z", "--name-only", ref).split("\0")
        return {n: repo.git(root, "show", f"{ref}:{n}") for n in names if n}
    names = repo.git(root, "ls-files", "-z", "--cached", "--others",
                     "--exclude-standard").split("\0")
    return {n: (root / n).read_text(errors="replace")
            for n in names if n and (root / n).is_file()}


def grep(root: Path, flag: str, paths: list[str] | None = None,
         ref: str | None = None) -> list[tuple[str, int, str]]:
    args = ["grep", "-n", "-z", "-I", "-F", *([] if ref else ["--untracked"]), "-e", flag]
    if ref:
        args.append(ref)
    out = repo.git(root, *args, "--", *(paths or ["."]), ok=(0, 1))  # 1 means no match
    hits = []
    for row in out.split("\n"):
        if not row:
            continue
        path, line, text = row.split("\0", 2)
        if ref:
            path = path.removeprefix(f"{ref}:")
        if mentions(text, flag):
            hits.append((path, int(line), text.strip()))
    return hits


def constants(files: dict[str, str]) -> dict[str, set]:
    """Module-level `NAME = <literal>` assignments in every Python file."""
    found: dict[str, set] = {}
    for path, text in files.items():
        if not path.endswith(".py"):
            continue
        try:
            body = ast.parse(text).body
        except SyntaxError:
            continue
        for node in body:
            if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        found.setdefault(target.id, set()).add(node.value.value)
    return found


def _resolve(node: ast.AST, known: dict[str, set]) -> object:
    """The literal a node stands for. Raises Unsupported if it is not certain."""
    if isinstance(node, ast.Constant):
        return node.value
    name = node.id if isinstance(node, ast.Name) else (
        node.attr if isinstance(node, ast.Attribute) else None)
    values = known.get(name, set())
    if name and name.isupper() and len(values) == 1:
        return next(iter(values))
    raise Unsupported(f"cannot tell the value of `{ast.unparse(node)}`")


def _method(node: ast.AST) -> str | None:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _flag_argument(call: ast.Call) -> ast.AST | None:
    if call.args:
        return call.args[0]
    return next((k.value for k in call.keywords if k.arg == "feature_name"), None)


def _reads(tree: ast.AST, flag: str, known: dict) -> tuple[list[ast.Call], list[ast.Call]]:
    """(reads of this flag, reads whose flag name cannot be determined)."""
    mine, dynamic = [], []
    for node in ast.walk(tree):
        if _method(node) in READ_METHODS and (argument := _flag_argument(node)) is not None:
            try:
                if _resolve(argument, known) == flag:
                    mine.append(node)
            except Unsupported:
                dynamic.append(node)
    return mine, dynamic


def find(files: dict[str, str], flag: str, folders: list[str],
         grep_hits: list[tuple[str, int, str]]) -> list[Site]:
    """Every place under `folders` that reads or names the flag."""
    known = constants(files)
    sites: dict[tuple[str, int], Site] = {}
    for path, text in sorted(files.items()):
        if not within(path, folders) or not path.endswith(".py"):
            continue
        lines = text.split("\n")

        def add(line: int, kind: str) -> None:
            sites.setdefault((path, line), Site(path, line, kind, lines[line - 1].strip()))

        try:
            tree = ast.parse(text)
        except SyntaxError as error:
            add(error.lineno or 1, "unparsed")
            continue
        mine, dynamic = _reads(tree, flag, known)
        for call in mine:
            add(call.lineno, "read")
        for call in dynamic:
            add(call.lineno, "dynamic")
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if mentions(node.value, flag):
                    add(node.lineno, "name")
            elif isinstance(node, (ast.Name, ast.Attribute)) and isinstance(node.ctx, ast.Load):
                try:
                    if _resolve(node, known) == flag:
                        add(node.lineno, "name")
                except Unsupported:
                    pass
        if any(p == path for p, _ in sites):
            for node in ast.walk(tree):
                if _method(node) in BULK_METHODS:
                    add(node.lineno, "bulk")
    for path, line, text in grep_hits:
        if within(path, folders):
            sites.setdefault((path, line), Site(path, line, "text", text))
    return [sites[key] for key in sorted(sites)]


def marked_test_files(files: dict[str, str], flag: str, folders: list[str]) -> list[str]:
    """Test files marked `pytestmark = pytest.mark.flag("<flag>")`: they go with the flag."""
    marked = []
    for path, text in sorted(files.items()):
        if not within(path, folders) or not path.endswith(".py"):
            continue
        try:
            body = ast.parse(text).body
        except SyntaxError:
            continue
        for node in body:
            if (isinstance(node, ast.Assign)
                    and any(getattr(t, "id", None) == "pytestmark" for t in node.targets)
                    and ast.unparse(node.value) == f"pytest.mark.flag({flag!r})"):
                marked.append(path)
    return marked


def tracked_events(files: dict[str, str], folders: list[str]) -> Counter:
    """How many `track_event` calls there are for each event expression."""
    events: Counter = Counter()
    for path, text in files.items():
        if within(path, folders) and path.endswith(".py"):
            for node in ast.walk(ast.parse(text)):
                if _method(node) == "track_event" and node.args:
                    events[ast.unparse(node.args[0])] += 1
    return events


# --- rewriting ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Winner:
    enabled: bool
    value: object


def _decide(node: ast.AST, bound: dict, known: dict) -> object:
    """Evaluate a condition using only the winner and literal constants."""
    if id(node) in bound:
        return bound[id(node)]
    if isinstance(node, ast.Name) and node.id in bound:
        return bound[node.id]
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        winner = bound.get(node.value.id)
        if isinstance(winner, Winner) and node.attr in ("enabled", "value"):
            return getattr(winner, node.attr)
    if isinstance(node, ast.BoolOp):
        result = None
        for operand in node.values:  # same short-circuit order as Python
            result = _decide(operand, bound, known)
            if bool(result) != isinstance(node.op, ast.And):
                break
        return result
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not _decide(node.operand, bound, known)
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return [_decide(item, bound, known) for item in node.elts]
    if isinstance(node, ast.Compare) and len(node.ops) == 1:
        left = _decide(node.left, bound, known)
        right = _decide(node.comparators[0], bound, known)
        operators = {
            ast.Eq: lambda: left == right, ast.NotEq: lambda: left != right,
            ast.Is: lambda: left is right, ast.IsNot: lambda: left is not right,
            ast.In: lambda: left in right, ast.NotIn: lambda: left not in right,
        }
        if type(node.ops[0]) in operators:
            return operators[type(node.ops[0])]()
    return _resolve(node, known)


def _blocks(tree: ast.AST):
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            block = getattr(node, field, None)
            if isinstance(block, list) and block and isinstance(block[0], ast.stmt):
                yield node, block


def _contains(node: ast.AST, target: ast.AST) -> bool:
    return any(child is target for child in ast.walk(node))


def _rewrite_one(source: str, tree: ast.Module, call: ast.Call, winner: Winner,
                 known: dict) -> str:
    method = _method(call)
    value = {"is_feature_enabled": winner.enabled,
             "get_feature_value": winner.value}.get(method, winner)
    for owner, block in _blocks(tree):
        for index, statement in enumerate(block):
            if (isinstance(statement, ast.Assign) and statement.value is call
                    and len(statement.targets) == 1
                    and isinstance(statement.targets[0], ast.Name)):
                variable = statement.targets[0].id
                for later in range(index + 1, len(block)):
                    if any(isinstance(n, ast.Name) and n.id == variable
                           for n in ast.walk(block[later])):
                        if isinstance(block[later], ast.If):  # its first use must be an `if`
                            return _splice(source, tree, block, index, later,
                                           {variable: value}, known, variable)
                        break
                raise Unsupported(f"`{variable}` is not used by an `if` after the read")
            if isinstance(statement, ast.If) and _contains(statement.test, call):
                return _splice(source, tree, block, index, index, {id(call): value}, known, None)
    raise Unsupported("the read is not an assignment followed by `if`, or an `if` condition")


def _splice(source: str, tree: ast.Module, block: list, first: int, branch_at: int,
            bound: dict, known: dict, variable: str | None) -> str:
    """Drop the read at block[first] and keep the winner's branch of the `if` at branch_at.

    Statements between the two are kept as they are.
    """
    lines = source.split("\n")
    head = block[first]
    condition = block[branch_at]
    if lines[condition.lineno - 1].lstrip().startswith("elif"):
        raise Unsupported("the flag is read in an `elif` condition")
    kept: list[ast.stmt] = [condition]
    while len(kept) == 1 and isinstance(kept[0], ast.If):
        depends = any(id(n) in bound or getattr(n, "id", None) in bound
                      for n in ast.walk(kept[0].test))
        if not depends:
            break  # an unrelated condition inside the kept branch stays as written
        try:
            taken = _decide(kept[0].test, bound, known)
        except Unsupported:
            if kept[0] is condition:
                raise
            break  # a later `elif` that does not depend on the flag
        branch = kept[0].body if taken else kept[0].orelse
        if branch and branch[0].lineno == kept[0].lineno:
            raise Unsupported("the `if` body is on the same line as its condition")
        kept = branch
    if kept and lines[kept[0].lineno - 1].lstrip().startswith("elif"):
        raise Unsupported("an `elif` that does not depend on the flag follows the flag check")

    terminates = bool(kept) and isinstance(kept[-1], (ast.Return, ast.Raise))
    last = block[-1] if terminates else condition  # anything after is unreachable
    start = head.lineno - 1
    indent = head.col_offset
    while start > 0 and lines[start - 1].startswith(" " * indent + "#"):
        start -= 1  # comments that describe the removed read

    replacement: list[str] = []
    if kept:
        for node in kept:
            for child in ast.walk(node):
                if (isinstance(child, ast.Constant) and isinstance(child.value, str)
                        and child.end_lineno != child.lineno):
                    raise Unsupported("the kept branch has a multi-line string")
        body_indent = kept[0].col_offset
        body_start = kept[0].lineno - 1
        while lines[body_start - 1].startswith(" " * body_indent + "#"):
            body_start -= 1
        for line in lines[body_start:kept[-1].end_lineno]:
            extra = " " * (body_indent - indent)
            replacement.append(line.removeprefix(extra) if line.strip() else "")
    elif first == 0 and branch_at - first <= 1 and block[-1] is last:  # block left empty
        replacement = [" " * indent + "pass"]

    between = [] if branch_at == first else lines[head.end_lineno:condition.lineno - 1]
    result = "\n".join(lines[:start] + between + replacement + lines[last.end_lineno:])
    new_tree = ast.parse(result)  # raises if the edit produced invalid code
    if variable:
        enclosing = _enclosing_name(tree, head)
        for node in ast.walk(new_tree):
            if enclosing is not None and getattr(node, "name", None) != enclosing:
                continue
            if any(isinstance(n, ast.Name) and n.id == variable for n in ast.walk(node)):
                raise Unsupported(f"`{variable}` is still used after removing the read")
    return result


def _enclosing_name(tree: ast.Module, statement: ast.stmt) -> str | None:
    """Name of the innermost function around `statement`, or None at module level."""
    functions = [n for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and _contains(n, statement)]
    return min(functions, key=lambda f: f.end_lineno - f.lineno).name if functions else None


def rewrite(source: str, flag: str, winner: Winner, known: dict[str, set]) -> str:
    """The source with every read of `flag` replaced by the winning behaviour."""
    for _ in range(50):
        tree = ast.parse(source)
        mine, _dynamic = _reads(tree, flag, known)
        if not mine:
            return source
        first = min(mine, key=lambda c: (c.lineno, c.col_offset))
        source = _rewrite_one(source, tree, first, winner, known)
    raise Unsupported("too many reads in one file")
