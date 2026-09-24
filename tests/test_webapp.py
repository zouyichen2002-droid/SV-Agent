# -*- coding: utf-8 -*-
"""可交互桌面程序的验收。

## 这一层的风险和别处不一样

仪表盘写错了，最坏是**看到一个错数字**。
这个程序写错了，最坏是**点一下就把创作者的工程改了**，
而且他可能正开着 FL 和 SynthV。

所以判据的重心不在渲染，在三条线：

1. **写动作没有 confirm 绝不能跑** —— 而且要证明它**没碰文件**，
   不是只看返回值说「我拒绝了」。自证清白不算数，这项目栽过
   （`reorchestrate` 的自检曾经结构性打不响）。
2. **前端只渲染不计算** —— 用 grep 盯住源码，别让第二个实现长出来。
   两个实现算同一件事，迟早算出两个不同的数**而且两边都不报错**。
3. **没有语料时分位是 `None`，不是 0** —— 三色纪律的灰档。
   0 的意思是「垫底」，`None` 的意思是「没依据」，差得远。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "toolkit"))

from svagent import webapp as W                   # noqa: E402
from svagent import project as PJ              # noqa: E402


# =========================================================================
# 一、写动作的护栏
# =========================================================================

def _fingerprint(slug: str) -> dict[str, tuple[int, float]]:
    """歌目录下每个文件的 (大小, mtime)。**用值不用数量** ——
    只数文件个数的话，原地改写一个文件是看不出来的。"""
    d = ROOT / "songs" / slug
    return {str(p.relative_to(d)): (p.stat().st_size, p.stat().st_mtime)
            for p in sorted(d.rglob("*")) if p.is_file()}


@pytest.fixture
def slug() -> str:
    for d in sorted((ROOT / "songs").iterdir()):
        if d.is_dir() and not d.name.startswith("_") \
                and (d / "project.json").exists():
            return d.name
    pytest.skip("songs/ 下没有工程")


def test_写动作没有confirm会被拒(slug):
    r = W.run_action(slug, "gen_melody", {}, confirm=False)
    assert r["ok"] is False
    assert r.get("need_confirm") is True


def test_被拒的写动作没有碰任何文件(slug):
    """**这一条才是真判据。** 上一条只验了它嘴上说拒绝。"""
    before = _fingerprint(slug)
    W.run_action(slug, "gen_melody", {}, confirm=False)
    assert _fingerprint(slug) == before


def test_所有写动作都受同一道闸(slug):
    """不能只有 `gen_melody` 被拦住 —— 逐个验，别让新动作漏网。"""
    from svagent.session import Session
    writes = [a.name for a in Session(slug).actions() if a.writes]
    assert writes, "一个写动作都没有？动作池读错了"
    for name in writes:
        r = W.run_action(slug, name, {}, confirm=False)
        assert r.get("need_confirm") is True, f"{name} 没被拦住"


def test_只读动作不需要confirm(slug):
    """闸门不能宽到把只读动作也拦下 —— 那样他会习惯性点确认。"""
    from svagent.session import Session
    ro = [a.name for a in Session(slug).actions() if not a.writes]
    assert ro, "一个只读动作都没有？"
    for name in ro:
        r = W.run_action(slug, name, {}, confirm=False)
        assert not r.get("need_confirm"), f"{name} 是只读的，不该要确认"


def test_不存在的动作被拒(slug):
    r = W.run_action(slug, "rm_rf", {}, confirm=True)
    assert r["ok"] is False and "没有" in r["error"]


# =========================================================================
# 二、前端只渲染，不计算
# =========================================================================

SRC = (ROOT / "toolkit" / "svagent" / "webapp.py").read_text(encoding="utf-8")


def test_webapp不自己算指标():
    """需要一个新数字就去库里加。

    这里盯的是 **import**：只要 `webapp` 没把算指标的模块拉进来，
    它就没法在自己这层重算一遍。
    """
    banned = ["from .agent import metrics", "from .compose",
              "from .agent import checks", "import librosa", "import numpy"]
    for b in banned:
        assert b not in SRC, f"webapp 不该 import {b!r} —— 前端只渲染不计算"


def test_webapp不读任何数据文件():
    """**一个都不读。** 数据要么从 `Session` 拿，要么从 `reference` 拿。

    盯的是**文件读取**本身。第一版这里用 `open\\(|json\\.load` 去数，
    结果把 `webbrowser.open(` 和解析请求体的 `json.loads` 一起数进来了 ——
    测的不是它声称的东西。所以这里只认「读了谁的正文」。

    第二版允许它读一个 `pop909_survey.json`。后来发现 `reference.py`
    才该是那个读取口 —— 两处各读各筛就是第二个实现。搬过去之后，
    这条就收紧成 0。
    """
    import re
    targets = re.findall(r'(\w+)\.read_text\(', SRC)
    assert targets == [], \
        f"webapp 读了这些文件：{targets}。数据应当从 Session / reference 拿"


def test_真歌分位和reference算的是同一个数():
    """一份分析，一处实现。**两边各算一遍迟早算出两个不同的数。**"""
    from svagent import reference as RF
    mine = W._REAL
    theirs = RF.values_of(RF.sane_rows(RF.load_survey()), "contour_line")
    assert mine == theirs


# =========================================================================
# 三、没有依据时是 None，不是 0
# =========================================================================

def test_没有值时分位是None():
    assert W.percentile_of(None) is None


def test_没有语料时分位是None(monkeypatch):
    """**0 的意思是垫底，None 的意思是没依据。** 这两个不能混。"""
    monkeypatch.setattr(W, "_REAL", [])
    assert W.percentile_of(3.0) is None


def test_语料在的时候分位是个数():
    if not W._REAL:
        pytest.skip("这台机器上没有 POP909 调查结果")
    p = W.percentile_of(W._REAL[len(W._REAL) // 2])
    assert 0.0 <= p <= 100.0


def test_分位单调不降():
    if len(W._REAL) < 10:
        pytest.skip("语料太少")
    a, b = W._REAL[0], W._REAL[-1]
    assert W.percentile_of(a) <= W.percentile_of(b)


def test_语料读不到不炸(tmp_path):
    """语料不在就返回空 —— **不编数，也不抛异常**。"""
    from svagent import reference as RF
    assert RF.load_survey(tmp_path / "不存在.json") == []


def test_语料是坏json也不炸(tmp_path):
    """半截文件、写坏的 json 都可能出现。**不能让整页打不开。**"""
    from svagent import reference as RF
    p = tmp_path / "坏.json"
    p.write_text("{不是合法 json", encoding="utf-8")
    assert RF.load_survey(p) == []
    p.write_text('{"不是":"列表"}', encoding="utf-8")
    assert RF.load_survey(p) == []


# =========================================================================
# 四、快照能上网
# =========================================================================

def test_快照能序列化(slug):
    """渲染前先过一遍 json —— 有个 Path 混进去就整页空白，而且不报错。"""
    d = W.snapshot(slug)
    json.dumps(d, ensure_ascii=False, default=str)


def test_快照带齐前端要的字段(slug):
    d = W.snapshot(slug)
    for k in ("slug", "title", "bpm", "state", "safety", "metrics",
              "findings", "actions", "tree", "real_song_n"):
        assert k in d, f"快照少了 {k}"
    assert d["state"]["steps"], "六步是空的"
    assert d["actions"], "动作池是空的"


def test_动作带着schema和status(slug):
    """前端按 `schema` 渲染表单、按 `status` 决定灰不灰 ——
    少一个就会出现「点下去才发现跑不了」。"""
    for a in W.snapshot(slug)["actions"]:
        assert "schema" in a and "status" in a and "writes" in a
        assert isinstance(a["schema"].get("properties", {}), dict)


def test_歌读不了也会被列出来():
    """静默跳过会让「怎么少了一首」查不出原因。"""
    names = [s["slug"] for s in W.songs()]
    on_disk = [d.name for d in (ROOT / "songs").iterdir()
               if d.is_dir() and not d.name.startswith("_")
               and (d / "project.json").exists()]
    assert sorted(names) == sorted(on_disk)


# =========================================================================
# 五、只听本机
# =========================================================================

def test_只绑127():
    """不是为了防外网，是为了不把「能改工程」的接口放到局域网上。"""
    assert '"127.0.0.1"' in SRC
    assert '"0.0.0.0"' not in SRC


def test_没有静态文件服务():
    """一行文件服务都没有，所以没有目录穿越这个面。"""
    assert "SimpleHTTPRequestHandler" not in SRC
    assert "translate_path" not in SRC


# =========================================================================
# 六、聊天框的写闸
#
# 按钮那条路每次写盘都弹框确认。聊天框没有这一步 ——
# 随手一句就可能触发写动作。所以它自带一道闸，默认关着。
#
# 这一节**不打真接口**（每分钟 4 次配额，且 key 是共用的）。
# 用注入的假模型，让它真的去调一个写动作，看拦不拦得住。
# =========================================================================

from svagent import llm as LM                    # noqa: E402
from svagent.agent import loop as LP             # noqa: E402
from svagent.agent import tools as TL            # noqa: E402

FAKE_KEY = "FAKEKEY000000000000000000000000"     # 纯虚构，与真 key 同格式


def _reply(content="", tool_calls=None):
    msg = {"content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return (200, {"x-ratelimit-limit-req-minute": "4",
                  "x-ratelimit-remaining-req-minute": "3"},
            {"choices": [{"message": msg}],
             "usage": {"prompt_tokens": 10, "completion_tokens": 5}})


def _call(name, args="{}"):
    return [{"id": "c1", "function": {"name": name, "arguments": args}}]


class _Fake:
    def __init__(self, *rs):
        self.rs = list(rs)

    def __call__(self, body):
        return self.rs.pop(0) if self.rs else _reply("完了")


def _fake_client(*rs):
    c = LM.Mistral(key=FAKE_KEY, transport=_Fake(*rs))
    c.sleep = lambda *_: None
    return c


def test_只读模式下工具表里没有写动作():
    ro = [t["function"]["name"] for t in TL.to_mistral_tools(writes=False)]
    full = [t["function"]["name"] for t in TL.to_mistral_tools()]
    assert ro, "只读工具一个都没有？"
    assert set(ro) < set(full)
    for n in ro:
        assert not TL.BY_NAME[n].writes, f"{n} 会写文件，不该出现在只读表里"


def test_不认识的动作名按会写处理():
    """打错一个字就绕过闸 —— 这是最容易出的那种安静错误。"""
    assert LP._writes("根本不存在") is True
    assert LP._writes("") is True


def test_模型真去调写动作会被拦住(slug):
    """**这一条才是闸。** 工具表少导出只是提示，模型照样能喊表外的名字。

    所以这里故意让假模型去调 `gen_melody`（它不在只读表里），
    然后验两件事：步骤标了 blocked，**而且文件指纹一个字节没动**。
    """
    from svagent.session import Session
    before = _fingerprint(slug)
    r = LP.run(Session(slug), "重做旋律",
               client=_fake_client(_reply("", _call("gen_melody")),
                                   _reply("拦住了")),
               allow_writes=False)
    blocked = [st for st in r.steps
               if st.result and st.result.get("blocked")]
    assert blocked, f"没拦住：{[(s.kind, s.action, s.error) for s in r.steps]}"
    assert _fingerprint(slug) == before, "闸报告拦住了，但文件被改了"


def test_允许写的时候闸不挡路(slug):
    """闸不能宽到把只读动作也拦下，也不能窄到默认就放行。"""
    from svagent.session import Session
    r = LP.run(Session(slug), "验一下对齐",
               client=_fake_client(_reply("", _call("verify_alignment")),
                                   _reply("验完了")),
               allow_writes=False)
    blocked = [st for st in r.steps
               if st.result and st.result.get("blocked")]
    assert not blocked, "verify_alignment 是只读的，不该被拦"


def test_ask默认不给写权限():
    """**默认值就是判据。** 默认给了写权限，等于确认闸白建。"""
    import inspect
    sig = inspect.signature(W.ask)
    src = inspect.getsource(W._Handler.do_POST)
    assert "allow_writes" in src
    assert "bool(b.get(\"allow_writes\"))" in src, \
        "没传就该是 False —— 用 bool(get()) 拿，别用 get(..., True)"
    assert "allow_writes" in sig.parameters


def test_聊天返回里没有key():
    """仓库是公开的，而这把 key 是共用的、不能轮换。"""
    import inspect
    src = inspect.getsource(W.ask)
    for bad in ("api_key", "MISTRAL_API_KEY", ".key"):
        assert bad not in src, f"ask() 里出现了 {bad!r}"


# =========================================================================
# 七、开一首新歌
#
# 这是「一句话 → 一首歌」的第一步，之前哪儿都没有入口 ——
# 不在动作池、不在 sv.py、不在程序里，只能让 agent 代跑。
# =========================================================================

def test_中文标题能出目录名():
    assert PJ.slugify("末班") == "moban"
    assert PJ.slugify("海风记事") == "haifengjishi"
    assert PJ.slugify("Hello World") == "helloworld"


def test_目录名不会是空的():
    """全是标点的标题也得有个能建目录的名字。"""
    for t in ("？？？", "——", "  "):
        s = PJ.slugify(t)
        assert s and s.isascii() and s.isalnum(), f"{t!r} → {s!r}"


def test_撞名直接拒绝不追加序号(slug):
    """悄悄建成 `moban2` 的话，`SVAGENT_SONG=moban` 会跑到旧的那首上，
    **而且哪儿都不报错**。"""
    with pytest.raises(FileExistsError):
        PJ.new_song("随便什么", slug=slug)


def test_目录名不能穿越目录():
    for bad in ("../坏", "a/b", "带空格 的"):
        with pytest.raises(ValueError):
            PJ.new_song("测试", slug=bad)


def test_空标题被拒():
    with pytest.raises(ValueError):
        PJ.new_song("   ")


def test_离谱的速度被拒():
    for bad in (0, 12, 500):
        with pytest.raises(ValueError):
            PJ.new_song("测试速度", slug="ceshisudu", bpm=bad)


def test_不给速度就按真歌分布取(tmp_path):
    """**不写死一个默认值。** 每首新歌同一个速度，
    是「怎么一直是那几首歌的感觉」的来源之一。"""
    import random
    from svagent import reference as RF
    r = random.Random(0)
    got = {RF.pick_bpm(r) for _ in range(30)}
    assert len(got) > 5, f"取出来的速度只有 {len(got)} 种：{got}"
    assert all(40 <= b <= 200 for b in got)


def test_没语料时速度退回有出处的数():
    """退回值是 909 首的中位（74），**出处写在 docstring 里**，
    不是凭感觉拍的。"""
    from svagent import reference as RF
    assert RF.pick_bpm(rows=[]) == 74.0


def test_新歌真能建起来并且能被读到(tmp_path, monkeypatch):
    """建完要能被 `songs()` 看见、能出快照 —— 否则等于没建。

    **建在临时目录**，不往 `songs/` 里塞垃圾。
    """
    from svagent import reference as RF
    monkeypatch.setattr(PJ, "SONGS", tmp_path)
    p = PJ.new_song("临时测试歌", theme="一句话主题", bpm=95)
    assert p.slug == "linshiceshige"
    assert p.bpm == 95.0
    cfg = tmp_path / "linshiceshige" / "project.json"
    assert cfg.exists()
    ly = tmp_path / "linshiceshige" / "lyrics.txt"
    assert ly.exists(), "歌词骨架没建 —— 创作者会不知道该往哪写"
    assert "临时测试歌" in ly.read_text(encoding="utf-8-sig")


def test_新歌不需要先在SynthV里建工程():
    """`scaffold` 的文档说「svp 由创作者在 SynthV 里建」——**那句是旧的**。

    第 ③ 步 `step3_melody` 从模板整份写出来（`Builder.save(force=True)`），
    所以创作者不用先建。这条钉住的是「模板这条路还在」。
    """
    assert PJ.TEMPLATE.exists(), f"模板不见了：{PJ.TEMPLATE}"
    src = (ROOT / "scripts" / "step3_melody.py").read_text(encoding="utf-8")
    assert "load_template(TEMPLATE)" in src
    assert "force=True" in src


# =========================================================================
# 八、新歌的第一次必须走得通
#
# 2026-09-18 创作者建了《清晨与海风》，点 gen_melody 得到：
#   FileNotFoundError: [Errno 2] No such file or directory: '…清晨与海风.svp'
#
# 两个毛病叠在一起，而且都属于**「最正常的情况」崩得最难看**这一类：
#   1. `.svp` 没人建 —— scaffold 不建，能建它的 step3 在被调到之前就崩了
#   2. 崩出来的是裸异常，不是一句能照着做的话
#
# 这一节钉住修好的三处，防止回归。
# =========================================================================

def test_没有svp会从模板建一份(tmp_path, monkeypatch):
    monkeypatch.setattr(PJ, "SONGS", tmp_path)
    p = PJ.new_song("测试建文件", bpm=88)
    assert p.svp.exists(), "新歌建完 .svp 还是不在 —— 第一次做旋律就会崩"
    assert p.svp.stat().st_size == PJ.TEMPLATE.stat().st_size


def test_已有的svp一个字节都不碰(tmp_path, monkeypatch):
    """创作者可能正开着 SynthV 编辑它。**这条是硬的。**"""
    monkeypatch.setattr(PJ, "SONGS", tmp_path)
    p = PJ.new_song("测试不覆盖", bpm=88)
    p.svp.write_bytes(b"creator's own bytes")
    assert PJ.ensure_svp(p) is None, "已经有文件了还报「建了」"
    assert p.svp.read_bytes() == b"creator's own bytes"


def test_建出来的空工程能被读回来(tmp_path, monkeypatch):
    """拷过去打不开等于没建。**模板是从真 SynthV 存出来的**，所以照抄；
    自己拼 JSON 只能赌 SynthV 认。"""
    from svagent import svp_build as SB
    monkeypatch.setattr(PJ, "SONGS", tmp_path)
    p = PJ.new_song("测试能读", bpm=88)
    back = SB.read_back(p.svp)
    assert back, "读回来是空的"
    assert all(len(v) == 0 for v in back.values()), "空工程里居然有音符"


def test_模板丢了会明确报出来(tmp_path, monkeypatch):
    """丢了得重新从 SynthV 存一份 —— **不能自己拼**，所以要报清楚。"""
    monkeypatch.setattr(PJ, "SONGS", tmp_path)
    monkeypatch.setattr(PJ, "TEMPLATE", tmp_path / "没有这个模板.svp")
    with pytest.raises(FileNotFoundError, match="模板不在"):
        PJ.new_song("测试模板丢了", bpm=88)


def test_gen_melody容得下缺文件():
    """`read_back` 抛的是 `FileNotFoundError`，不是 `ToolError`。

    第一版只 `except ToolError`，于是新歌第一次做旋律直接崩。
    """
    import inspect
    src = inspect.getsource(TL._a_gen_melody)
    assert "ensure_svp" in src, "gen_melody 不会自己建文件"
    assert "FileNotFoundError" in src, \
        "只接 ToolError 的话，缺文件仍然会崩成裸异常"


def test_空歌词报的是人话不是StopIteration(tmp_path):
    """「词还没写」是新歌的必经状态。

    第一版 `parse()` 对占位歌词返回 `({}, [])` —— 既没版本也没问题，
    于是 step3 的 `vs[next(iter(vs))]` 抛 `StopIteration`。
    """
    from svagent.compose.lyricfile import parse
    p = tmp_path / "lyrics.txt"
    p.write_text("# 某首歌\n\n（歌词待写）\n", encoding="utf-8-sig")
    vs, probs = parse(p)
    assert not vs
    assert probs, "0 版本 0 问题 —— 调用方只能崩"
    assert "没有一段歌词" in probs[0].why
    assert "lyrics.txt" in probs[0].why or "banjia" in probs[0].why, \
        "得告诉他照哪个文件抄"


def test_正常歌词不会被误报(tmp_path):
    """新加的判定不能把好文件也判成有问题。"""
    from svagent.compose.lyricfile import parse
    vs, probs = parse(ROOT / "songs" / "banjia" / "lyrics.txt")
    assert vs and not probs, f"《搬家那天》被误报：{[str(x) for x in probs]}"


# =========================================================================
# 九、和弦的真相来源是歌词那一列
#
# 2026-09-18 端到端跑《我爱你》时暴露的。因果链：
#
#   step3 的 `vary_progression` 把和弦进行变过，用来撑开候选池。
#   候选自检（`Cand.findings`）是拿**自己变过的进行**验的 → 0 finding。
#   但下游两处都从**歌词那一列**读和弦：
#       agent/state.py  `check_melody` → `read_lead(..., ver, ...)`
#       step4_accompaniment.py:105     → 同一个 `read_lead`
#   于是写进工程的旋律按一套和弦写、伴奏按另一套弹。
#
# 表现：gen_melody 的钩子说 0 finding，创作者点下一步才蹦出 7 个 ——
# 而且看起来像旋律有毛病。**它是真的会难听，不是记账问题。**
#
# 顺带查出来：挑候选那一行是死代码。原来按「跟《宇宙无边无垠》最不像」挑，
# 而 `melody_v2` 在 `out/` 下不在 sys.path 上，import 一直失败，
# 实际行为是 `usable[0]` —— 取第一个，根本没在挑。
# 「加大候选数反而 finding 变多」就是这么来的。
# =========================================================================

S3_SRC = (ROOT / "scripts" / "step3_melody.py").read_text(encoding="utf-8")


def test_挑候选时要求和弦跟歌词一致():
    assert "c.prog == base_prog" in S3_SRC, \
        "挑候选没有按「和弦跟歌词一致」过滤 —— 旋律和伴奏会对不上"


def test_不一致时会大声说出来():
    """退回去用变过进行的那版是允许的，**但必须报**。

    静默用掉它，创作者看到的是「旋律 0 finding」然后下一步蹦出一堆。
    """
    i = S3_SRC.find("c.prog == base_prog")
    tail = S3_SRC[i:i + 1200]
    assert "⚠" in tail, "不一致的分支没有警告"
    assert "伴奏" in tail, "警告里没说清后果（旋律和伴奏会对不上）"


def test_不再拿自己的旧歌挑候选():
    """创作者原话：「不要任何之前做的歌进入经验和记忆」。"""
    for bad in ("melody_v2", "宇宙无边无垠"):
        assert f"import {bad}" not in S3_SRC
        assert f"Fingerprint.of(\"{bad}\"" not in S3_SRC
    # 只剩注释里提它（记因果链），代码里不能再有 refs 这个变量
    assert "if refs:" not in S3_SRC
    assert "refs.append" not in S3_SRC


def test_歌词的和弦列和伴奏用的是同一个读法():
    """一份分析，一处实现。两处各读一遍，迟早读出两套和弦。"""
    st = (ROOT / "toolkit" / "svagent" / "agent" / "state.py").read_text(
        encoding="utf-8")
    s4 = (ROOT / "scripts" / "step4_accompaniment.py").read_text(
        encoding="utf-8")
    assert "read_lead(" in st and "read_lead(" in s4, \
        "两边不再走同一个 read_lead —— 和弦来源可能分叉了"


def test_第四步的提示不再叫创作者配器():
    """ADR-0013 之后配器由 `build_flp` 做。留着旧话会让他以为还要自己挂音源。

    盯源码写了两版都盯错地方：第一版抓到「等步骤 3 的主旋律」，
    第二版被我写在注释里的那句旧话绊住（注释里引用旧话是**故意的**，
    那是因果链记录）。**所以改成测行为** —— 真去拿一次 blocker 来看。
    """
    from svagent.agent.state import inspect as st_inspect
    # 找一首「有 acc_flp、还没有 wav」的歌 —— 正是这句提示要出现的场景
    for d in sorted((ROOT / "songs").iterdir()):
        if not d.is_dir() or not (d / "project.json").exists():
            continue
        p = PJ.load(d.name)
        if p.acc_flp.exists() and not p.wav.exists():
            s4 = st_inspect(p).steps[3]
            assert s4.blockers, f"{d.name} 的第 4 步没有 blocker"
            txt = " ".join(s4.blockers)
            assert "不用配器" in txt, f"提示里没说「不用配器」：{txt}"
            assert "配器并导出" not in txt, f"旧话还在：{txt}"
            return
    pytest.skip("没有「已出 flp、未导 wav」的歌可验")


def test_新歌会自动接上FL模板(tmp_path, monkeypatch):
    """`build_flp` 的前提是一份挂好音源的工程。新歌的 project.json 里
    没有 flp 字段 —— 那是**必经状态**，不是错误。"""
    real = PJ.default_flp()
    if real is None:
        pytest.skip("这台机器上没有可推的 FL 模板")
    monkeypatch.setattr(PJ, "SONGS", tmp_path)
    # 临时目录里推不出模板，所以先手动喂一首
    (tmp_path / "seed").mkdir()
    (tmp_path / "seed" / "project.json").write_text(
        json.dumps({"title": "种子", "svp": str(tmp_path / "seed" / "a.svp"),
                    "bpm": 72, "flp": str(real)}, ensure_ascii=False),
        encoding="utf-8")
    assert PJ.default_flp() == real
    p = PJ.new_song("测试接模板", bpm=72)
    assert p.flp == real, "新歌没接上共用模板 —— 第 ④ 步会停住"


def test_接过模板就不再改(tmp_path, monkeypatch):
    """创作者可能故意给某首歌换了模板。"""
    monkeypatch.setattr(PJ, "SONGS", tmp_path)
    (tmp_path / "s1").mkdir()
    (tmp_path / "s1" / "project.json").write_text(
        json.dumps({"title": "一", "svp": str(tmp_path / "s1" / "a.svp"),
                    "bpm": 72, "flp": "C:/他自己挑的.flp"}, ensure_ascii=False),
        encoding="utf-8")
    p = PJ.load("s1")
    assert PJ.ensure_flp(p) is None
    assert str(p.flp) == str(Path("C:/他自己挑的.flp"))


# =========================================================================
# 十、SystemExit 打死服务线程
#
# 2026-09-18 按创作者要求「全程只聊天」跑《海边的雨》时撞上的。
# 这是本项目「安静错误」清单的教科书案例，而且**命中每一首新歌**。
#
#   scripts/step3_melody.read_lead  没有主旋律轨时 raise SystemExit
#                                   （在命令行里是对的：退出码）
#   但它有 9 个调用点，两个在库里：
#       agent/state.check_melody
#       agent/metrics._lead
#
#   SystemExit 继承 **BaseException 不是 Exception** →
#   那些 `except Exception` 全部**写了却结构性打不响**
#   → 一路穿到 HTTP 处理线程 → 线程死掉、**连响应都不发**
#   → 创作者看到「✗ Failed to fetch」，HTTP 000，零解释
#
# 触发条件：**歌词有效 + 还没有旋律** —— set_lyrics 之后、
# gen_melody 之前，每首歌的必经状态。
#
# 我之前只在「已经有旋律」的歌上试过快照，所以没发现。
# =========================================================================

def test_read_lead抛的不是SystemExit(tmp_path):
    """根因修在源头：一处改，9 个调用点的防护一起开始生效。"""
    import sys as _s
    _s.path.insert(0, str(ROOT / "scripts"))
    import step3_melody as S3
    assert issubclass(S3.NoLead, Exception), \
        "NoLead 必须是 Exception —— BaseException 会穿过所有 except Exception"
    assert not issubclass(S3.NoLead, SystemExit)
    src = (ROOT / "scripts" / "step3_melody.py").read_text(encoding="utf-8")
    body = src[src.index("def read_lead("):src.index("def sections_from(")]
    assert "raise SystemExit" not in body, "read_lead 又开始 raise SystemExit 了"


def test_没有旋律的歌快照能出来():
    """**每首新歌的必经状态。** 原来这里整页 HTTP 000。"""
    for d in sorted((ROOT / "songs").iterdir()):
        if not d.is_dir() or not (d / "project.json").exists():
            continue
        p = PJ.load(d.name)
        if p.svp.exists() and not _has_lead(p.svp):
            snap = W.snapshot(d.name)          # 不抛就算过
            assert snap["state"]["steps"]
            # 检查跑不了要**说出来**，不能假装 0 finding
            assert snap["checks_error"] or snap["findings"] == [], \
                "没有旋律却报出了 finding？"
            if snap["checks_error"]:
                assert "NoLead" in snap["checks_error"] \
                    or "LyricsEmpty" in snap["checks_error"], \
                    f"错误类型不对：{snap['checks_error']}"
            return
    pytest.skip("没有「有工程、无主旋律」的歌可验")


def _has_lead(svp) -> bool:
    try:
        d = json.loads(svp.read_text(encoding="utf-8-sig"))
    except Exception:
        return False
    return any(str(t.get("name", "")).startswith("主旋律")
               for t in (d.get("tracks") or []))


def test_没有旋律时指标是灰档不是零():
    """`None` = 没依据，`0` = 很平。**这两个不能混。**"""
    from svagent.agent import metrics as MT
    for d in sorted((ROOT / "songs").iterdir()):
        if not d.is_dir() or not (d / "project.json").exists():
            continue
        p = PJ.load(d.name)
        if p.svp.exists() and not _has_lead(p.svp):
            for m in MT.contour(p):
                assert m.value is None, f"{m.name} 报了 {m.value}，应当是 None"
                assert m.ok is None, f"{m.name} 的 ok 是 {m.ok}，应当是 None"
            return
    pytest.skip("没有可验的歌")


def test_HTTP层接住SystemExit():
    """库里还有别的地方 `raise SystemExit`（`project.load` 找不到歌）。

    **服务器必须永远回一句话。** 这条不接 `BaseException` ——
    那会连 Ctrl-C 一起吞掉。
    """
    assert SRC.count("except SystemExit") >= 3, \
        "GET / POST / 动作三处都要接住"
    assert "except BaseException" not in SRC, \
        "不许接 BaseException —— 会吞掉 Ctrl-C"


def test_歌词空的时候报人话不报StopIteration():
    """六处裸的 `vs[next(iter(vs))]` 收成一个入口。

    `StopIteration` 是个**没有消息**的异常，界面上只显示 `StopIteration:`
    后面什么都没有。
    """
    from svagent.compose import lyricfile as LF
    with pytest.raises(LF.LyricsEmpty, match="还没有任何一段"):
        LF.first_version({}, "x/lyrics.txt")
    assert LF.first_version({"A": "ver"}) == "ver"
    # 盯的是**没有守卫**的那种写法。`vs[next(iter(vs))] if vs else None`
    # 是安全的 —— `_a_gen_lyrics` 就这么写，而且它靠那个分支走新歌骨架。
    bare = "vs[next(iter(vs))]"
    for f in ("toolkit/svagent/agent/state.py",
              "toolkit/svagent/agent/metrics.py",
              "toolkit/svagent/agent/tools.py",
              "scripts/step4_accompaniment.py",
              "scripts/step3_melody.py"):
        for ln in (ROOT / f).read_text(encoding="utf-8").splitlines():
            if bare in ln and "if vs" not in ln:
                raise AssertionError(
                    f"{f} 有裸的 next(iter(vs))，歌词空时抛 StopIteration：{ln.strip()}")


# =========================================================================
# 十一、聊天能不能自己开歌、自己写词
#
# 创作者的要求：「用户全程只需要和 agent 聊天和导出 fl 文件」。
# 聊天只能碰到动作池，而池子里原来**既没有「开新歌」也没有「写词」** ——
# 实测模型的回答是「手动创建文件夹」。
# =========================================================================

def test_动作池里有开新歌和写词(slug):
    from svagent.session import Session
    names = {a.name for a in Session(slug).actions()}
    assert "new_song" in names, "聊天开不了新歌"
    assert "set_lyrics" in names, "聊天写不了词"


def test_写词之前先过解析器(slug, tmp_path, monkeypatch):
    """写坏了不会立刻报错 —— 下一步 gen_melody 才崩，
    而且崩的地方看起来像旋律的问题。"""
    from svagent.session import Session
    s = Session(slug)
    # **只看 lyrics.txt 本身。** 第一版这里比整个歌目录的指纹，
    # 结果被 `.agent/checkpoints`（执行器在动作前建的回退点）绊住 ——
    # 那是**正确行为**，不是副作用。测的不是它声称的东西。
    before = s.proj.lyrics.read_bytes()
    r = s.act("set_lyrics", {"text": "# 标题\n\n这不是歌词格式\n"})
    assert r.ok is False
    assert "没有写" in (r.error or ""), r.error
    assert s.proj.lyrics.read_bytes() == before, "拒了却动了歌词文件"
