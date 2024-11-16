from twisted.internet import threads
from .epgimport_helper import epgimport_helper
from .Variables import USER_AGENT, CATCHUP_DEFAULT, CATCHUP_DEFAULT_TEXT, CATCHUP_APPEND_TEXT, CATCHUP_SHIFT_TEXT, CATCHUP_XTREME_TEXT, CATCHUP_STALKER_TEXT, CATCHUP_FLUSSONIC_TEXT, USER_IPTV_PROVIDER_BLACKLIST_FILE, USER_FOLDER
from .VoDItem import VoDItem
from .picon import Fetcher
from Components.config import config
from Tools.Directories import sanitizeFilename, fileExists
from os import fsync, rename, path, makedirs, listdir, remove as remove_file
import re
import json
import socket
import urllib
import threading
import shutil
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
		pass
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
		if len(match.groups()) > 4:
			fsHost = match.group(1)
			fsChannelId = match.group(2)
			fsListType = match.group(3)
			fsStreamType = match.group(4)
			fsUrlAppend = match.group(5).split("&")[0]
			isCatchupTSStream = fsStreamType == "mpegts"
			if isCatchupTSStream:
				catchupSource = fsHost + "/" + fsChannelId + "/timeshift_abs-${start}.ts" + fsUrlAppend
			else:
				if fsListType == "index":
					catchupSource = fsHost + "/" + fsChannelId + "/timeshift_rel-{offset:1}.m3u8" + fsUrlAppend
				else:
					catchupSource = fsHost + "/" + fsChannelId + "/" + fsListType + "-timeshift_rel-{offset:1}.m3u8" + fsUrlAppend
			return catchupSource
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
		self.vod_movies = []
		self.vod_series = {}
		self.onBouquetCreated = []
		self.progress_percentage = -1
		self.update_status_callback = []  # for passing messages
		self.epg_url = ""
		self.catchup_type = CATCHUP_DEFAULT
		self.play_system_vod = "4097"
		self.play_system_catchup = "4097"
		self.movie_categories = {}
		self.is_dynamic_epg = False
		self.is_custom_xmltv = False
		self.custom_xmltv_url = ""
		self.server_timezone_offset = 0
		self.provider_info = {}
		self.picons = False
		self.picon_database = {}

	def isLocalPlaylist(self):
		return not self.url.startswith(("http://", "https://"))

	def getTempDir(self):
		return path.join(path.realpath("/tmp"), "M3UIPTV", self.scheme)

	def getPlaylistAndGenBouquet(self, callback=None):
		if callback:
			threads.deferToThread(self.storePlaylistAndGenBouquet).addCallback(callback)
		else:
			self.storePlaylistAndGenBouquet()

	def storePlaylistAndGenBouquet(self):
		pass

	def getVoDMovies(self):
		pass

	def getMovieCategories(self):
		pass

	def loadMovieCategoriesFromFile(self):
		pass

	def loadVoDMoviesFromFile(self):
		pass

	def getVoDSeries(self):
		pass

	def loadVoDSeriesFromFile(self):
		pass

	def loadInfoFromFile(self):
		pass

	def makeVodSeriesDictFromJson(self, json_string):
		self.vod_series = {}
		if json_string:
			series = json.loads(json_string)
			for x in series:
				genre = x.get("genre")
				name = x.get("title") or x.get("name")
				series_id = x.get("series_id") and str(x["series_id"])
				if genre is None:
					genre = "UNCATEGORIZED"
				else:
					genre = ", ".join([s for s in sorted(map(str.strip, genre.replace("&amp;", "&").replace("/", ",").split(",")))])
				if name and series_id:
					if genre not in self.vod_series:
						self.vod_series[genre] = []
					self.vod_series[genre].append((series_id, name))

	def getSeriesById(self, series_id):
		ret = []
		titles = []  # this is a temporary hack to avoid duplicates when there are multiple container extensions
		file = path.join(self.getTempDir(), series_id)
		url = "%s/player_api.php?username=%s&password=%s&action=get_series_info&series_id=%s" % (self.url, self.username, self.password, series_id)
		json_string = self.loadFromFile(file) or self.getUrlToFile(url, file)
		if json_string:
			series = json.loads(json_string)
			episodes = series.get("episodes")
			if episodes:
				for season in episodes:
					iter = episodes[season] if isinstance(episodes, dict) else season  # this workaround is because there are multiple json formats for series
					for episode in iter:
						id = episode.get("id") and str(episode["id"])
						title = episode.get("title") and str(episode["title"])
						info = episode.get("info")
						print("getSeriesById info", info)
						marker = []
						if info and info.get("season"):
							marker.append(_("S%s") % str(info.get("season")))
						episode_num = episode.get("episode_num") and str(episode["episode_num"])
						if episode_num:
							marker.append(_("Ep%s") % episode_num)
						if marker:
							marker = ["[%s]" % " ".join(marker)]
						if info and (duration := info.get("duration")):
							marker.insert(0, _("Duration: %s") % str(duration))
						if info and (date := info.get("release_date") or info.get("releasedate") or info.get("air_date")):
							if date[:4].isdigit():
								date = date[:4]
							marker.insert(0, _("Released: %s") % str(date))
						ext = episode.get("container_extension")
						episode_url = "%s/series/%s/%s/%s.%s" % (self.url, self.username, self.password, id, ext)
						if title and info and title not in titles:
							ret.append((episode_url, title, info, self, ", ".join(marker)))
							titles.append(title)
		return ret

	def getUrl(self, url):
		is_check_network_val = config.plugins.m3uiptv.check_internet.value
		if is_check_network_val != "off":
			socket.setdefaulttimeout(int(is_check_network_val))
			socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("8.8.8.8", 53))
		req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
		req_timeout_val = config.plugins.m3uiptv.req_timeout.value
		if req_timeout_val != "off":
			response = urllib.request.urlopen(req, timeout=int(req_timeout_val))
		else:
			response = urllib.request.urlopen(req, timeout=10) # set a timeout to prevent blocking
		return response.read()

	def getUrlToFile(self, url, dest_file):
		vod_response = self.getUrl(url)
		makedirs(path.realpath(path.dirname(dest_file)), exist_ok=True)  # make folders and sub folders if not exists
		with write_lock:
			f = open(dest_file + ".writing", 'wb')
			f.write(vod_response)
			f.flush()
			fsync(f.fileno())
			f.close()
			rename(dest_file + ".writing", dest_file)
		return vod_response

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
				vod_item = VoDItem(url, name, id, self, self.movie_categories.get(movie.get("category_id")), movie.get("plot"))
				self.vod_movies.append(vod_item)

	def processService(self, nref, iptvinfodata, callback=None):
		return nref, nref, False

	def bouquetCreated(self, error):
		for f in self.onBouquetCreated:
			f(self, error)

	def generateChannelReference(self, type, tsid, url, name):
		return "%s:0:%s:%X:%X:1:CCCC0000:0:0:0:%s:%s•%s" % (self.play_system, type, tsid, self.onid, url.replace(":", "%3a"), name, self.iptv_service_provider)

	def getEpgUrl(self):  # if not overridden in the subclass
		return self.custom_xmltv_url if self.is_custom_xmltv and self.custom_xmltv_url else self.epg_url

	def getEpgUrlForSources(self):  # for use when dynamic xmltv url is needed for sources file
		return self.custom_xmltv_url if self.is_custom_xmltv and self.custom_xmltv_url else self.epg_url

	def generateEPGImportFiles(self, groups):
		if not self.create_epg or not self.getEpgUrl():
			return
		epghelper = epgimport_helper(self)
		epghelper.createSourcesFile()
		epghelper.createChannelsFile(groups)

		epghelper.importepg()  # auto epg update after bouquet generation

	def generateEPGChannelReference(self, original_sref):
		return f"{':'.join(original_sref.split(':', 10)[:10])}:http%3a//m3u.iptv.com"

	def constructCatchupSufix(self, days, url, catchup_type):
		if days.strip() and int(days) > 0:
			captchup_addon = "%scatchuptype=%s&catchupdays=%s&catchupstype=%s" % ("&" if "?" in url else "?", catchup_type, days, self.play_system_catchup)
			if catchup_type == CATCHUP_XTREME_TEXT and self.server_timezone_offset:
				captchup_addon += "&tz_offset=%d" % self.server_timezone_offset
			return url + captchup_addon
		return url

	def removeBouquets(self):
		from enigma import eDVBDB
		eDVBDB.getInstance().removeBouquet(re.escape(self.cleanFilename(f"userbouquet.m3uiptv.{self.iptv_service_provider}.")) + r".*[.]tv") # left temporarilly so we can delete bouquets with the old filenames 
		eDVBDB.getInstance().removeBouquet(re.escape(self.cleanFilename(f"userbouquet.m3uiptv.{self.scheme}.")) + r".*[.]tv")

	def removeBouquet(self, filename):
		from enigma import eDVBDB
		eDVBDB.getInstance().removeBouquet(re.escape(filename))

	def removeVoDData(self):
		shutil.rmtree(self.getTempDir(), True)
		for file in listdir(USER_FOLDER):
			if file.startswith(self.scheme):
				remove_file(path.join(USER_FOLDER, file))

	def cleanFilename(self, name):
		return sanitizeFilename(name.replace(" ", "").replace("(", "").replace(")", "").replace("&", "").replace("'", "").replace('"', "").replace(',', "").replace(":", "").replace(";", ""))

	def readBlacklist(self):
		file = USER_IPTV_PROVIDER_BLACKLIST_FILE % self.scheme
		return self.getBlacklist(file)

	def readExampleBlacklist(self):
		file = (USER_IPTV_PROVIDER_BLACKLIST_FILE % self.scheme) + ".example"
		return self.getBlacklist(file)

	def getBlacklist(self, file):
		if fileExists(file):
			try:
				return [stripped for line in open(file, "r").readlines() if (stripped := line.strip())]
			except Exception as err:
				print("[IPTVProcessor] readBlacklist, error reading blacklist", err)
		return []

	def writeExampleBlacklist(self, examples):
		file = (USER_IPTV_PROVIDER_BLACKLIST_FILE % self.scheme) + ".example"
		if examples:
			examples.insert(0, _("# only leave the groups you want to remove in blacklist below and then rename the file to %s and regenerate the bouquets") % (USER_IPTV_PROVIDER_BLACKLIST_FILE % self.scheme))
			open(file, "w").write("\n".join(examples))

	def writeBlacklist(self, blacklist):
		file = USER_IPTV_PROVIDER_BLACKLIST_FILE % self.scheme
		open(file, "w").write("\n".join(blacklist))

	def piconsAdd(self, stream_icon, ch_name):
		if ch_name := sanitizeFilename(ch_name.lower()):
			if not stream_icon.startswith('http'):
				stream_icon = 'http://' + stream_icon
			if stream_icon not in self.picon_database:
				self.picon_database[stream_icon] = []
			if ch_name not in self.picon_database[stream_icon]:
				self.picon_database[stream_icon].append(ch_name)

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
