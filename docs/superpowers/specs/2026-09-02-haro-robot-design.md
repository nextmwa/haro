# Haro — Personal AI Desk Robot: Design

Date: 2026-09-02
Status: Approved for implementation planning

## Purpose

Haro is a personal desktop companion robot. It listens for a wake word,
streams the user's speech to an external AI server (built separately, out of
scope for this spec), and plays back the server's spoken response while
animating a simple face on an OLED display, with expressions driven by an
emotion tag returned by the server.

This spec covers the **robot side only**: everything that runs on the
Raspberry Pi. The AI server (STT, LLM, TTS, emotion tagging) is a separate
project; this spec defines the network contract the robot expects from it.

## Hardware

| Component | Role | Interface |
|---|---|---|
| Raspberry Pi 3B+ | Brain | — |
| microSD card | OS + app storage | — |
| INMP441 MEMS microphone | Voice input | I2S |
| MAX98357A amp + 8Ω/2W speaker | Voice/sound output | I2S |
| SSD1306 0.96" OLED | Face / expressions | I2C |
| Sound sensor (KY-038 type) | **Unused** — kept as spare, not wired into the design (only detects noise threshold, not real speech) | — |
| 2× spare SSD1306 OLED | **Unused** — kept as spare hardware, not part of this design | — |

I2S bus is shared between the INMP441 (capture) and MAX98357A (playback):
BCLK/LRCLK lines shared, separate DIN/DOUT pins, requires a device tree
overlay that supports simultaneous full-duplex I2S (configured during
implementation, e.g. combining a capture overlay and `hifiberry`-style
playback overlay, or a suitable custom overlay).

## Operating System

Raspberry Pi OS Lite (headless, no desktop environment). The robot
application is a Python 3 program that starts automatically on boot as a
`systemd` service — no login, no keyboard/monitor required for normal
operation. This is the closest practical equivalent to "boots straight into
the robot" given the Pi requires an OS to drive WiFi, I2S, I2C and
networking (a bare-metal/no-OS approach was considered and rejected: it
would require writing WiFi, I2S and I2C drivers from scratch, which is not
practical for this project).

## Software Architecture

Single Python 3 `asyncio` application, composed of isolated modules:

1. **AudioInput** — captures PCM frames from the INMP441 via ALSA (I2S).
2. **WakeWordDetector** — wraps a local wake-word engine (openWakeWord),
   consumes AudioInput frames continuously, emits a wake event when
   triggered.
3. **VoiceActivityDetector (VAD)** — during the `listening` state, monitors
   the same audio frames to detect end-of-speech (silence).
4. **ServerClient** — manages the WebSocket connection to the AI server:
   connect, auto-reconnect with exponential backoff, send audio/control
   messages, receive audio/control messages. Implements the protocol
   defined below.
5. **AudioOutput** — plays PCM audio chunks received from the server through
   the MAX98357A via ALSA, streaming playback as chunks arrive (does not
   wait for the full response before starting playback).
6. **FaceDisplay** — renders expressions on the single SSD1306 OLED via I2C.
   States: `idle`, `listening`, `thinking`, `speaking` (with emotion
   variants: `happy`, `sad`, `confused`, `neutral`), `error`, `setup` (WiFi
   provisioning mode).
7. **WifiProvisioning** — checks for a known WiFi connection at boot (and
   after repeated reconnect failures at runtime); if none is available,
   switches the Pi to Access Point mode and serves a local web page to let
   the user pick a network and enter its password, then hands the
   connection to NetworkManager and resumes normal operation.
8. **Orchestrator** — the main state machine wiring all modules together:
   `idle → listening → thinking → speaking → idle`, plus `error` and
   `setup` states.
9. **Config** — central place for server URL, wake word name/sensitivity,
   audio device names, I2C settings.

## Data Flow

### Boot sequence

1. `systemd` starts the application.
2. **WifiProvisioning** checks connectivity:
   - Connected to a known network → continue to step 3.
   - Not connected → FaceDisplay shows `setup`; Pi starts an AP
     (`Haro-Setup`) + local web server; user connects from phone/PC, picks
     a network, enters password; Pi joins that network via NetworkManager,
     AP mode stops, continue to step 3.
3. **ServerClient** opens the WebSocket connection to the configured server
   URL. FaceDisplay shows `idle`.
4. **Orchestrator** starts the **WakeWordDetector** loop on the
   **AudioInput** stream.

### Conversation turn

1. **Idle**: mic frames pass only through WakeWordDetector.
2. **Wake word detected** → state `listening`: FaceDisplay shows
   `listening`. Orchestrator streams mic PCM frames to ServerClient as
   binary WebSocket frames, while VAD monitors the same frames in parallel.
3. **VAD detects silence** → send control message
   `{"type": "end_of_speech"}` → state `thinking`, FaceDisplay shows
   `thinking`, stop streaming mic audio.
4. **Server responds** on the same WebSocket with a mix of:
   - JSON control messages: `{"type": "emotion", "value": "happy"}`,
     `{"type": "response_end"}`, `{"type": "error", "message": "..."}`
   - Binary audio frames (PCM) — the spoken response, ready to play.
5. On the first audio chunk or emotion message → state `speaking`,
   FaceDisplay switches to the emotion expression, AudioOutput streams
   playback of chunks as they arrive.
6. On `response_end` → state `idle`, FaceDisplay shows `idle`, resume
   wake-word listening.

### WebSocket protocol (robot ↔ server contract)

This is the contract the robot implements; it is the reference for the
future server implementation.

- Transport: one persistent WebSocket connection per robot session.
- Control messages: JSON text frames, always `{"type": ..., ...}`.
  - Client → Server: `hello` (sent once on connect, session/robot info),
    `end_of_speech`.
  - Server → Client: `emotion` (`value` one of `happy`, `sad`, `confused`,
    `neutral`), `response_end`, `error` (`message`).
- Audio: raw binary WebSocket frames, 16-bit PCM mono. Sample rate for
  mic upload fixed at 16kHz (typical for STT). Sample rate for playback is
  a server-controlled parameter to be pinned during server implementation;
  documented here as an open parameter, not blocking the robot-side design.

## Error Handling

- **WiFi/server unreachable**: ServerClient reconnects automatically with
  exponential backoff; FaceDisplay shows `error`/offline while
  disconnected. WakeWordDetector keeps running locally. After repeated
  failures, WifiProvisioning re-triggers AP/setup mode (network may have
  changed).
- **Mic/audio device failure at startup**: logged, FaceDisplay shows
  `error` persistently until restart (no hot-swap handling for v1).
- **No response from server after `end_of_speech`** (timeout, e.g. 15s):
  fall back to `idle` with a brief `error` expression, so the robot never
  gets stuck in `thinking`.

## Testing

- **Unit tests** for the state machine, protocol message parsing/building,
  and VAD trigger logic, using mocked audio input and a mocked WebSocket —
  runnable on any dev machine, not just the Pi.
- **Hardware integration** (mic capture, I2S playback, OLED rendering,
  wake-word accuracy, WiFi provisioning flow) verified manually on the
  physical Raspberry Pi.
- **Local fake server**: a minimal WebSocket mock server (implements the
  protocol above with canned responses) included for development, so the
  full pipeline can be exercised end-to-end before the real AI server
  exists.

## Out of Scope

- The AI server itself (STT, LLM, TTS, emotion classification).
- The sound sensor and the two spare OLED displays (not wired into this
  design).
- Any mobile app or dedicated hardware config UI (superseded by the WiFi
  AP/captive-portal provisioning flow).
