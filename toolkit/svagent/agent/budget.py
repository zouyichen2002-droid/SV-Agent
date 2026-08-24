# -*- coding: utf-8 -*-
"""建造顺序第 1 项的后两件：**可中断**与**循环超时**。

## 为什么它们也算「写入正确性」

因为中断和超时处理得糙，就会在写到一半的时候退出 —— 又变成半成品。
所以两者的实现约束是同一条：

    **只在两个动作之间退出，绝不在动作中间退出。**

`check()` 因此是显式调用的，不是定时器、不是信号处理器。循环在每个动作
**开始前**调一次；动作一旦开始就让它写完。这样最坏情况只是多花一个动作的
时间，而不是留下一个坏文件。

## 停止靠文件，不靠信号

创作者不写代码，也不会去发 SIGINT。他能做的是**建一个文件**（或者跟我说
一声，我建）。文件也是唯一能跨进程、跨会话可靠工作的方式 ——
和「L0 是唯一真相来源」同一条原则。

## 三种退出分开报

    Stopped       你喊停的        → 不是失败，不要当错误处理
    TimedOut      墙钟用完了      → §8 的 budget_s=300
    ActionLimit   动作数用完了    → §8 的 max_total_actions=8

混成一个「跑完了」，创作者就分不清「它做完了」和「它被掐了」。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

STOP_NAME = ".stop"


class BudgetExhausted(Exception):
    """预算类退出的共同基类。**不是 bug，是设计好的出口。**"""


class Stopped(BudgetExhausted):
    """创作者建了停止文件。"""


class TimedOut(BudgetExhausted):
    """墙钟预算用完。"""


class ActionLimit(BudgetExhausted):
    """动作数用完。"""


@dataclass
class Budget:
    """一轮的预算。默认值来自架构文档 §8。"""

    seconds: float = 300.0
    max_actions: int = 8
    stop_file: Path | None = None
    started: float = field(default_factory=time.monotonic)
    n_actions: int = 0

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started

    @property
    def remaining(self) -> float:
        return max(0.0, self.seconds - self.elapsed)

    @property
    def actions_left(self) -> int:
        return max(0, self.max_actions - self.n_actions)

    def stop_requested(self) -> bool:
        return bool(self.stop_file and Path(self.stop_file).exists())

    def check(self) -> None:
        """**在每个动作开始之前**调。三种情况分别抛不同的异常。

        顺序有意为之：先看创作者喊没喊停。他的意思优先于任何预算数字。
        """
        if self.stop_requested():
            raise Stopped(f"你建了 {self.stop_file} —— 这一轮到此为止，"
                          f"已完成 {self.n_actions} 个动作。")
        if self.remaining <= 0:
            raise TimedOut(f"墙钟预算 {self.seconds:.0f}s 用完，"
                           f"已完成 {self.n_actions} 个动作。")
        if self.actions_left <= 0:
            raise ActionLimit(f"动作数上限 {self.max_actions} 用完，"
                              f"耗时 {self.elapsed:.0f}s。")

    def spend(self, n: int = 1) -> None:
        """动作**做完之后**记账。做完才算，中途崩了不算。"""
        self.n_actions += n

    def clear_stop(self) -> bool:
        """收工时把停止文件清掉，免得下一轮一起手就被上一次的停止掐死。"""
        if self.stop_requested():
            Path(self.stop_file).unlink(missing_ok=True)
            return True
        return False

    def status(self) -> dict:
        """给仪表盘用。"""
        return {
            "elapsed": round(self.elapsed, 1),
            "remaining": round(self.remaining, 1),
            "seconds": self.seconds,
            "n_actions": self.n_actions,
            "max_actions": self.max_actions,
            "stop_requested": self.stop_requested(),
            "stop_file": str(self.stop_file) if self.stop_file else None,
        }
