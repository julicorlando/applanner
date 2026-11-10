"""PDF of issued clinical documents in the clinic letterhead layout.

Pure rendering: callers pass already-authorized, plain values. No network
access; the logo is read by the caller from the tenant's validated storage.
"""
import re
from io import BytesIO
from xml.sax.saxutils import escape
from PIL import Image, UnidentifiedImageError
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (BaseDocTemplate, Frame, Image as PDFImage, KeepTogether,
                                PageTemplate, Paragraph, Spacer, Table, TableStyle)
from .pdf_styles import clinical_pdf_styles

MONTHS = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
          "agosto", "setembro", "outubro", "novembro", "dezembro")
TITLES = {"prescription": "RECEITUÁRIO", "certificate": "ATESTADO",
          "declaration": "DECLARAÇÃO", "budget": "ORÇAMENTO"}
ROLE_BY_COUNCIL = {"CRO": "Cirurgião-Dentista", "CREFITO": "Fisioterapeuta"}
LABEL_LINE = re.compile(r"^([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ /().º°-]{1,38}):(\s.*|)$")
PAGE_W, PAGE_H = A4


def long_date(city, when):
    text = f"{when.day:02d} de {MONTHS[when.month - 1]} de {when.year}"
    return f"{city}, {text}" if city else text


def _image(raw, max_px):
    if not raw:
        return None
    try:
        with Image.open(BytesIO(raw)) as source:
            if source.width * source.height > 4_000_000:
                return None
            picture = source.convert("RGBA")
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        return None
    picture.thumbnail(max_px)
    return picture


def _png(picture):
    out = BytesIO()
    picture.save(out, "PNG")
    out.seek(0)
    return out


def _faded(picture, opacity):
    faded = picture.copy()
    alpha = faded.getchannel("A").point(lambda value: int(value * opacity))
    faded.putalpha(alpha)
    return faded


def _styles(primary):
    base = clinical_pdf_styles()["Normal"]
    common = {"fontName": "ClinicalVera", "fontSize": 11, "leading": 16, "textColor": colors.HexColor("#1f2937")}
    return {
        "title": ParagraphStyle("DocTitle", parent=base, fontName="ClinicalVera-Bold", fontSize=13, leading=18,
                                alignment=TA_CENTER, textColor=colors.black, spaceAfter=18),
        "body": ParagraphStyle("DocBody", parent=base, alignment=TA_LEFT, **common),
        "justify": ParagraphStyle("DocJustify", parent=base, alignment=TA_JUSTIFY, firstLineIndent=36, **common),
        "center": ParagraphStyle("DocCenter", parent=base, alignment=TA_CENTER, **common),
        "brand": ParagraphStyle("DocBrand", parent=base, fontName="ClinicalVera-Bold", fontSize=18, leading=22,
                                alignment=TA_CENTER, textColor=primary),
        "small": ParagraphStyle("DocSmall", parent=base, fontSize=7, leading=9, textColor=colors.HexColor("#6b7280")),
    }


def _line(text, styles, justify):
    if text.startswith("## "):
        return Paragraph(f"<b><u>{escape(text[3:].strip())}</u></b>", styles["body"])
    match = LABEL_LINE.match(text)
    if match and not justify:
        return Paragraph(f"<b>{escape(match.group(1))}:</b>{escape(match.group(2))}", styles["body"])
    if text.startswith(("- ", "• ")):
        return Paragraph(escape(text), styles["body"])
    return Paragraph(escape(text) or "&nbsp;", styles["justify"] if justify else styles["body"])


def render_document(*, kind, title, body, clinic, patient, professional, issued_at,
                    signature_png=b"", verification_url="", verification_code=""):
    """clinic: name, logo(bytes), primary_color, city, phone, whatsapp, instagram, email, address.
    patient: name, cpf, phone, address, birth_date (str). professional: name, council, number, jurisdiction."""
    primary = colors.HexColor(clinic.get("primary_color")) if re.fullmatch(r"#[0-9a-fA-F]{6}", clinic.get("primary_color") or "") else colors.HexColor("#1f2937")
    styles = _styles(primary)
    logo = _image(clinic.get("logo"), (900, 300))
    watermark = _faded(logo, 0.09) if logo else None
    signature = _image(signature_png, (900, 300))
    footer_contacts = " · ".join(v for v in (
        clinic.get("whatsapp") or clinic.get("phone"),
        ("@" + clinic["instagram"].lstrip("@")) if clinic.get("instagram") else "",
        clinic.get("email"),
    ) if v)
    footer_address = clinic.get("address") or ""
    qr_size = 74

    def decorate(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(primary)
        canvas.setLineWidth(3)
        canvas.line(0, PAGE_H - 6, PAGE_W, PAGE_H - 6)
        canvas.line(0, 6, PAGE_W, 6)
        if logo:
            width = 190
            height = width * logo.height / logo.width
            if height > 62:
                height, width = 62, 62 * logo.width / logo.height
            canvas.drawImage(ImageReader(_png(logo)), (PAGE_W - width) / 2, PAGE_H - 34 - height,
                             width, height, mask="auto")
        else:
            canvas.setFont("ClinicalVera-Bold", 18)
            canvas.setFillColor(primary)
            canvas.drawCentredString(PAGE_W / 2, PAGE_H - 70, clinic.get("name", "")[:60])
        if watermark:
            width = PAGE_W * 0.72
            height = width * watermark.height / watermark.width
            canvas.drawImage(ImageReader(_png(watermark)), (PAGE_W - width) / 2, (PAGE_H - height) / 2 - 10,
                             width, height, mask="auto")
        canvas.setStrokeColor(colors.HexColor("#d1d5db"))
        canvas.setLineWidth(0.6)
        canvas.line(56, 58, PAGE_W - 56, 58)
        canvas.setFillColor(colors.HexColor("#374151"))
        canvas.setFont("ClinicalVera", 9)
        if footer_contacts:
            canvas.drawCentredString(PAGE_W / 2, 42, footer_contacts[:110])
        if footer_address:
            canvas.drawCentredString(PAGE_W / 2, 29, footer_address[:120])
        if verification_url:
            widget = QrCodeWidget(verification_url, barLevel="M")
            x0, y0, x1, y1 = widget.getBounds()
            drawing = Drawing(qr_size, qr_size, transform=[qr_size / (x1 - x0), 0, 0, qr_size / (y1 - y0), 0, 0])
            drawing.add(widget)
            renderPDF.draw(drawing, canvas, PAGE_W - 56 - qr_size, 64)
            canvas.setFont("ClinicalVera", 6.5)
            canvas.setFillColor(colors.HexColor("#4b5563"))
            lines = ["Documento emitido eletronicamente pelo ApPlanner.",
                     "Confira a autenticidade lendo o QR code ou acessando:",
                     verification_url[:95],
                     f"Código de validação: {verification_code}" if verification_code else "",
                     "A imagem da assinatura não substitui certificado digital ICP-Brasil."]
            y = 64 + qr_size - 10
            for text in lines:
                if text:
                    canvas.drawRightString(PAGE_W - 64 - qr_size, y, text)
                y -= 9
        canvas.drawRightString(PAGE_W - 56, 14, f"Página {doc.page}")
        canvas.restoreState()

    buffer = BytesIO()
    doc = BaseDocTemplate(buffer, pagesize=A4, title=title, author=professional.get("name", ""),
                          leftMargin=62, rightMargin=62, topMargin=112, bottomMargin=150)
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="body")
    doc.addPageTemplates([PageTemplate(id="letterhead", frames=[frame], onPage=decorate)])

    story = [Paragraph(f"<u>{escape(TITLES.get(kind, title.upper()))}</u>", styles["title"])]
    justify = kind in {"certificate", "declaration"}
    if kind == "prescription":
        story += [Paragraph(f"<b>Para:</b> {escape(patient.get('name', ''))}", styles["body"]), Spacer(1, 10)]
    elif kind == "budget":
        for label, key in (("Paciente", "name"), ("CPF", "cpf"), ("Endereço", "address"),
                           ("Data de Nascimento", "birth_date"), ("Fone", "phone")):
            if patient.get(key):
                story.append(Paragraph(f"<b>{label}:</b> {escape(str(patient[key]))}", styles["body"]))
        story.append(Spacer(1, 12))
    elif patient.get("name") and patient["name"].casefold() not in body.casefold():
        identity = f"Paciente: {patient['name']}" + (f" · CPF: {patient['cpf']}" if patient.get("cpf") else "")
        story += [Paragraph(escape(identity), styles["body"]), Spacer(1, 8)]

    for raw_line in body.splitlines():
        story.append(_line(raw_line.rstrip(), styles, justify))
        story.append(Spacer(1, 4 if not justify else 2))

    block = [Spacer(1, 26), Paragraph(escape(long_date(clinic.get("city", ""), issued_at)), styles["center"]),
             Spacer(1, 20)]
    if signature:
        width = 150
        height = width * signature.height / signature.width
        if height > 52:
            height, width = 52, 52 * signature.width / signature.height
        block.append(PDFImage(_png(signature), width=width, height=height))
    else:
        block.append(Spacer(1, 40))
    rule = Table([[""]], colWidths=[210], rowHeights=[2])
    rule.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, -1), 0.7, colors.black)]))
    council = professional.get("council", "")
    registration = f"{council}-{professional.get('jurisdiction', '')} {professional.get('number', '')}".strip()
    block += [rule,
              Paragraph(f"<b>{escape(professional.get('name', ''))}</b>", styles["center"]),
              Paragraph(escape(ROLE_BY_COUNCIL.get(council, "Profissional de saúde")), styles["center"]),
              Paragraph(escape(registration), styles["center"])]
    story.append(KeepTogether(block))
    doc.build(story)
    return buffer.getvalue()
