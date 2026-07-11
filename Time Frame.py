# Family Wall App - Phase 1 + Phase 2 Beta v0.7
# Windows / Tkinter / double-click friendly.
#
# What changed in v0.7:
# - Removes the "Also create individual XMLs" option.
# - Changes track layout to:
#     V1 = background duplicate photos, scaled to fill 1920x1080
#     V2 = empty adjustment-layer lane / blur lane placeholder
#     V3 = sharp photos, scaled to fit the border opening
#     V4 = border clips
# - Still generates ONE combined XML containing all Collection sequences.
# - Still no rendering/export automation.
#
# Track layout in each generated collection sequence:
#   V1 = background duplicate photos, scaled to fill 1920x1080
#   V2 = empty blur/adjustment-layer lane placeholder
#   V3 = sharp copy of each photo, scaled to fit inside the border opening
#   V4 = optional border clips, changed every 25 minutes by default
#
# Default math:
#   1920x1080, 24fps, 20 sec/photo, 10 hours/collection = 1800 photos per sequence
#   Borders: 25 minutes each = 24 border slots per 10-hour sequence

import os
import sys
import json
import math
import html
import shutil
import random
import time
import traceback
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

APP_NAME = "Time Frame - Phase 1 + Phase 2"
VERSION = "0.7"
CONFIG_NAME = "time_frame_config.json"

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
BORDER_EXTS = IMAGE_EXTS | {".mp4", ".mov", ".m4v"}
SUPPORTED_EXTS = IMAGE_EXTS | {".heic", ".heif"}

DEFAULT_CANVAS_W = 1920
DEFAULT_CANVAS_H = 1080
DEFAULT_FPS = 24
DEFAULT_PHOTO_SECONDS = 20.0
DEFAULT_COLLECTION_HOURS = 10.0
DEFAULT_OPENING_W = 1640
DEFAULT_OPENING_H = 824
DEFAULT_BORDER_MINUTES = 30.0
DEFAULT_TEXTURE_MINUTES = 30.0
DEFAULT_SCALE_OPENING_WITH_BORDER = True
FIXED_PROJECT_NAME = "Converted Images"
FIXED_SEQUENCE_BASE_NAME = "Premiere Sequence"

BORDER_TIMING_NEVER = "Never"
BORDER_TIMING_30 = "Every 30 Minutes"
BORDER_TIMING_60 = "Every Hour"
DEFAULT_BORDER_TIMING = BORDER_TIMING_30

TEXTURE_TIMING_NEVER = "Never"
TEXTURE_TIMING_15 = "Every 15 Minutes"
TEXTURE_TIMING_30 = "Every 30 Minutes"
TEXTURE_TIMING_60 = "Every Hour"
DEFAULT_TEXTURE_TIMING = TEXTURE_TIMING_30

ASSET_MODE_NONE = "none"
ASSET_MODE_ONE = "use_one"
ASSET_MODE_RANDOM_ALL = "random_all"
ASSET_MODE_RANDOM_SELECTED = "random_selected"

try:
    from PIL import Image, ImageOps, ImageTk, ImageDraw
except Exception:
    Image = None
    ImageOps = None
    ImageTk = None
    ImageDraw = None

try:
    import pillow_heif
except Exception:
    pillow_heif = None


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def config_path() -> Path:
    return app_dir() / CONFIG_NAME


def load_config() -> dict:
    try:
        p = config_path()
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def save_config(data: dict) -> None:
    config_path().write_text(json.dumps(data, indent=2), encoding="utf-8")


def file_url(path: Path) -> str:
    p = str(path.resolve()).replace("\\", "/")
    if not p.startswith("/"):
        p = "/" + p
    return "file://localhost" + p.replace(" ", "%20")


def xml_escape(s: str) -> str:
    return html.escape(str(s), quote=True)


def natural_sort_key(path: Path):
    import re
    parts = re.split(r"(\d+)", path.name.lower())
    return [int(x) if x.isdigit() else x for x in parts]


def list_files(folder: Path, exts):
    return sorted(
        [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in exts],
        key=natural_sort_key,
    )


def list_images(folder: Path):
    return list_files(folder, IMAGE_EXTS)


def list_borders(folder: Path):
    return list_files(folder, BORDER_EXTS)


def list_convertible_images(folder: Path):
    return sorted([p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS], key=natural_sort_key)


def _format_eta(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}h {m}m {s}s"
    return f"{m}m {s}s"


def convert_photos_to_jpg(source_folder: Path, output_folder: Path, log=None, progress=None, source_to_output_map=None, source_files=None):
    if Image is None or ImageOps is None:
        raise RuntimeError("Pillow is required for photo conversion.")
    source_folder = Path(source_folder)
    output_folder = Path(output_folder)
    if not source_folder.exists():
        raise ValueError("Please choose a valid photo folder.")

    images = list(source_files) if source_files is not None else list_convertible_images(source_folder)
    images = [Path(p) for p in images if Path(p).exists() and Path(p).is_file()]
    images = sorted(images, key=natural_sort_key)
    if not images:
        raise ValueError("No supported image files found in the photo folder.")

    has_heif_files = any(p.suffix.lower() in {".heic", ".heif"} for p in images)
    if has_heif_files:
        if pillow_heif is None:
            raise RuntimeError("HEIC/HEIF files were found, but pillow-heif is not installed. Install it with: pip install pillow-heif")
        pillow_heif.register_heif_opener()

    output_folder.mkdir(parents=True, exist_ok=True)
    shuffled = list(images)
    random.shuffle(shuffled)
    total = len(shuffled)

    def process_one(path: Path, index: int) -> Path:
        out_path = output_folder / f"{index:06d}.jpg"
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im)
            if im.mode in {"RGBA", "LA", "P"}:
                bg = Image.new("RGB", im.size, "white")
                if im.mode == "P" and "transparency" in im.info:
                    im = im.convert("RGBA")
                else:
                    im = im.convert("RGBA")
                bg.paste(im, mask=im.split()[-1])
                im = bg
            else:
                if im.mode != "RGB":
                    im = im.convert("RGB")

            max_dim = max(im.size)
            if max_dim > 2556:
                scale = 2556 / max_dim
                new_size = (max(1, int(im.width * scale)), max(1, int(im.height * scale)))
                im = im.resize(new_size, Image.LANCZOS)

            im.save(out_path, format="JPEG", quality=85, optimize=True, progressive=True)
        return out_path

    if log:
        log(f"Phase 2: converting {total} source images to optimized JPGs")

    start_time = time.monotonic()
    last_update_time = start_time

    def emit_progress(done: int, force=False):
        nonlocal last_update_time
        now = time.monotonic()
        should_emit = force or done == 1 or done % 100 == 0 or (now - last_update_time) >= 5.0 or done == total
        if not should_emit:
            return

        elapsed = max(0.001, now - start_time)
        speed = done / elapsed
        remaining = max(0, total - done)
        eta_seconds = remaining / speed if speed > 0 else 0
        percent = (done / total) * 100.0 if total else 100.0
        msg = (
            f"Phase 2: {done:,} / {total:,} converted ({percent:.1f}%) | "
            f"Speed: {speed:.1f} img/sec | Remaining: {_format_eta(eta_seconds)}"
        )
        if progress:
            progress(msg)
        elif log:
            log(msg)
        last_update_time = now

    emit_progress(0, force=True)

    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = {executor.submit(process_one, path, idx): path for idx, path in enumerate(shuffled, 1)}
        completed = 0
        for future in as_completed(futures):
            out_path = future.result()
            src_path = futures[future]
            if source_to_output_map is not None:
                source_to_output_map[str(src_path.resolve())] = str(Path(out_path).resolve())
            completed += 1
            emit_progress(completed)

    emit_progress(total, force=True)
    if log:
        log(f"Phase 2 complete: created {output_folder}")
    return output_folder


def prepare_converted_images_folder(photo_folder: Path) -> Path:
    """Use a stable conversion folder and clean only app-generated numbered JPGs."""
    photo_folder = Path(photo_folder)
    converted_folder = photo_folder.parent / "Converted Images"
    converted_folder.mkdir(parents=True, exist_ok=True)
    numbered_jpg = re.compile(r"^\d{6}\.jpg$", re.IGNORECASE)
    for child in converted_folder.iterdir():
        if child.is_file() and numbered_jpg.match(child.name):
            child.unlink()
    return converted_folder


def calculate_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def calculate_perceptual_hash(path: Path, hash_size: int = 8):
    if Image is None or ImageOps is None:
        raise RuntimeError("Pillow is required for perceptual duplicate detection.")

    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode != "RGB":
            im = im.convert("RGB")
        width, height = im.size
        gray = im.convert("L").resize((hash_size + 1, hash_size), Image.LANCZOS)
        pixels = list(gray.getdata())
        bits = 0
        for row in range(hash_size):
            row_offset = row * (hash_size + 1)
            for col in range(hash_size):
                left = pixels[row_offset + col]
                right = pixels[row_offset + col + 1]
                bits = (bits << 1) | (1 if left > right else 0)
        return bits, width, height


def safe_duplicate_destination(duplicates_folder: Path, source_name: str) -> Path:
    duplicates_folder = Path(duplicates_folder)
    base = Path(source_name).name
    stem = Path(base).stem
    suffix = Path(base).suffix
    candidate = duplicates_folder / base
    if not candidate.exists():
        return candidate

    idx = 2
    while True:
        candidate = duplicates_folder / f"{stem}_duplicate_{idx}{suffix}"
        if not candidate.exists():
            return candidate
        idx += 1


def safe_duplicate_match_destination(duplicates_folder: Path, base_name: str, suffix: str, sequence_index: int) -> Path:
    duplicates_folder = Path(duplicates_folder)
    safe_base = safe_filename(base_name)
    next_index = max(1, int(sequence_index))

    while True:
        if next_index == 1:
            candidate_name = f"{safe_base}{suffix}"
        else:
            candidate_name = f"{safe_base}_duplicate_{next_index}{suffix}"
        candidate = duplicates_folder / candidate_name
        if not candidate.exists():
            return candidate
        next_index += 1


def rename_duplicates_to_match_converted(
    duplicates_folder: Path,
    duplicate_to_accepted: dict,
    duplicate_copied_paths: dict,
    accepted_to_converted: dict,
    log=None,
):
    duplicates_folder = Path(duplicates_folder)
    total = 0
    renamed = 0
    per_accepted_counter = {}

    items = sorted(duplicate_copied_paths.items(), key=lambda kv: natural_sort_key(Path(kv[1])))
    for dup_original_key, copied_path_text in items:
        total += 1
        copied_path = Path(copied_path_text)
        try:
            if not copied_path.exists() or not copied_path.is_file():
                if log:
                    log(f"Duplicate rename warning: copied duplicate file missing, skipping: {copied_path}")
                continue

            accepted_key = duplicate_to_accepted.get(dup_original_key)
            if not accepted_key:
                if log:
                    log(f"Duplicate rename warning: no accepted-image mapping for duplicate: {copied_path.name}")
                continue

            converted_path_text = accepted_to_converted.get(accepted_key)
            if not converted_path_text:
                if log:
                    log(f"Duplicate rename warning: no converted-image mapping for duplicate: {copied_path.name}")
                continue

            converted_base = Path(converted_path_text).stem
            suffix = copied_path.suffix

            next_seq = per_accepted_counter.get(accepted_key, 0) + 1
            target = safe_duplicate_match_destination(duplicates_folder, converted_base, suffix, next_seq)

            while True:
                target_name = target.name
                if target_name == copied_path.name:
                    break
                if not target.exists():
                    break
                next_seq += 1
                target = safe_duplicate_match_destination(duplicates_folder, converted_base, suffix, next_seq)

            per_accepted_counter[accepted_key] = max(per_accepted_counter.get(accepted_key, 0), next_seq)

            if target.name == copied_path.name:
                renamed += 1
                continue

            copied_path.rename(target)
            renamed += 1
        except Exception as exc:
            if log:
                log(f"Duplicate rename warning: could not rename {copied_path.name}: {exc}")
            continue

    if log:
        log(f"Renamed {renamed} of {total} duplicate files to match their converted counterparts.")
    return {"renamed": renamed, "total": total}


def choose_duplicate_to_keep(paths, metadata_cache: dict) -> Path:
    def sort_key(p: Path):
        meta = metadata_cache.get(str(p), {})
        pixels = int(meta.get("pixels", 0))
        file_size = int(meta.get("file_size", p.stat().st_size if p.exists() else 0))
        return (-pixels, -file_size, natural_sort_key(p))

    ordered = sorted(paths, key=sort_key)
    return ordered[0]


def _hamming_distance_64(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except Exception:
        return False


def find_and_copy_duplicates(original_photos_dir: Path, duplicates_folder: Path = None, log=None, progress=None):
    original_photos_dir = Path(original_photos_dir)
    if not original_photos_dir.exists() or not original_photos_dir.is_dir():
        raise ValueError("Please choose a valid photo folder.")

    all_images = list_convertible_images(original_photos_dir)
    if not all_images:
        raise ValueError("No supported image files found in the photo folder.")

    has_heif_files = any(p.suffix.lower() in {".heic", ".heif"} for p in all_images)
    if has_heif_files:
        if pillow_heif is None:
            raise RuntimeError("HEIC/HEIF files were found, but pillow-heif is not installed. Install it with: pip install pillow-heif")
        pillow_heif.register_heif_opener()

    duplicates_folder = Path(duplicates_folder or (original_photos_dir.parent / "Duplicates"))
    duplicates_folder.mkdir(parents=True, exist_ok=True)

    start_time = time.monotonic()
    last_update = start_time
    metadata_cache = {}
    exact_duplicate_count = 0
    visual_duplicate_count = 0
    copied_count = 0
    duplicate_to_accepted = {}
    duplicate_copied_paths = {}

    def emit(stage_label: str, checked: int, total: int, force=False):
        nonlocal last_update
        now = time.monotonic()
        if not (force or checked == total or checked == 1 or checked % 100 == 0 or (now - last_update) >= 4.0):
            return
        elapsed = max(0.001, now - start_time)
        speed = checked / elapsed if checked > 0 else 0.0
        remaining = max(0, total - checked)
        eta = _format_eta(remaining / speed) if speed > 0 else "--"
        current_remaining = max(0, len(all_images) - copied_count)
        msg = (
            f"{stage_label}: {checked:,} / {total:,} checked ({(checked / total) * 100.0:.1f}%)"
            f" | ETA: {eta}\n"
            f"Exact duplicates found: {exact_duplicate_count:,}\n"
            f"Visual duplicates found: {visual_duplicate_count:,}\n"
            f"Duplicate copies saved: {copied_count:,}\n"
            f"Remaining originals: {current_remaining:,}"
        )
        if progress:
            progress(msg)
        if log:
            log(msg.replace("\n", " | "))
        last_update = now

    # Stage A: collect file sizes, then hash only matching-size candidates.
    size_groups = {}
    total = len(all_images)
    for idx, path in enumerate(all_images, 1):
        try:
            if not path.exists() or not path.is_file():
                continue
            size_groups.setdefault(path.stat().st_size, []).append(path)
            metadata_cache[str(path)] = {
                "file_size": path.stat().st_size,
                "pixels": 0,
            }
        except Exception as exc:
            if log:
                log(f"Duplicate scan warning: could not read file metadata for {path.name}: {exc}")
        emit("Duplicate scan", idx, total)

    exact_groups = []
    for group in size_groups.values():
        if len(group) <= 1:
            continue
        by_hash = {}
        for path in group:
            try:
                digest = calculate_sha256(path)
                by_hash.setdefault(digest, []).append(path)
            except Exception as exc:
                if log:
                    log(f"Duplicate scan warning: could not hash {path.name}: {exc}")
        for same_hash in by_hash.values():
            if len(same_hash) > 1:
                exact_groups.append(same_hash)

    exact_dupes_to_move = set()
    for group in exact_groups:
        for p in group:
            meta = metadata_cache.get(str(p), {})
            if not meta.get("pixels"):
                try:
                    with Image.open(p) as im:
                        im = ImageOps.exif_transpose(im)
                        meta["pixels"] = im.width * im.height
                except Exception:
                    meta["pixels"] = 0
                metadata_cache[str(p)] = meta
        keep = choose_duplicate_to_keep(group, metadata_cache)
        for p in group:
            if p != keep:
                exact_dupes_to_move.add(p)
                duplicate_to_accepted[str(p.resolve())] = str(keep.resolve())
    exact_duplicate_count = len(exact_dupes_to_move)
    emit("Duplicate scan", total, total, force=True)

    # Stage B: perceptual duplicates on remaining files, with conservative threshold.
    remaining_for_visual = [p for p in all_images if p not in exact_dupes_to_move]
    visual_groups = []
    if remaining_for_visual:
        dim_hash_map = {}
        visual_total = len(remaining_for_visual)
        for idx, path in enumerate(remaining_for_visual, 1):
            try:
                phash, width, height = calculate_perceptual_hash(path)
                dim_hash_map.setdefault((width, height), []).append((path, phash))
                meta = metadata_cache.get(str(path), {})
                meta["pixels"] = width * height
                meta["file_size"] = int(meta.get("file_size", path.stat().st_size if path.exists() else 0))
                metadata_cache[str(path)] = meta
            except Exception as exc:
                if log:
                    log(f"Duplicate scan warning: could not read image for visual hash {path.name}: {exc}")
            emit("Duplicate scan", idx, visual_total)

        for _, items in dim_hash_map.items():
            if len(items) <= 1:
                continue

            index_by_hash = {}
            for i, (_, h) in enumerate(items):
                index_by_hash.setdefault(h, []).append(i)

            parent = list(range(len(items)))

            def find(i):
                while parent[i] != i:
                    parent[i] = parent[parent[i]]
                    i = parent[i]
                return i

            def union(a, b):
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[rb] = ra

            for i, (_, h) in enumerate(items):
                neighbors = [h] + [h ^ (1 << bit) for bit in range(64)]
                for nh in neighbors:
                    for j in index_by_hash.get(nh, []):
                        if j > i:
                            if _hamming_distance_64(h, items[j][1]) <= 1:
                                union(i, j)

            groups = {}
            for i, (path, _) in enumerate(items):
                groups.setdefault(find(i), []).append(path)
            for grp in groups.values():
                if len(grp) > 1:
                    visual_groups.append(grp)

    visual_dupes_to_move = set()
    for group in visual_groups:
        keep = choose_duplicate_to_keep(group, metadata_cache)
        for p in group:
            if p != keep:
                visual_dupes_to_move.add(p)
                duplicate_to_accepted.setdefault(str(p.resolve()), str(keep.resolve()))
    visual_dupes_to_move -= exact_dupes_to_move
    visual_duplicate_count = len(visual_dupes_to_move)

    all_dupes_to_copy = sorted(exact_dupes_to_move | visual_dupes_to_move, key=natural_sort_key)

    # Stage C: safe copies for review.
    copy_total = len(all_dupes_to_copy)
    for idx, src in enumerate(all_dupes_to_copy, 1):
        try:
            if not src.exists() or not src.is_file():
                continue
            if not _is_within(src, original_photos_dir):
                continue
            if _is_within(src, duplicates_folder):
                continue
            converted_folder = original_photos_dir.parent / "Converted Images"
            if converted_folder.exists() and _is_within(src, converted_folder):
                continue

            dst = safe_duplicate_destination(duplicates_folder, src.name)
            if not _is_within(dst, duplicates_folder):
                continue
            shutil.copy2(str(src), str(dst))
            src_key = str(src.resolve())
            duplicate_copied_paths[src_key] = str(dst.resolve())
            copied_count += 1
        except Exception as exc:
            if log:
                log(f"Duplicate copy warning: could not copy {src.name}: {exc}")
        if copy_total:
            emit("Copying duplicates for review", idx, copy_total)

    emit("Copying duplicates for review", copy_total, max(1, copy_total), force=True)

    selected_for_conversion = sorted([p for p in all_images if p not in all_dupes_to_copy], key=natural_sort_key)
    summary = {
        "scanned_count": len(all_images),
        "exact_duplicate_count": exact_duplicate_count,
        "visual_duplicate_count": visual_duplicate_count,
        "copied_count": copied_count,
        "selected_count": len(selected_for_conversion),
        "duplicates_folder": duplicates_folder,
        "selected_source_files": selected_for_conversion,
        "duplicate_to_accepted": duplicate_to_accepted,
        "duplicate_copied_paths": duplicate_copied_paths,
    }
    return summary


def frames(seconds: float, fps: int) -> int:
    return int(round(float(seconds) * int(fps)))


def get_image_size(path: Path):
    if Image is None:
        return None
    try:
        with Image.open(path) as im:
            return im.size
    except Exception:
        return None


def scale_to_fill(img_w, img_h, canvas_w, canvas_h):
    return max(canvas_w / img_w, canvas_h / img_h) * 100.0


def scale_to_fit(img_w, img_h, box_w, box_h):
    return min(box_w / img_w, box_h / img_h) * 100.0


def safe_filename(name: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in "-_ " else "_" for c in name).strip()
    return cleaned or "Converted Images"


def js_string(s: str) -> str:
    return s.replace('\\', '/').replace('"', '\\"')


def basic_motion_filter_xml(scale_percent: float, center_horiz=0.0, center_vert=0.0):
    return f'''            <filter>
              <effect authoringApp="PremierePro">
                <name>Basic Motion</name>
                <effectid>basic</effectid>
                <effectcategory>motion</effectcategory>
                <effecttype>motion</effecttype>
                <mediatype>video</mediatype>
                <parameter><parameterid>scale</parameterid><name>Scale</name>
                  <value>{scale_percent:.6f}</value></parameter>
                <parameter><parameterid>center</parameterid><name>Center</name>
                  <value><horiz>{center_horiz:.6f}</horiz><vert>{center_vert:.6f}</vert></value></parameter>
              </effect>
            </filter>'''


def make_photo_clipitem(path: Path, clip_id: str, start: int, end: int, fps: int, scale_percent: float, canvas_w: int, canvas_h: int, media_w=None, media_h=None):
    name = path.name
    file_id = "file-" + clip_id
    duration = end - start
    media_w = int(media_w or canvas_w)
    media_h = int(media_h or canvas_h)
    return f'''          <clipitem id="{xml_escape(clip_id)}">
            <name>{xml_escape(name)}</name>
            <duration>{duration}</duration>
            <rate><timebase>{fps}</timebase><ntsc>FALSE</ntsc></rate>
            <start>{start}</start><end>{end}</end>
            <in>0</in><out>{duration}</out>
            <file id="{xml_escape(file_id)}">
              <name>{xml_escape(name)}</name>
              <pathurl>{xml_escape(file_url(path))}</pathurl>
              <rate><timebase>{fps}</timebase><ntsc>FALSE</ntsc></rate>
              <duration>{duration}</duration>
              <media><video><samplecharacteristics>
                <width>{media_w}</width><height>{media_h}</height>
                <pixelaspectratio>square</pixelaspectratio>
              </samplecharacteristics></video></media>
            </file>
{basic_motion_filter_xml(scale_percent)}
          </clipitem>'''

def make_texture_clipitem(path: Path, clip_id: str, start: int, end: int, fps: int, scale_percent: float, canvas_w: int, canvas_h: int, media_w=None, media_h=None, center_horiz=0.0, center_vert=0.0):
    name = path.name
    file_id = "file-" + clip_id
    duration = end - start
    media_w = int(media_w or canvas_w)
    media_h = int(media_h or canvas_h)
    return f'''          <clipitem id="{xml_escape(clip_id)}">
            <name>{xml_escape(name)}</name>
            <duration>{duration}</duration>
            <rate><timebase>{fps}</timebase><ntsc>FALSE</ntsc></rate>
            <start>{start}</start><end>{end}</end>
            <in>0</in><out>{duration}</out>
            <file id="{xml_escape(file_id)}">
              <name>{xml_escape(name)}</name>
              <pathurl>{xml_escape(file_url(path))}</pathurl>
              <rate><timebase>{fps}</timebase><ntsc>FALSE</ntsc></rate>
              <duration>{duration}</duration>
              <media><video><samplecharacteristics>
                <width>{media_w}</width><height>{media_h}</height>
                <pixelaspectratio>square</pixelaspectratio>
              </samplecharacteristics></video></media>
            </file>
{basic_motion_filter_xml(100.0, center_horiz=0.0, center_vert=0.0)}
          </clipitem>'''


def make_border_clipitem(path: Path, clip_id: str, start: int, end: int, fps: int, scale_percent: float, canvas_w: int, canvas_h: int, media_w=None, media_h=None):
    name = path.name
    file_id = "file-" + clip_id
    duration = end - start
    media_w = int(media_w or canvas_w)
    media_h = int(media_h or canvas_h)
    return f'''          <clipitem id="{xml_escape(clip_id)}">
            <name>{xml_escape(name)}</name>
            <duration>{duration}</duration>
            <rate><timebase>{fps}</timebase><ntsc>FALSE</ntsc></rate>
            <start>{start}</start><end>{end}</end>
            <in>0</in><out>{duration}</out>
            <file id="{xml_escape(file_id)}">
              <name>{xml_escape(name)}</name>
              <pathurl>{xml_escape(file_url(path))}</pathurl>
              <rate><timebase>{fps}</timebase><ntsc>FALSE</ntsc></rate>
              <duration>{duration}</duration>
              <media><video><samplecharacteristics>
                <width>{media_w}</width><height>{media_h}</height>
                <pixelaspectratio>square</pixelaspectratio>
              </samplecharacteristics></video></media>
            </file>
{basic_motion_filter_xml(100.0)}
          </clipitem>'''


def representative_border_scale(borders, canvas_w, canvas_h):
    """Return the scale percentage needed to fill the sequence using the first readable border image."""
    for b in borders or []:
        size = get_image_size(b)
        if size:
            return scale_to_fill(size[0], size[1], canvas_w, canvas_h), size
    return 100.0, None


class BorderPicker:
    def __init__(self, borders, seed_text=""):
        self.borders = list(borders)
        self.rng = random.Random(seed_text or datetime.now().isoformat())
        self.deck = []

    def next(self):
        if not self.borders:
            return None
        if not self.deck:
            self.deck = self.borders[:]
            self.rng.shuffle(self.deck)
        return self.deck.pop()


class TexturePicker(BorderPicker):
    pass


class AssetSelector:
    """Generic selector that can be reused for borders, textures, and future asset types."""

    def __init__(self, assets, mode=ASSET_MODE_RANDOM_ALL, selected_names=None, one_name=None, seed_text=""):
        self.assets = list(assets or [])
        self.mode = mode
        self.selected_names = set(selected_names or [])
        self.one_name = one_name or ""
        self.rng = random.Random(seed_text or datetime.now().isoformat())
        self.last_pick = None

    def _pool(self):
        if self.mode == ASSET_MODE_NONE:
            return []
        if self.mode == ASSET_MODE_ONE:
            if self.one_name:
                exact = [p for p in self.assets if p.name == self.one_name]
                if exact:
                    return exact
            return self.assets[:1]
        if self.mode == ASSET_MODE_RANDOM_SELECTED:
            pool = [p for p in self.assets if p.name in self.selected_names]
            return pool
        return self.assets

    def next(self):
        pool = self._pool()
        if not pool:
            return None
        if self.mode == ASSET_MODE_ONE:
            pick = pool[0]
            self.last_pick = pick
            return pick

        if len(pool) > 1 and self.last_pick is not None:
            filtered = [p for p in pool if p != self.last_pick]
            if filtered:
                pool = filtered

        pick = self.rng.choice(pool)
        self.last_pick = pick
        return pick


def build_asset_plan_for_chunk(chunk_photo_count: int, global_photo_start: int, photo_duration_frames: int, selector: AssetSelector, interval_frames=None):
    if selector is None or chunk_photo_count <= 0:
        return []

    if interval_frames is None:
        asset = selector.next()
        if asset is None:
            return []
        total_chunk_frames = chunk_photo_count * photo_duration_frames
        return [(0, total_chunk_frames, asset)]

    plan = []
    global_start_frame = global_photo_start * photo_duration_frames
    global_end_frame = global_start_frame + (chunk_photo_count * photo_duration_frames)
    cursor = global_start_frame
    while cursor < global_end_frame:
        next_boundary = ((cursor // interval_frames) + 1) * interval_frames
        section_end = min(global_end_frame, next_boundary)
        asset = selector.next()
        if asset is None:
            break
        start_frame = cursor - global_start_frame
        end_frame = section_end - global_start_frame
        plan.append((start_frame, end_frame, asset))
        cursor = section_end
    return plan


def make_sequence_xml_body(photos, sequence_name, seq_id, fps, canvas_w, canvas_h, opening_w, opening_h, photo_seconds, borders=None, border_minutes=25.0, border_picker=None, scale_opening_with_border=True, textures=None, texture_picker=None, texture_minutes=25.0, border_plan=None, texture_plan=None):
    dur = frames(photo_seconds, fps)
    photo_count = len(photos)
    total_frames = dur * photo_count
    border_slot_frames = frames(border_minutes * 60.0, fps)
    texture_slot_frames = frames(texture_minutes * 60.0, fps)

    bg_scales = []
    sharp_scales = []
    media_sizes = []
    v4_scales = []
    for p in photos:
        size = get_image_size(p)
        if size:
            img_w, img_h = size
            media_sizes.append((img_w, img_h))
            bg_scales.append(max(canvas_w / img_w, canvas_h / img_h) * 100.0)
            fit_scale = min(canvas_w / img_w, canvas_h / img_h) * 100.0
            photo_ratio = img_w / img_h
            opening_ratio = 1640 / 824
            if photo_ratio > opening_ratio:
                sharp_scale = (1640 / img_w) * 100.0
            else:
                sharp_scale = fit_scale * 0.764
            sharp_scales.append(sharp_scale)
        else:
            media_sizes.append((canvas_w, canvas_h))
            bg_scales.append(100.0)
            sharp_scales.append(75.0)

    lines = []
    lines.append(f'  <sequence id="sequence-{seq_id}">')
    lines.append(f'    <name>{xml_escape(sequence_name)}</name>')
    lines.append(f'    <duration>{total_frames}</duration>')
    lines.append(f'    <rate><timebase>{fps}</timebase><ntsc>FALSE</ntsc></rate>')
    lines.append('    <media>')
    lines.append('      <video>')
    lines.append('        <format>')
    lines.append('          <samplecharacteristics>')
    lines.append(f'            <width>{canvas_w}</width><height>{canvas_h}</height>')
    lines.append('            <pixelaspectratio>square</pixelaspectratio>')
    lines.append(f'            <rate><timebase>{fps}</timebase><ntsc>FALSE</ntsc></rate>')
    lines.append('          </samplecharacteristics>')
    lines.append('        </format>')

    # V1 background fill / duplicate photos for blur treatment
    lines.append('        <track>')
    for i, p in enumerate(photos):
        start = i * dur
        end = start + dur
        lines.append(make_photo_clipitem(p, f's{seq_id}-bg-{i+1}', start, end, fps, bg_scales[i], canvas_w, canvas_h, media_sizes[i][0], media_sizes[i][1]))
    lines.append('        </track>')

    # V2 texture lane. If no texture folder is selected, this stays empty.
    if texture_plan:
        lines.append('        <track>')
        for slot, (start, end, t) in enumerate(texture_plan):
            t_scale = 100.0
            t_media_w, t_media_h = 1920, 1080
            lines.append(make_texture_clipitem(t, f's{seq_id}-texture-{slot+1}', start, end, fps, t_scale, canvas_w, canvas_h, t_media_w, t_media_h))
        lines.append('        </track>')
    elif textures and texture_picker and texture_slot_frames > 0 and total_frames > 0:
        lines.append('        <track>')
        slot = 0
        start = 0
        while start < total_frames:
            end = min(total_frames, start + texture_slot_frames)
            t = texture_picker.next()
            if t is None:
                break

            t_scale = 100.0
            t_media_w, t_media_h = 1920, 1080
            # Premiere/FCP XML does not reliably expose a blend-mode parameter here, so Luminosity is left unset.
            lines.append(make_texture_clipitem(t, f's{seq_id}-texture-{slot+1}', start, end, fps, t_scale, canvas_w, canvas_h, t_media_w, t_media_h))
            slot += 1
            start = end
        lines.append('        </track>')
    else:
        lines.append('        <track>')
        lines.append('        </track>')

    # V3 sharp fit
    lines.append('        <track>')
    for i, p in enumerate(photos):
        start = i * dur
        end = start + dur
        lines.append(make_photo_clipitem(p, f's{seq_id}-sharp-{i+1}', start, end, fps, sharp_scales[i], canvas_w, canvas_h, media_sizes[i][0], media_sizes[i][1]))
    lines.append('        </track>')

    # V4 borders, optional
    border_records = []
    if border_plan:
        lines.append('        <track>')
        for slot, (start, end, b) in enumerate(border_plan):
            b_scale = 100.0
            b_media_w, b_media_h = 1920, 1080
            lines.append(make_border_clipitem(b, f's{seq_id}-border-{slot+1}', start, end, fps, b_scale, canvas_w, canvas_h, b_media_w, b_media_h))
            v4_scales.append(b_scale)
            border_records.append((start, end, b))
        lines.append('        </track>')
    elif borders and border_picker and border_slot_frames > 0 and total_frames > 0:
        lines.append('        <track>')
        slot = 0
        start = 0
        while start < total_frames:
            end = min(total_frames, start + border_slot_frames)
            b = border_picker.next()
            if b is None:
                break
            
            b_scale = 100.0
            b_media_w, b_media_h = 1920, 1080
            lines.append(make_border_clipitem(b, f's{seq_id}-border-{slot+1}', start, end, fps, b_scale, canvas_w, canvas_h, b_media_w, b_media_h))
            v4_scales.append(b_scale)
            border_records.append((start, end, b))
            slot += 1
            start = end
        lines.append('        </track>')

    lines.append('      </video>')
    lines.append('    </media>')
    lines.append('  </sequence>')
    motion_plan = [
        {"sequenceName": sequence_name, "trackIndex": 2, "scales": sharp_scales},
        {"sequenceName": sequence_name, "trackIndex": 3, "scales": v4_scales},
    ]
    return "\n".join(lines), border_records, motion_plan


def wrap_xmeml(sequence_bodies):
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<!DOCTYPE xmeml>', '<xmeml version="4">']
    lines.extend(sequence_bodies)
    lines.append('</xmeml>')
    return "\n".join(lines)


def make_jsx_import_helper(xml_paths, project_path: Path, motion_adjustments=None):
    xml_array = ",\n".join([f'    "{js_string(str(p.resolve()))}"' for p in xml_paths])
    motion_adjustments = motion_adjustments or []
    motion_json = json.dumps(motion_adjustments, indent=2)
    return f'''// Time Frame Premiere Import Helper - Phase 2 only
// Generated {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
// Purpose: import generated XML sequence(s) into the copied Premiere project.
// This script does NOT export/render anything.

var projectPath = "{js_string(str(project_path.resolve()))}";
var xmlPaths = [
{xml_array}
];
var motionAdjustments = {motion_json};

function getCollectionItem(collection, index) {{
    if (!collection) return null;
    if (collection.length) return collection[index];
    if (collection.numItems !== undefined) return collection.getItem(index);
    return null;
}}

function getPropertyCount(component) {{
    if (!component || !component.properties) return 0;
    if (component.properties.length !== undefined) return component.properties.length;
    if (component.properties.numItems !== undefined) return component.properties.numItems;
    return 0;
}}

function getPropertyAt(component, index) {{
    if (!component || !component.properties) return null;
    if (component.properties.length !== undefined) return component.properties[index];
    if (component.properties.numItems !== undefined) return component.properties.getItem(index);
    return null;
}}

function findPropertyByName(component, name) {{
    if (!component || !component.properties) return null;
    var count = getPropertyCount(component);
    for (var i = 0; i < count; i++) {{
        var prop = getPropertyAt(component, i);
        if (prop && prop.name && prop.name.toLowerCase() === name.toLowerCase()) {{
            return prop;
        }}
    }}
    return null;
}}

function setClipScale(trackItem, scaleValue, label) {{
    if (!trackItem) return false;

    try {{
        if (trackItem.setToFrameSize) {{
            trackItem.setToFrameSize();
            return true;
        }}
    }} catch (e) {{}}

    try {{
        var componentCount = trackItem.components ? (trackItem.components.length !== undefined ? trackItem.components.length : trackItem.components.numItems) : 0;
        for (var i = 0; i < componentCount; i++) {{
            var component = trackItem.components[i] || trackItem.components.getItem(i);
            if (!component) continue;
            var componentName = component.displayName || component.name || "";
            if (componentName.toLowerCase().indexOf("basic motion") >= 0 || componentName.toLowerCase().indexOf("motion") >= 0) {{
                var scaleProp = findPropertyByName(component, "Scale");
                if (scaleProp && scaleProp.setValue) {{
                    scaleProp.setValue(scaleValue);
                    return true;
                }}
            }}
        }}
    }} catch (e) {{
        $.writeln("Could not reach Basic Motion Scale for " + label + ": " + e);
    }}

    try {{
        if (trackItem.motion && trackItem.motion.scale !== undefined) {{
            trackItem.motion.scale = scaleValue;
            return true;
        }}
    }} catch (e) {{}}

    try {{
        if (trackItem.videoMotion && trackItem.videoMotion.scale !== undefined) {{
            trackItem.videoMotion.scale = scaleValue;
            return true;
        }}
    }} catch (e) {{}}

    $.writeln("Basic Motion scale could not be updated reliably for " + label + ".");
    return false;
}}

function applyMotionAdjustmentsToSequence(seq) {{
    if (!seq) return;
    for (var i = 0; i < motionAdjustments.length; i++) {{
        var plan = motionAdjustments[i];
        if (!plan || plan.sequenceName !== seq.name) continue;
        var track = seq.videoTracks ? seq.videoTracks[plan.trackIndex] : null;
        if (!track || !track.clips) continue;
        var clips = track.clips;
        var clipCount = clips.length !== undefined ? clips.length : (clips.numItems !== undefined ? clips.numItems : 0);
        if (!clipCount) continue;
        for (var c = 0; c < clipCount; c++) {{
            var trackItem = getCollectionItem(clips, c);
            if (!trackItem) continue;
            var scaleValue = plan.scales && plan.scales[c] !== undefined ? plan.scales[c] : null;
            if (scaleValue === null) continue;
            var label = seq.name + " / track " + plan.trackIndex + " / clip " + (c + 1);
            setClipScale(trackItem, scaleValue, label);
        }}
    }}
}}

function importAllXmls() {{
    try {{
        if (app.openDocument) {{
            app.openDocument(projectPath);
        }}
    }} catch (e) {{}}

    for (var i = 0; i < xmlPaths.length; i++) {{
        app.project.importFiles([xmlPaths[i]], true, app.project.rootItem, false);
    }}

    try {{
        if (app.project && app.project.sequences) {{
            var sequenceCount = app.project.sequences.length !== undefined ? app.project.sequences.length : (app.project.sequences.numItems !== undefined ? app.project.sequences.numItems : 0);
            for (var s = 0; s < sequenceCount; s++) {{
                var seq = getCollectionItem(app.project.sequences, s);
                if (seq) {{
                    applyMotionAdjustmentsToSequence(seq);
                }}
            }}
        }}
    }} catch (e) {{
        $.writeln("Time Frame motion adjustment pass failed: " + e);
    }}

    try {{
        app.project.saveAs(projectPath);
    }} catch (e2) {{
        try {{ app.project.save(); }} catch (e3) {{}}
    }}

    alert("Time Frame import complete. XML file(s) imported: " + xmlPaths.length + "\\nNo exports were started.");
}}

importAllXmls();
'''


def make_readme(project_name, run_folder, template_path, copied_project, combined_xml, jsx_path, borders_used):
    lines = []
    lines.append(f"Time Frame v{VERSION} - Phase 1 + Phase 2")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append(f"Project name: {project_name}")
    lines.append(f"Project folder: {run_folder}")
    lines.append(f"Template used: {template_path if template_path else 'None selected'}")
    lines.append(f"Copied Premiere project: {copied_project if copied_project else 'Not copied'}")
    lines.append(f"Combined XML: {combined_xml}")
    lines.append("")
    lines.append("What was generated:")
    lines.append("- ONE combined XML containing all Collection sequences")
    lines.append("- V1 background photos, V2 blur/adjustment lane, V3 sharp photos, optional V4 border track")
    lines.append("- Premiere import helper JSX")
    lines.append("- Copied Premiere template/project, if selected")
    lines.append("")
    lines.append("What was NOT generated:")
    lines.append("- No exports")
    lines.append("- No renders")
    lines.append("- No Media Encoder queue")
    lines.append("- No JPG, Original Photos, or Collection folders")
    lines.append("")
    lines.append("Recommended Premiere steps:")
    lines.append("1. Open the copied Premiere project.")
    lines.append("2. File > Import, choose the combined XML, OR File > Scripts > Run Script File and choose the JSX helper.")
    lines.append("3. Confirm the imported Collection sequences are correct.")
    lines.append("4. Handle final export manually when ready.")
    lines.append("")
    lines.append(f"JSX helper: {jsx_path}")
    lines.append("")
    if borders_used:
        lines.append("Border usage:")
        for seq_name, recs in borders_used:
            lines.append(f"- {seq_name}: {len(recs)} border slot(s)")
    return "\n".join(lines)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} v{VERSION}")
        self.geometry("940x820")
        self.minsize(880, 740)

        cfg = load_config()
        base = app_dir()

        self.template_path = tk.StringVar(value=cfg.get("template_path", ""))
        self.photo_folder = tk.StringVar()
        self.border_folder = tk.StringVar(value=cfg.get("border_folder", ""))
        self.texture_folder = tk.StringVar(value=cfg.get("texture_folder", ""))
        self.output_root = tk.StringVar(value=cfg.get("output_root", str(base)))

        self.canvas_w = tk.IntVar(value=int(cfg.get("canvas_w", DEFAULT_CANVAS_W)))
        self.canvas_h = tk.IntVar(value=int(cfg.get("canvas_h", DEFAULT_CANVAS_H)))
        self.fps = tk.IntVar(value=int(cfg.get("fps", DEFAULT_FPS)))
        self.photo_seconds = tk.DoubleVar(value=float(cfg.get("photo_seconds", DEFAULT_PHOTO_SECONDS)))
        self.collection_hours = tk.DoubleVar(value=float(cfg.get("collection_hours", DEFAULT_COLLECTION_HOURS)))
        self.opening_w = tk.IntVar(value=int(cfg.get("opening_w", DEFAULT_OPENING_W)))
        self.opening_h = tk.IntVar(value=int(cfg.get("opening_h", DEFAULT_OPENING_H)))
        self.border_timing = tk.StringVar(value=cfg.get("border_timing", DEFAULT_BORDER_TIMING))
        self.texture_timing = tk.StringVar(value=cfg.get("texture_timing", DEFAULT_TEXTURE_TIMING))

        self.copy_template = tk.BooleanVar(value=True)
        self.open_project_after = tk.BooleanVar(value=bool(cfg.get("open_project_after", True)))

        default_border_mode = cfg.get("border_mode") or ASSET_MODE_RANDOM_ALL
        if default_border_mode == ASSET_MODE_NONE:
            default_border_mode = ASSET_MODE_RANDOM_ALL
        default_texture_mode = cfg.get("texture_mode") or (ASSET_MODE_RANDOM_ALL if cfg.get("texture_folder", "") else ASSET_MODE_NONE)
        self.border_mode = tk.StringVar(value=default_border_mode)
        self.texture_mode = tk.StringVar(value=default_texture_mode)
        self.border_one = tk.StringVar(value=cfg.get("border_one", ""))
        self.texture_one = tk.StringVar(value=cfg.get("texture_one", ""))
        self.border_selected = set(cfg.get("border_selected", []))
        self.texture_selected = set(cfg.get("texture_selected", []))

        self.build_ui()
        self.refresh_asset_lists()
        self.refresh_asset_mode_ui()
        self.update_math_preview()

    def build_ui(self):
        root = ttk.Frame(self)
        root.pack(fill="both", expand=True)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(13, weight=1)

        ttk.Label(root, text="Time Frame - Phase 1 + Phase 2", font=("Segoe UI", 16, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", padx=12, pady=(14, 4)
        )
        ttk.Label(root, text="Prepares collections, copies your Premiere template, creates one combined XML, and can add randomized border tracks. No exporting/rendering.").grid(
            row=1, column=0, columnspan=3, sticky="w", padx=12, pady=(0, 8)
        )

        def path_row(label, var, cmd, r):
            ttk.Label(root, text=label).grid(row=r, column=0, sticky="w", padx=12, pady=6)
            ttk.Entry(root, textvariable=var).grid(row=r, column=1, sticky="ew", padx=12, pady=6)
            ttk.Button(root, text="Browse", command=cmd).grid(row=r, column=2, sticky="ew", padx=12, pady=6)

        path_row("Premiere template .prproj", self.template_path, self.pick_template, 2)
        path_row("Photo folder", self.photo_folder, self.pick_photos, 3)
        path_row("Border folder", self.border_folder, self.pick_borders, 4)
        path_row("Texture folder", self.texture_folder, self.pick_textures, 5)
        path_row("Output root folder", self.output_root, self.pick_output_root, 6)

        settings = ttk.LabelFrame(root, text="Collection settings")
        settings.grid(row=7, column=0, columnspan=3, sticky="ew", padx=12, pady=8)
        for c in range(8):
            settings.columnconfigure(c, weight=1)

        labels_vars = [
            ("FPS", self.fps),
            ("Seconds/photo", self.photo_seconds),
            ("Hours/collection", self.collection_hours),
        ]
        r = 0
        c = 0
        for label, var in labels_vars:
            ttk.Label(settings, text=label).grid(row=r, column=c, sticky="w", padx=8, pady=6)
            ent = ttk.Entry(settings, textvariable=var, width=10)
            ent.grid(row=r, column=c + 1, sticky="w", padx=8, pady=6)
            ent.bind("<KeyRelease>", lambda e: self.update_math_preview())
            c += 2
            if c >= 8:
                c = 0
                r += 1

        opts = ttk.LabelFrame(root, text="Output Options")
        opts.grid(row=8, column=0, columnspan=3, sticky="ew", padx=12, pady=8)
        opts.columnconfigure(1, weight=1)
        opts.columnconfigure(2, weight=1)
        ttk.Checkbutton(opts, text="Open copied Premiere project when finished", variable=self.open_project_after).grid(row=0, column=0, sticky="w", padx=8, pady=6)

        assets = ttk.LabelFrame(root, text="Asset Manager")
        assets.grid(row=9, column=0, columnspan=3, sticky="ew", padx=12, pady=(4, 6))
        assets.columnconfigure(0, weight=1)
        assets.columnconfigure(1, weight=1)

        self.border_asset_frame = ttk.LabelFrame(assets, text="Borders")
        self.border_asset_frame.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        self.texture_asset_frame = ttk.LabelFrame(assets, text="Textures")
        self.texture_asset_frame.grid(row=0, column=1, sticky="nsew", padx=8, pady=8)

        self._build_asset_controls(
            parent=self.border_asset_frame,
            mode_var=self.border_mode,
            one_var=self.border_one,
            list_attr="border_listbox",
            one_attr="border_one_combo",
            mode_attr="border_mode_combo",
            allow_none=False,
            selector_cmd=lambda: self.open_thumbnail_selector("border"),
            on_mode_change=self.refresh_asset_mode_ui,
        )
        ttk.Label(self.border_asset_frame, text="Border Changes").grid(row=3, column=0, sticky="w", padx=8, pady=(6, 2))
        self.border_timing_combo = ttk.Combobox(
            self.border_asset_frame,
            state="readonly",
            values=[BORDER_TIMING_NEVER, BORDER_TIMING_30, BORDER_TIMING_60],
            textvariable=self.border_timing,
            width=20,
        )
        self.border_timing_combo.grid(row=3, column=1, sticky="w", padx=8, pady=(6, 2))

        self._build_asset_controls(
            parent=self.texture_asset_frame,
            mode_var=self.texture_mode,
            one_var=self.texture_one,
            list_attr="texture_listbox",
            one_attr="texture_one_combo",
            mode_attr="texture_mode_combo",
            allow_none=True,
            selector_cmd=lambda: self.open_thumbnail_selector("texture"),
            on_mode_change=self.refresh_asset_mode_ui,
        )
        ttk.Label(self.texture_asset_frame, text="Texture Changes").grid(row=3, column=0, sticky="w", padx=8, pady=(6, 2))
        self.texture_timing_combo = ttk.Combobox(
            self.texture_asset_frame,
            state="readonly",
            values=[TEXTURE_TIMING_NEVER, TEXTURE_TIMING_15, TEXTURE_TIMING_30, TEXTURE_TIMING_60],
            textvariable=self.texture_timing,
            width=20,
        )
        self.texture_timing_combo.grid(row=3, column=1, sticky="w", padx=8, pady=(6, 2))

        self.preview = ttk.Label(root, text="", font=("Segoe UI", 10, "bold"))
        self.preview.grid(row=10, column=0, columnspan=3, sticky="w", padx=12, pady=(4, 6))

        actions = ttk.Frame(root)
        actions.grid(row=11, column=0, columnspan=3, sticky="ew", padx=12, pady=8)
        ttk.Button(actions, text="Save Template/Settings", command=self.save_current_settings).pack(side="left")
        ttk.Button(actions, text="Create Time Frame", command=self.generate).pack(side="left", padx=8)
        ttk.Button(actions, text="Refresh Math", command=self.update_math_preview).pack(side="left")
        ttk.Button(actions, text="Quit", command=self.destroy).pack(side="right")

        note = ttk.Label(root, text="Premiere note: this creates one combined XML. Auto-import is attempted through a JSX helper, but Premiere may still require File > Scripts > Run Script File.")
        note.grid(row=12, column=0, columnspan=3, sticky="w", padx=12, pady=(0, 4))

        progress_box = ttk.Frame(root)
        progress_box.grid(row=13, column=0, columnspan=3, sticky="ew", padx=12, pady=(6, 12))
        progress_box.columnconfigure(0, weight=1)

        self.progress_status_var = tk.StringVar(value="Ready")
        self.progress_percent_var = tk.StringVar(value="0%")
        self.progress_eta_var = tk.StringVar(value="Estimated time remaining:\n--")
        self.progress_value_var = tk.DoubleVar(value=0.0)
        self._last_progress_draw = 0.0
        self._last_eta_draw = 0.0

        ttk.Label(progress_box, textvariable=self.progress_status_var, font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 6))

        style = ttk.Style(self)
        style.configure("Green.Horizontal.TProgressbar", troughcolor="#d7d7d7", background="#2e9b42", thickness=28)
        self.progress_bar = ttk.Progressbar(
            progress_box,
            orient="horizontal",
            mode="determinate",
            style="Green.Horizontal.TProgressbar",
            variable=self.progress_value_var,
            maximum=100.0,
        )
        self.progress_bar.grid(row=1, column=0, sticky="ew")

        ttk.Label(progress_box, textvariable=self.progress_percent_var, font=("Segoe UI", 10, "bold")).grid(row=2, column=0, pady=(6, 2))
        ttk.Label(progress_box, textvariable=self.progress_eta_var, justify="center").grid(row=3, column=0, pady=(0, 2))

        self.log("Ready.")
        self.log("No Phase 3: this app will not export, render, or queue anything.")
        self.log("Default: 20 seconds/photo, 10 hours/collection = 1,800 photos per collection.")
        self.log("Borders now auto-scale to fill the frame; sharp photos can scale with that border.")
        self.log("Default borders: change every 30 minutes (configurable in Border Changes).")
        self.log("Track layout: V1 background photos, V2 blur/adjustment lane, V3 sharp photos, V4 borders.")

    def log(self, msg):
        print(str(msg), flush=True)

    def update_progress(self, percent, status_text, eta_text=None, force=False):
        now = time.monotonic()
        percent = max(0.0, min(100.0, float(percent)))
        status_changed = status_text != self.progress_status_var.get()
        percent_changed = abs(percent - float(self.progress_value_var.get())) >= 0.4

        if not force and not status_changed and not percent_changed and (now - self._last_progress_draw) < 0.5:
            return

        self.progress_value_var.set(percent)
        self.progress_status_var.set(status_text)
        if percent >= 100.0:
            self.progress_percent_var.set("Finished")
        else:
            self.progress_percent_var.set(f"{int(round(percent))}%")

        if eta_text is not None and (force or status_changed or (now - self._last_eta_draw) >= 1.0):
            self.progress_eta_var.set(f"Estimated time remaining:\n{eta_text}")
            self._last_eta_draw = now

        if percent >= 100.0 and force:
            self.progress_eta_var.set("Estimated time remaining:\nCompleted")

        self._last_progress_draw = now
        self.update_idletasks()

    def _build_asset_controls(self, parent, mode_var, one_var, list_attr, one_attr, mode_attr, allow_none, selector_cmd, on_mode_change):
        mode_values = [ASSET_MODE_ONE, ASSET_MODE_RANDOM_ALL, ASSET_MODE_RANDOM_SELECTED]
        if allow_none:
            mode_values = [ASSET_MODE_NONE] + mode_values

        ttk.Label(parent, text="Mode").grid(row=0, column=0, sticky="w", padx=8, pady=(6, 2))
        mode_combo = ttk.Combobox(parent, state="readonly", values=mode_values, textvariable=mode_var, width=18)
        mode_combo.grid(row=0, column=1, sticky="w", padx=8, pady=(6, 2))
        mode_combo.bind("<<ComboboxSelected>>", lambda e: on_mode_change())
        setattr(self, mode_attr, mode_combo)

        one_label = ttk.Label(parent, text="Use One")
        one_label.grid(row=1, column=0, sticky="w", padx=8, pady=2)
        one_combo = ttk.Combobox(parent, state="readonly", textvariable=one_var, width=30)
        one_combo.grid(row=1, column=1, sticky="w", padx=8, pady=2)
        setattr(self, one_attr, one_combo)

        selected_label = ttk.Label(parent, text="Randomize Selected")
        selected_label.grid(row=2, column=0, sticky="nw", padx=8, pady=2)
        listbox = tk.Listbox(parent, selectmode="multiple", height=7, exportselection=False)
        listbox.grid(row=2, column=1, sticky="ew", padx=8, pady=2)
        listbox.bind("<<ListboxSelect>>", lambda e: self._capture_asset_selections())
        setattr(self, list_attr, listbox)

        ttk.Button(parent, text="Open Thumbnail Selector", command=selector_cmd).grid(row=4, column=0, columnspan=2, sticky="w", padx=8, pady=(6, 2))

        setattr(self, f"{list_attr}_label", selected_label)
        setattr(self, f"{one_attr}_label", one_label)

    def _capture_asset_selections(self):
        if hasattr(self, "border_listbox"):
            self.border_selected = {self.border_listbox.get(i) for i in self.border_listbox.curselection()}
        if hasattr(self, "texture_listbox"):
            self.texture_selected = {self.texture_listbox.get(i) for i in self.texture_listbox.curselection()}

    def _set_listbox_values(self, listbox, names, selected_names):
        listbox.delete(0, "end")
        for name in names:
            listbox.insert("end", name)
        for idx, name in enumerate(names):
            if name in selected_names:
                listbox.select_set(idx)

    def refresh_asset_lists(self):
        border_names = []
        texture_names = []
        border_dir = Path(self.border_folder.get()) if self.border_folder.get().strip() else None
        texture_dir = Path(self.texture_folder.get()) if self.texture_folder.get().strip() else None

        if border_dir and border_dir.exists():
            border_names = [p.name for p in list_borders(border_dir)]
        if texture_dir and texture_dir.exists():
            texture_names = [p.name for p in list_images(texture_dir)]

        if getattr(self, "border_one_combo", None):
            self.border_one_combo["values"] = border_names
            if border_names and self.border_one.get() not in border_names:
                self.border_one.set(border_names[0])
            if not border_names:
                self.border_one.set("")
        if getattr(self, "texture_one_combo", None):
            self.texture_one_combo["values"] = texture_names
            if texture_names and self.texture_one.get() not in texture_names:
                self.texture_one.set(texture_names[0])
            if not texture_names:
                self.texture_one.set("")

        if getattr(self, "border_listbox", None):
            self._set_listbox_values(self.border_listbox, border_names, self.border_selected)
        if getattr(self, "texture_listbox", None):
            self._set_listbox_values(self.texture_listbox, texture_names, self.texture_selected)

    def _load_thumbnail_image(self, file_path: Path, thumb_size=120, for_border=False):
        if Image is None or ImageTk is None:
            return None

        suffix = file_path.suffix.lower()
        is_video = suffix in {".mp4", ".mov", ".m4v"}

        if is_video:
            # Placeholder for unsupported video thumbnail rendering.
            img = Image.new("RGB", (thumb_size, thumb_size), "#303030")
            draw = ImageDraw.Draw(img) if ImageDraw else None
            if draw:
                draw.rectangle((10, 10, thumb_size - 10, thumb_size - 10), outline="#9a9a9a", width=2)
                draw.polygon([(50, 42), (50, 78), (80, 60)], fill="#e0e0e0")
                draw.text((14, 88), "Video", fill="#e0e0e0")
            return ImageTk.PhotoImage(img)

        try:
            with Image.open(file_path) as im:
                im = ImageOps.exif_transpose(im)
                if for_border and ("A" in im.getbands()):
                    # Checkerboard behind alpha borders for accurate preview.
                    checker = Image.new("RGB", im.size, "#d0d0d0")
                    draw = ImageDraw.Draw(checker) if ImageDraw else None
                    if draw:
                        step = 24
                        for y in range(0, im.height, step):
                            for x in range(0, im.width, step):
                                if ((x // step) + (y // step)) % 2 == 0:
                                    draw.rectangle((x, y, x + step - 1, y + step - 1), fill="#b6b6b6")
                    im = im.convert("RGBA")
                    checker.paste(im, mask=im.split()[-1])
                    im = checker
                else:
                    if im.mode not in {"RGB", "L"}:
                        im = im.convert("RGB")
                im.thumbnail((thumb_size, thumb_size), Image.LANCZOS)
                canvas = Image.new("RGB", (thumb_size, thumb_size), "#1f1f1f")
                x = (thumb_size - im.width) // 2
                y = (thumb_size - im.height) // 2
                canvas.paste(im, (x, y))
                return ImageTk.PhotoImage(canvas)
        except Exception:
            img = Image.new("RGB", (thumb_size, thumb_size), "#4a2d2d")
            draw = ImageDraw.Draw(img) if ImageDraw else None
            if draw:
                draw.text((12, 52), "Preview\nunavailable", fill="#f2dcdc")
            return ImageTk.PhotoImage(img)

    def open_thumbnail_selector(self, asset_type: str):
        if Image is None or ImageTk is None:
            messagebox.showerror("Missing dependency", "Pillow with ImageTk is required for thumbnail selection.")
            return

        if asset_type == "border":
            folder_text = self.border_folder.get().strip()
            mode = self.border_mode.get()
            selected_set = set(self.border_selected)
            one_name = self.border_one.get()
            asset_files = list_borders(Path(folder_text)) if folder_text and Path(folder_text).exists() else []
            title = "Border Thumbnail Selector"
        else:
            folder_text = self.texture_folder.get().strip()
            mode = self.texture_mode.get()
            selected_set = set(self.texture_selected)
            one_name = self.texture_one.get()
            asset_files = list_images(Path(folder_text)) if folder_text and Path(folder_text).exists() else []
            title = "Texture Thumbnail Selector"

        if not folder_text or not Path(folder_text).exists():
            messagebox.showerror("Missing folder", f"Please select a valid {asset_type} folder first.")
            return
        if not asset_files:
            messagebox.showerror("No assets", f"No supported {asset_type} files found in the selected folder.")
            return

        win = tk.Toplevel(self)
        win.title(title)
        win.geometry("920x620")
        win.transient(self)
        win.grab_set()

        ttk.Label(win, text=f"Mode: {mode}").pack(anchor="w", padx=10, pady=(10, 4))

        scroller = ttk.Frame(win)
        scroller.pack(fill="both", expand=True, padx=10, pady=6)
        canvas = tk.Canvas(scroller, highlightthickness=0)
        vbar = ttk.Scrollbar(scroller, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=vbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        vbar.pack(side="right", fill="y")

        for i in range(4):
            inner.columnconfigure(i, weight=1)

        if mode == ASSET_MODE_ONE and one_name:
            selected_names = {one_name}
        else:
            selected_names = set(selected_set)

        win._thumb_refs = []
        tile_frames = {}
        checks = {}

        style = ttk.Style(win)
        style.configure("Selected.TFrame", borderwidth=2, relief="solid")

        def paint_selected(name):
            frm = tile_frames[name]
            if checks[name].get():
                frm.configure(style="Selected.TFrame")
            else:
                frm.configure(style="TFrame")

        def toggle_name(name):
            if mode == ASSET_MODE_ONE:
                for n in checks:
                    checks[n].set(1 if n == name else 0)
                selected_names.clear()
                selected_names.add(name)
            else:
                if checks[name].get():
                    selected_names.add(name)
                else:
                    selected_names.discard(name)
            for n in checks:
                paint_selected(n)

        for idx, asset_path in enumerate(asset_files):
            name = asset_path.name
            row = idx // 4
            col = idx % 4
            tile = ttk.Frame(inner, padding=6)
            tile.grid(row=row, column=col, sticky="nsew", padx=6, pady=6)
            tile_frames[name] = tile

            img = self._load_thumbnail_image(asset_path, thumb_size=120, for_border=(asset_type == "border"))
            win._thumb_refs.append(img)

            check_var = tk.IntVar(value=1 if name in selected_names else 0)
            checks[name] = check_var

            img_label = ttk.Label(tile, image=img)
            img_label.pack()
            ttk.Label(tile, text=name, wraplength=160, justify="center").pack(fill="x", pady=(4, 2))

            cb = ttk.Checkbutton(tile, text="Select", variable=check_var, command=lambda n=name: toggle_name(n))
            cb.pack()

            for widget in (tile, img_label):
                widget.bind("<Button-1>", lambda e, n=name: (checks[n].set(0 if checks[n].get() else 1), toggle_name(n)))

            paint_selected(name)

        btns = ttk.Frame(win)
        btns.pack(fill="x", padx=10, pady=(0, 10))

        def select_all():
            if mode == ASSET_MODE_ONE:
                if asset_files:
                    first = asset_files[0].name
                    for n in checks:
                        checks[n].set(1 if n == first else 0)
                    selected_names.clear()
                    selected_names.add(first)
            else:
                for n in checks:
                    checks[n].set(1)
                selected_names.clear()
                selected_names.update(checks.keys())
            for n in checks:
                paint_selected(n)

        def clear_all():
            for n in checks:
                checks[n].set(0)
                paint_selected(n)
            selected_names.clear()

        def apply_selection():
            chosen = [name for name, var in checks.items() if var.get()]
            if asset_type == "border":
                if mode == ASSET_MODE_ONE:
                    self.border_one.set(chosen[0] if chosen else "")
                elif mode == ASSET_MODE_RANDOM_SELECTED:
                    self.border_selected = set(chosen)
                    self._set_listbox_values(self.border_listbox, list(self.border_listbox.get(0, "end")), self.border_selected)
            else:
                if mode == ASSET_MODE_ONE:
                    self.texture_one.set(chosen[0] if chosen else "")
                elif mode == ASSET_MODE_RANDOM_SELECTED:
                    self.texture_selected = set(chosen)
                    self._set_listbox_values(self.texture_listbox, list(self.texture_listbox.get(0, "end")), self.texture_selected)
            self.save_current_settings()
            win.destroy()

        ttk.Button(btns, text="Select All", command=select_all).pack(side="left")
        ttk.Button(btns, text="Clear", command=clear_all).pack(side="left", padx=6)
        ttk.Button(btns, text="Apply Selection", command=apply_selection).pack(side="left", padx=6)
        ttk.Button(btns, text="Cancel", command=win.destroy).pack(side="right")

    def refresh_asset_mode_ui(self):
        border_mode = self.border_mode.get()
        texture_mode = self.texture_mode.get()

        border_show_one = border_mode == ASSET_MODE_ONE
        border_show_selected = border_mode == ASSET_MODE_RANDOM_SELECTED
        self.border_one_combo.grid() if border_show_one else self.border_one_combo.grid_remove()
        self.border_one_combo_label.grid() if border_show_one else self.border_one_combo_label.grid_remove()
        self.border_listbox.grid() if border_show_selected else self.border_listbox.grid_remove()
        self.border_listbox_label.grid() if border_show_selected else self.border_listbox_label.grid_remove()

        texture_show_one = texture_mode == ASSET_MODE_ONE
        texture_show_selected = texture_mode == ASSET_MODE_RANDOM_SELECTED
        self.texture_one_combo.grid() if texture_show_one else self.texture_one_combo.grid_remove()
        self.texture_one_combo_label.grid() if texture_show_one else self.texture_one_combo_label.grid_remove()
        self.texture_listbox.grid() if texture_show_selected else self.texture_listbox.grid_remove()
        self.texture_listbox_label.grid() if texture_show_selected else self.texture_listbox_label.grid_remove()

    def border_interval_frames(self):
        fps = int(self.fps.get())
        if self.border_timing.get() == BORDER_TIMING_NEVER:
            return None
        if self.border_timing.get() == BORDER_TIMING_60:
            return frames(60.0 * 60.0, fps)
        return frames(30.0 * 60.0, fps)

    def texture_interval_frames(self):
        fps = int(self.fps.get())
        timing = self.texture_timing.get()
        if timing == TEXTURE_TIMING_NEVER:
            return None
        if timing == TEXTURE_TIMING_15:
            return frames(15.0 * 60.0, fps)
        if timing == TEXTURE_TIMING_60:
            return frames(60.0 * 60.0, fps)
        return frames(30.0 * 60.0, fps)

    def save_current_settings(self):
        data = {
            "template_path": self.template_path.get(),
            "border_folder": self.border_folder.get(),
            "texture_folder": self.texture_folder.get(),
            "output_root": self.output_root.get(),
            "canvas_w": self.canvas_w.get(),
            "canvas_h": self.canvas_h.get(),
            "fps": self.fps.get(),
            "photo_seconds": self.photo_seconds.get(),
            "collection_hours": self.collection_hours.get(),
            "opening_w": self.opening_w.get(),
            "opening_h": self.opening_h.get(),
            "open_project_after": self.open_project_after.get(),
            "border_timing": self.border_timing.get(),
            "texture_timing": self.texture_timing.get(),
            "border_mode": self.border_mode.get(),
            "texture_mode": self.texture_mode.get(),
            "border_one": self.border_one.get(),
            "texture_one": self.texture_one.get(),
            "border_selected": sorted(self.border_selected),
            "texture_selected": sorted(self.texture_selected),
        }
        save_config(data)
        self.log(f"Settings saved: {config_path()}")

    def pick_template(self):
        p = filedialog.askopenfilename(
            title="Select Premiere template project",
            filetypes=[("Premiere Project", "*.prproj"), ("All files", "*.*")],
            initialdir=str(app_dir()),
        )
        if p:
            self.template_path.set(p)
            self.save_current_settings()

    def pick_photos(self):
        p = filedialog.askdirectory(title="Select photo folder")
        if p:
            self.photo_folder.set(p)
            self.output_root.set(str(Path(p).parent))
            self.save_current_settings()
            self.update_math_preview()

    def pick_borders(self):
        p = filedialog.askdirectory(title="Select border folder")
        if p:
            self.border_folder.set(p)
            if self.border_mode.get() == ASSET_MODE_NONE:
                self.border_mode.set(ASSET_MODE_RANDOM_ALL)
            self.refresh_asset_lists()
            self.refresh_asset_mode_ui()
            self.save_current_settings()
            self.update_math_preview()

    def pick_textures(self):
        p = filedialog.askdirectory(title="Select texture folder")
        if p:
            self.texture_folder.set(p)
            if self.texture_mode.get() == ASSET_MODE_NONE:
                self.texture_mode.set(ASSET_MODE_RANDOM_ALL)
            self.refresh_asset_lists()
            self.refresh_asset_mode_ui()
            self.save_current_settings()
            self.update_math_preview()

    def pick_output_root(self):
        p = filedialog.askdirectory(title="Select output root folder")
        if p:
            self.output_root.set(p)
            self.save_current_settings()

    def photos_per_collection(self):
        return max(1, int(math.floor(float(self.collection_hours.get()) * 3600.0 / float(self.photo_seconds.get()))))

    def border_slots_per_collection(self):
        if self.border_timing.get() == BORDER_TIMING_NEVER:
            return 1
        minutes = 60.0 if self.border_timing.get() == BORDER_TIMING_60 else 30.0
        return max(1, int(math.ceil(float(self.collection_hours.get()) * 60.0 / minutes)))

    def update_math_preview(self):
        try:
            per = self.photos_per_collection()
            border_slots = self.border_slots_per_collection()
            total = 0
            folder = Path(self.photo_folder.get()) if self.photo_folder.get() else None
            if folder and folder.exists():
                total = len(list_images(folder))
            collections = math.ceil(total / per) if total else 0
            length = per * float(self.photo_seconds.get()) / 3600.0
            total_hours = total * float(self.photo_seconds.get()) / 3600.0 if total else 0
            self.preview.config(
                text=f"Math: {per:,} photos/collection ≈ {length:.2f} hr. Current folder: {total:,} photos ≈ {total_hours:.2f} hr → {collections:,} sequence(s). Borders: {border_slots} slot(s)/collection ({self.border_timing.get()})."
            )
        except Exception:
            self.preview.config(text="Math preview unavailable. Check settings.")

    def validate(self, photos_dir=None):
        photos_dir = Path(photos_dir or self.photo_folder.get())
        output_root = Path(self.output_root.get())
        template = Path(self.template_path.get()) if self.template_path.get().strip() else None
        border_dir = Path(self.border_folder.get()) if self.border_folder.get().strip() else None
        texture_dir = Path(self.texture_folder.get()) if self.texture_folder.get().strip() else None

        if not photos_dir.exists():
            raise ValueError("Please choose a valid photo folder.")
        photos = list_images(photos_dir)
        if not photos:
            raise ValueError("No supported image files found in the photo folder.")
        output_root.mkdir(parents=True, exist_ok=True)

        borders = []
        border_enabled = self.border_mode.get() != ASSET_MODE_NONE
        if border_enabled:
            if not border_dir or not border_dir.exists():
                raise ValueError("Please choose a valid border folder.")
            borders = list_borders(border_dir)
            if not borders:
                raise ValueError("No supported border files found. Supported: JPG, PNG, WEBP, TIFF, MP4, MOV, M4V.")

        textures = []
        texture_enabled = self.texture_mode.get() != ASSET_MODE_NONE
        if texture_enabled:
            if not texture_dir or not texture_dir.exists():
                raise ValueError("Texture folder is selected but does not exist.")
            textures = list_images(texture_dir)

        if self.copy_template.get():
            if not template or not template.exists() or template.suffix.lower() != ".prproj":
                raise ValueError("Please choose a valid Premiere template .prproj, or turn off template copying.")

        if int(self.fps.get()) <= 0:
            raise ValueError("FPS must be greater than 0.")
        if float(self.photo_seconds.get()) <= 0:
            raise ValueError("Seconds/photo must be greater than 0.")
        if float(self.collection_hours.get()) <= 0:
            raise ValueError("Hours/collection must be greater than 0.")
        if int(self.canvas_w.get()) <= 0 or int(self.canvas_h.get()) <= 0:
            raise ValueError("Canvas dimensions must be greater than 0.")
        if int(self.opening_w.get()) <= 0 or int(self.opening_h.get()) <= 0:
            raise ValueError("Opening dimensions must be greater than 0.")
        if int(self.opening_w.get()) > int(self.canvas_w.get()) or int(self.opening_h.get()) > int(self.canvas_h.get()):
            raise ValueError("Opening dimensions should fit inside the canvas.")
        return photos, photos_dir, output_root, template, borders, textures

    def generate(self):
        try:
            self._capture_asset_selections()
            self.save_current_settings()
            self.log("Creating Time Frame project...")
            self.update_progress(0, "Creating project...", eta_text="--", force=True)

            original_photos_dir = Path(self.photo_folder.get())
            if not original_photos_dir.exists() or not original_photos_dir.is_dir():
                raise ValueError("Please choose a valid photo folder.")

            self.output_root.set(str(original_photos_dir.parent))
            output_root = original_photos_dir.parent
            output_root.mkdir(parents=True, exist_ok=True)
            photos_dir = original_photos_dir

            phase_weights = {
                "dupe": (0.0, 30.0),
                "convert": (30.0, 65.0),
                "xml": (65.0, 95.0),
                "final": (95.0, 100.0),
            }

            def weighted_percent(phase_key, phase_pct):
                lo, hi = phase_weights[phase_key]
                phase_pct = max(0.0, min(100.0, float(phase_pct)))
                return lo + ((hi - lo) * (phase_pct / 100.0))

            def parse_percent_and_eta(progress_message):
                percent = None
                eta = None
                m_pct = re.search(r"\((\d+(?:\.\d+)?)%\)", progress_message)
                if m_pct:
                    percent = float(m_pct.group(1))
                m_eta = re.search(r"(?:ETA|Remaining):\s*([^|\n]+)", progress_message)
                if m_eta:
                    eta = m_eta.group(1).strip()
                return percent, eta

            def duplicate_progress(msg):
                pct, eta = parse_percent_and_eta(msg)
                phase_pct = pct if pct is not None else 0.0
                status = "Scanning for duplicates..."
                if str(msg).startswith("Copying duplicates for review"):
                    status = "Copying duplicates for review..."
                self.update_progress(weighted_percent("dupe", phase_pct), status, eta_text=eta)

            def phase0_progress(msg):
                pct, eta = parse_percent_and_eta(msg)
                phase_pct = pct if pct is not None else 0.0
                self.update_progress(weighted_percent("convert", phase_pct), "Converting photos...", eta_text=eta)

            self.log("Phase 0: scanning original photos for duplicates...")
            self.update_progress(weighted_percent("dupe", 0), "Scanning for duplicates...", eta_text="--", force=True)
            duplicate_result = find_and_copy_duplicates(
                original_photos_dir=original_photos_dir,
                duplicates_folder=original_photos_dir.parent / "Duplicates",
                log=self.log,
                progress=duplicate_progress,
            )

            self.log("Phase 0 complete: duplicate scan finished.")
            self.log("Phase 1: copying duplicates for review into sibling Duplicates folder...")
            self.log("Phase 1 complete.")
            self.log("Duplicate scan complete")
            self.log(f"Original files scanned: {duplicate_result['scanned_count']:,}")
            self.log(f"Duplicate copies saved: {duplicate_result['copied_count']:,}")
            self.log(f"Files selected for conversion: {duplicate_result['selected_count']:,}")
            self.log("Original Photos folder unchanged")
            self.log(f"Duplicates folder: {duplicate_result['duplicates_folder']}")
            if duplicate_result["copied_count"] == 0:
                self.log("No duplicates found.")
            if duplicate_result["selected_count"] <= 0:
                raise ValueError("No usable photos remaining after duplicate handling.")

            self.log("Phase 2: converting remaining source photos to optimized JPGs...")
            self.update_progress(weighted_percent("convert", 0), "Converting photos...", eta_text="--", force=True)
            converted_dir = prepare_converted_images_folder(original_photos_dir)
            accepted_to_converted = {}
            converted_dir = convert_photos_to_jpg(
                original_photos_dir,
                converted_dir,
                log=self.log,
                progress=phase0_progress,
                source_to_output_map=accepted_to_converted,
                source_files=duplicate_result.get("selected_source_files", []),
            )
            photos_dir = converted_dir
            self.log(f"Phase 2: using converted JPG folder -> {photos_dir}")

            try:
                rename_duplicates_to_match_converted(
                    duplicates_folder=duplicate_result["duplicates_folder"],
                    duplicate_to_accepted=duplicate_result.get("duplicate_to_accepted", {}),
                    duplicate_copied_paths=duplicate_result.get("duplicate_copied_paths", {}),
                    accepted_to_converted=accepted_to_converted,
                    log=self.log,
                )
            except Exception as rename_exc:
                self.log(f"Duplicate rename warning: unexpected error during duplicate renaming: {rename_exc}")

            self.log("Phase 3: continuing Time Frame workflow...")
            self.update_progress(weighted_percent("xml", 0), "Generating Premiere XML...", eta_text="--", force=True)

            photos, photos_dir, output_root, template, borders, textures = self.validate(photos_dir=photos_dir)
            self.update_math_preview()

            project_name = FIXED_PROJECT_NAME
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            source_folder_name = safe_filename(original_photos_dir.name)
            run_folder = original_photos_dir.parent / "Premiere File"

            xml_folder = run_folder / "XML"
            premiere_folder = run_folder / "Premiere"
            for p in [xml_folder, premiere_folder]:
                p.mkdir(parents=True, exist_ok=True)

            copied_project = None
            if self.copy_template.get() and template:
                self.update_progress(weighted_percent("xml", 96), "Copying Premiere template...", eta_text="--")
                copied_project = premiere_folder / f"{source_folder_name}.prproj"
                shutil.copy2(template, copied_project)
                self.log(f"Copied Premiere template → {copied_project.name}")

            per = self.photos_per_collection()
            base_seq = FIXED_SEQUENCE_BASE_NAME
            photo_dur_frames = frames(float(self.photo_seconds.get()), int(self.fps.get()))
            border_interval_frames = self.border_interval_frames()
            texture_interval_frames = self.texture_interval_frames()
            effective_border_mode = self.border_mode.get()

            border_selector = AssetSelector(
                assets=borders,
                mode=effective_border_mode,
                selected_names=self.border_selected,
                one_name=self.border_one.get(),
                seed_text=f"{project_name}-{stamp}-border",
            )
            texture_selector = AssetSelector(
                assets=textures,
                mode=self.texture_mode.get(),
                selected_names=self.texture_selected,
                one_name=self.texture_one.get(),
                seed_text=f"{project_name}-{stamp}-texture",
            )

            sequence_bodies = []
            sequence_motion_plan = []
            manifest_lines = []
            borders_used_summary = []
            manifest_lines.append(f"Time Frame v{VERSION}")
            manifest_lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            manifest_lines.append(f"Project name: {project_name}")
            manifest_lines.append(f"Source folder: {photos_dir.resolve()}")
            manifest_lines.append(f"Photos total: {len(photos)}")
            manifest_lines.append(f"Photos per collection: {per}")
            manifest_lines.append(f"Seconds per photo: {self.photo_seconds.get()}")
            manifest_lines.append(f"FPS: {self.fps.get()}")
            manifest_lines.append(f"Canvas: {self.canvas_w.get()}x{self.canvas_h.get()}")
            manifest_lines.append(f"Sharp opening: {self.opening_w.get()}x{self.opening_h.get()}")
            manifest_lines.append(f"Scale opening with border: True")
            manifest_lines.append(f"Border folder: {self.border_folder.get() if effective_border_mode != ASSET_MODE_NONE and borders else 'None'}")
            manifest_lines.append(f"Texture folder: {self.texture_folder.get() if self.texture_mode.get() != ASSET_MODE_NONE and textures else 'None'}")
            manifest_lines.append(f"Border changes: {self.border_timing.get()}")
            manifest_lines.append(f"Texture changes: {self.texture_timing.get()}")
            manifest_lines.append(f"Template: {template if template else 'None'}")
            manifest_lines.append(f"Copied project: {copied_project if copied_project else 'None'}")
            manifest_lines.append("Exports/renders: NOT AUTOMATED")
            manifest_lines.append("")

            for idx in range(0, len(photos), per):
                collection_num = idx // per + 1
                chunk = photos[idx:idx + per]
                seq_name = f"{FIXED_SEQUENCE_BASE_NAME} {collection_num}"
                total_sequences = max(1, int(math.ceil(len(photos) / per)))
                current_sequence = collection_num
                xml_phase_pct = ((current_sequence - 1) / total_sequences) * 100.0
                self.update_progress(weighted_percent("xml", xml_phase_pct), "Generating Premiere XML...", eta_text="--")
                border_plan = build_asset_plan_for_chunk(
                    chunk_photo_count=len(chunk),
                    global_photo_start=idx,
                    photo_duration_frames=photo_dur_frames,
                    selector=border_selector,
                    interval_frames=border_interval_frames,
                )
                texture_plan = build_asset_plan_for_chunk(
                    chunk_photo_count=len(chunk),
                    global_photo_start=idx,
                    photo_duration_frames=photo_dur_frames,
                    selector=texture_selector,
                    interval_frames=texture_interval_frames,
                )
                seq_body, border_records, motion_plan = make_sequence_xml_body(
                    photos=chunk,
                    sequence_name=seq_name,
                    seq_id=collection_num,
                    fps=int(self.fps.get()),
                    canvas_w=int(self.canvas_w.get()),
                    canvas_h=int(self.canvas_h.get()),
                    opening_w=int(self.opening_w.get()),
                    opening_h=int(self.opening_h.get()),
                    photo_seconds=float(self.photo_seconds.get()),
                    borders=borders,
                    border_minutes=DEFAULT_BORDER_MINUTES,
                    border_picker=None,
                    scale_opening_with_border=True,
                    textures=textures,
                    texture_picker=None,
                    texture_minutes=DEFAULT_TEXTURE_MINUTES,
                    border_plan=border_plan,
                    texture_plan=texture_plan,
                )
                sequence_bodies.append(seq_body)
                borders_used_summary.append((seq_name, border_records))
                sequence_motion_plan.extend([
                    {"sequenceName": seq_name, **plan} for plan in motion_plan
                ])

                manifest_lines.append(f"{seq_name}: {len(chunk)} photos")
                manifest_lines.append(f"  First: {chunk[0].name}")
                manifest_lines.append(f"  Last:  {chunk[-1].name}")
                if border_records:
                    manifest_lines.append(f"  Border slots: {len(border_records)}")
                    for slot_i, (_, _, b) in enumerate(border_records, 1):
                        manifest_lines.append(f"    {slot_i:02d}. {b.name}")
                manifest_lines.append("")
                first_photo_name = chunk[0].name if chunk else ""
                first_photo_size = get_image_size(chunk[0]) if chunk else None
                if first_photo_size:
                    first_bg_scale = max(int(self.canvas_w.get()) / first_photo_size[0], int(self.canvas_h.get()) / first_photo_size[1]) * 100.0
                    fit_scale = min(int(self.canvas_w.get()) / first_photo_size[0], int(self.canvas_h.get()) / first_photo_size[1]) * 100.0
                    photo_ratio = first_photo_size[0] / first_photo_size[1]
                    opening_ratio = 1640 / 824
                    if photo_ratio > opening_ratio:
                        first_sharp_scale = (1640 / first_photo_size[0]) * 100.0
                        self.log(f"Wide-photo V3 correction used for {first_photo_name}: photo_ratio={photo_ratio:.6f}, opening_ratio={opening_ratio:.6f}")
                    else:
                        first_sharp_scale = fit_scale * 0.764
                else:
                    first_bg_scale = 100.0
                    first_sharp_scale = 75.0
                self.log(f"Prepared {seq_name}: first photo={first_photo_name}, V1 bg scale={first_bg_scale}, V3 sharp scale={first_sharp_scale}")
                self.log(f"Prepared {seq_name} with {len(chunk)} photos and {len(border_records)} border slot(s).")

            combined_xml = xml_folder / f"{base_seq}_ALL_COLLECTIONS.xml"
            combined_xml.write_text(wrap_xmeml(sequence_bodies), encoding="utf-8")
            self.log(f"Created combined XML: {combined_xml.name}")
            self.update_progress(weighted_percent("final", 20), "Generating Premiere XML...", eta_text="--")

            xmls_for_jsx = [combined_xml]
            project_for_jsx = copied_project if copied_project else (premiere_folder / f"{source_folder_name}.prproj")
            jsx_path = premiere_folder / "import_time_frame_combined_xml.jsx"
            jsx_path.write_text(make_jsx_import_helper(xmls_for_jsx, project_for_jsx, sequence_motion_plan), encoding="utf-8")
            self.update_progress(weighted_percent("final", 55), "Creating project...", eta_text="--")

            manifest_path = run_folder / "manifest.txt"
            manifest_path.write_text("\n".join(manifest_lines), encoding="utf-8")

            readme_path = run_folder / "README_NEXT_STEPS.txt"
            readme_path.write_text(make_readme(project_name, run_folder, template, copied_project, combined_xml, jsx_path, borders_used_summary), encoding="utf-8")
            self.update_progress(weighted_percent("final", 90), "Creating project...", eta_text="--")

            self.log("Done.")
            self.log(f"Project folder: {run_folder}")
            self.log(f"Combined XML: {combined_xml}")
            self.log(f"Premiere helper JSX: {jsx_path}")
            if copied_project:
                self.log(f"Copied Premiere project: {copied_project}")
                self.log("Next in Premiere: File > Import the combined XML, or File > Scripts > Run Script File > choose import_time_frame_combined_xml.jsx")
            else:
                self.log("No Premiere template copied. Combined XML and JSX were still generated.")
            self.log("No exports/renders were started.")
            self.update_progress(100, "Time Frame Complete", eta_text="Completed", force=True)

            os.startfile(str(xml_folder))
            if self.open_project_after.get() and copied_project:
                os.startfile(str(copied_project))
        except Exception as e:
            self.log("ERROR: " + str(e))
            self.log(traceback.format_exc())
            messagebox.showerror("Error", str(e))


if __name__ == "__main__":
    try:
        App().mainloop()
    except Exception as exc:
        print("Fatal error:", exc)
        traceback.print_exc()
        input("Press Enter to close...")
