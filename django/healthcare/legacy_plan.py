"""Plano de tratamento salvo antes da tabela de itens (nota do prontuário com a chave "plan")."""
import json
import re
from decimal import Decimal, InvalidOperation

LINE = re.compile(r"^\d+\.\s+(?:Dente\s+(?P<tooth>.+?)\s+·\s+)?(?P<procedure>.+?)\s+·\s+R\$\s*(?P<price>[\d.]+,\d{2})$")


def parse(raw):
    """Items of a legacy plan note, or None when the note is not a plan."""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict) or not str(data.get("plan") or "").strip():
        return None
    items = []
    if isinstance(data.get("plan_items"), list):
        for row in data["plan_items"]:
            try:
                items.append({"tooth": str(row.get("tooth") or "")[:20], "procedure": " ".join(str(row["procedure"]).split())[:200],
                              "price": Decimal(str(row.get("price") or "0")).quantize(Decimal("0.01"))})
            except (KeyError, TypeError, AttributeError, InvalidOperation):
                continue
        return [i for i in items if i["procedure"]]
    for line in str(data["plan"]).splitlines():
        match = LINE.match(line.strip())
        if match:
            items.append({"tooth": (match["tooth"] or "").strip()[:20], "procedure": match["procedure"].strip()[:200],
                          "price": Decimal(match["price"].replace(".", "").replace(",", "."))})
    return items
