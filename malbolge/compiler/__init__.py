"""
malbolge.compiler -- a Python-subset front-end for the Malbolge20 pipeline.

`compile_python_to_c` translates a restricted subset of Python into the
"Nagoya high-level C" subset accepted by ``ref/nagoya-highlevel/parser``,
which is the first stage of the Python -> C -> .mg -> .mc -> .mb toolchain.

    from malbolge.compiler import compile_python_to_c
    c_source = compile_python_to_c("putchar(72)\\nputchar(105)\\n")
"""

from .py2c import compile_python_to_c, CompileError

__all__ = ["compile_python_to_c", "CompileError"]
