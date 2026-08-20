import json, io, os, sys
import numpy as np, librosa
base=sys.argv[1]
Q,BPM=705600000,86.0; S=Q*BPM/60.0
MINGAP=0.085; CAP=1.700
src=json.load(io.open(os.path.join(base,'notes_ctc.json'), encoding='ascii'))
pc=np.load(os.path.join(base,'pitchcurve.npz')); tA,pA=pc['tA'],pc['pA']
f0d=np.load(os.path.join(base,'f0_full.npz'))
mF=librosa.hz_to_midi(f0d['f0']); tF=f0d['t']; rdb=librosa.amplitude_to_db(f0d['rms']+1e-10)
sv=json.load(io.open(r'E:\潮声回响\翻唱重制\潮声回响-86BPM.svp', encoding='utf-8-sig'))
CORR=112.32/112.00; LO,HI=52,80
T1=[(n['onset']*CORR/S,(n['onset']+n['duration'])*CORR/S,n['pitch']) for n in sv['library'][0]['notes']]

# 1) 按行摊开起音，保证最小间距
byline={}
for n in src: byline.setdefault(n['line'],[]).append(n)
events=[]
for li in sorted(byline):
    g=sorted(byline[li], key=lambda x:x['onset'])
    t=[x['onset']/S for x in g]
    # 前向推：保证 t[i+1]-t[i] >= MINGAP
    for i in range(1,len(t)):
        if t[i]-t[i-1] < MINGAP: t[i]=t[i-1]+MINGAP
    # 若整体被推得太靠后，整体回移使末字不超过原末字+0.35s
    over=t[-1]-(g[-1]['onset']/S+0.35)
    if over>0:
        shift=min(over, t[0]-(g[0]['onset']/S-0.35))
        if shift>0: t=[x-shift for x in t]
    for x,tt in zip(g,t):
        events.append({'t':tt,'lyrics':x['lyrics'],'line':li})
events.sort(key=lambda x:x['t'])
# 跨行也保证不重叠
for i in range(1,len(events)):
    if events[i]['t']-events[i-1]['t'] < MINGAP:
        events[i]['t']=events[i-1]['t']+MINGAP
print(f'事件 {len(events)} (源 {len(src)}) — 一个字都没丢: {len(events)==len(src)}')

# 2) 音高（同 v3 优先级）
def t5p(a,b):
    best=None
    for x0,x1,xp in T1:
        o=min(b,x1)-max(a,x0)
        if o>0.04 and (best is None or o>best[0]): best=(o,xp)
    return best[1] if best and best[0]>=0.30*(b-a) else None
def cmed(t,p,a,b,frac=0.6,lo=LO,hi=HI):
    c=(a+b)/2; h=(b-a)*frac/2
    m=(t>=c-h)&(t<=c+h)&(p>=lo)&(p<=hi)
    if m.sum()<2: m=(t>=a)&(t<=b)&(p>=lo)&(p<=hi)
    return float(np.median(p[m])) if m.sum()>=2 else None
def fmed(a,b,frac=0.6):
    c=(a+b)/2; h=(b-a)*frac/2
    m=(tF>=c-h)&(tF<=c+h)&(rdb>-38)&~np.isnan(mF)
    if m.sum()<3: return None
    mm=mF[m]; mm=mm[(mm>=LO)&(mm<=HI)]
    return float(np.median(mm)) if len(mm)>=3 else None

out=[]
for i,e in enumerate(events):
    a=e['t']
    b=a+(min(events[i+1]['t']-a, CAP) if i+1<len(events) else 0.60)
    p=t5p(a,b); s='轨5'
    if p is None: p=cmed(tA,pA,a,b); s='曲线A'
    if p is None: p=fmed(a,b); s='pyin'
    out.append({'onset':int(round(a*S)),
                'duration':max(1,int(round((b-a)*S))),
                'pitch':None if p is None else int(round(min(max(p,LO),HI))),
                'lyrics':e['lyrics'],'languageOverride':'mandarin','src':s})
last=None
for x in out:
    if x['pitch'] is not None: last=x['pitch']
    elif last is not None: x['pitch']=last; x['src']='邻近'
out=[x for x in out if x['pitch'] is not None]
ov=[i for i in range(len(out)-1) if out[i]['onset']+out[i]['duration']>out[i+1]['onset']]
ds=np.array([x['duration']/S*1000 for x in out])
from collections import Counter
print(f'音符 {len(out)}   残留重叠 {len(ov)}')
print(f'时长(ms) 中位 {np.median(ds):.0f}  最短 {ds.min():.0f}  最长 {ds.max():.0f}  <80ms {int((ds<80).sum())}')
print('音高来源:', dict(Counter(x['src'] for x in out)))
d=[]
for x in out:
    if x['src']=='轨5':
        a=x['onset']/S; b=a+x['duration']/S
        v=fmed(a,b,0.4)
        if v is not None: d.append(v-x['pitch'])
d=np.array(d,float)
print(f'轨5来源音符 vs 实测f0(非循环): {len(d)} 个  <0.5半音 {np.mean(np.abs(d)<0.5)*100:.1f}%  偏差 {d.mean():+.2f}')
fin=[{k:v for k,v in x.items() if k!='src'} for x in out]
json.dump(fin, io.open(os.path.join(base,'notes_v4.json'),'w',encoding='ascii'), ensure_ascii=True)
json.dump([{'t':round(x['onset']/S,2),'src':x['src']} for x in out],
          io.open(os.path.join(base,'notes_v4_src.json'),'w',encoding='ascii'), ensure_ascii=True)
print(f'已保存 notes_v4.json ({len(fin)} 音符)')
