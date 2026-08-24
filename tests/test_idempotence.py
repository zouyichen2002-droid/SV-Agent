# -*- coding: utf-8 -*-
"""建造顺序第 2 项：**六个步骤脚本连跑两次，产物语义必须相同。**

## 这一项要回答的具体问题

验收标准里有一条挂着「未验证」：**调教点会不会叠加两遍**。
`step5_tune` 往 `.svp` 的 `parameters` 里写点；如果它是「追加」而不是「重写」，
跑两次就会得到双份，而**文件照样能打开、SynthV 照样能唱** ——
又一个安静的错误。这个测试就是去回答它。

## 为什么必须在沙盒里跑

这些脚本会写创作者的真工程。所以每个测试先把《晓风残月》整套复制到
临时目录、建一个自己的 `project.json`，用 `SVAGENT_SONG` 指过去。
**真工程一个字节都不碰。**

## 为什么用子进程而不是直接调函数

因为「动作」的定义就是那条命令行。直接调内部函数会绕过参数解析、
路径解析、写入守卫 —— 那些恰恰是最容易在两次运行之间产生差异的地方。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "toolkit"))

from svagent import project as PJ              # noqa: E402
from svagent.agent import idem as ID           # noqa: E402

SLUG = "_idem_sandbox"
BASE = "xiaofeng"

# 每个动作：参数 · 产出什么 · 说明 · **它至少该产出什么**（防空跑）
ACTIONS = [
    ("step3_melody", ["--write", "--closed"], "svp", "生成主旋律与和声",
     "notes"),
    ("step4_accompaniment", ["--write"], "mid", "生成伴奏 MIDI",
     "midi_events"),
    ("step5_assemble", ["--write", "--closed"], "svp", "伴奏音频进工程",
     "audio_tracks"),
    ("step5_tune", ["--write", "--closed"], "svp", "写调教曲线",
     "tuning_points"),
    ("step6_mix", ["--write", "--closed"], "svp", "写混音 FX",
     "fx_tracks"),
]


@pytest.fixture
def sandbox(tmp_path):
    """把整首歌复制进临时目录，返回 (slug, env, 产物路径)。"""
    src = PJ.load(BASE)
    d = tmp_path / "song"
    d.mkdir()
    svp, mid, wav = d / "t.svp", d / "t_伴奏.mid", d / "t_伴奏.wav"
    shutil.copyfile(src.lyrics, d / "lyrics.txt")
    for s, t in ((src.svp, svp), (src.mid, mid), (src.wav, wav)):
        if s.exists():
            shutil.copyfile(s, t)

    cfg_dir = PJ.SONGS / SLUG
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "project.json").write_text(json.dumps({
        "title": "幂等沙盒", "svp": str(svp), "bpm": src.bpm,
        "form": [[n, b] for n, b in src.form],
        "lyrics": str(d / "lyrics.txt"), "mid": str(mid), "wav": str(wav),
    }, ensure_ascii=False), encoding="utf-8")

    env = dict(os.environ, SVAGENT_SONG=SLUG, PYTHONIOENCODING="utf-8")
    try:
        yield {"env": env, "svp": svp, "mid": mid, "wav": wav, "dir": d}
    finally:
        shutil.rmtree(cfg_dir, ignore_errors=True)


def _run(script: str, args: list[str], env: dict):
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / f"{script}.py"), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, timeout=600, cwd=str(ROOT))


@pytest.mark.parametrize("script,args,produces,desc,must_have", ACTIONS,
                         ids=[a[0] for a in ACTIONS])
def test_动作连跑两次语义相同(sandbox, script, args, produces, desc,
                              must_have):
    """跑一次 → 记语义指纹 → 再跑一次 → 必须一模一样，且产物必须非空。"""
    target = sandbox[produces]

    r1 = _run(script, args, sandbox["env"])
    if r1.returncode == 4 and "SynthV" in (r1.stdout + r1.stderr):
        pytest.skip("SynthV 正在运行 —— 关掉它再跑这一项")
    assert r1.returncode == 0, f"第一次就没跑通：\n{r1.stdout[-1500:]}"
    assert target.exists(), f"{script} 没产出 {target.name}"

    # 防空跑：两个空产物比起来也「相等」。先确认这一次真的产出了东西。
    stats = ID.content_stats(target)
    assert stats.get(must_have, 0) > 0, (
        f"{script} 产出的 {must_have} 是 0 —— 这个测试在比较空产物，"
        f"等于没测。实际统计：{stats}")

    before = ID.semantic_digest(target)
    snap = target.with_name(target.name + ".run1")
    shutil.copyfile(target, snap)

    r2 = _run(script, args, sandbox["env"])
    assert r2.returncode == 0, f"第二次没跑通：\n{r2.stdout[-1500:]}"
    after = ID.semantic_digest(target)
    detail = ""
    if before != after:
        parts = (ID.diff_svp(snap, target) if produces == "svp"
                 else ["MIDI 事件序列不同"])
        detail = "；".join(parts[:12])

    ID.save_result(script, desc, before == after, stats, detail)
    if detail:
        pytest.fail(f"{script}（{desc}）不幂等，两次运行差在：\n  "
                    + detail.replace("；", "\n  "))


# -------------------------------------------------------------------------
# 归一化本身也要有反向测试。
# 「只会返回相等」的比较器，比没有比较器更坏 —— 它会让整张动作表永远全绿。
# -------------------------------------------------------------------------

def _mini_svp(tmp_path, name, notes, params=None, uuid="u1"):
    d = {
        "time": {"tempo": [{"position": 0, "bpm": 66}]},
        "library": [{"uuid": uuid, "notes": notes,
                     "parameters": params or {}}],
        "tracks": [{"name": name, "mainRef": {"groupID": uuid},
                    "groups": [{"groupID": uuid}], "mixer": {"gainDecibel": 0}}],
    }
    p = tmp_path / f"{name}_{uuid}.svp"
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return p


def test_uuid不同但内容相同要判为相等(tmp_path):
    """这是归一化存在的理由 —— 每次写出都会换一批 uuid。"""
    ns = [{"onset": 0, "duration": 100, "pitch": 60, "lyrics": "渡"}]
    a = _mini_svp(tmp_path, "主旋律", ns, uuid="aaa")
    b = _mini_svp(tmp_path, "主旋律", ns, uuid="bbb")
    assert ID.semantic_digest(a) == ID.semantic_digest(b)


def test_音符变了必须判为不等(tmp_path):
    a = _mini_svp(tmp_path, "主旋律",
                  [{"onset": 0, "duration": 100, "pitch": 60, "lyrics": "渡"}])
    b = _mini_svp(tmp_path, "主旋律",
                  [{"onset": 0, "duration": 100, "pitch": 62, "lyrics": "渡"}],
                  uuid="u2")
    assert ID.semantic_digest(a) != ID.semantic_digest(b)
    assert any("音符内容不同" in s for s in ID.diff_svp(a, b))


def test_调教点翻倍必须判为不等(tmp_path):
    """这正是这一项要抓的东西：点数从 N 变成 2N。"""
    ns = [{"onset": 0, "duration": 100, "pitch": 60, "lyrics": "渡"}]
    one = {"loudness": {"mode": "cosine", "points": [0, 1.0, 100, 2.0]}}
    two = {"loudness": {"mode": "cosine",
                        "points": [0, 1.0, 50, 1.5, 100, 2.0, 150, 2.5]}}
    a = _mini_svp(tmp_path, "主旋律", ns, one)
    b = _mini_svp(tmp_path, "主旋律", ns, two, uuid="u2")
    assert ID.semantic_digest(a) != ID.semantic_digest(b)
    assert any("点数 2 → 4" in s for s in ID.diff_svp(a, b))


def test_丢uuid不能把引用结构一起丢掉(tmp_path):
    """两条轨用了不同的音符组，归一化之后必须还是不同的。

    如果解引用做错、只留下音符集合，这两个工程会归一化成同一个东西 ——
    测试就变成永远通过的空壳。
    """
    n1 = [{"onset": 0, "duration": 100, "pitch": 60, "lyrics": "渡"}]
    n2 = [{"onset": 0, "duration": 100, "pitch": 72, "lyrics": "口"}]
    a = _mini_svp(tmp_path, "主旋律", n1)
    b = _mini_svp(tmp_path, "主旋律", n2, uuid="u2")
    assert ID.semantic_digest(a) != ID.semantic_digest(b)


def test_过期检测会响(tmp_path, monkeypatch):
    """代码改了、幂等没重测，表上那些 ✓ 必须自己承认不算数。

    一个永远不报警的警报器等于没有 —— 而它守的正是
    「一张不肯承认自己过期的表比没有表更坏」这条。
    """
    rep = tmp_path / "idem.json"
    ID.save_result("stepX", "测试用", True, {"notes": 1}, path=rep)
    d = ID.load_report(rep)

    monkeypatch.setattr(ID, "code_mtime", lambda: 0.0)
    assert ID.report_is_stale(d) is False
    monkeypatch.setattr(ID, "code_mtime", lambda: 9e18)
    assert ID.report_is_stale(d) is True
    assert ID.report_is_stale({}) is None, "没测过要说「不知道」，不是「没过期」"


def test_mixer变了必须判为不等(tmp_path):
    ns = [{"onset": 0, "duration": 100, "pitch": 60, "lyrics": "渡"}]
    a = _mini_svp(tmp_path, "主旋律", ns)
    b = _mini_svp(tmp_path, "主旋律", ns, uuid="u2")
    d = json.loads(b.read_text(encoding="utf-8"))
    d["tracks"][0]["mixer"]["gainDecibel"] = -6.0
    b.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    assert ID.semantic_digest(a) != ID.semantic_digest(b)
    assert any("mixer" in s for s in ID.diff_svp(a, b))
