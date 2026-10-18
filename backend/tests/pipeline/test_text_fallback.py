import unittest

from backend.app.pipeline.text_fallback import infer_category, infer_fields, itemization


def ocr(*lines):
    return {"lines": [{"text": line} for line in lines], "full_text": "\n".join(lines)}


class TextFallbackTests(unittest.TestCase):
    def test_category_from_venue_words(self):
        self.assertEqual(infer_category("Harbor Bistro\nRESTAURANT RECEIPT"), "MEALS")
        self.assertEqual(infer_category("Grand Hotel\nHOTEL FOLIO\nRoom charge"), "LODGING")
        self.assertEqual(infer_category("City Cab\nTAXI TRIP RECEIPT\nTrip fare"), "TRAVEL")
        self.assertEqual(infer_category("Star Cinema\nShow tickets x2\nPopcorn meal"), "ENTERTAINMENT")
        self.assertEqual(infer_category("Merchant 12\n20.00"), "")

    def test_city_guests_and_item_classes(self):
        reader_a = {"currency": "MYR", "subtotal": "20.00", "total": "20.00",
                    "line_items": [{"description": "Food", "amount": "15.00", "item_class": "FOOD"},
                                   {"description": "Craft Beer", "amount": "5.00", "item_class": "OTHER"}]}
        found = infer_fields(ocr("Kuala Lumpur, MY", "Party size: 3", "Food 15.00"), reader_a)
        self.assertEqual((found["city"], found["country"], found["guest_count"]),
                         ("Kuala Lumpur", "MY", 3))
        self.assertEqual([item["item_class"] for item in found["line_items"]], ["FOOD", "ALCOHOL"])
        self.assertEqual(found["itemization"], "FULL")

    def test_itemization_requires_lines_to_add_up(self):
        items = [{"description": "A", "amount": "10.00"}, {"description": "B", "amount": "5.00"}]
        self.assertEqual(itemization(items, {"subtotal": "15.00"}), "FULL")
        self.assertEqual(itemization(items, {"subtotal": "16.00"}), "")
        self.assertEqual(itemization(items, {"total": "17.50", "tax": "1.50", "tip": "1.00"}), "FULL")
        self.assertEqual(itemization([], {"subtotal": "15.00"}), "")
        self.assertEqual(itemization([{"description": "A", "amount": "x"}], {"subtotal": "1.00"}), "")


class PolicyCallbackTests(unittest.TestCase):
    def test_compiler_callback_posts_policy_and_requires_endpoint(self):
        import io
        import json
        import os
        from unittest.mock import patch

        from backend.app.llm.client import compile_policy_text

        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                compile_policy_text("1.1 Meals are capped.")
        answer = {"sentences": [{"clause_id": "1.1", "text": "Meals are capped.", "kind": "rule"}], "rules": []}
        with patch.dict(os.environ, {"RECEIPT_LLM_ENDPOINT": "http://model.test"}, clear=True),                 patch("backend.app.llm.client.urlopen",
                      return_value=io.BytesIO(json.dumps(answer).encode())) as post:
            self.assertEqual(compile_policy_text("1.1 Meals are capped.", 0.7, 5), answer)
        sent = json.loads(post.call_args.args[0].data)
        self.assertEqual((sent["policy_text"], sent["temperature"]), ("1.1 Meals are capped.", 0.7))


if __name__ == "__main__":
    unittest.main()
