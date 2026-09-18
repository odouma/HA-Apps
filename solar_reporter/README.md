# Solar Reporter

Home Assistant add-on voor het bijhouden van elektriciteitstarieven en het
automatisch genereren en versturen van PDF-rapportages over de opbrengst en
besparing van je zonnepanelen.

## Functies

- Beheer van elektriciteitstarieven met ingangsdatum — de add-on houdt zelf
  bij welk tarief op elk moment (of elke gewenste datum) van toepassing is.
- Automatische berekening van je besparing en opbrengst, vandaag en
  cumulatief, op basis van de langetermijn-statistieken van Home Assistant.
- Dagelijkse en/of maandelijkse PDF-rapportages per e-mail, met een volledig
  aanpasbare, drag-and-drop lay-out-editor (los in te stellen per rapport).
- Optionele groepering van alle sensoren onder één apparaat in Home
  Assistant via MQTT-discovery.
- Werkt met elk merk omvormer/sensor — welke entiteiten gebruikt worden is
  instelbaar.

## Installatie

1. Zorg dat je bij het bestandssysteem van je Home Assistant-installatie
   kunt, bijvoorbeeld via de add-ons **Samba share** of **Terminal & SSH**.
2. Kopieer deze map naar de "local add-ons"-map van je installatie (op de
   meeste systemen `/addons/local/`, op recentere Supervisor-versies
   `/local_apps/local/`), zodat `config.yaml` en `Dockerfile` direct in die
   map staan.
3. Ga in Home Assistant naar **Instellingen → Add-ons → Add-on store**, klik
   rechtsboven op de drie puntjes en kies **Reload**.
4. Onder **Local add-ons** verschijnt nu "Solar Reporter". Klik erop en dan
   op **Installeren**.
5. Start de add-on en open de webinterface (via het pictogram in het
   linkermenu, of de knop **Open Web UI**) — dit gaat via Home Assistant's
   ingress, er hoeft dus geen extra poort geopend te worden.

## Tarieven bijhouden

Op het hoofdscherm zie je een overzicht van alle ingevoerde tarieven, met per
tarief de status **Actief**, **Toekomstig** of **Verlopen**. Via **+ Nieuw
tarief toevoegen** open je een venster om een tarief (in €/kWh) en de datum
waarop het ingaat in te voeren. Bestaande tarieven zijn te bewerken of te
verwijderen via de knoppen in de tabel.

Bovenaan de pagina zie je ook direct de besparing van vandaag en de totale
besparing sinds het eerst ingevoerde tarief.

## Sensoren in Home Assistant

De add-on maakt de volgende sensoren aan:

| Entiteit | Betekenis |
|---|---|
| `sensor.stroomtarief_actief` | Het tarief (€/kWh) dat vandaag geldt |
| `sensor.stroombesparing_vandaag` | Besparing vandaag, in euro |
| `sensor.stroombesparing_totaal` | Besparing sinds het eerste tarief, in euro |
| `sensor.stroomopbrengst_vandaag` | Opbrengst vandaag, in kWh |
| `sensor.stroomopbrengst_totaal` | Opbrengst sinds het eerste tarief, in kWh |

Deze worden bijgewerkt volgens het ververinterval in **Instellingen →
Algemeen** (standaard elke 10 seconden), en direct na elke wijziging in je
tarieven.

`sensor.stroomtarief_actief` heeft ook een attribuut **`tarieven`** met de
volledige lijst van alle ingevoerde tarieven (verleden, heden en toekomst).
Voorbeeld van gebruik in een template:

```jinja2
Huidig tarief: {{ states('sensor.stroomtarief_actief') }} €/kWh
Eerstvolgende wijziging: {{ state_attr('sensor.stroomtarief_actief', 'eerstvolgende_wijziging') }}

{% for tarief in state_attr('sensor.stroomtarief_actief', 'tarieven') %}
{{ tarief.ingangsdatum }}: {{ tarief.tarief }} €/kWh
{% endfor %}
```

### MQTT-apparaatgroepering (optioneel)

Standaard verschijnen de sensoren hierboven los in Home Assistant. Wil je ze
gegroepeerd zien onder één apparaat "Solar Reporter"? Zet dit aan bij
**Instellingen → MQTT**. Dit vereist een MQTT-broker (bijvoorbeeld de
add-on "Mosquitto broker") en de MQTT-integratie in Home Assistant. Zonder
MQTT blijft alles gewoon werken, alleen dan ongegroepeerd.

## Instellingen

De webinterface heeft een instellingenpagina met de volgende tabbladen:

- **Algemeen** — het ververinterval van de sensoren.
- **Entiteiten** — welke Home Assistant-entiteiten gebruikt worden voor het
  huidige vermogen (in Watt) en de dagelijkse opbrengst (in kWh). Een
  zoekbare lijst toont alleen entiteiten met de juiste eenheid.
- **MQTT** — apparaatgroepering aan/uit en de broker-instellingen.
- **E-mail** — de SMTP-gegevens voor het versturen van rapportages, en de
  onderwerpregel + berichttekst van de dag- en maandrapport-mails (met
  klikbare tags om velden zoals de opbrengst of het rapportonderwerp in te
  voegen).
- **Rapportages** — dagelijkse en/of maandelijkse rapporten aan/uit zetten,
  met verzendtijd/-dag en ontvangers. Een testrapport is direct te versturen
  met **✉️ Testrapport nu versturen**, en de PDF-lay-out van dat rapport is
  te bewerken via **🎨 PDF-opmaak bewerken**.

Wijzigingen op deze pagina worden pas doorgevoerd na het klikken op
**Instellingen opslaan** — bij niet-opgeslagen wijzigingen krijg je een
waarschuwing als je de pagina verlaat.

Op het hoofdscherm staat ook een kort overzicht van beide rapportages, met
een schakelaar om ze snel aan of uit te zetten.

### Rapportages

- **Dagrapport** — opbrengst van die dag in kWh en euro, met een grafiek van
  de opbrengst per uur, plus de besparing tot nu toe.
- **Maandrapport** — wordt verstuurd op de ingestelde dag van de maand en
  gaat over de volledige vorige maand, met een grafiek per dag.

### PDF-opmaak

Het dag- en maandrapport hebben elk hun **eigen, onafhankelijke lay-out**,
aan te passen via een drag-and-drop editor:

- **Onderdelen toevoegen**: tekst, een afbeelding, een grafiek, een lijn of
  een rechthoek. Bij een afbeelding-element kun je een nieuw bestand
  uploaden of een eerder geüploade afbeelding kiezen.
- **Verplaatsen/vergroten**: sleep een onderdeel naar de gewenste plek, of
  gebruik het handvat rechtsonder om het formaat aan te passen. X/Y/breedte/
  hoogte zijn ook rechtstreeks in te typen.
- **Tags in tekst**: klik op een tag-knop (bijv. "Opbrengst (kWh)") om die
  op de cursorpositie in te voegen — dit wordt bij het versturen automatisch
  vervangen door de echte waarde. Beschikbaar: `{report_title}`,
  `{period_label}`, `{opbrengst_kwh}`, `{opbrengst_euro}`,
  `{besparing_totaal_kwh}`, `{besparing_totaal_euro}`, `{gegenereerd_op}`.
- **Opmaak van tekst**: lettergrootte, lettertype, kleur, uitlijning, vet/
  cursief/onderstreept.
- **Grafiek**: staaf-, lijn- of vlakdiagram met eigen kleur, rasterlijnen en
  optionele waardelabels.
- **"Kopieer opmaak van ander rapport"**: neemt de lay-out van het andere
  rapport over als startpunt.
- **"Standaardlayout herstellen"**: zet de oorspronkelijke lay-out van het
  huidige rapport terug.
- Onderaan de editor zie je steeds een actuele PDF-voorbeeldweergave.

## Gegevensopslag

Tarieven, instellingen en geüploade afbeeldingen worden opgeslagen in de
`/data`-map van de add-on, die door Home Assistant persistent wordt
gehouden — je gegevens blijven dus bewaard bij herstarts en updates.

## Bijwerken

Deze add-on wordt lokaal gebouwd: de `Dockerfile` kopieert de map `app/`
tijdens het **bouwen** van de image. Vervang je bestanden zelf door een
nieuwere versie, klik dan altijd op **Herbouwen** — **Herstarten** start
alleen de bestaande, oude image opnieuw op en neemt gewijzigde bestanden
niet mee.
