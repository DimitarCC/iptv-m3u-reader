# for localized messages
from . import _

from twisted.internet import threads
from .epgimport_helper import epgimport_helper
from .Variables import REQUEST_USER_AGENT, CATCHUP_DEFAULT, CATCHUP_DEFAULT_TEXT, CATCHUP_APPEND_TEXT, CATCHUP_SHIFT_TEXT, CATCHUP_XTREME_TEXT, CATCHUP_STALKER_TEXT, \
					   CATCHUP_FLUSSONIC_TEXT, CATCHUP_VOD_TEXT, USER_IPTV_PROVIDER_BLACKLIST_FILE, USER_IPTV_VOD_MOVIES_FILE, USER_IPTV_VOD_SERIES_FILE, USER_AGENTS, \
					   USER_IPTV_MOVIE_CATEGORIES_FILE, USER_IPTV_SERIES_CATEGORIES_FILE, USER_IPTV_PROVIDER_VOD_MOVIES_BLACKLIST_FILE, \
					   USER_IPTV_PROVIDER_VOD_SERIES_BLACKLIST_FILE
from .VoDItem import VoDItem
from .picon import Fetcher
from Components.config import config
try:
	from Tools.Directories import sanitizeFilename
except ImportError:
	from unicodedata import normalize
	from os.path import splitext as pathSplitext

	def sanitizeFilename(filename, maxlen=255):  # 255 is max length in ext4 (and most other file systems)
		"""Return a fairly safe version of the filename.

		We don't limit ourselves to ascii, because we want to keep municipality
		names, etc, but we do want to get rid of anything potentially harmful,
		and make sure we do not exceed filename length limits.
		Hence a less safe blacklist, rather than a whitelist.
		"""
		blacklist = ["\\", "/", ":", "*", "?", "\"", "<", ">", "|", "\0"]
		reserved = [
			"CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5",
			"COM6", "COM7", "COM8", "COM9", "LPT1", "LPT2", "LPT3", "LPT4", "LPT5",
			"LPT6", "LPT7", "LPT8", "LPT9",
		]  # Reserved words on Windows
		# Remove any blacklisted chars. Remove all charcters below code point 32. Normalize. Strip.
		filename = normalize("NFKD", "".join(c for c in filename if c not in blacklist and ord(c) > 31)).strip()
		if all([x == "." for x in filename]) or filename in reserved:  # if filename is a string of dots
			filename = "__" + filename
		# Most Unix file systems typically allow filenames of up to 255 bytes.
		# However, the actual number of characters allowed can vary due to the
		# representation of Unicode characters. Therefore length checks must
		# be done in bytes, not unicode.
		#
		# Also we cannot leave the byte truncate in the middle of a multi-byte
		# utf8 character! So, convert to bytes, truncate then get back to unicode,
		# ignoring errors along the way, the result will be valid unicode.
		# Prioritise maintaining the complete extension if possible.
		# Any truncation of root or ext will be done at the end of the string
		root, ext = pathSplitext(filename.encode(encoding='utf-8', errors='ignore'))
		if len(ext) > maxlen - (1 if root else 0):  # leave at least one char for root if root
			ext = ext[:maxlen - (1 if root else 0)]
		# convert back to unicode, ignoring any incomplete utf8 multibyte chars
		filename = root[:maxlen - len(ext)].decode(encoding='utf-8', errors='ignore') + ext.decode(encoding='utf-8', errors='ignore')
		filename = filename.rstrip(". ")  # Windows does not allow these at end
		if len(filename) == 0:
			filename = "__"
		return filename
from Tools.Directories import fileExists
from os import fsync, rename, path, makedirs, remove as remove_file
import re
import json
import socket
import urllib
import threading
import shutil
import base64
from time import time
from datetime import datetime

try:
	from multiprocessing import Process
except ImportError:
	Process = None

write_lock = threading.Lock()


def constructCatchUpUrl(sref, url_play, stime, etime, duration):
	now = time()
	catchup_type = None
	match = re.search(r"catchuptype\=(.*?)[&]", sref)
	if match:
		catchup_type = match.groups(1)[0]

	if catchup_type == CATCHUP_DEFAULT_TEXT:
		return url_play.replace("%3a", ":").replace("${start}", str(stime)).replace("${timestamp}", str(now)).replace("${duration}", str(duration))
	elif catchup_type == CATCHUP_APPEND_TEXT:
		sref_split = sref.split(":")
		url = sref_split[10:][0]
		return f"{url}?utc={str(stime)}&lutc={str(int(now))}&duration={str(int(duration))}"
	elif catchup_type == CATCHUP_VOD_TEXT:
		sref_split = sref.split(":")
		url = sref_split[10:][0]
		url = url.replace("/index.m3u8", f"/video-{str(stime)}-{str(int(duration))}.m3u8").replace("/mpegts", f"/video-{str(stime)}-{str(int(duration))}.m3u8")
		return url
	elif catchup_type == CATCHUP_SHIFT_TEXT:
		sref_split = sref.split(":")
		url = sref_split[10:][0].split("?")[0]
		return f"{url}?utc={str(stime)}&lutc={str(int(now))}"
	elif catchup_type == CATCHUP_XTREME_TEXT:
		sref_split = sref.split(":")
		url = sref_split[10:][0]
		stime_offset = stime
		match_tz = re.search(r"tz_offset=([-,+]?\d*)", url)
		if match_tz:
			tz_offset = int(match_tz.group(1))
			stime_offset += tz_offset
		match = re.search(r"[\/]\d*\.ts|[\/]\d*\.m3u8", url)
		if match:
			end_s = match.group(0)
			url = url.replace("/live/", "/timeshift/").replace(end_s, f'/{duration}/{datetime.fromtimestamp(stime_offset).strftime("%Y-%m-%d:%H-%M")}{end_s}')
		return url.replace("%3a", ":")
	elif catchup_type == CATCHUP_STALKER_TEXT:
		pass
	elif catchup_type == CATCHUP_FLUSSONIC_TEXT:
		sref_split = sref.split(":")
		url = sref_split[10:][0]
		url = url.replace("%3a", ":")
		match = re.search(r"^(http[s]?:\/\/[^\/]+)\/(.*)\/([^\/]*)(mpegts|\\.m3u8)(\\?.+=.+)?$", url)
		if match:
			if len(match.groups()) > 4:
				fsHost = match.group(1)
				fsChannelId = match.group(2)
				fsListType = match.group(3)
				fsStreamType = match.group(4)
				fsUrlAppend = match.group(5)
				isCatchupTSStream = fsStreamType == "mpegts"
				if isCatchupTSStream:  # the catchup type was "flussonic-ts" or "fs"
					catchupSource = fsHost + "/" + fsChannelId + "/timeshift_abs-${start}.ts" + fsUrlAppend
				else:  # the catchup type was "flussonic" or "flussonic-hls"
					if fsListType == "index":
						catchupSource = fsHost + "/" + fsChannelId + "/timeshift_rel-${offset}.m3u8" + fsUrlAppend
					else:
						catchupSource = fsHost + "/" + fsChannelId + "/" + fsListType + "-timeshift_rel-${offset}.m3u8" + fsUrlAppend
				return catchupSource.replace("${start}", str(int(stime))).replace("${offset}", str(int(now - stime)))
		else:
			match = re.search(r"^(http[s]?:\/\/[^\/]+)\/(.*)\/([^\\?]*)(\\?.+=.+)?$", url)
			if match:
				if len(match.groups()) > 3:
					fsHost = match.group(1)
					fsChannelId = match.group(2)
					fsStreamType = match.group(3)
					fsUrlAppend = match.group(4)
					isCatchupTSStream = fsStreamType == "mpegts"
					if isCatchupTSStream:  # the catchup type was "flussonic-ts" or "fs"
						catchupSource = fsHost + "/" + fsChannelId + "/timeshift_abs-${start}.ts" + fsUrlAppend
					else:  # the catchup type was "flussonic" or "flussonic-hls"
						catchupSource = fsHost + "/" + fsChannelId + "/timeshift_rel-${offset}.m3u8" + fsUrlAppend
					return catchupSource.replace("${start}", str(int(stime))).replace("${offset}", str(int(now - stime)))

	return url_play


class IPTVProcessor():
	def __init__(self):
		self.type = "M3U"  # default type M3U. Possible Types: M3U, Xtreem, Stalker
		self.url = ""
		self.scheme = ""
		self.isPlayBackup = False
		self.play_system = "4097"
		self.ignore_vod = True
		self.iptv_service_provider = ""
		self.last_exec = None
		self.create_epg = True
		self.refresh_interval = 1  # used by M3UProvider, default here for Setup
		self.search_criteria = "tvg-id=\"{SID}\""  # used by M3UProvider, default here for Setup
		self.static_urls = False  # used by M3UProvider, default here for Setup
		self.username = ""  # used by XtreemProvider, default here for Setup
		self.password = ""  # used by XtreemProvider, default here for Setup
		self.mac = ""  # used by StalkerProvider, default here for Setup
		self.serial = ""  # used by StalkerProvider, default here for Setup
		self.devid = ""  # used by StalkerProvider, default here for Setup
		self.signature = ""  # used by StalkerProvider, default here for Setup
		self.vod_movies = []
		self.vod_series = {}
		self.onBouquetCreated = []
		self.onProgressChanged = []
		self.progress_percentage = -1
		self.update_status_callback = []  # for passing messages
		self.epg_url = ""
		self.catchup_type = CATCHUP_DEFAULT
		self.play_system_vod = "4097"
		self.play_system_catchup = "4097"
		self.movie_categories = {}
		self.series_categories = {}
		self.is_dynamic_epg = False
		self.is_custom_xmltv = False
		self.custom_xmltv_url = ""
		self.server_timezone_offset = 0
		self.provider_info = {}
		self.picons = False
		self.picon_database = {}
		self.picon_sref_database = {}
		self.picon_gen_strategy = 0
		self.create_bouquets_strategy = 0
		self.use_provider_tsid = False
		self.provider_tsid_search_criteria = "tvg-chno=\"{TSID}\""
		self.user_provider_ch_num = False
		self.bouquets_refresh_interval = -1
		self.epg_match_strategy = 0
		self.custom_user_agent = "off"
		self.output_format = "ts"
		self.ch_order_strategy = 0
		self.epg_time_offset = 0  # Only for Stalker providers
		self.server_time_offset = ""  # Only for Stalker providers
		self.portal_entry_point_type = 0  # Only for Stalker providers
		self.playlist_type = "m3u"  # Only for VOD providers

		# Fields for utilize substitutions if available
		self.servicename_substitutions = {}
		self.epg_substitions = {}

		# Fields for media library for M3U providers start here
		self.has_media_library = False
		self.media_library_type = "xc"  # can be xml, xc (Xtream Codes) or xc-token (Xtream Codes with single token). For the moment only xc and xc-token are implemented
		self.media_library_url = ""
		self.media_library_username = ""
		self.media_library_password = ""
		self.media_library_token = ""
		self.media_library_object = None
		self.auto_updates = False
		self.last_vod_update_time = 0

	def checkForNetwrok(self):
		is_check_network_val = config.plugins.m3uiptv.check_internet.value
		if is_check_network_val != "off":
			try:
				socket.setdefaulttimeout(int(is_check_network_val))
				socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("8.8.8.8", 53))
			except:
				print("[IPTVProcessor] No intenrnet connection or Google DNS (8.8.8.8) not reachable!")
				return False
		return True

	def constructRequest(self, url):
		headers = {'User-Agent': REQUEST_USER_AGENT}
		auth_match = re.search(r"\/\/(.*?)@", url)
		if auth_match:
			auth = auth_match.group(1)
			url = url.replace(f"{auth}@", "")
			headers["Authorization"] = "Basic %s" % base64.b64encode(bytes(auth, "ascii")).decode("utf-8")
		req = urllib.request.Request(url, headers=headers)
		return req

	def isLocalPlaylist(self):
		return not self.url.startswith(("http://", "https://"))

	def getTempDir(self):
		return path.join(path.realpath("/tmp"), "M3UIPTV", self.scheme)

	def getPlaylistAndGenBouquet(self, callback=None):
		if self.picon_gen_strategy == 1:
			self.removePicons()

		if callback:
			threads.deferToThread(self.storePlaylistAndGenBouquet).addCallback(callback)
		else:
			self.storePlaylistAndGenBouquet()

	def storePlaylistAndGenBouquet(self):
		pass

	def generateMediaLibrary(self):
		if not self.ignore_vod:
			self.getMovieCategories()
			self.getVoDMovies()
			self.getSeriesCategories()
			self.getVoDSeries()

	def loadMedialLibraryItems(self):
		if not self.ignore_vod:
			self.loadMovieCategoriesFromFile()
			self.loadVoDMoviesFromFile()
			self.loadSeriesCategoriesFromFile()
			self.loadVoDSeriesFromFile()

	def getVoDMovies(self):
		pass

	def getVoDPlayUrl(self, url, movie=0, series=0):
		return url

	def getMovieCategories(self):
		pass

	def getSeriesCategories(self) -> object:
		pass

	def loadMovieCategoriesFromFile(self):
		vodFile = USER_IPTV_MOVIE_CATEGORIES_FILE % self.scheme
		json_string = self.loadFromFile(vodFile)
		self.makeMovieCategoriesDictFromJson(json_string)

	def loadSeriesCategoriesFromFile(self):
		vodFile = USER_IPTV_SERIES_CATEGORIES_FILE % self.scheme
		json_string = self.loadFromFile(vodFile)
		self.makeSeriesCategoriesDictFromJson(json_string)

	def makeMovieCategoriesDictFromJson(self, json_string):
		self.movie_categories = {}
		if json_string:
			for category in json.loads(json_string):
				self.movie_categories[str(category["category_id"])] = category["category_name"]

	def makeSeriesCategoriesDictFromJson(self, json_string):
		self.series_categories = {}
		if json_string:
			for category in json.loads(json_string):
				self.series_categories[str(category["category_id"])] = category["category_name"]

	def loadVoDMoviesFromFile(self):
		pass

	def getVODCategories(self) -> list:
		pass

	def getSeriesCategories(self) -> list:
		pass

	def getVoDSeries(self):
		pass

	def loadVoDSeriesFromFile(self):
		self.vod_series = {}
		vodFile = USER_IPTV_VOD_SERIES_FILE % self.scheme
		json_string = self.loadFromFile(vodFile)
		self.makeVodSeriesDictFromJson(json_string)
		for x in self.onProgressChanged:
			x()

	def getProviderInfo(self, from_token=False):
		pass

	def loadInfoFromFile(self):
		pass

	def getAccountActive(self):
		if self.provider_info:
			if prov_info := self.provider_info.get("user_info", None):
				return "0" if prov_info.get("status", "") == "Active" else "1"
		return "2"

	def makeVodSeriesDictFromJson(self, json_string):
		self.vod_series = {}
		if json_string:
			series = json.loads(json_string)
			for x in series:
				category_id = x.get("category_id")
				if isinstance(category_id, int):
					category_id = str(category_id)
				category = "UNCATEGORIZED" if not category_id or category_id not in self.series_categories else self.series_categories[category_id]
				name = x.get("title") or x.get("name")
				series_id = x.get("series_id") and str(x["series_id"])
				cover_url = x.get("cover") or x.get("stream_icon")
				plot = x.get("plot")
				if name and series_id:
					if category not in self.vod_series:
						self.vod_series[category] = []
					self.vod_series[category].append((series_id, name, plot, cover_url))

	def getSeriesById(self, series_id):
		ret = []
		return ret

	def getMovieById(self, movie_id):
		ret = {}
		return ret

	def getUrl(self, url):
		is_check_network_val = config.plugins.m3uiptv.check_internet.value
		if is_check_network_val != "off":
			socket.setdefaulttimeout(int(is_check_network_val))
			socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("8.8.8.8", 53))
		try:
			req = urllib.request.Request(url, headers={'User-Agent': REQUEST_USER_AGENT})
			req_timeout_val = config.plugins.m3uiptv.req_timeout.value
			if req_timeout_val != "off":
				response = urllib.request.urlopen(req, timeout=int(req_timeout_val))
			else:
				response = urllib.request.urlopen(req, timeout=10)  # set a timeout to prevent blocking
			return response.read()
		except:
			return None

	def getUrlToFile(self, url, dest_file):
		vod_response = self.getUrl(url)
		if not vod_response:
			return None
		makedirs(path.realpath(path.dirname(dest_file)), exist_ok=True)  # make folders and sub folders if not exists
		with write_lock:
			f = open(dest_file + ".writing", 'wb')
			f.write(vod_response)
			f.flush()
			fsync(f.fileno())
			f.close()
			rename(dest_file + ".writing", dest_file)
		return vod_response

	def getDataToFile(self, data, dest_file):
		if not data:
			return None
		makedirs(path.realpath(path.dirname(dest_file)), exist_ok=True)  # make folders and sub folders if not exists
		with write_lock:
			f = open(dest_file + ".writing", 'wb')
			json_str = json.dumps(data).encode()
			f.write(json_str)
			f.flush()
			fsync(f.fileno())
			f.close()
			rename(dest_file + ".writing", dest_file)
		return data

	def loadFromFile(self, source_file):
		if not fileExists(source_file):
			return
		return open(source_file, 'rb').read()

	def makeVodListFromJson(self, json_string):
		if json_string:
			vod_json_obj = json.loads(json_string)
			for movie in vod_json_obj:
				name = movie["name"]
				ext = movie["container_extension"]
				id = movie["stream_id"]
				url = "%s/movie/%s/%s/%s.%s" % (self.url, self.username, self.password, id, ext)
				vod_item = VoDItem(url, name, id, self, self.movie_categories.get(str(movie.get("category_id"))), movie.get("plot"), movie.get("stream_icon"))
				self.vod_movies.append(vod_item)

	def processService(self, nref, iptvinfodata, callback=None, event=None):
		return nref, nref, False

	def generateXMLTVFile(self) -> bytes:
		return None

	def bouquetCreated(self, error):
		for f in self.onBouquetCreated:
			f(self, error)

	def generateChannelReference(self, type, tsid, url, name):
		if self.custom_user_agent == "off":
			return "%s:0:%s:%X:%X:1:CCCC0000:0:0:0:%s:%s•%s" % (self.play_system, type, tsid, self.onid, url.replace(":", "%3a"), name, self.iptv_service_provider)
		else:
			user_agent = USER_AGENTS[self.custom_user_agent]
			return "%s:0:%s:%X:%X:1:CCCC0000:0:0:0:%s#User-Agent=%s:%s•%s" % (self.play_system, type, tsid, self.onid, url.replace(":", "%3a"), user_agent, name, self.iptv_service_provider)

	def getEpgUrl(self):  # if not overridden in the subclass
		return self.custom_xmltv_url if self.is_custom_xmltv and self.custom_xmltv_url else self.epg_url

	def getEpgUrlForSources(self):  # for use when dynamic xmltv url is needed for sources file
		return self.custom_xmltv_url if self.is_custom_xmltv and self.custom_xmltv_url else self.epg_url

	def createChannelsFile(self, epghelper, groups):
		epghelper.createChannelsFile(groups)

	def generateEPGImportFiles(self, groups):
		print("[M3UIPTV] Generating epg started.")
		if not self.create_epg or not self.getEpgUrl():
			print("[M3UIPTV] Generating epg aboreted. Seem no epg url or epg generation disabled.")
			return
		epghelper = epgimport_helper(self)
		epghelper.createSourcesFile()
		self.createChannelsFile(epghelper, groups)

		epghelper.importepg()   # auto epg update after bouquet generation

	def generateEPGChannelReference(self, original_sref):
		return f"{':'.join(original_sref.split(':', 10)[:10])}:http%3a//m3u.iptv.com"

	def constructCatchupSuffix(self, days, url, catchup_type):
		if days.strip() and int(days) > 0:
			days_int = int(days)
			if days_int > 24:
				days = str(days_int // 24)
			captchup_addon = "%scatchuptype=%s&catchupdays=%s&catchupstype=%s" % ("&" if "?" in url else "?", catchup_type, days, self.play_system_catchup)
			if catchup_type == CATCHUP_XTREME_TEXT and self.server_timezone_offset:
				captchup_addon += "&tz_offset=%d" % self.server_timezone_offset
			return url + captchup_addon
		return url

	def removeAllData(self):
		self.removeBouquets()
		self.removeEpgSources()
		self.removePicons()
		self.removeVoDData()

	def removeBouquets(self):
		from enigma import eDVBDB
		eDVBDB.getInstance().removeBouquet(re.escape(self.cleanFilename(f"userbouquet.m3uiptv.{self.scheme}.")) + r".*[.]tv")
		eDVBDB.getInstance().removeBouquet(re.escape(self.cleanFilename(f"subbouquet.m3uiptv.{self.scheme}.")) + r".*[.]tv")

	def removeBouquet(self, filename):
		from enigma import eDVBDB
		eDVBDB.getInstance().removeBouquet(re.escape(filename))

	def removeVoDData(self):
		shutil.rmtree(self.getTempDir(), True)

		if fileExists(USER_IPTV_MOVIE_CATEGORIES_FILE % self.scheme):
			remove_file(USER_IPTV_MOVIE_CATEGORIES_FILE % self.scheme)
		if fileExists(USER_IPTV_SERIES_CATEGORIES_FILE % self.scheme):
			remove_file(USER_IPTV_SERIES_CATEGORIES_FILE % self.scheme)
		if fileExists(USER_IPTV_VOD_MOVIES_FILE % self.scheme):
			remove_file(USER_IPTV_VOD_MOVIES_FILE % self.scheme)
		if fileExists(USER_IPTV_VOD_SERIES_FILE % self.scheme):
			remove_file(USER_IPTV_VOD_SERIES_FILE % self.scheme)
		self.vod_movies = []
		self.vod_series = {}

	def removeEpgSources(self):
		epghelper = epgimport_helper(self)
		epghelper.removeSources()

	def cleanFilename(self, name):
		return sanitizeFilename(name.replace(" ", "").replace("(", "").replace(")", "").replace("&", "").replace("'", "").replace('"', "").replace('*', "").replace(',', "").replace(":", "").replace(";", "").replace('ы', 'и'))

	def readBlacklist(self, blacklist_type=0):
		file = USER_IPTV_PROVIDER_BLACKLIST_FILE % self.scheme
		if blacklist_type == 1:
			file = USER_IPTV_PROVIDER_VOD_MOVIES_BLACKLIST_FILE % self.scheme
		elif blacklist_type == 2:
			file = USER_IPTV_PROVIDER_VOD_SERIES_BLACKLIST_FILE % self.scheme
		return self.getBlacklist(file)

	def readExampleBlacklist(self, blacklist_type=0):
		file = (USER_IPTV_PROVIDER_BLACKLIST_FILE % self.scheme) + ".example"
		if blacklist_type == 1:
			file = (USER_IPTV_PROVIDER_VOD_MOVIES_BLACKLIST_FILE % self.scheme) + ".example"
		elif blacklist_type == 2:
			file = (USER_IPTV_PROVIDER_VOD_SERIES_BLACKLIST_FILE % self.scheme) + ".example"
		return self.getBlacklist(file)

	def getBlacklist(self, file):
		if fileExists(file):
			try:
				return [stripped for line in open(file, "r").readlines() if (stripped := line.strip())]
			except Exception as err:
				print("[IPTVProcessor] readBlacklist, error reading blacklist", err)
		return []

	def writeExampleBlacklist(self, examples, blacklist_type=0):
		file = (USER_IPTV_PROVIDER_BLACKLIST_FILE % self.scheme) + ".example"
		if blacklist_type == 1:
			file = (USER_IPTV_PROVIDER_VOD_MOVIES_BLACKLIST_FILE % self.scheme) + ".example"
		elif blacklist_type == 2:
			file = (USER_IPTV_PROVIDER_VOD_SERIES_BLACKLIST_FILE % self.scheme) + ".example"
		if examples:
			examples.insert(0, _("# only leave the groups you want to remove in blacklist below and then rename the file to %s and regenerate the bouquets") % (USER_IPTV_PROVIDER_BLACKLIST_FILE % self.scheme))
			open(file, "w").write("\n".join(examples))

	def writeBlacklist(self, blacklist, blacklist_type=0):
		file = USER_IPTV_PROVIDER_BLACKLIST_FILE % self.scheme
		if blacklist_type == 1:
			file = USER_IPTV_PROVIDER_VOD_MOVIES_BLACKLIST_FILE % self.scheme
		elif blacklist_type == 2:
			file = USER_IPTV_PROVIDER_VOD_SERIES_BLACKLIST_FILE % self.scheme
		open(file, "w").write("\n".join(blacklist))

	def piconsAdd(self, stream_icon, ch_name):
		if ch_name := sanitizeFilename(ch_name.lower()):
			if not stream_icon.startswith('http'):
				stream_icon = 'http://' + stream_icon
			if stream_icon not in self.picon_database:
				self.picon_database[stream_icon] = []
			if ch_name not in self.picon_database[stream_icon]:
				self.picon_database[stream_icon].append(ch_name)

	def piconsSrefAdd(self, stream_icon, ch_sref):
		sref_split = ch_sref.split(":")
		ch_sref_picon = "_".join(sref_split[:10])
		if not stream_icon.startswith('http'):
			stream_icon = 'http://' + stream_icon
		if stream_icon not in self.picon_sref_database:
			self.picon_sref_database[stream_icon] = []
		if ch_sref_picon not in self.picon_sref_database[stream_icon]:
			self.picon_sref_database[stream_icon].append(ch_sref_picon)

	def piconsDownload(self):
		if self.picons:
			if Process:
				p = Process(target=piconsDownloadProcess, args=(self,))
				p.start()
			else:
				fetcher = Fetcher(self)
				fetcher.fetchall()
				fetcher.createSoftlinks()

	# This function should be made available to the interface.
	# Removes all picons for the current provider.
	def removePicons(self):
		fetcher = Fetcher(self)
		fetcher.removeall()


def piconsDownloadProcess(self):
	print("Downloading picons starting")
	fetcher = Fetcher(self)
	fetcher.fetchall()
	fetcher.createSoftlinks()
	print("Picon download completed")
