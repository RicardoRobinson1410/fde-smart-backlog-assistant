from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.graphics.shapes import Drawing, Rect, String, Line, Polygon
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, KeepTogether
)

OUT_PATH = Path(r"c:\Proyectos\FDE_accenture\FDE PROJECT\docs\RDE_Step1_Step2_Problem_and_Design.pdf")
OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

NAVY = colors.HexColor("#0F172A")
PURPLE = colors.HexColor("#7C3AED")
BLUE = colors.HexColor("#2563EB")
TEAL = colors.HexColor("#0D9488")
SLATE = colors.HexColor("#334155")
MUTED = colors.HexColor("#64748B")
BG_LIGHT = colors.HexColor("#F8FAFC")
BG_CODE = colors.HexColor("#F1F5F9")
BORDER = colors.HexColor("#CBD5E1")


def build_simple_diagram() -> Drawing:
    """Easy-to-read 4-step architecture & data flow diagram."""
    w, h = 490, 180
    d = Drawing(w, h)
    d.add(Rect(0, 0, w, h, rx=8, ry=8, fillColor=BG_LIGHT, strokeColor=BORDER, strokeWidth=1))

    # Legend
    d.add(Rect(14, h - 22, 10, 10, rx=2, ry=2, fillColor=colors.HexColor("#E0F2FE"), strokeColor=BLUE, strokeWidth=1))
    d.add(String(28, h - 20, "Regular Python Code (Fast & Safe)", fontName="Helvetica-Bold", fontSize=7.5, fillColor=SLATE))
    d.add(Rect(200, h - 22, 10, 10, rx=2, ry=2, fillColor=colors.HexColor("#F3E8FF"), strokeColor=PURPLE, strokeWidth=1))
    d.add(String(214, h - 20, "AI Step (OpenAI via LangGraph)", fontName="Helvetica-Bold", fontSize=7.5, fillColor=PURPLE))
    d.add(Rect(370, h - 22, 10, 10, rx=2, ry=2, fillColor=colors.HexColor("#CCFBF1"), strokeColor=TEAL, strokeWidth=1))
    d.add(String(384, h - 20, "Final Output", fontName="Helvetica-Bold", fontSize=7.5, fillColor=TEAL))

    def box(x, y, bw, bh, title, line1, line2, fill, stroke, tcolor=NAVY):
        d.add(Rect(x, y, bw, bh, rx=6, ry=6, fillColor=fill, strokeColor=stroke, strokeWidth=1.3))
        d.add(String(x + 7, y + bh - 15, title, fontName="Helvetica-Bold", fontSize=8.2, fillColor=tcolor))
        d.add(String(x + 7, y + bh - 28, line1, fontName="Helvetica", fontSize=7.2, fillColor=SLATE))
        d.add(String(x + 7, y + bh - 39, line2, fontName="Helvetica", fontSize=7.2, fillColor=MUTED))

    def arrow_r(x1, y1, x2, y2):
        d.add(Line(x1, y1, x2, y2, strokeColor=SLATE, strokeWidth=1.2))
        d.add(Polygon([x2, y2, x2 - 5, y2 + 3, x2 - 5, y2 - 3], fillColor=SLATE, strokeColor=SLATE))

    det_fill = colors.HexColor("#E0F2FE")
    ai_fill = colors.HexColor("#F3E8FF")
    out_fill = colors.HexColor("#CCFBF1")

    # Top row: Step 1 -> Step 2
    box(14, 92, 215, 52, "Step 1: Read & Protect (Python)", "Reads .txt, .md, or .pdf notes + backlog JSON", "Hides emails, card numbers & API keys locally", det_fill, BLUE)
    arrow_r(229, 118, 256, 118)
    box(256, 92, 220, 52, "Step 2: Write Stories (AI - gpt-4o-mini)", "Turns messy notes into clear User Stories", "Lists missing details under Open Questions", ai_fill, PURPLE, PURPLE)

    # Connector from Step 2 down-left to Step 3
    d.add(Line(366, 92, 366, 80, strokeColor=SLATE, strokeWidth=1.2))
    d.add(Line(366, 80, 121, 80, strokeColor=SLATE, strokeWidth=1.2))
    d.add(Line(121, 80, 121, 68, strokeColor=SLATE, strokeWidth=1.2))
    d.add(Polygon([121, 68, 118, 73, 124, 73], fillColor=SLATE, strokeColor=SLATE))

    # Bottom row: Step 3 -> Step 4
    box(14, 14, 215, 54, "Step 3: Check Duplicates & Risks (AI)", "Compares against existing tickets (NEW/DUP/CONFLICT)", "gpt-4o flags risky P0 or security conflicts for human review", ai_fill, PURPLE, PURPLE)
    arrow_r(229, 41, 256, 41)
    box(256, 14, 220, 54, "Step 4: Validate & Deliver (Python)", "Checks >=3 testable Acceptance Criteria (Pydantic)", "Updates Kanban Board, Reports, Evals & Audit Logs", out_fill, TEAL, TEAL)

    return d


def build_pdf() -> None:
    doc = SimpleDocTemplate(
        str(OUT_PATH),
        pagesize=LETTER,
        leftMargin=0.65 * inch,
        rightMargin=0.65 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.55 * inch,
        title="Smart Backlog Assistant - Guide, Design & Initialization",
        author="Smart Backlog Assistant (FDE Edition)",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "DocTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=18,
        textColor=NAVY, spaceAfter=4, alignment=0
    )
    subtitle_style = ParagraphStyle(
        "DocSub", parent=styles["Normal"], fontName="Helvetica", fontSize=10,
        textColor=MUTED, spaceAfter=12
    )
    h1_style = ParagraphStyle(
        "H1", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=13,
        textColor=PURPLE, spaceBefore=10, spaceAfter=5
    )
    h2_style = ParagraphStyle(
        "H2", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=10.5,
        textColor=NAVY, spaceBefore=7, spaceAfter=4
    )
    body_style = ParagraphStyle(
        "Body", parent=styles["Normal"], fontName="Helvetica", fontSize=9.4,
        leading=13.8, textColor=SLATE, spaceAfter=5
    )
    bullet_style = ParagraphStyle(
        "Bullet", parent=body_style, leftIndent=14, bulletIndent=4, spaceAfter=3.5
    )
    code_style = ParagraphStyle(
        "Code", parent=styles["Normal"], fontName="Courier", fontSize=8.4,
        leading=12, textColor=NAVY, backColor=BG_CODE, borderPadding=6,
        spaceBefore=2, spaceAfter=6
    )

    story = []

    # Header
    story.append(Paragraph("Certified RDE Certification — Hands-On Project", subtitle_style))
    story.append(Paragraph("Smart Backlog Assistant: Plain-English Guide", title_style))
    story.append(Paragraph(
        "Problem Definition • Solution Design • Prompt Strategy • Code Review Guide • How to Initialize &amp; Run",
        subtitle_style
    ))

    # ==================== REVIEWER CALLOUT ====================
    note_box_data = [[
        Paragraph(
            "<b>IMPORTANT CODE REVIEW NOTE:</b><br/>"
            "• <b>Inspect the <code>agent/</code> folder only:</b> To evaluate the AI Agent, Prompts, Subagents, MCPs, Hooks, and Tools, reviewers only need to check the dedicated <b><code>agent/</code></b> directory. All AI components are cleanly condensed there without UI clutter.<br/>"
            "• <b>Do NOT delete <code>src/backlog_assistant/</code>:</b> The code in <code>src/backlog_assistant/</code> is the active, runnable package that powers the Streamlit web portal (<code>app.py</code>), terminal CLI, and automated <code>pytest</code> test suite. It is required for live execution.",
            ParagraphStyle("ReviewNote", parent=body_style, fontSize=8.4, leading=12, textColor=NAVY)
        )
    ]]
    note_tbl = Table(note_box_data, colWidths=[7.20 * inch])
    note_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FEF3C7")),
        ("BOX", (0, 0), (-1, -1), 1.2, colors.HexColor("#F59E0B")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(note_tbl)
    story.append(Spacer(1, 8))

    # ==================== STEP 1 ====================
    story.append(Paragraph("1. What Problem Does This Solve? (Step 1)", h1_style))
    story.append(Paragraph(
        "After every planning meeting, outage, or compliance review, engineers end up with messy notes, Markdown files, "
        "or PDFs. Turning those notes into clean Jira tickets by hand takes hours—and asking a basic AI to do it "
        "usually causes four headaches:",
        body_style
    ))
    for b in [
        "<b>Duplicate Tickets:</b> Creating a brand-new ticket for work that is already in the backlog.",
        "<b>Missed Updates:</b> Forgetting to link new requirements to the existing ticket they change.",
        "<b>Hidden Conflicts:</b> Missing when a new security rule breaks an existing feature (for example, requiring encryption when a current ticket uses plain caching).",
        "<b>Made-Up Numbers:</b> AI guessing deadlines or SLAs when the notes didn't mention them.",
    ]:
        story.append(Paragraph(f"• {b}", bullet_style))

    story.append(Paragraph("Three Real-World Examples Included", h2_style))
    hdr_style = ParagraphStyle(
        "TblHdr", parent=body_style, fontName="Helvetica-Bold", fontSize=8.4,
        leading=11, textColor=colors.white, spaceAfter=0
    )
    cell_style = ParagraphStyle(
        "TblCell", parent=body_style, fontName="Helvetica", fontSize=8.3,
        leading=11.5, textColor=SLATE, spaceAfter=0
    )
    uc_data = [
        [
            Paragraph("Scenario", hdr_style),
            Paragraph("Input File", hdr_style),
            Paragraph("What the Assistant Produces", hdr_style),
        ],
        [
            Paragraph("<b>1. Sprint Planning</b>", cell_style),
            Paragraph("01_sprint_planning_notes.txt", cell_style),
            Paragraph("Creates a new SSO login story, spots that CSV Export already exists (FIN-101), and updates Webhook Retries (FIN-104).", cell_style),
        ],
        [
            Paragraph("<b>2. Outage Postmortem</b>", cell_style),
            Paragraph("02_incident_postmortem.md", cell_style),
            Paragraph("Turns an outage report into a new circuit-breaker story and tightens timeout limits on an existing ticket (FIN-105).", cell_style),
        ],
        [
            Paragraph("<b>3. Security PDF</b>", cell_style),
            Paragraph("03_pci_compliance_spec.pdf", cell_style),
            Paragraph("Reads a PDF spec, catches a security conflict with FIN-106 (requiring human approval), and creates an audit-log story.", cell_style),
        ],
    ]
    uc_tbl = Table(uc_data, colWidths=[1.30 * inch, 1.75 * inch, 4.15 * inch])
    uc_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("BACKGROUND", (0, 1), (-1, -1), BG_LIGHT),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(uc_tbl)
    story.append(Spacer(1, 5))
    story.append(Paragraph(
        "<b>How AI Helped Define the Problem:</b> Used AI pair-programming to design realistic test scenarios that cover "
        "duplicates, updates, security conflicts, and missing specifications—not just simple text summaries.",
        body_style
    ))

    # ==================== STEP 2 ====================
    story.append(Paragraph("2. How the Solution Is Designed (Step 2)", h1_style))
    story.append(KeepTogether([build_simple_diagram(), Spacer(1, 6)]))

    story.append(Paragraph("How We Designed the AI Prompts (3 Iterations)", h2_style))
    for b in [
        "<b>v1 — Simple Request:</b> Just asked AI for JSON stories. <i>Problem:</i> It marked everything High Priority, wrote vague criteria ('system should be fast'), and invented SLAs.",
        "<b>v2 — Role &amp; Scoring Rules:</b> Gave the AI an Engineer persona, clear P0–P3 priority rules, and Fibonacci story points (1, 2, 3, 5, 8, 13).",
        "<b>v3 — Backlog-Aware &amp; Configurable (prompts.py):</b> Fed the existing backlog into the prompt so the AI classifies every item as <b>NEW</b>, <b>UPDATES_EXISTING</b>, <b>DUPLICATE</b>, or <b>CONFLICT</b>, and puts any missing info into <b>Open Questions</b> instead of guessing.",
    ]:
        story.append(Paragraph(f"• {b}", bullet_style))

    story.append(Paragraph(
        "<b>How AI Helped in Design:</b> Used AI pair-programming to structure the strict output schemas (Pydantic v2), "
        "build a 12-case Evaluation Lab with an AI Judge, and route simple tasks to <b>gpt-4o-mini</b> while saving "
        "<b>gpt-4o</b> for security checks (cutting API cost by ~94%).",
        body_style
    ))

    # ==================== HOW TO INITIALIZE ====================
    story.append(Paragraph("3. How to Initialize &amp; Run the Project", h1_style))
    story.append(Paragraph(
        "Follow these steps in Windows PowerShell from the project root folder. No paid API key is required to test—if "
        "OPENAI_API_KEY is not set, the app automatically runs in <b>Offline Mode</b>.",
        body_style
    ))

    story.append(Paragraph("Step A — Activate Environment &amp; Install Dependencies", h2_style))
    story.append(Paragraph(
        ".\\.venv\\Scripts\\Activate.ps1<br/>"
        "pip install -r requirements.txt<br/>"
        "pip install -e .",
        code_style
    ))

    story.append(Paragraph("Step B — (Optional) Configure OpenAI API Key for Live AI Mode", h2_style))
    story.append(Paragraph(
        "Copy <b>.env.example</b> to <b>.env</b> and add your key (skip this step to run in free Offline Mode):",
        body_style
    ))
    story.append(Paragraph(
        "Copy-Item .env.example .env<br/>"
        "# Then edit .env and set: OPENAI_API_KEY=sk-...",
        code_style
    ))

    story.append(Paragraph("Step C — Launch the 8-Tab Interactive Web Portal", h2_style))
    story.append(Paragraph(
        "python -m streamlit run src/backlog_assistant/app.py --server.port 8501",
        code_style
    ))
    story.append(Paragraph(
        "Open <b>http://localhost:8501</b> in your browser. Use Tab 1 to chat or upload files, Tab 2 for the Kanban Board, "
        "Tab 5 for the 12-case Evaluation Lab, and Tab 8 to switch or create isolated projects.",
        body_style
    ))

    story.append(Paragraph("Step D — Run CLI Analysis &amp; Automated Tests", h2_style))
    story.append(Paragraph(
        "python -m backlog_assistant.cli analyze data/samples/01_sprint_planning_notes.txt --offline<br/>"
        "python -m backlog_assistant.cli evaluate --offline<br/>"
        "python -m pytest -v",
        code_style
    ))

    doc.build(story)
    print(f"PDF_CREATED: {OUT_PATH} ({OUT_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    build_pdf()
