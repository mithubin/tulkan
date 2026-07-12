# Zeitgefilterter Graph – Plankonzept

## Ziel

Ein interaktiver Netzwerkgraph des Lexikons, der mit einem parametrischen Zeitfilter (Slider + Q-Regler) Karten ein- und ausblendet, die im gewählten Zeitfenster *wirksam* sind. Kein neues Tool-Ökosystem – eine einzige HTML-Datei, lokal im Browser.

---

## Visualisierungsmodell

**Zeitachse:** ca. 1700–2030 (Abdeckung des Vaults)

**Slider** = Zentrum des Zeitfensters ("wo schaue ich hin")

**Q-Regler** = Breite des Fensters ("wie scharf zoome ich")
- Niedriger Q (~0.1): breite Gaußglocke, ~100–200 Jahre sichtbar – strukturelle Übersicht
- Hoher Q (~2.0): enge Glocke, ~10–30 Jahre – fokussierter Moment

**Node-Opacity** folgt der Gaußkurve über den Wirkungszeitraum der Karte:
- `opacity = max(gauss(wirkung_start), gauss(wirkung_ende))`
- Karten mit langer Wirkungsdauer (z.B. Institutionen) bleiben über einen weiten Bereich sichtbar
- Kurzlebige Ereignisse erscheinen nur in einem engen Fenster

**Kanten** (Wikilinks) werden proportional zum Produkt der verbundenen Node-Opacities sichtbar.

---

## Semantik: `wirkung_start` / `wirkung_ende`

Nicht Geburt/Tod oder Gründung/Auflösung, sondern: **Beginn und Ende der Relevanz für die Machtstruktur, die der Vault dokumentiert.**

Beispiele:
- Rockefeller Sr.: `wirkung_start: 1870` (Standard Oil) / `wirkung_ende: 1937` (Tod)
- Standard Oil: `wirkung_start: 1870` / `wirkung_ende: 1911` (formal), aber Nachfolger weiter aktiv
- NSSM 200: `wirkung_start: 1974` / `wirkung_ende: 1974` (Punkt-Ereignis)
- Council on Foreign Relations: `wirkung_start: 1921` / `wirkung_ende: ~` (ongoing)
- IG Farben / Rockefeller-Partnerschaft: `wirkung_start: 1929` / `wirkung_ende: 1952`

**Approx-Flag:** Wo unklar, wird `~` oder Jahrzehnt-Angabe eingetragen (`1920er`). Das Tool rundet auf Mittelpunkt des Jahrzehnts. Keine Vollständigkeit nötig – fehlende Werte = Karte bleibt ungefiltert sichtbar (Fallback).

**Kein Recherche-Aufwand** für jeden Eintrag nötig: Die Epoche-Tags (`epoche/jahrhundertwende` etc.) können als Näherungswerte automatisch befüllt werden, bis genauere Werte eingetragen werden.

---

## Vault-Zugang: Echtzeit oder Export?

**Antwort: Echtzeit, ohne Server.**

Moderne Browser (Chrome/Edge) unterstützen die **File System Access API**:
```
[Vault-Ordner öffnen] → Browser liest .md-Dateien direkt vom Dateisystem
```
Ablauf:
1. HTML-Datei lokal öffnen
2. Button "Vault öffnen" → Browser-Dialog → Ordner `lexikon/` wählen
3. Tool parst alle `.md`-Dateien im Browser-Speicher, extrahiert Frontmatter + Wikilinks
4. Graph rendert sofort
5. Bei Änderungen im Vault: Browser-Tab neu laden → aktueller Stand

Kein Python-Server, kein Export-Skript, kein separater Build-Schritt. Die `.md`-Dateien *sind* die Datenquelle.

**Einschränkung:** Nur Chrome/Edge (Firefox unterstützt die API noch nicht vollständig). Für Firefox-Kompatibilität: einfaches Python-Skript als einmaligen Export-Step.

---

## Technische Architektur

```
lexikon/**/*.md
      │
      ▼ (File System Access API, im Browser)
  Parser (JS)
  ─ Frontmatter: type, wirkung_start, wirkung_ende, epoche, tags
  ─ Wikilinks: [[...]] → Kanten
      │
      ▼
  nodes.json + edges.json (in-memory)
      │
      ▼
  D3.js v7 Force Graph
  ─ Node-Farbe: type (person/organisation/ereignis) + epoche-Tag
  ─ Node-Opacity: Gaußfilter(slider_center, Q, wirkung_start, wirkung_ende)
  ─ Edge-Opacity: min(opacity_A, opacity_B)
  ─ Node-Größe: Degree (Anzahl Wikilinks)
      │
      ▼
  UI-Elemente
  ─ Zeitachse-Slider (1700–2030)
  ─ Q-Regler (logarithmisch, 0.05–3.0)
  ─ Anzeige: aktuell sichtbare Karten (n=...)
  ─ Klick auf Node: öffnet Markdown-Datei (falls Browser-API verfügbar)
```

---

## Umsetzungsphasen

### Phase 1: Frontmatter-Normalisierung (~1h)
Python-Skript über alle 191 Karten:
- Ableitung von `wirkung_start` aus vorhandenen Feldern (`aktiv:`, `gegründet:`, `datum:`)
- Epochen-Mapping als Fallback (z.B. `epoche/jahrhundertwende` → `wirkung_start: 1880`)
- Manuell-Flag für Karten ohne auflösbares Datum

### Phase 2: HTML/D3-Visualisierung (~4–6h)
- Selbstständige HTML-Datei (`zeitgraph.html`) im Vault-Root oder `pyramidofpower/`
- File System Access API + Frontmatter-Parser
- D3 Force Graph mit Gaußfilter
- Slider + Q-Regler UI

### Phase 3: Feintuning
- Farb-Schema aus bestehenden Epochen-Tags
- Hover-Tooltip mit Kurzinfos (type, wirkung, folge)
- Optional: "Pfad zwischen zwei Knoten hervorheben"

---

## Offene Fragen / Entscheidungen

1. **Ongoing-Institutionen** (CFR, Rockefeller Foundation, WEF): `wirkung_ende: 2030` oder `null`? → Vorschlag: `null` = immer sichtbar wenn Q < 0.5, sonst ab wirkung_start
2. **Wirkung vs. Gründung**: Standard Oil ist 1870–1911, aber Nachfolger (Exxon, Chevron) sind separate Karten – verketten oder trennen?
3. **Mehrere Wirkungsphasen** (z.B. Kissinger: aktiv 1969–1977, dann wieder ab 2000er als Berater): Einzelfeld genügt vorerst, Erweiterung möglich
