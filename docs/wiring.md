# Haro — Schema di collegamento elettrico

Schema di cablaggio per collegare i componenti hardware al Raspberry Pi 3B+
tramite una breadboard (basetta forata da prototipazione), secondo
l'architettura descritta in
[`docs/superpowers/specs/2026-09-02-haro-robot-design.md`](superpowers/specs/2026-09-02-haro-robot-design.md).

## Componenti collegati in questo schema

| Componente | Funzione | Bus |
|---|---|---|
| INMP441 | Microfono MEMS I2S | I2S (ingresso) |
| MAX98357A + cassa 8Ω 2W | Amplificatore Classe D I2S | I2S (uscita) |
| SSD1306 0.96" OLED | Display faccina | I2C |

**Non cablati in questo schema** (componenti disponibili ma esclusi dal
design, vedi spec): sound sensor, i 2 OLED di scorta.

## Riferimento pin Raspberry Pi 3B+ (header 40 pin)

Solo i pin usati in questo schema:

| Pin fisico | GPIO | Funzione | Usato per |
|---|---|---|---|
| 1 | — | 3.3V | Alimentazione INMP441, SSD1306 |
| 2 | — | 5V | Alimentazione MAX98357A |
| 3 | GPIO2 | SDA1 (I2C) | SSD1306 — SDA |
| 5 | GPIO3 | SCL1 (I2C) | SSD1306 — SCL |
| 6 / 9 / 14 / 20 / 25 / 30 / 34 / 39 | — | GND | Massa comune (usarne una per componente) |
| 12 | GPIO18 | PCM_CLK (BCLK) | INMP441 + MAX98357A — clock bit, **condiviso** |
| 35 | GPIO19 | PCM_FS (LRCLK/WS) | INMP441 + MAX98357A — word select, **condiviso** |
| 38 | GPIO20 | PCM_DIN | INMP441 — dati mic → Pi |
| 40 | GPIO21 | PCM_DOUT | MAX98357A — dati Pi → amp |

> **Nota importante**: BCLK (GPIO18) e LRCLK/WS (GPIO19) sono **condivisi** tra
> microfono e amplificatore — è lo stesso bus I2S usato in modalità
> full-duplex (ingresso e uscita simultanei). Serve un device tree overlay
> che supporti questa configurazione full-duplex (già annotato come attività
> da configurare in fase di implementazione nella spec). PCM_DIN e PCM_DOUT
> restano invece separati: uno porta i dati del microfono verso il Pi,
> l'altro porta i dati dell'amplificatore dal Pi verso la cassa.

## Collegamento 1 — INMP441 (microfono I2S)

| Pin INMP441 | Collega a | Note |
|---|---|---|
| VDD | Pi pin 1 (3.3V) | |
| GND | Pi pin 9 (GND) | |
| L/R | GND (stesso rail di massa) | Seleziona canale sinistro |
| WS | Pi pin 35 (GPIO19) | Condiviso con MAX98357A |
| SCK | Pi pin 12 (GPIO18) | Condiviso con MAX98357A |
| SD | Pi pin 38 (GPIO20) | Dati microfono → Pi |

## Collegamento 2 — MAX98357A (amplificatore) + cassa

| Pin MAX98357A | Collega a | Note |
|---|---|---|
| VIN | Pi pin 2 (5V) | Range modulo: 2.5–5.5V, usare il 5V del Pi |
| GND | Pi pin 14 (GND) | |
| BCLK | Pi pin 12 (GPIO18) | Condiviso con INMP441 |
| LRC | Pi pin 35 (GPIO19) | Condiviso con INMP441 |
| DIN | Pi pin 40 (GPIO21) | Dati Pi → amplificatore |
| SD | Non collegato (floating) | **Verificato su hardware reale**: su questa breakout, SD a GND mette il chip in shutdown (silenzio totale, nessun errore ALSA) — floating lo abilita. Il comportamento "GND = solo canale sinistro" citato in alcuni datasheet/tutorial **non vale per questa scheda**. Se cambi modulo, riverifica con un tono di prova prima di fidarti della doc del produttore. |
| GAIN | Non collegato | Guadagno di default (~9dB) |
| + / − (uscita altoparlante) | Cassa 8Ω 2W | Rispettare la polarità indicata sul modulo |

## Collegamento 3 — SSD1306 (display OLED 0.96", I2C)

| Pin SSD1306 | Collega a | Note |
|---|---|---|
| VCC | Pi pin 17 (3.3V) | |
| GND | Pi pin 20 (GND) | |
| SCL | Pi pin 5 (GPIO3) | |
| SDA | Pi pin 3 (GPIO2) | |

Indirizzo I2C atteso dal software: `0x3C` (già impostato di default in
`Config.i2c_display_address`).

## Layout sulla breadboard

Idea di disposizione: usa le due file di alimentazione della breadboard
(rail rosso/nero) per distribuire massa e alimentazione a tutti i moduli,
poi porta i segnali con jumper corti dal Pi alle rispettive righe.

```
Raspberry Pi 3B+ (header 40 pin)
   │
   ├── pin 1  (3.3V) ───────┬──────────────► rail (+) 3.3V della breadboard
   ├── pin 2  (5V)   ───────┼──────────────► rail (+) 5V della breadboard (separato dal 3.3V)
   ├── GND (es. pin 9,14,20)┴──────────────► rail (−) GND della breadboard (comune a tutti)
   │
   ├── pin 12 (GPIO18/BCLK) ──► riga A  ──┬──► INMP441  SCK
   │                                       └──► MAX98357A BCLK
   │
   ├── pin 35 (GPIO19/LRCLK) ─► riga B  ──┬──► INMP441  WS
   │                                       └──► MAX98357A LRC
   │
   ├── pin 38 (GPIO20/DIN)  ──────────────────► INMP441  SD   (solo andata mic→Pi)
   │
   ├── pin 40 (GPIO21/DOUT) ──────────────────► MAX98357A DIN (solo andata Pi→amp)
   │
   ├── pin 3  (GPIO2/SDA)  ───────────────────► SSD1306 SDA
   └── pin 5  (GPIO3/SCL)  ───────────────────► SSD1306 SCL

Rail (+) 3.3V  ──┬──► INMP441 VDD
                 └──► SSD1306 VCC

Rail (+) 5V    ──────► MAX98357A VIN

Rail (−) GND   ──┬──► INMP441 GND, L/R
                  ├──► MAX98357A GND (SD non collegato, floating)
                  └──► SSD1306 GND

MAX98357A (+/−) ──────► Cassa 8Ω 2W
```

**Praticamente, sulla breadboard:**

1. Collega i pin 1 (3.3V), 2 (5V) e una massa (es. pin 9) del Pi alle tre
   righe di alimentazione della breadboard con tre jumper corti — questo va
   fatto una volta sola.
2. Per ogni modulo (INMP441, MAX98357A, SSD1306), inseriscilo su un gruppo di
   fori della breadboard e collega i suoi pin di alimentazione (VDD/VIN,
   GND) alle rail con jumper corti.
3. Per BCLK (GPIO18) e LRCLK (GPIO19), porta un solo jumper dal Pi a una riga
   libera della breadboard per ciascun segnale, poi da quella stessa riga
   porta un secondo jumper sia verso INMP441 sia verso MAX98357A — è così
   che si realizza la condivisione del bus.
4. Per DIN (GPIO20, verso il Pi) e DOUT (GPIO21, dal Pi), collegamento
   diretto punto-punto: un jumper dal Pi al pin corrispondente del modulo,
   nessuna condivisione.
5. La cassa si collega direttamente ai due terminali di uscita del
   MAX98357A (non passa dalla breadboard).

## Verifica dopo il cablaggio

- Controlla continuità/polarità di alimentazione **prima** di accendere il
  Pi (un'inversione su VIN/GND del MAX98357A o VDD/GND dell'INMP441 può
  danneggiare il modulo).
- Abilita I2C (`raspi-config` → Interface Options → I2C) e verifica che il
  display risponda: `i2cdetect -y 1` deve mostrare il dispositivo
  all'indirizzo `3c`.
- La configurazione del bus I2S full-duplex (device tree overlay) è un passo
  software separato, da fare prima di testare microfono e amplificatore
  insieme — vedi [`overlays/haro-duplex-overlay.dts`](../overlays/haro-duplex-overlay.dts)
  e [`overlays/README.md`](../overlays/README.md) per compilazione,
  installazione e verifica (non ancora testato su hardware reale).
