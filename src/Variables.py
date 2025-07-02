from Tools.Directories import resolveFilename, SCOPE_CONFIG
from os import path

# General variables
USER_FOLDER = path.realpath(resolveFilename(SCOPE_CONFIG)) + "/M3UIPTV"
PROVIDER_FOLDER = USER_FOLDER + "/%s"
USER_IPTV_PROVIDERS_FILE = USER_FOLDER + "/providers.xml"
USER_IPTV_PROVIDER_SUBSTITUTIONS_FILE = PROVIDER_FOLDER + "/substitutions.xml"
USER_IPTV_VOD_MOVIES_FILE = PROVIDER_FOLDER + "/vod-movies.json"
USER_IPTV_MOVIE_CATEGORIES_FILE = PROVIDER_FOLDER + "/movie-categories.json"
USER_IPTV_SERIES_CATEGORIES_FILE = PROVIDER_FOLDER + "/series-categories.json"
USER_IPTV_VOD_SERIES_FILE = PROVIDER_FOLDER + "/vod-series.json"
USER_IPTV_PROVIDER_INFO_FILE = PROVIDER_FOLDER + "/provider-info.json"
USER_IPTV_PROVIDER_BLACKLIST_FILE = PROVIDER_FOLDER + "/blacklist"
USER_IPTV_PROVIDER_VOD_MOVIES_BLACKLIST_FILE = PROVIDER_FOLDER + "/blacklist_movies"
USER_IPTV_PROVIDER_VOD_SERIES_BLACKLIST_FILE = PROVIDER_FOLDER + "/blacklist_series"

# User Agents
USER_AGENTS = {"android": "Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.6834.79 Mobile Safari/537.36",
               "ios"    : "Mozilla/5.0 (iPhone; CPU iPhone OS 17_7_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/132.0.6834.78 Mobile/15E148 Safari/604.1",
               "windows": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 Edg/131.0.2903.86",
               "vlc"    : "VLC/3.0.18 LibVLC/3.0.11"}

REQUEST_USER_AGENT = USER_AGENTS["windows"]

# CatchUp types
CATCHUP_DEFAULT = 1
CATCHUP_APPEND = 2
CATCHUP_SHIFT = 3
CATCHUP_XTREME = 4
CATCHUP_STALKER = 5
CATCHUP_FLUSSONIC = 6
CATCHUP_VOD = 7

CATCHUP_DEFAULT_TEXT = "default"
CATCHUP_APPEND_TEXT = "append"
CATCHUP_SHIFT_TEXT = "shift"
CATCHUP_XTREME_TEXT = "xc"
CATCHUP_STALKER_TEXT = "stalker"
CATCHUP_FLUSSONIC_TEXT = "flussonic"
CATCHUP_VOD_TEXT = "vod"

CATCHUP_TYPES = {CATCHUP_DEFAULT: CATCHUP_DEFAULT_TEXT,
                 CATCHUP_APPEND: CATCHUP_APPEND_TEXT,
                 CATCHUP_SHIFT: CATCHUP_SHIFT_TEXT,
                 CATCHUP_XTREME: CATCHUP_XTREME_TEXT,
                 CATCHUP_STALKER: CATCHUP_STALKER_TEXT,
                 CATCHUP_FLUSSONIC: CATCHUP_FLUSSONIC_TEXT,
                 CATCHUP_VOD: CATCHUP_VOD_TEXT}
