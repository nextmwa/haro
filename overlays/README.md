# Overlay I2S full-duplex

`haro-duplex-overlay.dts` fa comparire INMP441 (cattura) e MAX98357A
(riproduzione) come **due dai-link indipendenti sullo stesso bus I2S**
(BCLK/LRCLK condivisi su GPIO18/19, DIN/DOUT separati su GPIO20/21 — vedi
[`../docs/wiring.md`](../docs/wiring.md)), invece che come due schede audio
separate che si contendono l'unica periferica I2S del Pi.

**Non ancora verificato su hardware reale.** La sintassi è stata derivata
dalle sorgenti reali del kernel Raspberry Pi (`hifiberry-dac-overlay.dts`,
`googlevoicehat-soundcard-overlay.dts`) e dal driver mainline
`ics43432.c`/`simple-card.yaml`, non da un Pi acceso davanti a me — quindi
va trattato come primo tentativo da collaudare, non come soluzione
garantita. Se qualcosa non torna, il fallback a costo zero è provare
`dtoverlay=googlevoicehat-soundcard` (già incluso in Raspberry Pi OS,
pensato per un mic I2S + ampli MAX98357A-like sugli stessi pin) prima di
investire altro tempo su questo overlay custom.

## Compilazione e installazione (sul Raspberry Pi)

```bash
sudo apt install -y device-tree-compiler
dtc -@ -I dts -O dtb -o haro-duplex.dtbo overlays/haro-duplex-overlay.dts
sudo cp haro-duplex.dtbo /boot/firmware/overlays/
```

Aggiungi in `/boot/firmware/config.txt` (**non** insieme a
`dtoverlay=max98357a` o a un overlay mic separato — sostituisce entrambi):

```
dtoverlay=haro-duplex
```

```bash
sudo reboot
```

## Verifica

```bash
dmesg | grep -i haroduplex   # nessun errore di probe
aplay -l                     # deve comparire la card "haroduplex" con un device playback
arecord -l                   # deve comparire la stessa card con un device capture

# test riproduzione (richiede un file wav di prova)
aplay -D hw:haroduplex,1 test.wav

# test cattura
arecord -D hw:haroduplex,0 -f S32_LE -r 16000 -c 1 -d 5 test-rec.wav

# test vero: entrambi insieme
arecord -D hw:haroduplex,0 -f S32_LE -r 16000 -c 1 -d 5 test-rec.wav &
aplay -D hw:haroduplex,1 test.wav
wait
```

Il numero di device (`,0` / `,1`) dipende dall'ordine con cui ALSA enumera
i due `dai-link` — verificalo con `aplay -l`/`arecord -l` invece di darlo
per scontato.

INMP441 è mono (L/R legato a GND, canale sinistro): se `arecord` con
`-c 2` produce un canale muto, prova `-c 1` prima di sospettare un problema
di cablaggio.

## Rollback

Se qualcosa non funziona, commenta la riga `dtoverlay=haro-duplex` in
`config.txt`, torna a `dtoverlay=max98357a` (solo riproduzione) e riavvia —
non tocca il resto del sistema.
