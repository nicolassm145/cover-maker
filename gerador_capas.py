#!/usr/bin/env python3
"""
gerador_capas.py - monta a capa completa estilo "Steam GridDB Comics".

ARQUIVOS NECESSÁRIOS NA MESMA PASTA DESTE .py:
    template.png          (molde da capa, PNG transparente 564x877)
    Anton-Regular.ttf     (fonte do número do issue)

DEPENDÊNCIAS:
    pip install pillow numpy customtkinter
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageDraw, ImageOps, ImageFont

# ===================== ENVELHECIMENTO DA ARTE =====================
PAPER = np.array([226, 214, 188], dtype=np.float32)

def pan_zoom_art(img, target_size, zoom=1.0, pan_x=0.0, pan_y=0.0):
    img_w, img_h = img.size
    target_w, target_h = target_size
    
    img_ratio = img_w / img_h
    target_ratio = target_w / target_h
    
    if img_ratio > target_ratio:
        base_h = img_h
        base_w = int(img_h * target_ratio)
    else:
        base_w = img_w
        base_h = int(img_w / target_ratio)
    
    crop_w = base_w / max(1.0, zoom)
    crop_h = base_h / max(1.0, zoom)
    
    max_pan_x = img_w - crop_w
    max_pan_y = img_h - crop_h
    
    px_norm = (pan_x + 1.0) / 2.0
    py_norm = (pan_y + 1.0) / 2.0
    
    left = px_norm * max_pan_x
    top = py_norm * max_pan_y
    
    crop_box = (left, top, left + crop_w, top + crop_h)
    return img.resize(target_size, Image.LANCZOS, box=crop_box)

def fractal_noise(w, h, rng, scales=(4, 12, 40, 120), weights=(0.15, 0.25, 0.3, 0.3)):
    out = np.zeros((h, w), dtype=np.float32)
    for s, wt in zip(scales, weights):
        small = rng.random((max(2, h // s), max(2, w // s))).astype(np.float32)
        im = Image.fromarray((small * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC)
        out += wt * np.asarray(im, dtype=np.float32) / 255.0
    out -= out.min()
    out /= out.max() + 1e-6
    return out

def edge_distance(w, h):
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.minimum(np.minimum(xx, w - 1 - xx) / (w * 0.25),
                   np.minimum(yy, h - 1 - yy) / (h * 0.25))
    return np.clip(d, 0, 1)

def mute_colors(arr, sat=0.68):
    lum = (0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2])[..., None]
    arr = lum + (arr - lum) * sat
    shadow = (1 - lum / 255.0)
    arr = arr + shadow * np.array([9, 4, -2], dtype=np.float32)
    return arr

def lift_blacks(arr, black=22, white=236):
    return black + (arr / 255.0) * (white - black)

def flatten_tones(arr, amount):
    if amount <= 0:
        return arr
    im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).filter(ImageFilter.MedianFilter(3))
    q = np.asarray(ImageOps.posterize(im, 4), dtype=np.float32)
    med = np.asarray(im, dtype=np.float32)
    return arr * (1 - amount) + (med * 0.5 + q * 0.5) * amount

def halftone(arr, amount):
    if amount <= 0:
        return arr
    h, w = arr.shape[:2]
    lum = (0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2]) / 255.0
    cell = max(4, round(w / 130))
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    a = np.deg2rad(45)
    u = xx * np.cos(a) + yy * np.sin(a)
    v = -xx * np.sin(a) + yy * np.cos(a)
    pat = (np.cos(2 * np.pi * u / cell) + np.cos(2 * np.pi * v / cell)) / 4 + 0.5
    ink = (pat > lum).astype(np.float32)
    mult = 1 - ink * 0.55
    return (arr * (1 - amount) + arr * mult[..., None] * amount) * (1 + amount * 0.25)

def ink_flakes(w, h, rng, wear):
    ed = edge_distance(w, h)
    near = (1 - ed) ** 1.4
    fine = fractal_noise(w, h, rng, scales=(1, 2, 3), weights=(0.4, 0.35, 0.25))
    thr_fine = 1 - (0.022 + 0.080 * near) * wear
    m_fine = (fine > thr_fine).astype(np.float32)
    big = fractal_noise(w, h, rng, scales=(3, 8, 20), weights=(0.3, 0.4, 0.3))
    thr_big = 1 - (0.006 + 0.22 * near ** 2) * wear
    m_big = (big > thr_big).astype(np.float32)
    m = np.clip(m_fine + m_big, 0, 1)
    m = np.asarray(Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.6)),
                   dtype=np.float32) / 255.0
    return np.clip(m * 1.6, 0, 1)

def hairlines(w, h, rng, wear):
    mask = Image.new("L", (w * 2, h * 2), 0)
    d = ImageDraw.Draw(mask)
    n = int(18 * wear * (w * h) / (600 * 900))
    for _ in range(n):
        if rng.random() < 0.6:
            side = rng.integers(0, 4)
            t = rng.random()
            if side == 0:   x, y = rng.random() * w * 0.12, t * h
            elif side == 1: x, y = w - rng.random() * w * 0.12, t * h
            elif side == 2: x, y = t * w, rng.random() * h * 0.08
            else:           x, y = t * w, h - rng.random() * h * 0.08
        else:
            x, y = rng.random() * w, rng.random() * h
        length = rng.random() ** 2.2 * 140 + 10
        ang = rng.random() * np.pi
        bend = rng.normal(0, 0.4)
        pts = []
        for i in range(12):
            f = i / 11
            a = ang + bend * f
            pts.append(((x + np.cos(a) * length * f) * 2, (y + np.sin(a) * length * f) * 2))
        d.line(pts, fill=int(rng.integers(120, 255)), width=2)
    mask = mask.resize((w, h), Image.LANCZOS).filter(ImageFilter.GaussianBlur(0.3))
    return np.asarray(mask, dtype=np.float32) / 255.0

def creases(w, h, rng, wear):
    light = Image.new("L", (w * 2, h * 2), 0)
    dark = Image.new("L", (w * 2, h * 2), 0)
    dl, dd = ImageDraw.Draw(light), ImageDraw.Draw(dark)
    for _ in range(rng.integers(2, 4)):
        vertical = rng.random() < 0.5
        if vertical:
            x0 = rng.random() * w; x1 = x0 + rng.normal(0, 12)
            p = [(x0 * 2, 0), (x1 * 2, h * 2)]
        else:
            y0 = rng.random() * h; y1 = y0 + rng.normal(0, 12)
            p = [(0, y0 * 2), (w * 2, y1 * 2)]
        dd.line(p, fill=160, width=3)
        dl.line([(p[0][0] + 3, p[0][1] + 3), (p[1][0] + 3, p[1][1] + 3)], fill=200, width=2)
    f = lambda m: np.asarray(m.resize((w, h), Image.LANCZOS).filter(ImageFilter.GaussianBlur(0.8)),
                             dtype=np.float32) / 255.0
    return f(light), f(dark)

def color_grade(arr, flat=0.35, seed=7):
    """Aplica o filtro de desbotamento, contraste e textura do papel."""
    rng = np.random.default_rng(seed)
    h, w = arr.shape[:2]
    arr = mute_colors(arr)
    arr = lift_blacks(arr)
    arr = flatten_tones(arr, flat)

    im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.6))
    arr = np.asarray(im, dtype=np.float32)

    mott = fractal_noise(w, h, rng, scales=(40, 120, 300), weights=(0.3, 0.4, 0.3))
    arr = arr * (0.94 + 0.10 * mott[..., None])
    return np.clip(arr, 0, 255).astype(np.uint8)

def process(arr, wear=1.0, halftone_amt=0.0, flat=0.35, seed=7):
    """Recebe a arte completa (já com a logo fundida nela) e envelhece TUDO de forma uniforme."""
    arr = color_grade(arr, flat, seed)
    arr = arr.astype(np.float32)
    rng = np.random.default_rng(seed)
    h, w = arr.shape[:2]

    arr = halftone(arr, halftone_amt)

    arr = arr + rng.normal(0, 3.2 * wear, (h, w)).astype(np.float32)[..., None]
    cl, cd = creases(w, h, rng, wear)
    arr = arr + cl[..., None] * 9 * wear - cd[..., None] * 12 * wear
    flakes = ink_flakes(w, h, rng, wear)
    arr = arr * (1 - flakes[..., None] * 0.92) + PAPER * flakes[..., None] * 0.92
    hl = hairlines(w, h, rng, wear)
    arr = arr * (1 - hl[..., None] * 0.75) + PAPER * 1.04 * hl[..., None] * 0.75

    return np.clip(arr, 0, 255).astype(np.uint8)

# ===================== LASCAS NAS LOGOS =====================
def logo_flake_mask(w, h, rng, wear, fine=0.05, big=0.035):
    f = fractal_noise(w, h, rng, scales=(1, 2, 3), weights=(0.4, 0.35, 0.25))
    m_fine = (f > 1 - fine * wear).astype(np.float32)
    b = fractal_noise(w, h, rng, scales=(3, 6, 14), weights=(0.3, 0.4, 0.3))
    m_big = (b > 1 - big * wear).astype(np.float32)
    m = np.clip(m_fine + m_big, 0, 1)
    m = np.asarray(Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.5)),
                   dtype=np.float32) / 255.0
    return np.clip(m * 1.6, 0, 1)

def distress_logo(img, rng, wear, fine=0.05, big=0.035, scratches=True):
    img = img.convert("RGBA")
    w, h = img.size
    m = logo_flake_mask(w, h, rng, wear, fine, big)
    if scratches:
        m = np.clip(m + hairlines(w, h, rng, wear * 2.0) * 0.9, 0, 1)
    a = np.asarray(img.getchannel("A"), dtype=np.float32) / 255.0
    a = a * (1 - m)
    out = img.copy()
    out.putalpha(Image.fromarray((a * 255).astype(np.uint8)))
    return out

# ===================== ASSETS =====================
def app_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

def asset_path(name):
    cands = [app_dir() / name]
    if getattr(sys, "_MEIPASS", None):
        cands.append(Path(sys._MEIPASS) / name)
    for c in cands:
        if c.exists():
            return c
    raise FileNotFoundError(f"Não achei '{name}' na mesma pasta do programa:\n{app_dir()}")

def template_image():
    return Image.open(asset_path("template.png")).convert("RGBA")

def get_font(size):
    return ImageFont.truetype(str(asset_path("Anton-Regular.ttf")), size)

# ===================== LAYOUT =====================
ISSUE_BOX = (8, 100, 72, 125)
ISSUE_MAX_H = 13
ISSUE_COLOR = (0x40, 0x3B, 0x3B, 255)
PUB_BOX = (12, 144, 68, 212)
PUB_PAD = 3
BARCODE_BOX = (14, 222, 68, 370)
LOGO_MAX_H_FRAC = 0.38

def trim(img):
    bbox = img.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    return img.crop(bbox) if bbox else img

def draw_issue(canvas, steam_id):
    x0, y0, x1, y1 = ISSUE_BOX
    bw, bh = x1 - x0, y1 - y0
    S = 6
    size = 200
    while size > 6:
        f = get_font(size)
        l, t, r, b = f.getbbox(steam_id)
        if (r - l) <= bw * S * 0.97 and (b - t) <= min(bh, ISSUE_MAX_H) * S:
            break
        size -= 2
    layer = Image.new("RGBA", (bw * S, bh * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    l, t, r, b = f.getbbox(steam_id)
    d.text(((bw * S - (r - l)) / 2 - l, (bh * S - (b - t)) / 2 - t), steam_id, font=f, fill=ISSUE_COLOR)
    canvas.alpha_composite(layer.resize((bw, bh), Image.LANCZOS), (x0, y0))

def filter_logo_pub(img, seed):
    arr = np.asarray(img.convert("RGB"), dtype=np.float32)
    graded = color_grade(arr, seed=seed)
    out = Image.fromarray(graded).convert("RGBA")
    out.putalpha(img.getchannel("A"))
    return out

def draw_publisher(canvas, pub_img, rng, wear_pub, seed, pub_zoom=1.0, pub_x=0.0, pub_y=0.0):
    pub_img = trim(pub_img)
    x0, y0, x1, y1 = PUB_BOX
    w, h = x1 - x0, y1 - y0
    
    iw, ih = w - 2 * PUB_PAD, h - 2 * PUB_PAD
    base_scale = min(iw / pub_img.width, ih / pub_img.height)
    
    final_scale = base_scale * pub_zoom
    new_w = max(1, round(pub_img.width * final_scale))
    new_h = max(1, round(pub_img.height * final_scale))
    
    p = pub_img.resize((new_w, new_h), Image.LANCZOS)
    p = filter_logo_pub(p, seed)
    p = distress_logo(p, rng, wear_pub, fine=0.07, big=0.04, scratches=False)
    
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    
    cx = (w - new_w) // 2
    cy = (h - new_h) // 2
    cx += int(pub_x * (w / 2))
    cy += int(pub_y * (h / 2))
    
    layer.paste(p, (cx, cy), p)
    canvas.alpha_composite(layer, (x0, y0))

def draw_barcode(canvas, steam_id, wear):
    x0, y0, x1, y1 = BARCODE_BOX
    w, h = x1 - x0, y1 - y0
    
    layer = Image.new("RGB", (w, h), (226, 214, 188))
    draw = ImageDraw.Draw(layer)
    draw.rectangle([0, 0, w-1, h-1], outline=(200, 190, 170), width=1)
    
    seed = int(steam_id) if str(steam_id).isdigit() else 0
    rng = np.random.default_rng(seed + 999)
    
    y = 6
    while y < h - 6:
        thickness = rng.integers(1, 6)
        if y + thickness > h - 6:
            break
        draw.rectangle([4, y, w - 4, y + thickness], fill=(40, 38, 38))
        gap = rng.integers(1, 7)
        y += thickness + gap
        
    arr = np.asarray(layer, dtype=np.float32)
    aged_arr = process(arr, wear=wear, seed=seed+111)
    aged_layer = Image.fromarray(aged_arr).convert("RGBA")
    
    canvas.alpha_composite(aged_layer, (x0, y0))

def compose(art_path, logo_path, pub_path, steam_id,
            logo_width=0.80, logo_bottom=0.10, wear_art=1.0, wear_logo=1.0, wear_pub=1.0, 
            art_zoom=1.0, art_x=0.0, art_y=0.0, 
            pub_zoom=1.0, pub_x=0.0, pub_y=0.0, preview=False):
    steam_id = str(steam_id).strip()
    
    seed = int(steam_id) if steam_id.isdigit() else 0
    if not preview and not steam_id.isdigit():
        raise ValueError("O Steam ID precisa ter só números.")
        
    if not pub_path:
        raise ValueError("A logo da publisher é obrigatória.")
    for label, p in (("arte", art_path), ("logo do jogo", logo_path), ("logo da publisher", pub_path)):
        if not p or not Path(p).exists():
            raise FileNotFoundError(f"Arquivo da {label} não encontrado.")

    rng = np.random.default_rng(seed)
    tpl = template_image()
    
    art = ImageOps.exif_transpose(Image.open(art_path)).convert("RGB")
    art_rgba = pan_zoom_art(art, tpl.size, zoom=art_zoom, pan_x=art_x, pan_y=art_y).convert("RGBA")
    
    logo = trim(Image.open(logo_path).convert("RGBA"))
    W, H = art_rgba.size
    lw = int(W * logo_width)
    lh = int(logo.height * lw / logo.width)
    max_h = int(H * LOGO_MAX_H_FRAC)
    if lh > max_h:
        lh = max_h
        lw = int(logo.width * lh / logo.height)
    lg = logo.resize((max(1, lw), max(1, lh)), Image.LANCZOS)
    
    lg = distress_logo(lg, rng, wear_logo)
    
    x = (W - lw) // 2
    y = int(H * (1 - logo_bottom)) - lh
    
    shadow_layer = Image.new("RGBA", art_rgba.size, (0, 0, 0, 0))
    shadow_alpha = lg.getchannel("A").point(lambda p: int(p * 0.8))
    shadow_layer.paste(Image.new("RGB", lg.size, (0, 0, 0)), (x, y + 4), shadow_alpha)
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(5))
    
    art_rgba.alpha_composite(shadow_layer)
    art_rgba.alpha_composite(lg, (x, y))
    
    if preview:
        small_art = art_rgba.resize((art_rgba.width // 2, art_rgba.height // 2), Image.BILINEAR)
        aged_small = Image.fromarray(process(np.asarray(small_art.convert("RGB"), dtype=np.float32), wear=wear_art, seed=seed))
        aged = aged_small.resize(tpl.size, Image.BILINEAR)
    else:
        aged = Image.fromarray(process(np.asarray(art_rgba.convert("RGB"), dtype=np.float32), wear=wear_art, seed=seed))

    canvas = aged.convert("RGBA")
    canvas.alpha_composite(tpl)
    draw_issue(canvas, steam_id)
    draw_barcode(canvas, steam_id, wear_pub)
    
    pub_img = Image.open(pub_path).convert("RGBA")
    draw_publisher(canvas, pub_img, rng, wear_pub, seed, pub_zoom, pub_x, pub_y)
    
    return canvas

# ------------------------------- JANELA COM CUSTOMTKINTER --------------------------------
def run_gui():
    try:
        import customtkinter as ctk
    except ImportError:
        import tkinter.messagebox
        tkinter.messagebox.showerror(
            "Erro de Dependência", 
            "A nova interface usa 'customtkinter'.\n\nInstale abrindo o terminal e rodando:\npip install customtkinter"
        )
        sys.exit(1)
        
    from tkinter import filedialog, messagebox
    from PIL import ImageTk

    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("blue")

    root = ctk.CTk()
    root.title("Gerador de capas - Steam Comics")
    
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    start_w = min(950, int(screen_w * 0.9))
    start_h = min(720, int(screen_h * 0.85))
    root.geometry(f"{start_w}x{start_h}")
    root.minsize(750, 500)

    paths = {"art": ctk.StringVar(), "logo": ctk.StringVar(), "pub": ctk.StringVar()}
    steam = ctk.StringVar()
    
    state = {
        "logo_w": 0.80, "logo_b": 0.10,
        "art_zoom": 1.0, "art_x": 0.0, "art_y": 0.0,
        "pub_zoom": 1.0, "pub_x": 0.0, "pub_y": 0.0,
        "wear_art": 1.0, "wear_logo": 1.0, "wear_pub": 1.0
    }
    
    status = ctk.StringVar(value="Pronto para criar!")
    preview_ref = {}
    timer_id = [None]
    
    def schedule_preview(*args):
        if not paths["art"].get() or not paths["logo"].get() or not paths["pub"].get() or not steam.get():
            return
        if timer_id[0] is not None:
            root.after_cancel(timer_id[0])
        timer_id[0] = root.after(400, render_preview)

    def pick(key):
        types = [("Imagens", "*.png *.jpg *.jpeg *.webp *.bmp"), ("Todos", "*.*")]
        f = filedialog.askopenfilename(filetypes=types)
        if f:
            paths[key].set(f)
            schedule_preview()

    def render_preview():
        try:
            status.set("Atualizando prévia...")
            root.update_idletasks()
            img = compose(
                paths["art"].get(), paths["logo"].get(), paths["pub"].get(), steam.get(),
                state["logo_w"], state["logo_b"], state["wear_art"], state["wear_logo"], state["wear_pub"], 
                state["art_zoom"], state["art_x"], state["art_y"], 
                state["pub_zoom"], state["pub_x"], state["pub_y"], preview=True
            )
            th = img.copy()
            th.thumbnail((320, 500), Image.LANCZOS)
            
            preview_ref["img"] = ctk.CTkImage(light_image=th, dark_image=th, size=(th.width, th.height))
            prev.configure(image=preview_ref["img"], text="")
            status.set("Prévia atualizada!")
        except Exception:
            pass

    left_frame = ctk.CTkFrame(root, fg_color="transparent")
    left_frame.pack(side="left", fill="both", expand=True, padx=15, pady=15)
    
    right_frame = ctk.CTkFrame(root, fg_color="transparent")
    right_frame.pack(side="right", fill="y", padx=(0, 15), pady=15)

    prev_label = ctk.CTkLabel(right_frame, text="Prévia ao Vivo", font=("Segoe UI", 16, "bold"))
    prev_label.pack(anchor="w", pady=(0, 10))
    
    prev_frame = ctk.CTkFrame(right_frame, width=320, height=500, fg_color=("gray85", "gray20"))
    prev_frame.pack(fill="both", expand=True)
    prev_frame.pack_propagate(False)
    
    prev = ctk.CTkLabel(prev_frame, text="Nenhuma prévia\ndisponível", font=("Segoe UI", 14))
    prev.pack(expand=True)

    try:
        init_tpl = template_image()
        init_th = init_tpl.copy()
        init_th.thumbnail((320, 500), Image.LANCZOS)
        preview_ref["img"] = ctk.CTkImage(light_image=init_th, dark_image=init_th, size=(init_th.width, init_th.height))
        prev.configure(image=preview_ref["img"], text="")
    except:
        pass

    tabview = ctk.CTkTabview(left_frame)
    tabview.pack(fill="both", expand=True)
    tab_main = tabview.add("Principal")
    tab_adv = tabview.add("Ajustes Avançados")

    lbl_base = ctk.CTkLabel(tab_main, text="Arquivos Base", font=("Segoe UI", 14, "bold"))
    lbl_base.pack(anchor="w", pady=(10, 5), padx=10)
    
    gf = ctk.CTkFrame(tab_main)
    gf.pack(fill="x", pady=(0, 15), padx=10)

    for label_text, key in [("Arte de fundo", "art"), ("Logo do jogo", "logo"), ("Logo da publisher", "pub")]:
        ctk.CTkLabel(gf, text=label_text).pack(anchor="w", padx=10, pady=(10,0))
        row = ctk.CTkFrame(gf, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=(0,10))
        ent = ctk.CTkEntry(row, textvariable=paths[key])
        ent.pack(side="left", fill="x", expand=True)
        ent.bind("<KeyRelease>", lambda e: schedule_preview())
        ctk.CTkButton(row, text="Buscar", width=60, command=lambda k=key: pick(k)).pack(side="left", padx=(10, 0))

    lbl_id = ctk.CTkLabel(tab_main, text="Steam ID (issue #)", font=("Segoe UI", 14, "bold"))
    lbl_id.pack(anchor="w", pady=(10, 5), padx=10)
    
    gf2 = ctk.CTkFrame(tab_main)
    gf2.pack(fill="x", pady=(0, 15), padx=10)
    ent_steam = ctk.CTkEntry(gf2, textvariable=steam, placeholder_text="Ex: 400")
    ent_steam.pack(fill="x", padx=10, pady=10)
    ent_steam.bind("<KeyRelease>", lambda e: schedule_preview())

    adv_scroll = ctk.CTkScrollableFrame(tab_adv, fg_color="transparent")
    adv_scroll.pack(fill="both", expand=True)

    def create_slider(parent, label_text, key, a, b):
        ctk.CTkLabel(parent, text=label_text).pack(anchor="w", padx=10, pady=(10, 0))
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=(0, 10))
        
        val_var = ctk.StringVar(value=f"{state[key]:.2f}")
        
        def update_from_slider(val):
            state[key] = float(val)
            val_var.set(f"{state[key]:.2f}")
            schedule_preview()
            
        def update_from_entry(*args):
            try:
                txt = val_var.get().replace(",", ".")
                v = float(txt)
                v = max(a, min(b, v))
                state[key] = v
                sl.set(v)
                schedule_preview()
            except ValueError:
                pass

        sl = ctk.CTkSlider(row, from_=a, to=b, command=update_from_slider)
        sl.set(state[key])
        sl.pack(side="left", fill="x", expand=True)
        
        ent = ctk.CTkEntry(row, textvariable=val_var, width=55, justify="center")
        ent.pack(side="left", padx=(10, 0))
        ent.bind("<KeyRelease>", update_from_entry)

    f_art = ctk.CTkFrame(adv_scroll)
    f_art.pack(fill="x", pady=5, padx=5)
    ctk.CTkLabel(f_art, text="Enquadramento da Arte", font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=10, pady=(5,0))
    create_slider(f_art, "Zoom da Arte", "art_zoom", 1.0, 3.0)
    create_slider(f_art, "Mover Arte ↔", "art_x", -1.0, 1.0)
    create_slider(f_art, "Mover Arte ↕", "art_y", -1.0, 1.0)

    f_logo = ctk.CTkFrame(adv_scroll)
    f_logo.pack(fill="x", pady=5, padx=5)
    ctk.CTkLabel(f_logo, text="Logo do Jogo", font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=10, pady=(5,0))
    create_slider(f_logo, "Tamanho da logo", "logo_w", 0.40, 0.95)
    create_slider(f_logo, "Altura da logo", "logo_b", 0.0, 0.60)

    f_pub = ctk.CTkFrame(adv_scroll)
    f_pub.pack(fill="x", pady=5, padx=5)
    ctk.CTkLabel(f_pub, text="Logo da Publisher", font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=10, pady=(5,0))
    create_slider(f_pub, "Tamanho da Publisher", "pub_zoom", 0.5, 3.0)
    create_slider(f_pub, "Mover Publisher ↔", "pub_x", -1.0, 1.0)
    create_slider(f_pub, "Mover Publisher ↕", "pub_y", -1.0, 1.0)

    f_wear = ctk.CTkFrame(adv_scroll)
    f_wear.pack(fill="x", pady=5, padx=5)
    ctk.CTkLabel(f_wear, text="Efeitos de Desgaste", font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=10, pady=(5,0))
    create_slider(f_wear, "Desgaste da arte", "wear_art", 0.0, 3.5)
    create_slider(f_wear, "Desgaste da logo", "wear_logo", 0.0, 3.5)
    create_slider(f_wear, "Desgaste da pub", "wear_pub", 0.0, 3.5)

    footer = ctk.CTkFrame(left_frame, fg_color="transparent")
    footer.pack(fill="x", pady=(10, 0))

    def gerar():
        if not paths["art"].get() or not paths["logo"].get() or not paths["pub"].get() or not steam.get():
            messagebox.showwarning("Aviso", "Por favor, preencha todos os arquivos base e o Steam ID.")
            return

        steam_id_str = steam.get().strip()
        default_name = f"final_{steam_id_str}.png" if steam_id_str else "capa_final.png"

        out_path = filedialog.asksaveasfilename(
            title="Salvar capa como...",
            initialdir=app_dir(),
            initialfile=default_name,
            defaultextension=".png",
            filetypes=[("Imagens PNG", "*.png"), ("Todos os arquivos", "*.*")]
        )

        if not out_path:
            status.set("Salvamento cancelado.")
            return

        try:
            status.set("Gerando capa em alta resolução...")
            root.update_idletasks()
            img = compose(
                paths["art"].get(), paths["logo"].get(), paths["pub"].get(), steam.get(),
                state["logo_w"], state["logo_b"], state["wear_art"], state["wear_logo"], state["wear_pub"], 
                state["art_zoom"], state["art_x"], state["art_y"], 
                state["pub_zoom"], state["pub_x"], state["pub_y"], preview=False
            )
            img.save(out_path)
            status.set(f"Pronto! Salvo com sucesso.")
            messagebox.showinfo("Sucesso", f"Capa gerada com sucesso em:\n{out_path}")
        except Exception as e:
            status.set("Erro.")
            messagebox.showerror("Erro", str(e))

    btn_gerar = ctk.CTkButton(footer, text="GERAR CAPA FINAL", height=40, font=("Segoe UI", 14, "bold"), command=gerar)
    btn_gerar.pack(side="left")
    
    lbl_status = ctk.CTkLabel(footer, textvariable=status)
    lbl_status.pack(side="left", padx=15)

    root.mainloop()

if __name__ == "__main__":
    run_gui()