# Energiemonitor Deutschland

Wie verändert sich Deutschlands Stromversorgung vom Mittag bis zum Abend? Im **Stromtag** bewegen ein Zeitregler und die automatische Wiedergabe Karte, Kennzahlen und Diagramme gemeinsam durch einen Kalendertag. Das Datum steht im Link (`?tag=2026-07-13`). Eine Grenzverbindung lässt sich auf der Karte oder in der Auswahlliste auswählen.

## Starten

Im Projektordner mit Python 3.11 oder neuer:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Ohne Datenbank liest die App direkt bei den Anbietern. Die historischen Kurven bieten Stunden-, Tages- und Wochenwerte, wahlweise als Energie oder prozentualer Anteil. Der Datumsfilter schließt den ganzen Endtag ein.

## Daten lesen

- **Stromtag:** Die vier Kennzahlen beziehen sich auf die am Regler gewählte Stunde. Stündliche Energie in MWh wird als mittlere Leistung in GW dargestellt. Wind umfasst Onshore und Offshore. Die Residuallast ist Netzlast abzüglich Wind und Solar. Eine gestrichelte Linie zeigt die veröffentlichte Prognose ab der ersten Stunde nach dem letzten Ist-Wert einer Reihe.
- **Karte:** Physikalische Flüsse in Richtung Deutschland sind positiv. Ein Stundenmittel erscheint nur, wenn alle zugehörigen Teilintervalle vorliegen. Import und Export verwenden denselben Farbton. Die Spitze zeigt die Flussrichtung, die Breite die mittlere Leistung. Die Verbindungen sind schematisch eingezeichnet. Die Skala bleibt beim Wechsel der Stunde gleich. Beim Überfahren eines Pfeils erscheinen Richtung, Leistung in MW und Messintervall. Dieselben Angaben stehen nach Auswahl eines Landes unter der Karte. „Saldo“ übernimmt die vom Anbieter veröffentlichte Summe.
- **Preisfenster:** Die Rechnung verwendet aufeinanderfolgende Viertelstundenpreise und gleichmäßigen Verbrauch. Für heute berücksichtigt sie die verbleibenden vollständigen Viertelstunden, für frühere Tage den gesamten Tag. Angezeigt wird der Börsenpreis für Deutschland/Luxemburg.
- **Historie:** Die fünf Kennzahlen verwenden dieselben vollständigen Stunden. Der Anteil der Erneuerbaren bezieht sich auf die erfasste Erzeugung, inklusive sonstiger Erneuerbarer. Für die Deckung durch Erneuerbare ist die Netzlast der Nenner. Die Diagramme zeigen GWh je gewähltem Intervall bzw. Prozent. Randwochen enthalten nur den gewählten Datumsbereich.
- **Zeit und Lücken:** Gemessen wird in festen Intervallen und angezeigt in Europe/Berlin, auch an Tagen mit 23 oder 25 Stunden. Striche und Unterbrechungen kennzeichnen fehlende Werte.

## Optionales PostgreSQL-Archiv

`SUPABASE_DB_URL` kann lokal in der ignorierten `.env` oder in der Betriebsumgebung stehen. Der Importer benötigt Schreibrechte im Schema `raw`. Für die App genügt Lesezugriff auf die Archivtabelle.

```sh
python ingest.py 2
```

Der Import legt `raw.stromtag_blocks` an, übernimmt vorhandene Blöcke aus `raw.smard_data` und aktualisiert überlappende Blöcke per Upsert. Der Workflow plant diesen Lauf stündlich, sofern das Repository-Secret `SUPABASE_DB_URL` eingerichtet ist. Fehlgeschlagene Reihen ergeben einen fehlgeschlagenen Job. Die App ergänzt fehlende Archivintervalle direkt von SMARD. Grenzflüsse kommen tagesweise von Energy-Charts. Beide Abrufe werden 15 Minuten zwischengespeichert.

## Quellen

- Erzeugung, Netzlast, Prognosen und Preise: [Bundesnetzagentur | SMARD.de](https://www.smard.de/home/datennutzung). Marktdaten unter CC BY 4.0; die Bundesnetzagentur weist bei Großhandelspreisen auf eine laufende Lizenzprüfung hin.
- Physikalische Grenzflüsse: [Energy-Charts.info](https://api.energy-charts.info/), Endpunkt `/v2/cbpf`, CC BY 4.0.
- Ländergrenzen: vereinfachter Mitteleuropa-Ausschnitt aus [Natural Earth](https://www.naturalearthdata.com/), Public Domain.
