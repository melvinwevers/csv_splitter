"""Tests voor splitter.py. Draai met: pytest, of python test_splitter.py

Bouwt zelf een klein corpus, dus er is geen echte harvest-map nodig.
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


def build_corpus(prefix="corpus/", include_reocr=True, drop_from_reocr=1):
    """Maak een corpus-ZIP in het geheugen, zoals de harvest-tool die oplevert."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        meta = io.StringIO()
        writer = csv.writer(meta)
        writer.writerow(
            ["article_id", "filename", "date", "year", "newspaper", "page",
             "article_type", "n_words_original", "n_words_reocr"]
        )
        for index, (name, date, year, paper, page) in enumerate(ROWS):
            writer.writerow(
                [f"id{index}", name, date, year, paper, page, "artikel", 100, 110]
            )
        zf.writestr(f"{prefix}metadata.csv", meta.getvalue())

        for index, (name, *_rest) in enumerate(ROWS):
            zf.writestr(f"{prefix}text/{name}", f"tekst van artikel {index}\n")
        if include_reocr:
            for name, *_rest in ROWS[: len(ROWS) - drop_from_reocr]:
                zf.writestr(f"{prefix}reocr/{name}", "opnieuw herkend\n")
    buffer.seek(0)
    return zipfile.ZipFile(buffer)


def load(zf):
    member = sp.find_metadata_member(zf)
    prefix = member[: -len("metadata.csv")]
    return sp.read_metadata(zf, member), sp.text_folders(zf, prefix), prefix


def test_vindt_metadata_in_submap_en_in_de_wortel():
    for prefix in ("corpus/", "", "a/b/"):
        zf = build_corpus(prefix)
        member = sp.find_metadata_member(zf)
        assert member == f"{prefix}metadata.csv"
        _meta, folders, _ = load(zf)
        assert set(folders) == {"text", "reocr"}
        assert len(folders["text"]) == len(ROWS)


def test_tekstmappen_staan_in_vaste_volgorde():
    _meta, folders, _ = load(build_corpus())
    assert sp.order_text_folders(folders) == ["text", "reocr"]


def test_indeling_per_decennium_jaar_en_maand():
    meta, _folders, _ = load(build_corpus())
    assert sp.compute_groups(meta, "Decennium") == [
        "1930s", "1930s", "1940s", "1950s", "1950s"
    ]
    assert sp.compute_groups(meta, "Jaar") == [
        "1930", "1934", "1948", "1951", "1952"
    ]
    assert sp.compute_groups(meta, "Jaar-maand")[0] == "1930-03"


def test_indeling_per_kolom_maakt_namen_veilig():
    meta, _folders, _ = load(build_corpus())
    groups = sp.compute_groups(meta, "kolom:newspaper")
    assert "De tĳd _ dagblad" in groups       # dubbele punt wordt _
    assert groups.count("Trouw") == 2


def test_eigen_indeling_met_mapping_csv():
    meta, _folders, _ = load(build_corpus())
    template = sp.mapping_template(sorted(set(meta["newspaper"])))
    rows = list(csv.reader(io.StringIO(template)))
    assert rows[0] == ["waarde", "groep"]
    assert len(rows) == 1 + len(set(meta["newspaper"]))

    mapping = sp.parse_mapping(io.StringIO(
        "waarde,groep\nTrouw,protestants\nHet vrĳe volk,socialistisch\n"
    ))
    groups = sp.compute_groups(meta, "mapping", "newspaper", mapping)
    assert groups == [
        "niet-ingedeeld", "niet-ingedeeld", "protestants",
        "socialistisch", "protestants",
    ]
    assert sp.unmapped_values(meta, "newspaper", mapping) == [
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


def test_zip_bevat_een_map_per_groep_met_originele_inhoud():
    zf = build_corpus()
    meta, folders, prefix = load(zf)
    groups = sp.compute_groups(meta, "Decennium")
    data, report = sp.build_split_zip(
        zf, meta, groups, "text", folders, source_name="test.zip", label="Decennium"
    )
    out = zipfile.ZipFile(io.BytesIO(data))

    texts = [n for n in out.namelist() if n.endswith(".txt") and not n.startswith("_")]
    assert len(texts) == len(ROWS)
    assert report["written"] == len(ROWS)
    assert report["missing"] == []
    assert report["groups"] == {"1930s": 2, "1940s": 1, "1950s": 2}

    # inhoud ongewijzigd
    name = ROWS[0][0]
    assert out.read(f"1930s/{name}") == zf.read(f"{prefix}text/{name}")

    # bijlagen
    assert {"_overzicht.csv", "_metadata.csv", "_LEESMIJ.txt"} <= set(out.namelist())
    overview = list(csv.DictReader(io.StringIO(out.read("_overzicht.csv").decode())))
    assert [r["map"] for r in overview] == ["1930s", "1940s", "1950s"]
    assert overview[0]["artikelen"] == "2"
    assert overview[0]["woorden"] == "200"
    assert overview[0]["eerste_datum"] == "1930-03-04"
    assert "_groep" in out.read("_metadata.csv").decode().splitlines()[0]


def test_ontbrekend_bestand_wordt_gemeld_niet_stilgeslikt():
    zf = build_corpus(drop_from_reocr=2)
    meta, folders, _ = load(zf)
    groups = sp.compute_groups(meta, "Jaar")
    _data, report = sp.build_split_zip(zf, meta, groups, "reocr", folders)
    assert report["written"] == len(ROWS) - 2
    assert len(report["missing"]) == 2


def test_kolommen_met_een_waarde_zijn_geen_indeling():
    meta, _folders, _ = load(build_corpus())
    assert "article_type" not in sp.grouping_columns(meta)   # altijd 'artikel'
    assert "newspaper" in sp.grouping_columns(meta)
    assert "n_words_original" not in sp.grouping_columns(meta)


def test_mapnaam_kan_niet_buiten_de_map_wijzen():
    assert "/" not in sp.safe_name("../../etc/passwd")
    assert sp.safe_name("") == "onbekend"
    assert sp.safe_name(float("nan")) == "onbekend"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"OK  {test.__name__}")
    print(f"\n{len(tests)} tests geslaagd")
