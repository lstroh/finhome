"""
Applies CATEGORY_RULES to a transaction description and returns a category.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from rules.categories import CATEGORY_RULES


def categorise(description: str) -> str:
    desc_upper = description.upper()
    for category, keywords in CATEGORY_RULES.items():
        for kw in keywords:
            if kw in desc_upper:
                return category
    return "Uncategorised"
