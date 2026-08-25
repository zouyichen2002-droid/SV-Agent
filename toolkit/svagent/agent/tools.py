# -*- coding: utf-8 -*-
"""建造顺序第 5 项：**工具层** —— 动作池 + schema + 写后钩子。

## 这一层把「一堆脚本」变成「agent 的动作」

在它之前，能力散在六个步骤脚本里，只有人能调。之后每个能力都有：

    名字与 JSON Schema      模型能看懂、能调
    不变的执行序列          校验哈希 → 写前备份 → 度量 → 执行 → 钩子 → 记节点
    **可程序化的产出**      不是「成功/失败」，是 findings 前后、改了几个音符

## 支点在最后一条

架构文档 §2.5：六个对照项目的 `tool_result` 都只说「执行成功 / 失败」。
我们的带度量，所以**模型不需要判断正确性** —— 它只看数字决定下一步。
模型负责品味，L1 负责正确。这一层就是那个交接面。

## 钩子的触发条件是「文件真的变了」，不是「动作说自己写了」

动作可能中途抛异常、可能声称写了却没写、可能声称没写却写了。
所以执行器比对前后的源文件指纹 —— **变了就必然跑钩子**，
哪怕动作本身失败了。一个写坏了却没被检查的文件，
就是这个项目最典型的那种安静错误。

## 窄逃生口

`set_mixer_param` 只能碰混音器（增益/声像/静音/FX 开关）。
**它碰不到音符，所以碰不到音乐正确性** —— 写完还会断言音符数没变。
不开放任意代码生成：那会让「每一步可度量」失效。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .. import project as PJ
from . import budget as BD
from . import idem as ID
from . import safewrite as SW
from . import state as ST
from . import tree as TR

ROOT = Path(__file__).resolve().parents[3]

READY, NEEDS_MODEL, PARTIAL = "ready", "needs_model", "partial"


class ToolError(Exception):
    """参数不合法、动作不存在、前置条件不满足。**不是 bug，是拒绝执行。**"""


# =========================================================================
# 度量：tool_result 的内容
# =========================================================================

def measure(proj: PJ.SongProject, *, deep: bool = True) -> dict:
    """产物的可程序化度量。**全部来自库里已有的函数，这里不算新数字。**"""
    m: dict = {}
    m.update(ID.content_stats(proj.svp))
    m.update(ID.content_stats(proj.mid))
    st = ST.inspect(proj)
    m["steps_done"] = st.n_done
    if deep and st.steps[2].done:
        try:
            fs = ST.check_melody(proj)
            m["findings"] = len(fs)
            by: dict = {}
            for f in fs:
                by[f.kind] = by.get(f.kind, 0) + 1
            m["findings_by_kind"] = by
        except Exception as e:
            m["findings"] = None
            m["findings_error"] = f"{type(e).__name__}: {e}"
    return m


def delta_of(before: dict, after: dict) -> dict:
    """只报**变了的**项。没变的不进 tool_result —— 噪声会淹掉信号。"""
    out = {}
    for k in sorted(set(before) | set(after)):
        a, b = before.get(k), after.get(k)
        if a == b:
            continue
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            out[k] = {"before": a, "after": b, "change": round(b - a, 4)}
        else:
            out[k] = {"before": a, "after": b}
    return out


# =========================================================================
# 写后钩子
# =========================================================================

@dataclass
class HookResult:
    name: str
    ok: bool
    detail: str
    numbers: dict = field(default_factory=dict)


def _h_checks(proj) -> HookResult:
    try:
        fs = ST.check_melody(proj)
    except Exception as e:
        return HookResult("checks", False, f"跑不起来：{type(e).__name__}: {e}")
    by: dict = {}
    for f in fs:
        by[f.kind] = by.get(f.kind, 0) + 1
    return HookResult("checks", not fs,
                      "七项检查 0 finding" if not fs else f"{len(fs)} finding：{by}",
                      {"findings": len(fs), "by_kind": by})


def _h_overlap(proj) -> HookResult:
    n = ID.content_stats(proj.svp).get("overlaps", 0)
    return HookResult("overlap", n == 0,
                      "同轨无重叠" if n == 0
                      else f"同轨重叠 {n} 处 —— SynthV 不允许（F03）",
                      {"overlaps": n})


def _h_state(proj) -> HookResult:
    st = ST.inspect(proj)
    nx = st.next_step
    return HookResult("state", True,
                      f"{st.n_done}/6 步"
                      + (f"，下一步 {nx.name}（{nx.who}）" if nx else "，全部完成"),
                      {"steps_done": st.n_done})


def _h_alignment(proj) -> HookResult:
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import step5_assemble as S5
        rep = S5.align_report(proj.bpm)      # **与脚本同一个实现**
    except Exception as e:
        return HookResult("alignment", False, f"跑不起来：{type(e).__name__}: {e}")
    return HookResult("alignment", rep["ok"],
                      f"偏移 {rep['offset_ms']:+.1f} ms　"
                      f"三段极差 {rep['spread_ms']:.1f} ms", rep)


HOOKS: dict[str, Callable] = {
    "checks": _h_checks, "overlap": _h_overlap,
    "state": _h_state, "alignment": _h_alignment,
}


# =========================================================================
# 动作的执行体
# =========================================================================

def _script(name: str, args: list[str], proj) -> tuple[int, str]:
    env = dict(os.environ, SVAGENT_SONG=proj.slug, PYTHONIOENCODING="utf-8")
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / f"{name}.py"), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, timeout=1800, cwd=str(ROOT))
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode == 4 and "SynthV" in out:
        raise ToolError("SynthV 正在打开这个工程 —— 先退出它。"
                        "（不是 bug：写一个别人正开着的文件必然出事）")
    if r.returncode != 0:
        raise ToolError(f"{name} 退出码 {r.returncode}：{out[-600:]}")
    return r.returncode, out


def _a_gen_melody(proj, p) -> dict:
    args = ["--write", "--closed"]
    for k, flag in (("specs", "--specs"), ("seeds", "--seeds")):
        if p.get(k) is not None:
            args += [flag, str(p[k])]
    if p.get("bpm") is not None:
        args += ["--bpm", str(p["bpm"])]
    _rc, out = _script("step3_melody", args, proj)
    return {"stdout_tail": out[-800:]}


def _a_gen_harmony(proj, p) -> dict:
    args = ["--keep-melody", "--write", "--closed",
            "--harmony", ",".join(p["kind"]),
            "--harmony-sections", ",".join(p.get("sections") or ["副歌"])]
    _rc, out = _script("step3_melody", args, proj)
    return {"stdout_tail": out[-800:]}


def _a_adjust_spec(proj, p) -> dict:
    args = ["--write", "--closed", "--register-shift", p["register_shift"]]
    for k, flag in (("specs", "--specs"), ("seeds", "--seeds")):
        if p.get(k) is not None:
            args += [flag, str(p[k])]
    _rc, out = _script("step3_melody", args, proj)
    return {"stdout_tail": out[-800:]}


def _a_gen_accompaniment(proj, p) -> dict:
    _rc, out = _script("step4_accompaniment", ["--write"], proj)
    return {"stdout_tail": out[-800:]}


def _a_assemble(proj, p) -> dict:
    _rc, out = _script("step5_assemble", ["--write", "--closed"], proj)
    return {"stdout_tail": out[-800:]}


def _a_tune(proj, p) -> dict:
    args = ["--write", "--closed"]
    if p.get("clear"):
        args.append("--clear")
    if p.get("scale") is not None:
        args += ["--scale", str(p["scale"])]
    if p.get("harmony_scale") is not None:
        args += ["--harmony-scale", str(p["harmony_scale"])]
    _rc, out = _script("step5_tune", args, proj)
    return {"stdout_tail": out[-800:]}


def _a_mix(proj, p) -> dict:
    args = ["--write", "--closed"]
    if p.get("clear"):
        args.append("--clear")
    if p.get("no_carve"):
        args.append("--no-carve")
    for k, flag in (("lead_gain", "--lead-gain"),
                    ("harmony_gain", "--harmony-gain"),
                    ("acc_gain", "--acc-gain")):
        if p.get(k) is not None:
            args += [flag, str(p[k])]
    _rc, out = _script("step6_mix", args, proj)
    return {"stdout_tail": out[-800:]}


def _a_verify_alignment(proj, p) -> dict:
    sys.path.insert(0, str(ROOT / "scripts"))
    import step5_assemble as S5
    return {"alignment": S5.align_report(p.get("bpm") or proj.bpm)}


def _a_revert(proj, p) -> dict:
    t = TR.Tree(proj)
    touched = t.checkout(p["node_id"])
    return {"reverted_to": p["node_id"],
            "files_written": [str(x) for x in touched]}


MIXER_FIELDS = ("gainDecibel", "pan", "mute", "solo")
FX_NAMES = ("postRoomEq", "compressor", "reverb", "room")


def _a_set_mixer_param(proj, p) -> dict:
    """**窄逃生口**：只碰混音器，写完断言音符数没变。"""
    before_notes = ID.content_stats(proj.svp).get("notes", 0)
    d = json.loads(proj.svp.read_text(encoding="utf-8-sig"))
    hit = [t for t in d.get("tracks", []) if t.get("name") == p["track"]]
    if not hit:
        names = [t.get("name") for t in d.get("tracks", [])]
        raise ToolError(f"没有叫「{p['track']}」的轨。现有：{names}")
    t = hit[0]
    field_, val = p["field"], p["value"]
    mixer = t.setdefault("mixer", {})
    if field_ in MIXER_FIELDS:
        old = mixer.get(field_)
        mixer[field_] = val
    elif field_.startswith("fx."):
        _, name, key = field_.split(".", 2)
        if name not in FX_NAMES:
            raise ToolError(f"未知的 FX「{name}」，只能是 {FX_NAMES}")
        old = ((mixer.get("fxParams") or {}).get(name) or {}).get(key)
        mixer.setdefault("fxParams", {}).setdefault(name, {})[key] = val
    else:
        raise ToolError(f"「{field_}」不在窄逃生口里。"
                        f"只能改 {MIXER_FIELDS} 或 fx.<{'|'.join(FX_NAMES)}>.<键>")

    g = SW.Guard(proj.agent_dir / "ledger.json")
    g.write(proj.svp, json.dumps(d, ensure_ascii=False).encode("utf-8"))

    after_notes = ID.content_stats(proj.svp).get("notes", 0)
    if after_notes != before_notes:
        raise ToolError(f"逃生口碰到了音符（{before_notes} → {after_notes}）"
                        f"—— 这是 bug，工程已被改动，去会话树回退")
    return {"track": p["track"], "field": field_, "before": old, "after": val,
            "notes_unchanged": True}


def _a_gen_lyrics(proj, p) -> dict:
    raise ToolError("gen_lyrics 需要模型，第 10 项才接上。"
                    "现在请在对话里让我写词，再存进 lyrics.txt")


# =========================================================================
# 动作池
# =========================================================================

@dataclass
class Action:
    name: str
    desc: str
    schema: dict
    run: Callable
    hooks: tuple[str, ...] = ()
    writes: bool = True
    status: str = READY
    note: str = ""
    # 它封装的是哪个步骤脚本。**显式写出来**，不靠名字模糊匹配 ——
    # 幂等报告是按脚本记的，模糊匹配迟早对错一个而且不会报错。
    script: str = ""


def _obj(props: dict, required: tuple = ()) -> dict:
    return {"type": "object", "properties": props,
            "required": list(required), "additionalProperties": False}


ACTIONS: list[Action] = [
    Action("gen_lyrics", "按主题生成多版歌词候选",
           _obj({"theme": {"type": "string", "description": "一句话主题"},
                 "n": {"type": "integer", "minimum": 1, "maximum": 20}},
                ("theme",)),
           _a_gen_lyrics, (), True, NEEDS_MODEL,
           "唯一真正需要语言能力的动作。第 10 项接 Mistral 之后可用"),

    Action("gen_melody", "重新生成主旋律与和声（整首）",
           _obj({"scope": {"type": "string", "enum": ["全曲"]},
                 "bpm": {"type": "number", "minimum": 40, "maximum": 200},
                 "specs": {"type": "integer", "minimum": 1, "maximum": 64},
                 "seeds": {"type": "integer", "minimum": 1, "maximum": 8}}),
           _a_gen_melody, ("checks", "overlap", "state"), True, PARTIAL,
           "只支持 scope=全曲。**段落级是第 6 项** —— 局部修改是归因的前提", script="step3_melody"),

    Action("gen_harmony", "保留主旋律，只重做和声轨",
           _obj({"kind": {"type": "array", "minItems": 1,
                          "items": {"type": "string",
                                    "enum": ["低八度", "下三度", "上三度", "下六度"]}},
                 "sections": {"type": "array",
                              "items": {"type": "string"}}},
                ("kind",)),
           _a_gen_harmony, ("checks", "overlap"), True, script="step3_melody"),

    Action("adjust_spec", "改规格后重生成：音区整体或按段偏移半音",
           _obj({"register_shift": {
                     "type": "string",
                     "description": '如 "+3" 或 "副歌=+3,主歌=-2"。'
                                    '会夹到声库舒适音域 57–78'},
                 "specs": {"type": "integer", "minimum": 1, "maximum": 64},
                 "seeds": {"type": "integer", "minimum": 1, "maximum": 8}},
                ("register_shift",)),
           _a_adjust_spec, ("checks", "overlap", "state"), True, PARTIAL,
           "只暴露了音区偏移。调 / 节奏细胞 / 动机在 SongSpec 里有，"
           "但 step3 还没开出对应开关", script="step3_melody"),

    Action("gen_accompaniment", "生成伴奏 MIDI（之后要人在 FL 里配器导出）",
           _obj({}), _a_gen_accompaniment, ("state",), True, script="step4_accompaniment"),

    Action("assemble", "把 FL 导出的伴奏音频挂进工程",
           _obj({}), _a_assemble, ("alignment", "state"), True, READY,
           "架构文档 §5 的十个动作里没有它 —— 但工作流需要，故补上（第 11 个）", script="step5_assemble"),

    Action("tune", "写调教曲线（响度/张力/音区偏移/唱法）",
           _obj({"scale": {"type": "number", "minimum": 0, "maximum": 3},
                 "harmony_scale": {"type": "number", "minimum": 0, "maximum": 3},
                 "clear": {"type": "boolean"}}),
           _a_tune, ("state",), True, script="step5_tune"),

    Action("mix", "写混音 FX（EQ/压缩/混响/增益结构）",
           _obj({"lead_gain": {"type": "number", "minimum": -24, "maximum": 12},
                 "harmony_gain": {"type": "number", "minimum": -24, "maximum": 12},
                 "acc_gain": {"type": "number", "minimum": -24, "maximum": 12},
                 "no_carve": {"type": "boolean"},
                 "clear": {"type": "boolean"}}),
           _a_mix, ("state",), True, script="step6_mix"),

    Action("verify_alignment", "验证伴奏与人声的对齐（只读，不碰文件）",
           _obj({"bpm": {"type": "number", "minimum": 40, "maximum": 200}}),
           _a_verify_alignment, (), False),

    Action("revert", "回到会话树上的某个节点",
           _obj({"node_id": {"type": "string",
                             "description": "如 n0003"}}, ("node_id",)),
           _a_revert, ("checks", "overlap", "state"), True),

    Action("set_mixer_param", "窄逃生口：只改某条轨的混音器参数，碰不到音符",
           _obj({"track": {"type": "string"},
                 "field": {"type": "string",
                           "description": "gainDecibel / pan / mute / solo，"
                                          "或 fx.<postRoomEq|compressor|reverb|room>.<键>"},
                 "value": {"description": "新值"}},
                ("track", "field", "value")),
           _a_set_mixer_param, ("overlap",), True),
]

BY_NAME = {a.name: a for a in ACTIONS}


def to_mistral_tools() -> list[dict]:
    """给模型的 tools 数组。**只导出 ready 与 partial** ——
    没接上的动作放进去只会换来一次必然失败的调用。"""
    return [{"type": "function",
             "function": {"name": a.name, "description": a.desc,
                          "parameters": a.schema}}
            for a in ACTIONS if a.status != NEEDS_MODEL]


# =========================================================================
# 参数校验（自带，不引入 jsonschema）
# =========================================================================

_TYPES = {"string": str, "number": (int, float), "integer": int,
          "boolean": bool, "array": list, "object": dict}


def validate(schema: dict, params: dict, where: str = "") -> None:
    for k in schema.get("required", []):
        if k not in params:
            raise ToolError(f"{where}缺少必填参数 {k!r}")
    props = schema.get("properties", {})
    if schema.get("additionalProperties") is False:
        extra = set(params) - set(props)
        if extra:
            raise ToolError(f"{where}不认识的参数 {sorted(extra)}，"
                            f"可用的是 {sorted(props)}")
    for k, v in params.items():
        s = props.get(k)
        if not s or v is None:
            continue
        t = s.get("type")
        if t and not isinstance(v, _TYPES[t]):
            raise ToolError(f"{where}{k} 应为 {t}，收到 {type(v).__name__}")
        if t == "integer" and isinstance(v, bool):
            raise ToolError(f"{where}{k} 应为 integer，收到 bool")
        if "enum" in s and v not in s["enum"]:
            raise ToolError(f"{where}{k} 只能是 {s['enum']} 之一，收到 {v!r}")
        if "minimum" in s and v < s["minimum"]:
            raise ToolError(f"{where}{k} 不能小于 {s['minimum']}，收到 {v}")
        if "maximum" in s and v > s["maximum"]:
            raise ToolError(f"{where}{k} 不能大于 {s['maximum']}，收到 {v}")
        if t == "array":
            if len(v) < s.get("minItems", 0):
                raise ToolError(f"{where}{k} 至少要 {s['minItems']} 项")
            for i, item in enumerate(v):
                validate({"properties": {f"{k}[{i}]": s["items"]}},
                         {f"{k}[{i}]": item}, where)


# =========================================================================
# 执行器
# =========================================================================

@dataclass
class ToolResult:
    ok: bool
    action: str
    params: dict
    elapsed_s: float = 0.0
    error: str = ""
    metrics_before: dict = field(default_factory=dict)
    metrics_after: dict = field(default_factory=dict)
    delta: dict = field(default_factory=dict)
    hooks: list[HookResult] = field(default_factory=list)
    node: str | None = None
    changed_files: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    @property
    def hooks_ok(self) -> bool:
        return all(h.ok for h in self.hooks)

    def to_json(self) -> dict:
        """**回灌给模型的就是这个。** 带数字，不只是「成功/失败」。"""
        return {
            "ok": self.ok, "action": self.action, "params": self.params,
            "error": self.error, "elapsed_s": round(self.elapsed_s, 1),
            "delta": self.delta,
            "hooks": [{"name": h.name, "ok": h.ok, "detail": h.detail,
                       **h.numbers} for h in self.hooks],
            "node": self.node,
            "changed_files": [Path(f).name for f in self.changed_files],
            **self.extra,
        }

    def report(self) -> str:
        out = [f"{'✓' if self.ok else '✗'} {self.action}"
               f"　{self.elapsed_s:.1f}s"
               + (f"　节点 {self.node}" if self.node else "")]
        if self.error:
            out.append(f"    ✗ {self.error}")
        for k, v in self.delta.items():
            if "change" in v:
                out.append(f"    {k}　{v['before']} → {v['after']}"
                           f"（{v['change']:+g}）")
            else:
                out.append(f"    {k}　{v['before']} → {v['after']}")
        for h in self.hooks:
            out.append(f"    {'✓' if h.ok else '✗'} 钩子 {h.name}　{h.detail}")
        if not self.delta and self.ok and not self.hooks:
            out.append("    （只读动作，没有改动）")
        return "\n".join(out)


@dataclass
class Runner:
    """执行一个动作，序列固定不变。"""

    proj: PJ.SongProject
    budget: BD.Budget | None = None
    deep_metrics: bool = True

    def _guard(self) -> SW.Guard:
        return SW.Guard(self.proj.agent_dir / "ledger.json")

    def run(self, name: str, params: dict | None = None) -> ToolResult:
        params = dict(params or {})
        act = BY_NAME.get(name)
        if act is None:
            raise ToolError(f"没有叫 {name!r} 的动作。可用：{sorted(BY_NAME)}")
        validate(act.schema, params, where=f"{name}: ")
        if self.budget is not None:
            self.budget.check()             # 只在动作之间退出

        res = ToolResult(ok=False, action=name, params=params)
        t0 = time.monotonic()
        tree = TR.Tree(self.proj)

        # ---- 写前：哈希校验 + 备份 -----------------------------------
        if act.writes:
            for f in self.proj.sources:
                if self._guard().verify(f) == SW.EXTERNAL:
                    res.error = (f"{f.name} 在我上次写入之后被外部改过。"
                                 f"先跑 safety.py --adopt 或 --restore")
                    res.elapsed_s = time.monotonic() - t0
                    return res
            # **每个动作之前树上必须有一个可回退的节点**
            if tree.head() is None:
                tree.commit(f"{name} 之前的基线", action="autosave")
            elif tree.is_dirty():
                tree.commit(f"{name} 之前的未提交改动", action="autosave")

        res.metrics_before = measure(self.proj, deep=self.deep_metrics)
        fp_before = {str(f): SW.fingerprint(f) for f in self.proj.sources}

        # ---- 执行 ---------------------------------------------------
        try:
            res.extra = act.run(self.proj, params) or {}
            res.ok = True
        except ToolError as e:
            res.error = str(e)
        except Exception as e:
            res.error = f"{type(e).__name__}: {e}"

        # ---- 写后：文件真的变了就必然跑钩子 ---------------------------
        fp_after = {str(f): SW.fingerprint(f) for f in self.proj.sources}
        res.changed_files = [k for k in fp_after if fp_before.get(k) != fp_after[k]]
        if res.changed_files:
            for h in act.hooks or ("state",):
                res.hooks.append(HOOKS[h](self.proj))
            for f in self.proj.sources:
                if f.exists():
                    self._guard().record(f)
            label = f"{name}" + (f"（失败后仍有改动）" if not res.ok else "")
            nd = tree.commit(label, action=name, params=params,
                             metrics_before=res.metrics_before)
            res.node = nd.id

        res.metrics_after = measure(self.proj, deep=self.deep_metrics)
        res.delta = delta_of(res.metrics_before, res.metrics_after)
        res.elapsed_s = time.monotonic() - t0
        if res.ok and self.budget is not None:
            self.budget.spend()
        return res
