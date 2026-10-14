"""Kernlogica voor de Corpus Splitter, los van de Streamlit-interface."""

import csv
import io
import posixpath
import zipfile

import pandas as pd

PREFERRED_TEXT_DIRS = ["text", "reocr", "original_ocr"]

# Kolommen die als groepering niets opleveren (unieke waarden per artikel).
NON_GROUPING_COLUMNS = {
    "filename",
    "article_id",
    "title",
    "delpher_url",
    "reocr_flags",
    "n_words_original",
    "n_words_reocr",
}

COLUMN_LABELS = {
    "newspaper": "Krant (newspaper)",
    "page": "Pagina (page)",
    "article_type": "Soort (article_type)",
    "ocr_source": "Tekstbron (ocr_source)",
    "qa_flag": "QA-markering (qa_flag)",
    "in_sample": "In steekproef (in_sample)",
    "year": "Jaar (year)",
    "date": "Datum (date)",
}


def safe_name(value, fallback="onbekend"):
    """Maak van een metadata-waarde een veilige map- of bestandsnaam."""
    text = str(value).strip()
    if not text or text.lower() in ("nan", "none", "nat"):
        return fallback
    cleaned = "".join(
        c if (c.isalnum() or c in (" ", "-", "_", ".")) else "_" for c in text
    )
    cleaned = " ".join(cleaned.split()).strip(" ._-")
    return cleaned[:80] or fallback


def safe_group_names(values):
    """Veilige mapnamen voor een reeks waarden, zonder dat er twee
    verschillende waarden in dezelfde map belanden door afkorten."""
    values = [str(v) for v in values]
    raw_per_name = {}
    for value in values:
        raw_per_name.setdefault(safe_name(value), set()).add(value)

    resolved = {}
    for name, raws in raw_per_name.items():
        if len(raws) == 1:
            resolved[next(iter(raws))] = name
            continue
        # deterministisch nummeren, zodat dezelfde invoer hetzelfde oplevert
        for index, raw in enumerate(sorted(raws), start=1):
            resolved[raw] = name if index == 1 else f"{name}_{index}"
    return [resolved[value] for value in values]


def find_metadata_member(zf):
    """Pad naar metadata.csv in de zip, ook als die in een submap zit."""
    candidates = [
        name
        for name in zf.namelist()
        if posixpath.basename(name).lower() == "metadata.csv"
        and not name.startswith("__MACOSX")
    ]
    candidates.sort(key=lambda name: (name.count("/"), len(name)))
    return candidates[0] if candidates else None


def text_folders(zf, prefix):
    """Submappen met .txt-bestanden naast metadata.csv, als {map: [paden]}."""
    found = {}
    for name in zf.namelist():
        if not name.lower().endswith(".txt") or name.startswith("__MACOSX"):
            continue
        if not name.startswith(prefix):
            continue
        rest = name[len(prefix):]
        if "/" not in rest:
            continue
        found.setdefault(rest.split("/", 1)[0], []).append(name)
    return found


def order_text_folders(folders):
    """Zet text/ vooraan, dan reocr/, dan de rest."""
    known = [f for f in PREFERRED_TEXT_DIRS if f in folders]
    return known + sorted(f for f in folders if f not in PREFERRED_TEXT_DIRS)


def read_metadata(zf, member):
    with zf.open(member) as handle:
        return pd.read_csv(handle, dtype=str, keep_default_na=False)


def grouping_columns(meta):
    return [
        c
        for c in meta.columns
        if c not in NON_GROUPING_COLUMNS and meta[c].nunique() > 1
    ]


def derived_options(meta):
    options = []
    if "year" in meta.columns or "date" in meta.columns:
        options += ["Decennium", "Jaar"]
    if "date" in meta.columns:
        options.append("Jaar-maand")
    return options


def _years(meta):
    if "year" in meta.columns:
        years = pd.to_numeric(meta["year"], errors="coerce")
        if years.notna().any():
            return years
    if "date" in meta.columns:
        return pd.to_datetime(meta["date"], errors="coerce").dt.year
    return pd.Series([pd.NA] * len(meta))


def compute_groups(meta, choice, source_col=None, mapping=None):
    """Bepaal per metadata-regel de groep (mapnaam), als lijst strings."""
    if choice == "Decennium":
        values = _years(meta).map(
            lambda y: f"{int(y) // 10 * 10}s" if pd.notna(y) else "onbekend"
        )
    elif choice == "Jaar":
        values = _years(meta).map(
            lambda y: str(int(y)) if pd.notna(y) else "onbekend"
        )
    elif choice == "Jaar-maand":
        dates = pd.to_datetime(meta["date"], errors="coerce")
        values = dates.dt.strftime("%Y-%m").fillna("onbekend")
    elif choice == "mapping":
        if not source_col or mapping is None:
            raise ValueError("mapping vereist een source_col en mapping")
        values = meta[source_col].astype(str).str.strip().map(
            lambda v: mapping.get(v) or "niet-ingedeeld"
        )
    elif choice.startswith("kolom:"):
        values = meta[choice[len("kolom:"):]]
    else:
        raise ValueError(f"onbekende indeling: {choice}")
    return safe_group_names(values)


def unmapped_values(meta, source_col, mapping):
    return sorted(
        {
            v
            for v in meta[source_col].astype(str).str.strip()
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


def _overview_csv(meta, groups, text_dir):
    word_col = None
    if text_dir == "reocr" and "n_words_reocr" in meta.columns:
        word_col = "n_words_reocr"
    elif "n_words_original" in meta.columns:
        word_col = "n_words_original"
    has_date = "date" in meta.columns

    frame = meta.copy()
    frame["_groep"] = groups

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    header = ["map", "artikelen"]
    if word_col:
        header += ["woorden", "woorden_per_artikel"]
    if has_date:
        header += ["eerste_datum", "laatste_datum"]
    writer.writerow(header)

    for group, rows in frame.groupby("_groep", sort=True):
        line = [group, len(rows)]
        if word_col:
            counts = pd.to_numeric(rows[word_col], errors="coerce").dropna()
            total = int(counts.sum())
            line += [total, round(total / len(rows), 1) if len(rows) else 0]
        if has_date:
            dates = sorted(d for d in rows["date"].astype(str) if d.strip())
            line += [dates[0] if dates else "", dates[-1] if dates else ""]
        writer.writerow(line)
    return buffer.getvalue()


def build_split_zip(zf, meta, groups, text_dir, folders, source_name="", label=""):
    """Bouw een ZIP met een map per groep. Geeft (bytes, rapport) terug."""
    available = {posixpath.basename(n): n for n in folders[text_dir]}
    frame = meta.copy()
    frame["_groep"] = groups

    buffer = io.BytesIO()
    missing = []
    written = 0
    per_group = {}

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as out:
        for _, row in frame.iterrows():
            base = posixpath.basename(str(row["filename"]))
            member = available.get(base)
            if member is None:
                missing.append(base)
                continue
            group = row["_groep"]
            out.writestr(f"{group}/{base}", zf.read(member))
            written += 1
            per_group[group] = per_group.get(group, 0) + 1

        out.writestr("_overzicht.csv", _overview_csv(meta, groups, text_dir))

        meta_out = io.StringIO()
        frame.to_csv(meta_out, index=False)
        out.writestr("_metadata.csv", meta_out.getvalue())

        out.writestr(
            "_LEESMIJ.txt",
            "Deelcorpora gemaakt met de Corpus Splitter\n"
            "==========================================\n\n"
            f"Bron: {source_name}\n"
            f"Tekstversie: {text_dir}/\n"
            f"Ingedeeld op: {label}\n"
            f"Aantal mappen: {len(per_group)}\n"
            f"Aantal bestanden: {written}\n"
            f"Overgeslagen (bestand niet gevonden): {len(missing)}\n\n"
            "Elke map is een deelcorpus: open zo'n map in AntConc.\n"
            "_overzicht.csv bevat de aantallen per map.\n"
            "_metadata.csv is de metadata met een kolom _groep erbij.\n",
        )

    buffer.seek(0)
    report = {
        "written": written,
        "missing": missing,
        "groups": per_group,
    }
    return buffer.getvalue(), report
