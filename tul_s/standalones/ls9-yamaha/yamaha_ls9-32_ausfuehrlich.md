# Yamaha LS9-32 – Ausführliches Handbuch mit Praxis-Setup

---

## 1. Grundkonzept und Denkweise

### Digital vs. Analog – der wichtigste Unterschied

Wer von analogen Pulten kommt, muss eine grundlegende Umstellung vollziehen: beim analogen Pult ist der Signalweg physisch sichtbar – ein Kanal, ein Kanalzug, ein Fader. Was du siehst, ist was du hast.

Beim LS9 ist der Signalweg **virtuell**. Die physischen Fader sind nur Fenster in eine interne Signalwelt, die weit mehr Kanäle enthält als Fader vorhanden sind. Das Pult denkt in Layern, Patches und Bussen – und du musst lernen, in denselben Kategorien zu denken.

Der Vorteil: ein einziges kompaktes Gerät ersetzt Dutzende externer Prozessoren, bietet vollständige Speicherbarkeit aller Einstellungen, und lässt sich für jede Show neu konfigurieren ohne einen einzigen Patch-Stecker umzustecken.

### Die drei Welten des LS9

Das LS9 denkt in drei getrennten Welten:

**Eingangs-Welt (Input Channels):** Alles was ins Pult hineinkommt – Mikrofone, Instrumente, Playback-Quellen, Effekt-Returns. Diese Welt liegt auf den Layern 1–32 und 33–64.

**Ausgangs-Welt (Mix Buses):** Alles was das Pult nach außen schickt – der Stereo-Master, Aux-Busse für Monitore, Matrix-Busse für Verteilung. Diese Welt liegt auf dem Master-Layer.

**Patch-Welt:** Die Verbindung zwischen physischen Ein-/Ausgängen und den internen Kanälen. Hier legst du fest, welcher XLR-Eingang auf welchem internen Kanal landet – vollständig frei konfigurierbar.

---

## 2. Physische Orientierung

### Übersicht der Bedienoberfläche

| Bereich | Inhalt | Funktion |
|---|---|---|
| Ganz links | Fader-Bank 1–32 | Eingangskanäle (je nach Layer) |
| Unten links | Layer-Tasten | Umschalten zwischen 1–32 / 33–64 / Master / Custom |
| Mitte links | Display-Access-Tasten | Aufrufen von Parameterseiten im Display |
| Mitte links | Mix/Matrix-Tasten | Kontext-Umschaltung im Display |
| Mitte | LCD-Display | Parameteranzeige und Navigation |
| Mitte rechts | Gain-Regler | Preamp-Gain des gewählten Kanals |
| Mitte rechts | Mic-EQ-Regler | Schnellzugriff auf EQ-Parameter |
| Mitte rechts | Dynamics-Regler | Schnellzugriff auf Gate/Kompressor |
| Mitte rechts | Manövrierfeld + Wheel + Enter | Navigation im Display, Werte ändern |
| Rechts | Master-Fader-Bank | Bus-Fader (je nach Layer) |
| Ganz rechts | Stereo-Master-Fader | Hauptlautstärke L/R |

### Display-Navigation im Detail

Das LCD-Display ist das Herzstück der Bedienung – aber es reagiert nicht auf Touch, sondern ausschließlich auf die umliegenden Tasten und das Wheel.

**Display-Access-Tasten** (links vom Display): Jede Taste ruft eine bestimmte Parameterseite auf – z.B. EQ, Dynamics, Routing, Patch. Welche Seite erscheint, hängt zusätzlich davon ab, welcher Kanal gerade **selected** ist (leuchtende SEL-Taste am Fader).

**Mix/Matrix-Tasten** (ebenfalls links vom Display): Schalten den Kontext um. Wenn du z.B. `MIX 1` drückst, zeigt das Display die Send-Pegel aller Eingangskanäle zu Mix-Bus 1 – und die Fader der Master-Bank zeigen den Pegel dieses Sends.

**Wheel:** Ändert den Wert des markierten Parameters. Im Display ist der aktive Parameter immer hervorgehoben.

**Enter:** Bestätigt Eingaben, öffnet Untermenüs, bestätigt Recalls.

**Cursor-Tasten / Manövrierfeld:** Navigieren zwischen Parametern innerhalb einer Seite.

**Typischer Workflow:**
```
1. Kanal auswählen (SEL-Taste am Fader drücken)
2. Display-Access-Taste für gewünschten Parameter drücken
3. Mit Cursor zum Parameter navigieren
4. Mit Wheel Wert ändern
5. Enter (falls nötig)
```

---

## 3. Signalfluss im Detail

### Der vollständige Weg eines Signals

```
Physischer Eingang (XLR/TRS an der Rückseite)
  ↓
PATCH (Input Patch) – Zuweisung zu internem Kanal
  ↓
Preamp – Gain (analog), Phantom Power (+48V), Phase (ø)
  ↓
HPF – High Pass Filter (Tiefenabschnitt, schaltbar, Frequenz wählbar)
  ↓
Gate / Expander – Rauschunterdrückung bei Stille
  ↓
4-Band parametrischer EQ
  ↓
Kompressor – Dynamikkontrolle
  ↓
Insert (optional) – externer Prozessor einschleifbar
  ↓
Fader – Kanallautstärke
  ↓
Pan – Stereoposition
  ↓
ON – Kanal stumm/aktiv
  ↓
Mix-Bus-Sends – Verteilung auf Aux-Busse, Matrix, Stereo-Master
  ↓
Stereo-Master / Aux-Busse / Matrix
  ↓
GEQ (optional, auf Ausgangsbus)
  ↓
Physischer Ausgang (XLR an der Rückseite)
```

### Gate und Kompressor – Reihenfolge verstehen

Gate kommt **vor** dem Kompressor – das ist Absicht. Das Gate entscheidet zuerst ob ein Signal überhaupt durchgelassen wird (Rauschunterdrückung, Übersprechen). Erst wenn das Gate offen ist, arbeitet der Kompressor an der Dynamik des Signals.

### Insert-Punkt

Jeder Kanal hat einen Insert-Punkt zwischen Dynamics und Fader. Hier kann ein externer Prozessor (z.B. dedizierter Hardware-Kompressor) physisch eingeschleift werden. Im LS9 kann der Insert-Punkt auch auf einen der internen Effektprozessoren geroutet werden.

---

## 4. Layer-System – vollständige Erklärung

### Das Grundproblem und seine Lösung

Das LS9-32 hat 33 physische Fader. Intern verwaltet es jedoch bis zu 64 Eingangskanäle, 16 Mix-Busse, 8 Matrix-Busse, Stereo-Master, Mono-Bus und interne Effekt-Returns. Das Layer-System macht dieselben physischen Fader für all diese Signalwege nutzbar – je nach aktivem Layer zeigen sie unterschiedliche Inhalte.

### Layer 1–32

Die Mono-Eingangskanäle 1–32 auf den physischen Fadern 1–32. Das ist die primäre Eingangs-Welt – Mikrofone, Instrumente, DI-Boxen. Hier verbringt man den Großteil des Soundchecks.

### Layer 33–64

Dieselben physischen Fader, andere Inhalte: Kanäle 33–64. In diesem Bereich liegen typischerweise:

- **ST IN 1–4** – die vier Stereo-Eingangskanäle (je ein Fader pro Stereopaar)
- **Effekt-Returns** der vier internen Prozessoren
- weitere Mono-Eingangskanäle falls gepatcht

Wichtig: die Stereo-Eingangskanäle sind konzeptionell anders als Mono-Kanäle – sie haben kein separates Pan für L und R, sondern ein Width-Control, und ihr EQ arbeitet auf beiden Seiten gleichzeitig.

### Master-Layer

Die Ausgangsseite des Pultes:

- Mix 1–16 (Aux-Busse für Monitore, Effekte, Subgruppen)
- Matrix 1–8
- Stereo-Master
- Mono-Bus

Hier arbeitest du wenn du Monitorpegel anpasst, Matrix-Routing prüfst oder den Stereo-Master kontrollierst.

### Custom Fader Layer

Der mächtigste und im Live-Betrieb wichtigste Layer. Du weist jedem der 33 physischen Fader **frei** einen beliebigen internen Kanal zu – quer durch alle anderen Layer.

**Einrichten:**
```
Display-Access: USER DEFINED KEYS oder CUSTOM FADER
→ Custom Fader Layer aufrufen
→ Fader 1 auswählen → Quelle zuweisen (z.B. Input Ch 1)
→ Fader 2 auswählen → Quelle zuweisen (z.B. Input Ch 2)
→ ... usw.
→ Store
```

**Die Denkweise:** Du baust dir einmal deine persönliche Show-Ansicht zusammen – nur die Fader, die du während der Veranstaltung wirklich anfasst. Alle anderen Layer dienen dem Setup und Soundcheck. Im Betrieb wechselst du den Layer kaum noch.

### Übersicht

| Layer-Taste | Inhalt | typische Nutzung |
|---|---|---|
| 1–32 | Mono-Eingänge 1–32 | Soundcheck, vollständiger Überblick |
| 33–64 | Kanäle 33–64, Stereo-IN, Returns | Stereo-Quellen, Effekt-Returns |
| Master | Aux-Busse, Matrix, Master | Output-Kontrolle, Monitoring-Pegel |
| Custom | frei belegbar | Show-Betrieb |

---

## 5. Preamp und Gain-Staging

### Gain-Staging – warum es wichtig ist

Gain-Staging bedeutet: an jedem Punkt des Signalwegs einen gesunden Pegel zu haben – nicht zu leise (Rauschen), nicht zu laut (Verzerrung / Clipping). Beim LS9 gibt es zwei Gain-Stufen:

1. **Analoger Preamp-Gain** (Gain-Regler rechts vom Display): verstärkt das analoge Signal vor der A/D-Wandlung. Das ist die wichtigste Einstellung – hier entscheidet sich die Grundqualität.
2. **Digitaler Channel Gain** (im Display): eine zusätzliche digitale Verstärkung nach der Wandlung. Sparsam einsetzen.

### Richtige Einstellung des Preamp-Gain

Ziel: der Peakmeter des Kanals soll bei normaler Lautstärke der Quelle im Bereich **−18 bis −12 dBFS** liegen, mit gelegentlichen Peaks bis maximal −6 dBFS. Das lässt genug Headroom für laute Momente ohne Clipping.

**Vorgehen:**
1. Kanal auswählen (SEL drücken)
2. Sprecher/Instrument normal spielen lassen
3. Gain-Regler drehen bis Pegel im Zielbereich
4. Auf Clip-LED achten – wenn sie leuchtet, Gain reduzieren

### Phantom Power

Kondensatormikrofone benötigen +48V Phantom Power. Beim LS9 wird sie **pro Kanal** geschaltet – nicht global. Wichtig: Phantom Power immer erst einschalten wenn das Mikrofon angeschlossen ist, und vor dem Ausstecken wieder ausschalten. Dynamic-Mikrofone werden durch Phantom Power in der Regel nicht beschädigt, aber es ist gute Praxis sie dort abzuschalten wo sie nicht gebraucht wird.

---

## 6. EQ – 4-Band parametrisch

### Aufbau

Jeder Mono-Eingangskanal hat einen 4-Band parametrischen EQ plus einen schaltbaren High Pass Filter (HPF):

| Band | Typ | Frequenzbereich |
|---|---|---|
| HPF | Hochpassfilter | 20 Hz – 600 Hz (schaltbar) |
| LOW | Low Shelf oder parametrisch | 20 Hz – 2 kHz |
| LOW MID | parametrisch | 20 Hz – 20 kHz |
| HIGH MID | parametrisch | 20 Hz – 20 kHz |
| HIGH | High Shelf oder parametrisch | 20 Hz – 20 kHz |

### HPF – fast immer einschalten

Für Sprachmikrofone: HPF bei ca. 80–120 Hz einschalten. Das entfernt Trittschall, Windgeräusche und Rumpeln ohne die Sprache zu beeinflussen. Für Handmikrofone eher 100–150 Hz da Nahbesprechungseffekt (Bassanhebung bei Nähe) zusätzlich auftreten kann.

### EQ für Sprache – Orientierung

- **Tiefmitten 200–400 Hz:** Mulmigkeit hier reduzieren falls der Klang "boxig" wirkt
- **Präsenz 2–5 kHz:** leichte Anhebung verbessert Verständlichkeit
- **Brillanz 8–12 kHz:** Luft und Klarheit, vorsichtig einsetzen
- **Sibilanz 6–10 kHz:** bei Zischlauten hier eine Delle schneiden

**Grundregel:** EQ subtraktiv einsetzen – lieber wegnehmen was stört als anheben was fehlt.

---

## 7. Dynamics – Gate und Kompressor

### Gate

Das Gate unterdrückt das Signal wenn es unter einen einstellbaren Schwellwert fällt. Für Sprachmikrofone in lauter Umgebung sehr nützlich – es schaltet den Kanal quasi stumm wenn niemand spricht.

**Parameter:**
- **Threshold:** ab welchem Pegel öffnet das Gate (in dBFS)
- **Range:** wie stark wird das Signal gedämpft wenn das Gate zu ist (in dB)
- **Attack:** wie schnell öffnet das Gate
- **Hold:** wie lange bleibt es offen nach Unterschreiten des Threshold
- **Decay:** wie schnell schließt es danach

**Einstellung für Handmikrofone:**
- Threshold: ca. −40 bis −30 dBFS (testen!)
- Range: 40–60 dB
- Attack: schnell (1–5 ms)
- Hold: 200–500 ms (verhindert "Pumpen" bei kurzen Pausen)
- Decay: mittel (100–300 ms)

**Vorsicht bei Handmikrofonen:** Das Gate kann bei wechselnden Sprechern und unterschiedlichen Mikrofonabständen unzuverlässig sein. Lieber etwas zu niedrigen Threshold als zu hohen – ein zu aggressives Gate schneidet Wortanfänge ab.

### Kompressor

Der Kompressor reduziert den Dynamikunterschied zwischen leisen und lauten Momenten – wichtig wenn verschiedene Sprecher das Mikrofon unterschiedlich laut besprechen.

**Parameter:**
- **Threshold:** ab welchem Pegel setzt Kompression ein
- **Ratio:** Stärke der Kompression (z.B. 3:1 = moderat, 8:1 = stark)
- **Attack:** wie schnell reagiert der Kompressor
- **Release:** wie schnell lässt er wieder los
- **Gain:** Makeup-Gain um den Pegelabfall zu kompensieren

**Einstellung für wechselnde Sprecher:**
- Threshold: ca. −18 dBFS
- Ratio: 3:1 bis 4:1
- Attack: 10–30 ms (zu schnell klingt unnatürlich)
- Release: 100–300 ms
- Gain: so einstellen dass der Ausgangspegel dem Eingangspegel bei Normallautstärke entspricht

---

## 8. Mix-Busse und Aux-Sends

### Das Bus-Konzept

Jeder Eingangskanal kann sein Signal an mehrere Busse gleichzeitig schicken – mit individuell einstellbarem Pegel pro Bus. Das ermöglicht:

- verschiedene Monitormixe für verschiedene Bühnenpositionen
- Subgruppen (z.B. alle Mikrofone auf einen Bus für gemeinsame Bearbeitung)
- Effekt-Sends (Kanal schickt etwas Hall)
- Matrix-Routing für Verteilung auf mehrere Ausgänge

### Pre-Fader vs. Post-Fader

**Post-Fader Send:** der Send-Pegel ist abhängig vom Kanal-Fader. Wenn du den Kanal leiser machst, wird auch der Send leiser. Typisch für Effekte (Hall soll mitatmen).

**Pre-Fader Send:** der Send-Pegel ist unabhängig vom Kanal-Fader. Der Monitor-Mix bleibt gleich egal was du am FOH-Fader machst. **Für Monitoring immer Pre-Fader verwenden.**

### Send-Pegel einstellen

**Methode 1 – über die Master-Sektion:**
```
Mix/Matrix-Taste für gewünschten Bus drücken (z.B. MIX 1)
→ Fader der Master-Sektion zeigen jetzt Send-Pegel aller Kanäle zu MIX 1
→ Fader bewegen = Send-Pegel des jeweiligen Kanals zu diesem Bus
```

**Methode 2 – im Display:**
```
Kanal auswählen (SEL)
→ Display-Access: MIX SEND
→ Send-Pegel zu allen Bussen sichtbar
→ mit Cursor und Wheel einstellen
```

---

## 9. Scenes – Speichern und Abrufen

### Was eine Scene speichert

Eine Scene speichert den **vollständigen Zustand** des Pultes:
- alle Fader-Positionen
- alle EQ- und Dynamics-Einstellungen
- alle Send-Pegel
- alle Routing-Einstellungen
- alle Patch-Zuweisungen
- alle Effekt-Einstellungen

**Ausnahme:** Preamp-Gain kann von Scene-Recalls ausgenommen werden (Recall Safe) – sinnvoll wenn der Gain physisch von Hand eingestellt wurde und stabil bleiben soll.

### Speichern

```
SCENE-Taste → Store → 
Nummer wählen (1–300) → 
Name eingeben (Wheel zum Buchstaben wählen, Cursor zum nächsten) → 
Enter
```

### Abrufen

```
SCENE-Taste → Recall → 
Nummer wählen → 
Enter (Bestätigung)
```

### Scene Recall Safe

Schützt einzelne Parameter oder ganze Kanäle vor dem Überschreiben durch einen Scene-Recall:

```
SCENE → Recall Safe → 
Kanal oder Parameter auswählen → 
Safe aktivieren
```

Typische Anwendung: Gain auf Recall Safe setzen – der Gain bleibt immer so wie er beim Soundcheck physisch eingestellt wurde, auch wenn du zwischen Scenes wechselst.

---

## 10. Interner Effektprozessor

### Vier Prozessoren im Rack-Prinzip

Das LS9 hat vier interne Effektprozessoren. Sie funktionieren nach dem **virtuellen Rack-Prinzip**: du "bestückst" jeden Slot mit einem Effekttyp (Reverb, Delay, Chorus, etc.) und verbindest ihn dann mit dem Signalweg.

### Typisches Send/Return-Routing für Hall

```
Eingangskanal → Send auf Aux-Bus X (Post-Fader) → 
Aux-Bus X → Effektprozessor 1 (Eingang) → 
Effektprozessor 1 (Ausgang) → Stereo-Return-Kanal → 
Return-Kanal → Stereo-Master
```

Der Eingangskanal schickt einen Teil seines Signals (Send-Pegel) an den Hall. Der Hall-Return wird auf einem Stereo-Eingangskanal empfangen und geht in den Mix.

### Einrichten

```
Display-Access: EFFECT → 
Slot 1–4 auswählen → 
Effekttyp wählen (z.B. REV-X Hall) → 
Parameter einstellen (Decay, Pre-Delay etc.) → 
Input/Output Routing prüfen
```

---

## 11. GEQ – Grafischer Equalizer

### Prinzip

Der GEQ arbeitet auf den **Ausgangsbussen** – nicht auf einzelnen Eingangskanälen. Er dient primär der Raumkorrektur: Frequenzen die im Raum aufgrund der Akustik oder der Lautsprechercharakteristik zu laut oder zu leise sind, werden ausgeglichen.

Das LS9 hat GEQ-Module im Rack-Prinzip – sie müssen einem Bus zugewiesen werden bevor sie aktiv sind.

### Einrichten

```
Display-Access: GEQ/EQ → 
GEQ-Rack aufrufen → 
GEQ-Modul einem Bus zuweisen → 
Bus auswählen → 
Fader der Bank werden zu GEQ-Bändern (31 Bänder, −12 bis +12 dB)
```

### Grundregel

GEQ subtraktiv einsetzen – Frequenzen die zu laut sind absenken, nicht andere anheben. Ein flacher GEQ ist fast immer besser als viele starke Eingriffe.

---

## 12. Praxis-Setup: Veranstaltung mit Sprache, Stereo-Einspielung und Monitoring

### Übersicht des Setups

| Kanal | Quelle | Typ | Verwendung |
|---|---|---|---|
| CH 1 | Handmikrofon 1 | dynamisch, Mono | Sprecher/Moderator |
| CH 2 | Handmikrofon 2 | dynamisch, Mono | Sprecher/Gast |
| CH 3 | Handmikrofon 3 | dynamisch, Mono | Sprecher/Gast |
| CH 4 | Handmikrofon 4 | dynamisch, Mono | Reserve/Moderator 2 |
| CH 5 | Kommunikation Kamera | dynamisch, Mono | Backstage/Kameramann |
| CH 6 | Kommunikation Technik | dynamisch, Mono | Backstage/Technik |
| ST IN 1 | Computer 1 L+R | Stereo | Playback/Präsentation |
| ST IN 2 | Computer 2 L+R | Stereo | Playback/Backup |
| MIX 1 | Monitor Master | Stereo-Bus | Abhörmonitor für Technik |
| MIX 2 | Komm-Box Kamera | Mono-Bus | Kleine Monitorbox Kamera |
| MIX 3 | Komm-Box Technik | Mono-Bus | Kleine Monitorbox Technik |

---

### Schritt 1: Input Patch

Zuerst die physischen Eingänge den internen Kanälen zuweisen:

```
Display-Access: PATCH → INPUT PATCH →
XLR Input 1 → CH 1
XLR Input 2 → CH 2
XLR Input 3 → CH 3
XLR Input 4 → CH 4
XLR Input 5 → CH 5
XLR Input 6 → CH 6
XLR Input 7/8 → ST IN 1 (L/R)
XLR Input 9/10 → ST IN 2 (L/R)
```

---

### Schritt 2: Output Patch

Die Ausgangsbuse auf physische Ausgänge legen:

```
Display-Access: PATCH → OUTPUT PATCH →
Stereo Master L/R → XLR Out 1/2 (Hauptbeschallung)
MIX 1 L/R → XLR Out 3/4 (Monitor Technik, Stereo)
MIX 2 → XLR Out 5 (Komm-Box Kamera, Mono)
MIX 3 → XLR Out 6 (Komm-Box Technik, Mono)
```

---

### Schritt 3: Preamp und Grundeinstellungen – Sprachmikrofone (CH 1–4)

Für jeden der vier Sprachkanäle:

```
SEL-Taste CH 1 drücken
→ Gain-Regler: Sprecher sprechen lassen, auf −18 bis −12 dBFS pegeln
→ Phantom Power: NEIN (dynamisches Mikrofon)
→ HPF einschalten: ca. 120 Hz (Handmikrofon, Nahbesprechungseffekt)
→ EQ: zunächst flat lassen, später nach Klang anpassen
→ Gate: Threshold ca. −35 dBFS, Hold 300 ms, Range 50 dB
→ Kompressor: Threshold −18 dBFS, Ratio 3:1, Attack 20 ms, Release 200 ms
→ Fader: auf 0 dB (Nominalposition)
→ ON: einschalten
→ Pan: Center (Mono-Signal auf Stereo-Master)
```

Gleiche Prozedur für CH 2, 3, 4.

**Wichtig bei Handmikrofonen:** Gate-Threshold nicht zu aggressiv setzen – besser etwas zu niedrig als Wortanfänge abschneiden. Im Zweifel Gate ganz deaktivieren und lieber auf Fader-Disziplin setzen.

---

### Schritt 4: Grundeinstellungen – Kommunikationskanäle (CH 5–6)

Die Kommunikationskanäle sind technisch ähnlich wie die Sprachkanäle, aber mit anderen Zielen:

```
SEL-Taste CH 5 drücken
→ Gain: Kameramann sprechen lassen, auf −18 bis −12 dBFS pegeln
→ HPF: ca. 150 Hz (kleine Monitorboxen brauchen keine Bässe)
→ Gate: moderat, Threshold −30 dBFS
→ Kompressor: etwas stärker, Ratio 4:1 (Pegel soll konstant sein)
→ Fader: auf 0 dB
→ ON: einschalten
```

**Wichtig:** CH 5 und CH 6 werden **nicht** auf den Stereo-Master geroutet – sie sollen nur auf den jeweiligen Kommunikations-Bus gehen. Das Routing wird in Schritt 6 eingestellt.

---

### Schritt 5: Grundeinstellungen – Stereo-Einspielungen (ST IN 1–2)

```
Layer 33–64 aufrufen
SEL-Taste ST IN 1 drücken
→ Gain: Computerpegel prüfen, Ziel −18 bis −12 dBFS
→ HPF: aus (Musik/Playback soll vollständig übertragen werden)
→ EQ: flat
→ Dynamics: aus (Playback ist bereits mastered)
→ Fader: auf 0 dB
→ ON: einschalten
→ Pan: L/R voll (Stereobreite)
```

Gleiche Prozedur für ST IN 2 (Backup-Computer).

**Empfehlung:** ST IN 2 zunächst auf ON lassen aber Fader ganz unten – so kann er schnell hochgezogen werden wenn Computer 1 ausfällt.

---

### Schritt 6: Bus-Routing – wer geht wohin

#### Sprachmikrofone CH 1–4: auf Stereo-Master und Monitor MIX 1

```
MIX-Taste für STEREO drücken
→ CH 1–4 Sends aufdrehen (auf 0 dB oder nach Bedarf)
→ MIX 1-Taste drücken
→ CH 1–4 Sends auf MIX 1 aufdrehen (Pre-Fader einstellen!)
```

Pre-Fader für MIX 1 einstellen:
```
CH 1 SEL → Display-Access: MIX SEND → 
MIX 1 auswählen → PRE auf ON setzen
```
Für CH 2–4 wiederholen.

#### Kommunikationskanäle CH 5–6: NUR auf eigene Komm-Busse

```
CH 5: Send auf MIX 2 aufdrehen (Pre-Fader), Send auf Stereo-Master = 0
CH 6: Send auf MIX 3 aufdrehen (Pre-Fader), Send auf Stereo-Master = 0
```

Sicherstellen dass CH 5 und 6 **keinen** Send auf den Stereo-Master haben – die Kommunikation soll nicht ins Saalpublikum.

#### Stereo-Einspielungen ST IN 1–2: auf Stereo-Master, optional auf Monitor

```
ST IN 1: Send auf Stereo-Master aufdrehen
ST IN 1: Send auf MIX 1 nach Bedarf (Techniker soll Playback hören)
ST IN 2: gleich wie ST IN 1
```

---

### Schritt 7: Monitor-Mischung einrichten

#### MIX 1 – Abhörmonitor Technik (Stereo)

Der Technik-Monitor soll alles hören was im Saal läuft:

```
MIX 1-Taste drücken
→ CH 1–4 Sends: aufdrehen (Sprecher)
→ ST IN 1–2 Sends: aufdrehen (Einspielung)
→ CH 5–6 Sends: nach Bedarf (Kommunikation mithören?)
→ MIX 1 Fader (Master-Sektion): auf 0 dB
```

#### MIX 2 – Komm-Box Kameramann (Mono)

Der Kameramann hört nur den Kommunikationskanal der Technik:

```
MIX 2-Taste drücken
→ CH 6 Send: aufdrehen (Technik spricht zum Kameramann)
→ alle anderen Sends: zu (0)
→ MIX 2 Fader: auf 0 dB
```

#### MIX 3 – Komm-Box Technik (Mono)

Die Technik hört den Kameramann:

```
MIX 3-Taste drücken
→ CH 5 Send: aufdrehen (Kameramann spricht zur Technik)
→ alle anderen Sends: zu (0)
→ MIX 3 Fader: auf 0 dB
```

---

### Schritt 8: Custom Fader Layer einrichten

Für den Show-Betrieb bauen wir uns eine übersichtliche Fader-Belegung:

| Physischer Fader | Quelle | Funktion |
|---|---|---|
| 1 | CH 1 | Handmikrofon 1 |
| 2 | CH 2 | Handmikrofon 2 |
| 3 | CH 3 | Handmikrofon 3 |
| 4 | CH 4 | Handmikrofon 4 (Reserve) |
| 5 | CH 5 | Komm Kamera |
| 6 | CH 6 | Komm Technik |
| 7 | – | (frei) |
| 8 | ST IN 1 | Computer 1 |
| 9 | ST IN 2 | Computer 2 |
| 10 | – | (frei) |
| 11 | MIX 1 | Monitor Technik |
| 12 | MIX 2 | Komm-Box Kamera |
| 13 | MIX 3 | Komm-Box Technik |

```
Custom Fader Layer aufrufen →
Fader 1 → CH 1 zuweisen
Fader 2 → CH 2 zuweisen
... usw. →
Store
```

Im Show-Betrieb arbeitest du ausschließlich in diesem Layer.

---

### Schritt 9: Scene speichern

Wenn alles eingestellt und geprüft ist:

```
SCENE → Store → Scene 1 → Name: "Soundcheck" → Enter
```

Vor Show-Beginn nochmals speichern:

```
SCENE → Store → Scene 2 → Name: "Show Start" → Enter
```

Bei mehreren Programmpunkten mit unterschiedlichen Anforderungen weitere Scenes anlegen.

---

### Schritt 10: Gain-Recall-Safe setzen

Damit beim Scene-Wechsel der manuell eingestellte Gain nicht überschrieben wird:

```
SCENE → Recall Safe → 
HA GAIN für alle Eingangskanäle auf Safe setzen
```

---

### Checkliste vor Show-Beginn

- [ ] Alle Mikrofone auf Signalfluss geprüft (klopfen, sprechen)
- [ ] Gain aller Kanäle eingestellt
- [ ] HPF auf allen Sprachkanälen aktiv
- [ ] Gate und Kompressor geprüft (kein ungewolltes Abreißen)
- [ ] Stereo-Einspielungen geprüft (Pegel, Stereobreite)
- [ ] Monitor MIX 1 geprüft (Technik hört alles)
- [ ] Komm-Boxen geprüft (Kameramann und Technik hören einander)
- [ ] CH 5 und 6 **nicht** auf Stereo-Master geroutet – bestätigt
- [ ] Custom Layer eingerichtet und aktiv
- [ ] Scene "Show Start" gespeichert
- [ ] Gain Recall Safe aktiv

---

## 13. Weiterführende Themen

- **Dante-Netzwerkaudio**: falls eine Dante-MY16-AUD Erweiterungskarte eingebaut ist, können Signale über Netzwerk von und zu Stagebox, Aufnahmesystem oder weiteren Pulten geroutet werden
- **Remote-Preamp-Steuerung**: Yamaha Rio-Stageboxen können direkt vom LS9 aus gesteuert werden – Gain, Phantom, Phase, alles remote
- **User-defined Keys**: die programmierbaren Tasten können häufig genutzte Funktionen (z.B. Talkback, Oszillator, Scene-Recall) auf einen Tastendruck legen
- **Oscillator / Signalgenerator**: interner Sinus-/Pink-Noise-Generator für Pegelabgleich mit Lautsprechersystem und Messmikrofon
- **Matrix-Routing**: für komplexere Verteilung (z.B. Aufnahme, Lobby-Beschallung, Dolmetscher-Feed) bietet die 8-fach Matrix flexible Möglichkeiten
- **Ganged Sends**: mehrere Kanäle gleichzeitig in einem Monitor-Mix anpassen – sinnvoll wenn z.B. alle Sprecher-Mikrofone gemeinsam lauter/leiser im Monitor werden sollen

---

*Yamaha LS9-32 Ausführliches Handbuch – erstellt April 2026*
