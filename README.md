# IPTV M3U Reader (M3UIPTV)

An Enigma2 plugin for set-top boxes (OpenPLi, OpenViX, OpenATV, VTi, and other
oe-alliance / openpli-oe-core based images) that turns IPTV playlists and
portals into native Enigma2 bouquets — with live TV, catch-up/timeshift
playback, Video on Demand, EPG import, and picons, all managed from the box
itself or from a browser.

## Features

- **Multiple provider types**, each with its own screen/API integration:
  - **M3U / M3U8** playlists (static URL or dynamic list, `#EXTINF` metadata parsing)
  - **Xtream Codes** (XC) panels via the `player_api.php` API
  - **Stalker / Ministra** portals (MAG STB emulation, MAC-derived device IDs)
  - **TVHeadend** servers (playlist + XMLTV endpoints)
  - **VOD-only** sources (`m3u` or plain `name,url` text lists)
- **Automatic bouquet generation** with configurable strategy: per-group
  bouquets, a single "All Channels" bouquet, both, or one provider bouquet
  with `FROM BOUQUET` sub-bouquets per group. Bouquet name casing and
  provider-native channel numbering (LCN/TSID) are configurable.
- **Catch-up / timeshift playback** directly from the EPG grid, with a
  dedicated player (accelerating seek, resume points, EOF handling) and
  support for several catch-up URL schemes: default, append, shift,
  Xtream (`xc`/`xc60`), Stalker, and Flussonic.
- **Video On Demand**: movies and TV series listings with posters, paging,
  search, and per-provider VoD/series blacklists.
- **EPG import** integration with the third-party [EPGImport](https://github.com/oe-alliance/EPGImport)
  plugin (static or auto-discovered XMLTV URLs), plus a built-in local EPG
  helper server for Stalker portals that don't expose persistent EPG data.
- **Picon handling**: multithreaded picon downloads that link into your
  existing picon path without overwriting picons you already have.
- **Per-provider substitutions and blacklists** — regex-based overrides for
  channel name/EPG id/service type/catchup type, and group/category
  exclusion lists, editable per provider.
- **Web Manager**: an optional built-in web UI for adding, editing, and
  deleting providers from any browser on your network.
- **Scheduled auto-updates** — refresh playlists/EPG automatically on
  selected days and times.
- Translated into English, Bulgarian, German, Spanish, Finnish, French,
  Italian, Russian, Turkish, and Ukrainian.

## Requirements

- An Enigma2-based receiver image (oe-alliance / openpli-oe-core derived).
- Python 3 packages available on the image: `requests`, `multiprocessing`,
  `zoneinfo`.
- Optional but recommended: the **EPGImport** plugin, for EPG data.
- Optional: **ServiceApp**, for alternate playback engines on some catch-up
  configurations (auto-detected if installed).

## Installation

### From an image feed / package manager

If your image feed carries the plugin, install it like any other package,
e.g. from the receiver's package manager or over SSH:

```sh
opkg update
opkg install enigma2-plugin-extensions-m3uiptv
```

### Building an .ipk yourself

```sh
./build.sh
```

This packages `src/` together with the metadata in `meta/` into an
`.ipk` you can install with `opkg install`.

### From source (development)

```sh
python setup.py install
```

`setup.py` installs the plugin under
`Plugins.SystemPlugins.M3UIPTV` and compiles the translation catalogs via
`setup_translate.py`.

### Yocto / OpenEmbedded

`enigma2-plugin-systemplugins-m3uiptv.bb` is provided for images built with
`bitbake` (oe-alliance-core or openpli-oe-core layers).

## Getting started

After installing, restart Enigma2 (or reboot). Two new menu areas appear:

- **Menu → Setup → IPTV**
  - **Settings** — global plugin configuration (see below).
  - **Playlist manager** — add, edit, delete providers and (re)generate
    bouquets.
- **Menu → Video On Demand** (main menu and/or extensions/blue-button menu,
  depending on settings) — browse Movies and TV Shows across all VoD-capable
  providers.

To add a provider: open **Playlist manager → Add**, choose a provider type
(M3U/M3U8, Xtream Codes, Stalker, TVHeadend, or VOD), fill in the
URL/credentials, pick a catch-up type and bouquet strategy, then save and
generate. Regenerating pulls the latest playlist/API data and rewrites the
provider's bouquets, EPG source files, and picons.

## Global settings (`Settings`)

| Setting | Purpose |
|---|---|
| Enabled | Master on/off switch for the plugin |
| Internet check timeout | Seconds to wait for a connectivity check before fetching playlists (or off) |
| Request timeout | HTTP timeout (seconds) used for playlist/API requests |
| Local EPG server port | TCP port for the built-in EPG helper (default `9010`), mainly used by Stalker portals |
| Web manager enabled / port / require login | Turn the browser-based manager on/off, its TCP port (default `8090`), and whether it requires your box's system login |
| Show in main menu / Show in extensions menu | Where the Video On Demand entry appears |
| Show VoD posters | Toggle poster art downloads for movies/series |
| Picon download threads | Concurrency for picon downloads (50–1000) |
| Bouquet name case | Original / lowercase / UPPERCASE for generated bouquet titles |
| Catch-up EOF timeout | Delay before honoring end-of-file during catch-up playback |
| Fallback picon path | Picon directory used when auto-detection fails |
| VoD play system | Service type used to play VoD streams |
| Scheduled updates | Enable auto-refresh, plus time and days of the week |

## Catch-up / timeshift playback

Events with archive data show a catch-up icon in the EPG grid; pressing
**Play** launches the catch-up player instead of a live zap. Archive
duration and URL construction are read per-channel (from playlist
attributes such as `tvg-rec`, `catchup-days`, `timeshift`) or derived from
the provider's API (Xtream `tv_archive_duration`, Stalker portal calls).
Supported catch-up types: `default`, `append`, `shift`, `xc`/`xc60`
(Xtream), `stalker`, `flussonic`, and `vod`.

## Web Manager

Enable **Web manager enabled** under Settings to manage providers from a
browser at `http://<receiver-ip>:8090/` (port configurable). The page lets
you list, add, edit, and delete providers for all supported types, with
fields shown/hidden per provider type (URL, credentials, MAC/serial/device
ID for Stalker, refresh interval, EPG source, playback systems, output
format, catch-up type, picon options, bouquet/channel-ordering strategy,
and auto-update scheduling).

When **Require login** is enabled (the default), access is protected with
HTTP Basic Auth checked against your receiver's own system credentials —
the same login used for Telnet/FTP/the stock web interface — not a
separate plugin password. Deleting a provider through the web UI fully
tears it down: bouquets, VoD cache, EPG sources, and picons are all
removed.

## Per-provider extras

- **Substitutions** (`substitutions.xml`, see
  [`src/substitutions.example.xml`](src/substitutions.example.xml)):
  regex rules to override a channel's name, EPG id, service type, or
  catch-up type when a provider's playlist metadata is incomplete or wrong.
- **Blacklists**: per-provider text files listing groups/categories (or
  VoD movies/series) to exclude from bouquet generation; an example
  blacklist listing every discovered group is generated automatically on
  first import.
- **M3U media library**: an M3U provider can optionally pull its VoD/series
  catalogue from an attached Xtream Codes API instead of (or alongside) its
  M3U playlist.

## Translating

Translation sources live in [`po/`](po) as gettext `.po` files, one per
language, generated from [`po/m3uiptv.pot`](po/m3uiptv.pot). Use
`po/updateallpo-multiOS.sh` to refresh catalogs from source strings, and
`setup.py`/`setup_translate.py` to compile `.po` into the `.mo` files
shipped with the plugin.

## License

Licensed under the [GNU General Public License v3.0](LICENSE).

## Maintainers

DimitarCC, Huevos — see the [GitHub repository](https://github.com/DimitarCC/iptv-m3u-reader) for issues and contributions.
