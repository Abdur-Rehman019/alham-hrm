"""
Counselor of the Month certificate (A4 landscape), in the style of ALHAM's promotion certificate:
blue patterned frame, white card, blue logo, gold medal, faint "A" mark, gold script name.
"""
import base64
import functools
import io
import logging
import math
from pathlib import Path

from django.conf import settings
from reportlab.lib.colors import Color, HexColor, white
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as pdf_canvas

logger = logging.getLogger(__name__)

BLUE = HexColor('#1546b0')
BLUE_DARK = HexColor('#0f3a94')
TEXT_BLUE = HexColor('#0d3fb0')
INK = HexColor('#111111')
GREY = HexColor('#333333')
WATERMARK = HexColor('#d9e6f2')
GOLD = HexColor('#b07d2b')
GOLD_LIGHT = HexColor('#f6dc8c')
GOLD_MID = HexColor('#d9ad4c')
GOLD_DARK = HexColor('#9a6a1f')

STATIC = Path(settings.BASE_DIR) / 'static'
SCRIPT_FONT_FILE = STATIC / 'fonts' / 'GreatVibes-Regular.ttf'
SIGNATURE_FILE = Path(settings.BASE_DIR) / 'private' / 'ceo_signature.png'  # git-ignored, never public


@functools.lru_cache(maxsize=1)
def _signature():
    """The CEO's signature from the private Railway variable, or the local private file; None if neither."""
    if settings.CERTIFICATE_SIGNATURE_B64:
        try:
            return ImageReader(io.BytesIO(base64.b64decode(settings.CERTIFICATE_SIGNATURE_B64)))
        except Exception:
            logger.exception('CERTIFICATE_SIGNATURE_B64 is not a valid base64 PNG; printing a signature line instead')
            return None
    return ImageReader(str(SIGNATURE_FILE)) if SIGNATURE_FILE.exists() else None


@functools.lru_cache(maxsize=1)
def _script_font():
    """Handwriting-style font for the name if it is installed, otherwise an elegant built-in italic."""
    if SCRIPT_FONT_FILE.exists():
        pdfmetrics.registerFont(TTFont('CertificateScript', str(SCRIPT_FONT_FILE)))
        return 'CertificateScript', 1.0
    return 'Times-Italic', 0.82


@functools.lru_cache(maxsize=1)
def _blue_logo():
    """The white sidebar logo, recoloured blue for a white page."""
    from PIL import Image
    logo = Image.open(STATIC / 'images' / 'logo.png').convert('RGBA')
    blue = Image.new('RGBA', logo.size, (21, 70, 176, 255))
    blue.putalpha(logo.getchannel('A'))
    return ImageReader(blue), logo.size


def _spaced(c, text, x, y, font, size, spacing, color):
    """Centered text with extra letter spacing."""
    c.setFont(font, size)
    c.setFillColor(color)
    width = pdfmetrics.stringWidth(text, font, size) + spacing * (len(text) - 1)
    t = c.beginText(x - width / 2, y)
    t.setFont(font, size)
    t.setCharSpace(spacing)
    t.textOut(text)
    c.drawText(t)


def _frame(c, w, h):
    c.setFillColor(BLUE)
    c.rect(0, 0, w, h, fill=1, stroke=0)
    # Faint diagonal lattice, like the pattern on the printed certificates.
    c.saveState()
    c.setStrokeColor(Color(1, 1, 1, alpha=0.07))
    c.setLineWidth(1.2)
    step = 46
    for i in range(-int(h / step) - 2, int(w / step) + 3):
        c.line(i * step, 0, i * step + h, h)
        c.line(i * step, h, i * step + h, 0)
    c.restoreState()


def _watermark(c, x, y, s):
    """The three shapes of the ALHAM mark (from logo.svg), scaled; (x, y) is the mark's bottom-left."""
    shapes = [
        [(96.58, 108.32), (127.62, 162.9), (96.6, 153.06), (65.58, 162.9)],
        [(117.09, 126.22), (96.6, 90.43), (75.84, 54.84), (96.6, 19.2), (158.34, 126.22)],
        [(76.11, 126.22), (34.86, 126.22), (55.35, 90.43), (96.6, 90.43)],
    ]
    c.setFillColor(WATERMARK)
    for shape in shapes:
        path = c.beginPath()
        # SVG y grows downwards; flip it.
        points = [(x + (px - 34.86) * s, y + (162.9 - py) * s) for px, py in shape]
        path.moveTo(*points[0])
        for point in points[1:]:
            path.lineTo(*point)
        path.close()
        c.drawPath(path, fill=1, stroke=0)


def _medal(c, cx, cy, r):
    # Ribbon tails behind the medal.
    for direction in (-1, 1):
        x0 = cx + direction * r * 0.25
        path = c.beginPath()
        path.moveTo(x0 - r * 0.32, cy)
        path.lineTo(x0 + r * 0.32, cy)
        path.lineTo(x0 + r * 0.32 + direction * r * 0.18, cy - r * 1.55)
        path.lineTo(x0 + direction * r * 0.09, cy - r * 1.3)
        path.lineTo(x0 - r * 0.32 + direction * r * 0.18, cy - r * 1.55)
        path.close()
        c.setFillColor(GOLD_MID if direction < 0 else GOLD)
        c.drawPath(path, fill=1, stroke=0)
    # Ribbon strip above the medal.
    c.setFillColor(GOLD)
    c.rect(cx - r * 0.45, cy, r * 0.9, r * 1.8, fill=1, stroke=0)
    c.setFillColor(GOLD_LIGHT)
    c.rect(cx - r * 0.12, cy, r * 0.24, r * 1.8, fill=1, stroke=0)
    # Scalloped rim.
    teeth = 28
    path = c.beginPath()
    for i in range(teeth * 2 + 1):
        angle = math.pi * i / teeth
        radius = r * (1.0 if i % 2 == 0 else 0.92)
        point = (cx + radius * math.cos(angle), cy + radius * math.sin(angle))
        path.moveTo(*point) if i == 0 else path.lineTo(*point)
    path.close()
    c.setFillColor(GOLD_DARK)
    c.drawPath(path, fill=1, stroke=0)
    # Shiny face.
    c.saveState()
    face = c.beginPath()
    face.circle(cx, cy, r * 0.84)
    c.clipPath(face, stroke=0, fill=0)
    c.radialGradient(cx - r * 0.25, cy + r * 0.25, r * 1.1, (GOLD_LIGHT, GOLD_MID, GOLD_DARK), extend=True)
    c.restoreState()
    c.setStrokeColor(GOLD_LIGHT)
    c.setLineWidth(1.2)
    c.circle(cx, cy, r * 0.66, stroke=1, fill=0)


def _wrap(text, font, size, max_width):
    words, lines, line = text.split(), [], ''
    for word in words:
        trial = f'{line} {word}'.strip()
        if pdfmetrics.stringWidth(trial, font, size) <= max_width:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def draw_counselor_certificate(response, name, period_label, enrollment_count):
    page = landscape(A4)
    w, h = page
    c = pdf_canvas.Canvas(response, pagesize=page)
    c.setTitle(f'Counselor of the Month - {name} - {period_label}')

    _frame(c, w, h)

    # White card and its thin inner border.
    margin_x, margin_y = 34, 30
    c.setFillColor(white)
    c.rect(margin_x, margin_y, w - 2 * margin_x, h - 2 * margin_y, fill=1, stroke=0)
    inner_x, inner_y = margin_x + 20, margin_y + 20
    inner_w, inner_h = w - 2 * inner_x, h - 2 * inner_y

    c.saveState()
    clip = c.beginPath()
    clip.rect(margin_x, margin_y, w - 2 * margin_x, h - 2 * margin_y)
    c.clipPath(clip, stroke=0, fill=0)
    _watermark(c, w * 0.63, margin_y - 4, 3.05)
    c.restoreState()

    c.setStrokeColor(INK)
    c.setLineWidth(1.3)
    c.rect(inner_x, inner_y, inner_w, inner_h, fill=0, stroke=1)

    # Logo, top left.
    logo, (lw, lh) = _blue_logo()
    logo_w = 118
    c.drawImage(logo, inner_x + 26, h - inner_y - 58, width=logo_w, height=logo_w * lh / lw, mask='auto')

    # Medal, top right.
    _medal(c, w - inner_x - 82, h - inner_y - 92, 46)

    cx = w / 2
    top = h - inner_y
    _spaced(c, 'CERTIFICATE', cx, top - 70, 'Helvetica-Bold', 46, 2.5, INK)
    _spaced(c, 'OF ACHIEVEMENT', cx, top - 100, 'Helvetica', 19, 3, GREY)
    _spaced(c, 'This certificate is proudly presented to', cx, top - 138, 'Helvetica', 11.5, 0.3, INK)

    script, scale = _script_font()
    size = 62 * scale
    while pdfmetrics.stringWidth(name, script, size) > inner_w * 0.62 and size > 26:
        size -= 2
    c.setFont(script, size)
    c.setFillColor(GOLD)
    c.drawCentredString(cx, top - 198, name)

    _spaced(c, 'For Being Selected As', cx, top - 232, 'Helvetica-Bold', 11.5, 0.2, INK)
    _spaced(c, 'Counselor of the Month', cx, top - 262, 'Helvetica-Bold', 22, 0.6, TEXT_BLUE)

    students = f"{enrollment_count} Student Enrollment{'s' if enrollment_count != 1 else ''}"
    body = (f'In Recognition Of Outstanding Performance In {period_label}, With {students} Confirmed. '
            'Your Dedication Helps Our Students Reach Their Dreams, And We Truly Appreciate Your Hard Work. '
            'Congratulations And Keep It Up!')
    c.setFont('Helvetica', 11.5)
    c.setFillColor(GREY)
    for i, line in enumerate(_wrap(body, 'Helvetica', 11.5, inner_w * 0.68)):
        c.drawCentredString(cx, top - 294 - i * 17, line)

    # Signature block.
    sig_y = inner_y + 52
    sig = _signature()
    if sig is not None:
        sw, sh = sig.getSize()
        sig_w = 118
        c.drawImage(sig, cx - sig_w / 2, sig_y + 12, width=sig_w, height=sig_w * sh / sw, mask='auto')
    else:
        c.setStrokeColor(GREY)
        c.setLineWidth(0.8)
        c.line(cx - 80, sig_y + 18, cx + 80, sig_y + 18)
    _spaced(c, settings.CERTIFICATE_SIGNATORY_NAME, cx, sig_y, 'Helvetica-Bold', 12.5, 0.3, TEXT_BLUE)
    _spaced(c, settings.CERTIFICATE_SIGNATORY_TITLE, cx, sig_y - 15, 'Helvetica', 10, 0.3, GREY)

    c.showPage()
    c.save()
