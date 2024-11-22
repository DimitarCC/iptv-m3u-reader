from enigma import eDVBDB
from twisted.internet import threads
import requests
import time
from .IPTVProcessor import IPTVProcessor
from .Variables import USER_IPTV_VOD_MOVIES_FILE, USER_AGENT, CATCHUP_STALKER, CATCHUP_STALKER_TEXT

db = eDVBDB.getInstance()


class Channel():
	def __init__(self, id, name, cmd, catchup_days):
		self.id = id
		self.name = name
		self.cmd = cmd
		self.catchup_days = catchup_days


class StalkerProvider(IPTVProcessor):
	def __init__(self):
		IPTVProcessor.__init__(self)
		self.type = "Stalker"
		self.refresh_interval = -1
		self.vod_movies = []
		self.progress_percentage = -1
		self.create_epg = False
		self.catchup_type = CATCHUP_STALKER
		self.play_system_vod = "4097"
		self.play_system_catchup = "4097"

	def storePlaylistAndGenBouquet(self):
		self.checkForNetwrok()
		session = requests.Session()
		token = self.get_token(session)
		if token:
			genres = self.get_genres(session, token)
			# print("GETTING CHANNELS FOR GENRE %s/%s" % (genres[0]["genre_id"], genres[0]["name"]))
			threads.deferToThread(self.get_channels, session, token, genres).addCallback(self.channels_callback)

	def channels_callback(self, groups):
		tsid = 1000
		for group in groups.values():
			services = []
			for service in group[1]:
				surl = service.cmd
				catchup_days = service.catchup_days
				if catchup_days:
					surl = self.constructCatchupSufix(str(catchup_days), surl, CATCHUP_STALKER_TEXT)
				ch_name = service.name.replace(":", "|")
				stype = "1"
				if ("UHD" in ch_name or "4K" in ch_name) and " HD" not in ch_name:
					stype = "1F"
				elif "HD" in ch_name:
					stype = "19"
				sref = self.generateChannelReference(stype, tsid, surl.replace(":", "%3a"), ch_name)
				tsid += 1
				services.append(sref)

			bfilename = self.cleanFilename(f"userbouquet.m3uiptv.{self.scheme}.{group[0]}.tv")
			db.addOrUpdateBouquet(self.iptv_service_provider.upper() + " - " + group[0], bfilename, services, False)

		if not self.ignore_vod:
			self.getVoDMovies()

		self.bouquetCreated(None)

	def get_token(self, session):
		try:
			url = f"{self.url}/portal.php?type=stb&action=handshake&JsHttpRequest=1-xml"
			cookies = {"mac": self.mac, "stb_lang": "en", "timezone": "Europe/London"}
			headers = {"User-Agent": USER_AGENT}
			response = session.get(url, cookies=cookies, headers=headers)
			token = response.json()["js"]["token"]
			if token:
				return token
		except Exception as ex:
			print("[M3UIPTV] [Stalker] Error getting token: " + str(ex))
			pass

	def get_genres(self, session, token):
		try:
			url = f"{self.url}/portal.php?type=itv&action=get_genres&JsHttpRequest=1-xml"
			cookies = {"mac": self.mac, "stb_lang": "en", "timezone": "Europe/London"}
			headers = {"User-Agent": USER_AGENT, "Authorization": "Bearer " + token}
			response = session.get(url, cookies=cookies, headers=headers)
			genre_data = response.json()["js"]
			if genre_data:
				genres = []
				for i in genre_data:
					gid = i["id"]
					name = i["title"]
					genres.append({'name': name, 'category_type': 'IPTV', 'genre_id': gid})
				return genres
		except Exception as ex:
			print("[M3UIPTV] [Stalker] Error getting genres: " + str(ex))
			pass

	def get_channels_for_group(self, services, session, cookies, headers, genre_id):
		page_number = 1
		while True:
			time.sleep(0.05)
			url = f"{self.url}/portal.php?type=itv&action=get_ordered_list&genre={genre_id}&fav=0&p={page_number}&JsHttpRequest=1-xml&from_ch_id=0"
			try:
				response = session.get(url, cookies=cookies, headers=headers)
			except:
				time.sleep(3)
				response = session.get(url, cookies=cookies, headers=headers)
			if response.status_code != 200:
				time.sleep(3)
				response = session.get(url, cookies=cookies, headers=headers)

			if response.status_code == 200:
				# print("[M3UIPTV] GETTING CHANNELS FOR PAGE %d" % page_number)
				try:
					response_json = response.json()
					channels_data = response_json["js"]["data"]

					for channel in channels_data:
						surl = channel["cmd"].replace("ffmpeg ", "")
						if self.play_system != "1":
							surl = surl.replace("extension=ts", "extension=m3u8")
						services.append(Channel(channel["id"], channel["name"], channel["cmd"].replace("ffmpeg ", ""), channel["tv_archive_duration"]))
					total_items = response_json["js"]["total_items"]
					if len(services) >= total_items:
						break
					page_number += 1
				except ValueError:
					print("[M3UIPTV] [Stalker] Invalid JSON format in response")
			else:
				print(f"[M3UIPTV] [Stalker] IPTV Request failed for page {page_number}")

	def get_channels(self, session, token, genres):
		groups = {}
		try:
			for group in genres:
				groups[group["genre_id"]] = (group["name"], [])

			cookies = {"mac": self.mac, "stb_lang": "en", "timezone": "Europe/London"}
			headers = {"User-Agent": USER_AGENT, "Authorization": "Bearer " + token}
			i = 0
			for group in genres:
				genre_id = group["genre_id"]
				if genre_id != "*":
					self.get_channels_for_group(groups[genre_id][1], session, cookies, headers, genre_id)
					# print("[M3UIPTV] [Stalker] GENERATE CHANNELS FOR GROUP %d/%d" % (i, len(genres)))
					self.progress_percentage = int((i / len(genres)) * 100)
				i += 1

			self.progress_percentage = -1
			return groups
		except Exception as ex:
			print("[M3UIPTV] [Stalker] Error getting channels: " + str(ex))
			self.bouquetCreated(ex)
			pass

# 	def getVoDMovies(self):
# 		self.vod_movies = []
# 		url = "%s/player_api.php?username=%s&password=%s&action=get_vod_streams" % (self.url, self.username, self.password)
# 		dest_file = USER_IPTV_VOD_MOVIES_FILE % self.scheme
# 		json_string = self.getUrlToFile(url, dest_file)
# 		self.makeVodListFromJson(json_string)

	def loadVoDMoviesFromFile(self):
		self.vod_movies = []
		vodFile = USER_IPTV_VOD_MOVIES_FILE % self.scheme
		json_string = self.loadFromFile(vodFile)
		self.makeVodListFromJson(json_string)
