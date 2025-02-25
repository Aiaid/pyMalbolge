import unittest

from malbolge import eval

class TestEval(unittest.TestCase):
    def test_hello(self):
        self.assertEqual(eval('''(=<`#9]~6ZY32Vx/4Rs+0No-&Jk)"Fh}|Bcy?`=*z]Kw%oG4UUS0/@-ejc(:'8dc'''), "Hello World!")

    def test_cat(self):
        self.assertEqual(eval('''(=BA#9"=<;:3y7x54-21q/p-,+*)"!h%B0/.~P<<:(8&66#"!~}|{zyxwvugJ%''',"abc123"), "abc123")

    
if __name__ == "__main__":
    unittest.main()