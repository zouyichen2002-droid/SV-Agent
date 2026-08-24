# -*- coding: utf-8 -*-
"""仪表盘渲染的反向测试。

## 为什么需要它

《晓风残月》六步全绿，所以拿它生成仪表盘时，**阻塞、下一步、命令、
复制按钮这四条路径一次都不会被走到**。「看起来对」在这个项目里反复
等于「没被执行过」—— 声称注入 8 个缺陷实际只落地 6 个，就是这么来的。

所以这里造一个人工的混合状态：前两步完成、第三步卡住、后三步等它。
渲染出来必须能看见阻塞和命令。

## 这些断言对应验收标准里的哪一条

`specs/testing-and-acceptance.md` §2「检查会响（敏感度）」：
只报 0 的检查不算检查。仪表盘同理 —— 只会画全绿的仪表盘不算仪表盘。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "toolkit"))

from svagent import dashboard as D           # noqa: E402
from svagent import project as PJ            # noqa: E402
from svagent.agent import state as ST        # noqa: E402


def _mixed() -> ST.ProjectState:
    """人工构造：2 步完成 · 第 3 步卡住 · 后 3 步在等。"""
    proj = PJ.SongProject(
        slug="t_mixed", title="测试用歌",
        lyrics=Path("E:/tmp/lyrics.txt"), svp=Path("E:/tmp/x.svp"),
        bpm=66.0, form=[("主歌1", 8), ("副歌1", 8)],
        mid=Path("E:/tmp/x.mid"), wav=Path("E:/tmp/x.wav"),
    )
    steps = [
        ST.Step(1, "定题目", ST.BY_CREATOR, True, evidence=["工程 x.svp 存在"]),
        ST.Step(2, "定歌词", ST.BY_BOTH, True, evidence=["A｜测试　4 句 / 36 字"]),
        ST.Step(3, "定主旋律和和声", ST.BY_AGENT, False,
                evidence=["主旋律_G 小调　176 音符　同轨重叠 57"],
                blockers=["同轨重叠 57 处 —— SynthV 不允许，必须重生成"],
                command="SVAGENT_SONG=t_mixed python step3_melody.py --write"),
        ST.Step(4, "定伴奏", ST.BY_BOTH, False, blockers=["等步骤 3 的主旋律"],
                waits_for=3, command="不该出现的命令_4"),
        ST.Step(5, "伴奏进 SV + 调教", ST.BY_AGENT, False,
                blockers=["等步骤 4 的伴奏音频"], waits_for=4,
                command="不该出现的命令_5"),
        ST.Step(6, "混音", ST.BY_AGENT, False, blockers=["等步骤 5"],
                waits_for=5, command="不该出现的命令_6"),
    ]
    return ST.ProjectState(proj=proj, steps=steps)


@pytest.fixture(scope="module")
def html() -> str:
    return D.render(_mixed())


def test_进度必须来自库_而不是前端自己数():
    """**这条是「前端只渲染不计算」那条规则的唯一自动判据。**

    断言「渲染出 2/6」是抓不住违规的 —— 前端自己 `sum()` 一遍也是 2。
    所以让库说一个它自己绝对算不出来的数：前端照抄就对，自己算就露馅。
    （第一版这条测试写成断言输出值，变异测试当场发现它不会响。）
    """
    class 说谎的状态(ST.ProjectState):
        @property
        def n_done(self) -> int:
            return 99

    st = _mixed()
    assert st.n_done == 2
    assert "99/6 步" in D.render(说谎的状态(proj=st.proj, steps=st.steps))


def test_下一步是第一个未完成的步骤(html: str):
    assert "下一步：步骤 3" in html
    assert "下一步：步骤 4" not in html


def test_阻塞原因必须出现在页面上(html: str):
    assert "同轨重叠 57 处" in html
    assert "等步骤 3 的主旋律" in html
    assert 'class="blk"' in html               # 阻塞用的是专门的样式


def test_只有下一步给命令(html: str):
    """给六条命令会让创作者不知道该敲哪条 —— 只给下一步那条。"""
    assert "step3_melody.py --write" in html
    for n in (4, 5, 6):
        assert f"不该出现的命令_{n}" not in html
    assert html.count('class="copy"') == 1


def test_复制按钮存在(html: str):
    assert 'class="copy" type="button">复制<' in html


def test_只有下一步的卡片高亮(html: str):
    assert html.count('class="card next"') == 1


def test_六步全绿时不出现下一步也不出现命令():
    st = _mixed()
    for s in st.steps:
        s.done, s.blockers = True, []
    out = D.render(st)
    assert "六步全部完成" in out
    assert "6/6 步" in out
    assert 'class="copy"' not in out
    assert 'class="card next"' not in out


def test_未建造的面板只列名字():
    """画一个填着假数据的会话树，比没有会话树更糟。"""
    out = D.render(_mixed())
    assert "只列名字，不画假界面" in out
    for name, n, _d in D.PENDING_PANELS:
        assert f"第 {n} 项" in out and name in out


def test_歌名与证据要转义():
    """歌词和歌名是创作者写的自由文本，路径里全是反斜杠。"""
    st = _mixed()
    st.proj.title = '<script>alert(1)</script>&"'
    st.steps[2].evidence = ["<b>不该变粗</b>"]
    out = D.render(st)
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;" in out
    assert "<b>不该变粗</b>" not in out
    assert "&lt;b&gt;" in out


def test_自动刷新秒数会进页面():
    out = D.render(_mixed(), refresh_s=9)
    assert "每 9 秒自动刷新" in out
    assert "var MS=9000" in out


def test_渲染是纯函数_同状态两次结果只差时间戳():
    """可复现：同一个状态渲染两次，除了生成时间戳之外必须逐字节相同。"""
    import re
    st = _mixed()
    a = re.sub(r"生成于 \d\d:\d\d:\d\d", "", D.render(st))
    b = re.sub(r"生成于 \d\d:\d\d:\d\d", "", D.render(st))
    assert a == b


def test_被上游挡住和自己坏了必须画得不一样(html: str):
    """仪表盘建好当天暴露的第一个建模缺失：三个红叉让人以为三处出了问题。

    步骤 3 是真的坏了（同轨重叠 57），步骤 4/5/6 只是在排队。
    """
    st = _mixed()
    assert st.steps[2].mark == "✗" and st.steps[2].blocked_by_self
    for s in st.steps[3:]:
        assert s.mark == "…" and not s.blocked_by_self
    assert html.count('class="mark block"') == 1     # 只有一个红叉
    assert html.count('class="mark wait"') == 3      # 三个在等
    assert html.count('class="blk"') == 1            # 阻塞原因也要跟着分开
    assert html.count('class="waitblk"') == 3
