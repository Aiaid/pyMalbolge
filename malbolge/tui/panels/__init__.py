"""
Debugger TUI panels.

Deliberately empty of imports: ``malbolge.tui`` pulls ``HAS_TEXTUAL`` out of
``.panels.base`` before it knows whether textual exists, so importing this
package must not drag in any textual-dependent module.
"""
