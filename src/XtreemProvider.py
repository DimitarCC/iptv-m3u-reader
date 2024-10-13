from enigma import eDVBDB
from Components.config import config
import socket
import urllib
import json
import time
from .IPTVProcessor import IPTVProcessor
from .Variables import USER_IPTV_VOD_MOVIES_FILE, USER_AGENT, USER_IPTV_MOVIE_CATEGORIES_FILE, USER_IPTV_PROVIDER_INFO_FILE, USER_IPTV_VOD_SERIES_FILE, CATCHUP_XTREME, CATCHUP_XTREME_TEXT

db = eDVBDB.getInstance()

class XtreemProvider(IPTVProcessor):
	def __init__(self):
		IPTVProcessor.__init__(self)
		self.type = "Xtreeme"
		self.refresh_interval = -1
		self.vod_movies = []
		self.progress_percentage = -1
		self.create_epg = True
		self.catchup_type = CATCHUP_XTREME
		self.play_system_vod = "4097"
		self.play_system_catchup = self.play_system
		
	def getEpgUrl(self):
		return self.custom_xmltv_url if self.is_custom_xmltv and self.custom_xmltv_url else "%s/xmltv.php?username=%s&password=%s" % (self.url, self.username, self.password)

	def storePlaylistAndGenBouquet(self):
		is_check_network_val = config.plugins.m3uiptv.check_internet.value
		if is_check_network_val != "off":
			socket.setdefaulttimeout(int(is_check_network_val))
			socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("8.8.8.8", 53))
		self.getServerTZoffset()
		url = "%s/player_api.php?username=%s&password=%s&action=get_live_streams" % (self.url, self.username, self.password)
		req = urllib.request.Request(url, headers={'User-Agent' : USER_AGENT}) 
		req_timeout_val = config.plugins.m3uiptv.req_timeout.value
		if req_timeout_val != "off":
			response = urllib.request.urlopen(req, timeout=int(req_timeout_val))
		else:
			response = urllib.request.urlopen(req)
		services_response = response.read()
		services_json_obj = json.loads(services_response)
		tsid = 1000
		groups = {}

		url = "%s/player_api.php?username=%s&password=%s&action=get_live_categories" % (self.url, self.username, self.password)
		req = urllib.request.Request(url, headers={'User-Agent' : USER_AGENT}) 
		if req_timeout_val != "off":
			response = urllib.request.urlopen(req, timeout=int(req_timeout_val))
		else:
			response = urllib.request.urlopen(req)

		groups_response = response.read()
		groups_json_obj = json.loads(groups_response)

		for group in groups_json_obj:
			groups[group["category_id"]] = (group["category_name"], [])

		groups["EMPTY"] = ("UNCATEGORIZED", [])  # put "EMPTY" in last place

		for service in services_json_obj:
			surl = "%s/live/%s/%s/%s.%s" % (self.url, self.username, self.password, service["stream_id"], "ts" if self.play_system == "1" else "m3u8")
			catchup_days = service["tv_archive_duration"]
			if catchup_days:
				surl = self.constructCatchupSufix(str(catchup_days), surl, CATCHUP_XTREME_TEXT)
			ch_name = service["name"].replace(":", "|")
			epg_id = service["epg_channel_id"]
			stype = "1"
			if ("UHD" in ch_name or "4K" in ch_name) and not " HD" in ch_name:
				stype = "1F"
			elif "HD" in ch_name:
				stype = "19"
			sref = self.generateChannelReference(stype, tsid, surl.replace(":", "%3a"), ch_name)
			tsid += 1
			groups[service["category_id"] if service["category_id"] else "EMPTY"][1].append((sref, epg_id, ch_name))

		if not self.ignore_vod:
			self.getMovieCategories()
			self.getVoDMovies()
			self.getVoDSeries()

		examples = []
		blacklist = self.readBlacklist()

		for groupItem in groups.values():
			examples.append(groupItem[0])
			if groupItem[1]:  # don't create the bouquet if there are no services
				bfilename =  self.cleanFilename(f"userbouquet.m3uiptv.{self.iptv_service_provider}.{groupItem[0]}.tv")
				if groupItem[0] in blacklist:
					self.removeBouquet(bfilename)  # remove blacklisted bouquet if already exists
					continue
				services = []
				for x in groupItem[1]:
					services.append(x[0])
				db.addOrUpdateBouquet(self.iptv_service_provider.upper() + " - " + groupItem[0], bfilename, services, False)
		self.writeExampleBlacklist(examples)
		self.generateEPGImportFiles(groups)
		self.bouquetCreated(None)

	def getVoDMovies(self):
		self.vod_movies = []
		url = "%s/player_api.php?username=%s&password=%s&action=get_vod_streams" % (self.url, self.username, self.password)
		dest_file = USER_IPTV_VOD_MOVIES_FILE % self.scheme
		json_string = self.getUrlToFile(url, dest_file)
		self.makeVodListFromJson(json_string)

	def loadVoDMoviesFromFile(self):
		self.vod_movies = []
		vodFile = USER_IPTV_VOD_MOVIES_FILE % self.scheme
		json_string = self.loadFromFile(vodFile)
		self.makeVodListFromJson(json_string)

	def getVoDSeries(self):
		self.vod_series = {}
		url = "%s/player_api.php?username=%s&password=%s&action=get_series" % (self.url, self.username, self.password)
		dest_file = USER_IPTV_VOD_SERIES_FILE % self.scheme
		json_string = self.getUrlToFile(url, dest_file)
		self.makeVodSeriesDictFromJson(json_string)

	def loadVoDSeriesFromFile(self):
		self.vod_series = {}
		vodFile = USER_IPTV_VOD_SERIES_FILE % self.scheme
		json_string = self.loadFromFile(vodFile)
		self.makeVodSeriesDictFromJson(json_string)

	def getServerTZoffset(self):
		url = "%s/player_api.php?username=%s&password=%s" % (self.url, self.username, self.password)
		dest_file = USER_IPTV_PROVIDER_INFO_FILE % self.scheme
		json_string = self.getUrlToFile(url, dest_file)
		if json_string:
			self.provider_info = info = json.loads(json_string)
			server_time = info and info.get("server_info") and info["server_info"].get("time_now")
			if server_time:
				try:  # just in case format string is in unexpected format
					servertime = time.mktime(time.strptime(server_time, '%Y-%m-%d %H:%M:%S'))
					self.server_timezone_offset = int(round((servertime - time.time()) / 600) * 600)  # force output to be in sync
					from .plugin import writeProviders  # deferred import
					writeProviders()  # save to config so it doesn't get lost on reboot
				except Exception as err:
					print("[XtreemProvider] getServerTZoffset, an error occured", err)

	def loadInfoFromFile(self):
		info_file = USER_IPTV_PROVIDER_INFO_FILE % self.scheme
		json_string = self.loadFromFile(info_file)
		if json_string:
			self.provider_info = json.loads(json_string)

	def getMovieCategories(self):
		url = "%s/player_api.php?username=%s&password=%s&action=get_vod_categories" % (self.url, self.username, self.password)
		dest_file = USER_IPTV_MOVIE_CATEGORIES_FILE % self.scheme
		json_string = self.getUrlToFile(url, dest_file)
		self.makeMovieCategoriesDictFromJson(json_string)

	def loadMovieCategoriesFromFile(self):
		vodFile = USER_IPTV_MOVIE_CATEGORIES_FILE % self.scheme
		json_string = self.loadFromFile(vodFile)
		self.makeMovieCategoriesDictFromJson(json_string)

	def makeMovieCategoriesDictFromJson(self, json_string):
		self.movie_categories = {}
		if json_string:
			for category in json.loads(json_string):
				self.movie_categories[category["category_id"]] = category["category_name"]

