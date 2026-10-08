"""Shared, source-located lowering for inexpensive Python conveniences.

No expression with side effects is hoisted out of its control-flow context.
Keyword argument binding therefore returns an evaluation order/permutation
for each backend rather than rewriting calls into eager prelude statements.
"""

import ast


_TARGET_FUNCTION_KEYWORDS = frozenset(
    "DEF VAR FLAG OPR ROT SET RESET END IF ELSE REPEAT BREAK SWITCH CASE0 "
    "CASE1 CASE2 OUTPUT TRUE FALSE INF GOTO IND_OPR CALL RETURN PROTO FLIP "
    "CON0 CON1 CON2 BASE RETURN_ADDR".split())


def bind_call_arguments(call, parameters, *, error):
    """Return (expressions in source order, destination parameter indices)."""
    parameters = list(parameters)
    if any(isinstance(arg, ast.Starred) for arg in call.args):
        raise error("starred call arguments are unsupported", call)
    if len(call.args) > len(parameters):
        raise error("too many positional arguments", call)
    nodes = list(call.args)
    indices = list(range(len(nodes)))
    assigned = set(indices)
    for kw in call.keywords:
        if kw.arg is None:
            raise error("keyword argument unpacking is unsupported", kw.value)
        if kw.arg not in parameters:
            raise error("unexpected keyword argument {!r}".format(kw.arg), kw.value)
        index = parameters.index(kw.arg)
        if index in assigned:
            raise error("multiple values for argument {!r}".format(kw.arg), kw.value)
        nodes.append(kw.value)
        indices.append(index)
        assigned.add(index)
    if len(assigned) != len(parameters):
        missing = [name for i, name in enumerate(parameters) if i not in assigned]
        raise error("missing argument(s): {}".format(", ".join(missing)), call)
    return nodes, indices


def _is_reader(node):
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "int" and len(node.args) == 1
            and isinstance(node.args[0], ast.Call)
            and isinstance(node.args[0].func, ast.Name)
            and node.args[0].func.id == "input")


def may_fail_expression(node):
    """Conservative runtime-error reachability, with nonzero constants cheap."""
    for part in ast.walk(node):
        if _is_reader(part):
            return True
        if isinstance(part, (ast.BinOp, ast.AugAssign)) and isinstance(
                part.op, (ast.FloorDiv, ast.Mod)):
            divisor = part.right if isinstance(part, ast.BinOp) else part.value
            if not (isinstance(divisor, ast.Constant)
                    and isinstance(divisor.value, int)
                    and divisor.value % (3 ** 20) != 0):
                return True
    return False


def io_reachable_functions(tree):
    """Functions that can propagate an input/arithmetic error, transitively."""
    definitions = {node.name: node for node in tree.body
                   if isinstance(node, ast.FunctionDef)}
    reached = {name for name, node in definitions.items()
               if may_fail_expression(node)}
    calls = {name: {part.func.id for part in ast.walk(node)
                    if isinstance(part, ast.Call) and isinstance(part.func, ast.Name)}
             for name, node in definitions.items()}
    changed = True
    while changed:
        changed = False
        for name, callees in calls.items():
            if name not in reached and callees & reached:
                reached.add(name)
                changed = True
    return reached


def _truth(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, bool)):
        return bool(node.value % (3 ** 20))
    return None


def _exits(body):
    """Return reachable value/None/fallthrough/loop-control outcomes."""
    outcomes = {"fallthrough"}
    for stmt in body:
        if "fallthrough" not in outcomes:
            break
        outcomes.remove("fallthrough")
        if isinstance(stmt, ast.Return):
            is_none = stmt.value is None or (
                isinstance(stmt.value, ast.Constant) and stmt.value.value is None)
            exits = {"none" if is_none else "value"}
        elif isinstance(stmt, ast.If):
            known = _truth(stmt.test)
            if known is not None:
                exits = _exits(stmt.body if known else stmt.orelse)
            else:
                exits = _exits(stmt.body) | _exits(stmt.orelse)
        elif isinstance(stmt, ast.While):
            inner = _exits(stmt.body)
            known = _truth(stmt.test)
            if known is False:
                exits = _exits(stmt.orelse)
            else:
                exits = inner & {"value", "none"}
                if known is not True or "break" in inner:
                    exits.add("fallthrough")
        elif isinstance(stmt, ast.For):
            inner = _exits(stmt.body)
            nonempty = None
            if (isinstance(stmt.iter, ast.Call)
                    and isinstance(stmt.iter.func, ast.Name)
                    and stmt.iter.func.id == "range"):
                try:
                    args = [ast.literal_eval(arg) for arg in stmt.iter.args]
                    if all(isinstance(value, int) for value in args):
                        step = args[2] if len(args) > 2 else 1
                        if len(args) == 1:
                            args[0] = args[0] % (3 ** 20) if args[0] >= 0 else 0
                        elif len(args) > 1:
                            if args[0] < 0:
                                raise ValueError("negative range start")
                            args[0] %= 3 ** 20
                            if args[1] >= 0:
                                args[1] %= 3 ** 20
                            elif step > 0:
                                args[1] = 0
                            elif args[1] != -1:
                                raise ValueError("unsupported negative stop")
                        iterator = range(*args)
                        nonempty = (iterator.start < iterator.stop if iterator.step > 0
                                    else iterator.start > iterator.stop)
                except (ValueError, TypeError):
                    pass
            if nonempty is False:
                exits = _exits(stmt.orelse)
            else:
                exits = inner & {"value", "none"}
                if nonempty is None or inner & {"fallthrough", "break", "continue"}:
                    exits.add("fallthrough")
        elif isinstance(stmt, ast.Break):
            exits = {"break"}
        elif isinstance(stmt, ast.Continue):
            exits = {"continue"}
        else:
            exits = {"fallthrough"}
        outcomes.update(exits)
    return outcomes


class _Normalize(ast.NodeTransformer):
    def __init__(self, tree, error):
        self.error = error
        self.used = {node.id.lower() for node in ast.walk(tree)
                     if isinstance(node, ast.Name)}
        self.used.update(node.name.lower() for node in ast.walk(tree)
                         if isinstance(node, ast.FunctionDef))
        self.used.update(node.arg.lower() for node in ast.walk(tree)
                         if isinstance(node, ast.arg))
        self.counter = 0

    def fresh(self):
        while True:
            name = "pymqv{}".format(self.counter)
            self.counter += 1
            if name.lower() not in self.used:
                self.used.add(name.lower())
                return name

    def visit_Assign(self, node):
        node = self.generic_visit(node)
        if not any(isinstance(target, ast.Tuple) for target in node.targets):
            return node
        if not isinstance(node.value, ast.Tuple) or not all(
                isinstance(target, ast.Tuple) for target in node.targets):
            raise self.error("tuple assignment requires fixed-arity tuple values", node)
        values = node.value.elts
        if any(isinstance(value, (ast.Starred, ast.Tuple, ast.List)) for value in values):
            raise self.error("tuple assignment requires flat values without unpacking", node.value)
        for target in node.targets:
            if len(target.elts) != len(values) or not all(
                    isinstance(item, ast.Name) for item in target.elts):
                raise self.error("tuple assignment requires matching flat name targets", target)
        names = [self.fresh() for _ in values]
        statements = []
        for name, value in zip(names, values):
            statements.append(ast.copy_location(ast.Assign(
                targets=[ast.Name(id=name, ctx=ast.Store())], value=value), value))
        for target in node.targets:
            for item, name in zip(target.elts, names):
                statements.append(ast.copy_location(ast.Assign(
                    targets=[item], value=ast.Name(id=name, ctx=ast.Load())), node))
        return statements

    def visit_Call(self, node):
        node = self.generic_visit(node)
        if not (isinstance(node.func, ast.Name) and node.func.id == "print"
                and any(isinstance(arg, ast.JoinedStr) for arg in node.args)):
            return node
        sep = " "
        for kw in node.keywords:
            if kw.arg == "sep":
                if not (isinstance(kw.value, ast.Constant)
                        and isinstance(kw.value.value, str)):
                    raise self.error("print() sep= must be a constant string literal", kw.value)
                sep = kw.value.value
        pieces = []
        for i, arg in enumerate(node.args):
            if i:
                pieces.append(ast.copy_location(ast.Constant(value=sep), arg))
            if not isinstance(arg, ast.JoinedStr):
                pieces.append(arg)
                continue
            for part in arg.values:
                if isinstance(part, ast.Constant):
                    pieces.append(part)
                elif isinstance(part, ast.FormattedValue):
                    if part.conversion != -1:
                        raise self.error("f-string conversion specifiers are unsupported", part)
                    if part.format_spec is not None:
                        raise self.error("f-string format specifiers are unsupported", part)
                    pieces.append(part.value)
        node.args = pieces
        node.keywords = [kw for kw in node.keywords if kw.arg != "sep"]
        node.keywords.append(ast.keyword(arg="sep", value=ast.Constant(value="")))
        return node


def normalize_tree(tree, *, error):
    """Normalize safe conveniences and reject scalar use of possible None."""
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name.upper() in _TARGET_FUNCTION_KEYWORDS:
            raise error("function name {!r} is reserved by the target language".format(
                node.name), node)
    tree = _Normalize(tree, error).visit(tree)
    ast.fix_missing_locations(tree)
    maybe_none = {node.name for node in tree.body
                  if isinstance(node, ast.FunctionDef)
                  and _exits(node.body) & {"none", "fallthrough"}}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            if (isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
                    and child.func.id in maybe_none
                    and not (isinstance(parent, ast.Expr) and parent.value is child)):
                raise error("function {!r} may return None; its result cannot be used "
                            "as an integer".format(child.func.id), child)
    return tree
