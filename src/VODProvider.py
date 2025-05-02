from . import _

from enigma import eDVBDB
from Components.config import config
from Tools.Directories import fileExists
import urllib, re, json
from .IPTVProcessor import IPTVProcessor
from .VoDItem import VoDItem
from .Variables import CATCHUP_DEFAULT, USER_IPTV_MOVIE_CATEGORIES_FILE, USER_IPTV_VOD_MOVIES_FILE, USER_IPTV_VOD_SERIES_FILE

db = eDVBDB.getInstance()


class VODProvider(IPTVProcessor):
	def __init__(self):
		IPTVProcessor.__init__(self)
		self.type = "VOD"
		self.playlist = None
		self.isPlayBackup = False
		self.offset = 0
		self.progress_percentage = -1
		self.create_epg = True
		self.catchup_type = CATCHUP_DEFAULT
		self.play_system_vod = "4097"
		self.play_system_catchup = "4097"

	def storePlaylistAndGenBouquet(self):
		playlist = None
		if not self.isLocalPlaylist():
			self.checkForNetwrok()
			req = self.constructRequest(self.url)
			req_timeout_val = config.plugins.m3uiptv.req_timeout.value
			if req_timeout_val != "off":
				response = urllib.request.urlopen(req, timeout=int(req_timeout_val))
			else:
				response = urllib.request.urlopen(req, timeout=10)  # set a timeout to prevent blocking
			playlist = response.read().decode('utf-8')
		else:
			if not fileExists(self.url):
				return
			fd = open(self.url, 'rb')
			playlist = fd.read().decode('utf-8')
		self.playlist = playlist
		playlist_splitted = playlist.splitlines()
		tsid = 1000
		services = []
		groups = {"ALL": []}  # add fake, user-optional, all-channels bouquet
		curr_group = None
		line_nr = 0
		for line in playlist_splitted:
			if self.playlist_type == "m3u":
				if line.startswith("#EXTINF:"):
					gr_match = re.search(r"group-title=\"(.*?)\"", line)
					if gr_match:
						curr_group = gr_match.group(1)
						if curr_group not in groups:
							groups[curr_group] = []
					else:
						curr_group = None
					# possible issue is if there are "," in the service name
					ch_name = line.split(",")[-1].strip()
					url = ""
					found_url = False
					next_line_nr = line_nr + 1
					while not found_url:
						if len(playlist_splitted) > next_line_nr:
							next_line = playlist_splitted[next_line_nr].strip()
							if next_line.startswith(("http://", "https://")):
								url = next_line.replace(":", "%3a")
								found_url = True
							else:
								next_line_nr += 1
						else:
							break
					if curr_group:
						groups[curr_group].append((url, ch_name, ch_name, tsid))
					else:
						services.append((url, ch_name, ch_name, tsid))
				line_nr += 1
				tsid += 1
			elif self.playlist_type == "txt":
				if self.iptv_service_provider not in groups:
					groups[self.iptv_service_provider] = []
				data = line.split(",")
				if len(data) < 2:
					continue
				ch_name = data[0]
				url = data[1].replace(":", "%3a")
				groups[self.iptv_service_provider].append((url, ch_name, ch_name, tsid))
				tsid += 1

		self.generateMediaLibrary(groups, services)
		self.bouquetCreated(None)

	def getVODCategories(self, groups, services):
		try:
			genres = []
			for groupName, srefs in groups.items():
				gid = groupName
				name = groupName
				genres.append({'category_name': name, 'category_type': 'VOD', 'category_id': gid})
			if len(services) > 0:
				genres.append({'category_name': _("UNCATEGORIZED"), 'category_type': 'VOD', 'category_id': "UNCATEGORIZED"})
			dest_file = USER_IPTV_MOVIE_CATEGORIES_FILE % self.scheme
			return self.getDataToFile(genres, dest_file)
		except Exception as ex:
			print("[M3UIPTV][VOD] Error getting vod genres: " + str(ex))
			pass

	def generateMediaLibrary(self, groups=None, services=None):
		vod_categories = self.getVODCategories(groups, services)
		for category in vod_categories:
			self.movie_categories[category["category_id"]] = category["category_name"]
		movies = []
		series = []
		for groupName, srefs in groups.items():
			for vod in srefs:
				item = {}
				item["num"] = str(vod[3])
				item["stream_id"] = vod[3]
				item["container_extension"] = "ts"
				item["name"] = vod[2]
				item["stream_type"] = "movie"
				item["stream_icon"] = ""
				item["rating"] = ""
				item["added"] = ""
				item["is_adult"] = "0"
				item["category_id"] = groupName
				item["hd"] = "0"
				item["tmdb_id"] = ""
				item["plot"] = ""
				item["director"] = ""
				item["actors"] = ""
				item["year"] = ""
				item["genres_str"] = ""
				item["play_url"] = vod[0]
				movies.append(item)
		for vod in services:
			item = {}
			item["num"] = str(vod[3])
			item["stream_id"] = vod[3]
			item["container_extension"] = "ts"
			item["name"] = vod[2]
			item["stream_type"] = "movie"
			item["stream_icon"] = ""
			item["rating"] = ""
			item["added"] = ""
			item["is_adult"] = "0"
			item["category_id"] = "UNCATEGORIZED"
			item["hd"] = "0"
			item["tmdb_id"] = ""
			item["plot"] = ""
			item["director"] = ""
			item["actors"] = ""
			item["year"] = ""
			item["genres_str"] = ""
			item["play_url"] = vod[0]
			movies.append(item)
		
		if len(movies) > 0:
			dest_file_movies = USER_IPTV_VOD_MOVIES_FILE % self.scheme
			self.v_movies = self.getDataToFile(movies, dest_file_movies)
		if len(series) > 0:
			dest_file_series = USER_IPTV_VOD_SERIES_FILE % self.scheme
			self.v_series = self.getDataToFile(series, dest_file_series)
		self.loadMedialLibraryItems()

	def makeVodListFromJson(self, json_string):
		if json_string:
			vod_json_obj = json.loads(json_string)
			for movie in vod_json_obj:
				name = movie["name"]
				id = movie["stream_id"]
				url = movie["play_url"]
				vod_item = VoDItem(url, name, id, self, self.movie_categories.get(str(movie.get("category_id"))), movie.get("plot"), movie.get("stream_icon"))
				self.vod_movies.append(vod_item)

	def loadVoDMoviesFromFile(self):
		self.vod_movies = []
		vodFile = USER_IPTV_VOD_MOVIES_FILE % self.scheme
		json_string = self.loadFromFile(vodFile)
		self.makeVodListFromJson(json_string)
		for x in self.onProgressChanged:
			x()
	
	def loadMedialLibraryItems(self):
		self.loadMovieCategoriesFromFile()
		self.loadVoDMoviesFromFile()
		self.loadSeriesCategoriesFromFile()
		self.loadVoDSeriesFromFile()
