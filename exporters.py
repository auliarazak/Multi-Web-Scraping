import json
import pandas as pd
from typing import List, Dict

def export_csv(path: str, rows: List[Dict]):
    if not rows:
        raise ValueError("Tidak ada data untuk diekspor.")
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")

def export_json(path: str, rows: List[Dict]):
    if not rows:
        raise ValueError("Tidak ada data untuk diekspor.")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
