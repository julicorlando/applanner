"""Create a value-free inventory from a phpMyAdmin MySQL dump.

Usage: python django/scripts/legacy_dump_inventory.py dump.sql docs/legacy-schema.csv
The output contains schema names and approximate INSERT row counts, never row values.
"""
import csv
import re
import sys
from collections import Counter,defaultdict
from pathlib import Path


def inventory(dump):
    contents=Path(dump).read_text(encoding="utf-8-sig",errors="replace")
    tables={}
    for table,definition in re.findall(
        r"^CREATE TABLE `([^`]+)` \((.*?)\) ENGINE=",contents,re.M|re.S
    ):
        columns=[]
        for line in definition.splitlines():
            match=re.match(r"  `([^`]+)`\s+(.+?)(?:,)?$",line)
            if match:
                columns.append((match[1],match[2].rstrip(",")))
        tables[table]=columns
    if not tables:
        raise ValueError("Nenhuma tabela CREATE TABLE encontrada.")

    relations=defaultdict(list)
    for table,body in re.findall(r"^ALTER TABLE `([^`]+)`\s+(.*?);",contents,re.M|re.S):
        for field,reference,reference_field in re.findall(
            r"FOREIGN KEY \(`([^`]+)`\) REFERENCES `([^`]+)` \(`([^`]+)`\)",body
        ):
            relations[table].append(f"{field} -> {reference}.{reference_field}")

    rows=Counter()
    active=None
    for line in contents.splitlines():
        match=re.match(r"^INSERT INTO `([^`]+)`",line)
        if match:
            active=match[1]
        elif active and line.startswith("("):
            rows[active]+=1
        if active and line.endswith(";"):
            active=None
    return [
        (table,len(columns),rows[table],len(relations[table]),
         " | ".join(f"{name}: {definition}" for name,definition in columns),
         " | ".join(relations[table]))
        for table,columns in sorted(tables.items())
    ]


def main():
    if len(sys.argv)!=3:
        raise SystemExit("Uso: legacy_dump_inventory.py DUMP_SQL SAIDA_CSV")
    rows=inventory(sys.argv[1])
    output=Path(sys.argv[2]);output.parent.mkdir(parents=True,exist_ok=True)
    with output.open("w",newline="",encoding="utf-8") as file:
        writer=csv.writer(file)
        writer.writerow(("table","column_count","insert_rows","fk_count","columns_and_types","foreign_keys"))
        writer.writerows(rows)
    print(f"{len(rows)} tabelas, {sum(row[1] for row in rows)} colunas, "
          f"{sum(row[3] for row in rows)} FKs; inventário salvo em {output}")


if __name__=="__main__":
    main()
