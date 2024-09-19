from Tools.Directories import resolveFilename, SCOPE_CONFIG
from os import path

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36 Edg/127.0.0.0"
USER_IPTV_PROVIDERS_FILE = path.realpath(resolveFilename(SCOPE_CONFIG)) + "/M3UIPTV/providers.xml"
USER_IPTV_VOD_MOVIES_FILE = path.realpath(resolveFilename(SCOPE_CONFIG)) + "/M3UIPTV/%s-vod-movies.json"
USER_IPTV_VOD_SERIES_FILE = path.realpath(resolveFilename(SCOPE_CONFIG)) + "/M3UIPTV/%s-vod-series.json"
	