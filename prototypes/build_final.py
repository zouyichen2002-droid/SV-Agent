import json, io, os, sys
import numpy as np, librosa
base=sys.argv[1]
Q,BPM=705600000,86.0; SEC2BLK=Q*BPM/60.0
LO,HI=52,80; MIND,MAXD=0.090,1.700
res=json.load(io.open(os.path.join(base,'ctc_spans.json'), encoding='ascii'))
pc=np.load(os.path.join(base,'pitchcurve.npz')); tA,pA,tB,pB=pc['tA'],pc['pA'],pc['tB'],pc['pB']
f0d=np.load(os.path.join(base,'f0_full.npz'))
mF=librosa.hz_to_midi(f0d['f0']); tF=f0d['t']; rdb=librosa.amplitude_to_db(f0d['rms']+1e-10)
sv=json.load(io.open(r'E:\潮声回响\翻唱重制\潮声回响-86BPM.svp', encoding='utf-8-sig'))
CORR=112.32/112.00
T1=[(n['onset']*CORR/SEC2BLK,(n['onset']+n['duration'])*CORR/SEC2BLK,n['pitch'])
    for n in sv['library'][0]['notes']]

# 1) 每行：取尖峰起音，缺字插值
events=[]   # (onset_sec, char, line)
for r in res:
    if not r.get('ok'): continue
    n=r['nchar']; sp={int(k):v for k,v in r['spans'].items()}
    known=sorted(sp)
    if not known: continue
    ons={k: sp[k][0] for k in known}
    # 缺失的按已知邻居线性插值
    for k in range(n):
        if k in ons: continue
        lo=[x for x in known if x<k]; hi=[x for x in known if x>k]
        if lo and hi:
            a,b=lo[-1],hi[0]
            ons[k]=ons[a]+(ons[b]-ons[a])*(k-a)/(b-a)
        elif hi:  ons[k]=ons[hi[0]]-0.18*(hi[0]-k)
        elif lo:  ons[k]=ons[lo[-1]]+0.18*(k-lo[-1])
    for k in range(n):
        events.append((ons[k], r['chars'][k], r['line']))
events.sort(key=lambda x:x[0])
print(f'事件总数 {len(events)} (目标 315)')

# 2) 时长 = 到下一个起音；跨行大间隙时封顶
notes=[]
for i,(t0,ch,li) in enumerate(events):
    if i+1<len(events):
        gap=events[i+1][0]-t0
    else:
        gap=0.6
    d=min(max(gap*0.96, MIND), MAXD)
    notes.append({'t0':t0,'t1':t0+d,'ch':ch,'line':li})

def cmed(t,p,a,b,frac=0.6):
    c=(a+b)/2; h=(b-a)*frac/2
    m=(t>=c-h)&(t<=c+h)&(p>=LO)&(p<=HI)
    if m.sum()<2: m=(t>=a)&(t<=b)&(p>=LO)&(p<=HI)
    return float(np.median(p[m])) if m.sum() else None

out=[]
for n in notes:
    va=cmed(tA,pA,n['t0'],n['t1']); vb=cmed(tB,pB,n['t0'],n['t1'])
    if va is not None and vb is not None and abs(va-vb)<=1.5: v=(va+vb)/2
    else: v=va if va is not None else vb
    if v is None:
        va=cmed(tA,pA,n['t0']-0.25,n['t1']+0.25); vb=cmed(tB,pB,n['t0']-0.25,n['t1']+0.25)
        v=va if va is not None else vb
    if v is None: continue
    out.append({'onset':int(round(n['t0']*SEC2BLK)),
                'duration':max(1,int(round((n['t1']-n['t0'])*SEC2BLK))),
                'pitch':int(round(v)),'lyrics':n['ch'],
                'languageOverride':'mandarin','line':n['line']})
out.sort(key=lambda x:x['onset'])
for i in range(len(out)-1):
    e=out[i]['onset']+out[i]['duration']
    if e>out[i+1]['onset']:
        out[i]['duration']=max(int(MIND*SEC2BLK), out[i+1]['onset']-out[i]['onset'])

def val(lst,tag):
    d1=[]
    for n in lst:
        a=n['onset']/SEC2BLK; b=a+n['duration']/SEC2BLK
        best=None
        for x0,x1,xp in T1:
            o=min(b,x1)-max(a,x0)
            if o>0.05 and (best is None or o>best[0]): best=(o,xp)
        if best: d1.append(n['pitch']-best[1])
    d2=[]
    for n in lst:
        a=n['onset']/SEC2BLK; b=a+n['duration']/SEC2BLK
        m=(tF>=a)&(tF<=b)&(rdb>-38)&~np.isnan(mF)
        if m.sum()>=3:
            mm=mF[m]; mm=mm[(mm>=LO)&(mm<=HI)]
            if len(mm)>=3: d2.append(float(np.median(mm))-n['pitch'])
    d1=np.array(d1,float); d2=np.array(d2,float)
    print(f'  {tag}')
    print(f'    vs 轨5  ({len(d1):>3}个) <0.5半音 {np.mean(np.abs(d1)<0.5)*100:5.1f}%  >3半音 {np.mean(np.abs(d1)>3)*100:5.1f}%  平均 {d1.mean():+.2f}')
    print(f'    vs 实测f0({len(d2):>3}个) <0.5半音 {np.mean(np.abs(d2)<0.5)*100:5.1f}%  >3半音 {np.mean(np.abs(d2)>3)*100:5.1f}%  平均 {d2.mean():+.2f}')
    return np.mean(np.abs(d2)<0.5)*100

print('\n基线: 轨5(174音符) vs 实测f0 = 67.6%')
s=val(out,'CTC 对齐版')
ds=np.array([n['duration']/SEC2BLK for n in out]); ps=[n['pitch'] for n in out]
print(f'\n音符 {len(out)}  音高 MIDI {min(ps)}~{max(ps)}  时长 中位 {np.median(ds)*1000:.0f}ms 最短 {ds.min()*1000:.0f}ms 最长 {ds.max()*1000:.0f}ms')
print(f'时间 {out[0]["onset"]/SEC2BLK:.2f}s -> {(out[-1]["onset"]+out[-1]["duration"])/SEC2BLK:.2f}s')
json.dump(out, io.open(os.path.join(base,'notes_ctc.json'),'w',encoding='ascii'), ensure_ascii=True)
print('已保存 notes_ctc.json')
