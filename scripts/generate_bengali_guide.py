"""Automated Generator for Real-Time Fraud Detection Bengali Guide (.docx & .md).

Features:
- Pure Python standard library implementation (no third-party dependencies required).
- Generates standard Office OpenXML (.docx) document compatible with Word, LibreOffice, and Google Docs.
- Generates matching comprehensive Markdown (.md) guide for instant IDE preview.
- Modular architecture allowing incremental updates as stages 8, 9, 10... are executed.
"""

from datetime import UTC, datetime
import html
from pathlib import Path
import zipfile


class DocxBuilder:
    """Zero-dependency ECMA-376 OpenXML (.docx) builder."""

    def __init__(self, title: str):
        self.title = title
        self.body_elements: list[str] = []

    def _escape(self, text: str) -> str:
        return html.escape(str(text), quote=True)

    def add_title(self, main_title: str, subtitle: str, metadata: list[str]) -> None:
        """Add formal document title block."""
        t_esc = self._escape(main_title)
        sub_esc = self._escape(subtitle)

        self.body_elements.append(f"""
        <w:p>
            <w:pPr>
                <w:spacing w:before="400" w:after="160"/>
                <w:jc w:val="center"/>
            </w:pPr>
            <w:r>
                <w:rPr>
                    <w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Nirmala UI"/>
                    <w:b/>
                    <w:color w:val="0B3C5D"/>
                    <w:sz w:val="48"/>
                    <w:szCs w:val="48"/>
                </w:rPr>
                <w:t>{t_esc}</w:t>
            </w:r>
        </w:p>
        <w:p>
            <w:pPr>
                <w:spacing w:before="100" w:after="240"/>
                <w:jc w:val="center"/>
            </w:pPr>
            <w:r>
                <w:rPr>
                    <w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Nirmala UI"/>
                    <w:i/>
                    <w:color w:val="5B6770"/>
                    <w:sz w:val="26"/>
                    <w:szCs w:val="26"/>
                </w:rPr>
                <w:t>{sub_esc}</w:t>
            </w:r>
        </w:p>
        """)

        for meta in metadata:
            m_esc = self._escape(meta)
            self.body_elements.append(f"""
            <w:p>
                <w:pPr>
                    <w:spacing w:before="40" w:after="40"/>
                    <w:jc w:val="center"/>
                </w:pPr>
                <w:r>
                    <w:rPr>
                        <w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Nirmala UI"/>
                        <w:color w:val="708090"/>
                        <w:sz w:val="20"/>
                        <w:szCs w:val="20"/>
                    </w:rPr>
                    <w:t>{m_esc}</w:t>
                </w:r>
            </w:p>
            """)

        # Add horizontal separator
        self.body_elements.append("""
        <w:p>
            <w:pPr>
                <w:pBdr>
                    <w:bottom w:val="single" w:sz="12" w:space="8" w:color="0B3C5D"/>
                </w:pBdr>
                <w:spacing w:before="160" w:after="300"/>
            </w:pPr>
        </w:p>
        """)

    def add_h1(self, text: str) -> None:
        """Add Heading 1 (Section Title)."""
        t_esc = self._escape(text)
        self.body_elements.append(f"""
        <w:p>
            <w:pPr>
                <w:spacing w:before="400" w:after="160"/>
                <w:pBdr>
                    <w:left w:val="single" w:sz="24" w:space="12" w:color="0B3C5D"/>
                </w:pBdr>
            </w:pPr>
            <w:r>
                <w:rPr>
                    <w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Nirmala UI"/>
                    <w:b/>
                    <w:color w:val="0B3C5D"/>
                    <w:sz w:val="34"/>
                    <w:szCs w:val="34"/>
                </w:rPr>
                <w:t xml:space="preserve">  {t_esc}</w:t>
            </w:r>
        </w:p>
        """)

    def add_h2(self, text: str) -> None:
        """Add Heading 2 (Subsection)."""
        t_esc = self._escape(text)
        self.body_elements.append(f"""
        <w:p>
            <w:pPr>
                <w:spacing w:before="280" w:after="120"/>
            </w:pPr>
            <w:r>
                <w:rPr>
                    <w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Nirmala UI"/>
                    <w:b/>
                    <w:color w:val="1D5C8C"/>
                    <w:sz w:val="28"/>
                    <w:szCs w:val="28"/>
                </w:rPr>
                <w:t>{t_esc}</w:t>
            </w:r>
        </w:p>
        """)

    def add_h3(self, text: str) -> None:
        """Add Heading 3 (Topic)."""
        t_esc = self._escape(text)
        self.body_elements.append(f"""
        <w:p>
            <w:pPr>
                <w:spacing w:before="200" w:after="80"/>
            </w:pPr>
            <w:r>
                <w:rPr>
                    <w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Nirmala UI"/>
                    <w:b/>
                    <w:color w:val="2C3E50"/>
                    <w:sz w:val="24"/>
                    <w:szCs w:val="24"/>
                </w:rPr>
                <w:t>{t_esc}</w:t>
            </w:r>
        </w:p>
        """)

    def add_p(self, text: str, bold_prefix: str | None = None, italic: bool = False) -> None:
        """Add standard body paragraph with Bengali unicode font settings."""
        t_esc = self._escape(text)
        prefix_xml = ""
        if bold_prefix:
            b_esc = self._escape(bold_prefix)
            prefix_xml = f"""
            <w:r>
                <w:rPr>
                    <w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Nirmala UI"/>
                    <w:b/>
                    <w:color w:val="1F2937"/>
                    <w:sz w:val="22"/>
                    <w:szCs w:val="22"/>
                </w:rPr>
                <w:t xml:space="preserve">{b_esc} </w:t>
            </w:r>
            """

        it_tag = "<w:i/>" if italic else ""
        self.body_elements.append(f"""
        <w:p>
            <w:pPr>
                <w:spacing w:before="60" w:after="100" w:line="280" w:lineRule="auto"/>
            </w:pPr>
            {prefix_xml}
            <w:r>
                <w:rPr>
                    <w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Nirmala UI"/>
                    {it_tag}
                    <w:color w:val="2D3748"/>
                    <w:sz w:val="22"/>
                    <w:szCs w:val="22"/>
                </w:rPr>
                <w:t xml:space="preserve">{t_esc}</w:t>
            </w:r>
        </w:p>
        """)

    def add_bullet(self, text: str, bold_prefix: str | None = None, level: int = 0) -> None:
        """Add a clean bullet item."""
        t_esc = self._escape(text)
        left_indent = 360 + (level * 360)

        prefix_xml = ""
        if bold_prefix:
            b_esc = self._escape(bold_prefix)
            prefix_xml = f"""
            <w:r>
                <w:rPr>
                    <w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Nirmala UI"/>
                    <w:b/>
                    <w:color w:val="1A202C"/>
                    <w:sz w:val="22"/>
                    <w:szCs w:val="22"/>
                </w:rPr>
                <w:t xml:space="preserve">{b_esc} </w:t>
            </w:r>
            """

        bullet_symbol = "▪" if level == 0 else "▫"

        self.body_elements.append(f"""
        <w:p>
            <w:pPr>
                <w:ind w:left="{left_indent}" w:hanging="240"/>
                <w:spacing w:before="40" w:after="60"/>
            </w:pPr>
            <w:r>
                <w:rPr>
                    <w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Nirmala UI"/>
                    <w:color w:val="0B3C5D"/>
                    <w:sz w:val="20"/>
                </w:rPr>
                <w:t xml:space="preserve">{bullet_symbol} </w:t>
            </w:r>
            {prefix_xml}
            <w:r>
                <w:rPr>
                    <w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Nirmala UI"/>
                    <w:color w:val="2D3748"/>
                    <w:sz w:val="22"/>
                    <w:szCs w:val="22"/>
                </w:rPr>
                <w:t xml:space="preserve">{t_esc}</w:t>
            </w:r>
        </w:p>
        """)

    def add_callout(self, title: str, text: str, kind: str = "info") -> None:
        """Add an eye-catching callout container (Note, Tip, Warning)."""
        color_map = {
            "info": ("0B3C5D", "F0F4F8"),
            "tip": ("107C41", "F1F9F4"),
            "warning": ("C15C00", "FDF6EE"),
            "alert": ("A80000", "FDF2F2"),
        }
        bdr_color, bg_color = color_map.get(kind, ("0B3C5D", "F0F4F8"))
        title_esc = self._escape(title)
        text_esc = self._escape(text)

        self.body_elements.append(f"""
        <w:p>
            <w:pPr>
                <w:pBdr>
                    <w:left w:val="single" w:sz="36" w:space="16" w:color="{bdr_color}"/>
                </w:pBdr>
                <w:shd w:val="clear" w:color="auto" w:fill="{bg_color}"/>
                <w:spacing w:before="140" w:after="40"/>
                <w:ind w:left="240" w:right="240"/>
            </w:pPr>
            <w:r>
                <w:rPr>
                    <w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Nirmala UI"/>
                    <w:b/>
                    <w:color w:val="{bdr_color}"/>
                    <w:sz w:val="22"/>
                    <w:szCs w:val="22"/>
                </w:rPr>
                <w:t>{title_esc}</w:t>
            </w:r>
        </w:p>
        <w:p>
            <w:pPr>
                <w:pBdr>
                    <w:left w:val="single" w:sz="36" w:space="16" w:color="{bdr_color}"/>
                </w:pBdr>
                <w:shd w:val="clear" w:color="auto" w:fill="{bg_color}"/>
                <w:spacing w:before="20" w:after="160"/>
                <w:ind w:left="240" w:right="240"/>
            </w:pPr>
            <w:r>
                <w:rPr>
                    <w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Nirmala UI"/>
                    <w:color w:val="2D3748"/>
                    <w:sz w:val="21"/>
                    <w:szCs w:val="21"/>
                </w:rPr>
                <w:t xml:space="preserve">{text_esc}</w:t>
            </w:r>
        </w:p>
        """)

    def add_code_block(self, code_text: str) -> None:
        """Add monospaced code or CLI command box."""
        lines = code_text.strip().split("\n")
        self.body_elements.append("""
        <w:p>
            <w:pPr>
                <w:spacing w:before="120" w:after="0"/>
            </w:pPr>
        </w:p>
        """)
        for line in lines:
            line_esc = self._escape(line)
            self.body_elements.append(f"""
            <w:p>
                <w:pPr>
                    <w:shd w:val="clear" w:color="auto" w:fill="F3F4F6"/>
                    <w:spacing w:before="10" w:after="10"/>
                    <w:ind w:left="240" w:right="240"/>
                </w:pPr>
                <w:r>
                    <w:rPr>
                        <w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" w:cs="Consolas"/>
                        <w:color w:val="1F2937"/>
                        <w:sz w:val="19"/>
                        <w:szCs w:val="19"/>
                    </w:rPr>
                    <w:t xml:space="preserve">{line_esc}</w:t>
                </w:r>
            </w:p>
            """)
        self.body_elements.append("""
        <w:p>
            <w:pPr>
                <w:spacing w:before="0" w:after="140"/>
            </w:pPr>
        </w:p>
        """)

    def add_table(self, headers: list[str], rows: list[list[str]]) -> None:
        """Add a professional styled table."""
        header_cells = ""
        for h in headers:
            h_esc = self._escape(h)
            header_cells += f"""
            <w:tc>
                <w:tcPr>
                    <w:shd w:val="clear" w:color="auto" w:fill="0B3C5D"/>
                    <w:tcMar>
                        <w:top w:w="120" w:type="dxa"/>
                        <w:bottom w:w="120" w:type="dxa"/>
                        <w:left w:w="160" w:type="dxa"/>
                        <w:right w:w="160" w:type="dxa"/>
                    </w:tcMar>
                </w:tcPr>
                <w:p>
                    <w:r>
                        <w:rPr>
                            <w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Nirmala UI"/>
                            <w:b/>
                            <w:color w:val="FFFFFF"/>
                            <w:sz w:val="21"/>
                            <w:szCs w:val="21"/>
                        </w:rPr>
                        <w:t>{h_esc}</w:t>
                    </w:r>
                </w:p>
            </w:tc>
            """

        rows_xml = f"""
        <w:tr>
            <w:trPr><w:tblHeader/></w:trPr>
            {header_cells}
        </w:tr>
        """

        for i, row in enumerate(rows):
            bg = "F9FAFB" if i % 2 == 1 else "FFFFFF"
            cells = ""
            for cell in row:
                c_esc = self._escape(cell)
                cells += f"""
                <w:tc>
                    <w:tcPr>
                        <w:shd w:val="clear" w:color="auto" w:fill="{bg}"/>
                        <w:tcMar>
                            <w:top w:w="100" w:type="dxa"/>
                            <w:bottom w:w="100" w:type="dxa"/>
                            <w:left w:w="160" w:type="dxa"/>
                            <w:right w:w="160" w:type="dxa"/>
                        </w:tcMar>
                    </w:tcPr>
                    <w:p>
                        <w:r>
                            <w:rPr>
                                <w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Nirmala UI"/>
                                <w:color w:val="2D3748"/>
                                <w:sz w:val="20"/>
                                <w:szCs w:val="20"/>
                            </w:rPr>
                            <w:t>{c_esc}</w:t>
                        </w:r>
                    </w:p>
                </w:tc>
                """
            rows_xml += f"<w:tr>{cells}</w:tr>"

        table_xml = f"""
        <w:tbl>
            <w:tblPr>
                <w:tblW w:w="0" w:type="auto"/>
                <w:tblBorders>
                    <w:top w:val="single" w:sz="6" w:space="0" w:color="D1D5DB"/>
                    <w:left w:val="none"/>
                    <w:bottom w:val="single" w:sz="8" w:space="0" w:color="0B3C5D"/>
                    <w:right w:val="none"/>
                    <w:insideH w:val="single" w:sz="4" w:space="0" w:color="E5E7EB"/>
                    <w:insideV w:val="none"/>
                </w:tblBorders>
                <w:tblCellMar>
                    <w:top w:w="80" w:type="dxa"/>
                    <w:bottom w:w="80" w:type="dxa"/>
                    <w:left w:w="120" w:type="dxa"/>
                    <w:right w:w="120" w:type="dxa"/>
                </w:tblCellMar>
            </w:tblPr>
            {rows_xml}
        </w:tbl>
        <w:p><w:pPr><w:spacing w:after="160"/></w:pPr></w:p>
        """
        self.body_elements.append(table_xml)

    def add_page_break(self) -> None:
        """Insert page break."""
        self.body_elements.append("""
        <w:p>
            <w:r><w:br w:type="page"/></w:r>
        </w:p>
        """)

    def save(self, filepath: Path | str) -> None:
        """Package all XML components into an ECMA-376 .docx file."""
        content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>"""

        rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

        doc_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

        styles = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:docDefaults>
    <w:rPrDefault>
      <w:rPr>
        <w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Nirmala UI"/>
        <w:sz w:val="22"/>
        <w:szCs w:val="22"/>
        <w:lang w:val="en-US" w:bidi="bn-BD"/>
      </w:rPr>
    </w:rPrDefault>
  </w:docDefaults>
</w:styles>"""

        body_inner = "".join(self.body_elements)
        document_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    {body_inner}
    <w:sectPr>
      <w:pgSz w:w="12240" w:h="15840"/>
      <w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/>
    </w:sectPr>
  </w:body>
</w:document>"""

        out_path = Path(filepath)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", content_types)
            z.writestr("_rels/.rels", rels)
            z.writestr("word/_rels/document.xml.rels", doc_rels)
            z.writestr("word/styles.xml", styles)
            z.writestr("word/document.xml", document_xml)


def build_full_guide(docx_path: str, md_path: str) -> None:
    """Build comprehensive Bengali guide up to Stage 7."""
    doc = DocxBuilder("Real-Time Fraud Detection System Handbook")
    md_lines: list[str] = []

    def md_h1(text: str) -> None:
        md_lines.append(f"\n# {text}\n")
        doc.add_h1(text)

    def md_h2(text: str) -> None:
        md_lines.append(f"\n## {text}\n")
        doc.add_h2(text)

    def md_h3(text: str) -> None:
        md_lines.append(f"\n### {text}\n")
        doc.add_h3(text)

    def md_p(text: str, bold_prefix: str | None = None) -> None:
        if bold_prefix:
            md_lines.append(f"\n**{bold_prefix}** {text}\n")
        else:
            md_lines.append(f"\n{text}\n")
        doc.add_p(text, bold_prefix=bold_prefix)

    def md_bullet(text: str, bold_prefix: str | None = None, level: int = 0) -> None:
        indent = "  " * level
        if bold_prefix:
            md_lines.append(f"{indent}- **{bold_prefix}** {text}")
        else:
            md_lines.append(f"{indent}- {text}")
        doc.add_bullet(text, bold_prefix=bold_prefix, level=level)

    def md_callout(title: str, text: str, kind: str = "info") -> None:
        alert_tag = "NOTE" if kind == "info" else ("TIP" if kind == "tip" else "WARNING")
        md_lines.append(f"\n> [!{alert_tag}]\n> **{title}**\n> {text}\n")
        doc.add_callout(title, text, kind=kind)

    def md_code(code_text: str) -> None:
        md_lines.append(f"\n```bash\n{code_text}\n```\n")
        doc.add_code_block(code_text)

    def md_table(headers: list[str], rows: list[list[str]]) -> None:
        sep = "| " + " | ".join(["---"] * len(headers)) + " |"
        header_str = "| " + " | ".join(headers) + " |"
        md_lines.append(f"\n{header_str}\n{sep}")
        for r in rows:
            md_lines.append("| " + " | ".join(r) + " |")
        md_lines.append("")
        doc.add_table(headers, rows)

    # ----------------------------------------------------
    # Title & Metadata
    # ----------------------------------------------------
    doc.add_title(
        main_title="রিয়েল-টাইম ফ্রড ডিটেকশন সিস্টেম (Real-Time Fraud Detection)",
        subtitle="বিগিনারদের জন্য সহজ বাংলায় হাতে-কলমে প্রজেক্ট গাইডবুক (স্টেজ ১ থেকে স্টেজ ৭)",
        metadata=[
            "সংস্করণ: ১.০ (স্টেজ ১ - স্টেজ ৭ সম্পূর্ণ কভারেজ)",
            f"আপডেট তারিখ: {datetime.now(UTC).strftime('%Y-%m-%d')} | টেক স্ট্যাক: Python, Kafka, Redis 7, LightGBM, PostgreSQL 16",
            "লক্ষ্য: ফিনটেক ও ব্যাংকিং গ্রেড আর্কিটেকচার সহজে আত্মস্থ করা",
        ],
    )
    md_lines.append("# রিয়েল-টাইম ফ্রড ডিটেকশন সিস্টেম (Real-Time Fraud Detection)")
    md_lines.append("### বিগিনারদের জন্য সহজ বাংলায় হাতে-কলমে প্রজেক্ট গাইডবুক (স্টেজ ১ থেকে স্টেজ ৭)\n")

    # ----------------------------------------------------
    # অধ্যায় ১: সিস্টেম পরিচিতি
    # ----------------------------------------------------
    md_h1("অধ্যায় ১: রিয়েল-টাইম ফ্রড ডিটেকশন সিস্টেম আসলে কী?")

    md_p(
        "মনে করুন আপনি প্রতিদিন বিকাশ, নগদ বা ব্যাংকের এটিএম কার্ড দিয়ে লেনদেন করেন। আপনার কার্ডটি যদি হঠাৎ কোনো হ্যাকার ক্লোন করে রাত ৩টায় নাইজেরিয়া থেকে ৫ লাখ টাকা তোলার চেষ্টা করে, তখন ব্যাংক কী করবে? "
        "যদি ব্যাংক পরদিন সকালে ফাইল চেক করে দেখে, ততক্ষণে আপনার টাকা গায়েব! এই কারণেই দরকার 'রিয়েল-টাইম ফ্রড ডিটেকশন সিস্টেম' (Real-Time Fraud Detection System)।",
        bold_prefix="বাস্তব জীবনের একটি গল্প:",
    )

    md_p(
        "গ্রাহক যখনই 'Pay' বা 'Withdraw' বাটনে চাপ দেন, ট্রানজ্যাকশনটি ব্যাংকের মূল কোর অ্যাকাউন্টে পৌঁছানোর আগেই মাত্র কয়েক মিলি-সেকেন্ডের (মিলি-সেকেন্ড = সেকেন্ডের ১০০০ ভাগের এক ভাগ!) মধ্যে আমাদের সিস্টেম স্ক্যান করে ফেলে। "
        "স্ক্যান করে সিস্টেমটি ৩টি সিদ্ধান্তের যেকোনো একটি জানায়:",
        bold_prefix="সিস্টেমের মূল লক্ষ্য:",
    )

    md_bullet("লেনদেন পুরোপুরি নিরাপদ। টাকা সাথে সাথে চলে যাবে।", bold_prefix="১. APPROVED (অনুমোদিত):")
    md_bullet(
        "লেনদেনটি কিছুটা সন্দেহজনক। টাকা আটকে ওটিপি (OTP) বা ম্যানুয়াল ভেরিফিকেশনে পাঠানো হবে।",
        bold_prefix="২. FLAGGED (সতর্কবার্তা):",
    )
    md_bullet(
        "নিশ্চিত প্রতারণা বা আন্তর্জাতিক স্যাংশন ভায়োলেশন। লেনদেনটি সাথে সাথে বাতিল!",
        bold_prefix="৩. REJECTED (বাতিল):",
    )

    md_h2("পুরো পাইপলাইনের আর্কিটেকচার (ডেটা কীভাবে এক ধাপ থেকে আরেক ধাপে যায়?)")
    md_p(
        "নিচের তালিকাটি লক্ষ্য করুন। একটি ট্রানজ্যাকশন কীভাবে বিভিন্ন স্তরের মধ্য দিয়ে গিয়ে ৫ মিলি-সেকেন্ডের মধ্যে নির্ধারিত হয়:"
    )

    flow_table = [
        ["ধাপ (Stage)", "কম্পোনেন্ট", "কী কাজ করে?", "কত সময় লাগে?"],
        [
            "১. ইভেন্ট স্ট্রিমিং",
            "Apache Kafka",
            "প্রতি সেকেন্ডে হাজার হাজার ট্রানজ্যাকশন গ্রহণ করে কনজিউমারে পাঠায়",
            "< ১ ms",
        ],
        [
            "২. গতি পরিমাপ",
            "Redis 7 Feature Store",
            "গ্রাহক গত ৫ মিনিট, ১ ঘণ্টা ও ২৪ ঘণ্টায় কতবার লেনদেন করেছেন তা বের করে",
            "< ০.৮ ms",
        ],
        [
            "৩. নীতিমালা যাচাই",
            "Deterministic Rule Engine",
            "অসম্ভব দূরত্বে ভ্রমণ, কালোতালিকা ও রাতের অস্বাভাবিক লেনদেন যাচাই করে",
            "< ০.২ ms",
        ],
        [
            "৪. এআই স্ক্যানিং",
            "Hybrid ML (LightGBM + IsoForest)",
            "অতীতের চেনা জালিয়াতি ও অচেনা নতুন প্যাটার্ন প্রিডিক্ট করে রিস্ক স্কোর দেয়",
            "< ২.৫ ms",
        ],
        [
            "৫. ফলাফল অডিট",
            "PostgreSQL 16 (Micro-Batch)",
            "চূড়ান্ত সিদ্ধান্ত, ফিচার হিস্ট্রি ও টাকার সঠিক হিসাব ডিস্কে স্থায়ী করে",
            "ব্যাকগ্রাউন্ডে",
        ],
    ]
    md_table(flow_table[0], flow_table[1:])

    md_callout(
        "বিগিনারদের জন্য সোনালী নিয়ম:",
        "রিয়েল-টাইম সিস্টেমে প্রতি মিলি-সেকেন্ডের মূল্য কোটি টাকা! তাই এখানে কোনো ভারী ডিস্ক কুয়েরি করা যাবে না। সবকিছু র‍্যামের মধ্যে লাইটনিং স্পিডে ঘটাতে হবে।",
        kind="tip",
    )

    # ----------------------------------------------------
    # অধ্যায় ২: স্টেজ ১
    # ----------------------------------------------------
    md_h1("অধ্যায় ২: স্টেজ ১ — প্রজেক্ট আর্কিটেকচার ও ফাউন্ডেশন সেটআপ")

    md_p(
        "অনেকে মনে করেন কোডিং মানেই শুধু ফাইল খুলে কোড লেখা। কিন্তু ব্যাংকিং বা ফিনটেক ইন্ডাস্ট্রিতে আর্কিটেকচার ঠিক না থাকলে প্রজেক্ট কিছুদিন পর মেইনটেইন করা অসম্ভব হয়ে পড়ে। "
        "স্টেজ ১-এ আমরা পুরো প্রজেক্টের আধুনিক ভিত্তিপ্রস্তর স্থাপন করেছি।",
        bold_prefix="সহজ ব্যাখ্যা:",
    )

    md_h2("১. ডিরেক্টরি স্ট্রাকচার (কোড কোথায় থাকে?)")
    md_bullet(
        "সিস্টেমের সমস্ত আসল প্রোডাকশন কোড এখানে থাকে। এটি একটি ইনস্টলেবল প্যাকেজ হিসেবে কাজ করে।",
        bold_prefix="src/fraud_detection/:",
    )
    md_bullet(
        "সিস্টেমের কনফিগারেশন, লগিং ও গ্লোবাল কনস্ট্যান্টস।", bold_prefix="src/fraud_detection/core/:"
    )
    md_bullet(
        "Pydantic V2 ডেটা ভ্যালিডেশন মডেল (যাতে ভুল ফরম্যাটের কোনো ডেটা ঢুকতে না পারে)।",
        bold_prefix="src/fraud_detection/schemas/:",
    )
    md_bullet(
        "মেশিন লার্নিং প্রিপ্রসেসিং, ফিচার স্কেলিং ও মডেল ইনফারেন্স লজিক।",
        bold_prefix="src/fraud_detection/ml/:",
    )
    md_bullet(
        "কাফকা প্রডিউসার, কনজিউমার এবং সিন্থেটিক অ্যানোমালি তৈরি।",
        bold_prefix="src/fraud_detection/streaming/:",
    )
    md_bullet(
        "রেডিস ফিচার স্টোর এবং পোস্টগ্রেস অডিট রিপোজিটরি।", bold_prefix="src/fraud_detection/storage/:"
    )
    md_bullet("সমস্ত স্বয়ংক্রিয় টেস্ট স্ক্রিপ্ট (Pytest)।", bold_prefix="tests/:")

    md_h2("২. কনফিগারেশন ও পরিবেশ নিরাপত্তা (`config.py`)")
    md_p(
        "কখনোই কোডের ভেতরে ডাটাবেস পাসওয়ার্ড বা সিক্রেট কি সরাসরি হার্ডকোড করে লেখা যাবে না। "
        "`Pydantic Settings` ব্যবহার করে আমরা `.env` ফাইল থেকে স্বয়ংক্রিয়ভাবে সেটিংস রিড করি। যেমন ডাটাবেসের ইউজারনেম, কাফকা পোর্ট, রেডিস হোস্ট ইত্যাদি।"
    )

    md_h2("৩. কোড কোয়ালিটি ও সেফটি গার্ডরেইল (Ruff & Pre-commit)")
    md_p(
        "প্রজেক্টে যাতে কোনো আনইউজড ভ্যারিয়েবল, সিনট্যাক্স ভুল বা অনিরাপদ কোড কমিট না হয়, সেজন্য `pre-commit` ও `ruff` কনফিগার করা হয়েছে। "
        "আপনি `git commit` করার সাথে সাথে এই গার্ডরেইলগুলো অটোমেটিক্যালি কোড স্ক্যান করে সব ভুল শুধরে দেয়।"
    )

    # ----------------------------------------------------
    # অধ্যায় ৩: স্টেজ ২
    # ----------------------------------------------------
    md_h1("অধ্যায় ৩: স্টেজ ২ — পোস্টগ্রেস ডেটাবেস ও রিলেশনাল স্কিমা")

    md_p(
        "একটি লেনদেন যখন সম্পন্ন হয়, তখন ভবিষ্যতে অডিট, বাংলাদেশ ব্যাংক বা আন্তর্জাতিক তদন্তের জন্য প্রতিটি তথ্যের নির্ভুল প্রমাণ সংরক্ষণ করতে হয়। "
        "স্টেজ ২-এ আমরা PostgreSQL 16 এর শক্তিশালী রিলেশনাল স্কিমা তৈরি করেছি।",
        bold_prefix="কেন ডাটাবেস দরকার?",
    )

    md_h2("১. কেন `FLOAT` নিষিদ্ধ এবং `NUMERIC(12, 2)` বাধ্যতামূলক?")
    md_p(
        "কম্পিউটার সায়েন্সে ফ্লোটিং পয়েন্ট (Float/Double) সংখ্যা হিসাব করার সময় বাইনারি রাউন্ডিং এরর তৈরি করে। যেমন: 0.1 + 0.2 হিসাব করলে পাইথনে উত্তর আসে 0.30000000000000004! "
        "যদি ব্যাংকের কোটি কোটি লেনদেনে এই ভগ্নাংশের গরমিল হয়, তবে ব্যালেন্স শিট মিলবে না। এজন্য আমাদের সমস্ত ট্রানজ্যাকশন টেবিলে `NUMERIC(12, 2)` ব্যবহার করা হয়েছে, যা পয়সা পর্যন্ত ১০০% নিখুঁত হিসাব রাখে।"
    )

    md_h2("২. ইমিউটেবল অডিট লগ (Immutable Audit Log)")
    md_callout(
        "ব্যাংকিং রুল:",
        "কোনো ট্রানজ্যাকশন ডাটাবেসে একবার ঢুকলে তা কখনোই আপডেট (UPDATE) বা মুছে (DELETE) ফেলা যাবে না! ভুল হলে নতুন অ্যাডজাস্টমেন্ট ট্রানজ্যাকশন করতে হবে, কিন্তু হিস্ট্রি চিরকাল অপরিবর্তিত থাকবে।",
        kind="warning",
    )

    md_h2("৩. ডাটাবেসের ৪টি মূল টেবিল:")
    md_bullet("গ্রাহকের ইউনিক আইডি, ইমেইল, নাম ও স্ট্যাটাস।", bold_prefix="users:")
    md_bullet("গ্রাহকের ব্যাংক অ্যাকাউন্ট নম্বর ও কারেন্সি।", bold_prefix="accounts:")
    md_bullet(
        "প্রতিটি লেনদেনের আইডি, সময়, টাকার পরিমাণ, লোকেশন, আইপি অ্যাড্রেস এবং ফ্রড রিস্ক স্কোর।",
        bold_prefix="transactions:",
    )
    md_bullet("কমপ্লায়েন্স নীতিমালার কোড, নাম ও বিবরণ।", bold_prefix="rules:")

    md_h2("৪. `JSONB` এর ক্ষমতা:")
    md_p(
        "মেশিন লার্নিং মডেল যখন লেনদেনটি যাচাই করেছিল, তখন কী কী ফিচার ছিল এবং কোন কোন রুল ভঙ্গ হয়েছিল, তা ফ্লেক্সিবল `JSONB` কলামে রাখা হয়। "
        "এর ফলে আলাদা জটিল টেবিল জয়েন ছাড়াই মুহূর্তের মধ্যে পুরো হিস্ট্রি বের করে ফেলা যায়।"
    )

    # ----------------------------------------------------
    # অধ্যায় ৪: স্টেজ ৩
    # ----------------------------------------------------
    md_h1("অধ্যায় ৪: স্টেজ ৩ — ডিটারমিনিস্টিক রুল ইঞ্জিন ও পলিসি")

    md_p(
        "মেশিন লার্নিং বা এআই অত্যন্ত বুদ্ধিমান হলেও মাঝে মাঝে জটিল বা অচেনা প্যাটার্নে ভুল অনুমান (False Positive) করতে পারে। কিন্তু কিছু অপরাধ এতই স্পষ্ট যে সেখানে এআই ভাবারই দরকার নেই, সরাসরি নিয়ম দিয়েই আটকে দেওয়া যায়! "
        "এজন্য এআই-এর আগেই চলে আমাদের 'রুল ইঞ্জিন' (Deterministic Rule Engine)।",
        bold_prefix="রুল ইঞ্জিনের দর্শন:",
    )

    md_h2("আমাদের ৪টি মারাত্মক ফ্রড ডিটেকশন রুল:")

    rules_table = [
        ["রুল কোড", "রুলের নাম", "সহজ ব্যাখ্যা ও শর্ত", "পদক্ষেপ (Action)"],
        [
            "RULE_IMPOSSIBLE_TRAVEL",
            "অসম্ভব ভ্রমণ",
            "একজন ব্যক্তি ঢাকায় কেনাকাটা করার ১৫ মিনিটের মধ্যে যদি লন্ডন বা নিউইয়র্কে কার্ড সোয়াইপ করেন (গতিবেগ > ১০০০ কিমি/ঘণ্টা), তবে এটি স্পষ্টত কার্ড ক্লোনিং!",
            "সরাসরি REJECTED (বাতিল)",
        ],
        [
            "RULE_VELOCITY_BURST",
            "ঘন ঘন লেনদেনের ঝড়",
            "স্বাভাবিক মানুষ ১ মিনিটে ১০ বার টাকা পাঠায় না। ১ মিনিটের মধ্যে যদি ৫টির বেশি লেনদেন হয়, তবে এটি হ্যাকার বা বট অ্যাটাক।",
            "+০.৩০ রিস্ক পেনাল্টি / FLAGGED",
        ],
        [
            "RULE_SANCTIONED_DEST",
            "নিষিদ্ধ দেশ / ব্ল্যাকলিস্ট",
            "আন্তর্জাতিক অর্থনৈতিক নিষেধাজ্ঞা প্রাপ্ত কোনো দেশ বা সন্দেহভাজন অ্যাকাউন্ট থেকে লেনদেনের চেষ্টা।",
            "সরাসরি REJECTED (বাতিল)",
        ],
        [
            "RULE_NOCTURNAL_ATO",
            "রাতের আঁধারে অ্যাকাউন্ট দখল",
            "রাত ২টা থেকে ভোর ৫টার মধ্যে যদি হঠাৎ সম্পূর্ণ নতুন ডিভাইস থেকে গ্রাহকের স্বাভাবিকের চেয়ে দ্বিগুণ টাকা তোলার চেষ্টা হয়।",
            "+০.৪০ রিস্ক পেনাল্টি / FLAGGED",
        ],
    ]
    md_table(rules_table[0], rules_table[1:])

    md_h2("হাভারসিন দূরত্ব সূত্র (Haversine Distance Formula)")
    md_p(
        "Impossible Travel ধরার জন্য আমরা পৃথিবী পৃষ্ঠের বক্রতা বিবেচনা করে দুটি জিপিএস স্থানাঙ্কের (Latitude, Longitude) মধ্যে নিখুঁত দূরত্ব ও গতিবেগ বের করি:"
    )
    md_code("Speed (km/h) = Haversine_Distance(Lat1, Lon1, Lat2, Lon2) / Time_Difference_in_Hours")

    # ----------------------------------------------------
    # অধ্যায় ৫: স্টেজ ৪
    # ----------------------------------------------------
    md_h1("অধ্যায় ৫: স্টেজ ৪ — কাফকা ইভেন্ট স্ট্রিমিং ও সিন্থেটিক ডেটা প্রডিউসার")

    md_p(
        "বাস্তব ব্যাংকে প্রতি সেকেন্ডে হাজার হাজার মানুষ এটিএম বুথ, পিওএস মেশিন ও অ্যাপে ট্রানজ্যাকশন করছেন। সাধারণ ওয়েব সার্ভার (যেমন সাধারণ রেস্ট এপিআই) এত ট্রাফিক একসাথে সামলাতে গিয়ে ক্র্যাশ করতে পারে। "
        "এজন্য ব্যবহার করা হয় Apache Kafka — বিশ্বের সবচেয়ে শক্তিশালী ডিস্ট্রিবিউটেড ইভেন্ট স্ট্রিমিং প্ল্যাটফর্ম।",
        bold_prefix="কাফকা কেন দরকার?",
    )

    md_h2("কাফকাকে কীভাবে চিন্তা করবেন? (সহজ উপমা)")
    md_p(
        "কাফকা হলো একটি বিশাল পোস্ট অফিস বা কনভেয়ার বেল্টের মতো। এটিএম বা মোবাইল অ্যাপ হলো 'প্রডিউসার' (Producer), যারা চিঠির মতো লেনদেনের বার্তা কাফকার 'transactions' টপিকে ফেলে দেয়। "
        "আমাদের ফ্রড ডিটেকশন ইঞ্জিন হলো 'কনজিউমার' (Consumer), যে কনভেয়ার বেল্ট থেকে দ্রুত চিঠিগুলো তুলে পরীক্ষা করে।"
    )

    md_h2("সিন্থেটিক ডেটা প্রডিউসার (`TransactionProducer`)")
    md_p(
        "বাস্তব ব্যাংকের আসল গ্রাহকদের ডেটা অত্যন্ত গোপনীয়। তাই আমরা একটি উচ্চক্ষমতাসম্পন্ন সিন্থেটিক প্রডিউসার তৈরি করেছি, যা বাস্তব কার্ড নম্বর, মার্চেন্ট (Amazon, Uber, Walmart, ইত্যাদি), ইউজার ও ডিভাইস আইডি সহ প্রতি সেকেন্ডে ৫০ থেকে ৫০০টি ইভেন্ট তৈরি করে কাফকাতে পাঠাতে পারে।"
    )

    md_h2("অ্যানোমালি ইনজেকশন (`AnomalyGenerator`)")
    md_p(
        "যদি সব ডেটাই স্বাভাবিক হয়, তবে সিস্টেম টেস্ট করবেন কীভাবে? "
        "আমাদের প্রডিউসার বুদ্ধি খাটিয়ে মোট ট্রানজ্যাকশনের মধ্যে ২% থেকে ১০% ইচ্ছাকৃত ফ্রড বা অ্যানোমালি (যেমন অসম্ভব ভ্রমণ, রাতের অস্বাভাবিক লেনদেন) মিশিয়ে দেয়, যাতে কনজিউমার ও এআই মডেল এগুলো ধরে ফেলে।"
    )

    # ----------------------------------------------------
    # অধ্যায় ৬: স্টেজ ৫
    # ----------------------------------------------------
    md_h1("অধ্যায় ৬: স্টেজ ৫ — রেডিস ফিচার স্টোর ও ভেলোসিটি মিটার")

    md_p(
        "ফ্রড ডিটেকশনে সবচেয়ে গুরুত্বপূর্ণ প্রশ্ন হলো: 'এই গ্রাহক গত ৫ মিনিটে কয়টি লেনদেন করেছেন?' "
        "যদি আমরা প্রতি ট্রানজ্যাকশনের জন্য পোস্টগ্রেসের মতো ডিস্ক ডাটাবেসে `SELECT COUNT(*) FROM transactions WHERE user_id=...` চালাই, তবে ডিস্ক রিড করতে করতেই ২০-৫০ মিলি-সেকেন্ড পার হয়ে যাবে! "
        "গ্রাহক তখন পেমেন্ট গেটওয়েতে আটকে বিরক্ত হবেন। এই সমস্যার ১০০% সমাধান হলো Redis 7।",
        bold_prefix="১ মিলি-সেকেন্ডের চ্যালেঞ্জ:",
    )

    md_h2("রেডিস (Redis 7) এর জাদু ও সর্টেড সেট (`ZSET`)")
    md_p(
        "রেডিস কোনো ডিস্কে চলে না, এটি সরাসরি কম্পিউটারের র‍্যামে (RAM) ডেটা রাখে। আমরা রেডিসের 'Sorted Set' ডেটা স্ট্রাকচার ব্যবহার করি। "
        "এখানে ট্রানজ্যাকশনের ইউনিক্স টাইমস্ট্যাম্পকে স্কোর (Score) হিসেবে রাখা হয়।"
    )
    md_bullet("নতুন লেনদেনের সময় ও আইডি মেমরিতে অ্যাড হয় মাত্র ০.৩ মিলি-সেকেন্ডে।", bold_prefix="ZADD:")
    md_bullet(
        "বর্তমান সময় থেকে গত ৫ মিনিট বা ১ ঘণ্টার পরিসীমার সব লেনদেন নিমেষে গুনে ফেলা হয়।",
        bold_prefix="ZRANGEBYSCORE:",
    )
    md_bullet(
        "৩০ মিনিটের বেশি পুরনো ডেটা স্বয়ংক্রিয়ভাবে ডিলিট হয়ে যায়, ফলে সার্ভারের র‍্যাম কখনো জ্যাম হয় না।",
        bold_prefix="ZREMRANGEBYSCORE & TTL:",
    )

    md_callout(
        "বেঞ্চমার্ক রেজাল্ট:",
        "আমাদের মাল্টি-থ্রেডেড রেডিস ফিচার স্টোর বেঞ্চমার্কে প্রতি সেকেন্ডে ২০,০০০+ ভেলোসিটি আপডেট সম্পন্ন হয়েছে এবং গড় ল্যাটেন্সি ছিল মাত্র ০.৭০ মিলি-সেকেন্ড!",
        kind="tip",
    )

    # ----------------------------------------------------
    # অধ্যায় ৭: স্টেজ ৬
    # ----------------------------------------------------
    md_h1("অধ্যায় ৭: স্টেজ ৬ — হাইব্রিড মেশিন লার্নিং ইনফারেন্স ও কাফকা কনজিউমার")

    md_p(
        "রুল ইঞ্জিনের পর আসে আমাদের সিস্টেমের সবচেয়ে বুদ্ধিমান মস্তিষ্ক — হাইব্রিড মেশিন লার্নিং আর্কিটেকচার। "
        "এখানে দুটি সম্পূর্ণ ভিন্ন ধরণের এআই মডেল একসাথে হাত মিলিয়ে কাজ করে:",
        bold_prefix="হাইব্রিড এআই কেন?",
    )

    md_h2("১. LightGBM (Supervised Model)")
    md_p(
        "এটি অতীতের হাজার হাজার চিহ্নিত ফ্রড কেস মুখস্থ করে প্রশিক্ষণ নিয়েছে। এটি টাকার পরিমাণ, সময়ের ব্যবধান, মার্চেন্ট ক্যাটাগরি ও ভেলোসিটি ফিচারের ভিত্তিতে প্রবাবিলিটি (Probability 0.0 - 1.0) বের করে।"
    )

    md_h2("২. Fast Isolation Forest (Unsupervised Anomaly Detector)")
    md_p(
        "হ্যাকাররা প্রতিদিন নতুন নতুন কৌশলে চুরি করার চেষ্টা করে যা অতীতে কেউ কখনো দেখেনি। Isolation Forest কোনো লেবেল ছাড়াই ডেটার অস্বাভাবিক বিচ্যুতি (Outlier) খুঁজে বের করে। "
        "আমরা সাইকিট-লার্নের ধীরগতির ফাংশন পরিহার করে সরাসরি সি-লেভেলের প্রি-কম্পিউটেড ট্রি ট্রাভার্সাল করেছি, যা মাত্র ০.১ মিলি-সেকেন্ডে আইসোলেশন ডেপথ বের করে ফেলে!"
    )

    md_h2("৩. কম্পোজিট রিস্ক স্কোরিং ফর্মুলা")
    md_code(
        "Composite_Risk = (0.65 * LightGBM_Score) + (0.35 * Isolation_Forest_Score) + Rule_Penalty"
    )
    md_p(
        "যদি কম্পোজিট রিস্ক ০.৮০ এর বেশি হয় -> REJECTED | ০.৫০ থেকে ০.৮০ এর মধ্যে হলে -> FLAGGED | ০.৫০ এর নিচে থাকলে -> APPROVED।"
    )

    md_h2("৪. কাফকা কনজিউমার ওয়ার্কার (`FraudConsumer`)")
    md_bullet("কাফকার 'transactions' টপিক থেকে রিয়েল-টাইমে মেসেজ পড়ে।", bold_prefix="পোলিং (Poll):")
    md_bullet(
        "রেডিস থেকে ভেলোসিটি ফিচার এনে রুল ইঞ্জিন ও এআই মডেলে পাঠায়।", bold_prefix="প্রসেসিং (Process):"
    )
    md_bullet(
        "অ্যাট-লিস্ট-ওয়ান্স (At-least-once) ডেলিভারি নিশ্চিত করতে প্রসেসিং সফল হলে অফসেট ম্যানুয়ালি সেভ করে।",
        bold_prefix="ম্যানুয়াল কমিট (Manual Commit):",
    )
    md_bullet(
        "কোনো বার্তা যদি নষ্ট বা ভুল ফরম্যাটে আসে, তবে সিস্টেম না থামিয়ে সেটিকে আলাদা ডেড-লেটার কিউতে ফেলে দেয়।",
        bold_prefix="ডেড লেটার কিউ (DLQ):",
    )

    # ----------------------------------------------------
    # অধ্যায় ৮: স্টেজ ৭
    # ----------------------------------------------------
    md_h1("অধ্যায় ৮: স্টেজ ৭ — পোস্টগ্রেস পারসিসটেন্স লেয়ার ও মাইক্রো-ব্যাচিং বাফার")

    md_p(
        "কনজিউমার যখন প্রতি সেকেন্ডে শত শত লেনদেন স্ক্যান করে সিদ্ধান্ত নিচ্ছে, তখন সেই ফলাফলগুলো ডাটাবেসে স্থায়ীভাবে সেভ করা প্রয়োজন। "
        "কিন্তু আপনি যদি প্রতি ট্রানজ্যাকশন শেষ হওয়ার সাথে সাথে আলাদা করে ডাটাবেসে `INSERT INTO transactions ...` চালান, তবে সার্ভারের হার্ডডিস্কের ওপর প্রচণ্ড চাপ পড়ে কনজিউমার আটকে যাবে! "
        "স্টেজ ৭-এ আমরা এই সমস্যার যুগান্তকারী সমাধান করেছি — 'মাইক্রো-ব্যাচিং বাফার' (Micro-Batch Persistence Buffer)।",
        bold_prefix="ডিস্ক বোটলনেক সমস্যা:",
    )

    md_h2("১. সিঙ্গেল ইনসার্ট বনাম মাইক্রো-ব্যাচিং")
    batch_table = [
        ["বৈশিষ্ট্য", "সিঙ্গেল রো ইনসার্ট (Single Insert)", "আমাদের মাইক্রো-ব্যাচ ইনসার্ট (Micro-Batch)"],
        ["নেটওয়ার্ক রাউন্ড-ট্রিপ (RTT)", "প্রতি লেনদেনে ১ বার", "৫০-১০০টি লেনদেনের জন্য মাত্র ১ বার!"],
        [
            "ডিস্ক রাইট ও কমিট (fsync)",
            "সেকেন্ডে ১০০-২০০ বার (ডিস্ক স্লো)",
            "সেকেন্ডে মাত্র ১-২ বার (ডিস্ক দ্রুত)",
        ],
        ["সর্বোচ্চ ক্ষমতা (Throughput)", "~১৫০-২৫০ ট্রানজ্যাকশন/সেকেন্ড", "২,৫০০ - ৫,০০০+ ট্রানজ্যাকশন/সেকেন্ড!"],
        ["ডাটাবেস সিপিইউ ব্যবহার", "অত্যধিক (বারবার কুয়েরি পার্সিং)", "খুবই কম (বাল্ক এক্সিকিউশন)"],
    ]
    md_table(batch_table[0], batch_table[1:])

    md_h2("২. ডুয়াল-ট্রিগার মেকানিজম (Dual-Trigger Flush Logic)")
    md_p(
        "কনজিউমার যখন একটি ট্রানজ্যাকশন শেষ করে, তখন সে ডাটাবেসের জন্য অপেক্ষা না করে সাথে সাথে মেমরির একটি সুরক্ষিত কিউতে (`asyncio.Queue`) ফলাফলটি রেখে পরবর্তী মেসেজ পড়তে চলে যায়। "
        "একটি ব্যাকগ্রাউন্ড ওয়ার্কার কিউটি পাহারা দেয় এবং দুটি শর্তের যেকোনো একটি পূরণ হলেই ডাটাবেসে পাঠায়:"
    )
    md_bullet(
        "কিউতে ৫০টি ট্রানজ্যাকশন জমা হওয়ার সাথে সাথেই সাথে সাথে বাল্ক ইনসার্ট হবে।",
        bold_prefix="শর্ত ১ (Size Trigger):",
    )
    md_bullet(
        "যদি ট্রাফিক কম থাকে এবং ৫০টি জমা না হয়, তবুও সর্বোচ্চ ৫০ মিলি-সেকেন্ড পর যা জমা হয়েছে তা নিয়েই ডাটাবেসে সেভ হবে। এর ফলে কোনো ট্রানজ্যাকশন কখনোই মেমরিতে আটকে থাকবে না।",
        bold_prefix="শর্ত ২ (Time Trigger):",
    )

    md_h2("৩. আইডেমপোটেন্সি (Idempotency) ও ডুপ্লিকেট রোধ")
    md_p(
        "কাফকা বা নেটওয়ার্কে ক্র্যাশ হলে কখনো কখনো একই লেনদেন দুইবার চলে আসতে পারে। আমাদের রিপোজিটরি ডাটাবেসে এক্সিকিউট করে:"
    )
    md_code("INSERT INTO transactions (...) VALUES (...) ON CONFLICT (transaction_ref) DO NOTHING;")
    md_p("এর ফলে ডুপ্লিকেট ট্রানজ্যাকশন এলেও কোনো এরর হবে না এবং হিসেবে ডবল কাউন্ট হবে না। এটি পুরোপুরি সেফ!")

    md_h2("৪. `asyncpg` কানেকশন পুল ও অফলাইন সিমুলেটর")
    md_p(
        "আমরা পাইথনের সবচেয়ে দ্রুততম ড্রাইভার `asyncpg` ব্যবহার করেছি। একইসাথে একটি ফুল ইন-মেমরি সিমুলেটর তৈরি করা হয়েছে, যাতে ডকার বা লোকাল পোস্টগ্রেস বন্ধ থাকলেও আপনার কোড বা টেস্ট কখনও আটকে না থাকে।"
    )

    # ----------------------------------------------------
    # অধ্যায় ৯: টেস্ট ও ভেরিফিকেশন গাইড
    # ----------------------------------------------------
    md_h1("অধ্যায় ৯: কীভাবে পুরো সিস্টেমটি টেস্ট ও রান করবেন?")

    md_p(
        "আপনার পিসিতে টার্মিনালে গিয়ে সরাসরি নিচের কমান্ডগুলো রান করে আপনি নিজেই পুরো সিস্টেমের কার্যকারিতা দেখতে পারেন:",
        bold_prefix="হাতে-কলমে ট্রায়াল:",
    )

    md_h2("১. ভার্চুয়াল এনভায়রনমেন্ট সিঙ্ক ও ডিপেন্ডেন্সি ইনস্টল")
    md_code("uv sync")

    md_h2("২. পোস্টগ্রেস মাইক্রো-ব্যাচিং বাফারের লাইভ ডেমো রান")
    md_p("এটি মেমরিতে ১০০টি ট্রানজ্যাকশন পুশ করে ডুয়াল-ট্রিগার ব্যাচিং টেস্ট করে দেখাবে:")
    md_code("uv run python consumers/persistence_worker.py --count 100 --mock")

    md_h2("৩. রিয়েল-টাইম ফ্রড কনজিউমার রান")
    md_p("এটি সিন্থেটিক ট্রানজ্যাকশন স্ট্রিম থেকে ২৫টি মেসেজ স্ক্যান করে এআই ডিসিশন ও পোস্টগ্রেস সেভিং দেখাবে:")
    md_code("uv run fraud-consumer --mock --max-messages 25")

    md_h2("৪. সমস্ত স্বয়ংক্রিয় টেস্ট একসাথে রান করা (৮৪টি টেস্ট)")
    md_code("uv run pytest tests/ -v")

    md_h2("৫. লাইভ ডকারে পোস্টগ্রেস ডাটাবেস কুয়েরি করা")
    md_p("ডকার চালু থাকলে ডাটাবেসের ভেতরের স্ট্যাটাস দেখতে রান করুন:")
    md_code(
        'docker compose exec postgres psql -U postgres -d fraud_detection -c "SELECT status, count(*), round(avg(risk_score), 4) as avg_risk, round(sum(amount), 2) as volume FROM transactions GROUP BY status;"'
    )

    # ----------------------------------------------------
    # অধ্যায় ১০: ভবিষ্যৎ রোডম্যাপ
    # ----------------------------------------------------
    md_h1("অধ্যায় ১০: ভবিষ্যৎ রোডম্যাপ (পরবর্তী স্টেজগুলোতে কী আসছে?)")

    md_p(
        "স্টেজ ৭ সফলভাবে সম্পন্ন হওয়ার পর আমাদের সিস্টেমের কোর ব্যাকএন্ড, ডেটাবেস, এআই ও স্ট্রিমিং পুরোপুরি প্রস্তুত। পরবর্তী স্টেজগুলোতে আমরা তৈরি করব:"
    )

    md_bullet(
        "ব্যাংক কর্মকর্তা ও অডিটরের জন্য REST API গেটওয়ে, ওটিপি চ্যালেঞ্জ ও অ্যালার্ট হিস্ট্রি।",
        bold_prefix="স্টেজ ৮ (FastAPI Gateway & Endpoints):",
    )
    md_bullet(
        "ওয়েবসকেট (WebSocket) সংযোগের মাধ্যমে লাইভ স্ক্রিনে চোখের সামনে ট্রানজ্যাকশনAPPROVED/REJECTED হওয়ার রিয়েল-টাইম চার্ট।",
        bold_prefix="স্টেজ ৯ (Live WebSocket Dashboard):",
    )
    md_bullet(
        "সম্পূর্ণ ডকারাইজড ও ক্লাউড রেডি ডেপ্লয়মেন্ট পাইপলাইন।",
        bold_prefix="স্টেজ ১০ (CI/CD & Cloud Deployment):",
    )

    md_callout(
        "স্বয়ংক্রিয় আপডেট গ্যারান্টি:",
        "পরবর্তী স্টেজগুলো (স্টেজ ৮, ৯, ১০...) যখনই সম্পন্ন হবে, এই গাইডবুকটি সাথে সাথে নতুন কোড, আর্কিটেকচার ও কমান্ড সহ আপডেট হয়ে যাবে।",
        kind="tip",
    )

    # Save both .docx and .md
    doc.save(docx_path)
    Path(md_path).write_text("\n".join(md_lines), encoding="utf-8")
    print(f"Generated DOCX guide: {docx_path}")
    print(f"Generated Markdown guide: {md_path}")


if __name__ == "__main__":
    out_docx = "docs/Real_Time_Fraud_Detection_Bengali_Guide.docx"
    out_md = "docs/Real_Time_Fraud_Detection_Bengali_Guide.md"
    build_full_guide(out_docx, out_md)
