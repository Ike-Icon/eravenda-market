"""Unit tests for the PDF receipt itself (app/receipt_pdf.py). No database or web framework needed:

    cd backend && python -m unittest tests.test_receipt_pdf -v

Text assertions use pypdf when it is installed (it is not a runtime dependency) and are skipped otherwise.
"""
import io
import unittest
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace as NS

from app import receipt_pdf as R

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    PdfReader = None


def _item(name, qty, price, **kw):
    return NS(product_name=name, quantity=qty, unit_price=Decimal(price), line_total=Decimal(price) * qty,
              color=kw.get("color"), size=kw.get("size"), option=kw.get("option"), wholesale_min_quantity=kw.get("min"))


ADDRESS = NS(recipient_name="Kwame Boateng", phone="+233 24 123 4567", area="East Legon", sub_town=None,
             city="Accra", region="Greater Accra", landmark="Near the mall")
STORE = NS(store_name="Adwoa's Fresh Market", sub_town="Madina", city="Accra", region="Greater Accra")


def _build(items, *, fee="25.00", pickup=False, otype="retail", method="mobile_money", provider="paystack",
           pay_status="success", order_status="paid", buyer=None, number="ORD-20261010-ABC123"):
    sub = sum(i.line_total for i in items)
    order = NS(order_number=number, created_at=datetime(2026, 10, 10, 9, 14), items=items, subtotal=sub,
               delivery_fee=Decimal(fee), total_amount=sub + Decimal(fee), is_pickup=pickup, order_type=otype,
               payment_method=method, status=order_status)
    payment = NS(provider=provider, provider_reference="EVM-REF-123", amount=order.total_amount, currency="GHS",
                 status=pay_status, paid_at=datetime(2026, 10, 10, 9, 16), created_at=datetime(2026, 10, 10, 9, 15))
    buyer = buyer or NS(full_name="Kwame Boateng", email="kwame@example.com", phone="+233241234567")
    return R.build_receipt_pdf(order=order, payment=payment, buyer=buyer, store=STORE, address=ADDRESS), order


def _text(pdf: bytes) -> str:
    return "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf)).pages)


class ReceiptPdf(unittest.TestCase):
    def test_produces_a_pdf(self):
        pdf, _ = _build([_item("Tote bag", 2, "85.00")])
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 5000)

    def test_naming(self):
        _, order = _build([_item("A", 1, "1.00")], number="ORD-1/2 3")
        self.assertEqual(R.receipt_number(order), "RCP-ORD-1/2 3")
        self.assertEqual(R.receipt_filename(order), "EraVenda-Receipt-ORD-1-2-3.pdf")  # filename-safe

    def test_money_format(self):
        self.assertEqual(R.money(Decimal("1234.5")), "GHS 1,234.50")
        self.assertEqual(R.money(0), "GHS 0.00")
        self.assertEqual(R.money(None), "GHS 0.00")
        self.assertEqual(R.money("12.345"), "GHS 12.35")  # half-up, not banker's rounding

    def test_every_scenario_builds(self):
        cases = [
            dict(items=[_item("Rice 25kg", 10, "450.00", min=10)], otype="wholesale"),
            dict(items=[_item("Phone case", 1, "35.00", color="Black")], pickup=True, fee="0", method="cash_on_delivery", provider="cash_on_delivery"),
            dict(items=[_item("Blender", 1, "320.00")], pay_status="refunded", order_status="refunded"),
            dict(items=[], fee="0"),  # defensive: an order with no lines still renders
            dict(items=[_item("Tote", 1, "9.99")], buyer=NS(full_name="", email="", phone=None)),  # sparse buyer
        ]
        for case in cases:
            pdf, _ = _build(**case)
            self.assertTrue(pdf.startswith(b"%PDF"), case)

    def test_many_items_flow_onto_extra_pages(self):
        items = [_item(f"Item {i}", 1 + i % 3, "10.25") for i in range(1, 80)]
        pdf, _ = _build(items)
        if PdfReader:
            self.assertGreater(len(PdfReader(io.BytesIO(pdf)).pages), 1)

    def test_markup_in_names_is_escaped_not_interpreted(self):
        pdf, _ = _build([_item("<b>Bold</b> & <script>x</script>", 1, "5.00")])  # must not raise on bad markup
        self.assertTrue(pdf.startswith(b"%PDF"))

    @unittest.skipIf(PdfReader is None, "pypdf not installed")
    def test_content_is_correct(self):
        pdf, order = _build([_item("Kente tote", 2, "85.00", color="Gold"), _item("Shea butter", 1, "60.50")])
        text = _text(pdf)
        for expected in ("PAYMENT RECEIPT", "RCP-ORD-20261010-ABC123", "Kwame Boateng", "kwame@example.com",
                         "Adwoa's Fresh Market", "Kente tote", "Colour: Gold", "GHS 170.00", "GHS 60.50",
                         "GHS 230.50", "GHS 25.00", "GHS 255.50", "TOTAL PAID", "PAID", "EVM-REF-123", "Page 1 of 1"):
            self.assertIn(expected, text)

    @unittest.skipIf(PdfReader is None, "pypdf not installed")
    def test_ghanaian_letters_survive(self):
        buyer = NS(full_name="Akosua Ɛnyonam Ɔwusu", email="a@example.com", phone=None)
        pdf, _ = _build([_item("Kɔkɔɔ powder", 1, "12.00")], buyer=buyer)
        text = _text(pdf)
        self.assertIn("Ɛnyonam", text)
        self.assertIn("Kɔkɔɔ", text)

    @unittest.skipIf(PdfReader is None, "pypdf not installed")
    def test_wholesale_pickup_and_refund_wording(self):
        text = _text(_build([_item("Rice", 10, "450.00", min=10)], otype="wholesale")[0])
        self.assertIn("Wholesale", text); self.assertIn("minimum order 10", text)
        text = _text(_build([_item("Case", 1, "35.00")], pickup=True, fee="0")[0])
        self.assertIn("Pickup", text); self.assertNotIn("DELIVERED TO", text)
        text = _text(_build([_item("Blender", 1, "320.00")], pay_status="refunded", order_status="refunded")[0])
        self.assertIn("REFUNDED", text); self.assertNotIn("TOTAL PAID", text)

    @unittest.skipIf(PdfReader is None, "pypdf not installed")
    def test_internal_commission_is_never_shown(self):
        item = _item("Tote", 1, "100.00")
        item.commission_amount, item.commission_rate = Decimal("7.00"), Decimal("7.00")
        pdf, _ = _build([item])
        self.assertNotIn("ommission", _text(pdf))


if __name__ == "__main__":
    unittest.main()
