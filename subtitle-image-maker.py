# -*- coding: utf-8 -*-
"""
Subtitle Image Maker v6

1行につき1枚の字幕PNGを生成するGUIツール。
Pillow の textbbox() を使い、フォントの見えない上下余白ではなく
実際の描画範囲を基準に上下中央を合わせる。

v6 追加機能:
- 固定サイズの透過キャンバス出力
- 文字の前に透過PNGアイコンを追加
- アイコンサイズモード（文字高 / ボックス高 / 指定px）
- 背景ボックスの固定高さ指定
- 全テキストを調べて最大ボックス高さを自動設定
- 全テキストを調べて最大テキスト幅を自動設定
- PNG書き出しボタンを強調表示
- ファイル名にテキスト内容を追加するオプション

必要ライブラリ:
    pip install pillow

作成: Chappy
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import tkinter as tk
from tkinter import filedialog, messagebox, colorchooser
from tkinter import ttk

try:
    from PIL import Image, ImageDraw, ImageFont, ImageTk
except ImportError as exc:
    raise SystemExit(
        "Pillow が見つかりません。\n"
        "コマンドプロンプトで pip install pillow を実行してください。"
    ) from exc


APP_NAME = "字幕画像メーカー v6"
CONFIG_NAME = "subtitle-image-maker-config.json"
ICON_SIZE_MODE_LABELS = {
    "text": "文字高基準",
    "box": "ボックス高基準",
    "manual": "指定px",
}
ICON_SIZE_MODE_VALUES = tuple(ICON_SIZE_MODE_LABELS.values())
ICON_SIZE_MODE_REVERSE = {v: k for k, v in ICON_SIZE_MODE_LABELS.items()}


# -----------------------------------------------------------------------------
# Utility
# -----------------------------------------------------------------------------


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def config_path() -> Path:
    return app_dir() / CONFIG_NAME


def clamp(value: int, min_value: int, max_value: int) -> int:
    return max(min_value, min(value, max_value))


def parse_int(value: str, default: int = 0, min_value: Optional[int] = None, max_value: Optional[int] = None) -> int:
    try:
        num = int(str(value).strip())
    except Exception:
        num = default
    if min_value is not None:
        num = max(min_value, num)
    if max_value is not None:
        num = min(max_value, num)
    return num


def parse_optional_int(value: str) -> Optional[int]:
    s = str(value).strip()
    if not s:
        return None
    try:
        num = int(s)
        return num if num > 0 else None
    except Exception:
        return None


def hex_to_rgb(hex_color: str, fallback: Tuple[int, int, int] = (255, 255, 255)) -> Tuple[int, int, int]:
    s = str(hex_color).strip()
    if s.startswith("#"):
        s = s[1:]
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    if len(s) != 6:
        return fallback
    try:
        return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except Exception:
        return fallback


def normalize_hex(hex_color: str, fallback: str = "#FFFFFF") -> str:
    r, g, b = hex_to_rgb(hex_color, hex_to_rgb(fallback))
    return f"#{r:02X}{g:02X}{b:02X}"


def choose_default_font() -> str:
    candidates: List[Path] = []

    if os.name == "nt":
        win_fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        candidates.extend([
            win_fonts / "meiryo.ttc",
            win_fonts / "meiryob.ttc",
            win_fonts / "msgothic.ttc",
            win_fonts / "consola.ttf",
            win_fonts / "arial.ttf",
        ])
    elif sys.platform == "darwin":
        candidates.extend([
            Path("/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc"),
            Path("/System/Library/Fonts/Helvetica.ttc"),
            Path("/Library/Fonts/Arial.ttf"),
        ])
    else:
        candidates.extend([
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        ])

    for p in candidates:
        if p.exists():
            return str(p)
    return ""


def safe_open_folder(path: Path) -> None:
    try:
        if os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            import subprocess
            subprocess.Popen(["open", str(path)])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as exc:
        messagebox.showerror("フォルダを開けません", str(exc))


def safe_filename_text(text: str, max_len: int = 80) -> str:
    """ファイル名に使えない文字を置換し、長すぎる場合は切り詰める。"""
    s = str(text).strip()
    if not s:
        return ""
    forbidden = '<>:"/\\|?*'
    out = []
    for ch in s:
        code = ord(ch)
        if ch in forbidden or code < 32:
            out.append("_")
        elif ch in "\t\r\n":
            out.append(" ")
        else:
            out.append(ch)
    s = "".join(out)
    s = " ".join(s.split())
    s = s.rstrip(" .")
    if len(s) > max_len:
        s = s[:max_len].rstrip(" .")
    return s


# -----------------------------------------------------------------------------
# Rendering
# -----------------------------------------------------------------------------


@dataclass
class RenderConfig:
    font_path: str
    font_size: int = 42
    text_color: str = "#FF008C"

    outline_enabled: bool = True
    outline_color: str = "#1200FF"
    outline_width: int = 2

    bg_enabled: bool = True
    bg_color: str = "#000000"
    bg_alpha: int = 255
    corner_radius: int = 0
    fixed_box_height: str = ""

    padding_top: int = 16
    padding_bottom: int = 16
    padding_left: int = 80
    padding_right: int = 80

    align: str = "center"  # left / center / right
    fixed_width: str = ""  # px. blank = auto.
    antialias_scale: int = 1

    fixed_canvas_enabled: bool = False
    canvas_width: int = 1920
    canvas_height: int = 180

    icon_enabled: bool = False
    icon_path: str = ""
    icon_gap: int = 16
    icon_size_mode: str = "text"  # text / box / manual
    icon_manual_height: int = 48


def load_font(font_path: str, size: int) -> ImageFont.FreeTypeFont:
    if font_path and Path(font_path).exists():
        return ImageFont.truetype(font_path, size=size)
    default = choose_default_font()
    if default:
        return ImageFont.truetype(default, size=size)
    return ImageFont.load_default()


def text_bbox(text: str, font: ImageFont.ImageFont, stroke_width: int) -> Tuple[int, int, int, int]:
    dummy = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    draw = ImageDraw.Draw(dummy)
    try:
        return draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    except TypeError:
        bbox = draw.textbbox((0, 0), text, font=font)
        return (
            bbox[0] - stroke_width,
            bbox[1] - stroke_width,
            bbox[2] + stroke_width,
            bbox[3] + stroke_width,
        )


def load_and_resize_icon(path: str, target_height: int) -> Optional[Image.Image]:
    if not path:
        return None
    p = Path(path)
    if not p.exists() or target_height <= 0:
        return None
    try:
        icon = Image.open(p).convert("RGBA")
    except Exception:
        return None

    w, h = icon.size
    if w <= 0 or h <= 0:
        return None

    scale = target_height / h
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    return icon.resize((new_w, new_h), Image.Resampling.LANCZOS)


def estimate_required_box_height(text: str, cfg: RenderConfig) -> int:
    """現在の設定で、この1行を収めるのに必要なボックス高さ(px)を推定する。
    戻り値は最終出力時の実px（antialias前の値）。
    """
    scale = clamp(int(cfg.antialias_scale), 1, 4)
    font_size = max(1, cfg.font_size * scale)
    font = load_font(cfg.font_path, font_size)
    stroke_w = cfg.outline_width * scale if cfg.outline_enabled else 0
    bbox = text_bbox(text, font, stroke_w)
    text_h = max(1, bbox[3] - bbox[1])

    pad_t = max(0, cfg.padding_top * scale)
    pad_b = max(0, cfg.padding_bottom * scale)

    icon_h = 0
    if cfg.icon_enabled and cfg.icon_path.strip():
        mode = cfg.icon_size_mode if cfg.icon_size_mode in {"text", "box", "manual"} else "text"
        if mode == "manual":
            icon_h = max(1, cfg.icon_manual_height * scale)
        elif mode == "text":
            icon_h = text_h
        else:
            # ボックス高基準は高さ決定後にアイコンを合わせるので、
            # 自動計算時は文字側を基準にする。
            icon_h = 0

    needed_scaled = max(text_h, icon_h) + pad_t + pad_b
    needed_px = max(1, (needed_scaled + scale - 1) // scale)
    return needed_px


def estimate_required_text_width(text: str, cfg: RenderConfig) -> int:
    """現在の設定で、この1行を収めるのに必要なテキスト幅(px)を推定する。
    戻り値は fixed_width 欄に入れる想定の値（padding を含まない内容幅）。
    """
    scale = clamp(int(cfg.antialias_scale), 1, 4)
    font_size = max(1, cfg.font_size * scale)
    font = load_font(cfg.font_path, font_size)
    stroke_w = cfg.outline_width * scale if cfg.outline_enabled else 0
    bbox = text_bbox(text, font, stroke_w)
    text_w = max(1, bbox[2] - bbox[0])
    text_h = max(1, bbox[3] - bbox[1])

    icon_w = 0
    if cfg.icon_enabled and cfg.icon_path.strip():
        mode = cfg.icon_size_mode if cfg.icon_size_mode in {"text", "box", "manual"} else "text"
        if mode == "manual":
            target_icon_h = max(1, cfg.icon_manual_height * scale)
        elif mode == "box":
            fixed_box_height_px = parse_optional_int(cfg.fixed_box_height)
            if fixed_box_height_px is not None:
                pad_t = max(0, cfg.padding_top * scale)
                pad_b = max(0, cfg.padding_bottom * scale)
                target_icon_h = max(1, fixed_box_height_px * scale - pad_t - pad_b)
            else:
                target_icon_h = text_h
        else:
            target_icon_h = text_h

        icon_img = load_and_resize_icon(cfg.icon_path.strip(), target_icon_h)
        if icon_img is not None:
            icon_w = icon_img.size[0]

    gap = max(0, cfg.icon_gap * scale) if icon_w > 0 else 0
    needed_scaled = icon_w + gap + text_w
    needed_px = max(1, (needed_scaled + scale - 1) // scale)
    return needed_px


def render_subtitle_image(text: str, cfg: RenderConfig) -> Tuple[Image.Image, List[str]]:
    warnings: List[str] = []

    scale = clamp(int(cfg.antialias_scale), 1, 4)
    font_size = max(1, cfg.font_size * scale)
    font = load_font(cfg.font_path, font_size)

    stroke_w = cfg.outline_width * scale if cfg.outline_enabled else 0
    bbox = text_bbox(text, font, stroke_w)
    text_w = max(1, bbox[2] - bbox[0])
    text_h = max(1, bbox[3] - bbox[1])

    pad_t = max(0, cfg.padding_top * scale)
    pad_b = max(0, cfg.padding_bottom * scale)
    pad_l = max(0, cfg.padding_left * scale)
    pad_r = max(0, cfg.padding_right * scale)
    icon_gap = max(0, cfg.icon_gap * scale)

    fixed_box_height_px = parse_optional_int(cfg.fixed_box_height)
    fixed_box_height_scaled = fixed_box_height_px * scale if fixed_box_height_px else None

    icon_img: Optional[Image.Image] = None
    icon_w = 0
    icon_h = 0

    if cfg.icon_enabled:
        if not cfg.icon_path.strip():
            warnings.append("アイコンが有効ですが、アイコン画像が未指定です。")
        else:
            mode = cfg.icon_size_mode if cfg.icon_size_mode in {"text", "box", "manual"} else "text"
            if mode == "box":
                if fixed_box_height_scaled is None:
                    warnings.append("アイコンのサイズモードがボックス高基準ですが、固定ボックス高が未指定のため文字高基準で処理します。")
                    target_icon_h = text_h
                else:
                    target_icon_h = max(1, fixed_box_height_scaled - pad_t - pad_b)
            elif mode == "manual":
                target_icon_h = max(1, cfg.icon_manual_height * scale)
            else:
                target_icon_h = text_h

            icon_img = load_and_resize_icon(cfg.icon_path.strip(), target_icon_h)
            if icon_img is None:
                warnings.append("アイコン画像を読み込めませんでした。")
            else:
                icon_w, icon_h = icon_img.size

    inline_gap = icon_gap if icon_img is not None else 0
    inline_w = icon_w + inline_gap + text_w
    inline_h = max(text_h, icon_h)

    content_target_w = inline_w
    fixed_width_px = parse_optional_int(cfg.fixed_width)
    if fixed_width_px is not None:
        content_target_w = max(inline_w, fixed_width_px * scale)
        if inline_w > fixed_width_px * scale:
            warnings.append(f"固定幅 {fixed_width_px}px より内容が長いため、固定幅内に収まりません。")

    box_w = max(1, content_target_w + pad_l + pad_r)

    if fixed_box_height_scaled is not None:
        box_h = max(1, fixed_box_height_scaled)
        needed_h = inline_h + pad_t + pad_b
        if needed_h > box_h:
            warnings.append(f"固定ボックス高 {fixed_box_height_px}px に内容が収まりません。")
    else:
        box_h = max(1, inline_h + pad_t + pad_b)

    if cfg.fixed_canvas_enabled:
        img_w = max(1, cfg.canvas_width * scale)
        img_h = max(1, cfg.canvas_height * scale)
        if box_w > img_w or box_h > img_h:
            warnings.append(f"固定キャンバス {cfg.canvas_width}x{cfg.canvas_height}px に内容が収まりません。")
        align = cfg.align if cfg.align in {"left", "center", "right"} else "center"
        if align == "left":
            box_x = 0
        elif align == "right":
            box_x = max(0, img_w - box_w)
        else:
            box_x = max(0, (img_w - box_w) // 2)
        box_y = max(0, (img_h - box_h) // 2)
    else:
        img_w = box_w
        img_h = box_h
        box_x = 0
        box_y = 0

    image = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    if cfg.bg_enabled:
        br, bg, bb = hex_to_rgb(cfg.bg_color, (0, 0, 0))
        bg_alpha = clamp(int(cfg.bg_alpha), 0, 255)
        radius = max(0, int(cfg.corner_radius) * scale)
        rect = (box_x, box_y, box_x + box_w - 1, box_y + box_h - 1)
        if radius > 0:
            draw.rounded_rectangle(rect, radius=radius, fill=(br, bg, bb, bg_alpha))
        else:
            draw.rectangle(rect, fill=(br, bg, bb, bg_alpha))

    inner_x = box_x + pad_l
    inner_y = box_y + pad_t
    content_w = max(1, box_w - pad_l - pad_r)
    available_h = max(1, box_h - pad_t - pad_b)

    align = cfg.align if cfg.align in {"left", "center", "right"} else "center"
    if align == "left":
        inline_x = inner_x
    elif align == "right":
        inline_x = inner_x + max(0, content_w - inline_w)
    else:
        inline_x = inner_x + max(0, (content_w - inline_w) // 2)

    inline_y = inner_y + max(0, (available_h - inline_h) // 2)
    icon_x = inline_x
    icon_y = inline_y + max(0, (inline_h - icon_h) // 2)
    text_x = inline_x + (icon_w + inline_gap if icon_img is not None else 0) - bbox[0]
    text_y = inline_y + max(0, (inline_h - text_h) // 2) - bbox[1]

    tr, tg, tb = hex_to_rgb(cfg.text_color, (255, 255, 255))
    sr, sg, sb = hex_to_rgb(cfg.outline_color, (0, 0, 0))

    if icon_img is not None:
        image.alpha_composite(icon_img, (icon_x, icon_y))

    if cfg.outline_enabled and stroke_w > 0:
        draw.text(
            (text_x, text_y),
            text,
            font=font,
            fill=(tr, tg, tb, 255),
            stroke_width=stroke_w,
            stroke_fill=(sr, sg, sb, 255),
        )
    else:
        draw.text((text_x, text_y), text, font=font, fill=(tr, tg, tb, 255))

    if scale > 1:
        target_size = (max(1, img_w // scale), max(1, img_h // scale))
        image = image.resize(target_size, Image.Resampling.LANCZOS)

    return image, warnings


def make_checkerboard(size: Tuple[int, int], cell: int = 12) -> Image.Image:
    w, h = size
    img = Image.new("RGB", (w, h), (240, 240, 240))
    draw = ImageDraw.Draw(img)
    c1 = (235, 235, 235)
    c2 = (205, 205, 205)
    for y in range(0, h, cell):
        for x in range(0, w, cell):
            draw.rectangle((x, y, x + cell - 1, y + cell - 1), fill=c1 if ((x // cell + y // cell) % 2 == 0) else c2)
    return img


def preview_composite(src: Image.Image, max_size: Tuple[int, int]) -> Image.Image:
    img = src.copy()
    img.thumbnail(max_size, Image.Resampling.LANCZOS)
    board = make_checkerboard(img.size)
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    board.paste(img, (0, 0), img)
    return board


# -----------------------------------------------------------------------------
# GUI
# -----------------------------------------------------------------------------


class SubtitleImageMakerApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_NAME)
        self.minsize(1080, 720)
        self.geometry("1180x780")

        self.preview_photo: Optional[ImageTk.PhotoImage] = None
        self.preview_after_id: Optional[str] = None
        self.last_output_dir: Optional[Path] = None

        self.vars = self._create_vars()
        self._build_ui()
        self._load_config()
        self._wire_traces()
        self.after(200, self.update_preview)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _create_vars(self) -> dict:
        return {
            "font_path": tk.StringVar(value=choose_default_font()),
            "font_size": tk.StringVar(value="42"),
            "text_color": tk.StringVar(value="#FF008C"),
            "outline_enabled": tk.BooleanVar(value=True),
            "outline_color": tk.StringVar(value="#1200FF"),
            "outline_width": tk.StringVar(value="2"),
            "bg_enabled": tk.BooleanVar(value=True),
            "bg_color": tk.StringVar(value="#000000"),
            "bg_alpha": tk.StringVar(value="255"),
            "corner_radius": tk.StringVar(value="0"),
            "fixed_box_height": tk.StringVar(value=""),
            "padding_top": tk.StringVar(value="16"),
            "padding_bottom": tk.StringVar(value="16"),
            "padding_left": tk.StringVar(value="80"),
            "padding_right": tk.StringVar(value="80"),
            "align": tk.StringVar(value="center"),
            "fixed_width": tk.StringVar(value=""),
            "antialias_scale": tk.StringVar(value="1"),
            "fixed_canvas_enabled": tk.BooleanVar(value=False),
            "canvas_width": tk.StringVar(value="1920"),
            "canvas_height": tk.StringVar(value="180"),
            "icon_enabled": tk.BooleanVar(value=False),
            "icon_path": tk.StringVar(value=""),
            "icon_gap": tk.StringVar(value="16"),
            "icon_size_mode": tk.StringVar(value=ICON_SIZE_MODE_LABELS["text"]),
            "icon_manual_height": tk.StringVar(value="48"),
            "skip_empty": tk.BooleanVar(value=True),
            "output_dir": tk.StringVar(value=str(Path.home() / "Desktop")),
            "prefix": tk.StringVar(value="text-"),
            "digits": tk.StringVar(value="3"),
            "filename_include_text": tk.BooleanVar(value=False),
            "overwrite_confirm": tk.BooleanVar(value=True),
            "preview_line_no": tk.StringVar(value="1"),
        }

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=8)
        root.pack(fill=tk.BOTH, expand=True)

        paned = ttk.PanedWindow(root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        left_outer = ttk.Frame(paned)
        right = ttk.Frame(paned)
        paned.add(left_outer, weight=0)
        paned.add(right, weight=1)

        canvas = tk.Canvas(left_outer, highlightthickness=0, width=450)
        scrollbar = ttk.Scrollbar(left_outer, orient=tk.VERTICAL, command=canvas.yview)
        self.control_frame = ttk.Frame(canvas)
        self.control_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.control_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self._build_controls(self.control_frame)
        self._build_text_preview_area(right)

    def _build_controls(self, parent: ttk.Frame) -> None:
        lf_font = ttk.LabelFrame(parent, text="文字・フォント", padding=8)
        lf_font.pack(fill=tk.X, padx=4, pady=4)
        ttk.Label(lf_font, text="フォント").grid(row=0, column=0, sticky="w")
        ttk.Entry(lf_font, textvariable=self.vars["font_path"], width=34).grid(row=1, column=0, columnspan=3, sticky="ew", pady=(2, 4))
        ttk.Button(lf_font, text="選択", command=self.choose_font).grid(row=1, column=3, padx=(4, 0), sticky="ew")
        ttk.Label(lf_font, text="サイズ").grid(row=2, column=0, sticky="w")
        ttk.Entry(lf_font, textvariable=self.vars["font_size"], width=8).grid(row=2, column=1, sticky="w", padx=(4, 12))
        self._color_row(lf_font, 3, "文字色", "text_color")
        ttk.Label(lf_font, text="アンチエイリアス").grid(row=4, column=0, sticky="w", pady=(6, 0))
        ttk.Combobox(lf_font, textvariable=self.vars["antialias_scale"], values=("1", "2", "4"), width=6, state="readonly").grid(row=4, column=1, sticky="w", padx=(4, 0), pady=(6, 0))
        ttk.Label(lf_font, text="1=標準 / 2,4=高品質").grid(row=4, column=2, columnspan=2, sticky="w", padx=(8, 0), pady=(6, 0))
        lf_font.columnconfigure(2, weight=1)

        lf_outline = ttk.LabelFrame(parent, text="アウトライン", padding=8)
        lf_outline.pack(fill=tk.X, padx=4, pady=4)
        ttk.Checkbutton(lf_outline, text="アウトラインを付ける", variable=self.vars["outline_enabled"]).grid(row=0, column=0, columnspan=4, sticky="w")
        self._color_row(lf_outline, 1, "色", "outline_color")
        ttk.Label(lf_outline, text="太さ px").grid(row=2, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(lf_outline, textvariable=self.vars["outline_width"], width=8).grid(row=2, column=1, sticky="w", padx=(4, 0), pady=(4, 0))
        ttk.Label(lf_outline, text="太すぎると文字内部が潰れやすいので注意").grid(row=3, column=0, columnspan=4, sticky="w", pady=(6, 0))

        lf_bg = ttk.LabelFrame(parent, text="背景ボックス", padding=8)
        lf_bg.pack(fill=tk.X, padx=4, pady=4)
        ttk.Checkbutton(lf_bg, text="背景を描画する", variable=self.vars["bg_enabled"]).grid(row=0, column=0, columnspan=4, sticky="w")
        self._color_row(lf_bg, 1, "背景色", "bg_color")
        ttk.Label(lf_bg, text="透明度 0-255").grid(row=2, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(lf_bg, textvariable=self.vars["bg_alpha"], width=8).grid(row=2, column=1, sticky="w", padx=(4, 12), pady=(4, 0))
        ttk.Label(lf_bg, text="角丸 px").grid(row=2, column=2, sticky="w", pady=(4, 0))
        ttk.Entry(lf_bg, textvariable=self.vars["corner_radius"], width=8).grid(row=2, column=3, sticky="w", padx=(4, 0), pady=(4, 0))
        ttk.Label(lf_bg, text="ボックス高さ px（空欄=自動）").grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Entry(lf_bg, textvariable=self.vars["fixed_box_height"], width=10).grid(row=3, column=2, sticky="w", padx=(4, 0), pady=(4, 0))
        btn_box_h = ttk.Frame(lf_bg)
        btn_box_h.grid(row=3, column=3, sticky="w", padx=(6, 0), pady=(4, 0))
        ttk.Button(btn_box_h, text="自動", command=self.auto_set_box_height).pack(side=tk.LEFT)
        ttk.Button(btn_box_h, text="解除", command=self.clear_box_height, width=6).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Label(lf_bg, text="[自動] は全テキストを調べて最大必要高さを設定。指定時はその高さの中で内容を縦中央配置").grid(row=4, column=0, columnspan=4, sticky="w", pady=(6, 0))
        lf_bg.columnconfigure(2, weight=1)

        lf_icon = ttk.LabelFrame(parent, text="先頭アイコン", padding=8)
        lf_icon.pack(fill=tk.X, padx=4, pady=4)
        ttk.Checkbutton(lf_icon, text="透過PNGアイコンを前に付ける", variable=self.vars["icon_enabled"]).grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Label(lf_icon, text="アイコン画像").grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(lf_icon, textvariable=self.vars["icon_path"], width=34).grid(row=2, column=0, columnspan=3, sticky="ew", pady=(2, 4))
        ttk.Button(lf_icon, text="選択", command=self.choose_icon).grid(row=2, column=3, padx=(4, 0), sticky="ew")
        ttk.Label(lf_icon, text="文字との余白 px").grid(row=3, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(lf_icon, textvariable=self.vars["icon_gap"], width=8).grid(row=3, column=1, sticky="w", padx=(4, 12), pady=(4, 0))
        ttk.Label(lf_icon, text="サイズ基準").grid(row=4, column=0, sticky="w", pady=(6, 0))
        ttk.Combobox(lf_icon, textvariable=self.vars["icon_size_mode"], values=ICON_SIZE_MODE_VALUES, width=14, state="readonly").grid(row=4, column=1, sticky="w", padx=(4, 12), pady=(6, 0))
        ttk.Label(lf_icon, text="指定高さ px").grid(row=4, column=2, sticky="w", pady=(6, 0))
        ttk.Entry(lf_icon, textvariable=self.vars["icon_manual_height"], width=8).grid(row=4, column=3, sticky="w", padx=(4, 0), pady=(6, 0))
        ttk.Label(lf_icon, text="ボックス高基準は固定ボックス高があるときに安定します。 ").grid(row=5, column=0, columnspan=4, sticky="w", pady=(6, 0))
        lf_icon.columnconfigure(2, weight=1)

        lf_pad = ttk.LabelFrame(parent, text="余白 px", padding=8)
        lf_pad.pack(fill=tk.X, padx=4, pady=4)
        fields = [("上", "padding_top"), ("下", "padding_bottom"), ("左", "padding_left"), ("右", "padding_right")]
        for i, (label, key) in enumerate(fields):
            r = i // 2
            c = (i % 2) * 2
            ttk.Label(lf_pad, text=label).grid(row=r, column=c, sticky="w", pady=2)
            ttk.Entry(lf_pad, textvariable=self.vars[key], width=8).grid(row=r, column=c + 1, sticky="w", padx=(4, 16), pady=2)
        ttk.Label(lf_pad, text="上下中央は実際の文字描画範囲 bbox 基準で計算").grid(row=2, column=0, columnspan=4, sticky="w", pady=(6, 0))

        lf_align = ttk.LabelFrame(parent, text="配置・幅", padding=8)
        lf_align.pack(fill=tk.X, padx=4, pady=4)
        ttk.Radiobutton(lf_align, text="左詰め", value="left", variable=self.vars["align"]).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(lf_align, text="中央", value="center", variable=self.vars["align"]).grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(lf_align, text="右詰め", value="right", variable=self.vars["align"]).grid(row=0, column=2, sticky="w")
        ttk.Label(lf_align, text="テキスト幅 px（空欄=自動）").grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Entry(lf_align, textvariable=self.vars["fixed_width"], width=12).grid(row=1, column=2, sticky="w", padx=(4, 0), pady=(8, 0))
        ttk.Button(lf_align, text="自動", command=self.auto_set_text_width, width=6).grid(row=1, column=3, sticky="w", padx=(6, 0), pady=(8, 0))
        ttk.Label(lf_align, text="[自動] は全テキストを調べて最大必要幅を設定。固定幅が短い場合は警告。自動縮小なし。").grid(row=2, column=0, columnspan=4, sticky="w", pady=(6, 0))

        lf_canvas = ttk.LabelFrame(parent, text="固定キャンバス（透過）", padding=8)
        lf_canvas.pack(fill=tk.X, padx=4, pady=4)
        ttk.Checkbutton(lf_canvas, text="固定サイズの透過画像にする", variable=self.vars["fixed_canvas_enabled"]).grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Label(lf_canvas, text="幅 px").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(lf_canvas, textvariable=self.vars["canvas_width"], width=10).grid(row=1, column=1, sticky="w", padx=(4, 12), pady=(6, 0))
        ttk.Label(lf_canvas, text="高さ px").grid(row=1, column=2, sticky="w", pady=(6, 0))
        ttk.Entry(lf_canvas, textvariable=self.vars["canvas_height"], width=10).grid(row=1, column=3, sticky="w", padx=(4, 0), pady=(6, 0))
        ttk.Label(lf_canvas, text="外側キャンバスは透過。内容全体は縦中央、横位置は左/中央/右詰めに従います。 ").grid(row=2, column=0, columnspan=4, sticky="w", pady=(6, 0))

        lf_out = ttk.LabelFrame(parent, text="出力", padding=8)
        lf_out.pack(fill=tk.X, padx=4, pady=4)
        ttk.Label(lf_out, text="出力フォルダ").grid(row=0, column=0, sticky="w")
        ttk.Entry(lf_out, textvariable=self.vars["output_dir"], width=34).grid(row=1, column=0, columnspan=3, sticky="ew", pady=(2, 4))
        ttk.Button(lf_out, text="選択", command=self.choose_output_dir).grid(row=1, column=3, padx=(4, 0), sticky="ew")
        ttk.Label(lf_out, text="接頭語").grid(row=2, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(lf_out, textvariable=self.vars["prefix"], width=14).grid(row=2, column=1, sticky="w", padx=(4, 12), pady=(4, 0))
        ttk.Label(lf_out, text="桁数").grid(row=2, column=2, sticky="w", pady=(4, 0))
        ttk.Entry(lf_out, textvariable=self.vars["digits"], width=6).grid(row=2, column=3, sticky="w", padx=(4, 0), pady=(4, 0))
        ttk.Checkbutton(lf_out, text="空行をスキップ", variable=self.vars["skip_empty"]).grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Checkbutton(lf_out, text="上書き前に確認", variable=self.vars["overwrite_confirm"]).grid(row=3, column=2, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Checkbutton(lf_out, text="ファイル名にテキストを含める", variable=self.vars["filename_include_text"]).grid(row=4, column=0, columnspan=4, sticky="w", pady=(6, 0))
        ttk.Label(lf_out, text="例: text-001てきすと.png / 禁止文字は自動で置換").grid(row=5, column=0, columnspan=4, sticky="w", pady=(2, 0))
        btns = ttk.Frame(lf_out)
        btns.grid(row=6, column=0, columnspan=4, sticky="ew", pady=(10, 0))
        tk.Button(
            btns,
            text="PNGを書き出し",
            command=self.export_images,
            bg="#1E88E5",
            fg="white",
            activebackground="#1565C0",
            activeforeground="white",
            relief=tk.RAISED,
            font=("", 10, "bold"),
            padx=10,
            pady=2,
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(btns, text="出力フォルダを開く", command=self.open_output_dir).pack(side=tk.LEFT, padx=(6, 0))
        lf_out.columnconfigure(2, weight=1)

        lf_setting = ttk.LabelFrame(parent, text="設定", padding=8)
        lf_setting.pack(fill=tk.X, padx=4, pady=4)
        ttk.Button(lf_setting, text="設定を保存", command=self.save_config).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(lf_setting, text="設定を読み込み直す", command=self._load_config).pack(side=tk.LEFT, padx=(6, 0), fill=tk.X, expand=True)

    def _build_text_preview_area(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        parent.rowconfigure(3, weight=1)

        top = ttk.Frame(parent)
        top.grid(row=0, column=0, sticky="ew", padx=(8, 0), pady=(0, 6))
        top.columnconfigure(2, weight=1)
        ttk.Label(top, text="プレビュー行").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.vars["preview_line_no"], width=6).grid(row=0, column=1, padx=(4, 8), sticky="w")
        ttk.Button(top, text="プレビュー更新", command=self.update_preview).grid(row=0, column=2, sticky="w")

        preview_frame = ttk.LabelFrame(parent, text="プレビュー（外側はチェック柄＝透過確認用）", padding=8)
        preview_frame.grid(row=1, column=0, sticky="nsew", padx=(8, 0), pady=(0, 8))
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)
        self.preview_label = ttk.Label(preview_frame, anchor="center")
        self.preview_label.grid(row=0, column=0, sticky="nsew")

        text_label_frame = ttk.Frame(parent)
        text_label_frame.grid(row=2, column=0, sticky="ew", padx=(8, 0))
        text_label_frame.columnconfigure(0, weight=1)
        ttk.Label(text_label_frame, text="テキスト入力：1行につき1画像").grid(row=0, column=0, sticky="w")
        ttk.Button(text_label_frame, text="サンプル挿入", command=self.insert_sample).grid(row=0, column=1, sticky="e")

        text_frame = ttk.Frame(parent)
        text_frame.grid(row=3, column=0, sticky="nsew", padx=(8, 0), pady=(4, 0))
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)
        self.text_input = tk.Text(text_frame, wrap=tk.NONE, undo=True, height=12)
        yscroll = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=self.text_input.yview)
        xscroll = ttk.Scrollbar(text_frame, orient=tk.HORIZONTAL, command=self.text_input.xview)
        self.text_input.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.text_input.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        self.text_input.insert("1.0", "I looked at you wrong.\n")
        self.text_input.bind("<<Modified>>", self._on_text_modified)

        self.status_var = tk.StringVar(value="準備完了")
        ttk.Label(parent, textvariable=self.status_var, anchor="w").grid(row=4, column=0, sticky="ew", padx=(8, 0), pady=(8, 0))

    def _color_row(self, parent: ttk.Frame, row: int, label: str, key: str) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(parent, textvariable=self.vars[key], width=12).grid(row=row, column=1, sticky="w", padx=(4, 4), pady=(4, 0))
        tk.Button(parent, text="選択", width=6, command=lambda: self.choose_color(key)).grid(row=row, column=2, sticky="w", padx=(4, 0), pady=(4, 0))

    def _wire_traces(self) -> None:
        watch_keys = [
            "font_path", "font_size", "text_color", "outline_enabled", "outline_color", "outline_width",
            "bg_enabled", "bg_color", "bg_alpha", "corner_radius", "fixed_box_height",
            "padding_top", "padding_bottom", "padding_left", "padding_right",
            "align", "fixed_width", "antialias_scale", "preview_line_no",
            "fixed_canvas_enabled", "canvas_width", "canvas_height",
            "icon_enabled", "icon_path", "icon_gap", "icon_size_mode", "icon_manual_height",
        ]
        for key in watch_keys:
            self.vars[key].trace_add("write", lambda *_: self.schedule_preview())

    def schedule_preview(self) -> None:
        if self.preview_after_id:
            self.after_cancel(self.preview_after_id)
        self.preview_after_id = self.after(250, self.update_preview)

    def _on_text_modified(self, event: tk.Event) -> None:
        try:
            self.text_input.edit_modified(False)
        except Exception:
            pass
        self.schedule_preview()

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    def _current_config_dict(self) -> dict:
        data = {}
        for key, var in self.vars.items():
            if isinstance(var, tk.BooleanVar):
                data[key] = bool(var.get())
            else:
                data[key] = str(var.get())
        data["window_geometry"] = self.geometry()
        return data

    def save_config(self) -> None:
        try:
            data = self._current_config_dict()
            config_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            self.status_var.set(f"設定を保存しました: {config_path()}")
        except Exception as exc:
            messagebox.showerror("設定保存エラー", str(exc))

    def _load_config(self) -> None:
        p = config_path()
        if not p.exists():
            return
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            for key, value in data.items():
                if key not in self.vars:
                    continue
                var = self.vars[key]
                if isinstance(var, tk.BooleanVar):
                    var.set(bool(value))
                else:
                    var.set(str(value))

            # v2 -> v3 移行保険
            if "icon_size_mode" not in data:
                old_fit = data.get("icon_fit_text_height")
                if old_fit is False:
                    self.vars["icon_size_mode"].set(ICON_SIZE_MODE_LABELS["manual"])
                else:
                    self.vars["icon_size_mode"].set(ICON_SIZE_MODE_LABELS["text"])

            geom = data.get("window_geometry")
            if geom:
                try:
                    self.geometry(str(geom))
                except Exception:
                    pass
            self.status_var.set("設定を読み込みました")
            self.schedule_preview()
        except Exception as exc:
            messagebox.showerror("設定読み込みエラー", str(exc))

    def on_close(self) -> None:
        self.save_config()
        self.destroy()

    # ------------------------------------------------------------------
    # UI actions
    # ------------------------------------------------------------------

    def auto_set_text_width(self) -> None:
        numbered_lines = self.get_numbered_lines()
        if not numbered_lines:
            messagebox.showwarning("自動設定できません", "対象となるテキスト行がありません。")
            return

        cfg = self.get_render_config()
        max_w = 0
        max_line_no = 0
        max_line_text = ""
        for line_no, line in numbered_lines:
            w = estimate_required_text_width(line, cfg)
            if w >= max_w:
                max_w = w
                max_line_no = line_no
                max_line_text = line

        self.vars["fixed_width"].set(str(max_w))
        preview = max_line_text.strip()
        if len(preview) > 40:
            preview = preview[:40] + "..."
        self.status_var.set(f"最大必要テキスト幅 {max_w}px を設定しました（元テキスト {max_line_no} 行目）: {preview}")
        self.update_preview()

    def auto_set_box_height(self) -> None:
        numbered_lines = self.get_numbered_lines()
        if not numbered_lines:
            messagebox.showwarning("自動設定できません", "対象となるテキスト行がありません。")
            return

        cfg = self.get_render_config()
        max_h = 0
        max_line_no = 0
        max_line_text = ""
        for line_no, line in numbered_lines:
            h = estimate_required_box_height(line, cfg)
            if h >= max_h:
                max_h = h
                max_line_no = line_no
                max_line_text = line

        self.vars["fixed_box_height"].set(str(max_h))
        preview = max_line_text.strip()
        if len(preview) > 40:
            preview = preview[:40] + "..."
        self.status_var.set(f"最大必要高さ {max_h}px を設定しました（元テキスト {max_line_no} 行目）: {preview}")
        self.update_preview()

    def clear_box_height(self) -> None:
        self.vars["fixed_box_height"].set("")
        self.status_var.set("ボックス高さの固定を解除しました")
        self.update_preview()

    def choose_font(self) -> None:
        initial_dir = str(Path(self.vars["font_path"].get()).parent) if self.vars["font_path"].get() else str(Path.home())
        path = filedialog.askopenfilename(
            title="フォントを選択",
            initialdir=initial_dir,
            filetypes=[
                ("Font files", "*.ttf *.otf *.ttc"),
                ("TrueType", "*.ttf"),
                ("OpenType", "*.otf"),
                ("TrueType Collection", "*.ttc"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self.vars["font_path"].set(path)

    def choose_icon(self) -> None:
        current = self.vars["icon_path"].get().strip()
        initial_dir = str(Path(current).parent) if current else str(Path.home())
        path = filedialog.askopenfilename(
            title="アイコン画像を選択",
            initialdir=initial_dir,
            filetypes=[
                ("Image files", "*.png *.webp *.jpg *.jpeg *.bmp *.gif"),
                ("PNG", "*.png"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self.vars["icon_path"].set(path)

    def choose_color(self, key: str) -> None:
        initial = normalize_hex(self.vars[key].get())
        color = colorchooser.askcolor(color=initial, title="色を選択")
        if color and color[1]:
            self.vars[key].set(normalize_hex(color[1]))

    def choose_output_dir(self) -> None:
        current = self.vars["output_dir"].get().strip() or str(Path.home())
        path = filedialog.askdirectory(title="出力フォルダを選択", initialdir=current)
        if path:
            self.vars["output_dir"].set(path)

    def open_output_dir(self) -> None:
        path = Path(self.vars["output_dir"].get().strip()).expanduser()
        if not path.exists():
            messagebox.showwarning("フォルダがありません", "出力フォルダが存在しません。")
            return
        safe_open_folder(path)

    def insert_sample(self) -> None:
        sample = "aaaaaaa\nI looked at you wrong.\ntt\n"
        self.text_input.delete("1.0", tk.END)
        self.text_input.insert("1.0", sample)
        self.schedule_preview()

    # ------------------------------------------------------------------
    # Data collection
    # ------------------------------------------------------------------

    def get_render_config(self) -> RenderConfig:
        icon_mode_label = self.vars["icon_size_mode"].get()
        icon_mode = ICON_SIZE_MODE_REVERSE.get(icon_mode_label, "text")
        return RenderConfig(
            font_path=self.vars["font_path"].get().strip(),
            font_size=parse_int(self.vars["font_size"].get(), 42, 1, 1000),
            text_color=normalize_hex(self.vars["text_color"].get(), "#FFFFFF"),
            outline_enabled=bool(self.vars["outline_enabled"].get()),
            outline_color=normalize_hex(self.vars["outline_color"].get(), "#000000"),
            outline_width=parse_int(self.vars["outline_width"].get(), 0, 0, 200),
            bg_enabled=bool(self.vars["bg_enabled"].get()),
            bg_color=normalize_hex(self.vars["bg_color"].get(), "#000000"),
            bg_alpha=parse_int(self.vars["bg_alpha"].get(), 255, 0, 255),
            corner_radius=parse_int(self.vars["corner_radius"].get(), 0, 0, 1000),
            fixed_box_height=self.vars["fixed_box_height"].get().strip(),
            padding_top=parse_int(self.vars["padding_top"].get(), 0, 0, 5000),
            padding_bottom=parse_int(self.vars["padding_bottom"].get(), 0, 0, 5000),
            padding_left=parse_int(self.vars["padding_left"].get(), 0, 0, 5000),
            padding_right=parse_int(self.vars["padding_right"].get(), 0, 0, 5000),
            align=self.vars["align"].get(),
            fixed_width=self.vars["fixed_width"].get().strip(),
            antialias_scale=parse_int(self.vars["antialias_scale"].get(), 1, 1, 4),
            fixed_canvas_enabled=bool(self.vars["fixed_canvas_enabled"].get()),
            canvas_width=parse_int(self.vars["canvas_width"].get(), 1920, 1, 100000),
            canvas_height=parse_int(self.vars["canvas_height"].get(), 180, 1, 100000),
            icon_enabled=bool(self.vars["icon_enabled"].get()),
            icon_path=self.vars["icon_path"].get().strip(),
            icon_gap=parse_int(self.vars["icon_gap"].get(), 16, 0, 5000),
            icon_size_mode=icon_mode,
            icon_manual_height=parse_int(self.vars["icon_manual_height"].get(), 48, 1, 5000),
        )

    def get_numbered_lines(self) -> List[Tuple[int, str]]:
        text = self.text_input.get("1.0", "end-1c")
        raw_lines = text.splitlines()
        numbered: List[Tuple[int, str]] = []
        for i, line in enumerate(raw_lines, start=1):
            if self.vars["skip_empty"].get() and line.strip() == "":
                continue
            numbered.append((i, line))
        return numbered

    def get_lines(self) -> List[str]:
        return [line for _, line in self.get_numbered_lines()]

    def get_preview_line(self) -> str:
        lines = self.get_lines()
        if not lines:
            return ""
        idx = parse_int(self.vars["preview_line_no"].get(), 1, 1, max(1, len(lines))) - 1
        return lines[idx]

    # ------------------------------------------------------------------
    # Preview / Export
    # ------------------------------------------------------------------

    def update_preview(self) -> None:
        self.preview_after_id = None
        line = self.get_preview_line()
        if line == "":
            self.preview_label.configure(text="プレビューする行がありません", image="")
            self.preview_photo = None
            return

        try:
            cfg = self.get_render_config()
            img, warnings = render_subtitle_image(line, cfg)
            self.update_idletasks()
            max_w = max(320, self.preview_label.winfo_width() - 16)
            max_h = max(160, self.preview_label.winfo_height() - 16)
            prev = preview_composite(img, (max_w, max_h))
            self.preview_photo = ImageTk.PhotoImage(prev)
            self.preview_label.configure(image=self.preview_photo, text="")
            msg = f"プレビュー: {img.width} x {img.height}px"
            if warnings:
                msg += " / 警告: " + " ".join(warnings)
            self.status_var.set(msg)
        except Exception as exc:
            self.preview_label.configure(text="プレビューエラー", image="")
            self.preview_photo = None
            self.status_var.set(f"プレビューエラー: {exc}")

    def export_images(self) -> None:
        lines = self.get_lines()
        if not lines:
            messagebox.showwarning("出力できません", "出力するテキスト行がありません。")
            return

        out_dir = Path(self.vars["output_dir"].get().strip()).expanduser()
        prefix = self.vars["prefix"].get()
        digits = parse_int(self.vars["digits"].get(), 3, 1, 10)

        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            messagebox.showerror("出力フォルダエラー", str(exc))
            return

        include_text = bool(self.vars["filename_include_text"].get())
        targets = []
        for i, line in enumerate(lines, start=1):
            suffix = ""
            if include_text:
                safe_text = safe_filename_text(line)
                if safe_text:
                    suffix = safe_text
            targets.append(out_dir / f"{prefix}{i:0{digits}d}{suffix}.png")
        existing = [p for p in targets if p.exists()]
        if existing and self.vars["overwrite_confirm"].get():
            sample = "\n".join(p.name for p in existing[:8])
            if len(existing) > 8:
                sample += f"\n...ほか {len(existing) - 8} 件"
            ok = messagebox.askyesno("上書き確認", f"既存ファイル {len(existing)} 件を上書きします。よろしいですか？\n\n{sample}")
            if not ok:
                self.status_var.set("出力をキャンセルしました")
                return

        cfg = self.get_render_config()
        warning_count = 0
        errors: List[str] = []
        saved = 0

        for i, (line, target) in enumerate(zip(lines, targets), start=1):
            try:
                img, warnings = render_subtitle_image(line, cfg)
                if warnings:
                    warning_count += len(warnings)
                img.save(target, format="PNG")
                saved += 1
                self.status_var.set(f"出力中... {i}/{len(lines)}: {target.name}")
                self.update_idletasks()
            except Exception as exc:
                errors.append(f"{target.name}: {exc}")

        self.last_output_dir = out_dir
        self.save_config()

        msg = f"出力完了: {saved} 枚 / {out_dir}"
        if warning_count:
            msg += f"\n警告: {warning_count} 件"
        if errors:
            msg += "\n\nエラー:\n" + "\n".join(errors[:10])
            if len(errors) > 10:
                msg += f"\n...ほか {len(errors) - 10} 件"
            messagebox.showwarning("出力完了（一部エラーあり）", msg)
        else:
            messagebox.showinfo("出力完了", msg)
        self.status_var.set(msg.replace("\n", " / "))
        self.update_preview()


def main() -> None:
    try:
        app = SubtitleImageMakerApp()
        app.mainloop()
    except Exception:
        err = traceback.format_exc()
        try:
            messagebox.showerror("致命的エラー", err)
        except Exception:
            print(err)
        raise


if __name__ == "__main__":
    main()
