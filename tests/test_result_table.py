import ast
import unittest
from pathlib import Path

from qml_prototype.result_table import SCHEMAS, columns_for, visible_rows


class ResultTableTests(unittest.TestCase):
    def test_all_column_keys_and_order_match_archived_ui(self):
        path = Path(__file__).resolve().parents[1] / "app.py"
        schemas = next(ast.literal_eval(node.value) for node in ast.parse(path.read_bytes()).body
                       if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                       and node.targets[0].id == "SCHEMAS")
        self.assertEqual(set(SCHEMAS), set(schemas))
        for source, keys in schemas.items():
            self.assertEqual([col["key"] for col in columns_for(source)], keys)

    def test_filter_searches_visible_fields_only(self):
        row = {"title": "Paper", "abstract": "Tentang visi komputer", "shop_name": "hidden"}
        self.assertEqual(visible_rows([row], "Google Research", "VISI", "", False), [row])
        self.assertEqual(visible_rows([row], "Google Research", "hidden", "", False), [])

    def test_sort_by_value_preserves_missing_values_at_end(self):
        cases = [
            ("Tokopedia", "harga", ["Rp950", "Rp12.500", "Rp1.000.000"]),
            ("Google Reviews", "rating", ["3,9", "4.2", "4,8"]),
            ("Lazada", "sold", ["850 terjual", "1,2 rb", "2K+"]),
            ("News", "published", ["Tue, 03 Nov 2026 10:00:00 +0700", "2026-11-05T13:00:00Z"]),
        ]
        for source, key, values in cases:
            with self.subTest(key=key):
                rows = [{key: value} for value in ["-", *reversed(values)]]
                for desc in (False, True):
                    result = visible_rows(rows, source, "", key, desc)
                    expected = list(reversed(values)) if desc else values
                    self.assertEqual([r[key] for r in result], [*expected, "-"])
