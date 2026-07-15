#!/usr/bin/env python3
"""
md2map.py — convert a Markdown outline (headings + nested bullets) into:

  1. a .drawio mind map   (imports into Lucidchart / draw.io desktop)
  2. a .vsdx mind map     (drags straight onto a Zoom Whiteboard, which
                           converts Visio shapes/connectors/text into
                           editable whiteboard objects)

Layout: tidy left-to-right tree — root at the left, one column per depth,
leaves stacked vertically, parents centred on their children.

Usage:
  python3 tools/md2map.py overview.md              # writes overview.drawio + overview.vsdx
  python3 tools/md2map.py overview.md -o out/map   # writes out/map.drawio + out/map.vsdx
"""

import argparse
import html
import re
import zipfile
from pathlib import Path

# ---------------------------------------------------------------- parsing

class Node:
    def __init__(self, text, depth):
        self.text = text
        self.depth = depth
        self.children = []
        # filled in by layout()
        self.id = 0
        self.x = self.y = self.w = self.h = 0.0


MD_CLEAN = [
    (re.compile(r"\*\*(.+?)\*\*"), r"\1"),   # bold
    (re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)"), r"\1"),  # italics (incl. citations)
    (re.compile(r"`([^`]*)`"), r"\1"),       # inline code
]


def clean(text):
    for rx, rep in MD_CLEAN:
        text = rx.sub(rep, text)
    return text.strip()


def parse_markdown(md):
    """Headings (#/##/###…) and dash bullets (2-space indent per level)."""
    root = None
    heading_stack = {}   # heading level -> node
    bullet_stack = []    # stack of (indent, node)

    for raw in md.splitlines():
        if not raw.strip():
            continue
        m = re.match(r"^(#+)\s+(.*)$", raw)
        if m:
            level = len(m.group(1))
            node = Node(clean(m.group(2)), level - 1)
            if level == 1 and root is None:
                root = node
            else:
                parent = heading_stack.get(level - 1) or root
                if parent is None:
                    root = node
                else:
                    parent.children.append(node)
            heading_stack[level] = node
            heading_stack = {k: v for k, v in heading_stack.items() if k <= level}
            bullet_stack = []
            continue
        m = re.match(r"^(\s*)-\s+(.*)$", raw)
        if m:
            indent = len(m.group(1))
            anchor = heading_stack[max(heading_stack)] if heading_stack else root
            while bullet_stack and bullet_stack[-1][0] >= indent:
                bullet_stack.pop()
            parent = bullet_stack[-1][1] if bullet_stack else anchor
            node = Node(clean(m.group(2)), parent.depth + 1)
            parent.children.append(node)
            bullet_stack.append((indent, node))
    if root is None:
        raise SystemExit("No level-1 heading found in the markdown.")
    return root

# ---------------------------------------------------------------- layout
# Units are INCHES (Visio native; converted to px for draw.io).

ROW_H = 0.42        # node height
ROW_GAP = 0.16      # vertical gap between sibling leaves
COL_GAP = 0.55      # horizontal gap between columns
CHAR_W = 0.082      # rough width of a character at 10pt
MIN_W, MAX_W = 1.0, 3.4


def node_width(text):
    return max(MIN_W, min(MAX_W, 0.3 + len(text) * CHAR_W))


def layout(root):
    """Assign ids, x/y (top-left, y grows downward), w/h. Returns (w, h)."""
    counter = [0]

    def assign_ids(n):
        counter[0] += 1
        n.id = counter[0]
        for c in n.children:
            assign_ids(c)
    assign_ids(root)

    # column x-offsets: widest node per depth defines the column
    col_w = {}
    def measure(n):
        n.w, n.h = node_width(n.text), ROW_H
        col_w[n.depth] = max(col_w.get(n.depth, 0), n.w)
        for c in n.children:
            measure(c)
    measure(root)
    col_x = {}
    x = 0.4
    for d in sorted(col_w):
        col_x[d] = x
        x += col_w[d] + COL_GAP

    # y: leaves stack downward, parents centre on children
    cursor = [0.4]
    def place(n):
        n.x = col_x[n.depth]
        if not n.children:
            n.y = cursor[0]
            cursor[0] += n.h + ROW_GAP
        else:
            for c in n.children:
                place(c)
            n.y = (n.children[0].y + n.children[-1].y + n.children[-1].h) / 2 - n.h / 2
    place(root)
    return x + 0.4, cursor[0] + 0.4   # page width, page height

# ---------------------------------------------------------------- palette

PALETTE = [  # (fill, stroke) per top-level branch, cycled
    ("#dae8fc", "#6c8ebf"), ("#d5e8d4", "#82b366"), ("#ffe6cc", "#d79b00"),
    ("#e1d5e7", "#9673a6"), ("#fff2cc", "#d6b656"), ("#f8cecc", "#b85450"),
]
ROOT_FILL, ROOT_STROKE = "#e8b64c", "#8f6b1e"
LEAF_FILL, LEAF_STROKE = "#f5f5f5", "#999999"


def branch_colors(root):
    """Map node id -> (fill, stroke): root gold, each theme its own colour."""
    colors = {root.id: (ROOT_FILL, ROOT_STROKE)}
    for i, theme in enumerate(root.children):
        fill = PALETTE[i % len(PALETTE)]
        def paint(n, depth=0):
            colors[n.id] = fill if depth < 2 else (LEAF_FILL, LEAF_STROKE)
            for c in n.children:
                paint(c, depth + 1)
        paint(theme)
    return colors

# ---------------------------------------------------------------- draw.io

PX = 96  # px per inch


def emit_drawio(root, colors, path):
    cells = []

    def visit(n, parent=None):
        fill, stroke = colors[n.id]
        bold = ";fontStyle=1" if n.depth <= 1 else ""
        cells.append(
            f'<mxCell id="n{n.id}" value="{html.escape(n.text)}" '
            f'style="rounded=1;whiteSpace=wrap;html=1;fillColor={fill};'
            f'strokeColor={stroke}{bold};" vertex="1" parent="1">'
            f'<mxGeometry x="{n.x*PX:.0f}" y="{n.y*PX:.0f}" '
            f'width="{n.w*PX:.0f}" height="{n.h*PX:.0f}" as="geometry" /></mxCell>'
        )
        if parent is not None:
            _, stroke_p = colors[n.id]
            cells.append(
                f'<mxCell id="e{n.id}" style="edgeStyle=orthogonalEdgeStyle;rounded=1;'
                f'orthogonalLoop=1;jettySize=auto;html=1;endArrow=none;'
                f'strokeColor={stroke_p};exitX=1;exitY=0.5;entryX=0;entryY=0.5;" '
                f'edge="1" parent="1" source="n{parent.id}" target="n{n.id}">'
                f'<mxGeometry relative="1" as="geometry" /></mxCell>'
            )
        for c in n.children:
            visit(c, n)
    visit(root)

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<mxfile host="drawio" version="26.0.0">\n'
        '  <diagram name="Mind Map">\n'
        '    <mxGraphModel><root><mxCell id="0" /><mxCell id="1" parent="0" />'
        + "".join(cells) +
        '</root></mxGraphModel>\n  </diagram>\n</mxfile>\n'
    )
    path.write_text(xml, encoding="utf-8")

# ---------------------------------------------------------------- vsdx

VISIO_NS = "http://schemas.microsoft.com/office/visio/2012/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def emit_vsdx(root, colors, path, page_w, page_h):
    """Minimal masterless VSDX. Visio's y-axis points UP, origin bottom-left."""
    shapes, connects = [], []

    def flip(y, h):          # top-left y (down) -> Visio pin y (up, centre)
        return page_h - (y + h / 2)

    def visit(n, parent=None):
        fill, stroke = colors[n.id]
        pin_x = n.x + n.w / 2
        pin_y = flip(n.y, n.h)
        bold = '<Cell N="Style" V="17"/>' if n.depth <= 1 else ""
        shapes.append(f"""
   <Shape ID="{n.id}" Type="Shape" Name="Node{n.id}" NameU="Node{n.id}">
    <Cell N="PinX" V="{pin_x:.3f}"/><Cell N="PinY" V="{pin_y:.3f}"/>
    <Cell N="Width" V="{n.w:.3f}"/><Cell N="Height" V="{n.h:.3f}"/>
    <Cell N="LocPinX" V="{n.w/2:.3f}"/><Cell N="LocPinY" V="{n.h/2:.3f}"/>
    <Cell N="FillForegnd" V="{fill}"/>
    <Cell N="FillPattern" V="1"/>
    <Cell N="LineColor" V="{stroke}"/>
    <Cell N="LineWeight" V="0.014"/>
    <Cell N="Rounding" V="0.06"/>
    <Cell N="VerticalAlign" V="1"/>
    <Section N="Character"><Row IX="0"><Cell N="Color" V="#333333"/><Cell N="Size" V="0.125"/>{bold}</Row></Section>
    <Section N="Geometry" IX="0">
     <Cell N="NoFill" V="0"/><Cell N="NoLine" V="0"/>
     <Row T="RelMoveTo" IX="1"><Cell N="X" V="0"/><Cell N="Y" V="0"/></Row>
     <Row T="RelLineTo" IX="2"><Cell N="X" V="1"/><Cell N="Y" V="0"/></Row>
     <Row T="RelLineTo" IX="3"><Cell N="X" V="1"/><Cell N="Y" V="1"/></Row>
     <Row T="RelLineTo" IX="4"><Cell N="X" V="0"/><Cell N="Y" V="1"/></Row>
     <Row T="RelLineTo" IX="5"><Cell N="X" V="0"/><Cell N="Y" V="0"/></Row>
    </Section>
    <Text>{html.escape(n.text)}</Text>
   </Shape>""")
        if parent is not None:
            cid = 1000 + n.id
            bx = parent.x + parent.w          # parent right edge
            by = flip(parent.y, parent.h)
            ex = n.x                          # child left edge
            ey = flip(n.y, n.h)
            dist = ((ex - bx) ** 2 + (ey - by) ** 2) ** 0.5 or 0.01
            _, stroke_c = colors[n.id]
            shapes.append(f"""
   <Shape ID="{cid}" Type="Shape" Name="Conn{cid}" NameU="Conn{cid}">
    <Cell N="BeginX" V="{bx:.3f}"/><Cell N="BeginY" V="{by:.3f}"/>
    <Cell N="EndX" V="{ex:.3f}"/><Cell N="EndY" V="{ey:.3f}"/>
    <Cell N="PinX" V="{bx:.3f}"/><Cell N="PinY" V="{by:.3f}"/>
    <Cell N="Width" V="{dist:.3f}"/><Cell N="Height" V="0"/>
    <Cell N="LocPinX" V="0"/><Cell N="LocPinY" V="0"/>
    <Cell N="OneD" V="1"/><Cell N="ObjType" V="2"/>
    <Cell N="LineColor" V="{stroke_c}"/>
    <Cell N="LineWeight" V="0.014"/>
    <Cell N="BeginArrow" V="0"/><Cell N="EndArrow" V="0"/>
    <Section N="Geometry" IX="0">
     <Cell N="NoFill" V="1"/>
     <Row T="MoveTo" IX="1"><Cell N="X" V="0"/><Cell N="Y" V="0"/></Row>
     <Row T="LineTo" IX="2"><Cell N="X" V="{dist:.3f}"/><Cell N="Y" V="0"/></Row>
    </Section>
   </Shape>""")
            connects.append(
                f'  <Connect FromSheet="{cid}" FromCell="BeginX" FromPart="9" '
                f'ToSheet="{parent.id}" ToCell="PinX" ToPart="3"/>\n'
                f'  <Connect FromSheet="{cid}" FromCell="EndX" FromPart="12" '
                f'ToSheet="{n.id}" ToCell="PinX" ToPart="3"/>'
            )
        for c in n.children:
            visit(c, n)
    visit(root)

    page1 = (
        f'<?xml version="1.0" encoding="utf-8"?>\n'
        f'<PageContents xmlns="{VISIO_NS}" xmlns:r="{R_NS}" xml:space="preserve">\n'
        f' <Shapes>{"".join(shapes)}\n </Shapes>\n'
        f' <Connects>\n{chr(10).join(connects)}\n </Connects>\n'
        f'</PageContents>'
    )
    pages = (
        f'<?xml version="1.0" encoding="utf-8"?>\n'
        f'<Pages xmlns="{VISIO_NS}" xmlns:r="{R_NS}" xml:space="preserve">\n'
        f' <Page ID="0" NameU="Page-1" Name="Page-1">\n'
        f'  <PageSheet LineStyle="0" FillStyle="0" TextStyle="0">\n'
        f'   <Cell N="PageWidth" V="{page_w:.3f}"/>\n'
        f'   <Cell N="PageHeight" V="{page_h:.3f}"/>\n'
        f'   <Cell N="PageScale" V="1" U="IN_F"/>\n'
        f'   <Cell N="DrawingScale" V="1" U="IN_F"/>\n'
        f'  </PageSheet>\n'
        f'  <Rel r:id="rId1"/>\n'
        f' </Page>\n'
        f'</Pages>'
    )
    document = (
        f'<?xml version="1.0" encoding="utf-8"?>\n'
        f'<VisioDocument xmlns="{VISIO_NS}" xmlns:r="{R_NS}" xml:space="preserve">\n'
        f' <DocumentSettings/>\n'
        f' <StyleSheets>\n'
        f'  <StyleSheet ID="0" NameU="No Style" Name="No Style">\n'
        f'   <Cell N="EnableLineProps" V="1"/><Cell N="EnableFillProps" V="1"/>\n'
        f'   <Cell N="EnableTextProps" V="1"/>\n'
        f'  </StyleSheet>\n'
        f' </StyleSheets>\n'
        f'</VisioDocument>'
    )
    content_types = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
        ' <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
        ' <Default Extension="xml" ContentType="application/xml"/>\n'
        ' <Override PartName="/visio/document.xml" ContentType="application/vnd.ms-visio.drawing.main+xml"/>\n'
        ' <Override PartName="/visio/pages/pages.xml" ContentType="application/vnd.ms-visio.pages+xml"/>\n'
        ' <Override PartName="/visio/pages/page1.xml" ContentType="application/vnd.ms-visio.page+xml"/>\n'
        '</Types>'
    )
    root_rels = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        ' <Relationship Id="rId1" Type="http://schemas.microsoft.com/visio/2010/relationships/document" Target="visio/document.xml"/>\n'
        '</Relationships>'
    )
    doc_rels = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        ' <Relationship Id="rId1" Type="http://schemas.microsoft.com/visio/2010/relationships/pages" Target="pages/pages.xml"/>\n'
        '</Relationships>'
    )
    pages_rels = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        ' <Relationship Id="rId1" Type="http://schemas.microsoft.com/visio/2010/relationships/page" Target="page1.xml"/>\n'
        '</Relationships>'
    )

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("visio/document.xml", document)
        z.writestr("visio/_rels/document.xml.rels", doc_rels)
        z.writestr("visio/pages/pages.xml", pages)
        z.writestr("visio/pages/_rels/pages.xml.rels", pages_rels)
        z.writestr("visio/pages/page1.xml", page1)

# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", help="Markdown outline file")
    ap.add_argument("-o", "--output", help="output base path (no extension)")
    args = ap.parse_args()

    src = Path(args.input)
    base = Path(args.output) if args.output else src.with_suffix("")
    base.parent.mkdir(parents=True, exist_ok=True)

    root = parse_markdown(src.read_text(encoding="utf-8"))
    page_w, page_h = layout(root)
    colors = branch_colors(root)

    drawio_path = base.with_suffix(".drawio")
    vsdx_path = base.with_suffix(".vsdx")
    emit_drawio(root, colors, drawio_path)
    emit_vsdx(root, colors, vsdx_path, page_w, page_h)
    print(f"wrote {drawio_path}")
    print(f"wrote {vsdx_path}")


if __name__ == "__main__":
    main()
