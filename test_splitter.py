"""Tests voor splitter.py. Draai met: pytest, of python test_splitter.py

Bouwt zelf een corpus.tsv, dus er is geen echte harvest-map nodig.
"""

import csv
import io
import zipfile

import splitter as sp

ROWS = [
    # filename, date, year, newspaper, page
    ("1930-03-04_de-telegraaf_a1.txt", "1930-03-04", "1930", "De Telegraaf", "3"),
    ("1934-07-01_de-tijd_a2.txt", "1934-07-01", "1934", "De tĳd : dagblad", "1"),
    ("1948-01-09_trouw_a3.txt", "1948-01-09", "1948", "Trouw", "5"),
    ("1951-11-20_het-vrije-volk_a4.txt", "1951-11-20", "1951", "Het vrĳe volk", "2"),
    ("1952-02-02_trouw_a5.txt", "1952-02-02", "1952", "Trouw", "7"),
]
COLUMNS = ["article_id", "filename", "date", "year", "newspaper", "page",
           "article_type", "n_words_original", "n_words_reocr", "text", "reocr"]


def corpus_tsv(with_reocr=True, empty_rows=()):
    """corpus.tsv zoals de harvest-tool die oplevert, als tekst."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter="\t", lineterminator="\n")
    writer.writerow(COLUMNS if with_reocr else COLUMNS[:-1])
    for index, (name, date, year, paper, page) in enumerate(ROWS):
        # echte artikelen bevatten regeleindes: die moeten de tabel heel laten
        text = "" if index in empty_rows else f"Titel {index}\n\ntekst van artikel {index}\n"
        row = [f"id{index}", name, date, year, paper, page, "artikel", 100, 110, text]
        if with_reocr:
            row.append("" if index in empty_rows else f"opnieuw herkend {index}\n")
        writer.writerow(row)
    return buffer.getvalue()


def source(**kw):
    return io.BytesIO(corpus_tsv(**kw).encode("utf-8"))


def load(**kw):
    """(bestand, corpus): build_split_zip leest hetzelfde bestand nog een keer."""
    handle = source(**kw)
    return handle, sp.read_corpus(handle, "corpus.tsv")


def test_leest_corpus_tsv_met_regeleindes_in_de_tekst():
    _src, corpus = load()
    assert len(corpus.meta) == len(ROWS)
    # de tekst blijft niet in het geheugen, alleen het aantal woorden
    assert list(corpus.meta.columns) == COLUMNS[:-2]
    assert corpus.words["text"][0] == 6
    assert corpus.empty_count("text") == 0


def test_tekstkolommen_staan_in_vaste_volgorde():
    assert load()[1].text_cols == ["text", "reocr"]
    assert load(with_reocr=False)[1].text_cols == ["text"]


def test_eigen_csv_met_bom_en_onbekende_tekstkolom():
    lang = "woord " * 50
    handle = io.BytesIO(f"\ufeffdatum,artikel\n1950-01-01,{lang}\n".encode("utf-8"))
    corpus = sp.read_corpus(handle, "eigen.csv")
    assert list(corpus.meta.columns) == ["datum"]          # BOM niet in de kolomnaam
    assert corpus.text_cols == ["artikel"]
    data, report = sp.build_split_zip(handle, corpus, ["alles"], "artikel")
    out = zipfile.ZipFile(io.BytesIO(data))
    assert out.read("alles/artikel_1.txt").decode("utf-8") == lang
    assert not handle.closed                             # upload blijft bruikbaar


def test_indeling_per_decennium_jaar_en_maand():
    src, corpus = load()
    frame = corpus.meta
    assert sp.compute_groups(frame, "Decennium") == [
        "1930s", "1930s", "1940s", "1950s", "1950s"
    ]
    assert sp.compute_groups(frame, "Jaar") == [
        "1930", "1934", "1948", "1951", "1952"
    ]
    assert sp.compute_groups(frame, "Jaar-maand")[0] == "1930-03"


def test_indeling_per_kolom_maakt_namen_veilig():
    groups = sp.compute_groups(load()[1].meta, "kolom:newspaper")
    assert "De tĳd _ dagblad" in groups       # dubbele punt wordt _
    assert groups.count("Trouw") == 2


def test_eigen_indeling_met_mapping_csv():
    src, corpus = load()
    frame = corpus.meta
    template = sp.mapping_template(sorted(set(frame["newspaper"])))
    rows = list(csv.reader(io.StringIO(template)))
    assert rows[0] == ["waarde", "groep"]
    assert len(rows) == 1 + len(set(frame["newspaper"]))

    mapping = sp.parse_mapping(io.StringIO(
        "waarde,groep\nTrouw,protestants\nHet vrĳe volk,socialistisch\n"
    ))
    groups = sp.compute_groups(frame, "mapping", "newspaper", mapping)
    assert groups == [
        "niet-ingedeeld", "niet-ingedeeld", "protestants",
        "socialistisch", "protestants",
    ]
    assert sp.unmapped_values(frame, "newspaper", mapping) == [
        "De Telegraaf", "De tĳd : dagblad"
    ]


def test_mapping_zonder_juiste_kolommen_geeft_fout():
    try:
        sp.parse_mapping(io.StringIO("a,b\n1,2\n"))
    except ValueError as error:
        assert "waarde" in str(error)
    else:
        raise AssertionError("verwachtte een ValueError")


def test_lange_titels_komen_niet_in_dezelfde_map():
    lang = "A" * 80
    names = sp.safe_group_names([lang + "een", lang + "twee", lang + "een"])
    assert names[0] == names[2]
    assert len(set(names)) == 2


def test_bestandsnamen_komen_uit_de_kolom_filename():
    src, corpus = load()
    frame = corpus.meta
    assert sp.file_names(frame) == [name for name, *_rest in ROWS]


def test_bestandsnamen_zonder_filename_komen_uit_de_datum():
    frame = load()[1].meta.drop(columns=["filename"])
    frame.loc[1, "date"] = frame.loc[0, "date"]            # zelfde dag: nummeren
    names = sp.file_names(frame)
    assert names[0] == "1930-03-04.txt" and names[1] == "1930-03-04_2.txt"


def test_zip_bevat_een_map_per_groep_met_de_tekst_uit_de_tabel():
    src, corpus = load()
    frame = corpus.meta
    groups = sp.compute_groups(frame, "Decennium")
    data, report = sp.build_split_zip(
        src, corpus, groups, "text", source_name="corpus.tsv", label="Decennium"
    )
    out = zipfile.ZipFile(io.BytesIO(data))

    texts = [n for n in out.namelist() if n.endswith(".txt") and not n.startswith("_")]
    assert len(texts) == len(ROWS)
    assert report["written"] == len(ROWS)
    assert report["empty"] == []
    assert report["groups"] == {"1930s": 2, "1940s": 1, "1950s": 2}

    # inhoud ongewijzigd, inclusief de regeleindes
    assert out.read(f"1930s/{ROWS[0][0]}").decode("utf-8") == "Titel 0\n\ntekst van artikel 0\n"

    # bijlagen
    assert {"_overzicht.csv", "_metadata.csv", "_LEESMIJ.txt"} <= set(out.namelist())
    overview = list(csv.DictReader(io.StringIO(out.read("_overzicht.csv").decode())))
    assert [r["map"] for r in overview] == ["1930s", "1940s", "1950s"]
    assert overview[0]["artikelen"] == "2"
    assert overview[0]["woorden"] == "12"                  # 6 woorden per artikel
    assert overview[0]["eerste_datum"] == "1930-03-04"

    # de metadata gaat mee, de tekstkolommen niet (anders staat het corpus er twee keer in)
    header = out.read("_metadata.csv").decode().splitlines()[0]
    assert "_groep" in header and "text" not in header.split(",")


def test_reocr_kolom_levert_de_andere_tekstversie():
    src, corpus = load()
    frame = corpus.meta
    data, report = sp.build_split_zip(src, corpus, sp.compute_groups(frame, "Jaar"), "reocr")
    out = zipfile.ZipFile(io.BytesIO(data))
    assert out.read(f"1930/{ROWS[0][0]}").decode("utf-8") == "opnieuw herkend 0\n"
    assert report["written"] == len(ROWS)
    assert "kolom reocr" in out.read("_LEESMIJ.txt").decode()


def test_lege_tekst_wordt_gemeld_niet_stilgeslikt():
    src, corpus = load(empty_rows=(1, 3))
    frame = corpus.meta
    groups = sp.compute_groups(frame, "Jaar")
    _data, report = sp.build_split_zip(src, corpus, groups, "text")
    assert report["written"] == len(ROWS) - 2
    assert report["empty"] == [ROWS[1][0], ROWS[3][0]]


def test_samenvoegen_geeft_een_bestand_per_groep():
    src, corpus = load()
    frame = corpus.meta
    groups = sp.compute_groups(frame, "Decennium")
    data, report = sp.build_split_zip(src, corpus, groups, "text", merge=True)
    out = zipfile.ZipFile(io.BytesIO(data))
    assert sorted(n for n in out.namelist() if not n.startswith("_")) == [
        "1930s.txt", "1940s.txt", "1950s.txt"
    ]
    assert "\n---\n" in out.read("1930s.txt").decode("utf-8")
    assert report["groups"] == {"1930s": 2, "1940s": 1, "1950s": 2}


def test_kolommen_met_een_waarde_of_tekst_zijn_geen_indeling():
    src, corpus = load()
    frame = corpus.meta
    columns = sp.grouping_columns(frame, "text")
    assert "article_type" not in columns          # altijd 'artikel'
    assert "text" not in columns and "reocr" not in columns
    assert "n_words_original" not in columns
    assert "qa_flag" not in columns
    assert "newspaper" in columns
    # datum en jaar zitten al in Decennium/Jaar/Jaar-maand: geen dubbele opties
    assert "year" not in columns and "date" not in columns


def test_lange_harvest_bestandsnaam_blijft_heel():
    name = "1967-01-02_het-vrije-volk-democratisch-socialistisc_ddd_010956226_mpeg21_a0236.txt"
    frame = sp.read_corpus(io.StringIO(f"filename\ttext\n{name}\thallo\n"), "x.tsv").meta
    assert sp.file_names(frame) == [name]


def test_zipnaam_geeft_de_keuze_weer():
    assert sp.zip_name("Decennium", "text") == "deelcorpora_decennium_text.zip"
    assert sp.zip_name("Jaar-maand", "reocr", merge=True) == (
        "deelcorpora_jaar-maand_reocr_per-groep-1-bestand.zip"
    )
    assert sp.zip_name("Eigen indeling (mapping-CSV)", "text", "newspaper") == (
        "deelcorpora_eigen-indeling-krant_text.zip"
    )
    assert sp.zip_name("Krant", "text", source_name="wg5-g9.tsv") == (
        "wg5-g9_deelcorpora_krant_text.zip"
    )


def test_mapnaam_kan_niet_buiten_de_map_wijzen():
    assert "/" not in sp.safe_name("../../etc/passwd")
    assert sp.safe_name("") == "onbekend"
    assert sp.safe_name(float("nan")) == "onbekend"
    assert "/" not in sp.file_names(
        sp.read_corpus(io.StringIO("filename\ttext\n../../x.txt\thallo\n"), "x.tsv").meta
    )[0]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"OK  {test.__name__}")
    print(f"\n{len(tests)} tests geslaagd")
