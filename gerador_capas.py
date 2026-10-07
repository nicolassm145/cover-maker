#!/usr/bin/env python3
"""
gerador_capas.py - monta a capa completa estilo "Steam GridDB Comics".

ARQUIVOS NECESSÁRIOS NA MESMA PASTA DESTE .py:
    template.png          (molde da capa, PNG transparente 564x877)
    Anton-Regular.ttf     (fonte do número do issue)

COMO RODAR:
    pip install pillow numpy      (tkinter já vem com o Python)
    python gerador_capas.py
  -> abre uma janela: escolha arte / logo do jogo / logo da publisher,
     digite o Steam ID e clique em "Gerar capa".
     Saída: final_<SteamID>.png na mesma pasta.

Camadas (de baixo pra cima):
  arte envelhecida -> logo do jogo (com lascas) -> template (desgaste por cima)
  -> Steam ID (Anton, #403b3b) -> logo da publisher (com lascas, presa no quadrado)
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageDraw, ImageOps, ImageFont



# ===================== ENVELHECIMENTO DA ARTE =====================
PAPER = np.array([226, 214, 188], dtype=np.float32)  # cor do papel que aparece nas lascas


def pan_zoom_art(img, target_size, zoom=1.0, pan_x=0.0, pan_y=0.0):
    """Enquadra a arte permitindo zoom in e deslocamento X/Y (-1.0 a 1.0)."""
    img_w, img_h = img.size
    target_w, target_h = target_size
    
    img_ratio = img_w / img_h
    target_ratio = target_w / target_h
    
    # Descobre o corte base (como se fosse preencher a tela inteira sem esticar)
    if img_ratio > target_ratio:
        base_h = img_h
        base_w = int(img_h * target_ratio)
    else:
        base_w = img_w
        base_h = int(img_w / target_ratio)
    
    # Aplica o zoom encolhendo a área de corte
    crop_w = base_w / max(1.0, zoom)
    crop_h = base_h / max(1.0, zoom)
    
    # Calcula o quanto podemos andar pros lados
    max_pan_x = img_w - crop_w
    max_pan_y = img_h - crop_h
    
    # Converte os pans de [-1, 1] para [0, 1]
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
    """0 na borda, 1 a partir de ~25% pra dentro."""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.minimum(np.minimum(xx, w - 1 - xx) / (w * 0.25),
                   np.minimum(yy, h - 1 - yy) / (h * 0.25))
    return np.clip(d, 0, 1)


def mute_colors(arr, sat=0.68):
    """Cores desbotadas + preto levemente quente (sem amarelar tudo)."""
    lum = (0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2])[..., None]
    arr = lum + (arr - lum) * sat
    # sombras puxam pra marrom-queimado, luzes ficam quase neutras
    shadow = (1 - lum / 255.0)
    arr = arr + shadow * np.array([9, 4, -2], dtype=np.float32)
    return arr


def lift_blacks(arr, black=22, white=236):
    return black + (arr / 255.0) * (white - black)


def flatten_tones(arr, amount):
    """Deixa os tons mais chapados, tipo tinta de impressão antiga."""
    if amount <= 0:
        return arr
    im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).filter(ImageFilter.MedianFilter(3))
    q = np.asarray(ImageOps.posterize(im, 4), dtype=np.float32)  # 16 níveis por canal
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
    """Tinta lascada: pontinhos e manchas irregulares mostrando o papel,
    mais densos perto das bordas. Retorna máscara 0..1."""
    ed = edge_distance(w, h)
    near = (1 - ed) ** 1.4  # 1 na borda
    # pontinhos finos (espalhados)
    fine = fractal_noise(w, h, rng, scales=(1, 2, 3), weights=(0.4, 0.35, 0.25))
    thr_fine = 1 - (0.022 + 0.080 * near) * wear
    m_fine = (fine > thr_fine).astype(np.float32)
    # lascas maiores (só perto das bordas e algumas esparsas)
    big = fractal_noise(w, h, rng, scales=(3, 8, 20), weights=(0.3, 0.4, 0.3))
    thr_big = 1 - (0.006 + 0.22 * near ** 2) * wear
    m_big = (big > thr_big).astype(np.float32)
    m = np.clip(m_fine + m_big, 0, 1)
    m = np.asarray(Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.6)),
                   dtype=np.float32) / 255.0
    return np.clip(m * 1.6, 0, 1)


def hairlines(w, h, rng, wear):
    """Riscos finos e compridos (curvos), claros, mais perto das bordas."""
    mask = Image.new("L", (w * 2, h * 2), 0)  # supersample p/ linha fina
    d = ImageDraw.Draw(mask)
    n = int(18 * wear * (w * h) / (600 * 900))
    for _ in range(n):
        if rng.random() < 0.6:  # perto de uma borda
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
    """Duas ou três dobras bem sutis (par claro/escuro)."""
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


def process(arr, wear=1.0, halftone_amt=0.0, flat=0.35, seed=7):
    rng = np.random.default_rng(seed)
    h, w = arr.shape[:2]

    arr = mute_colors(arr)
    arr = lift_blacks(arr)
    arr = flatten_tones(arr, flat)

    # perda leve de nitidez (tinta assentada no papel)
    im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.6))
    arr = np.asarray(im, dtype=np.float32)

    arr = halftone(arr, halftone_amt)

    # desbotado irregular: variação suave de brilho (sem amarelar)
    mott = fractal_noise(w, h, rng, scales=(40, 120, 300), weights=(0.3, 0.4, 0.3))
    arr = arr * (0.94 + 0.10 * mott[..., None])

    # grão fino
    arr = arr + rng.normal(0, 3.2 * wear, (h, w)).astype(np.float32)[..., None]

    # dobras sutis
    cl, cd = creases(w, h, rng, wear)
    arr = arr + cl[..., None] * 9 * wear - cd[..., None] * 12 * wear

    # tinta lascada mostrando o papel
    flakes = ink_flakes(w, h, rng, wear)
    arr = arr * (1 - flakes[..., None] * 0.92) + PAPER * flakes[..., None] * 0.92

    # riscos finos claros
    hl = hairlines(w, h, rng, wear)
    arr = arr * (1 - hl[..., None] * 0.75) + PAPER * 1.04 * hl[..., None] * 0.75

    return np.clip(arr, 0, 255).astype(np.uint8)


# ===================== LASCAS NAS LOGOS =====================
def logo_flake_mask(w, h, rng, wear, fine=0.05, big=0.035):
    """Máscara 0..1 de tinta lascada espalhada pela logo toda (não só na borda)."""
    f = fractal_noise(w, h, rng, scales=(1, 2, 3), weights=(0.4, 0.35, 0.25))
    m_fine = (f > 1 - fine * wear).astype(np.float32)
    b = fractal_noise(w, h, rng, scales=(3, 6, 14), weights=(0.3, 0.4, 0.3))
    m_big = (b > 1 - big * wear).astype(np.float32)
    m = np.clip(m_fine + m_big, 0, 1)
    m = np.asarray(Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.5)),
                   dtype=np.float32) / 255.0
    return np.clip(m * 1.6, 0, 1)


def distress_logo(img, rng, wear, fine=0.05, big=0.035, scratches=True):
    """Tira tinta da logo (reduz o alfa): onde lasca, aparece o que está embaixo."""
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


# ===================== ASSETS (ficam na MESMA pasta do .py) =====================
def app_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def asset_path(name):
    """Procura o arquivo na pasta do programa (e na pasta interna do PyInstaller, se for .exe)."""
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


# ===================== LAYOUT (medido no template 564x877) =====================
ISSUE_BOX = (8, 100, 72, 125)          # x0, y0, x1, y1 - espaço do número
ISSUE_MAX_H = 13                       # altura máx. dos dígitos
ISSUE_COLOR = (0x40, 0x3B, 0x3B, 255)  # #403b3b
PUB_BOX = (12, 144, 68, 212)           # Centralizado visualmente abaixo do texto "PUBLISHER:"
PUB_PAD = 3
BARCODE_BOX = (14, 222, 68, 370)       # área exata do código de barras
LOGO_MAX_H_FRAC = 0.38


def trim(img):
    """Tira a margem transparente em volta da logo."""
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


def draw_publisher(canvas, pub_img, rng, wear_pub, seed, pub_zoom=1.0, pub_x=0.0, pub_y=0.0):
    """Logo da publisher com zoom e pan manuais, garantindo que nada saia do quadrado."""
    pub_img = trim(pub_img)
    x0, y0, x1, y1 = PUB_BOX
    w, h = x1 - x0, y1 - y0
    
    # Tamanho base pra caber certinho no quadrado
    iw, ih = w - 2 * PUB_PAD, h - 2 * PUB_PAD
    base_scale = min(iw / pub_img.width, ih / pub_img.height)
    
    # Aplica o multiplicador de zoom do usuário
    final_scale = base_scale * pub_zoom
    new_w = max(1, round(pub_img.width * final_scale))
    new_h = max(1, round(pub_img.height * final_scale))
    
    p = pub_img.resize((new_w, new_h), Image.LANCZOS)
    p = filter_logo(p, wear_pub, seed) # Filtro de cor igual ao da capa
    p = distress_logo(p, rng, wear_pub, fine=0.07, big=0.04, scratches=False)
    
    # O canvas da publisher, tudo que vazar dele é cortado!
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    
    # Centro matemático
    cx = (w - new_w) // 2
    cy = (h - new_h) // 2
    
    # Deslocamento manual do usuário
    cx += int(pub_x * (w / 2))
    cy += int(pub_y * (h / 2))
    
    # Usamos paste com a própria imagem como máscara (suporta coord negativa)
    layer.paste(p, (cx, cy), p)
    canvas.alpha_composite(layer, (x0, y0))


def filter_logo(img, wear, seed):
    """Aplica o mesmo color grading da capa (cores desbotadas, pretos quentes) na logo, mantendo transparência."""
    rng = np.random.default_rng(seed + 222)
    arr = np.asarray(img.convert("RGB"), dtype=np.float32)
    h, w = arr.shape[:2]
    
    arr = mute_colors(arr)
    arr = lift_blacks(arr)
    arr = flatten_tones(arr, 0.35)
    
    # Assentamento leve de tinta
    im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.6))
    arr = np.asarray(im, dtype=np.float32)
    
    # Grão pra não ficar liso demais
    arr = arr + rng.normal(0, 3.2 * wear, (h, w)).astype(np.float32)[..., None]
    
    out_rgb = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    out = img.copy()
    out.paste(out_rgb, (0, 0), img.getchannel("A"))
    return out


def place_game_logo(canvas, logo, width_frac, bottom_margin_frac, rng, wear_logo, seed):
    logo = trim(logo)
    W, H = canvas.size
    lw = int(W * width_frac)
    lh = int(logo.height * lw / logo.width)
    max_h = int(H * LOGO_MAX_H_FRAC)
    if lh > max_h:
        lh = max_h
        lw = int(logo.width * lh / logo.height)
    lg = logo.resize((max(1, lw), max(1, lh)), Image.LANCZOS)
    
    # Aplica o filtro de cor desbotada e depois as lascas
    lg = filter_logo(lg, wear_logo, seed)
    lg = distress_logo(lg, rng, wear_logo)
    
    x = (W - lw) // 2
    y = int(H * (1 - bottom_margin_frac)) - lh
    
    # Sombra automática pra dar contraste quando a logo for clara
    shadow_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shadow_alpha = lg.getchannel("A").point(lambda p: int(p * 0.8)) # opacidade da sombra
    shadow_layer.paste(Image.new("RGB", lg.size, (0, 0, 0)), (x, y + 4), shadow_alpha)
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(5))
    
    canvas.alpha_composite(shadow_layer)
    canvas.alpha_composite(lg, (x, y))
    return canvas


def draw_barcode(canvas, steam_id, wear):
    """Gera um código de barras procedural e desgasta ele inteiro igual à capa."""
    x0, y0, x1, y1 = BARCODE_BOX
    w, h = x1 - x0, y1 - y0
    
    layer = Image.new("RGB", (w, h), (226, 214, 188)) # opaco pra rodar no process()
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
        
    # Joga o barcode inteiro no moedor de carne da arte pra ficar igualzinho!
    arr = np.asarray(layer, dtype=np.float32)
    aged_arr = process(arr, wear=wear, seed=seed+111)
    aged_layer = Image.fromarray(aged_arr).convert("RGBA")
    
    canvas.alpha_composite(aged_layer, (x0, y0))

def compose(art_path, logo_path, pub_path, steam_id,
            logo_width=0.80, logo_bottom=0.10, wear_art=1.0, wear_logo=1.0, wear_pub=1.0, 
            art_zoom=1.0, art_x=0.0, art_y=0.0, 
            pub_zoom=1.0, pub_x=0.0, pub_y=0.0, preview=False):
    steam_id = str(steam_id).strip()
    
    # Previne erros ao apagar o ID na janela
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
    art = pan_zoom_art(art, tpl.size, zoom=art_zoom, pan_x=art_x, pan_y=art_y)
    
    if preview:
        # Encolhe a imagem antes do numpy para acelerar muito a prévia ao vivo
        small_art = art.resize((art.width // 2, art.height // 2), Image.BILINEAR)
        aged_small = Image.fromarray(process(np.asarray(small_art, dtype=np.float32), wear=wear_art, seed=seed))
        aged = aged_small.resize(tpl.size, Image.BILINEAR)
    else:
        aged = Image.fromarray(process(np.asarray(art, dtype=np.float32), wear=wear_art, seed=seed))

    canvas = aged.convert("RGBA")
    canvas = place_game_logo(canvas, Image.open(logo_path).convert("RGBA"), logo_width, logo_bottom, rng, wear_logo, seed)
    canvas.alpha_composite(tpl)
    draw_issue(canvas, steam_id)
    draw_barcode(canvas, steam_id, wear_pub)
    draw_publisher(canvas, Image.open(pub_path).convert("RGBA"), rng, wear_pub, seed, pub_zoom, pub_x, pub_y)
    return canvas


# ------------------------------- janela --------------------------------
def run_gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    from PIL import ImageTk

    root = tk.Tk()
    root.title("Gerador de capas - Steam Comics")
    root.resizable(False, False)

    paths = {"art": tk.StringVar(), "logo": tk.StringVar(), "pub": tk.StringVar()}
    steam = tk.StringVar()
    logo_w = tk.DoubleVar(value=0.80)
    logo_b = tk.DoubleVar(value=0.10)
def run_gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    from PIL import ImageTk

    root = tk.Tk()
    root.title("Gerador de capas - Steam Comics")
    root.geometry("900x680")
    root.resizable(False, False)

    # Tema mais limpo se disponível
    style = ttk.Style()
    if 'clam' in style.theme_names():
        style.theme_use('clam')
    
    style.configure("TLabelFrame", font=("Segoe UI", 10, "bold"), padding=10)
    style.configure("TLabelFrame.Label", font=("Segoe UI", 10, "bold"))
    style.configure("TButton", font=("Segoe UI", 9))

    paths = {"art": tk.StringVar(), "logo": tk.StringVar(), "pub": tk.StringVar()}
    steam = tk.StringVar()
    logo_w = tk.DoubleVar(value=0.80)
    logo_b = tk.DoubleVar(value=0.10)
    art_zoom = tk.DoubleVar(value=1.0)
    art_x = tk.DoubleVar(value=0.0)
    art_y = tk.DoubleVar(value=0.0)
    pub_zoom = tk.DoubleVar(value=1.0)
    pub_x = tk.DoubleVar(value=0.0)
    pub_y = tk.DoubleVar(value=0.0)
    wear_art = tk.DoubleVar(value=1.0)
    wear_logo = tk.DoubleVar(value=1.0)
    wear_pub = tk.DoubleVar(value=1.0)
    status = tk.StringVar(value="Pronto para criar!")
    preview_ref = {}

    types = [("Imagens", "*.png *.jpg *.jpeg *.webp *.bmp"), ("Todos", "*.*")]

    def pick(key):
        f = filedialog.askopenfilename(filetypes=types)
        if f:
            paths[key].set(f)

    # Divisão principal da janela
    left_frame = ttk.Frame(root)
    left_frame.pack(side="left", fill="both", expand=True, padx=12, pady=12)
    
    right_frame = ttk.Frame(root)
    right_frame.pack(side="right", fill="y", padx=(0, 12), pady=12)

    # Moldura da Prévia
    prev_frame = ttk.LabelFrame(right_frame, text="Prévia ao Vivo", padding=10)
    prev_frame.pack(fill="both", expand=True)
    prev = ttk.Label(prev_frame)
    prev.pack(expand=True)

    # Canvas de rolagem da esquerda
    canvas = tk.Canvas(left_frame, highlightthickness=0)
    scrollbar = ttk.Scrollbar(left_frame, orient="vertical", command=canvas.yview)
    frm = ttk.Frame(canvas)

    frm.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas_window = canvas.create_window((0, 0), window=frm, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    
    def _configure_canvas(event):
        canvas.itemconfig(canvas_window, width=event.width)
    canvas.bind('<Configure>', _configure_canvas)

    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    def _on_mousewheel(event):
        canvas.yview_scroll(int(-1*(event.delta/120)), "units")
    canvas.bind_all("<MouseWheel>", _on_mousewheel)

    # ---- BLOCO 1: ARQUIVOS ----
    gf = ttk.LabelFrame(frm, text="1. Arquivos Base")
    gf.pack(fill="x", expand=True, pady=(0, 12))
    
    rows = [("Arte de fundo", "art"), ("Logo do jogo", "logo"), ("Logo da publisher (obrigatória)", "pub")]
    for i, (label, key) in enumerate(rows):
        ttk.Label(gf, text=label).pack(anchor="w")
        ctrl_frm = ttk.Frame(gf)
        ctrl_frm.pack(fill="x", pady=(0, 8))
        ttk.Entry(ctrl_frm, textvariable=paths[key]).pack(side="left", fill="x", expand=True)
        ttk.Button(ctrl_frm, text="...", width=4, command=lambda k=key: pick(k)).pack(side="left", padx=(4, 0))

    ttk.Label(gf, text="Steam ID (issue #)").pack(anchor="w")
    ttk.Entry(gf, textvariable=steam, width=20).pack(anchor="w", pady=(0, 4))

    # Construtor de Sliders atualizado para usar .pack() e ficar flexível
    def slider(parent, label, var, a, b):
        container = ttk.Frame(parent)
        container.pack(fill="x", expand=True, pady=(0, 8))
        ttk.Label(container, text=label).pack(anchor="w")
        
        row_frm = ttk.Frame(container)
        row_frm.pack(fill="x", expand=True)
        ttk.Scale(row_frm, from_=a, to=b, variable=var, orient="horizontal").pack(side="left", fill="x", expand=True)
        ttk.Spinbox(row_frm, from_=a, to=b, increment=0.01, textvariable=var, width=6, format="%.2f").pack(side="left", padx=(8, 0))

    # ---- BLOCO 2: ARTE ----
    ga = ttk.LabelFrame(frm, text="2. Enquadramento da Arte")
    ga.pack(fill="x", expand=True, pady=(0, 12))
    slider(ga, "Zoom da Arte", art_zoom, 1.0, 3.0)
    slider(ga, "Mover Arte ↔", art_x, -1.0, 1.0)
    slider(ga, "Mover Arte ↕", art_y, -1.0, 1.0)

    # ---- BLOCO 3: LOGO JOGO ----
    gl = ttk.LabelFrame(frm, text="3. Logo do Jogo")
    gl.pack(fill="x", expand=True, pady=(0, 12))
    slider(gl, "Tamanho da logo", logo_w, 0.40, 0.95)
    slider(gl, "Altura da logo", logo_b, 0.0, 0.60)

    # ---- BLOCO 4: PUBLISHER ----
    gp = ttk.LabelFrame(frm, text="4. Logo da Publisher")
    gp.pack(fill="x", expand=True, pady=(0, 12))
    slider(gp, "Tamanho da Publisher", pub_zoom, 0.5, 3.0)
    slider(gp, "Mover Publisher ↔", pub_x, -1.0, 1.0)
    slider(gp, "Mover Publisher ↕", pub_y, -1.0, 1.0)

    # ---- BLOCO 5: DESGASTE ----
    gw = ttk.LabelFrame(frm, text="5. Efeitos de Desgaste (Sujeira e Lascas)")
    gw.pack(fill="x", expand=True, pady=(0, 12))
    slider(gw, "Desgaste da arte", wear_art, 0.0, 3.5)
    slider(gw, "Desgaste da logo do jogo", wear_logo, 0.0, 3.5)
    slider(gw, "Desgaste da publisher", wear_pub, 0.0, 3.5)

    # ---- RODAPÉ ----
    btn_frm = ttk.Frame(frm)
    btn_frm.pack(fill="x", pady=(8, 20))

    timer_id = [None]
    def schedule_preview(*args):
        if not paths["art"].get() or not paths["logo"].get() or not paths["pub"].get() or not steam.get():
            return
        if timer_id[0] is not None:
            root.after_cancel(timer_id[0])
        timer_id[0] = root.after(400, render_preview)

    def render_preview():
        try:
            status.set("Atualizando prévia...")
            img = compose(paths["art"].get(), paths["logo"].get(), paths["pub"].get(),
                          steam.get(), logo_w.get(), logo_b.get(), wear_art.get(), wear_logo.get(), wear_pub.get(), 
                          art_zoom.get(), art_x.get(), art_y.get(), 
                          pub_zoom.get(), pub_x.get(), pub_y.get(), preview=True)
            th = img.copy()
            th.thumbnail((300, 470), Image.LANCZOS)
            preview_ref["img"] = ImageTk.PhotoImage(th)
            prev.configure(image=preview_ref["img"])
            status.set("Prévia atualizada!")
        except Exception:
            pass

    # Triggers
    logo_w.trace_add("write", schedule_preview)
    logo_b.trace_add("write", schedule_preview)
    art_zoom.trace_add("write", schedule_preview)
    art_x.trace_add("write", schedule_preview)
    art_y.trace_add("write", schedule_preview)
    pub_zoom.trace_add("write", schedule_preview)
    pub_x.trace_add("write", schedule_preview)
    pub_y.trace_add("write", schedule_preview)
    wear_art.trace_add("write", schedule_preview)
    wear_logo.trace_add("write", schedule_preview)
    wear_pub.trace_add("write", schedule_preview)
    steam.trace_add("write", schedule_preview)
    paths["art"].trace_add("write", schedule_preview)
    paths["logo"].trace_add("write", schedule_preview)
    paths["pub"].trace_add("write", schedule_preview)

    def gerar():
        try:
            status.set("Gerando capa em alta resolução...")
            root.update_idletasks()
            img = compose(paths["art"].get(), paths["logo"].get(), paths["pub"].get(),
                          steam.get(), logo_w.get(), logo_b.get(), wear_art.get(), wear_logo.get(), wear_pub.get(),
                          art_zoom.get(), art_x.get(), art_y.get(), 
                          pub_zoom.get(), pub_x.get(), pub_y.get(), preview=False)
            out = app_dir() / f"final_{steam.get().strip()}.png"
            img.save(out)
            status.set(f"Pronto! Salvo em {out}")
        except Exception as e:
            status.set("Erro.")
            messagebox.showerror("Erro", str(e))

    ttk.Button(btn_frm, text="Gerar capa final", command=gerar).pack(side="left")
    ttk.Label(btn_frm, textvariable=status, wraplength=250).pack(side="left", padx=10)
    
    root.mainloop()


if __name__ == "__main__":
    run_gui()
