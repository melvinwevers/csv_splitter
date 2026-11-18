"""Kernlogica voor de Corpus Splitter, los van de Streamlit-interface.

Invoer is één tabel: `corpus.tsv` uit de harvest-tool (metadata plus de volledige tekst
per artikel), of een eigen CSV/TSV met de tekst in een kolom. Uitvoer is een ZIP met een
map per groep en één tekstbestand per artikel, klaar om in AntConc te openen.

Zuinig met geheugen, omdat de app met een hele werkgroep tegelijk op één kleine server
draait: `read_corpus` bewaart alleen de metadata en het aantal woorden per artikel, niet
de tekst. `build_split_zip` leest het bestand daarna nog eens regel voor regel en schrijft
elk artikel meteen in de ZIP.
"""

import csv
import io
import posixpath
import sys
import zipfile
from dataclasses import dataclass

import pandas as pd

# Tekstkolommen, in de volgorde waarin ze worden aangeboden. `text` is de oorspronkelijke
# OCR van Delpher, `reocr` de opnieuw herkende tekst.
PREFERRED_TEXT_COLUMNS = ["text", "reocr"]

# Datumkolommen worden niet als losse kolom aangeboden: Decennium, Jaar en Jaar-maand
# (derived_options) dekken ze, en een map per dag is voor AntConc onbruikbaar.
DATE_COLUMNS = {"date", "year"}

# Kolommen die als groepering niets opleveren (unieke waarden per artikel).
NON_GROUPING_COLUMNS = {
    "filename",
    "article_id",
    "title",
    "delpher_url",
    "reocr_flags",
    "n_words_original",
    "n_words_reocr",
    "qa_flag",          # lege/korte tekst: een controle, geen indeling van het corpus
}

COLUMN_LABELS = {
    "newspaper": "Krant",
    "page": "Pagina",
    "article_type": "Soort artikel",
    "ocr_source": "Tekstbron",
    "in_sample": "In steekproef",
}


def safe_name(value, fallback="onbekend", max_len=60):
    """Maak van een metadata-waarde een veilige map- of bestandsnaam.

    Mapnamen blijven kort (60 tekens); bestandsnamen krijgen meer ruimte, zodat het
    artikel-id aan het eind van de harvest-naam heel blijft.
    """
    text = str(value).strip()
    if not text or text.lower() in ("nan", "none", "nat"):
        return fallback
    cleaned = "".join(
        character if character.isalnum() or character in " -_" else "_"
        for character in text
    )
    cleaned = " ".join(cleaned.split())
    return cleaned[:max_len].strip(" .") or fallback


def safe_group_names(values):
    """Veilige mapnamen die uniek blijven: twee lange titels worden niet één map."""
    by_name = {}
    for value in values:
        by_name.setdefault(safe_name(value), set()).add(str(value))

    resolved = {}
    for name, raws in by_name.items():
        # deterministisch nummeren, zodat dezelfde invoer hetzelfde oplevert
        for index, raw in enumerate(sorted(raws), start=1):
            resolved[raw] = name if index == 1 else f"{name}_{index}"
    return [resolved[str(value)] for value in values]


@dataclass
class Corpus:
    """Wat er van een geüpload corpus in het geheugen blijft: alles behalve de tekst."""

    meta: pd.DataFrame      # alle kolommen behalve de tekstkolommen, als strings
    text_cols: list         # tekstkolommen, bekende namen vooraan
    words: dict             # tekstkolom -> aantal woorden per artikel
    name: str               # bestandsnaam, bepaalt tab of komma

    def empty_count(self, text_col):
        return sum(1 for n in self.words[text_col] if n == 0)


def _rows(handle, name):
    """Regels van de tabel, telkens vanaf het begin. Tabs bij .tsv, anders komma's.

    De tekst bevat regeleindes en staat daarom tussen aanhalingstekens; de csv-module
    leest dat goed, een eigen split op tabs niet. Lege regels worden overgeslagen.
    """
    csv.field_size_limit(sys.maxsize)
    separator = "\t" if str(name).lower().endswith((".tsv", ".tab")) else ","
    handle.seek(0)
    if isinstance(handle, io.TextIOBase):
        wrapper, text = None, handle
    else:
        # utf-8-sig: een eigen CSV uit Excel begint vaak met een BOM
        wrapper = text = io.TextIOWrapper(handle, encoding="utf-8-sig", newline="")
    try:
        for row in csv.reader(text, delimiter=separator):
            if row:
                yield row
    finally:
        if wrapper is not None:
            wrapper.detach()    # anders sluit de wrapper ook het geüploade bestand


def read_corpus(handle, name=""):
    """Lees corpus.tsv of een eigen CSV/TSV, zonder de tekst te bewaren."""
    rows = _rows(handle, name)
    header = next(rows, None)
    if header is None:
        raise ValueError("Het bestand is leeg.")
    width = len(header)

    known = {i: c for i, c in enumerate(header) if c in PREFERRED_TEXT_COLUMNS}
    keep = [i for i in range(width) if i not in known]
    words = {c: [] for c in known.values()}
    meta_rows = []
    for row in rows:
        if len(row) < width:
            row += [""] * (width - len(row))
        for i, column in known.items():
            words[column].append(len(row[i].split()))
        meta_rows.append([row[i] for i in keep])
    meta = pd.DataFrame(meta_rows, columns=[header[i] for i in keep], dtype=str)

    text_cols = [c for c in PREFERRED_TEXT_COLUMNS if c in words]
    if not text_cols:
        # Geen bekende naam (eigen export): alles wat lange tekst bevat is een kandidaat.
        text_cols = [c for c in meta.columns if meta[c].str.len().max() >= 200]
        for column in text_cols:
            words[column] = [len(v.split()) for v in meta[column]]
        meta = meta.drop(columns=text_cols)
    return Corpus(meta=meta, text_cols=text_cols, words=words, name=name)


def grouping_columns(frame, text_col=None):
    return [
        c
        for c in frame.columns
        if c not in NON_GROUPING_COLUMNS
        and c not in DATE_COLUMNS
        and c not in PREFERRED_TEXT_COLUMNS
        and c != text_col
        and frame[c].nunique() > 1
    ]


def derived_options(frame):
    options = []
    if "year" in frame.columns or "date" in frame.columns:
        options += ["Decennium", "Jaar"]
    if "date" in frame.columns:
        options.append("Jaar-maand")
    return options


def _years(frame):
    if "year" in frame.columns:
        years = pd.to_numeric(frame["year"], errors="coerce")
        if years.notna().any():
            return years
    if "date" in frame.columns:
        return pd.to_datetime(frame["date"], errors="coerce").dt.year
    return pd.Series([pd.NA] * len(frame))


def compute_groups(frame, choice, source_col=None, mapping=None):
    """Bepaal per regel de groep (mapnaam), als lijst strings."""
    if choice == "Decennium":
        values = _years(frame).map(
            lambda y: f"{int(y) // 10 * 10}s" if pd.notna(y) else "onbekend"
        )
    elif choice == "Jaar":
        values = _years(frame).map(
            lambda y: str(int(y)) if pd.notna(y) else "onbekend"
        )
    elif choice == "Jaar-maand":
        dates = pd.to_datetime(frame["date"], errors="coerce")
        values = dates.dt.strftime("%Y-%m").fillna("onbekend")
    elif choice == "mapping":
        if not source_col or mapping is None:
            raise ValueError("mapping vereist een source_col en mapping")
        values = frame[source_col].astype(str).str.strip().map(
            lambda v: mapping.get(v) or "niet-ingedeeld"
        )
    elif choice.startswith("kolom:"):
        values = frame[choice[len("kolom:"):]]
    else:
        raise ValueError(f"onbekende indeling: {choice}")
    return safe_group_names(values)


def unmapped_values(frame, source_col, mapping):
    return sorted(
        {
            v
            for v in frame[source_col].astype(str).str.strip()
            if not mapping.get(v)
        }
    )


def parse_mapping(handle):
    """Lees een mapping-CSV met kolommen waarde,groep."""
    frame = pd.read_csv(handle, dtype=str, keep_default_na=False)
    if not {"waarde", "groep"} <= set(frame.columns):
        raise ValueError("De mapping-CSV moet de kolommen `waarde` en `groep` hebben.")
    return {
        str(row["waarde"]).strip(): str(row["groep"]).strip()
        for _, row in frame.iterrows()
    }


def mapping_template(values):
    """CSV-sjabloon met alle unieke waarden en een lege kolom groep."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["waarde", "groep"])
    for value in values:
        writer.writerow([value, ""])
    return buffer.getvalue()


def file_names(frame):
    """Bestandsnaam per regel: uit de kolom `filename`, anders uit de datum.

    De harvest-tool zet in `filename` al `JJJJ-MM-DD_krant_artikel-id.txt`, zodat de
    bestanden op datum sorteren. Namen die twee keer voorkomen krijgen een nummer.
    """
    if "filename" in frame.columns:
        raw = [posixpath.basename(str(v)).strip() for v in frame["filename"]]
    elif "date" in frame.columns:
        dates = pd.to_datetime(frame["date"], errors="coerce")
        raw = [
            f"{d.strftime('%Y-%m-%d')}.txt" if pd.notna(d) else "onbekend.txt"
            for d in dates
        ]
    else:
        raw = [f"artikel_{i + 1}.txt" for i in range(len(frame))]

    names, seen = [], {}
    for name in raw:
        # 200 tekens: harvest-namen zijn ~80 tekens en mogen niet worden afgekapt,
        # anders verdwijnt het artikel-id en botsen namen van dezelfde krant en dag.
        stem = safe_name(name.removesuffix(".txt"), fallback="artikel", max_len=200)
        seen[stem] = seen.get(stem, 0) + 1
        suffix = "" if seen[stem] == 1 else f"_{seen[stem]}"
        names.append(f"{stem}{suffix}.txt")
    return names


def zip_name(choice_label, text_col, source_col=None, merge=False, source_name=""):
    """Naam van de ZIP die de keuze weergeeft, bv. `deelcorpora_decennium_text.zip`.

    Met een eigen indeling staat de hergroepeerde kolom erin
    (`deelcorpora_eigen-indeling-krant_text.zip`); bij een hernoemd bestand
    (`wg5-g9.tsv`) komt die naam vooraan.
    """
    def part(value):
        return safe_name(value).lower().replace(" ", "-").replace("_", "-").strip("-")

    if source_col:
        indeling = "eigen-indeling-" + part(COLUMN_LABELS.get(source_col, source_col))
    else:
        indeling = part(choice_label)
    parts = ["deelcorpora", indeling, part(text_col)]
    if merge:
        parts.append("per-groep-1-bestand")
    stem = posixpath.basename(str(source_name)).rsplit(".", 1)[0]
    if stem and stem.lower() != "corpus":
        parts.insert(0, part(stem))
    return "_".join(parts) + ".zip"


def _overview_csv(meta, groups, words):
    has_date = "date" in meta.columns
    dates = meta["date"] if has_date else [""] * len(meta)
    stats = {}
    for group, count, date in zip(groups, words, dates):
        entry = stats.setdefault(group, [0, 0, []])
        entry[0] += 1
        entry[1] += count
        if date.strip():
            entry[2].append(date)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    header = ["map", "artikelen", "woorden", "woorden_per_artikel"]
    if has_date:
        header += ["eerste_datum", "laatste_datum"]
    writer.writerow(header)
    for group in sorted(stats):
        articles, total, group_dates = stats[group]
        line = [group, articles, total, round(total / articles, 1)]
        if has_date:
            group_dates.sort()
            line += [group_dates[0], group_dates[-1]] if group_dates else ["", ""]
        writer.writerow(line)
    return buffer.getvalue()


def build_split_zip(source, corpus, groups, text_col, source_name="", label="", merge=False):
    """Bouw een ZIP met een map per groep. Geeft (bytes, rapport) terug.

    `source` is hetzelfde bestand als waaruit `corpus` gelezen is; het wordt opnieuw
    gelezen en elk artikel gaat meteen de ZIP in, zodat nooit het hele corpus tegelijk
    in het geheugen staat.

    Met merge=True komt er één bestand per groep, met de artikelen achter elkaar
    gescheiden door een regel met `---` (voor tools die één bestand per groep willen).
    """
    meta = corpus.meta
    names = file_names(meta)
    rows = _rows(source, corpus.name)
    column = next(rows).index(text_col)

    buffer = io.BytesIO()
    empty, written, per_group, merged = [], 0, {}, {}

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as out:
        count = 0
        for index, row in enumerate(rows):
            count += 1
            if index >= len(meta):
                raise ValueError("Het bestand is veranderd sinds het is ingelezen.")
            text = row[column] if column < len(row) else ""
            if not text.strip():
                empty.append(names[index])
                continue
            group = groups[index]
            if merge:
                merged.setdefault(group, []).append(text)
            else:
                out.writestr(f"{group}/{names[index]}", text.encode("utf-8"))
            written += 1
            per_group[group] = per_group.get(group, 0) + 1
        if count != len(meta):
            raise ValueError("Het bestand is veranderd sinds het is ingelezen.")

        for group in sorted(merged):
            out.writestr(f"{group}.txt", "\n\n---\n\n".join(merged.pop(group)))

        out.writestr("_overzicht.csv", _overview_csv(meta, groups, corpus.words[text_col]))

        meta_out = io.StringIO()
        meta.assign(_groep=groups, _bestand=names).to_csv(meta_out, index=False)
        out.writestr("_metadata.csv", meta_out.getvalue())

        out.writestr(
            "_LEESMIJ.txt",
            "Deelcorpora gemaakt met de Corpus Splitter\n"
            "==========================================\n\n"
            f"Bron: {source_name}\n"
            f"Tekstversie: kolom {text_col}\n"
            f"Ingedeeld op: {label}\n"
            f"Aantal {'bestanden' if merge else 'mappen'}: {len(per_group)}\n"
            f"Aantal artikelen: {written}\n"
            f"Overgeslagen (lege tekst): {len(empty)}\n\n"
            + (
                "Elk bestand is een deelcorpus: de artikelen staan achter elkaar,\n"
                "gescheiden door een regel met ---.\n"
                if merge
                else "Elke map is een deelcorpus: open zo'n map in AntConc.\n"
            )
            + "_overzicht.csv bevat de aantallen per groep.\n"
            "_metadata.csv is de metadata (zonder de tekst) met een kolom _groep erbij.\n",
        )

    report = {
        "written": written,
        "empty": empty,
        "groups": per_group,
    }
    return buffer.getvalue(), report
