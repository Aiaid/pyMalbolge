"""Cycle-accurate simulator of the .mg ROT/OPR register machine (Malbolge20, 20 trits)."""
W=20; M=3**W; RM=3**(W-1)
T=[[1,0,0],[1,0,2],[2,2,1]]  # T[d][a]
def rotr(n): return RM*(n%3)+n//3
def crazy(a,d):
    r=0;p=1
    for _ in range(W):
        r+=T[(d//p)%3][(a//p)%3]*p; p*=3
    return r
CON={'CON0':0,'CON1':1743392200,'CON2':3486784400}
class Sim:
    def __init__(s,**vars):
        s.A=0; s.mem=dict(CON); s.mem.update(vars); s.out=[]
    def rot(s,x): v=rotr(s.mem[x]); s.mem[x]=v; s.A=v; return s
    def opr(s,x): v=crazy(s.A,s.mem[x]); s.mem[x]=v; s.A=v; return s
    def run(s,prog):
        for op,x in prog:
            getattr(s,op)(x)
        return s
    def out_byte(s): s.out.append(s.A%256); return s
def trits(n): 
    t=[];
    for _ in range(W): t.append(n%3); n//=3
    return t
