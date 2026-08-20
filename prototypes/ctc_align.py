import json, io, os, sys, re, time
import numpy as np
import torch, librosa
from transformers import Wav2Vec2ForCTC, Wav2Vec2FeatureExtractor

BASE  = sys.argv[1]
LIMIT = int(sys.argv[2]) if len(sys.argv) > 2 else 0     # 0 = 全部
MDL   = os.path.join(BASE, 'models', 'zh-ctc')
WAV   = r'E:\潮声回响\人声分离\htdemucs\来自塞壬的歌谣，听『潮声回响』【洛天依海洋之心原创曲】\vocals.wav'
SR    = 16000

torch.set_num_threads(16)
vocab = json.load(io.open(os.path.join(MDL,'vocab.json'), encoding='utf-8'))
BLANK = vocab['<pad>']
fe    = Wav2Vec2FeatureExtractor.from_pretrained(MDL)
model = Wav2Vec2ForCTC.from_pretrained(MDL)
model.eval()
print(f'模型就绪 vocab={len(vocab)} blank={BLANK} do_normalize={fe.do_normalize}', flush=True)

y, _ = librosa.load(WAV, sr=SR, mono=True)
print(f'音频 {len(y)/SR:.2f}s', flush=True)

def logprobs(seg):
    iv = fe(seg, sampling_rate=SR, return_tensors='pt')
    with torch.no_grad():
        lg = model(iv.input_values).logits[0]
    return torch.log_softmax(lg, -1).numpy(), (len(seg)/SR)/lg.shape[0]

def forced_align(lp, ids):
    T = lp.shape[0]; S = 2*len(ids)+1
    ext = np.full(S, BLANK, int)
    for i,c in enumerate(ids): ext[2*i+1] = c
    NEG = -1e30
    dp = np.full((T,S), NEG); bt = np.zeros((T,S), np.int8)
    dp[0,0] = lp[0,ext[0]]
    if S>1: dp[0,1] = lp[0,ext[1]]
    for t in range(1,T):
        prev = dp[t-1]
        a = prev
        b = np.concatenate(([NEG], prev[:-1]))
        c = np.concatenate(([NEG,NEG], prev[:-2]))
        okc = np.zeros(S, bool)
        for s in range(2,S):
            okc[s] = ext[s]!=BLANK and ext[s]!=ext[s-2]
        c = np.where(okc, c, NEG)
        stack = np.vstack([a,b,c])
        arg = np.argmax(stack, 0)
        dp[t] = stack[arg, np.arange(S)] + lp[t, ext]
        bt[t] = arg
    s = S-1 if dp[T-1,S-1] >= dp[T-1,S-2] else S-2
    path = np.zeros(T,int)
    for t in range(T-1,-1,-1):
        path[t] = s; s -= bt[t,s]
    spans = {}
    for t,s in enumerate(path):
        if ext[s]!=BLANK:
            i=(s-1)//2
            spans.setdefault(i,[t,t])[1]=t
    return [tuple(spans[i]) if i in spans else None for i in range(len(ids))]

lines=[]
for ln in io.open(os.path.join(BASE,'lyrics.lrc'), encoding='utf-8'):
    m=re.match(r'\[(\d+):(\d+\.\d+)\]\s*(.*)', ln.strip())
    if m: lines.append((int(m.group(1))*60+float(m.group(2)), m.group(3)))
sung=[x for x in lines if '：' not in x[1]]
lead=[(s,tx) for s,tx in sung if not tx.startswith('（')]
allt=[s for s,_ in sung]
CH=re.compile(r'[\u4e00-\u9fff]')

todo = lead[:LIMIT] if LIMIT else lead
res=[]; t0=time.time()
for li,(s,tx) in enumerate(todo,1):
    txt=CH.findall(tx); n=len(txt)
    nxt=min([x for x in allt if x>s+0.5], default=s+7.0)
    lo,hi=max(0.0,s-1.0), min(len(y)/SR, nxt+0.35)
    lp,fd = logprobs(y[int(lo*SR):int(hi*SR)])
    inv=[(k,c) for k,c in enumerate(txt) if c in vocab]
    if not inv:
        res.append({'line':li,'ok':False}); continue
    sp = forced_align(lp, [vocab[c] for _,c in inv])
    per={}
    for (k,c),rng in zip(inv,sp):
        if rng is None: continue
        per[k]=(round(lo+rng[0]*fd,4), round(lo+(rng[1]+1)*fd,4))
    res.append({'line':li,'ok':True,'win':[round(lo,3),round(hi,3)],
                'nchar':n,'chars':txt,'aligned':len(per),
                'spans':{str(k):list(v) for k,v in per.items()}})
    durs=[v[1]-v[0] for v in per.values()]
    print(f'  行{li:>2}/{len(todo)} {lo:6.1f}-{hi:6.1f}s 帧{lp.shape[0]:>4} 字{n:>2} 对齐{len(per):>2} '
          f'时长中位{np.median(durs)*1000 if durs else 0:5.0f}ms ({time.time()-t0:.0f}s)', flush=True)

json.dump(res, io.open(os.path.join(BASE,'ctc_spans.json'),'w',encoding='ascii'), ensure_ascii=True)
ok=[r for r in res if r.get('ok')]
print(f'\n完成 {len(ok)}/{len(todo)} 行  耗时 {time.time()-t0:.0f}s')
print(f'对齐字数 {sum(r["aligned"] for r in ok)}/{sum(r["nchar"] for r in ok)}')
