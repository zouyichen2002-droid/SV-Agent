# -*- coding: utf-8 -*-
"""两个钢琴预览渲染器：纯代码合成 vs 读 Windows 自带的 gm.dls 采样钢琴。

两个都只做一件事：音符列表 → 单声道 float32 音频。

**固定增益，不做逐文件归一化。** PRD R05 要求 A/B 比较时「相同预览音色和增益」——
逐文件归一化会让两个候选的响度各不相同，响的那个听起来总是更好，比较就不公平了。
MASTER 按标准样本定一次，之后不动。

命令行（给冷启动测量用，每次一个新进程）：
    python renderers.py additive out.wav
    python renderers.py gmdls out.wav
"""
from __future__ import annotations

import struct
import sys
import wave

import numpy as np

SR = 44100
RELEASE_S = 0.18   # 松键后的衰减时间（制音器落下）


def _release_env(t, dur):
    """按住期间为 1，松键后指数衰减。"""
    env = np.ones_like(t)
    off = t > dur
    env[off] = np.exp(-(t[off] - dur) / (RELEASE_S / 4))
    return env


def _buffer(notes):
    end = max(s + d for s, d, _, _ in notes)
    return np.zeros(int((end + RELEASE_S + 0.05) * SR), np.float32)


class AdditivePiano:
    """纯代码合成：每个音 = 最多 12 个泛音，高泛音衰减得更快。零外部依赖。"""

    name = "additive"
    MASTER = 0.195   # 标准样本 RMS ≈ -20 dBFS，与 gmdls 对齐（响度不同会带偏听感比较）

    def load(self):
        return self   # 没有东西要载入

    def render(self, notes):
        out = _buffer(notes)
        for start, dur, pitch, vel in notes:
            f0 = 440.0 * 2 ** ((pitch - 69) / 12)
            n = int((dur + RELEASE_S) * SR)
            t = np.arange(n, dtype=np.float32) / SR
            decay = 0.9 * 2 ** ((pitch - 60) / 24)   # 低音衰减慢，高音快
            y = np.zeros(n, np.float32)
            for k in range(1, 13):
                fk = k * f0 * np.sqrt(1 + 0.0004 * k * k)   # 弦的非谐性：高泛音略偏高
                if fk > SR * 0.45:
                    break
                partial_decay = decay * (1 + 0.5 * (k - 1))
                y += (k ** -1.3) * np.exp(-t * partial_decay) * np.sin(2 * np.pi * fk * t)
            env = np.minimum(1.0, t / 0.003) * _release_env(t, dur)   # 3 ms 起音防爆音
            i0 = int(start * SR)
            out[i0:i0 + n] += y * env * (vel / 127) ** 1.5
        return out * self.MASTER


class GmDlsPiano:
    """读 Windows 自带的 gm.dls（Microsoft GS Wavetable 音色集）里的 0 号音色 Piano 1。

    只在本机读取，**从不复制进仓库**（.gitignore 里有 *.dls）。
    10 个分区，每段是 22050 Hz / 16-bit 的短采样（0.2–0.6 秒），尾部带一个
    循环段用来延音。

    DLS 自带的包络参数（art1）没有解析，用一个固定的钢琴式衰减代替 ——
    预览只判断旋律、和声、节奏（PRD §8.1），不判断音色。
    """

    name = "gmdls"
    PATH = r"C:\Windows\System32\drivers\gm.dls"
    MASTER = 1.38    # 标准样本 RMS ≈ -20 dBFS，与 additive 对齐

    def load(self):
        self.buf = open(self.PATH, "rb").read()
        assert self.buf[0:4] == b"RIFF" and self.buf[8:12] == b"DLS ", "不是 DLS 文件"
        top = list(self._chunks(12, len(self.buf)))
        lins = next(c for c in top if c[3] == "lins")
        wvpl = next(c for c in top if c[3] == "wvpl")
        ptbl = next(c for c in top if c[0] == "ptbl")
        cb, ncues = struct.unpack_from("<II", self.buf, ptbl[1])
        self.cues = struct.unpack_from(f"<{ncues}I", self.buf, ptbl[1] + cb)
        self.wvpl_data = wvpl[1] + 4
        self.regions = self._piano_regions(lins)
        assert len(self.regions) == 10, f"Piano 1 应有 10 个分区，实际 {len(self.regions)}"
        del self.buf   # 采样已经拷出来了，原文件不留在内存里
        return self

    # ---- DLS 是 RIFF 格式：一层层的 [4 字节标识][4 字节长度][内容] ----

    def _chunks(self, start, end):
        pos = start
        while pos + 8 <= end:
            cid = self.buf[pos:pos + 4].decode("latin1")
            size = struct.unpack_from("<I", self.buf, pos + 4)[0]
            d0, d1 = pos + 8, pos + 8 + size
            ltype = self.buf[d0:d0 + 4].decode("latin1") if cid in ("RIFF", "LIST") else None
            yield cid, d0, d1, ltype
            pos = d1 + (size & 1)   # 奇数长度后面有一个填充字节

    def _wsmp(self, at):
        """wsmp 块 → (基准音, 微调音分, 增益, 循环(起点, 长度) 或 None)。"""
        cb, unity, fine, att, _, nloops = struct.unpack_from("<IHhiII", self.buf, at)
        loop = struct.unpack_from("<IIII", self.buf, at + cb)[2:] if nloops else None
        gain = 10 ** (att / 655360 / 20)   # DLS 的衰减单位是 1/655360 dB
        return unity, fine, gain, loop

    def _piano_regions(self, lins):
        for _, d0, d1, lt in self._chunks(lins[1] + 4, lins[2]):
            if lt != "ins ":
                continue
            sub = list(self._chunks(d0 + 4, d1))
            _, bank, prog = struct.unpack_from("<III", self.buf, next(s for s in sub if s[0] == "insh")[1])
            if prog != 0 or bank != 0:   # 只要 bank 0 的 0 号音色（非鼓组）
                continue
            lrgn = next(s for s in sub if s[3] == "lrgn")
            regions = []
            for _, r0, r1, rt in self._chunks(lrgn[1] + 4, lrgn[2]):
                if rt not in ("rgn ", "rgn2"):
                    continue
                rs = {c: a for c, a, _, _ in self._chunks(r0 + 4, r1)}
                klo, khi = struct.unpack_from("<HH", self.buf, rs["rgnh"])
                table_index = struct.unpack_from("<HHII", self.buf, rs["wlnk"])[3]
                sr, samples, wave_wsmp = self._wave(table_index)
                unity, fine, gain, loop = self._wsmp(rs["wsmp"] if "wsmp" in rs else wave_wsmp)
                regions.append((klo, khi, unity, fine, gain, sr, samples, loop))
            return regions
        raise LookupError("gm.dls 里没找到 bank 0 / program 0")

    def _wave(self, table_index):
        w0 = self.wvpl_data + self.cues[table_index]
        size = struct.unpack_from("<I", self.buf, w0 + 4)[0]
        sub = {c: (a, b) for c, a, b, _ in self._chunks(w0 + 12, w0 + 8 + size)}
        fmt_tag, channels, sr, _, _, bits = struct.unpack_from("<HHIIHH", self.buf, sub["fmt "][0])
        assert (fmt_tag, channels, bits) == (1, 1, 16), "只处理单声道 16-bit PCM"
        a, b = sub["data"]
        samples = np.frombuffer(self.buf[a:b], "<i2").astype(np.float32) / 32768
        return sr, samples, sub["wsmp"][0] if "wsmp" in sub else None

    # ---- 渲染 ----

    def render(self, notes):
        out = _buffer(notes)
        for start, dur, pitch, vel in notes:
            klo, khi, unity, fine, gain, src_sr, s, loop = next(
                r for r in self.regions if r[0] <= pitch <= r[1])
            ratio = (src_sr / SR) * 2 ** ((pitch - unity) / 12 + fine / 1200)
            n = int((dur + RELEASE_S) * SR)
            pos = np.arange(n) * ratio               # 每个输出样本对应原采样的哪个位置
            if loop:                                 # 走到循环段末尾就绕回循环起点
                ls, ll = loop
                le = ls + ll
                over = pos >= le
                pos[over] = ls + np.mod(pos[over] - ls, ll)
            else:                                    # 没有循环：采样放完就结束
                pos = pos[pos < len(s) - 1]
                n = len(pos)
            i = pos.astype(np.int64)
            frac = (pos - i).astype(np.float32)
            j = i + 1
            if loop:
                j[j >= le] = ls
            y = s[i] * (1 - frac) + s[j] * frac      # 线性插值
            t = np.arange(n, dtype=np.float32) / SR
            tau = 2.2 * 2 ** (-(pitch - 60) / 24)    # 延音衰减：低音长，高音短
            env = np.exp(-t / tau) * _release_env(t, dur)
            i0 = int(start * SR)
            out[i0:i0 + n] += y * env * gain * (vel / 127) ** 1.5
        return out * self.MASTER


RENDERERS = {"additive": AdditivePiano, "gmdls": GmDlsPiano}


def write_wav(path, audio):
    """写 44.1 kHz / 16-bit / 单声道 WAV → (峰值 dBFS, RMS dBFS, 削波样本数)。

    削波数应为 0；不是 0 说明 MASTER 定高了。**这里不做任何归一化。**
    """
    peak = float(np.max(np.abs(audio)))
    rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))
    clipped = int(np.count_nonzero(np.abs(audio) > 1.0))
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return 20 * np.log10(peak), 20 * np.log10(rms), clipped


if __name__ == "__main__":
    import sample

    name, out_path = sys.argv[1], sys.argv[2]
    renderer = RENDERERS[name]().load()
    write_wav(out_path, renderer.render(sample.notes_in_seconds()))
