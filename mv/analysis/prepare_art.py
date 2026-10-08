# -*- coding: utf-8 -*-
r"""给曲绘 PV 准备图（SV-Agent 10-04）：每张曲绘 → 人物层（透明底）+ 背景层（人物的位置用周围补上）+ 位置信息。
人物用动漫插画抠图模型（skytnt/anime-seg 的 isnetis.onnx，Apache-2.0；onnxruntime CPU 跑）。写到项目的 MV\art\（仓库外）：
    <id>_full.png   原图（最长边缩到 2560 以内）
    <id>_fg.png     人物层（RGBA，边缘羽化）
    <id>_bg.png     背景层（人物那块先放大一圈再用周围的颜色补，镜头一动不会看到两个人）
    <id>_check.png  检查用：原图上叠一层红色的人物范围
    art.json        每张：尺寸、人物外框、人物重心、人物占画面多少、字该放哪边（人物少的那边）
已经有透明底的图（png 有透明）直接当人物层，背景层留空。
用法（miniconda 的 Python，要 onnxruntime、opencv）：
    python prepare_art.py --project <项目文件夹> --src <曲绘文件夹> [--model <isnetis.onnx>]
"""
from __future__ import annotations

import argparse
import ctypes
import json
import pathlib
import sys

import cv2
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
MODEL = r"E:\sv-agent-data\models\anime-seg\isnetis.onnx"
MAXSIDE = 2560


def low_priority():
    try:
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
    except Exception:
        pass


def read_rgba(p: pathlib.Path) -> np.ndarray:
    data = np.fromfile(str(p), dtype=np.uint8)                       # 中文路径：cv2.imread 读不了
    im = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    if im is None:
        raise ValueError(f"读不了 {p.name}")
    if im.ndim == 2:
        im = cv2.cvtColor(im, cv2.COLOR_GRAY2BGRA)
    elif im.shape[2] == 3:
        im = cv2.cvtColor(im, cv2.COLOR_BGR2BGRA)
    s = MAXSIDE / max(im.shape[:2])
    if s < 1:
        im = cv2.resize(im, (round(im.shape[1] * s), round(im.shape[0] * s)), interpolation=cv2.INTER_AREA)
    return im


def write(p: pathlib.Path, im: np.ndarray):
    ok, buf = cv2.imencode(".png", im)
    if not ok:
        raise ValueError(f"写不了 {p}")
    buf.tofile(str(p))


def get_mask(sess, bgr: np.ndarray, s: int = 1024) -> np.ndarray:
    """照 anime-segmentation 的推理写法：RGB 0..1、等比缩进 s×s 居中补零 → 输出 0..1 的人物概率。"""
    img = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255
    h0, w0 = img.shape[:2]
    h, w = (s, int(s * w0 / h0)) if h0 > w0 else (int(s * h0 / w0), s)
    ph, pw = s - h, s - w
    inp = np.zeros([s, s, 3], dtype=np.float32)
    inp[ph // 2:ph // 2 + h, pw // 2:pw // 2 + w] = cv2.resize(img, (w, h))
    inp = np.transpose(inp, (2, 0, 1))[np.newaxis, :]
    name = sess.get_inputs()[0].name
    m = sess.run(None, {name: inp})[0][0]
    m = np.transpose(m, (1, 2, 0))[ph // 2:ph // 2 + h, pw // 2:pw // 2 + w]
    return np.clip(cv2.resize(m, (w0, h0)), 0, 1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--src", required=True)
    ap.add_argument("--model", default=MODEL)
    a = ap.parse_args()
    low_priority()
    proj, src = pathlib.Path(a.project), pathlib.Path(a.src)
    out = proj / "MV" / "art"
    out.mkdir(parents=True, exist_ok=True)
    files = sorted([p for p in src.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".bmp")], key=lambda p: p.name)
    if not files:
        print(f"{src} 里没有图")
        return 1
    import onnxruntime as rt
    sess = rt.InferenceSession(a.model, providers=["CPUExecutionProvider"])
    info = []
    for i, p in enumerate(files, 1):
        im = read_rgba(p)
        bgr, alpha = im[:, :, :3], im[:, :, 3]
        h, w = alpha.shape
        iid = f"q{i:02d}"
        has_alpha = alpha.min() < 250
        if has_alpha:
            mask = alpha.astype(np.float32) / 255
        else:
            mask = get_mask(sess, bgr)
        # 人物层：概率 → 收一点边、羽化
        m8 = (np.clip((mask - 0.35) / 0.3, 0, 1) * 255).astype(np.uint8)
        m8 = cv2.GaussianBlur(m8, (0, 0), 1.2)
        fg = np.dstack([bgr, m8 if not has_alpha else alpha])
        write(out / f"{iid}_full.png", im if has_alpha else np.dstack([bgr, np.full_like(alpha, 255)]))
        write(out / f"{iid}_fg.png", fg)
        # 背景层：人物范围放大一圈，用周围的颜色补（缩小了补再放大，快、也够用：背景只在人物后面露一点点）
        if not has_alpha:
            hole = (m8 > 20).astype(np.uint8) * 255
            hole = cv2.dilate(hole, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31)))
            k = 4
            small = cv2.resize(bgr, (w // k, h // k), interpolation=cv2.INTER_AREA)
            sh = cv2.resize(hole, (w // k, h // k), interpolation=cv2.INTER_NEAREST)
            fill = cv2.inpaint(small, sh, 9, cv2.INPAINT_TELEA)
            fill = cv2.GaussianBlur(cv2.resize(fill, (w, h), interpolation=cv2.INTER_CUBIC), (0, 0), 6)
            hm = cv2.GaussianBlur(hole, (0, 0), 8).astype(np.float32)[:, :, None] / 255
            bg = (bgr.astype(np.float32) * (1 - hm) + fill.astype(np.float32) * hm).astype(np.uint8)
            write(out / f"{iid}_bg.png", bg)
        # 位置信息
        ys, xs = np.nonzero(m8 > 128)
        if len(xs) == 0:
            box, cen, cover = [0, 0, w, h], [w / 2, h / 2], 0.0
        else:
            box = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]
            cen = [float(xs.mean()), float(ys.mean())]
            cover = float(len(xs)) / (w * h)
        left = float((m8[:, : w // 2] > 128).mean()); right = float((m8[:, w // 2:] > 128).mean())
        side = "right" if left > right else "left"         # 字放人物少的那边
        # 检查图
        chk = bgr.copy()
        red = np.zeros_like(chk); red[:, :, 2] = 255
        a3 = (m8.astype(np.float32) / 255 * 0.45)[:, :, None]
        chk = (chk * (1 - a3) + red * a3).astype(np.uint8)
        cv2.rectangle(chk, (box[0], box[1]), (box[2], box[3]), (0, 255, 255), 3)
        write(out / f"{iid}_check.png", cv2.resize(chk, (w * 640 // max(w, h), h * 640 // max(w, h))))
        info.append({"id": iid, "src": p.name, "w": w, "h": h, "透明底": bool(has_alpha), "人物外框": box, "人物重心": [round(cen[0]), round(cen[1])],
                     "人物占画面": round(cover, 3), "字放": side, "full": f"art/{iid}_full.png", "fg": f"art/{iid}_fg.png",
                     "bg": None if has_alpha else f"art/{iid}_bg.png"})
        print(f"{iid} ← {p.name}：{w}×{h}，{'透明底' if has_alpha else '抠图'}，人物占 {cover:.0%}，字放{'左' if side == 'left' else '右'}边")
    (out / "art.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"写到 {out}（{len(info)} 张）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
