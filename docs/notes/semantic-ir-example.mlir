builtin.module {
  "pysem.program"() <{globals = ["byte"], entry = "mbentry"}> ({
    "pysem.func"() <{sym_name = "next_byte", parameters = ["value"], locals = ["value"], globals = [], returns = "word"}> ({
    ^bb0(%0: !pysem.word<#builtin.int<20>> loc(unknown)):
      "pysem.store"(%0) <{slot = "value", scope = "local"}> : (!pysem.word<#builtin.int<20>>) -> () loc("<python-subset>":1:1)
      %1 = "pysem.load"() <{slot = "value", scope = "local"}> : () -> !pysem.word<#builtin.int<20>> loc("<python-subset>":2:12)
      %2 = "pysem.const"() <{value = #builtin.int<1>}> : () -> !pysem.word<#builtin.int<20>> loc("<python-subset>":2:20)
      %3 = "pysem.binary"(%1, %2) <{kind = "add"}> : (!pysem.word<#builtin.int<20>>, !pysem.word<#builtin.int<20>>) -> !pysem.word<#builtin.int<20>> loc("<python-subset>":2:12)
      "pysem.return"(%3) : (!pysem.word<#builtin.int<20>>) -> () loc("<python-subset>":2:5)
    }) : () -> () loc("<python-subset>":1:1)
    "pysem.func"() <{sym_name = "mbentry", parameters = [], locals = [], globals = ["byte"], returns = "void"}> ({
      %4 = "pysem.getchar"() : () -> !pysem.word<#builtin.int<20>> loc("<python-subset>":3:8)
      "pysem.store"(%4) <{slot = "byte", scope = "global"}> : (!pysem.word<#builtin.int<20>>) -> () loc("<python-subset>":3:1)
      %5 = "pysem.load"() <{slot = "byte", scope = "global"}> : () -> !pysem.word<#builtin.int<20>> loc("<python-subset>":4:19)
      %6 = "pysem.call"(%5) <{callee = "next_byte"}> : (!pysem.word<#builtin.int<20>>) -> !pysem.word<#builtin.int<20>> loc("<python-subset>":4:9)
      "pysem.putchar"(%6) : (!pysem.word<#builtin.int<20>>) -> () loc("<python-subset>":4:1)
      "pysem.return"() : () -> () loc(unknown)
    }) : () -> () loc(unknown)
  }) : () -> () loc(unknown)
} loc(unknown)
