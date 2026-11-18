import pandas as pd
import streamlit as st

import splitter as sp

st.set_page_config(page_title="Corpus Splitter", page_icon="📄")

st.title("Corpus Splitter")

st.write(
    "Upload **corpus.tsv** uit je corpusmap. Je kiest welke tekstversie je wilt en "
    "hoe je het corpus indeelt; je krijgt een ZIP terug met een map per groep en één "
    "tekstbestand per artikel — klaar om als corpus in AntConc te openen."
)

upload = st.file_uploader("corpus.tsv (of een eigen CSV/TSV)", type=["tsv", "csv", "tab"])

if upload is None:
    st.stop()

# Eén keer inlezen per upload, niet bij elke klik: Streamlit draait dit script opnieuw
# bij elke wijziging, en het inlezen kost bij een groot corpus het meeste geheugen.
upload_key = (upload.file_id, upload.name, upload.size)
if st.session_state.get("corpus_key") != upload_key:
    for key in ("corpus", "corpus_key", "split_zip", "split_report", "split_name",
                "split_settings"):
        st.session_state.pop(key, None)
    try:
        st.session_state["corpus"] = sp.read_corpus(upload, upload.name)
    except Exception as error:                  # de csv-module noemt het probleem zelf
        st.error(f"Dit bestand kon niet worden gelezen: {error}")
        st.stop()
    st.session_state["corpus_key"] = upload_key

corpus = st.session_state["corpus"]
frame = corpus.meta
available = corpus.text_cols
if not available:
    st.error(
        "Geen kolom met tekst gevonden. `corpus.tsv` heeft een kolom `text`; in een "
        "eigen export moet de tekst in een kolom staan. Gevonden kolommen: "
        + ", ".join(frame.columns)
    )
    st.stop()

st.success(f"{len(frame)} artikelen geladen")

# ------------------------------------------------------------- tekstversie kiezen
text_col = st.selectbox(
    "Welke tekstversie?",
    available,
    format_func=lambda c: {
        "text": "text — oorspronkelijke OCR van Delpher",
        "reocr": "reocr — opnieuw herkend door een taalmodel",
    }.get(c, c),
    help=(
        "`text` is de tekst om mee te werken: de oorspronkelijke OCR van Delpher. "
        "`reocr` is opnieuw herkende tekst — vaak beter leesbaar, maar met andere "
        "fouten. Citeer en tel woorden op basis van `text`."
    ),
)
if text_col == "reocr":
    st.info(
        "`reocr` is machinaal opnieuw herkende tekst. Vermeld het als je die voor een "
        "analyse gebruikt, en bekijk `qa_flags.csv` in je corpusmap."
    )

empty = corpus.empty_count(text_col)
if empty:
    st.caption(f"{empty} artikelen hebben geen tekst in deze kolom en worden overgeslagen.")

# ------------------------------------------------------------------ indeling kiezen
columns = sp.grouping_columns(frame, text_col)
choices = (
    sp.derived_options(frame)
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
        "Hiermee groepeer je zelf, bijvoorbeeld kranten naar signatuur (katholiek, "
        "socialistisch, liberaal, protestants, neutraal) of naar landelijk en "
        "regionaal. Zo'n indeling staat niet in de metadata, dus die geef je zelf op."
    )
    source_col = st.selectbox(
        "Welke kolom hergroeperen?",
        columns,
        index=columns.index("newspaper") if "newspaper" in columns else 0,
        format_func=lambda c: sp.COLUMN_LABELS.get(c, c),
    )
    values = sorted(set(frame[source_col].astype(str).str.strip()))
    st.download_button(
        f"1. Download mapping-CSV ({len(values)} waarden)",
        data=sp.mapping_template(values).encode("utf-8-sig"),
        file_name=f"mapping_{source_col}.csv",
        mime="text/csv",
    )
    st.caption(
        "Vul de kolom `groep` in, bewaar als CSV en upload hieronder. Waarden zonder "
        "groep komen in de map `niet-ingedeeld`."
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
    unmapped = sp.unmapped_values(frame, source_col, mapping)
    if unmapped:
        st.warning(
            f"{len(unmapped)} waarden hebben geen groep en komen in `niet-ingedeeld`: "
            + ", ".join(unmapped[:10])
            + (" …" if len(unmapped) > 10 else "")
        )
    groups = sp.compute_groups(frame, "mapping", source_col, mapping)
else:
    groups = sp.compute_groups(frame, choice)

counts = pd.Series(groups).value_counts().sort_index()
st.write(f"**{len(counts)} groepen**")
st.dataframe(
    counts.rename_axis("map").reset_index(name="artikelen"),
    hide_index=True,
    width="stretch",
)
if len(counts) > 100:
    st.warning(
        f"{len(counts)} mappen is veel voor AntConc. Overweeg een grovere indeling, "
        "bijvoorbeeld decennium in plaats van jaar-maand."
    )

merge = st.checkbox(
    "Eén bestand per groep in plaats van losse bestanden",
    help=(
        "AntConc werkt het best met losse bestanden: laat dit uit. Zet het aan voor "
        "tools die één bestand per groep willen; de artikelen komen dan achter elkaar, "
        "gescheiden door een regel met ---."
    ),
)

# Een ZIP hoort bij precies deze keuzes. Verandert er iets, dan gooien we hem weg:
# anders blijft per student een oude ZIP in het geheugen van de server staan.
settings = (text_col, choice, source_col, tuple(sorted((mapping or {}).items())), merge)
if st.session_state.get("split_settings") != settings:
    for key in ("split_zip", "split_report", "split_name", "split_settings"):
        st.session_state.pop(key, None)

if st.button("Maak ZIP", type="primary"):
    st.session_state.pop("split_zip", None)     # oude ZIP eerst vrijgeven
    with st.spinner("Bestanden maken…"):
        data, report = sp.build_split_zip(
            upload,
            corpus,
            groups,
            text_col,
            source_name=upload.name,
            label=choice_label(choice) + (f" (kolom {source_col})" if source_col else ""),
            merge=merge,
        )
    st.session_state["split_zip"] = data
    st.session_state["split_report"] = report
    st.session_state["split_settings"] = settings
    st.session_state["split_name"] = sp.zip_name(
        choice_label(choice), text_col, source_col, merge, upload.name
    )

if "split_zip" in st.session_state:
    report = st.session_state["split_report"]
    if report["empty"]:
        st.warning(
            f"{len(report['empty'])} artikelen hadden geen tekst en zijn overgeslagen: "
            + ", ".join(report["empty"][:5])
            + (" …" if len(report["empty"]) > 5 else "")
        )
    st.success(
        f"{report['written']} artikelen verdeeld over {len(report['groups'])} "
        + ("bestanden." if merge else "mappen.")
    )
    st.download_button(
        "Download ZIP",
        data=st.session_state["split_zip"],
        file_name=st.session_state["split_name"],
        mime="application/zip",
        type="primary",
    )
