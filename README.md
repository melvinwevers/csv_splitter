# Corpus Splitter

Streamlit-app met twee functies:

1. **Corpus opdelen in mappen** — deelcorpora maken op basis van `metadata.csv`
   (per decennium, jaar, krant, of een eigen indeling zoals signatuur).
2. **Tabel opsplitsen in tekstbestanden** — van één CSV/TSV met de tekst in een
   kolom naar losse `.txt`-bestanden. Bedoeld als noodroute, bijvoorbeeld voor
   een eigen export uit Delpher.

## Lokaal draaien

```sh
pip install -r requirements.txt
streamlit run app.py
```

## Tests

```sh
python test_splitter.py     # of: pytest test_splitter.py
```

De tests bouwen zelf een klein corpus, dus er is geen echte harvest-map nodig.

---

## Instructie voor studenten (modus 1)

> **Deelcorpora maken met de Corpus Splitter**
>
> Je hoeft geen bestanden met de hand te kopiëren. De Corpus Splitter doet dat
> op basis van `metadata.csv`.
>
> 1. Zip je corpusmap — de map waarin `metadata.csv` staat.
>    Windows: rechtermuisklik → *Comprimeren naar* → *ZIP-bestand*.
>    macOS: rechtermuisklik → *Comprimeer*.
> 2. Open de Corpus Splitter en upload de ZIP.
> 3. Kies bij *Welke tekstversie?* de map `text/` — dat is de tekst om mee te
>    werken.
> 4. Kies bij *Map per:* de indeling die je nodig hebt, bijvoorbeeld
>    **Decennium** of **Krant**.
> 5. Klik op *Maak ZIP* en download het resultaat.
> 6. Pak de ZIP uit. Elke map is een deelcorpus: open zo'n map in AntConc.
>
> In de ZIP zit ook `_overzicht.csv` met het aantal artikelen en woorden per
> map — handig voor de beschrijvende statistiek.

### Eigen indeling (bijvoorbeeld signatuur)

Signatuur staat niet in de metadata; die indeling maak je zelf.

1. Kies bij *Map per:* de optie **Eigen indeling (mapping-CSV)**.
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

De tekstbestanden worden ongewijzigd gekopieerd — alleen verdeeld over mappen.
In de ZIP zitten verder `_metadata.csv` (de oorspronkelijke metadata met een
kolom `_groep` erbij) en `_LEESMIJ.txt` met wat er is gedaan.

Staat een bestand uit `metadata.csv` niet in de gekozen tekstmap, dan meldt de
app dat en wordt het overgeslagen. Dat komt voor bij `reocr/`, waar soms een
enkel artikel ontbreekt.
