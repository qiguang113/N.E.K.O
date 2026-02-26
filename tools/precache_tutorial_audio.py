#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import wave
from pathlib import Path

try:
    import requests  # type: ignore
except Exception:  # pragma: no cover
    requests = None


ROOT = Path(__file__).resolve().parents[1]
LOCALE_ZH = ROOT / "static" / "locales" / "zh-CN.json"
OUT_DIR = ROOT / "static" / "tutorial_audio"
INDEX_PATH = OUT_DIR / "index.json"


def flatten(obj, prefix=""):
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(flatten(v, f"{prefix}{k}."))
    else:
        out[prefix[:-1]] = obj
    return out


def sanitize(text: str) -> str:
    if not text:
        return ""
    s = str(text)
    s = re.sub(r"N\s*\.?\s*E\s*\.?\s*K\s*\.?\s*O\s*\.?", "neko", s, flags=re.I)
    s = re.sub(r"<[^>]*>", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    try:
        s = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", s)
        s = re.sub(r"\s+", " ", s).strip()
    except Exception:
        pass
    return s


def build_text_pairs(flat: dict) -> list[str]:
    pairs = {}
    for k, v in flat.items():
        if not isinstance(v, str):
            continue
        if not k.startswith("tutorial."):
            continue
        if k.endswith(".title"):
            base = k[: -len(".title")]
            pairs.setdefault(base, {})["title"] = v
        elif k.endswith(".desc"):
            base = k[: -len(".desc")]
            pairs.setdefault(base, {})["desc"] = v

    texts = []
    for base, item in pairs.items():
        title = item.get("title", "")
        desc = item.get("desc", "")
        combined = "。".join([t for t in [title, desc] if t])
        combined = sanitize(combined)
        if combined:
            texts.append(combined)
    # 去重
    uniq = []
    seen = set()
    for t in texts:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq


def write_wav(path: Path, pcm_bytes: bytes, sample_rate: int):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate or 24000)
        wf.writeframes(pcm_bytes)


def ffmpeg_exists():
    return shutil.which("ffmpeg") is not None


def wav_to_mp3(wav_path: Path, mp3_path: Path):
    mp3_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(wav_path), "-vn", "-codec:a", "libmp3lame", "-q:a", "4", str(mp3_path)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def main():
    parser = argparse.ArgumentParser(description="预生成新手引导语音文件")
    default_port = os.environ.get("NEKO_MAIN_SERVER_PORT", "48911")
    parser.add_argument("--base-url", default=f"http://127.0.0.1:{default_port}", help="服务地址")
    parser.add_argument("--format", default="wav", choices=["wav", "mp3"], help="输出格式（mp3 需要 ffmpeg）")
    parser.add_argument("--limit", type=int, default=0, help="限制生成条数（0 表示全部）")
    args = parser.parse_args()

    if not LOCALE_ZH.exists():
        print(f"找不到 {LOCALE_ZH}")
        return 1

    with LOCALE_ZH.open("r", encoding="utf-8") as f:
        data = json.load(f)

    flat = flatten(data)
    texts = build_text_pairs(flat)
    if args.limit and args.limit > 0:
        texts = texts[: args.limit]

    if args.format == "mp3" and not ffmpeg_exists():
        print("未检测到 ffmpeg，无法导出 mp3，将改为 wav")
        args.format = "wav"

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    index = []

    for i, text in enumerate(texts, 1):
        h = hashlib.sha1(text.encode("utf-8")).hexdigest()
        out_path = OUT_DIR / f"{h}.{args.format}"
        if out_path.exists():
            index.append({"hash": h, "text": text, "format": args.format})
            continue

        if requests is None:
            print("缺少 requests 库，请先安装：pip install requests")
            return 1

        resp = requests.post(
            f"{args.base_url}/api/config/tutorial_tts_audio",
            json={"text": text},
            timeout=15,
        )
        if resp.status_code != 200:
            print(f"[{i}/{len(texts)}] 失败 {resp.status_code}: {text[:30]}...")
            continue
        payload = resp.json()
        if not payload.get("success") or not payload.get("audio"):
            print(f"[{i}/{len(texts)}] 失败: {payload.get('error')}")
            continue

        pcm = base64.b64decode(payload["audio"])
        sample_rate = int(payload.get("sampleRate") or 24000)
        wav_path = OUT_DIR / f"{h}.wav"
        write_wav(wav_path, pcm, sample_rate)

        if args.format == "mp3":
            try:
                wav_to_mp3(wav_path, out_path)
                wav_path.unlink(missing_ok=True)
            except Exception as e:
                print(f"[{i}/{len(texts)}] mp3 转换失败: {e}")
                continue
        else:
            out_path = wav_path

        index.append({"hash": h, "text": text, "format": out_path.suffix.lstrip("."), "sampleRate": sample_rate})
        print(f"[{i}/{len(texts)}] OK {out_path.name}")

    with INDEX_PATH.open("w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    print(f"完成，共生成 {len(index)} 条，索引: {INDEX_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
