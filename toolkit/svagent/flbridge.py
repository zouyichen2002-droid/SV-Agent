"""驱动 flstudio-mcp 的客户端。复用 `bridge.Bridge` 的 stdio/JSON-RPC 传输。

## 为什么不注册到 Claude Desktop

上游 README 建议把服务写进 `%APPDATA%\\Claude\\claude_desktop_config.json`。
**我们不这么做**：SV 桥就是直接 spawn 进程的，同一套模式复用一次，
就不用改用户的应用配置（那是持久化配置，改坏了会影响他别的会话）。
实测 `mcpServers` 本来是空的 —— 说明这个项目从来没依赖过那条路。

## 实测的工具面（2026-08-22，fl-studio-mcp 0.3.0，67 个工具）

    混音/效果/插件  26      ← 它真正的强项，也是我做不了的部分
    查询            31
    写音符           5
    编排/图案        4
    MIDI 导出        1

## 能力边界：MCP 不能导入 MIDI，也不能挂音源

这是 **FL Studio 脚本 API 的硬限制**，不是 loopMIDI 缺失、也不是这个 MCP 的短板。
工具自己的说明原文：

    fl_plugin_list   "We cannot load NEW plugins (FL API limit)"
    fl_setup_chain   "FL can't load plugins -- add those manually"

67 个工具里**没有任何**打开工程 / 导入 MIDI / 新建 channel 的工具。
`fl_export_midi` 只写文件，说明里明说「不碰 FL」。

**所以这两件必须用户手动，任何 FL 的 MCP 都替不了：**

1. File → Import → MIDI file
2. 给每条导入的轨挂一个音源

MCP 的全部价值在音源挂好**之后**：音量/声像/路由/EQ/压缩/混响/增益结构、
`fl_diagnose_mix` 体检、`fl_take_snapshot` 快照与 `fl_rollback_last_change` 回滚。
这一层需要 loopMIDI。

**写音符不要走 MCP。** `fl_write_piano_roll_notes` 是通用的，但 note bridge
一次只能写一个 pattern，且要 loopMIDI + 钢琴卷帘里 arm 过 `MCP_Apply`，
音符走实时 MIDI 传输、没有 tick 保证。我们的伴奏是 5 声部 × 48 小节 × 9 段。
上游 `fl_export_midi` 的说明自己就写着「不碰 FL，文件你自己导入」——
所以伴奏走 `scripts/make_accompaniment.py` 生成的 `.mid`，见 ADR-0008。

## 前置条件（缺哪个 `preflight()` 会说清楚）

1. **loopMIDI** 里建两个端口，名字必须一字不差：`FLStudioMCP RX` / `FLStudioMCP TX`
   —— 这个装不了驱动级软件的事只能用户自己做
2. FL Studio → Options → MIDI Settings：RX 设为 input（controller type = FLStudioMCP），
   TX 设为 output，**两者 port 号相同**
3. FL Studio 正在运行，且 View → Script output 显示 `[FLStudioMCP] Ready`

用法:
    python -m svagent.flbridge          # 体检，报告缺什么
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from .bridge import Bridge, BridgeError

# 隔离的 Python 3.12 环境。主环境是 3.13，python-rtmidi 没有 cp313 wheel、
# 本机也没有 C++ 编译器，装不上 —— 所以 FL 桥只能跑在这个 env 里
FL_MCP_EXE = Path(r"G:\miniconda\envs\flmcp\Scripts\fl-studio-mcp.exe")
FL_MCP_REPO = Path(r"E:\FL_MCP")
REQUIRED_PORTS = ("FLStudioMCP RX", "FLStudioMCP TX")


# FL 的插件数据库。服务默认找不到（它找的是 .../Plugin database/Installed，
# 而本机是 .../Plugin database/{Generators,Effects}），所以显式指给它。
# 读这个目录**不需要 loopMIDI** —— 所以"基于用户实际装了什么来推荐音源"
# 这件事在端口建好之前就能做。
PLUGIN_DB = (Path.home() / "Documents" / "Image-Line" / "FL Studio"
             / "Presets" / "Plugin database")


def open_fl(timeout_s: float = 60.0, verbose: bool = False) -> Bridge:
    """起一个 FL 桥会话。用 with 语句。"""
    if not FL_MCP_EXE.exists():
        raise BridgeError(f"找不到 {FL_MCP_EXE}。先在 flmcp env 里 pip install -e E:/FL_MCP")
    import os
    if PLUGIN_DB.is_dir():
        os.environ["FLSTUDIO_MCP_PLUGIN_DB"] = str(PLUGIN_DB)   # 子进程继承
    return Bridge(argv=[str(FL_MCP_EXE)], cwd=FL_MCP_REPO,
                  client_name="SV-Agent/flbridge",
                  timeout_s=timeout_s, verbose=verbose)


def midi_ports() -> set[str]:
    """flmcp env 里可见的 MIDI 端口。主环境没有 rtmidi，得问那个 env。"""
    import subprocess
    py = FL_MCP_EXE.parent.parent / "python.exe"
    code = ("import mido,json;"
            "print(json.dumps(sorted(set(mido.get_output_names())"
            "|set(mido.get_input_names()))))")
    r = subprocess.run([str(py), "-c", code], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode:
        raise BridgeError(f"枚举 MIDI 端口失败: {r.stderr[-300:]}")
    import json
    return set(json.loads(r.stdout.strip().splitlines()[-1]))


def preflight() -> int:
    """逐条报告前置条件。缺什么就说缺什么，不含糊。"""
    sys.stdout.reconfigure(encoding="utf-8")
    ok = True

    print("=== FL 桥体检 ===\n")
    print(f"[1] MCP 可执行文件　{FL_MCP_EXE}")
    print(f"    {'✓ 存在' if FL_MCP_EXE.exists() else '✗ 缺失'}")
    ok &= FL_MCP_EXE.exists()

    hw = (Path.home() / "Documents" / "Image-Line" / "FL Studio" / "Settings"
          / "Hardware" / "FLStudioMCP" / "device_FLStudioMCP.py")
    print(f"\n[2] FL 控制器脚本　{hw}")
    print(f"    {'✓ 已安装' if hw.exists() else '✗ 未安装'}")
    ok &= hw.exists()

    apply_ = (Path.home() / "Documents" / "Image-Line" / "FL Studio" / "Settings"
              / "Piano roll scripts" / "MCP_Apply.pyscript")
    print(f"\n[3] note bridge 脚本　{apply_}")
    print(f"    {'✓ 已生成' if apply_.exists() else '✗ 未生成'}"
          "（只影响 MCP 写音符；伴奏走 MIDI 文件，不需要它）")

    print(f"\n[4] 虚拟 MIDI 端口（loopMIDI）")
    try:
        names = midi_ports()
        print(f"    当前可见: {sorted(names) or '（无）'}")
        missing = [n for n in REQUIRED_PORTS
                   if not any(n.lower() in x.lower() for x in names)]
        if missing:
            print(f"    ✗ 缺少 {missing}")
            print("      装 loopMIDI 后建这两个端口，名字必须一字不差：")
            for n in REQUIRED_PORTS:
                print(f"        {n}")
            print("      https://www.tobias-erichsen.de/software/loopmidi.html")
            ok = False
        else:
            print("    ✓ 两个端口都在")
    except BridgeError as e:
        print(f"    ✗ {e}")
        ok = False

    print(f"\n[5] MCP 服务能否 stdio 起来")
    try:
        with open_fl(timeout_s=40) as b:
            print(f"    ✓ {b.server_info}　工具 {len(b.list_tools())} 个")
            print(f"\n[6] FL Studio 是否在跑且控制器已加载（fl_ping）")
            try:
                # 两个坑，都踩过：
                # 1) fl_ping **不抛异常也可能失败** —— 结果在 alive 字段里。
                #    原来只捕异常，于是 alive=False 时体检照样打印「全部就绪」。
                # 2) **必须重试。** FL 的控制器脚本约每 0.5s 发一次心跳，
                #    而 MCP 是新起的进程、刚打开端口时手里没有任何心跳。
                #    开桥后立刻 ping 必然 alive=False —— 我因此误判用户配错了 FL，
                #    实际他一开始就配对了。这是本项目最典型的假阴性。
                r, alive = {}, False
                for attempt in range(6):
                    r = b.call("fl_ping")
                    alive = bool(r.get("alive")) if isinstance(r, dict) else False
                    if alive:
                        break
                    if attempt == 0:
                        print("    首次没有心跳（正常，端口刚打开），等待中...")
                    time.sleep(1.0)
                print(f"    {'✓' if alive else '✗'} alive={alive}"
                      f"（第 {attempt + 1} 次尝试）")
                if alive:
                    print(f"      {r}")
                else:
                    print(f"      {r.get('reason') if isinstance(r, dict) else r}")
                    print("      → FL → 选项 → MIDI 设置：")
                    print(f"        输入  {REQUIRED_PORTS[0]}：启用，"
                          "控制器类型 = FLStudioMCP，端口 = 42")
                    print(f"        输出  {REQUIRED_PORTS[1]}：启用，"
                          "端口 = 42（同一个数字）")
                    ok = False
            except BridgeError as e:
                print(f"    ✗ {str(e)[:220]}")
                ok = False
    except BridgeError as e:
        print(f"    ✗ {str(e)[:220]}")
        ok = False

    print("\n" + "=" * 60)
    print("✓ 全部就绪，可以让 MCP 做配器与混音" if ok
          else "✗ 还有缺项，见上。伴奏 MIDI 的导入不受影响 —— 那一步不需要桥")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(preflight())
