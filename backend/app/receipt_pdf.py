"""
Builds the EraVenda payment receipt as a PDF.

Deliberately framework-free: build_receipt_pdf() only reads attributes from the
objects it is given (an Order, its Payment, the buyer, store and address), so it
can be tested without a database, and the routers decide who may see it and how
it is delivered.

Layout, top to bottom: brand header and receipt number; payment status; who the
receipt is for / where it is going / who sold it; order and payment details; the
itemised table; totals; a short footer note. Long orders flow onto extra pages
with the table header repeated and "Page X of Y" in the footer.

Text uses a bundled DejaVu Sans (app/assets/fonts) rather than the PDF standard
fonts, because those can't draw characters that appear in Ghanaian names (ɛ, ɔ)
or the cedi sign. If the font files are ever missing it falls back to Helvetica
and swaps any character it can't draw for "?", so a receipt still always builds.
"""

from __future__ import annotations

import io
import os
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import BaseDocTemplate, Flowable, Frame, KeepTogether, PageTemplate, Paragraph, Spacer, Table, TableStyle

SITE_NAME = "EraVenda Market"
SITE_URL_TEXT = os.getenv("SITE_URL", "https://eravenda.com").rstrip("/").replace("https://", "").replace("http://", "")
SUPPORT_EMAIL = os.getenv("SUPPORT_EMAIL", "support@eravenda.com")

# Brand colours, matching the site's Tailwind theme and favicon.
BRAND = colors.HexColor("#1c6b4f")
BRAND_DARK = colors.HexColor("#12503a")
BRAND_SOFT = colors.HexColor("#eaf5f0")
BRAND_LINE = colors.HexColor("#cfe9dc")
MARK_GREEN = colors.HexColor("#0F766E")
MARK_GOLD = colors.HexColor("#F59E0B")
INK = colors.HexColor("#24352e")
MUTED = colors.HexColor("#5b6b63")
RULE = colors.HexColor("#d8e5de")
ZEBRA = colors.HexColor("#f6faf8")
REFUND_RED = colors.HexColor("#b42318")
REFUND_SOFT = colors.HexColor("#fdecea")

PAGE_W, PAGE_H = A4
MARGIN_X = 18 * mm
CONTENT_W = PAGE_W - 2 * MARGIN_X

_FONT_DIR = os.path.join(os.path.dirname(__file__), "assets", "fonts")
_FONTS: dict | None = None


def _fonts() -> dict:
    """Register the bundled font once. Returns {'regular', 'bold', 'unicode'}."""
    global _FONTS
    if _FONTS is not None:
        return _FONTS
    regular, bold = os.path.join(_FONT_DIR, "DejaVuSans.ttf"), os.path.join(_FONT_DIR, "DejaVuSans-Bold.ttf")
    try:
        pdfmetrics.registerFont(TTFont("EV", regular))
        pdfmetrics.registerFont(TTFont("EV-Bold", bold))
        pdfmetrics.registerFontFamily("EV", normal="EV", bold="EV-Bold", italic="EV", boldItalic="EV-Bold")
        _FONTS = {"regular": "EV", "bold": "EV-Bold", "unicode": True}
    except Exception:  # missing/corrupt font files: still produce a receipt
        pdfmetrics.registerFontFamily("Helvetica", normal="Helvetica", bold="Helvetica-Bold",
                                      italic="Helvetica-Oblique", boldItalic="Helvetica-BoldOblique")
        _FONTS = {"regular": "Helvetica", "bold": "Helvetica-Bold", "unicode": False}
    return _FONTS


def _txt(value) -> str:
    """Text safe to put in a Paragraph: markup-escaped, and (only in the Helvetica
    fallback) limited to characters that font can draw."""
    text = "" if value is None else str(value)
    if not _fonts()["unicode"]:
        text = text.encode("cp1252", "replace").decode("cp1252")
    return escape(text)


def _val(x):
    """Enum -> its value; anything else unchanged."""
    return getattr(x, "value", x)


def money(value, currency: str = "GHS") -> str:
    try:
        number = Decimal(str(value if value is not None else 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        number = Decimal("0.00")
    return f"{currency} {number:,.2f}"


def fmt_dt(value, with_time: bool = True) -> str:
    """Timestamps are stored as naive UTC, which is Ghana local time year-round (GMT, no DST)."""
    if not isinstance(value, datetime):
        return "—"
    return value.strftime("%d %b %Y, %H:%M GMT" if with_time else "%d %b %Y")


def receipt_number(order) -> str:
    return f"RCP-{order.order_number}"


def receipt_filename(order) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in str(order.order_number))
    return f"EraVenda-Receipt-{safe}.pdf"


def payment_method_label(order, payment) -> str:
    method, provider = str(_val(order.payment_method) or ""), str(payment.provider or "")
    if provider == "cash_on_delivery" or method == "cash_on_delivery":
        return "Cash on delivery"
    if provider.lower() == "paystack":
        return "Mobile Money / Card (Paystack)"
    return provider.replace("_", " ").title() or "Online payment"


# ---------------------------------------------------------------- styles
def _styles() -> dict:
    f = _fonts()
    base = dict(fontName=f["regular"], textColor=INK, fontSize=9, leading=12.5)
    return {
        "body": ParagraphStyle("body", **base),
        "small": ParagraphStyle("small", **{**base, "fontSize": 7.8, "leading": 10.5, "textColor": MUTED}),
        "label": ParagraphStyle("label", **{**base, "fontName": f["bold"], "fontSize": 7.2, "leading": 9.5, "textColor": BRAND, "spaceAfter": 2}),
        "strong": ParagraphStyle("strong", **{**base, "fontName": f["bold"]}),
        "h_title": ParagraphStyle("h_title", **{**base, "fontName": f["bold"], "fontSize": 21, "leading": 24, "textColor": BRAND_DARK, "alignment": TA_RIGHT}),
        "h_sub": ParagraphStyle("h_sub", **{**base, "fontSize": 8.6, "leading": 12, "textColor": MUTED, "alignment": TA_RIGHT}),
        "brand": ParagraphStyle("brand", **{**base, "fontName": f["bold"], "fontSize": 16, "leading": 19, "textColor": BRAND_DARK}),
        "tagline": ParagraphStyle("tagline", **{**base, "fontSize": 7.8, "leading": 10, "textColor": MUTED}),
        "th": ParagraphStyle("th", **{**base, "fontName": f["bold"], "fontSize": 8, "leading": 10, "textColor": colors.white}),
        "th_r": ParagraphStyle("th_r", **{**base, "fontName": f["bold"], "fontSize": 8, "leading": 10, "textColor": colors.white, "alignment": TA_RIGHT}),
        "td": ParagraphStyle("td", **{**base, "fontSize": 8.8, "leading": 11.5}),
        "td_r": ParagraphStyle("td_r", **{**base, "fontSize": 8.8, "leading": 11.5, "alignment": TA_RIGHT}),
        "td_sub": ParagraphStyle("td_sub", **{**base, "fontSize": 7.4, "leading": 9.6, "textColor": MUTED}),
        "tot_l": ParagraphStyle("tot_l", **{**base, "fontSize": 9, "textColor": MUTED}),
        "tot_r": ParagraphStyle("tot_r", **{**base, "fontSize": 9, "alignment": TA_RIGHT}),
        "grand_l": ParagraphStyle("grand_l", **{**base, "fontName": f["bold"], "fontSize": 10.5, "leading": 14, "textColor": colors.white}),
        "grand_r": ParagraphStyle("grand_r", **{**base, "fontName": f["bold"], "fontSize": 12.5, "leading": 15, "textColor": colors.white, "alignment": TA_RIGHT}),
        "note": ParagraphStyle("note", **{**base, "fontSize": 8.2, "leading": 11.8, "textColor": MUTED}),
        "chip": ParagraphStyle("chip", **{**base, "fontName": f["bold"], "fontSize": 8.6, "leading": 11, "alignment": 1}),
    }


# ---------------------------------------------------------------- flowables
class BrandMark(Flowable):
    """The EraVenda mark (rounded green square, gold handle, three white bars), drawn as vector
    from the same shapes as the site's favicon.svg."""

    def __init__(self, size=12 * mm):
        super().__init__()
        self.size, self.width, self.height = size, size, size

    def draw(self):
        c, s = self.canv, self.size / 64.0
        c.setFillColor(MARK_GREEN)
        c.roundRect(0, 0, self.size, self.size, 16 * s, stroke=0, fill=1)

        def pt(x, y):
            return x * s, self.size - y * s
        c.setLineCap(1)
        c.setLineWidth(4.5 * s)
        c.setStrokeColor(MARK_GOLD)
        p = c.beginPath()
        p.moveTo(*pt(24, 21))
        p.curveTo(*pt(24, 14), *pt(40, 14), *pt(40, 21))
        c.drawPath(p, stroke=1, fill=0)
        c.setStrokeColor(colors.white)
        for (x1, y1, x2, y2) in ((21, 29, 43, 29), (21, 37, 36, 37), (21, 45, 43, 45)):
            c.line(*pt(x1, y1), *pt(x2, y2))


class _NumberedCanvas(pdfcanvas.Canvas):
    """Two-pass canvas so every page can say 'Page X of Y' and carry the footer."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_pages = []

    def showPage(self):
        self._saved_pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved_pages)
        for state in self._saved_pages:
            self.__dict__.update(state)
            self._draw_footer(total)
            super().showPage()
        super().save()

    def _draw_footer(self, total):
        f = _fonts()
        self.setStrokeColor(RULE)
        self.setLineWidth(0.6)
        self.line(MARGIN_X, 17 * mm, PAGE_W - MARGIN_X, 17 * mm)
        self.setFont(f["regular"], 7.4)
        self.setFillColor(MUTED)
        self.drawString(MARGIN_X, 12.2 * mm, f"{SITE_NAME}  ·  {SITE_URL_TEXT}  ·  {SUPPORT_EMAIL}")
        self.drawRightString(PAGE_W - MARGIN_X, 12.2 * mm, f"Page {self._pageNumber} of {total}")


# ---------------------------------------------------------------- building blocks
def _address_lines(address) -> list[str]:
    if address is None:
        return []
    lines = []
    for attr in ("recipient_name", "phone"):
        v = getattr(address, attr, None)
        if v:
            lines.append(str(v))
    place = ", ".join(str(getattr(address, a)) for a in ("area", "sub_town", "city", "region") if getattr(address, a, None))
    if place:
        lines.append(place)
    if getattr(address, "landmark", None):
        lines.append(f"Landmark: {address.landmark}")
    return lines


def _store_place(store) -> str:
    if store is None:
        return ""
    return ", ".join(str(getattr(store, a)) for a in ("sub_town", "city", "region") if getattr(store, a, None))


def _fit(text, style: ParagraphStyle, max_w: float, min_size: float = 6.4) -> Paragraph:
    """One-line Paragraph that shrinks its font until `text` fits in max_w, so emails, references and
    order numbers stay on a single line instead of splitting mid-word. Below min_size it wraps as usual."""
    size = style.fontSize
    raw = "" if text is None else str(text)
    if not _fonts()["unicode"]:
        raw = raw.encode("cp1252", "replace").decode("cp1252")
    while size > min_size and pdfmetrics.stringWidth(raw, style.fontName, size) > max_w:
        size -= 0.2
    if size != style.fontSize:
        style = ParagraphStyle(f"{style.name}-fit", parent=style, fontSize=size, leading=size * 1.35)
    return Paragraph(escape(raw), style)


def _block(label: str, lines: list[str], st, max_w: float) -> list:
    out = [Paragraph(_txt(label.upper()), st["label"])]
    for i, line in enumerate([ln for ln in lines if ln] or ["—"]):
        # Name/address text may wrap; single-token lines (email, phone) are fitted to one line.
        wrap_ok = i == 0 or " " in str(line)
        out.append(Paragraph(_txt(line), st["strong"] if i == 0 else st["body"]) if wrap_ok else _fit(line, st["body"], max_w))
    return out


def _chip(text: str, fg, bg, st, width=34 * mm) -> Table:
    t = Table([[Paragraph(f'<font color="{fg.hexval().replace("0x", "#")}">{_txt(text)}</font>', st["chip"])]], colWidths=[width])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg), ("ROUNDEDCORNERS", [8, 8, 8, 8]),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("BOX", (0, 0), (-1, -1), 0.8, fg),
    ]))
    t.hAlign = "RIGHT"
    return t


def _item_cell(item, st, wholesale_order: bool) -> list:
    parts = [Paragraph(_txt(item.product_name), st["td"])]
    details = []
    for label, attr in (("Colour", "color"), ("Size", "size"), ("Option", "option")):
        v = getattr(item, attr, None)
        if v:
            details.append(f"{label}: {v}")
    minimum = getattr(item, "wholesale_min_quantity", None)
    if wholesale_order and minimum:
        details.append(f"Wholesale · minimum order {minimum}")
    if details:
        parts.append(Paragraph(_txt("  ·  ".join(details)), st["td_sub"]))
    return parts


def build_receipt_pdf(*, order, payment, buyer, store, address) -> bytes:
    """Render the receipt for one paid order and return the PDF bytes."""
    st = _styles()
    currency = (payment.currency or "GHS") if payment is not None else "GHS"
    pay_status = str(_val(payment.status)) if payment is not None else "success"
    order_status = str(_val(order.status))
    refunded = pay_status == "refunded" or order_status == "refunded"
    wholesale = str(getattr(order, "order_type", "retail") or "retail") == "wholesale"
    paid_at = (payment.paid_at or payment.created_at) if payment is not None else None

    buf = io.BytesIO()
    doc = BaseDocTemplate(
        buf, pagesize=A4, leftMargin=MARGIN_X, rightMargin=MARGIN_X, topMargin=16 * mm, bottomMargin=24 * mm,
        title=f"Receipt {receipt_number(order)}", author=SITE_NAME,
        subject=f"Payment receipt for order {order.order_number}", creator=SITE_NAME,
    )
    doc.addPageTemplates([PageTemplate(id="main", frames=[Frame(MARGIN_X, 24 * mm, CONTENT_W, PAGE_H - 40 * mm, id="body",
                                                                 leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)])])
    story: list = []

    # ---- header: brand left, receipt title right
    brand = Table([[BrandMark(13 * mm), [Paragraph(_txt(SITE_NAME), st["brand"]), Paragraph("Ghana's local marketplace", st["tagline"])]]],
                  colWidths=[16 * mm, 70 * mm])
    brand.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    title = [Paragraph("PAYMENT RECEIPT", st["h_title"]),
             Paragraph(f"Receipt no. {_txt(receipt_number(order))}", st["h_sub"]),
             Paragraph(f"Issued {_txt(fmt_dt(paid_at or order.created_at, with_time=False))}", st["h_sub"])]
    header = Table([[brand, title]], colWidths=[CONTENT_W * 0.5, CONTENT_W * 0.5])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    story += [header, Spacer(1, 5 * mm)]
    rule = Table([[""]], colWidths=[CONTENT_W], rowHeights=[1.6])
    rule.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), BRAND), ("LINEBELOW", (0, 0), (-1, -1), 0, colors.white)]))
    story += [rule, Spacer(1, 5 * mm)]

    # ---- status band
    if refunded:
        chip = _chip("REFUNDED", REFUND_RED, REFUND_SOFT, st)
        status_text = "This payment has been refunded."
    else:
        chip = _chip("PAID", BRAND_DARK, BRAND_SOFT, st)
        status_text = f"Payment of <b>{_txt(money(payment.amount if payment is not None else order.total_amount, currency))}</b> received. Thank you!"
    band = Table([[Paragraph(status_text, st["body"]), chip]], colWidths=[CONTENT_W - 40 * mm, 40 * mm])
    band.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                              ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    story += [band, Spacer(1, 6 * mm)]

    # ---- three parties
    gutter = 4 * mm
    widths = [CONTENT_W * 0.39, CONTENT_W * 0.35, CONTENT_W * 0.26]
    fit_w = [w - gutter for w in widths]
    billed = _block("Billed to", [getattr(buyer, "full_name", "") or "Customer", getattr(buyer, "email", "") or "", getattr(buyer, "phone", "") or ""], st, fit_w[0])
    if order.is_pickup:
        ship_lines = ["Pickup from the seller", "No delivery was charged"]
        if _store_place(store):
            ship_lines.append(_store_place(store))
        ship = _block("Collection", ship_lines, st, fit_w[1])
    else:
        ship = _block("Delivered to", _address_lines(address), st, fit_w[1])
    sold = _block("Sold by", [getattr(store, "store_name", "") or "Seller", _store_place(store)], st, fit_w[2])
    parties = Table([[billed, ship, sold]], colWidths=widths)
    parties.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), gutter),
                                 ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    story += [parties, Spacer(1, 6 * mm)]

    # ---- order + payment facts
    def fact(label, value):
        return [Paragraph(_txt(label.upper()), st["label"]), _fit(value, st["body"], CONTENT_W / 3 - 18)]
    facts_rows = [
        [fact("Order number", order.order_number), fact("Order date", fmt_dt(order.created_at)), fact("Order type", "Wholesale" if wholesale else "Retail")],
        [fact("Payment date", fmt_dt(paid_at)), fact("Payment method", payment_method_label(order, payment) if payment is not None else "—"),
         fact("Payment reference", (payment.provider_reference if payment is not None else "") or "—")],
    ]
    facts = Table(facts_rows, colWidths=[CONTENT_W / 3] * 3)
    facts.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BRAND_SOFT), ("ROUNDEDCORNERS", [6, 6, 6, 6]), ("BOX", (0, 0), (-1, -1), 0.6, BRAND_LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story += [facts, Spacer(1, 7 * mm)]

    # ---- items
    qty_w, unit_w, amt_w, no_w = 14 * mm, 30 * mm, 32 * mm, 9 * mm
    item_w = CONTENT_W - qty_w - unit_w - amt_w - no_w
    rows = [[Paragraph("#", st["th"]), Paragraph("ITEM", st["th"]), Paragraph("QTY", st["th_r"]),
             Paragraph("UNIT PRICE", st["th_r"]), Paragraph("AMOUNT", st["th_r"])]]
    for n, item in enumerate(order.items, start=1):
        rows.append([Paragraph(str(n), st["td"]), _item_cell(item, st, wholesale), Paragraph(str(int(item.quantity)), st["td_r"]),
                     Paragraph(_txt(money(item.unit_price, currency)), st["td_r"]), Paragraph(_txt(money(item.line_total, currency)), st["td_r"])])
    if len(rows) == 1:
        rows.append([Paragraph("", st["td"]), Paragraph("No items", st["td_sub"]), "", "", ""])
    items = Table(rows, colWidths=[no_w, item_w, qty_w, unit_w, amt_w], repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), BRAND), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, 0), 6), ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING", (0, 1), (-1, -1), 7), ("BOTTOMPADDING", (0, 1), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("LINEBELOW", (0, 1), (-1, -1), 0.5, RULE), ("LINEBELOW", (0, -1), (-1, -1), 0.8, BRAND_LINE),
    ]
    for r in range(2, len(rows), 2):
        style.append(("BACKGROUND", (0, r), (-1, r), ZEBRA))
    items.setStyle(TableStyle(style))
    story += [items, Spacer(1, 5 * mm)]

    # ---- totals (kept together so the total never lands alone on a new page)
    paid_amount = payment.amount if payment is not None else order.total_amount
    delivery_text = "Pickup — no delivery fee" if order.is_pickup else money(order.delivery_fee, currency)
    tot_w = 82 * mm
    totals = Table([
        [Paragraph("Subtotal", st["tot_l"]), Paragraph(_txt(money(order.subtotal, currency)), st["tot_r"])],
        [Paragraph("Delivery fee", st["tot_l"]), Paragraph(_txt(delivery_text), st["tot_r"])],
    ], colWidths=[tot_w * 0.45, tot_w * 0.55])
    totals.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                                ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3), ("LINEBELOW", (0, -1), (-1, -1), 0.6, RULE)]))
    grand = Table([[Paragraph("REFUNDED" if refunded else "TOTAL PAID", st["grand_l"]), Paragraph(_txt(money(paid_amount, currency)), st["grand_r"])]],
                  colWidths=[tot_w * 0.4, tot_w * 0.6])
    grand.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), REFUND_RED if refunded else BRAND), ("ROUNDEDCORNERS", [6, 6, 6, 6]),
                               ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                               ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    stack = Table([[totals], [Spacer(1, 2)], [grand]], colWidths=[tot_w])
    stack.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    stack.hAlign = "RIGHT"
    note = [
        Paragraph("Thank you for shopping on EraVenda Market.", st["strong"]),
        Spacer(1, 2),
        Paragraph("This receipt confirms that EraVenda Market received your payment for the order above, on behalf of the seller. "
                  "It is generated by computer and is valid without a signature.", st["note"]),
        Spacer(1, 2),
        Paragraph(f"Questions about this order? Reply to the email it came with, or contact {_txt(SUPPORT_EMAIL)} and quote "
                  f"order <b>{_txt(order.order_number)}</b>.", st["note"]),
    ]
    closing = Table([[note, stack]], colWidths=[CONTENT_W - tot_w - 8 * mm, tot_w + 8 * mm])
    closing.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (0, 0), 0), ("RIGHTPADDING", (0, 0), (0, 0), 8 * mm),
                                 ("LEFTPADDING", (1, 0), (1, 0), 8 * mm), ("RIGHTPADDING", (1, 0), (1, 0), 0),
                                 ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    story.append(KeepTogether([closing]))

    doc.build(story, canvasmaker=_NumberedCanvas)
    return buf.getvalue()
