from twisted.internet import threads
from .epgimport_helper import epgimport_helper
from .Variables import USER_AGENT, CATCHUP_DEFAULT, CATCHUP_DEFAULT_TEXT, CATCHUP_APPEND_TEXT, CATCHUP_SHIFT_TEXT, CATCHUP_XTREME_TEXT, CATCHUP_STALKER_TEXT
from .VoDItem import VoDItem
from Components.config import config
from Tools.Directories import sanitizeFilename, fileExists
from os import fsync, rename
import re
import json
import socket
import urllib
import threading
from time import time
from datetime import datetime

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
		url = sref_split[10:][0]
		return f"{url}&utc={str(stime)}&lutc={str(etime)}"
	elif catchup_type == CATCHUP_XTREME_TEXT:
		sref_split = sref.split(":")
		url = sref_split[10:][0]
		match = re.search(r"[\/]\d*\.ts|[\/]\d*\.m3u8", url)
		if match:
			end_s = match.group(0)
			url = url.replace("/live/", "/timeshift/").replace(end_s, f'/{duration}/{datetime.fromtimestamp(stime).strftime("%Y-%m-%d:%H-%M")}{end_s}')
		return url
	elif catchup_type == CATCHUP_STALKER_TEXT:
		pass
	return url_play


class IPTVProcessor():
	def __init__(self):
		self.type = "M3U" # default type M3U. Possible Types: M3U, Xtreem, Stalker
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
		self.onBouquetCreated = []
		self.progress_percentage = -1
		self.update_status_callback = []  # for passing messages
		self.epg_url = ""
		self.catchup_type = CATCHUP_DEFAULT
		self.play_system_vod = "4097"
		self.play_system_catchup = self.play_system
		self.movie_categories = {}
		
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

	def getJsonUrl(self, url, dest_file):
		is_check_network_val = config.plugins.m3uiptv.check_internet.value
		if is_check_network_val != "off":
			socket.setdefaulttimeout(int(is_check_network_val))
			socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("8.8.8.8", 53))
		req = urllib.request.Request(url, headers={'User-Agent' : USER_AGENT}) 
		req_timeout_val = config.plugins.m3uiptv.req_timeout.value
		if req_timeout_val != "off":
			response = urllib.request.urlopen(req, timeout=int(req_timeout_val))
		else:
			response = urllib.request.urlopen(req)
		vod_response = response.read()
		with write_lock:
			f = open(dest_file + ".writing", 'wb')
			f.write(vod_response)
			f.flush()
			fsync(f.fileno())
			f.close()
			rename(dest_file + ".writing", dest_file)
		return vod_response

	def loadJsonFromFile(self, source_file):
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
				vod_item = VoDItem(url, name, self.movie_categories.get(movie.get("category_id")))
				self.vod_movies.append(vod_item)

	def processService(self, nref, iptvinfodata, callback=None):
		return nref, nref, False
	
	def bouquetCreated(self, error):
		for f in self.onBouquetCreated:
			f(self, error)

	def generateChannelReference(self, type, tsid, url, name):
		return "%s:0:%s:%x:%x:1:CCCC0000:0:0:0:%s:%s•%s" % (self.play_system, type, tsid, self.onid, url.replace(":", "%3a"), name, self.iptv_service_provider)
	
	def getEpgUrl(self):
		return ""
	
	def generateEPGImportFiles(self, groups):
		if not self.create_epg:
			return
		epghelper = epgimport_helper(self)
		epghelper.createSourcesFile()
		epghelper.createChannelsFile(groups)

		epghelper.importepg()  # auto epg update after bouquet generation


	def generateEPGChannelReference(self, original_sref):
		return f"{':'.join(original_sref.split(':', 10)[:10])}:http%3a//m3u.iptv.com"

	def constructCatchupSufix(self, days, url, catchup_type):
		if days.strip() and int(days) > 0:
			captchup_addon = "%scatchuptype=%s&catchupdays=%s" % ("&" if "?" in url else "?", catchup_type, days)
			return url + captchup_addon
		return url

	def removeBouquets(self):
		from enigma import eDVBDB
		search_bouquets_criteria = re.escape(sanitizeFilename(f"userbouquet.m3uiptv.{self.iptv_service_provider}.".replace(" ", "").replace("(", "").replace(")", "").replace("&", ""))) + r".*[.]tv"
		eDVBDB.getInstance().removeBouquet(search_bouquets_criteria)