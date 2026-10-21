# Corpus Splitter

Streamlit-app die van `corpus.tsv` deelcorpora maakt: één map per groep (decennium,
jaar, krant, of een eigen indeling) met één tekstbestand per artikel, klaar om in
AntConc te openen.

Invoer is de tabel uit de harvest-tool — metadata plus de volledige tekst per artikel —
of een eigen CSV/TSV met de tekst in een kolom.

## Lokaal draaien

```sh
pip install -r requirements.txt
streamlit run app.py
```

## Tests

```sh
python test_splitter.py     # of: pytest test_splitter.py
```

De tests bouwen zelf een `corpus.tsv`, dus er is geen echte harvest-map nodig.

---

## Instructie voor studenten

> **Deelcorpora maken met de Corpus Splitter**
>
> Je hoeft geen bestanden met de hand te kopiëren. De Corpus Splitter maakt ze voor je
> uit `corpus.tsv`.
>
> 1. Download `corpus.tsv` uit je corpusmap. Open het niet in Excel: de tekst bevat
>    regeleindes en Excel maakt daar een rommeltje van.
> 2. Open de Corpus Splitter en upload `corpus.tsv`.
> 3. Kies bij *Welke tekstversie?* de kolom `text` — de oorspronkelijke OCR van
>    Delpher, de tekst om mee te werken. `reocr` is opnieuw herkende tekst: vaak beter
>    leesbaar, maar met andere fouten. Citeer en tel woorden op basis van `text`.
> 4. Kies bij *Map per* de indeling die je nodig hebt, bijvoorbeeld **Decennium** of
>    **Krant**.
> 5. Klik op *Maak ZIP* en download het resultaat.
> 6. Pak de ZIP uit. Elke map is een deelcorpus: open zo'n map in AntConc
>    (*File → Open Dir* in AntConc 3, *Corpus → Add Directory* in AntConc 4).
>
> In de ZIP zit ook `_overzicht.csv` met het aantal artikelen en woorden per map —
> handig voor de beschrijvende statistiek. Open in AntConc steeds één groepsmap en
> niet de uitgepakte hoofdmap: anders komen `_LEESMIJ.txt` en de andere bijlagen in je
> corpus terecht.

### Eigen indeling (bijvoorbeeld signatuur)

Signatuur staat niet in de metadata; die indeling maak je zelf.

1. Kies bij *Map per* de optie **Eigen indeling (mapping-CSV)**.
2. Kies de kolom die je wilt hergroeperen, meestal `newspaper`.
3. Download de mapping-CSV. Die bevat alle krantentitels uit jóuw corpus en een
   lege kolom `groep`.
4. Vul `groep` in (bijvoorbeeld *katholiek*, *socialistisch*, *protestants*,
   *liberaal*, *neutraal*) en bewaar als CSV.
5. Upload de ingevulde CSV. Titels die je leeg laat komen in de map
   `niet-ingedeeld`.

Dezelfde route werkt voor elke andere indeling, bijvoorbeeld landelijk tegenover
regionaal.

## Wat de app niet verandert

De tekst gaat ongewijzigd uit de tabel naar de bestanden — alleen verdeeld over
mappen. Bestandsnamen komen uit de kolom `filename` (`JJJJ-MM-DD_krant_artikel-id.txt`),
zodat ze op datum sorteren; heeft de tabel die kolom niet, dan wordt de datum gebruikt.

In de ZIP zitten verder `_metadata.csv` (de metadata met een kolom `_groep` erbij, zonder
de tekstkolommen) en `_LEESMIJ.txt` met wat er is gedaan. Artikelen zonder tekst in de
gekozen kolom worden overgeslagen; de app meldt hoeveel en welke. Dat komt voor bij
`reocr`, waar soms een enkel artikel ontbreekt.

Met het vinkje *Eén bestand per groep* krijg je in plaats van losse bestanden één
bestand per groep, met de artikelen achter elkaar gescheiden door een regel met `---`.
Voor AntConc laat je dat uit.
