import re
import random
import string
from datetime import datetime


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def random_suffix(length: int = 5) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


def generate_order_number() -> str:
    today = datetime.utcnow().strftime("%Y%m%d")
    return f"ORD-{today}-{random_suffix(6).upper()}"
