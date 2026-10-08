"""Shared AST conveniences must preserve evaluation order and source errors."""
import ast
import contextlib
import io
import itertools
import unittest

from malbolge.compiler.python_normalize import (
    bind_call_arguments, io_reachable_functions, may_fail_expression,
    normalize_tree,
)


class LocatedError(ValueError):
    def __init__(self, message, node):
        super().__init__(message)
        self.lineno = getattr(node, 'lineno', None)


def normalized(source):
    return normalize_tree(ast.parse(source), error=LocatedError)


def execute(tree):
    output = io.StringIO()
    namespace = {}
    with contextlib.redirect_stdout(output):
        exec(compile(tree, '<normalization-test>', 'exec'), namespace)
    return output.getvalue()


class TestTupleNormalization(unittest.TestCase):
    def assert_same_output(self, source):
        self.assertEqual(execute(normalized(source)), execute(ast.parse(source)))

    def test_rhs_values_are_captured_before_any_target_changes(self):
        self.assert_same_output('''
a = 1
b = 2
a, b = b, a
print(a, b)
a, b = a + b, a
print(a, b)
''')

    def test_chained_tuple_targets_evaluate_rhs_once_in_order(self):
        self.assert_same_output('''
def mark(value):
    print("mark", value)
    return value
(a, b) = (c, d) = (mark(7), mark(9))
print(a, b, c, d)
''')

    def test_no_hoisting_out_of_branch_or_loop(self):
        self.assert_same_output('''
def mark(value):
    print("mark", value)
    return value
if 0:
    a, b = mark(1), mark(2)
for i in range(2):
    if i:
        a, b = mark(3), mark(4)
        print(a, b)
''')

    def test_generated_names_avoid_case_insensitive_collisions(self):
        self.assert_same_output('''
pymqv0 = 11
PymQV1 = 12
a, b = 1, 2
print(pymqv0, PymQV1, a, b)
''')

    def test_rejects_nonfixed_or_nested_tuple_shapes_at_original_line(self):
        for statement in ('a, b = values', 'a, (b, c) = 1, 2',
                          'a, b = 1, 2, 3', 'a, b = 1, *values',
                          'a, b = 1, (2, 3)'):
            with self.subTest(statement=statement):
                with self.assertRaises(LocatedError) as caught:
                    normalized('\n' + statement)
                self.assertEqual(caught.exception.lineno, 2)


class TestFStringNormalization(unittest.TestCase):
    def test_mixed_print_arguments_keep_side_effects_and_static_separator(self):
        source = '''
def mark(value):
    print("mark", value)
    return value
print(f"left:{mark(1)}:{mark(2)}", mark(3), f"right:{mark(4)}", sep="|", end="!")
'''
        self.assertEqual(execute(normalized(source)), execute(ast.parse(source)))

    def test_empty_and_adjacent_fstrings(self):
        for source in ('print(f"", 3, sep="/")',
                       'n = 4\nprint(f"{n}{n + 1}", f"static", sep="")',
                       'n = 4\nif 0:\n    print(f"{n}")\nprint("done")'):
            with self.subTest(source=source):
                self.assertEqual(execute(normalized(source)), execute(ast.parse(source)))

    def test_does_not_hoist_expression_from_short_circuit_context(self):
        source = '''
def mark():
    print("unreachable")
    return 1
if 0:
    print(f"{mark()}")
print("done")
'''
        self.assertEqual(execute(normalized(source)), 'done\n')

    def test_conversion_and_format_specifiers_are_source_errors(self):
        for source in ('n=1\nprint(f"{n!r}")',
                       'n=1\nprint(f"{n:03d}")',
                       'n=1\nprint(f"{n}", sep=n)'):
            with self.subTest(source=source):
                with self.assertRaises(LocatedError) as caught:
                    normalized(source)
                self.assertEqual(caught.exception.lineno, 2)


class TestKeywordBinding(unittest.TestCase):
    def test_all_keyword_permutations_preserve_source_order_and_destination(self):
        for order in itertools.permutations(('a', 'b', 'c')):
            with self.subTest(order=order):
                call = ast.parse('f(' + ', '.join(f'{name}=mark({index})'
                                 for index, name in enumerate(order)) + ')').body[0].value
                before = ast.dump(call)
                nodes, indices = bind_call_arguments(call, ['a', 'b', 'c'], error=LocatedError)
                self.assertEqual([node.args[0].value for node in nodes], [0, 1, 2])
                self.assertEqual(indices, [['a', 'b', 'c'].index(name) for name in order])
                self.assertEqual(ast.dump(call), before)

    def test_keyword_binding_plan_matches_cpython_execution(self):
        prefix = ('def mark(value):\n    print("mark", value)\n    return value\n'
                  'def f(a, b, c):\n    return a * 100 + b * 10 + c\n')
        for order in itertools.permutations(('a', 'b', 'c')):
            with self.subTest(order=order):
                expression = 'f(' + ', '.join(f'{name}=mark({index + 1})'
                                             for index, name in enumerate(order)) + ')'
                expected = execute(ast.parse(prefix + 'print(' + expression + ')'))
                call = ast.parse(expression).body[0].value
                nodes, indices = bind_call_arguments(call, ['a', 'b', 'c'], error=LocatedError)
                namespace = {}
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    exec(prefix, namespace)
                    bound = [None, None, None]
                    for node, destination in zip(nodes, indices):
                        bound[destination] = eval(compile(ast.Expression(node), '<argument>', 'eval'), namespace)
                    print(namespace['f'](*bound))
                self.assertEqual(output.getvalue(), expected)

    def test_mixed_positional_keyword_binding_does_not_rewrite_lazy_context(self):
        tree = ast.parse('if 0:\n    f(mark(1), c=mark(2), b=mark(3))')
        call = tree.body[0].body[0].value
        before = ast.dump(tree)
        nodes, indices = bind_call_arguments(call, ['a', 'b', 'c'], error=LocatedError)
        self.assertEqual(indices, [0, 2, 1])
        self.assertEqual([node.args[0].value for node in nodes], [1, 2, 3])
        self.assertEqual(ast.dump(tree), before)

    def test_invalid_binding_forms_have_source_located_errors(self):
        for expression in ('f(1, 2, 3)', 'f(1, a=2)', 'f(a=1, a=2)',
                           'f(c=1)', 'f(a=1)', 'f(*values)', 'f(**values)'):
            with self.subTest(expression=expression):
                call = ast.parse('\n' + expression).body[0].value
                with self.assertRaises(LocatedError) as caught:
                    bind_call_arguments(call, ['a', 'b'], error=LocatedError)
                self.assertEqual(caught.exception.lineno, 2)


class TestRuntimeErrorReachability(unittest.TestCase):
    def test_transitive_and_recursive_call_graph(self):
        tree = ast.parse('''
def read():
    return int(input())
def wrapper():
    return read()
def recurse(n):
    if n:
        return recurse(n - 1)
    return wrapper()
def divide(n, d):
    return n // d
def modulo(n, d):
    n %= d
    return n
def safe(n):
    return n // 10
''')
        self.assertEqual(io_reachable_functions(tree),
                         {'read', 'wrapper', 'recurse', 'divide', 'modulo'})

    def test_ring_zero_divisors_are_not_misclassified_as_safe_constants(self):
        for expression in ('n // 0', 'n % d', 'n // 3486784401'):
            with self.subTest(expression=expression):
                self.assertTrue(may_fail_expression(ast.parse(expression)))
        self.assertFalse(may_fail_expression(ast.parse('n // 10')))


class TestPossibleNoneAnalysis(unittest.TestCase):
    def test_void_discard_is_allowed_but_scalar_contexts_are_rejected(self):
        prefix = 'def maybe(n):\n    if n:\n        return 1\n'
        normalized(prefix + 'maybe(0)\n')
        for use in ('x = maybe(0)', 'print(maybe(0))',
                    'if maybe(0):\n    pass',
                    'def wrapper():\n    return maybe(0)'):
            with self.subTest(use=use):
                with self.assertRaisesRegex(LocatedError, 'may return None'):
                    normalized(prefix + use)

    def test_total_return_paths_are_accepted(self):
        for function in ('''def f(n):
    if n:
        return 1
    else:
        return 2
''', '''def f(n):
    for i in range(1):
        return 1
''', '''def f(n):
    while 1:
        return 1
''', '''def f(n):
    for i in range(0):
        return None
    return 1
'''):
            with self.subTest(function=function):
                normalized(function + 'x = f(0)\n')

    def test_unreachable_loop_bodies_do_not_add_none_exit_paths(self):
        for test in ('0', '3486784401'):
            with self.subTest(test=test):
                normalized('def f():\n    while ' + test + ':\n        return None\n    return 1\nx=f()\n')

    def test_negative_ascending_stop_is_empty_for_none_analysis(self):
        with self.assertRaisesRegex(LocatedError, 'may return None'):
            normalized('def f():\n    for i in range(-1):\n        return 1\nx=f()\n')

    def test_literal_truth_is_normalized_to_the_unsigned_word_ring(self):
        normalized('''def f():
    if 3486784401:
        return None
    return 1
x = f()
''')
        with self.assertRaisesRegex(LocatedError, 'may return None'):
            normalized('''def f():
    if 3486784401:
        return 1
x = f()
''')
        normalized('''def f():
    if 3486784402:
        return 1
x = f()
''')

    def test_break_and_continue_do_not_prove_a_value_return(self):
        for body in ('while 1:\n        break',
                     'for i in range(1):\n        continue'):
            with self.subTest(body=body):
                with self.assertRaisesRegex(LocatedError, 'may return None'):
                    normalized('def f():\n    ' + body + '\nx = f()\n')
