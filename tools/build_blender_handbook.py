"""Build the original authoring manuscript to a checked 50-100 page A5 PDF and offline HTML."""

from __future__ import annotations

import ast
import base64
import hashlib
import html
import json
import re
from pathlib import Path

import markdown
import pymupdf as fitz
from PIL import Image as PILImage
from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A5
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

ROOT = Path(__file__).resolve().parents[1]
BOOK = ROOT / "docs" / "book"
PDF = ROOT / "docs" / "TrickRoom-Blender-Authoring-Handbook.pdf"


def source_link(match):
    relative, symbol = match.group(1).split("::", 1)
    path = ROOT.joinpath(*relative.split("/"))
    tree = ast.parse(path.read_text(encoding="utf-8"))
    target = symbol.split(".")
    nodes = tree.body
    found = None
    for part in target:
        found = next(
            (n for n in nodes if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == part),
            None,
        )
        if found is None:
            raise ValueError(f"Unresolved source citation: {relative}::{symbol}")
        nodes = found.body
    return f"`{relative}:{found.lineno}` (`{symbol}`)"


def inline(text):
    text = html.escape(text)
    text = re.sub(r"`([^`]+)`", r'<font name="Mono" size="8.7">\1</font>', text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r'<a href="\2" color="#325a83">\1</a>', text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return text


class Handbook(BaseDocTemplate):
    def __init__(self, filename):
        super().__init__(
            filename,
            pagesize=A5,
            leftMargin=40,
            rightMargin=40,
            topMargin=44,
            bottomMargin=42,
            title="TrickRoom Blender Authoring Handbook",
            author="TrickRoom engineering",
            allowSplitting=True,
        )
        frame = Frame(
            self.leftMargin,
            self.bottomMargin,
            self.width,
            self.height,
            id="body",
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
        )
        self.addPageTemplates(PageTemplate(id="body", frames=frame, onPage=self.page_chrome))
        self.chapter_pages = {}

    @staticmethod
    def page_chrome(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#aebec7"))
        canvas.line(40, 29, A5[0] - 40, 29)
        canvas.setFont("Body", 7.5)
        canvas.setFillColor(colors.HexColor("#526573"))
        canvas.drawString(40, 18, "TRICKROOM / BLENDER AUTHORING / PROFILE 1")
        canvas.drawRightString(A5[0] - 40, 18, str(doc.page))
        canvas.restoreState()

    def afterFlowable(self, flowable):
        if (
            isinstance(flowable, Paragraph)
            and flowable.style.name == "Chapter"
            and re.match(r"^\d{2}\.", flowable.getPlainText())
        ):
            title = flowable.getPlainText()
            key = "chapter-" + hashlib.sha256(title.encode()).hexdigest()[:10]
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(title, key, 0)
            self.notify("TOCEntry", (0, title, self.page, key))
            self.chapter_pages[title] = self.page


def build():
    source = BOOK / "AUTHORING.md"
    raw = source.read_text(encoding="utf-8")
    resolved = re.sub(r"\{\{source:([^}]+)\}\}", source_link, raw)
    (BOOK / "AUTHORING-resolved.md").write_text(resolved, encoding="utf-8")
    text = re.sub(r"\A---\n.*?\n---\n", "", resolved, flags=re.S)
    pdfmetrics.registerFont(TTFont("Body", r"C:\Windows\Fonts\calibri.ttf"))
    pdfmetrics.registerFont(TTFont("BodyBold", r"C:\Windows\Fonts\calibrib.ttf"))
    pdfmetrics.registerFont(TTFont("BodyItalic", r"C:\Windows\Fonts\calibrii.ttf"))
    pdfmetrics.registerFont(TTFont("Mono", r"C:\Windows\Fonts\consola.ttf"))
    pdfmetrics.registerFontFamily(
        "Body", normal="Body", bold="BodyBold", italic="BodyItalic", boldItalic="BodyBold"
    )
    body = ParagraphStyle(
        "BodyTextBook",
        fontName="Body",
        fontSize=10.8,
        leading=14.5,
        spaceAfter=7,
        textColor=colors.HexColor("#202d35"),
    )
    chapter = ParagraphStyle(
        "Chapter",
        parent=body,
        fontName="BodyBold",
        fontSize=20,
        leading=23,
        spaceAfter=14,
        textColor=colors.HexColor("#164f54"),
    )
    section = ParagraphStyle(
        "Section",
        parent=body,
        fontName="BodyBold",
        fontSize=13,
        leading=16,
        spaceBefore=10,
        spaceAfter=7,
        keepWithNext=True,
    )
    caption = ParagraphStyle(
        "Caption",
        parent=body,
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#526573"),
        alignment=TA_CENTER,
    )
    cell = ParagraphStyle("Cell", parent=body, fontSize=8.4, leading=10.4, spaceAfter=0)
    code = ParagraphStyle(
        "Code",
        fontName="Mono",
        fontSize=7.2,
        leading=9.3,
        backColor=colors.HexColor("#eef3f4"),
        borderPadding=6,
        spaceBefore=4,
        spaceAfter=9,
    )
    story = [
        Spacer(1, 38),
        Paragraph("TRICKROOM", ParagraphStyle("Cover", parent=chapter, fontSize=32, leading=38)),
        Paragraph("Blender Avatar<br/>Authoring Handbook", chapter),
        Paragraph(
            "Model, rig, export, validate and animate<br/>"
            "against the implemented Profile 1 runtime.",
            ParagraphStyle("Subtitle", parent=body, fontSize=15, leading=20),
        ),
        Spacer(1, 18),
        Image(str(ROOT / "docs" / "images" / "room" / "lab-character.png"), width=340, height=255),
        Spacer(1, 12),
        Paragraph("Local engineering edition / 2026-10-12", caption),
        PageBreak(),
        Paragraph("How to use this handbook", chapter),
        Paragraph(
            "This is an original implementation-specific guide, not a generic Blender manual. "
            "Follow the supported contract rather than assuming every Blender feature survives "
            "runtime export. The technical conformance rig proves the pipeline, not the final "
            "character artwork. Use the practical checkpoints before investing in polish.",
            body,
        ),
        Paragraph(
            "Recommended order: chapters 1-8 before modeling; 9-20 while rigging and surfacing; "
            "21-26 for export/import and runtime behavior; 27-30 for validation and delivery; "
            "31-35 for hands-on construction, weighting, shapes and export workshops. "
            "Source citations resolve to the checked repository snapshot. URLs identify upstream "
            "specifications; authoring and runtime guarantees come from the tested implementation.",
            body,
        ),
        Paragraph(
            "Evidence boundary: Blender exports, numerical deformation comparisons, synthetic "
            "motion, model previews and local transport checks were executed. Your real phone "
            "framing, motion quality and artistic approval are separate acceptance steps. "
            "No raw camera media or credentials are included.",
            body,
        ),
        Paragraph(
            "Editable source: docs/book/AUTHORING.md. Rebuild: "
            "<font name='Mono' size='8'>python tools/build_blender_handbook.py</font>. "
            "The builder refuses a PDF outside the requested 50-100 page range and records "
            "source, model and document hashes.",
            body,
        ),
        PageBreak(),
        Paragraph("Contents", chapter),
    ]
    toc = TableOfContents()
    toc.levelStyles = [
        ParagraphStyle(
            "TOC",
            parent=body,
            fontSize=9,
            leading=13,
            leftIndent=0,
            firstLineIndent=0,
            spaceBefore=3,
        )
    ]
    story.extend((toc, PageBreak()))
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if line.startswith("# "):
            i += 1
            continue
        if line.startswith("## "):
            if story and not isinstance(story[-1], PageBreak):
                story.append(PageBreak())
            story.append(Paragraph(inline(line[3:]), chapter))
            i += 1
            continue
        if line.startswith("### "):
            story.append(Paragraph(inline(line[4:]), section))
            i += 1
            continue
        if line.startswith("```"):
            language = line[3:]
            block = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                block.append(lines[i])
                i += 1
            i += 1
            if language == "mermaid":
                filename = "pipeline.png" if "flowchart" in "\n".join(block) else "validation.png"
                path = BOOK / "diagrams" / filename
                if not path.is_file():
                    raise FileNotFoundError(f"Render Mermaid diagram first: {filename}")
                with PILImage.open(path) as image:
                    w, h = image.size
                factor = min(335 / w, 400 / h)
                story.append(Image(str(path), width=w * factor, height=h * factor))
                story.append(Spacer(1, 8))
            else:
                if any(len(value) > 91 for value in block):
                    raise ValueError(f"Code line too wide for printed page: {block}")
                story.append(Preformatted("\n".join(block), code))
            continue
        image_match = re.fullmatch(r"!\[([^]]*)\]\(([^)]+)\)", line)
        if image_match:
            alt, target = image_match.groups()
            path = (BOOK / target).resolve()
            with PILImage.open(path) as image:
                w, h = image.size
            factor = min(335 / w, 290 / h)
            story.append(
                KeepTogether(
                    [
                        Image(str(path), width=w * factor, height=h * factor),
                        Paragraph(inline(alt), caption),
                        Spacer(1, 8),
                    ]
                )
            )
            i += 1
            continue
        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [value.strip() for value in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-+:?", value) for value in cells):
                    rows.append([Paragraph(inline(value), cell) for value in cells])
                i += 1
            columns = len(rows[0])
            widths = [340 / columns] * columns
            table_ = Table(rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
            table_.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dfecef")),
                        (
                            "ROWBACKGROUNDS",
                            (0, 1),
                            (-1, -1),
                            [colors.white, colors.HexColor("#f3f6f7")],
                        ),
                        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#bacbd2")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 5),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                        ("TOPPADDING", (0, 0), (-1, -1), 5),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ]
                )
            )
            story.extend((table_, Spacer(1, 9)))
            continue
        if re.match(r"^(- |\d+\. )", line):
            bullet = re.sub(r"^(- |\d+\. )", "", line)
            story.append(
                Paragraph(
                    inline(bullet),
                    body,
                    bulletText="\u2022" if line.startswith("- ") else line.split()[0],
                )
            )
            i += 1
            continue
        paragraph = [line.lstrip("> ")]
        i += 1
        while (
            i < len(lines)
            and lines[i].strip()
            and not re.match(r"^(#|```|\||!\[|- |\d+\. )", lines[i])
        ):
            paragraph.append(lines[i].lstrip("> "))
            i += 1
        story.append(Paragraph(inline(" ".join(paragraph)), body))
    document = Handbook(str(PDF))
    document.multiBuild(story)
    reader = PdfReader(PDF)
    page_count = len(reader.pages)
    if not 50 <= page_count <= 100:
        raise ValueError(f"Handbook is {page_count} pages; required 50-100. Revise content/layout.")
    converter = markdown.Markdown(extensions=["tables", "fenced_code", "toc"])
    html_text = converter.convert(text)
    html_text = (
        "<details><summary>Chapter navigation</summary>" + converter.toc + "</details>" + html_text
    )
    for name, filename in (("flowchart", "pipeline.png"), ("sequenceDiagram", "validation.png")):
        pattern = rf'<pre><code class="language-mermaid">.*?{name}.*?</code></pre>'
        png = base64.b64encode((BOOK / "diagrams" / filename).read_bytes()).decode()
        html_text = re.sub(
            pattern,
            f'<img alt="{name} architecture diagram" src="data:image/png;base64,{png}">',
            html_text,
            count=1,
            flags=re.S,
        )

    def embed_image(match):
        value = match.group(1)
        if value.startswith("data:"):
            return match.group(0)
        image_path = (BOOK / value).resolve()
        mime = "image/png" if image_path.suffix == ".png" else "image/gif"
        return f'src="data:{mime};base64,{base64.b64encode(image_path.read_bytes()).decode()}"'

    html_text = re.sub(r'src="([^"]+)"', embed_image, html_text)
    stylesheet = """
body{margin:auto;max-width:980px;padding:48px 28px;background:#101820;color:#dce8eb;
font:17px/1.65 system-ui}h1,h2,h3{color:#8cdfcf}h2{margin-top:3em;border-top:1px solid #3a5260;
padding-top:1em}a{color:#adccff}code,pre{font-family:Consolas,monospace}pre{overflow:auto;background:
#1d2a36;padding:20px;border-radius:8px;font-size:14px}table{border-collapse:collapse;width:100%}
td,th{border:1px solid #425965;padding:10px;text-align:left}th{background:#243642}
img{max-width:100%;height:auto;display:block;margin:20px auto}p{max-width:80ch}
"""
    (BOOK / "index.html").write_text(
        "<!doctype html><html lang='en'><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width'>"
        "<title>TrickRoom Blender Authoring Handbook</title><style>"
        + stylesheet
        + "</style>"
        + html_text
        + "</html>",
        encoding="utf-8",
    )
    doc = fitz.open(PDF)
    previews = BOOK / "review"
    previews.mkdir(exist_ok=True)
    empty, outside = [], []
    for page in doc:
        if len(page.get_text().strip()) < 70:
            empty.append(page.number + 1)
        for block in page.get_text("dict")["blocks"]:
            if block["type"] != 0:
                continue
            x0, y0, x1, y1 = block["bbox"]
            if x0 < 20 or x1 > page.rect.width - 20 or y0 < 8 or y1 > page.rect.height - 8:
                outside.append(page.number + 1)
    for number in sorted({0, 1, 3, 8, 15, page_count // 2, page_count - 1}):
        doc[number].get_pixmap(matrix=fitz.Matrix(1.3, 1.3)).save(
            previews / f"page-{number + 1:03}.png"
        )
    if empty or outside:
        raise ValueError(f"PDF content/overflow check failed: empty={empty}, bounds={outside}")
    words = len(re.findall(r"\b[\w'-]+\b", text))
    manifest = {
        "pages": page_count,
        "words": words,
        "chapter_pages": document.chapter_pages,
        "blank_pages": empty,
        "text_outside_bounds": outside,
        "pdf_sha256": hashlib.sha256(PDF.read_bytes()).hexdigest(),
        "html_sha256": hashlib.sha256((BOOK / "index.html").read_bytes()).hexdigest(),
        "manuscript_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "source_citations_resolved": len(re.findall(r"\{\{source:", raw)),
        "format": "A5, original implementation-specific reference handbook",
    }
    (BOOK / "edition-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    build()
