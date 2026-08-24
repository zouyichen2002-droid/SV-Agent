# -*- coding: utf-8 -*-
"""建造顺序第 1 项的前两件：**原子写**与**哈希校验**。

## 为什么这两件必须一起做

它们防的是同一类事故的两半：

    原子写      我写到一半崩了   → 文件不许是半成品
    哈希校验    你在 SynthV 手改了 → 我不许默默盖掉

第二件在这个项目里不是假想。创作者会在 SynthV 里调音符、改工程、
从 `_backup/` 回滚。**「他手改了什么」没有任何标记会告诉我们** —— 只有内容会。
所以规则是：agent 每次写完记下内容哈希，下次写之前先比对，
对不上就**拒绝写入并说清楚**，而不是覆盖。

## 拒绝，而不是提醒

`fl_ping` 那次的教训：我只捕异常、不看返回字段，于是体检打印了「全部就绪」，
而实际 `alive: False`。**警告会被忽略，异常不会。**
所以外部改动一律抛 `ExternalEdit`，由调用方决定是备份后强写还是放弃。

## 两个哈希函数，故意不一样

    digest()       整个文件的内容哈希。**不走捷径**，用于哈希校验与 blob 寻址
    fingerprint()  小文件走 digest，大文件走 (mtime, size)。用于每秒轮询的监视器

分开是因为用途不同：校验一次写入可以慢，每秒扫 33 MB 的 wav 不行。
但**只有这一个模块知道怎么算哈希** —— `audio.py` 那次两个入口各自实现同一段
分析、产出 0.340 和 0.360 且两边都不报错，是这条规则的由来。
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

# 超过这个大小的文件，fingerprint() 不再读内容。项目里只有伴奏 wav（33 MB）
# 走这条，而它是 FL 导出的产物，慢到不可能撞上同一个时钟刻。
HASH_MAX_BYTES = 4 * 1024 * 1024
_CHUNK = 1 << 20
TMP_SUFFIX = ".svtmp"

# 校验结果。**四种，不是两种** —— 「没跟踪过」和「没被改过」是完全不同的处境，
# 混成一个 bool 就等于假装我们知道一件其实不知道的事。
CLEAN = "clean"          # 内容 = agent 上次写的
EXTERNAL = "external"    # 内容变了 —— 创作者动过
UNTRACKED = "untracked"  # 没有记录 —— 不知道是谁写的
MISSING = "missing"      # 文件不在了


class ExternalEdit(Exception):
    """目标文件在 agent 上次写入之后被外部改动过。"""


def digest(path: Path) -> str | None:
    """整个文件的内容哈希。文件不存在返回 None。"""
    h = hashlib.blake2b(digest_size=16)
    try:
        with open(path, "rb") as f:
            while chunk := f.read(_CHUNK):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def fingerprint(path: Path) -> str | None:
    """给轮询用的便宜指纹。小文件按内容，大文件按 (mtime, size)。

    **不能只用 mtime**：本机实测连续两次写有 59% 的概率 mtime 完全相同
    （Windows 时钟刻约 15 ms）。把一个字换成另一个同长度的字就能骗过它 ——
    而「监视器瞎了」的表现和它要治的病一模一样：显示旧数字、不报错。
    """
    try:
        st = path.stat()
    except OSError:
        return None
    if st.st_size <= HASH_MAX_BYTES:
        return digest(path)
    return f"{st.st_mtime_ns}:{st.st_size}"


def write_bytes(path: Path, data: bytes) -> Path:
    """原子写。要么完整的旧内容，要么完整的新内容，不存在中间态。

    先写同目录的临时文件、fsync、再 `os.replace`。同卷的 replace 在 Windows 上
    是原子的（MoveFileEx + MOVEFILE_REPLACE_EXISTING）。
    **临时文件必须同目录** —— 跨卷的 replace 会退化成复制，原子性就没了。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}{TMP_SUFFIX}{os.getpid()}")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        # KeyboardInterrupt 也要清 —— 否则每次 Ctrl-C 都留一个残骸
        tmp.unlink(missing_ok=True)
        raise
    return path


def write_text(path: Path, text: str, *, encoding: str = "utf-8") -> Path:
    return write_bytes(path, text.encode(encoding))


def write_json(path: Path, obj, *, indent: int = 2) -> Path:
    return write_text(path, json.dumps(obj, ensure_ascii=False, indent=indent))


def stale_tmps(dirs) -> list[Path]:
    """崩溃留下的临时文件。**正常情况下永远是空的** —— 非空就是出过事。"""
    out = []
    for d in dirs:
        d = Path(d)
        if d.is_dir():
            out += sorted(d.glob(f"*{TMP_SUFFIX}*"))
    return out


def sweep_tmps(dirs) -> list[Path]:
    """清掉崩溃残留。→ 清掉了哪些。"""
    gone = []
    for f in stale_tmps(dirs):
        try:
            f.unlink()
            gone.append(f)
        except OSError:
            pass
    return gone


@dataclass
class Guard:
    """记住 agent 写过什么，据此判断文件有没有被外部改动。

    账本是**出处记录**，不是状态标记 —— 它回答的是「上次是我写的吗」，
    这件事无法从文件本身推出来，所以必须存。它不参与任何「这一步做完没有」
    的判定（那永远从内容现算，见 `state.inspect`）。
    """

    ledger_path: Path

    def __post_init__(self) -> None:
        self.ledger_path = Path(self.ledger_path)

    def _read(self) -> dict:
        """**每次从文件现读，不缓存。**

        缓存过一版，被测试抓到：`guard_of(proj)` 每次造一个新实例，
        两个实例同时活着时，后 flush 的那个会拿自己那份过期的内存副本
        把前一个的记录整片盖掉 —— 而且不报错。

        这正是这一项要防的失败形态，所以规矩和 `state.inspect()` 一样：
        **真相在文件里，每次现读。** 账本只有几条，读它不值得优化。

        读不出来一律退回空 dict —— 于是所有文件变成 UNTRACKED（「不知道」），
        而不是 CLEAN（「没被改过」）。坏账本不许静默放行。
        """
        try:
            return json.loads(self.ledger_path.read_text("utf-8"))
        except (OSError, ValueError):
            return {}

    # ---- 查 ----------------------------------------------------------
    def verify(self, path: Path) -> str:
        path = Path(path)
        rec = self._read().get(str(path))
        if rec is None:
            return MISSING if not path.exists() else UNTRACKED
        if not path.exists():
            return MISSING
        return CLEAN if digest(path) == rec["hash"] else EXTERNAL

    def assert_clean(self, path: Path) -> None:
        """外部改动就抛。**不打警告** —— 警告会被忽略。"""
        v = self.verify(path)
        if v == EXTERNAL:
            rec = self._read()[str(Path(path))]
            when = time.strftime("%m-%d %H:%M", time.localtime(rec["ts"]))
            raise ExternalEdit(
                f"{path} 在我上次写入（{when}）之后被改过。\n"
                f"    我不会覆盖它。要么先备份再用 force=True，"
                f"要么先把你的改动保留下来。")

    def status(self, paths) -> list[tuple[Path, str]]:
        """给仪表盘用：一批文件各自什么状态。"""
        return [(Path(p), self.verify(p)) for p in paths]

    # ---- 写 ----------------------------------------------------------
    def record(self, path: Path) -> None:
        path = Path(path)
        book = self._read()          # 读—改—写，不是覆盖
        h = digest(path)
        if h is None:
            book.pop(str(path), None)
        else:
            book[str(path)] = {"hash": h, "ts": time.time(),
                               "size": path.stat().st_size}
        self._flush(book)

    def write(self, path: Path, data: bytes, *, force: bool = False) -> Path:
        """校验 → 原子写 → 记账。这是 agent 写文件的**唯一**入口。"""
        if not force:
            self.assert_clean(path)
        write_bytes(path, data)
        self.record(path)
        return Path(path)

    def forget(self, path: Path) -> None:
        book = self._read()
        book.pop(str(Path(path)), None)
        self._flush(book)

    def _flush(self, book: dict) -> None:
        # 账本自己也走原子写 —— 它坏了会让所有校验失效
        write_json(self.ledger_path, book)
