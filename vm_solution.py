"""t=19 stack VM. Op=1 byte(+i32 LE for PUSH/JMP/JZ/JNZ/CALL, jumps
relative to next op). i64 math, gas, CALL/RET, lossless checkpoints."""
import json,hashlib,struct,sys,time
N='HALT PUSH POP DUP SWAP OVER ADD SUB MUL DIV MOD NEG EQ LT GT JMP JZ JNZ CALL RET YIELD'.split()
OP={n:i for i,n in enumerate(N)};ARG={1,15,16,17,18}
POPS=[*map(int,'001122222221222011000')]
GAS=[*map(int,'111111112331111111321')]
H=1<<63;M=H*2;MAXS=1<<16;MAXF=1024
class VMError(Exception):pass
def E(m):raise VMError(m)
def asm(src):
 ins=[];L={};pc=0
 for ln in src.replace(';','\n').split('\n'):
  t=ln.split('#')[0].split()
  while t and t[0][-1]==':':L[t.pop(0)[:-1]]=pc
  if t:o=OP[t[0].upper()];pc+=1+4*(o in ARG);ins.append((o,t[1:],pc))
 b=bytearray()
 for o,a,nx in ins:
  b.append(o)
  if o in ARG:v=a[0];b+=struct.pack('<i',L[v]-nx if v in L else int(v))
 return bytes(b)
class VM:
 def __init__(s,code,gas=10**6):
  c=bytes(code);s.h=hashlib.sha256(c).hexdigest()[:16];s.n=n=len(c)
  s.ip=p=0;s.st=[];s.fr=[];s.gas=gas;s.steps=0;s.status='READY';D=s.dec={}
  while p<n:
   o=c[p];w=1+4*(o in ARG)
   if o>=len(N)or p+w>n:E('bad op @%d'%p)
   D[p]=[o,w>1 and struct.unpack_from('<i',c,p+1)[0],p+w];p+=w
  for d in D.values():
   if d[0]in ARG and d[0]>1:
    d[1]+=d[2]
    if not s.ok(d[1]):E('bad jump %d'%d[1])
 def ok(s,t):return type(t)is int and(t in s.dec or t==s.n)
 def run(s,steps=-1):
  if s.status in('HALT','FAULT'):return s.status
  D=s.dec;st=s.st;fr=s.fr;ip=s.ip;g=s.gas;n=s.n;k=0;push=st.append;pop=st.pop
  try:
   while k!=steps:
    if ip==n:r='HALT';break
    o,a,nx=D[ip];c=GAS[o];l=len(st)
    if g<c:r='OOG';break
    if l<POPS[o]:E('underflow')
    if l>=MAXS and o in(1,3,5):E('overflow')
    if o==1:push(a)
    elif o==6:b=pop();st[-1]=(st[-1]+b+H)%M-H
    elif o==7:b=pop();st[-1]=(st[-1]-b+H)%M-H
    elif o==16:
     if pop()==0:nx=a
    elif o==17:
     if pop():nx=a
    elif o==15:nx=a
    elif o==3:push(st[-1])
    elif o==18:
     if len(fr)>=MAXF:E('call depth')
     fr.append(nx);nx=a
    elif o==19:
     if not fr:E('no frame')
     nx=fr.pop()
    elif o==8:b=pop();st[-1]=(st[-1]*b+H)%M-H
    elif o in(9,10):
     b=st[-1]
     if b==0:E('div by 0')
     pop();x=st[-1];q=abs(x)//abs(b)*(1-2*((x<0)!=(b<0)));st[-1]=(q+H)%M-H if o==9 else x-b*q
    elif o==2:pop()
    elif o==4:st[-1],st[-2]=st[-2],st[-1]
    elif o==5:push(st[-2])
    elif o==11:st[-1]=(H-st[-1])%M-H
    elif o==12:b=pop();st[-1]=int(st[-1]==b)
    elif o==13:b=pop();st[-1]=int(st[-1]<b)
    elif o==14:b=pop();st[-1]=int(st[-1]>b)
    elif o==20:ip=nx;g-=c;k+=1;r='YIELD';break
    else:g-=c;k+=1;r='HALT';break
    ip=nx;g-=c;k+=1
   else:r='PAUSE'
  except VMError as e:r='FAULT';raise VMError('%s @ip=%d'%(e,ip))from None
  finally:s.ip=ip;s.gas=g;s.steps+=k;s.status=r
  return r
 def checkpoint(s):return json.dumps({'v':1,'h':s.h,'ip':s.ip,'st':s.st,'fr':s.fr,'gas':s.gas,'steps':s.steps,'status':s.status},separators=(',',':')).encode()
 @classmethod
 def restore(cls,code,blob):
  try:
   d=json.loads(blob);v=cls(code,d['gas']);S,F,g,k=d['st'],d['fr'],d['gas'],d['steps'];I=lambda x:type(x)is int
   if not(d['v']==1 and d['h']==v.h and v.ok(d['ip'])and all(I(x)and-H<=x<H for x in S)and all(map(v.ok,F))and I(g)and g>=0 and I(k)and d['status']in'READY PAUSE YIELD OOG HALT FAULT'.split()):E(0)
  except Exception:E('bad checkpoint')
  v.ip,v.st,v.fr,v.steps,v.status=d['ip'],S,F,k,d['status'];return v
FACT=asm('PUSH 12;CALL f;HALT;f: DUP;PUSH 2;LT;JNZ e;DUP;PUSH 1;SUB;CALL f;MUL;e: RET')
LOOP=asm('PUSH 0;PUSH 400000;l: DUP;JZ x;SWAP;OVER;ADD;SWAP;PUSH 1;SUB;JMP l;x: POP;HALT')
if __name__=='__main__':
 v=VM(LOOP,10**8);t=time.perf_counter();v.run();dt=time.perf_counter()-t
 a=VM(FACT);a.run(40);c=a.checkpoint();b=VM.restore(FACT,c);r=b.checkpoint()==c;b.run();f=VM(FACT);f.run()
 print(json.dumps({'py':sys.version.split()[0],'bytes':len(open(__file__,'rb').read()),'loop':v.st,'ops':v.steps,'sec':round(dt,4),'ops_per_sec':round(v.steps/dt),'checkpoint':c.decode(),'roundtrip':r,'fact12':b.st,'resume_eq_full':vars(b)==vars(f)}))
