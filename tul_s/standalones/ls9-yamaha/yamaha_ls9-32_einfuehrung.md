# Yamaha LS9-32 – Stufenweise Einführung

---

## Stufe 1: Grundkonzept und Orientierung

Die LS9-32 ist ein **digitales Mischpult** mit 32 Mono-Eingangskanälen und 8 Stereo-Eingangskanälen, intern auf einer einzigen Fader-Bank mit **Layering** organisiert.

**Wichtigste Besonderheit gegenüber analogen Pulten:**
- Es gibt mehr Kanäle als physische Fader – Navigation über **Layer**
- Alles wird intern gespeichert (Scenes)
- Der Signalweg ist fest digital, aber vollständig konfigurierbar

### Physische Orientierung

| Bereich | Inhalt |
|---|---|
| Links | Eingangskanäle (Fader-Bank) |
| Mitte links | Display-Access-Tasten, Mix/Matrix-Tasten |
| Display | LCD-Display, navigiert über Wheel + Enter + umliegende Tasten |
| Mitte rechts | Gain-Regler, Mic-EQ, Dynamics-Drehregler, Manövrierfeld |
| Rechts | Master-Sektion mit Aux/Bus-Fadern |
| Ganz rechts | Master-Fader |

---

## Stufe 2: Signalfluss verstehen

```
Eingang (XLR/TRS)
  → Preamp (Gain, Phantom Power)
  → EQ (4-Band parametrisch)
  → Dynamics (Gate + Kompressor)
  → Fader + Pan
  → Mix-Busse / Aux-Sends
  → Master L/R
```

Jeder Kanal hat seinen eigenen EQ und Dynamics – kein externes Rack nötig für die Grundbearbeitung.

---

## Stufe 3: Erster Umgang – einen Kanal in Betrieb nehmen

1. **Eingang patchen**: `PATCH` → Input Patch → Kanal einem physischen Eingang zuweisen
2. **Preamp einstellen**: Kanal auswählen → Gain-Regler (rechte Sektion) bis Pegelanzeige bei Sprache/Instrument ca. −18 bis −12 dBFS im Normalbereich
3. **Phantom Power**: falls Kondensatormikrofon → `+48V`-Taste am Kanal
4. **Kanal aufmachen**: Fader hochziehen, `ON`-Taste leuchtet
5. **Auf Master routen**: standardmäßig ist jeder Kanal auf den Stereo-Master geroutet

---

## Stufe 4: Display-Navigation

Das LCD-Display wird **nicht per Touch** bedient, sondern über:

- **Display-Access-Tasten** (links vom Display): rufen bestimmte Parameterseiten auf
- **Mix/Matrix-Tasten** (links vom Display): wechseln den Kontext (Mix-Busse, Matrix)
- **Wheel** (rechts vom Display): Wert ändern / in Listen scrollen
- **Enter-Taste**: Auswahl bestätigen
- **Cursor-Tasten / Manövrierfeld**: Navigation innerhalb der Seiten

Typischer Workflow: Display-Access-Taste drücken → mit Cursor zur gewünschten Stelle → mit Wheel Wert ändern → Enter.

---

## Stufe 5: Layer-System

### Das Grundprinzip

Die LS9-32 hat physisch **33 Fader** (32 Kanal-Fader + 1 Master). Intern verwaltet sie aber weit mehr Signalwege – Eingänge, Busse, Returns, Effekte usw. Das Layer-System löst diesen Widerspruch: dieselben physischen Fader zeigen je nach aktivem Layer unterschiedliche Kanäle.

Umgeschaltet wird über die **vier Layer-Tasten links unten vom Display**:

---

### Layer 1–32 (Eingangskanäle, erste Hälfte)

Die Mono-Eingangskanäle 1–32 liegen auf den physischen Fadern 1–32. Das ist die klassische "Eingangs-Welt" – Mikrofone, Instrumente, Playback-Quellen.

---

### Layer 33–64 (Eingangskanäle, zweite Hälfte)

Auf denselben physischen Fadern liegen hier die Kanäle 33–64. Das sind nicht nur "weitere Eingänge", sondern auch:

- **Stereo-Eingangskanäle** (ST IN 1–4)
- **Effekt-Returns** der internen Prozessoren
- weitere interne Signalquellen

Die Denkweise: Layer 1–32 und 33–64 bilden zusammen die gesamte **Eingangsseite** des Pultes.

---

### Master-Layer

Hier liegt die **Ausgangsseite** – alles was das Pult nach außen schickt:

- Mix-Busse (Aux 1–16)
- Matrix-Busse
- Stereo-Master
- Mono-Bus

Der Master-Layer ist also die Welt der Sends und Outputs, nicht der Quellen.

---

### Custom Fader Layer

Das ist der **freie Arbeitsbereich** – und das mächtigste Layer-Konzept der LS9.

Du kannst dir beliebige Kanäle aus allen anderen Layern auf die 33 Fader legen, quer durch alle Welten. Zum Beispiel:

- Fader 1–8 = die wichtigsten Gesangsmikrofone aus Layer 1–32
- Fader 9–12 = Effekt-Returns aus Layer 33–64
- Fader 13–16 = Monitor-Busse aus dem Master-Layer
- Fader 17 = Stereo-Master

**Die Denkweise dahinter:** Im Live-Betrieb willst du nicht während der Show zwischen Layern blättern. Du baust dir einmal im Custom Layer deine persönliche **Show-Ansicht** zusammen – nur die Dinge, die du wirklich anfasst – und arbeitest dann fast ausschließlich dort. Die anderen Layer sind für Soundcheck, Setup und Ausnahmesituationen.

**Custom Layer einrichten:**
```
USER DEFINED → Custom Fader Layer → Fader auswählen → 
Quelle zuweisen (Kanal, Bus, Return) → Enter
```

---

### Übersicht

| Layer-Taste | Inhalt | typische Nutzung |
|---|---|---|
| 1–32 | Mono-Eingänge 1–32 | Soundcheck, vollständiger Überblick |
| 33–64 | Eingänge 33–64, Stereo-IN, Returns | Ergänzende Quellen |
| Master | Aux-Busse, Matrix, Master | Output-Kontrolle, Monitoring |
| Custom | frei belegbar | Show-Betrieb |

---

## Stufe 6: Scenes (Szenen)

Das mächtigste Feature für den Live-Einsatz – eine Scene speichert den **kompletten Zustand** des Pultes.

**Speichern:**
```
SCENE → Store → Name vergeben → Enter
```

**Abrufen:**
```
SCENE → Recall → gewünschte Scene wählen → Enter
```

**Scene Recall Safe**: einzelne Parameter oder Kanäle vom Recall ausschließen (z.B. Gain bleibt immer physisch eingestellt).

**Empfohlene Struktur:**
- Scene 1 = Soundcheck-Zustand
- Scene 2 = Show-Beginn
- weitere Scenes pro Programmpunkt

---

## Stufe 7: Aux-Sends (Monitoring)

Für Bühnenmonitore oder Effektgeräte:

- Aux 1–8 sind typische Monitor-Wege
- Pro Kanal: `SEND`-Taste drücken → Aux-Sends erscheinen auf den Fadern der Master-Sektion
- Alternativ: Kanal auswählen → im Display MIX SEND-Seite aufrufen

**Pre/Post-Fader** ist pro Aux-Bus umschaltbar – für Monitore immer **Pre-Fader**.

---

## Stufe 8: Interner Effektprozessor

Die LS9-32 hat **4 interne Effektprozessoren** (Reverb, Delay etc.):

- Routing: Ein Effekt wird typisch über einen Aux-Bus angesteuert (Send/Return-Prinzip)
- Im Display: `EFFECT` → Effekttyp wählen → Parameter mit Wheel einstellen
- Return des Effekts auf einen freien Stereo-Eingangskanal routen

---

## Stufe 9: GEQ (Grafischer Equalizer)

Für Raumkorrektur auf den Hauptausgängen:

- 31-Band GEQ verfügbar auf allen Mix-Bussen
- Im Display: `GEQ` → Bus auswählen
- Die Fader werden zu GEQ-Bändern (−12 bis +12 dB)
- **Rack-Konzept**: GEQs sind wie einsteckbare Module organisiert – müssen zuerst einem Bus zugewiesen werden

---

## Weiterführende Themen

- **Dante-Netzwerkaudio** (falls Dante-MY16-AUD Karte eingebaut)
- **Remote-Preamp-Steuerung** über Rio-Stageboxen
- **User-defined Keys**: frei belegbare Tasten für häufige Funktionen
- **Oscillator / Signalgenerator** für Pegelabgleich
- **Monitor-Mischung mit ganged Sends** (mehrere Kanäle gleichzeitig)

---

*Yamaha LS9-32 Einführung – erstellt April 2026*
