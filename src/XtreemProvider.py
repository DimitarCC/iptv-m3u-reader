from . import _

import urllib, json, time
from enigma import eDVBDB
from Components.config import config
from os import path
from .IPTVProcessor import IPTVProcessor
from .Variables import USER_IPTV_VOD_MOVIES_FILE, REQUEST_USER_AGENT, USER_IPTV_MOVIE_CATEGORIES_FILE, USER_IPTV_PROVIDER_INFO_FILE, USER_IPTV_VOD_SERIES_FILE, CATCHUP_XTREME, CATCHUP_XTREME_TEXT, USER_IPTV_SERIES_CATEGORIES_FILE

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
		self.play_system_catchup = "4097"

	def getEpgUrl(self):
		return self.custom_xmltv_url if self.is_custom_xmltv and self.custom_xmltv_url else "%s/xmltv.php?username=%s&password=%s" % (self.url, self.username, self.password)

	def storePlaylistAndGenBouquet(self):
		self.checkForNetwrok()
		self.getProviderInfo()
		url = "%s/player_api.php?username=%s&password=%s&action=get_live_streams" % (self.url, self.username, self.password)
		req = urllib.request.Request(url, headers={'User-Agent': REQUEST_USER_AGENT})
		req_timeout_val = config.plugins.m3uiptv.req_timeout.value
		if req_timeout_val != "off":
			response = urllib.request.urlopen(req, timeout=int(req_timeout_val))
		else:
			response = urllib.request.urlopen(req, timeout=10)  # set a timeout to prevent blocking
		services_response = response.read()
		services_json_obj = json.loads(services_response)
		tsid = 1000

		groups = {"ALL_CHANNELS": (_("All channels"), [])}  # add fake, user-optional, all-channels bouquet

		url = "%s/player_api.php?username=%s&password=%s&action=get_live_categories" % (self.url, self.username, self.password)
		req = urllib.request.Request(url, headers={'User-Agent': REQUEST_USER_AGENT})
		if req_timeout_val != "off":
			response = urllib.request.urlopen(req, timeout=int(req_timeout_val))
		else:
			response = urllib.request.urlopen(req, timeout=10)  # set a timeout to prevent blocking

		groups_response = response.read()
		groups_json_obj = json.loads(groups_response)

		for group in groups_json_obj:
			if (category_id := group.get("category_id")) and (category_name := group.get("category_name")):
				groups[category_id] = (category_name, [])

		groups["EMPTY"] = (_("UNCATEGORIZED"), [])  # put "EMPTY" in last place

		blacklist = self.readBlacklist()

		for service in services_json_obj:
			stream_id = service.get("stream_id")
			ch_name = service.get("name") and service["name"].replace(":", "|")
			ch_num = service.get("num")
			epg_id = service.get("epg_channel_id")
			category_id = service.get("category_id")
			if not (stream_id and ch_name):
				continue
			if self.use_provider_tsid and ch_num:
				tsid = int(ch_num)
			surl = "%s/live/%s/%s/%s.%s" % (self.url, self.username, self.password, stream_id, self.output_format)
			catchup_days = service.get("tv_archive_duration")
			if catchup_days:
				surl = self.constructCatchupSuffix(str(catchup_days), surl, CATCHUP_XTREME_TEXT)
			stype = "1"
			if ("UHD" in ch_name or "4K" in ch_name) and " HD" not in ch_name:
				stype = "1F"
			elif "HD" in ch_name:
				stype = "19"
			sref = self.generateChannelReference(stype, tsid, surl.replace(":", "%3a"), ch_name)

			if self.create_bouquets_strategy > 0:  # config option here: for user-optional, all-channels bouquet
				if category_id not in groups or groups[category_id][0] not in blacklist:
					groups["ALL_CHANNELS"][1].append((sref, epg_id, ch_name, tsid, ch_num))

			if self.create_bouquets_strategy != 1:  # config option here: for sections bouquets
				groups[category_id if category_id and category_id in groups else "EMPTY"][1].append((sref, epg_id, ch_name, tsid, ch_num))

			if stream_icon := service.get("stream_icon"):
				if self.picon_gen_strategy == 0:
					self.piconsAdd(stream_icon, ch_name)
				else:
					self.piconsSrefAdd(stream_icon, sref)
			if not self.use_provider_tsid:
				tsid += 1

		self.generateMediaLibrary()

		examples = []

		for groupItem in groups.values():
			examples.append(groupItem[0])
			if groupItem[1]:  # don't create the bouquet if there are no services
				bfilename = self.cleanFilename(f"userbouquet.m3uiptv.{self.scheme}.{groupItem[0]}.tv")
				if groupItem[0] in blacklist:
					self.removeBouquet(bfilename)  # remove blacklisted bouquet if already exists
					continue
				services = []
				service_list = groupItem[1]
				if self.ch_order_strategy > 0:
					service_list.sort(key=lambda x: (x[4] if self.ch_order_strategy == 1 else x[2]))
				for x in service_list:
					services.append(x[0])
				provider_name_for_titles = self.iptv_service_provider
				name_case_config = config.plugins.m3uiptv.bouquet_names_case.value
				if name_case_config == 1:
					provider_name_for_titles = provider_name_for_titles.lower()
				elif name_case_config == 2:
					provider_name_for_titles = provider_name_for_titles.upper()
				db.addOrUpdateBouquet(provider_name_for_titles + " - " + groupItem[0], bfilename, services, False)
		self.writeExampleBlacklist(examples)
		self.piconsDownload()
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
		for x in self.onProgressChanged:
			x()

	def getVoDSeries(self):
		self.vod_series = {}
		url = "%s/player_api.php?username=%s&password=%s&action=get_series" % (self.url, self.username, self.password)
		dest_file = USER_IPTV_VOD_SERIES_FILE % self.scheme
		json_string = self.getUrlToFile(url, dest_file)
		self.makeVodSeriesDictFromJson(json_string)

	def getMovieById(self, movie_id):
		ret = {}
		url = "%s/player_api.php?username=%s&password=%s&action=get_vod_info&vod_id=%s" % (self.url, self.username, self.password, movie_id)
		file = path.join(self.getTempDir(), "m_" + str(movie_id))
		json_string = self.loadFromFile(file) or self.getUrlToFile(url, file)
		if json_string:
			movie_info = json.loads(json_string)
			info = movie_info.get("info")
			ret["plot"] = info.get("plot")
		return ret

	def getSeriesById(self, series_id):
		ret = []
		titles = []  # this is a temporary hack to avoid duplicates when there are multiple container extensions
		file = path.join(self.getTempDir(), series_id)
		url = "%s/player_api.php?username=%s&password=%s&action=get_series_info&series_id=%s" % (self.url, self.username, self.password, series_id)
		json_string = self.loadFromFile(file) or self.getUrlToFile(url, file)
		if json_string:
			series = json.loads(json_string)
			episodes = series.get("episodes")
			main_info = series.get("info")
			if episodes:
				for season in episodes:
					iter = episodes[season] if isinstance(episodes, dict) else season  # this workaround is because there are multiple json formats for series
					for episode in iter:
						id = episode.get("id") and str(episode["id"])
						title = episode.get("title") and str(episode["title"])
						info = episode.get("info")
						season_num = episode.get("season")
						print("getSeriesById info", info)
						marker = []
						if info and info.get("season"):
							season_num = info.get("season")
							marker.append(_("S%s") % str(season_num))
						elif season_num:
							marker.append(_("S%s") % str(season_num))
						episode_num = episode.get("episode_num") and episode["episode_num"]
						episode_image = episode.get("movie_image") and episode["movie_image"]
						if episode_num:
							marker.append(_("Ep%s") % str(episode_num))
						if marker:
							marker = ["[%s]" % " ".join(marker)]
						if info and (duration := info.get("duration")):
							marker.insert(0, _("Duration: %s") % str(duration))
						elif main_info and (duration := main_info.get("episode_run_time")):
							marker.insert(0, _("Duration: %s") % str(duration))
						if info and (date := info.get("release_date") or info.get("releasedate") or info.get("air_date")):
							if date[:4].isdigit():
								date = date[:4]
							marker.insert(0, _("Released: %s") % str(date))
						elif main_info and (date := main_info.get("releaseDate") or main_info.get("releasedate") or main_info.get("air_date")):
							if date[:4].isdigit():
								date = date[:4]
							marker.insert(0, _("Released: %s") % str(date))
						ext = episode.get("container_extension")
						episode_url = "%s/series/%s/%s/%s.%s" % (self.url, self.username, self.password, id, ext)
						se_num = f"S{season_num:02d}E{episode_num:02d}"
						title = title.replace(se_num, "").replace("." + ext, "")
						title = f"{se_num} - {title}"
						if title and (info or main_info) and title not in titles:
							ret.append((episode_url, title, info or main_info, self, ", ".join(marker), id.split(":")[0], episode_image))
							titles.append(title)
		return ret

	def getProviderInfo(self):
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
					print("[XtreemProvider] getProviderInfo, an error occured", err)

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

	def getSeriesCategories(self):
		url = "%s/player_api.php?username=%s&password=%s&action=get_series_categories" % (self.url, self.username, self.password)
		dest_file = USER_IPTV_SERIES_CATEGORIES_FILE % self.scheme
		json_string = self.getUrlToFile(url, dest_file)
		self.makeSeriesCategoriesDictFromJson(json_string)
