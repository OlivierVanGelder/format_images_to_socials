import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

from PIL import Image


PLATFORMS = {
    # In de praktijk zijn TikTok, Reels en Shorts allemaal 9:16 op 1080x1920 het meest gangbaar.
    "tiktok": {"w": 1080, "h": 1920},
    "instagram": {"w": 1080, "h": 1920},
    "yt_shorts": {"w": 1080, "h": 1920},
    "facebook": {"w": 1080, "h": 1920},
}

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm"}


def run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "Command failed:\n"
            + " ".join(cmd)
            + "\n\nSTDOUT:\n"
            + proc.stdout
            + "\n\nSTDERR:\n"
            + proc.stderr
        )


def run_capture(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "Command failed:\n"
            + " ".join(cmd)
            + "\n\nSTDOUT:\n"
            + proc.stdout
            + "\n\nSTDERR:\n"
            + proc.stderr
        )
    return proc.stdout.strip()


def clamp01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def guess_ext_from_url(url: str) -> str | None:
    # Probeert extensie uit URL te halen, ook bij querystrings
    m = re.search(r"\.([a-zA-Z0-9]{2,5})(?:\?|$)", url)
    if not m:
        return None
    return "." + m.group(1).lower()


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as resp, open(dest, "wb") as f:
        shutil.copyfileobj(resp, f)


def is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTS


def is_video(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTS


def crop_box_centered(
    src_w: int,
    src_h: int,
    target_w: int,
    target_h: int,
    focal_x: float,
    focal_y: float,
) -> tuple[int, int, int, int]:
    """
    Bepaalt crop box binnen bron, met focuspunt.
    Return: left, top, width, height
    """
    src_ratio = src_w / src_h
    tgt_ratio = target_w / target_h

    if src_ratio > tgt_ratio:
        # bron is te breed, crop in breedte
        crop_h = src_h
        crop_w = int(round(crop_h * tgt_ratio))
    else:
        # bron is te hoog, crop in hoogte
        crop_w = src_w
        crop_h = int(round(crop_w / tgt_ratio))

    max_left = max(0, src_w - crop_w)
    max_top = max(0, src_h - crop_h)

    left = int(round(max_left * focal_x))
    top = int(round(max_top * focal_y))

    if left < 0:
        left = 0
    if top < 0:
        top = 0
    if left > max_left:
        left = max_left
    if top > max_top:
        top = max_top

    return left, top, crop_w, crop_h


def pad_box(
    src_w: int,
    src_h: int,
    target_w: int,
    target_h: int,
) -> tuple[int, int]:
    """
    Bepaalt geschaalde afmetingen zodat alles past binnen target.
    """
    scale = min(target_w / src_w, target_h / src_h)
    new_w = int(round(src_w * scale))
    new_h = int(round(src_h * scale))
    return new_w, new_h


def format_image(
    inp: Path,
    outp: Path,
    target_w: int,
    target_h: int,
    mode: str,
    focal_x: float,
    focal_y: float,
) -> None:
    img = Image.open(inp).convert("RGB")
    src_w, src_h = img.size

    if mode == "crop":
        left, top, cw, ch = crop_box_centered(src_w, src_h, target_w, target_h, focal_x, focal_y)
        img = img.crop((left, top, left + cw, top + ch))
        img = img.resize((target_w, target_h), Image.Resampling.LANCZOS)
    else:
        new_w, new_h = pad_box(src_w, src_h, target_w, target_h)
        resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (target_w, target_h), (0, 0, 0))
        x = (target_w - new_w) // 2
        y = (target_h - new_h) // 2
        canvas.paste(resized, (x, y))
        img = canvas

    outp.parent.mkdir(parents=True, exist_ok=True)
    img.save(outp, quality=92, optimize=True)


def ffprobe_dims(path: Path) -> tuple[int, int]:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "json",
        str(path),
    ]
    out = run_capture(cmd)
    data = json.loads(out)
    streams = data.get("streams", [])
    if not streams:
        raise RuntimeError("Geen videostream gevonden via ffprobe.")
    w = int(streams[0]["width"])
    h = int(streams[0]["height"])
    return w, h


def format_video(
    inp: Path,
    outp: Path,
    target_w: int,
    target_h: int,
    mode: str,
    focal_x: float,
    focal_y: float,
) -> None:
    src_w, src_h = ffprobe_dims(inp)

    outp.parent.mkdir(parents=True, exist_ok=True)

    if mode == "crop":
        left, top, cw, ch = crop_box_centered(src_w, src_h, target_w, target_h, focal_x, focal_y)
        vf = f"crop={cw}:{ch}:{left}:{top},scale={target_w}:{target_h}"
    else:
        new_w, new_h = pad_box(src_w, src_h, target_w, target_h)
        pad_x = (target_w - new_w) // 2
        pad_y = (target_h - new_h) // 2
        vf = f"scale={new_w}:{new_h},pad={target_w}:{target_h}:{pad_x}:{pad_y}:black"

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(inp),
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(outp),
    ]
    run(cmd)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--media-url", required=True)
    p.add_argument("--platform", required=True, choices=sorted(PLATFORMS.keys()))
    p.add_argument("--mode", required=True, choices=["crop", "pad"])
    p.add_argument("--focal-x", required=False, default="0.5")
    p.add_argument("--focal-y", required=False, default="0.5")
    p.add_argument("--filename", required=False, default="output")
    args = p.parse_args()

    focal_x = clamp01(float(args.focal_x))
    focal_y = clamp01(float(args.focal_y))

    target = PLATFORMS[args.platform]
    target_w = target["w"]
    target_h = target["h"]

    work = Path("work")
    out_dir = Path("out")
    work.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    ext = guess_ext_from_url(args.media_url)
    if not ext:
        # fallback, we proberen later type te detecteren
        ext = ".bin"

    inp = work / f"input{ext}"
    download(args.media_url, inp)

    # Als .bin, probeer te hernoemen op basis van header of openen
    if inp.suffix == ".bin":
        # Probeer image
        try:
            with Image.open(inp) as im:
                fmt = (im.format or "").lower()
            if fmt in {"jpeg", "jpg"}:
                new = inp.with_suffix(".jpg")
                inp.rename(new)
                inp = new
            elif fmt == "png":
                new = inp.with_suffix(".png")
                inp.rename(new)
                inp = new
            elif fmt == "webp":
                new = inp.with_suffix(".webp")
                inp.rename(new)
                inp = new
        except Exception:
            # Probeer video met ffprobe
            try:
                ffprobe_dims(inp)
                new = inp.with_suffix(".mp4")
                inp.rename(new)
                inp = new
            except Exception as e:
                raise RuntimeError("Kon bestandstype niet bepalen. Gebruik een URL met een herkenbare extensie.") from e

    base = args.filename.strip() or "output"

    if is_image(inp):
        outp = out_dir / f"{base}_{args.platform}.jpg"
        format_image(inp, outp, target_w, target_h, args.mode, focal_x, focal_y)
        print(f"Wrote {outp}")
        return 0

    if is_video(inp):
        outp = out_dir / f"{base}_{args.platform}.mp4"
        format_video(inp, outp, target_w, target_h, args.mode, focal_x, focal_y)
        print(f"Wrote {outp}")
        return 0

    raise RuntimeError(f"Onbekend bestandstype: {inp.suffix}")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)