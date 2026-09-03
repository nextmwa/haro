# haro
Personal ai desk robot

Guida completa per portare Haro da SD card vuota a robot funzionante. Per lo
schema elettrico vedi [`docs/wiring.md`](docs/wiring.md); per l'architettura
software vedi
[`docs/superpowers/specs/2026-09-02-haro-robot-design.md`](docs/superpowers/specs/2026-09-02-haro-robot-design.md).

## Requisiti hardware

- Raspberry Pi 3B+ (o successivo) + alimentatore + microSD (8GB+)
- Microfono I2S INMP441
- Amplificatore I2S MAX98357A + cassa 8Ω 2W
- Display OLED SSD1306 0.96" (I2C)
- Breadboard e jumper — schema completo in [`docs/wiring.md`](docs/wiring.md)
- Un server Haro AI backend raggiungibile in rete (repo `server`, vedi il suo
  README per come lanciarlo con Docker)

## 1. Flash della SD e primo avvio

Usa [Raspberry Pi Imager](https://www.raspberrypi.com/software/) e scegli
**Raspberry Pi OS Lite (64-bit)** — nessun desktop, Haro parte come servizio
di sistema senza bisogno di tastiera o monitor.

Prima di scrivere la SD, apri le impostazioni avanzate (icona ingranaggio in
basso a destra, o Ctrl+Shift+X) e configura:

- hostname (es. `haro`)
- utente `pi` con una password
- **SSH abilitato**
- SSID e password del tuo WiFi di casa

Così al primo boot la Pi si collega da sola alla rete ed è raggiungibile via
SSH — niente hotspot da configurare a mano per il primissimo setup (il
provisioning via hotspot descritto più sotto resta comunque disponibile per
riconfigurare il WiFi in futuro, senza reflash).

Inserisci la SD nella Pi, accendi, e dopo un minuto:

```bash
ssh pi@haro.local   # o l'IP assegnato dal router, se .local non risolve
```

## 2. Dipendenze di sistema

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip git portaudio19-dev i2c-tools
```

`libatlas-base-dev`, storicamente citato per numpy, **non esiste più** nei
repository Debian recenti (Bookworm/Trixie) — sostituito da OpenBLAS. Nella
maggior parte dei casi non serve nemmeno: i wheel precompilati di `numpy`
per `aarch64` includono già OpenBLAS. Installa `libopenblas-dev` solo se il
passo 4 (`pip install -e .`) si lamenta di BLAS/LAPACK mancante:

```bash
sudo apt install -y libopenblas-dev
```

## 3. Clona il repository

```bash
git clone https://github.com/nextmwa/haro.git ~/haro
cd ~/haro
```

## 4. Ambiente Python (serve esattamente 3.11)

Haro dipende da `openwakeword`, che a sua volta richiede `tflite-runtime` —
pacchetto che **non pubblica wheel oltre Python 3.11** (l'ultima release,
2.14.0, copre solo cp38-cp311 su aarch64). Le Raspberry Pi OS più recenti
possono avere Python 3.12/3.13 di default: se `python3 --version` mostra
altro da 3.11, `pip install -e .` fallirà con "no matching distribution" per
`tflite-runtime`. `pyproject.toml` fissa `requires-python = ">=3.11,<3.12"`
apposta per rendere questo vincolo esplicito invece di un errore criptico.

Il modo più rapido per avere un Python 3.11 dedicato, senza compilarlo, è
[`uv`](https://docs.astral.sh/uv/) (scarica un build precompilato):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env

uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -e .
```

Se preferisci senza `uv` e la tua Pi ha già Python 3.11 come predefinito,
il classico `python3 -m venv .venv && .venv/bin/pip install -e .` funziona
allo stesso modo.

**Nota:** `webrtcvad` (dipendenza non più mantenuta) importa `pkg_resources`
a runtime, che `setuptools` ha rimosso del tutto a partire dalla versione
82.0.0. `pyproject.toml` pinna `setuptools<82` apposta, quindi un
`pip install -e .` fatto dopo questa modifica lo risolve da solo. Se il
servizio va in crash con `ModuleNotFoundError: No module named
'pkg_resources'`, la tua installazione è precedente a questo fix — rilancia
`uv pip install --python .venv/bin/python -e .` (o il `pip install -e .`
del venv classico) per aggiornare le dipendenze.

## 5. File di configurazione

Crea `~/haro/config.json` con almeno l'indirizzo del server AI (vedi
`src/haro/config.py` per tutti i campi disponibili e i loro default):

```json
{
  "server_url": "ws://<IP-DEL-SERVER>:8765"
}
```

Nessun percorso dopo la porta: il client si collega direttamente a
quell'URL. Cambia anche `hotspot_password` (default `haro1234`) prima di
usare Haro fuori da un ambiente di solo test — vedi la sezione
[WiFi setup](#wifi-setup) più sotto.

## 6. Servizio systemd

```bash
sudo cp systemd/haro.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now haro.service
```

`systemd/haro.service` è già scritto per `User=pi` e
`WorkingDirectory=/home/pi/haro` — se hai clonato altrove o con un altro
utente, modifica il file prima di copiarlo. Per vedere i log in tempo reale:

```bash
journalctl -u haro.service -f
```

## 7. Display e I2C

Abilita l'interfaccia I2C:

```bash
sudo raspi-config   # Interface Options → I2C → Enable
sudo reboot
```

Dopo il riavvio, verifica che il display risponda (deve comparire
all'indirizzo `3c`):

```bash
i2cdetect -y 1
```

## 8. Audio I2S (microfono + amplificatore)

INMP441 (cattura) e MAX98357A (riproduzione) condividono lo stesso bus I2S
(BCLK/LRCLK) mantenendo DIN/DOUT separati — vedi
[`docs/wiring.md`](docs/wiring.md) per lo schema di cablaggio completo.

A differenza di I2C, qui **non c'è un dtoverlay standard unico** che
supporti cattura e riproduzione I2S simultanee su Raspberry Pi: gli overlay
comuni (es. `dtoverlay=max98357a`, overlay da soundcard per il microfono)
sono pensati per un solo verso alla volta, e se ne configuri più di uno in
`/boot/firmware/config.txt` di norma vince solo l'ultimo caricato. Serve un
overlay combinato/custom per il full-duplex — non ancora verificato su
hardware reale in questo progetto. Approccio consigliato per non perdere
tempo a debuggare i due problemi insieme:

1. Configura e testa **solo** il microfono (il suo overlay dedicato) e
   verifica la cattura con `arecord -l` / una registrazione di prova.
2. Configura e testa **solo** l'amplificatore (`dtoverlay=max98357a`) e
   verifica la riproduzione con `aplay -l` / un file di prova.
3. Solo dopo aver confermato che funzionano separatamente, cerca o scrivi un
   overlay combinato che dichiari entrambe le direzioni sullo stesso bus.

## 9. Verifica finale

Con il server AI raggiungibile e il servizio avviato, `journalctl -u haro
-f` dovrebbe mostrare la connessione WebSocket stabilita e Haro pronto a
riconoscere la wake word. Se la Pi non trova una rete WiFi nota, mostra la
faccina di setup e apre l'hotspot descritto qui sotto invece di connettersi
al server.

## WiFi setup

When Haro starts without a known WiFi network — and whenever it loses
connectivity for long enough while running — it shows the setup face and opens
its own hotspot, `Haro-Setup`. Join that network from a phone or laptop and
browse to <http://10.42.0.1:8080> (NetworkManager's default gateway address
for a shared-mode hotspot — not the more common `192.168.4.1` used by
hostapd/dnsmasq setups), pick your WiFi network from the list, and enter its
password. Haro connects, shuts the hotspot down, and resumes normal
operation.

The hotspot ships with the default password `haro1234`
(`Config.hotspot_password`). Change it in `config.json` for anything beyond
initial testing: the setup page has no authentication of its own, so anyone who
can join the hotspot can reach it.
