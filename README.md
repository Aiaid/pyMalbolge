# pyMalbolge

This is fork from https://github.com/Avantgarde95/pyMalbolge

Simple Malbolge(https://en.wikipedia.org/wiki/Malbolge) interpreter in python

## Howto
Install

`pip install malbolge`

Command Line Tool

`python3 -m malbolge hello.mb`

Eval

```
from malbolge import eval

eval('''(=<`#9]~6ZY32Vx/4Rs+0No-&Jk)"Fh}|Bcy?`=*z]Kw%oG4UUS0/@-ejc(:'8dc''')
# Hello World!
eval('''(=BA#9"=<;:3y7x54-21q/p-,+*)"!h%B0/.~P<<:(8&66#"!~}|{zyxwvugJ%''',"abc123")
# abc123
```


## Fix:
Integer division syntax

## Add:
Eval function for inline evaluation


## TODO:
- Support Malbolge20 and Malbolge Unshackled
- Add debug mode
- A simple Malbolge compiler/generator(not sure if possible)
