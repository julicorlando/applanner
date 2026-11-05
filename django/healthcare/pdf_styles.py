"""Embedded fonts keep clinical exports readable on devices without PDF core fonts."""
from pathlib import Path
from threading import Lock
import reportlab
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.styles import getSampleStyleSheet

_lock=Lock()

def clinical_pdf_styles():
    with _lock:
        if 'ClinicalVera' not in pdfmetrics.getRegisteredFontNames():
            root=Path(reportlab.__file__).parent/'fonts'
            for name,file in [('ClinicalVera','Vera.ttf'),('ClinicalVera-Bold','VeraBd.ttf'),('ClinicalVera-Italic','VeraIt.ttf'),('ClinicalVera-BoldItalic','VeraBI.ttf')]:
                pdfmetrics.registerFont(TTFont(name,str(root/file)))
            pdfmetrics.registerFontFamily('ClinicalVera',normal='ClinicalVera',bold='ClinicalVera-Bold',italic='ClinicalVera-Italic',boldItalic='ClinicalVera-BoldItalic')
    styles=getSampleStyleSheet()
    for style in styles.byName.values():
        if hasattr(style,'fontName'):
            style.fontName='ClinicalVera-Bold' if 'Bold' in style.fontName else 'ClinicalVera'
    return styles
