from Tools.Directories import resolveFilename, SCOPE_CONFIG
from os import path

# General variables
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36 Edg/127.0.0.0"
USER_IPTV_PROVIDERS_FILE = path.realpath(resolveFilename(SCOPE_CONFIG)) + "/M3UIPTV/providers.xml"
USER_IPTV_VOD_MOVIES_FILE = path.realpath(resolveFilename(SCOPE_CONFIG)) + "/M3UIPTV/%s-vod-movies.json"
USER_IPTV_MOVIE_CATEGORIES_FILE = path.realpath(resolveFilename(SCOPE_CONFIG)) + "/M3UIPTV/%s-movie-categories.json"
USER_IPTV_VOD_SERIES_FILE = path.realpath(resolveFilename(SCOPE_CONFIG)) + "/M3UIPTV/%s-vod-series.json"
USER_IPTV_PROVIDER_INFO_FILE = path.realpath(resolveFilename(SCOPE_CONFIG)) + "/M3UIPTV/%s-provider-info.json"

# CatchUp types
CATCHUP_DEFAULT = 1
CATCHUP_APPEND = 2
CATCHUP_SHIFT = 3
CATCHUP_XTREME = 4
CATCHUP_STALKER = 5

CATCHUP_DEFAULT_TEXT = "default"
CATCHUP_APPEND_TEXT = "append"
CATCHUP_SHIFT_TEXT = "shift"
CATCHUP_XTREME_TEXT = "xc"
CATCHUP_STALKER_TEXT = "stalker"

CATCHUP_TYPES = {CATCHUP_DEFAULT : CATCHUP_DEFAULT_TEXT, 
                 CATCHUP_APPEND  : CATCHUP_APPEND_TEXT,
                 CATCHUP_SHIFT   : CATCHUP_SHIFT_TEXT,
                 CATCHUP_XTREME  : CATCHUP_XTREME_TEXT,
                 CATCHUP_STALKER : CATCHUP_STALKER_TEXT}
	