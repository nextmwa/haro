# Overlay I2S full-duplex

`haro-duplex-overlay.dts` fa comparire INMP441 (cattura) e MAX98357A
(riproduzione) come **due dai-link indipendenti sullo stesso bus I2S**
(BCLK/LRCLK condivisi su GPIO18/19, DIN/DOUT separati su GPIO20/21 — vedi
[`../docs/wiring.md`](../docs/wiring.md)), invece che come due schede audio
separate che si contendono l'unica periferica I2S del Pi.

**Verificato su hardware reale il 2026-09-08** (Raspberry Pi 3B+, utente
`haro`): compila senza warning, l'overlay carica senza errori in `dmesg`,
`aplay -l`/`arecord -l` mostrano una sola card `haroduplex` con un device
playback e uno capture, e cattura+riproduzione girano **contemporaneamente**
senza errori ALSA — la registrazione fatta durante la riproduzione mostra un
segnale reale (non silenzio piatto) sul canale sinistro, muto sul destro
com'è atteso dal cablaggio INMP441 (L/R a GND). **Non verificato**: la
qualità audio in uscita all'orecchio (nessun modo di sentirla da remoto) —
controllalo tu alla prima accensione con l'altoparlante collegato.

Se in futuro qualcosa smette di funzionare, il fallback a costo zero è
provare `dtoverlay=googlevoicehat-soundcard` (già incluso in Raspberry Pi
OS, pensato per un mic I2S + ampli MAX98357A-like sugli stessi pin) prima
di investire altro tempo a debuggare l'overlay custom.

## Compilazione e installazione (sul Raspberry Pi)

```bash
sudo apt install -y device-tree-compiler   # spesso già presente
dtc -@ -I dts -O dtb -o /tmp/haro-duplex.dtbo overlays/haro-duplex-overlay.dts
sudo cp /tmp/haro-duplex.dtbo /boot/firmware/overlays/
```

In `/boot/firmware/config.txt`, commenta `dtoverlay=max98357a` (o qualunque
overlay mic-only) e aggiungi al suo posto:

```
dtoverlay=haro-duplex
```

```bash
sudo reboot
```

## Verifica

```bash
aplay -l    # card "haroduplex", device 0: bcm2835-i2s-pcm5102a-hifi (playback = ampli)
arecord -l  # card "haroduplex", device 1: bcm2835-i2s-ics43432-hifi (capture = mic)
```

**Formato richiesto per entrambi i device: `S32_LE`, 2 canali.** Anche se
INMP441 è mono e MAX98357A è mono, i codec-stub usati nell'overlay
(`ti,pcm5102a` per l'ampli, `invensense,ics43432` per il mic) sono driver
per chip stereo — `-c 1` viene rifiutato con "Channels count non
available". In cattura il canale reale è il sinistro (L/R dell'INMP441 è
legato a GND); il destro resta silenzioso.

```bash
# riproduzione
aplay -D hw:haroduplex,0 test.wav        # test.wav: S32_LE, 2ch

# cattura (5s)
arecord -D hw:haroduplex,1 -f S32_LE -r 16000 -c 2 -d 5 test-rec.wav

# insieme — il vero test di full-duplex
arecord -D hw:haroduplex,1 -f S32_LE -r 16000 -c 2 -d 5 test-rec.wav &
aplay -D hw:haroduplex,0 test.wav
wait
```

Se `haro.service` è già attivo, il mic (device 1) risulta "busy" per i test
manuali — è normale, lo tiene aperto per la wake word: `sudo systemctl stop
haro.service` prima di testare a mano, `sudo systemctl start haro.service`
dopo.

## Rollback

Se qualcosa non funziona, commenta la riga `dtoverlay=haro-duplex` in
`config.txt`, torna a `dtoverlay=max98357a` (solo riproduzione) e riavvia —
non tocca il resto del sistema. Sul Pi di sviluppo esiste un backup del
config.txt precedente in `/boot/firmware/config.txt.bak-pre-haro-duplex`.
