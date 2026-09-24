# M0-06 · 所谓「512 音符限制」

| | |
|---|---|
| 对应 | PRD §14「所谓 512 音符限制 · 验证这个限制属于哪个桥接版本或接口」 |
| 日期 | 2026-09-24 |
| 结论 | **绿。** 512 是**上游桥（SynthV Agent Bridge 0.3.1）自己定的「每次调用最多 512 条」**，不是 SynthV 的限制。v2 直接写 `.svp` 就碰不到；真要走桥，桥自己的说明是每次 **≤ 60 条**才安全 |

---

## 证据

来源：本机的上游仓库 `E:\SV_MCP`，版本 **v0.3.1**（提交 `5c51bd9`）。只读，没有改动。

| 位置 | 原文 |
|---|---|
| `src/score-import.ts:19` | `const MAX_IMPORTED_SCORE_NOTES = 512;` |
| `src/server.ts:460` | 同上 |
| `src/server.ts` 多处 | 工具参数写成 `z.array(...).max(512)`：加音符、改音素等 |
| `src/server.ts:1816` | 乐谱导入工具的说明：*…more than 512 notes… are rejected before any project write* |
| `src/server.ts:1973` | *The SynthV host is fragile with large note batches: keep each call at or below 60 items… **The 512 ceiling is a protocol bound, not a safe batch size.*** |

最后一行是关键：**连桥的作者都说 512 只是协议上限，不是安全的批量。**

---

## 这对我们意味着什么

```
  v2 直接写 .svp（M0-04）        没有这个限制 —— 一首歌几百个音一次写完
  以后要走桥（在 SynthV 里实时改）  每次 ≤ 60 条，分批
```

---

## 没查的

| 没查 | 为什么可以先不查 |
|---|---|
| 上游的最新版本 | 本机是 0.3.1，上游还在更新，限制可能变了。**走桥的时候再查** |
| 「60 条」这个数 | 是桥作者的经验值，我们没实测。同上，走桥时再验 |
| SynthV 本身对一个音符组的音符数有没有上限 | 一首歌一条轨通常几百个音；直写 `.svp` 的整曲规模在 M0-04 之后验 |
