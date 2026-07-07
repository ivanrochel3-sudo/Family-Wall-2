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
import traceback
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

APP_NAME = "Family Wall App - Phase 1 + Phase 2"
VERSION = "0.7"
CONFIG_NAME = "family_wall_app_config.json"

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
BORDER_EXTS = IMAGE_EXTS | {".mp4", ".mov", ".m4v"}

DEFAULT_CANVAS_W = 1920
DEFAULT_CANVAS_H = 1080
DEFAULT_FPS = 24
DEFAULT_PHOTO_SECONDS = 20.0
DEFAULT_COLLECTION_HOURS = 10.0
DEFAULT_OPENING_W = 1428
DEFAULT_OPENING_H = 717
DEFAULT_BORDER_MINUTES = 25.0
DEFAULT_TEXTURE_MINUTES = 25.0
DEFAULT_SCALE_OPENING_WITH_BORDER = True

try:
    from PIL import Image
except Exception:
    Image = None


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
    return cleaned or "Family Wall"


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


def make_sequence_xml_body(photos, sequence_name, seq_id, fps, canvas_w, canvas_h, opening_w, opening_h, photo_seconds, borders=None, border_minutes=25.0, border_picker=None, scale_opening_with_border=True, textures=None, texture_picker=None, texture_minutes=25.0):
    dur = frames(photo_seconds, fps)
    total_frames = dur * len(photos)
    border_slot_frames = frames(border_minutes * 60.0, fps)
    texture_slot_frames = frames(texture_minutes * 60.0, fps)

    border_scale_percent, representative_border_size = representative_border_scale(borders, canvas_w, canvas_h)
    opening_multiplier = (border_scale_percent / 100.0) if (scale_opening_with_border and representative_border_size) else 1.0
    effective_opening_w = opening_w * opening_multiplier
    effective_opening_h = opening_h * opening_multiplier

    bg_scales = []
    sharp_scales = []
    media_sizes = []
    v4_scales = []
    for p in photos:
        size = get_image_size(p)
        if size:
            img_w, img_h = size
            media_sizes.append((img_w, img_h))
            bg_scales.append(scale_to_fill(img_w, img_h, canvas_w, canvas_h))
            sharp_scales.append(scale_to_fit(img_w, img_h, effective_opening_w, effective_opening_h))
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
    if textures and texture_picker and texture_slot_frames > 0 and total_frames > 0:
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
    if borders and border_picker and border_slot_frames > 0 and total_frames > 0:
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
    return f'''// Family Wall Premiere Import Helper - Phase 2 only
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
        $.writeln("Family Wall motion adjustment pass failed: " + e);
    }}

    try {{
        app.project.saveAs(projectPath);
    }} catch (e2) {{
        try {{ app.project.save(); }} catch (e3) {{}}
    }}

    alert("Family Wall import complete. XML file(s) imported: " + xmlPaths.length + "\\nNo exports were started.");
}}

importAllXmls();
'''


def make_readme(project_name, run_folder, template_path, copied_project, combined_xml, jsx_path, borders_used):
    lines = []
    lines.append(f"Family Wall App v{VERSION} - Phase 1 + Phase 2")
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
        self.project_name = tk.StringVar(value="Family Wall Project")
        self.base_sequence_name = tk.StringVar(value="Collection")

        self.canvas_w = tk.IntVar(value=int(cfg.get("canvas_w", DEFAULT_CANVAS_W)))
        self.canvas_h = tk.IntVar(value=int(cfg.get("canvas_h", DEFAULT_CANVAS_H)))
        self.fps = tk.IntVar(value=int(cfg.get("fps", DEFAULT_FPS)))
        self.photo_seconds = tk.DoubleVar(value=float(cfg.get("photo_seconds", DEFAULT_PHOTO_SECONDS)))
        self.collection_hours = tk.DoubleVar(value=float(cfg.get("collection_hours", DEFAULT_COLLECTION_HOURS)))
        self.opening_w = tk.IntVar(value=int(cfg.get("opening_w", DEFAULT_OPENING_W)))
        self.opening_h = tk.IntVar(value=int(cfg.get("opening_h", DEFAULT_OPENING_H)))
        self.border_minutes = tk.DoubleVar(value=float(cfg.get("border_minutes", DEFAULT_BORDER_MINUTES)))

        self.copy_template = tk.BooleanVar(value=True)
        self.open_project_after = tk.BooleanVar(value=True)
        self.open_folder_after = tk.BooleanVar(value=True)
        self.include_borders = tk.BooleanVar(value=bool(cfg.get("border_folder", "")))
        self.scale_opening_with_border = tk.BooleanVar(value=bool(cfg.get("scale_opening_with_border", DEFAULT_SCALE_OPENING_WITH_BORDER)))

        self.build_ui()
        self.update_math_preview()

    def build_ui(self):
        root = ttk.Frame(self)
        root.pack(fill="both", expand=True)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(13, weight=1)

        ttk.Label(root, text="Family Wall App - Phase 1 + Phase 2", font=("Segoe UI", 16, "bold")).grid(
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

        names = ttk.LabelFrame(root, text="Naming")
        names.grid(row=7, column=0, columnspan=3, sticky="ew", padx=12, pady=8)
        names.columnconfigure(1, weight=1)
        names.columnconfigure(3, weight=1)
        ttk.Label(names, text="Project name").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        ttk.Entry(names, textvariable=self.project_name).grid(row=0, column=1, sticky="ew", padx=8, pady=6)
        ttk.Label(names, text="Sequence base name").grid(row=0, column=2, sticky="w", padx=8, pady=6)
        ttk.Entry(names, textvariable=self.base_sequence_name).grid(row=0, column=3, sticky="ew", padx=8, pady=6)

        settings = ttk.LabelFrame(root, text="Collection settings")
        settings.grid(row=8, column=0, columnspan=3, sticky="ew", padx=12, pady=8)
        for c in range(8):
            settings.columnconfigure(c, weight=1)

        labels_vars = [
            ("FPS", self.fps),
            ("Seconds/photo", self.photo_seconds),
            ("Hours/collection", self.collection_hours),
            ("Border minutes", self.border_minutes),
            ("Canvas W", self.canvas_w),
            ("Canvas H", self.canvas_h),
            ("Opening W", self.opening_w),
            ("Opening H", self.opening_h),
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

        opts = ttk.LabelFrame(root, text="Phase 2 options")
        opts.grid(row=9, column=0, columnspan=3, sticky="ew", padx=12, pady=8)
        ttk.Checkbutton(opts, text="Copy Premiere template into project folder", variable=self.copy_template).grid(row=0, column=0, sticky="w", padx=8, pady=6)
        ttk.Checkbutton(opts, text="Open copied Premiere project when finished", variable=self.open_project_after).grid(row=0, column=1, sticky="w", padx=8, pady=6)
        ttk.Checkbutton(opts, text="Open output folder when finished", variable=self.open_folder_after).grid(row=0, column=2, sticky="w", padx=8, pady=6)
        ttk.Checkbutton(opts, text="Include randomized border track on V4", variable=self.include_borders).grid(row=1, column=0, sticky="w", padx=8, pady=6)
        ttk.Checkbutton(opts, text="Scale sharp opening with border", variable=self.scale_opening_with_border).grid(row=1, column=1, sticky="w", padx=8, pady=6)

        self.preview = ttk.Label(root, text="", font=("Segoe UI", 10, "bold"))
        self.preview.grid(row=10, column=0, columnspan=3, sticky="w", padx=12, pady=(4, 6))

        actions = ttk.Frame(root)
        actions.grid(row=11, column=0, columnspan=3, sticky="ew", padx=12, pady=8)
        ttk.Button(actions, text="Save Template/Settings", command=self.save_current_settings).pack(side="left")
        ttk.Button(actions, text="Create Family Wall Project", command=self.generate).pack(side="left", padx=8)
        ttk.Button(actions, text="Refresh Math", command=self.update_math_preview).pack(side="left")
        ttk.Button(actions, text="Quit", command=self.destroy).pack(side="right")

        note = ttk.Label(root, text="Premiere note: this creates one combined XML. Auto-import is attempted through a JSX helper, but Premiere may still require File > Scripts > Run Script File.")
        note.grid(row=12, column=0, columnspan=3, sticky="w", padx=12, pady=(0, 4))

        self.status = tk.Text(root, height=18, wrap="word")
        self.status.grid(row=13, column=0, columnspan=3, sticky="nsew", padx=12, pady=(4, 12))
        self.log("Ready.")
        self.log("No Phase 3: this app will not export, render, or queue anything.")
        self.log("Default: 20 seconds/photo, 10 hours/collection = 1,800 photos per collection.")
        self.log("Borders now auto-scale to fill the frame; sharp photos can scale with that border.")
        self.log("Default borders: change every 25 minutes = 24 border slots per 10-hour collection.")
        self.log("Track layout: V1 background photos, V2 blur/adjustment lane, V3 sharp photos, V4 borders.")

    def log(self, msg):
        self.status.insert("end", str(msg) + "\n")
        self.status.see("end")
        self.update_idletasks()

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
            "border_minutes": self.border_minutes.get(),
            "scale_opening_with_border": self.scale_opening_with_border.get(),
        }
        save_config(data)
        self.log(f"Settings saved: {config_path()}")
        messagebox.showinfo("Saved", "Template/settings saved for future runs.")

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
            if self.project_name.get() == "Family Wall Project":
                self.project_name.set(Path(p).name or "Family Wall Project")
            self.update_math_preview()

    def pick_borders(self):
        p = filedialog.askdirectory(title="Select border folder")
        if p:
            self.border_folder.set(p)
            self.include_borders.set(True)
            self.save_current_settings()
            self.update_math_preview()

    def pick_textures(self):
        p = filedialog.askdirectory(title="Select texture folder")
        if p:
            self.texture_folder.set(p)
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
        return max(1, int(math.ceil(float(self.collection_hours.get()) * 60.0 / float(self.border_minutes.get()))))

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
                text=f"Math: {per:,} photos/collection ≈ {length:.2f} hr. Current folder: {total:,} photos ≈ {total_hours:.2f} hr → {collections:,} sequence(s). Borders: {border_slots} slots/10hr at {self.border_minutes.get():g} min each."
            )
        except Exception:
            self.preview.config(text="Math preview unavailable. Check settings.")

    def validate(self):
        photos_dir = Path(self.photo_folder.get())
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
        if self.include_borders.get():
            if not border_dir or not border_dir.exists():
                raise ValueError("Border track is enabled. Please choose a valid border folder, or turn off border track.")
            borders = list_borders(border_dir)
            if not borders:
                raise ValueError("No supported border files found. Supported: JPG, PNG, WEBP, TIFF, MP4, MOV, M4V.")

        textures = []
        if texture_dir:
            if not texture_dir.exists():
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
        if float(self.border_minutes.get()) <= 0:
            raise ValueError("Border minutes must be greater than 0.")
        if int(self.canvas_w.get()) <= 0 or int(self.canvas_h.get()) <= 0:
            raise ValueError("Canvas dimensions must be greater than 0.")
        if int(self.opening_w.get()) <= 0 or int(self.opening_h.get()) <= 0:
            raise ValueError("Opening dimensions must be greater than 0.")
        if int(self.opening_w.get()) > int(self.canvas_w.get()) or int(self.opening_h.get()) > int(self.canvas_h.get()):
            raise ValueError("Opening dimensions should fit inside the canvas.")
        return photos, photos_dir, output_root, template, borders, textures

    def generate(self):
        try:
            self.save_current_settings()
            self.log("Creating Family Wall project...")
            photos, photos_dir, output_root, template, borders, textures = self.validate()
            self.update_math_preview()

            project_name = safe_filename(self.project_name.get())
            if not project_name:
                project_name = safe_filename(photos_dir.name)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            run_folder = output_root / f"{project_name}_{stamp}"

            xml_folder = run_folder / "XML"
            premiere_folder = run_folder / "Premiere"
            for p in [xml_folder, premiere_folder]:
                p.mkdir(parents=True, exist_ok=True)

            copied_project = None
            if self.copy_template.get() and template:
                copied_project = premiere_folder / f"{project_name}.prproj"
                shutil.copy2(template, copied_project)
                self.log(f"Copied Premiere template → {copied_project.name}")

            per = self.photos_per_collection()
            base_seq = safe_filename(self.base_sequence_name.get() or "Collection")
            border_picker = BorderPicker(borders, seed_text=f"{project_name}-{stamp}") if borders else None
            texture_picker = TexturePicker(textures, seed_text=f"{project_name}-{stamp}-texture") if textures else None

            sequence_bodies = []
            sequence_motion_plan = []
            manifest_lines = []
            borders_used_summary = []
            manifest_lines.append(f"Family Wall App v{VERSION}")
            manifest_lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            manifest_lines.append(f"Project name: {project_name}")
            manifest_lines.append(f"Source folder: {photos_dir.resolve()}")
            manifest_lines.append(f"Photos total: {len(photos)}")
            manifest_lines.append(f"Photos per collection: {per}")
            manifest_lines.append(f"Seconds per photo: {self.photo_seconds.get()}")
            manifest_lines.append(f"FPS: {self.fps.get()}")
            manifest_lines.append(f"Canvas: {self.canvas_w.get()}x{self.canvas_h.get()}")
            manifest_lines.append(f"Sharp opening: {self.opening_w.get()}x{self.opening_h.get()}")
            manifest_lines.append(f"Scale opening with border: {self.scale_opening_with_border.get()}")
            manifest_lines.append(f"Border folder: {self.border_folder.get() if borders else 'None'}")
            manifest_lines.append(f"Texture folder: {self.texture_folder.get() if textures else 'None'}")
            manifest_lines.append(f"Border change interval: {self.border_minutes.get()} minutes")
            manifest_lines.append(f"Template: {template if template else 'None'}")
            manifest_lines.append(f"Copied project: {copied_project if copied_project else 'None'}")
            manifest_lines.append("Exports/renders: NOT AUTOMATED")
            manifest_lines.append("")

            for idx in range(0, len(photos), per):
                collection_num = idx // per + 1
                chunk = photos[idx:idx + per]
                seq_name = f"{self.base_sequence_name.get()} {collection_num}"
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
                    border_minutes=float(self.border_minutes.get()),
                    border_picker=border_picker,
                    scale_opening_with_border=self.scale_opening_with_border.get(),
                    textures=textures,
                    texture_picker=texture_picker,
                    texture_minutes=DEFAULT_TEXTURE_MINUTES,
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
                self.log(f"Prepared {seq_name} with {len(chunk)} photos and {len(border_records)} border slot(s).")

            combined_xml = xml_folder / f"{base_seq}_ALL_COLLECTIONS.xml"
            combined_xml.write_text(wrap_xmeml(sequence_bodies), encoding="utf-8")
            self.log(f"Created combined XML: {combined_xml.name}")

            xmls_for_jsx = [combined_xml]
            project_for_jsx = copied_project if copied_project else (premiere_folder / f"{project_name}.prproj")
            jsx_path = premiere_folder / "import_family_wall_combined_xml.jsx"
            jsx_path.write_text(make_jsx_import_helper(xmls_for_jsx, project_for_jsx, sequence_motion_plan), encoding="utf-8")

            manifest_path = run_folder / "manifest.txt"
            manifest_path.write_text("\n".join(manifest_lines), encoding="utf-8")

            readme_path = run_folder / "README_NEXT_STEPS.txt"
            readme_path.write_text(make_readme(project_name, run_folder, template, copied_project, combined_xml, jsx_path, borders_used_summary), encoding="utf-8")

            self.log("Done.")
            self.log(f"Project folder: {run_folder}")
            self.log(f"Combined XML: {combined_xml}")
            self.log(f"Premiere helper JSX: {jsx_path}")
            if copied_project:
                self.log(f"Copied Premiere project: {copied_project}")
                self.log("Next in Premiere: File > Import the combined XML, or File > Scripts > Run Script File > choose import_family_wall_combined_xml.jsx")
            else:
                self.log("No Premiere template copied. Combined XML and JSX were still generated.")
            self.log("No exports/renders were started.")

            if self.open_folder_after.get():
                os.startfile(str(run_folder))
            if self.open_project_after.get() and copied_project:
                os.startfile(str(copied_project))

            messagebox.showinfo("Created", "Created 1 combined XML containing all collection sequences.\n\nNo exports were started.")
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
