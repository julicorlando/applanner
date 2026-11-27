"""Reads the clinic's legacy Word patient sheets ("Ficha clínica e ortodôntica").

Pure standard library so it can run anywhere. Each sheet has:
- a header box: Paciente, Data de Nascimento, Cidade, Estado, Telefone;
- an "Orçamentos/Procedimentos | Observações" box with free text;
- a table of visits: Data | Procedimento Clínico | Valor recebido | Valor pago | Profissional,
  split by a "TRATAMENTO ORTODÔNTICO" row into clinical and orthodontic sections.
Rows without a date belong to the last dated row above them (same visit).
Nothing is dropped: anything that cannot be placed is reported and kept as text.
"""
import io
import re
import unicodedata
import zipfile
from datetime import date
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
DATE = re.compile(r"(?<!\d)(\d{1,2})\s*[/.\-]+\s*(\d{1,2})\s*[/.\-]+\s*(\d{4}|\d{2})(?!\d)")
MONTH = re.compile(r"^\s*(\d{1,2})\s*/\s*(\d{4})\s*$")
PHONE = re.compile(r"\(?\s*(\d{2})\s*\)?\s*(9?\s*\d{4})\s*-?\s*(\d{4})")
TEMPLATE_MARK = "PARA EDITAR"
MAX_FILES = 2000
MAX_XML = 5_000_000


def nfc(value):
    return unicodedata.normalize("NFC", value or "")


def fold(value):
    """Accent/case-insensitive key used to match a sheet with an existing patient."""
    value = unicodedata.normalize("NFKD", nfc(value)).encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", value).split())


def _text(paragraph):
    out = []
    for node in paragraph.iter():
        if node.tag == W + "t":
            out.append(node.text or "")
        elif node.tag == W + "tab":
            out.append("\t")
        elif node.tag in (W + "br", W + "cr"):
            out.append("\n")
    return "".join(out)


def _cell(tc):
    return nfc("\n".join(_text(p) for p in tc.findall(W + "p")).strip())


def read_tables(document_xml):
    root = ET.fromstring(document_xml)
    # Text boxes are stored twice (DrawingML + VML fallback); keep one copy.
    for parent in root.iter():
        for child in list(parent):
            if child.tag == MC + "Fallback":
                parent.remove(child)
    tables, inside = [], set()
    for tbl in root.iter(W + "tbl"):
        if id(tbl) in inside:
            continue
        for node in tbl.iter():
            if node is not tbl:
                inside.add(id(node))
        tables.append([[_cell(tc) for tc in tr.findall(W + "tc")] for tr in tbl.findall(W + "tr")])
    loose = [nfc(_text(p)).strip() for p in root.iter(W + "p") if id(p) not in inside]
    return tables, [x for x in loose if x]


def parse_date(value, issues=None, context=""):
    match = DATE.search(value or "")
    if not match:
        return None
    day, month, year = (int(x) for x in match.groups())
    if year < 100:
        year += 2000 if year <= 40 else 1900
    try:
        return date(year, month, day)
    except ValueError:
        if issues is not None:
            issues.append(f"Data inválida “{match.group(0)}” em {context}; mantida no texto.")
        return None


def _after(label, text):
    match = re.search(re.escape(label) + r"\s*:?\s*(.*)", text, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else ""


def parse_header(rows, issues):
    cells = [c for row in rows for c in row]
    joined = "\n".join(cells)
    name = state = city = phone_raw = birth_raw = documentation = ""
    for cell in cells:
        if cell.lower().startswith("paciente"):
            name = _after("Paciente", cell)
        elif "nascimento" in cell.lower():
            birth_raw = _after("Data de Nascimento", cell)
        elif cell.lower().startswith("cidade"):
            city_part, _, state_part = cell.partition("Estado")
            city = _after("Cidade", city_part)
            state = state_part.lstrip(": ").strip()
        elif cell.lower().startswith("telefone"):
            phone_raw = _after("Telefone", cell)
        elif fold(cell).startswith("documentacao digital"):
            marks = re.findall(r"\[\s*([xX✓]?)\s*\]\s*(SIM|NÃO|NAO)", cell, re.I)
            chosen = [label for mark, label in marks if mark]
            documentation = f"Documentação digital: {chosen[0].capitalize() if chosen else 'não marcada'}"
    name = " ".join(name.split())
    city = " ".join(city.split())
    birth = parse_date(birth_raw, issues, "data de nascimento")
    if birth_raw and not birth:
        issues.append(f"Data de nascimento incompleta na ficha (“{birth_raw}”); guardada na observação.")
    phones = ["55" + "".join(m.groups()).replace(" ", "") for m in PHONE.finditer(phone_raw)]
    phones = [p for p in phones if len(p) in (12, 13)]
    phone_note = " ".join(phone_raw.split())
    return {"name": name, "birth_date": birth.isoformat() if birth else "", "birth_raw": birth_raw,
            "city": city, "state": state.upper()[:2] if re.fullmatch(r"[A-Za-z]{2}", state) else "",
            "state_raw": state, "phone": phones[0] if phones else "", "phone_raw": phone_note,
            "header_text": joined, "documentation": documentation}


def _money(value):
    value = " ".join((value or "").split())
    return "" if value in {"", "-", "–", "—"} else value


STANDARD_HEADER = ["Data", "Procedimento Clínico", "Valor recebido", "Valor pago", "Profissional"]


def _column(label):
    key = fold(label)
    if key.startswith("procedimento"):
        return "procedure", ""
    if "recebido" in key:
        return "money", "Valor recebido"
    if key.startswith("valor pago"):
        return "money", "Valor pago"
    if key.startswith("valor"):
        return "money", "Valor do procedimento"
    if key.startswith("profissional"):
        return "text", "Profissional"
    if key.startswith("prox"):
        return "text", "Próx. consulta"
    return "text", " ".join(label.split())


def entry_line(row, header=None, date_note=""):
    mapped = header is not None
    header = header or STANDARD_HEADER
    procedure, parts, has_professional = "", [], False
    for index, label in enumerate(header[1:], start=1):
        raw = row[index] if index < len(row) else ""
        # Header-mapped sheets keep each typed line apart and treat "--" as empty.
        value = " / ".join(" ".join(x.split()) for x in raw.splitlines() if x.strip()) if mapped else " ".join(raw.split())
        if mapped and value in {"--", "---"}:
            value = ""
        kind, title = _column(label)
        has_professional = has_professional or title == "Profissional"
        if kind == "procedure":
            procedure = value
        elif kind == "money":
            if _money(value):
                parts.append(f"{title}: R$ {_money(value)}")
        elif value:
            parts.append(f"{title}: {value}")
    if date_note:
        parts.append(f"{'Obs.' if has_professional else 'Profissional'}: {date_note}")
    return " · ".join(p for p in [procedure] + parts if p)


def _is_header(row):
    return len(row) > 1 and fold(row[0]).startswith("data") and fold(row[1]).startswith("procedimento")


def parse_visits(rows, issues, header=None, orthodontic_only=False):
    visits, current = {}, None
    section = "orthodontic" if orthodontic_only else "procedure"
    for row in rows:
        if not any(c.strip() for c in row):
            continue
        first = fold(row[0])
        if len(row) == 1 or ("tratamento" in first and "ortod" in first):
            section, current = "orthodontic", None
            continue
        if _is_header(row) or fold(" ".join(row[:2])) == "data procedimento clinico":
            header = row if (header is not None and _is_header(row)) else header
            continue
        when = parse_date(row[0], issues, "a tabela de atendimentos")
        month = MONTH.match(row[0]) if not when else None
        if month and 1 <= int(month.group(1)) <= 12:
            # Only month/year on the sheet: filed on the 1st of that month, original text kept.
            when = date(int(month.group(2)), int(month.group(1)), 1)
            current = when
            line = f"[Data na ficha: {row[0].strip()}] " + entry_line(row, header)
            visits.setdefault(when.isoformat(), {"procedure": [], "orthodontic": []})[section].append(line)
            continue
        if row[0].strip() and not when:
            # "A realizar", "xx/xx/2024", "--": not a visit date; kept apart as undated items.
            issues.append(f"Linha sem data válida “{row[0].strip()}”; guardada como item sem data da ficha.")
            line = f"[{row[0].strip()}] {entry_line(row, header)}"
            visits.setdefault("", {"procedure": [], "orthodontic": []})[section].append(line)
            continue
        if when:
            current = when
        rest = [c for c in row[1:] if c.strip()]
        date_note = ""
        if when:
            date_note = " ".join(DATE.sub("", row[0], count=1).split())
        if not rest and when and not date_note:
            if orthodontic_only:
                visits.setdefault(when.isoformat(), {"procedure": [], "orthodontic": []})[section].append(
                    "Consulta registrada na ficha, sem procedimento descrito.")
            continue
        line = entry_line(row, header, date_note)
        if row[0].strip() and not when:
            line = f"[{row[0].strip()}] {line}"
        key = current.isoformat() if current else ""
        if not current:
            issues.append(f"Procedimento sem data antes do primeiro atendimento: “{line}”.")
        visits.setdefault(key, {"procedure": [], "orthodontic": []})[section].append(line)
    return visits


def split_budgets(text):
    """'Orçamentos/Procedimentos' text → {iso_date or '': text}, keeping every line."""
    blocks, current = {}, ""
    for line in text.splitlines():
        stripped = line.strip()
        lead = DATE.match(stripped)
        when = parse_date(lead.group(0)) if lead else None
        if when:
            current = when.isoformat()
            blocks.setdefault(current, [])
            rest = stripped[lead.end():].strip(" :-–")
            if rest:
                blocks[current].append(rest)
            continue
        if stripped:
            blocks.setdefault(current, []).append(stripped)
    return {k: "\n".join(v) for k, v in blocks.items() if v}


def parse_sheet(filename, document_xml, folder=""):
    issues = []
    tables, loose = read_tables(document_xml)
    header, budgets_text, observations_text, visit_rows = None, [], [], []
    clinical_notes, visit_header, orthodontic_only, appliance = [], None, False, []
    for table in tables:
        flat = "\n".join(c for row in table for c in row)
        header_row = next((i for i, row in enumerate(table) if _is_header(row)), None)
        if header is None and "Paciente" in flat and ("Telefone" in flat or "Nascimento" in flat):
            header = parse_header(table, issues)
        elif table and table[0] and fold(table[0][0]).startswith("observacoes"):
            # "Observações Clínicas" box: dated lines become notes on their own dates.
            clinical_notes.append(re.sub(r"^\s*Observações Clínicas\s*", "", "\n".join(c for row in table for c in row)))
        elif header_row is not None and not (table[0] and fold(table[0][0]) == "data" and header_row == 0
                                             and [fold(c) for c in table[0]] == [fold(c) for c in STANDARD_HEADER]):
            # Header-mapped visit table (orthodontic sheets, sheets without "Profissional").
            for row in table[:header_row]:
                text = " · ".join(" ".join(c.split()) for c in row if c.strip())
                if text:
                    appliance.append(text)
            visit_header = table[header_row]
            orthodontic_only = not any(fold(c).startswith("valor") for c in visit_header)
            visit_rows.extend(table[header_row + 1:])
        elif table and table[0] and fold(table[0][0]).startswith("orcamentos"):
            # Left cell: budgets; right cell: observations. The word "Observações" can drift into
            # the left cell when the sheet was typed; split on it.
            cells = [c for row in table for c in row]
            left = cells[0] if cells else ""
            right = "\n".join(cells[1:])
            for chunk in (left, right):
                body = re.sub(r"^\s*Orçamentos/Procedimentos\s*", "", chunk)
                if "Observações" in body:
                    before, _, after = body.partition("Observações")
                    budgets_text.append(before)
                    observations_text.append(after)
                elif chunk is left:
                    budgets_text.append(body)
                else:
                    # Text in the right cell is either the budget continuation or the observations.
                    (observations_text if re.match(r"^\s*Observações", chunk) else budgets_text).append(body)
        elif table and table[0] and fold(table[0][0]) == "data":
            visit_rows.extend(table[1:])
        else:
            text = "\n".join(c for row in table for c in row if c.strip())
            if text:
                observations_text.append(text)
                issues.append("Quadro fora do modelo guardado como observação.")
    if not header or not header["name"]:
        has_content = any(c.strip() for row in visit_rows for c in row) or any(x.strip() for x in budgets_text + clinical_notes + observations_text)
        if not has_content:
            return {"file": filename, "skip": True, "issues": ["Ficha em branco (sem nome e sem atendimentos); não importada."]}
        # Name missing inside the sheet: use the file name.
        stem_name = re.sub(r"\.docx$|\s*\(.*\)|\s+-\s+.*$|^\d{4}-\d{2}-", "", filename, flags=re.IGNORECASE).strip()
        header = (header or {"birth_date": "", "birth_raw": "", "city": "", "state": "", "state_raw": "", "phone": "", "phone_raw": ""}) | {"name": stem_name}
        issues.append("Nome do paciente vazio na ficha; usado o nome do arquivo.")
    stem = re.sub(r"\.docx$", "", filename, flags=re.IGNORECASE).strip()
    name = header["name"]
    # Remarks typed after the name ("Maria de Fátima da Silva - protocolo") stay as an observation.
    name_note = ""
    if " - " in name:
        name, _, name_note = name.partition(" - ")
    paren = re.search(r"\s*\(([^)]*)\)\s*$", name)
    if paren:
        name, name_note = name[:paren.start()], (name_note + " " + paren.group(1)).strip()
    file_note = stem.partition(" - ")[2].replace("_", "/") if " - " in stem else ""
    notes = []
    for item in (name_note, file_note):
        if item.strip() and item.strip().lower() not in {n.lower() for n in notes}:
            notes.append(item.strip())
    observations = "\n".join(x.strip() for x in observations_text if x.strip())
    extra = []
    if header["birth_raw"] and not header["birth_date"]:
        extra.append(f"Data de nascimento na ficha: {header['birth_raw']}")
    if header["phone_raw"] and (re.sub(r"[\d()\s-]", "", header["phone_raw"]) or len(PHONE.findall(header["phone_raw"])) != 1):
        extra.append(f"Telefone na ficha: {header['phone_raw']}")
    if header["state_raw"] and not header["state"]:
        extra.append(f"Estado na ficha: {header['state_raw']}")
    if header.get("documentation"):
        extra.append(header["documentation"])
    if appliance:
        extra.append("Aparelho/tratamento: " + "; ".join(appliance))
    if folder:
        extra.append(f"Pasta da ficha: {folder}")
    if loose:
        extra.append("\n".join(loose))
    return {
        "file": filename, "skip": False, "name": " ".join(name.split()), "key": fold(name),
        "birth_date": header["birth_date"], "phone": header["phone"], "city": header["city"], "state": header["state"],
        "visits": parse_visits(visit_rows, issues, visit_header, orthodontic_only),
        "clinical_notes": split_budgets("\n".join(clinical_notes)),
        "budgets": split_budgets("\n".join(budgets_text)),
        "observations": observations, "remarks": notes, "sheet_details": extra, "issues": issues,
    }


def read_upload(name, data):
    """Accepts one .docx or a .zip of .docx files. Returns (sheets, problems)."""
    sheets, problems = [], []

    def docx(path, payload):
        path = nfc(re.sub(r"#U([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), path))
        parts = [x for x in path.split("/") if x]
        filename = parts[-1] if parts else path
        # Subfolders below the top folder carry the treatment status ("Pacientes com TTO em Andamento").
        folder = " / ".join(parts[:-1]) if len(parts) > 2 else ""
        if TEMPLATE_MARK in filename.upper():
            return
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                info = archive.getinfo("word/document.xml")
                if info.file_size > MAX_XML:
                    raise ValueError("documento muito grande")
                sheets.append(parse_sheet(filename, archive.read(info), folder))
        except (KeyError, ValueError, zipfile.BadZipFile, ET.ParseError) as exc:
            problems.append(f"{filename}: não foi possível ler ({exc}).")

    if name.lower().endswith(".docx"):
        docx(name, data)
    else:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = [i for i in archive.infolist() if i.filename.lower().endswith(".docx") and not i.is_dir()
                       and "__MACOSX" not in i.filename and not i.filename.rsplit("/", 1)[-1].startswith("~")]
            if len(members) > MAX_FILES:
                raise ValueError(f"Envie no máximo {MAX_FILES} fichas por vez.")
            for info in members:
                name = info.filename
                if not info.flag_bits & 0x800:
                    # Windows zips store names in the OEM code page (cp850 for Portuguese).
                    try:
                        name = name.encode("cp437").decode("cp850")
                    except UnicodeError:
                        pass
                docx(name, archive.read(info))
    separate_homonyms(sheets)
    sheets.sort(key=lambda s: fold(s.get("name") or s["file"]))
    return sheets, problems


def same_person(birth_a, birth_b):
    """Same name is the same patient unless both birth dates exist with different years."""
    return not (birth_a and birth_b and str(birth_a)[:4] != str(birth_b)[:4])


def separate_homonyms(sheets):
    groups = {}
    for sheet in sheets:
        if not sheet.get("skip"):
            groups.setdefault(sheet["key"], []).append(sheet)
    for key, group in groups.items():
        births = {s["birth_date"] for s in group if s["birth_date"]}
        if len(births) <= 1:
            continue
        clusters = []
        for sheet in group:
            target = next((c for c in clusters if same_person(c[0]["birth_date"], sheet["birth_date"])), None)
            (target.append(sheet) if target else clusters.append([sheet]))
        for cluster in clusters:
            for sheet in cluster:
                others = sorted(b for b in births if b != sheet["birth_date"])
                if len(clusters) > 1:
                    sheet["key"] = f"{key}#{cluster[0]['birth_date'] or 'sem-data'}"
                    sheet["issues"].append(f"Outra ficha com o mesmo nome e nascimento diferente ({', '.join(others)}): cadastrados como pacientes diferentes.")
                else:
                    sheet["issues"].append(f"Outra ficha deste paciente tem outro nascimento ({', '.join(others)}); juntadas no mesmo paciente. Confira o cadastro.")
