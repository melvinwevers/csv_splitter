import io
import zipfile

import pandas as pd
import streamlit as st

import splitter as sp

st.set_page_config(page_title="Corpus Splitter", page_icon="📄")

st.title("Corpus Splitter")

mode = st.radio(
    "Wat wil je doen?",
    [
        "Corpus opdelen in mappen",
        "Tabel opsplitsen in tekstbestanden",
    ],
    captions=[
        "Je hebt losse .txt-bestanden met een metadata.csv, en wilt mappen "
        "per decennium, krant of een eigen indeling.",
        "Je hebt één CSV/TSV met de tekst in een kolom, en wilt daar losse "
        "tekstbestanden van maken.",
    ],
)

st.divider()


# ------------------------------------------------- modus 1: corpus naar mappen

if mode == "Corpus opdelen in mappen":
    st.write(
        "Upload je corpus als **ZIP-bestand**. Je krijgt een ZIP terug met een "
        "map per groep, met de originele tekstbestanden erin — klaar om als "
        "corpus in AntConc te openen."
    )
    with st.expander("Hoe maak ik zo'n ZIP?"):
        st.markdown(
            "Zip de hele corpusmap, dus de map waarin `metadata.csv` staat.\n\n"
            "- **Windows:** rechtermuisklik op de map → *Comprimeren naar* → "
            "*ZIP-bestand*\n"
            "- **macOS:** rechtermuisklik op de map → *Comprimeer*"
        )

    upload = st.file_uploader("Corpus (ZIP)", type=["zip"])

    if upload is not None:
        try:
            zf = zipfile.ZipFile(io.BytesIO(upload.getvalue()))
        except zipfile.BadZipFile:
            st.error("Dit lijkt geen geldig ZIP-bestand te zijn.")
            st.stop()

        member = sp.find_metadata_member(zf)
        if member is None:
            st.error(
                "Geen `metadata.csv` gevonden in de ZIP. Zip de corpusmap "
                "waarin `metadata.csv` staat."
            )
            st.stop()

        prefix = member[: -len("metadata.csv")]
        meta = sp.read_metadata(zf, member)
        folders = sp.text_folders(zf, prefix)

        if "filename" not in meta.columns:
            st.error(
                "`metadata.csv` heeft geen kolom `filename`; die is nodig om de "
                "metadata aan de tekstbestanden te koppelen. Gevonden kolommen: "
                + ", ".join(meta.columns)
            )
            st.stop()
        if not folders:
            st.error(
                "Geen map met .txt-bestanden gevonden naast `metadata.csv`. "
                "Zit `text/` wel in de ZIP?"
            )
            st.stop()

        st.success(f"{len(meta)} artikelen in `metadata.csv`")

        ordered = sp.order_text_folders(folders)
        text_dir = st.selectbox(
            "Welke tekstversie?",
            ordered,
            format_func=lambda f: f"{f}/ — {len(folders[f])} bestanden",
            help=(
                "`text/` is de tekst om mee te werken: de oorspronkelijke OCR "
                "van Delpher. `reocr/` is opnieuw herkende tekst — vaak beter "
                "leesbaar, maar met andere fouten. Citeer en tel woorden op "
                "basis van `text/`."
            ),
        )
        if text_dir == "reocr":
            st.info(
                "`reocr/` is machinaal opnieuw herkende tekst. Vermeld het als "
                "je die voor een analyse gebruikt, en bekijk `qa_flags.csv`."
            )

        # ------------------------------------------------------ indeling kiezen
        columns = sp.grouping_columns(meta)
        choices = (
            sp.derived_options(meta)
            + [f"kolom:{c}" for c in columns]
            + ["Eigen indeling (mapping-CSV)"]
        )

        def choice_label(choice):
            if choice.startswith("kolom:"):
                name = choice[len("kolom:"):]
                return sp.COLUMN_LABELS.get(name, name)
            return choice

        choice = st.selectbox(
            "Map per:",
            choices,
            format_func=choice_label,
            help="Elke groep wordt een map in de ZIP die je downloadt.",
        )

        source_col = None
        mapping = None

        if choice == "Eigen indeling (mapping-CSV)":
            st.write(
                "Hiermee groepeer je zelf, bijvoorbeeld kranten naar signatuur "
                "(katholiek, socialistisch, liberaal, protestants, neutraal) of "
                "naar landelijk en regionaal. Zo'n indeling staat niet in de "
                "metadata, dus die geef je zelf op."
            )
            source_col = st.selectbox(
                "Welke kolom hergroeperen?",
                columns,
                index=columns.index("newspaper") if "newspaper" in columns else 0,
                format_func=lambda c: sp.COLUMN_LABELS.get(c, c),
            )
            values = sorted(set(meta[source_col].astype(str).str.strip()))
            st.download_button(
                f"1. Download mapping-CSV ({len(values)} waarden)",
                data=sp.mapping_template(values).encode("utf-8-sig"),
                file_name=f"mapping_{source_col}.csv",
                mime="text/csv",
            )
            st.caption(
                "Vul de kolom `groep` in, bewaar als CSV en upload hieronder. "
                "Waarden zonder groep komen in de map `niet-ingedeeld`."
            )
            mapping_file = st.file_uploader(
                "2. Ingevulde mapping-CSV", type=["csv"], key="mapping_upload"
            )
            if mapping_file is None:
                st.stop()
            try:
                mapping = sp.parse_mapping(mapping_file)
            except ValueError as error:
                st.error(str(error))
                st.stop()
            unmapped = sp.unmapped_values(meta, source_col, mapping)
            if unmapped:
                st.warning(
                    f"{len(unmapped)} waarden hebben geen groep en komen in "
                    "`niet-ingedeeld`: "
                    + ", ".join(unmapped[:10])
                    + (" …" if len(unmapped) > 10 else "")
                )
            groups = sp.compute_groups(meta, "mapping", source_col, mapping)
        else:
            groups = sp.compute_groups(meta, choice)

        counts = pd.Series(groups).value_counts().sort_index()
        st.write(f"**{len(counts)} mappen**")
        st.dataframe(
            counts.rename_axis("map").reset_index(name="artikelen"),
            hide_index=True,
            width="stretch",
        )
        if len(counts) > 100:
            st.warning(
                f"{len(counts)} mappen is veel voor AntConc. Overweeg een "
                "grovere indeling, bijvoorbeeld decennium in plaats van "
                "jaar-maand."
            )

        if st.button("Maak ZIP", type="primary"):
            with st.spinner("Bestanden verdelen…"):
                data, report = sp.build_split_zip(
                    zf,
                    meta,
                    groups,
                    text_dir,
                    folders,
                    source_name=upload.name,
                    label=choice_label(choice)
                    + (f" (kolom {source_col})" if source_col else ""),
                )
            st.session_state["split_zip"] = data
            st.session_state["split_report"] = report
            st.session_state["split_name"] = (
                "deelcorpora_"
                + sp.safe_name(choice_label(choice)).lower().replace(" ", "_")
                + ".zip"
            )

        if "split_zip" in st.session_state:
            report = st.session_state["split_report"]
            if report["missing"]:
                st.warning(
                    f"{len(report['missing'])} bestanden uit `metadata.csv` "
                    f"staan niet in `{text_dir}/` en zijn overgeslagen: "
                    + ", ".join(report["missing"][:5])
                    + (" …" if len(report["missing"]) > 5 else "")
                )
            st.success(
                f"{report['written']} bestanden verdeeld over "
                f"{len(report['groups'])} mappen."
            )
            st.download_button(
                "Download ZIP",
                data=st.session_state["split_zip"],
                file_name=st.session_state["split_name"],
                mime="application/zip",
                type="primary",
            )

# ------------------------------------------- modus 2: tabel naar tekstbestanden

else:
    st.write(
        "Upload een CSV of TSV met de tekst in een kolom — bijvoorbeeld een "
        "eigen export — en maak daar tekstbestanden van."
    )

    upload = st.file_uploader("CSV/TSV-bestand", type=["csv", "tsv"])

    if upload is not None:
        separator = "\t" if upload.name.lower().endswith(".tsv") else ","
        df = pd.read_csv(upload, sep=separator)

        st.success(f"{len(df)} regels geladen")
        st.dataframe(df.head(), width="stretch")

        column_list = list(df.columns)
        text_col = st.selectbox(
            "Kolom met de tekst",
            column_list,
            index=column_list.index("ocr") if "ocr" in column_list else 0,
        )
        date_col = st.selectbox(
            "Kolom met de datum",
            ["(geen)"] + column_list,
            index=column_list.index("date") + 1 if "date" in column_list else 0,
        )

        dates = None
        if date_col != "(geen)":
            dates = pd.to_datetime(df[date_col], errors="coerce")

        options = ["Eén bestand per artikel"]
        if dates is not None:
            options += ["Eén bestand per jaar", "Eén bestand per maand"]
        options += [
            f"Eén bestand per {c}"
            for c in column_list
            if c not in (text_col, date_col) and 1 < df[c].nunique() <= 500
        ]

        split_option = st.selectbox("Opdelen in:", options)
        st.caption(
            "Bij één bestand per artikel krijg je losse bestanden; bij de "
            "andere opties worden de artikelen per groep samengevoegd, "
            "gescheiden door een regel met `---`."
        )

        if st.button("Maak ZIP", type="primary"):
            buffer = io.BytesIO()

            def joined(group):
                return "\n\n---\n\n".join(
                    str(v) if pd.notna(v) else "" for v in group[text_col]
                )

            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as out:
                if split_option == "Eén bestand per artikel":
                    seen = {}
                    for position, (_, row) in enumerate(df.iterrows()):
                        stem = "onbekend"
                        if dates is not None and pd.notna(dates.iloc[position]):
                            stem = dates.iloc[position].strftime("%Y-%m-%d")
                        seen[stem] = seen.get(stem, 0) + 1
                        suffix = "" if seen[stem] == 1 else f"_{seen[stem]}"
                        value = row[text_col]
                        out.writestr(
                            f"{stem}{suffix}.txt",
                            str(value) if pd.notna(value) else "",
                        )
                elif split_option == "Eén bestand per jaar":
                    for year, group in df.groupby(dates.dt.year, dropna=False):
                        name = sp.safe_name(int(year) if pd.notna(year) else None)
                        out.writestr(f"{name}.txt", joined(group))
                elif split_option == "Eén bestand per maand":
                    months = dates.dt.strftime("%Y-%m")
                    for month, group in df.groupby(months, dropna=False):
                        out.writestr(f"{sp.safe_name(month)}.txt", joined(group))
                else:
                    column = split_option[len("Eén bestand per "):]
                    for value, group in df.groupby(column, dropna=False):
                        out.writestr(f"{sp.safe_name(value)}.txt", joined(group))

            buffer.seek(0)
            st.session_state["table_zip"] = buffer.getvalue()

        if "table_zip" in st.session_state:
            st.download_button(
                "Download ZIP",
                data=st.session_state["table_zip"],
                file_name="tekstbestanden.zip",
                mime="application/zip",
                type="primary",
            )
