# haro
Personal ai desk robot

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
