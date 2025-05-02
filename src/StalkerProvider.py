from . import _

from enigma import eDVBDB, eServiceReference
from ServiceReference import ServiceReference
from Components.config import config
from xml.dom import minidom
import requests, time, re, math, json
from zoneinfo import ZoneInfo
from datetime import datetime, timezone
from twisted.internet import threads
from .IPTVProcessor import IPTVProcessor
from .VoDItem import VoDItem
from .Variables import USER_IPTV_VOD_MOVIES_FILE, REQUEST_USER_AGENT, USER_AGENTS, CATCHUP_STALKER, CATCHUP_STALKER_TEXT, USER_IPTV_MOVIE_CATEGORIES_FILE, USER_IPTV_VOD_MOVIES_FILE, USER_IPTV_VOD_SERIES_FILE, USER_IPTV_SERIES_CATEGORIES_FILE

db = eDVBDB.getInstance()


class Channel():
	def __init__(self, id, number, name, cmd, catchup_days, picon, xmltv_id):
		self.id = id
		self.number = number
		self.name = name.replace(":", "|").replace("  ", " ").strip()
		self.cmd = cmd
		self.catchup_days = catchup_days
		self.picon = picon
		self.xmltv_id = xmltv_id
		self.sref = ""


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
		self.session = requests.Session()
		self.token = None
		self.portal_entry_point_type = 0
		self.v_movies = []
		self.v_series = []

	def getPortalUrl(self):
		url = self.url.removesuffix("/")
		if self.portal_entry_point_type == 0:
			if url.endswith("/c"):
				url = url.removesuffix("/c") + "/server"
			elif "/server" not in url:
				url = url + "/server"
			url = url + "/load.php"
		elif self.portal_entry_point_type == 1:
			url = url + "/portal.php"

		print("[M3UIPTV][Stalker] Portal URL: " + url)
		return url

	def getEpgUrl(self):
		return self.custom_xmltv_url if self.is_custom_xmltv and self.custom_xmltv_url else "http://localhost:9010/StalkerEPG?p=%s" % self.scheme

	def createChannelsFile(self, epghelper, groups):
		epghelper.createStalkerChannelsFile(groups)

	def generateXMLTVFile(self): # Use this for the timer for regenerate of EPG xml
		if self.create_epg and not self.custom_xmltv_url:
			self.checkForNetwrok()
			session = requests.Session()
			token = self.get_token(session)
			if token:
				genres = self.get_genres(session, token)
				groups = self.get_all_channels(session, token, genres)
				channels = [
					x
					for xs in groups.values()
					for x in xs[1]
				]
				channel_dict = {}
				for x in channels:
					channel_dict[x.id] = x

				try:
					url = f"{self.getPortalUrl()}?type=itv&action=get_epg_info&period=7&JsHttpRequest=1-xml"
					cookies = {"mac": self.mac, "stb_lang": "en", "timezone": "Europe/London"}
					headers = {"User-Agent": REQUEST_USER_AGENT, "Authorization": "Bearer " + token}
					response = session.get(url, cookies=cookies, headers=headers)
					epg_data = response.json()["js"]["data"]
					if epg_data:
						doc = minidom.Document()
						base = doc.createElement('tv')
						base.setAttribute("generator-info-name", "M3UIPTV Plugin")
						base.setAttribute("generator-info-url", "http://www.xmltv.org/")
						doc.appendChild(base)
						for c in epg_data:
							if not str(c) in channel_dict.keys():
								continue
						
							channel = channel_dict[str(c)]
							name = channel.name
							
							c_entry = doc.createElement('channel')
							c_entry.setAttribute("id", str(c))
							base.appendChild(c_entry)
							
							
							dn_entry = doc.createElement('display-name')
							dn_entry_content = doc.createTextNode(name)
							dn_entry.appendChild(dn_entry_content)
							c_entry.appendChild(dn_entry)

						for k,v in epg_data.items():
							channel = None
							
							if str(k) in channel_dict.keys():
								channel = channel_dict[str(k)]
							
							for epg in v:
								start_time 	= datetime.fromtimestamp(float(epg['start_timestamp']))
								stop_time	= datetime.fromtimestamp(float(epg['stop_timestamp']))
								
								pg_entry = doc.createElement('programme')
								format_string = f"%Y%m%d%H%M%S {self.server_timezone_offset}"
								pg_entry.setAttribute("start", start_time.strftime(format_string))
								pg_entry.setAttribute("stop", stop_time.strftime(format_string))
								pg_entry.setAttribute("channel", str(k))
								base.appendChild(pg_entry)
								
								t_entry = doc.createElement('title')
								t_entry.setAttribute("lang", "en")
								t_entry_content = doc.createTextNode(epg['name'])
								t_entry.appendChild(t_entry_content)
								pg_entry.appendChild(t_entry)
								
								d_entry = doc.createElement('desc')
								d_entry.setAttribute("lang", "en")
								d_entry_content = doc.createTextNode(epg['descr'])
								d_entry.appendChild(d_entry_content)
								pg_entry.appendChild(d_entry)
							
								if epg_category := epg['category']:
									c_entry = doc.createElement('category')
									c_entry.setAttribute("lang", "en")
									c_entry_content = doc.createTextNode(epg_category)
									c_entry.appendChild(c_entry_content)
									pg_entry.appendChild(c_entry)
						return doc.toxml(encoding='utf-8')
				except Exception as ex:
					print("[M3UIPTV][Stalker] Error getting epg info: " + str(ex))
					return None
		return None

	def storePlaylistAndGenBouquet(self):
		self.checkForNetwrok()
		self.token = self.get_token(self.session)
		if self.token:
			self.get_server_timezone_offset(self.session, self.token)
			genres = self.get_genres(self.session, self.token)
			groups = self.get_all_channels(self.session, self.token, genres)
			self.channels_callback(groups)
			self.piconsDownload()
			self.generateEPGImportFiles(groups)
			self.generateMediaLibrary()
			
	def generateMediaLibrary(self):
		if not self.ignore_vod:
			vod_categories = self.getVODCategories(self.session, self.token)
			for category in vod_categories:
				self.movie_categories[category["category_id"]] = category["category_name"]
			series_categories = self.getSeriesCategories(self.session, self.token)
			for category in series_categories:
				self.series_categories[category["category_id"]] = category["category_name"]
			threads.deferToThread(self.get_vod).addCallback(self.store_vod)


	def channels_callback(self, groups):
		tsid = 1000
		blacklist = self.readBlacklist()
		for group in groups.values():
			services = []
			service_list = group[1]
			if self.ch_order_strategy > 0:
				if self.ch_order_strategy == 1:
					service_list.sort(key=lambda x: int(x.number or "0"))
				else:
					service_list.sort(key=lambda x: x.name)
			for service in service_list:
				surl = service.cmd
				if self.use_provider_tsid:
					tsid = int(service.id)
				catchup_days = service.catchup_days
				if catchup_days:
					surl = self.constructCatchupSuffix(str(catchup_days), surl, CATCHUP_STALKER_TEXT)
				ch_name = service.name
				stype = "1"
				if ("UHD" in ch_name or "4K" in ch_name) and " HD" not in ch_name:
					stype = "1F"
				elif "HD" in ch_name:
					stype = "19"
				sref = self.generateChannelReference(stype, tsid, surl.replace(":", "%3a"), ch_name)
				if not self.use_provider_tsid:
					tsid += 1
				if stream_icon := service.picon:
					if self.picon_gen_strategy == 0:
						self.piconsAdd(stream_icon, ch_name)
					else:
						self.piconsSrefAdd(stream_icon, sref)
				services.append(sref)
				service.sref = sref

			if len(services) > 0:
				bfilename = self.cleanFilename(f"userbouquet.m3uiptv.{self.scheme}.{group[0]}.tv")
				if group[0] in blacklist:
					self.removeBouquet(bfilename)  # remove blacklisted bouquet if already exists
					continue
				provider_name_for_titles = self.iptv_service_provider
				name_case_config = config.plugins.m3uiptv.bouquet_names_case.value
				if name_case_config == 1:
					provider_name_for_titles = provider_name_for_titles.lower()
				elif name_case_config == 2:
					provider_name_for_titles = provider_name_for_titles.upper()
				db.addOrUpdateBouquet(provider_name_for_titles + " - " + group[0], bfilename, services, False)

		if not self.ignore_vod:
			self.getVoDMovies()

		self.bouquetCreated(None)

	def get_token(self, session):
		try:
			url = f"{self.getPortalUrl()}?type=stb&action=handshake&JsHttpRequest=1-xml"
			cookies = {"mac": self.mac, "stb_lang": "en", "timezone": "Europe/London"}
			headers = {"User-Agent": REQUEST_USER_AGENT}
			response = session.get(url, cookies=cookies, headers=headers)
			if response.status_code == 404:
				self.portal_entry_point_type = 1
				from .plugin import writeProviders  # deferred import
				writeProviders()  # save to config so it doesn't get lost on reboot
			url = f"{self.getPortalUrl()}?type=stb&action=handshake&JsHttpRequest=1-xml"
			response = session.get(url, cookies=cookies, headers=headers)
			token = response.json()["js"]["token"]
			if token:
				return token
		except Exception as ex:
			print("[M3UIPTV][Stalker] Error getting token: " + str(ex))
			pass

	def get_genres(self, session, token):
		try:
			url = f"{self.getPortalUrl()}?type=itv&action=get_genres&JsHttpRequest=1-xml"
			cookies = {"mac": self.mac, "stb_lang": "en", "timezone": "Europe/London"}
			headers = {"User-Agent": REQUEST_USER_AGENT, "Authorization": "Bearer " + token}
			response = session.get(url, cookies=cookies, headers=headers)
			genre_data = response.json()["js"]
			if genre_data:
				genres = []
				examples = []
				genres.append({'name': _("All channels"), 'category_type': 'IPTV', 'genre_id': "ALL_CHANNELS"})
				genres.append({'name': _("UNCATEGORIZED"), 'category_type': 'IPTV', 'genre_id': "EMPTY"})
				examples.append(_("UNCATEGORIZED"))
				for i in genre_data:
					gid = i["id"]
					if isinstance(gid, int):
						gid = str(gid)
					name = i["title"]
					genres.append({'name': name, 'category_type': 'IPTV', 'genre_id': gid})
					if gid != "*":
						examples.append(name)
				self.writeExampleBlacklist(examples)
				return genres
		except Exception as ex:
			print("[M3UIPTV][Stalker] Error getting genres: " + str(ex))
			pass

	def getVODCategories(self, session, token):
		try:
			url = f"{self.getPortalUrl()}?type=vod&action=get_categories&JsHttpRequest=1-xml"
			cookies = {"mac": self.mac, "stb_lang": "en", "timezone": "Europe/London"}
			headers = {"User-Agent": REQUEST_USER_AGENT, "Authorization": "Bearer " + token}
			response = session.get(url, cookies=cookies, headers=headers)
			genre_data = response.json()["js"]
			if genre_data:
				genres = []
				for i in genre_data:
					gid = i["id"]
					if isinstance(gid, int):
						gid = str(gid)
					name = i["title"]
					genres.append({'category_name': name, 'category_type': 'VOD', 'category_id': gid})
				dest_file = USER_IPTV_MOVIE_CATEGORIES_FILE % self.scheme
				return self.getDataToFile(genres, dest_file)
		except Exception as ex:
			print("[M3UIPTV][Stalker] Error getting vod genres: " + str(ex))
			pass

	def getSeriesCategories(self, session, token):
		try:
			url = f"{self.getPortalUrl()}?type=series&action=get_categories&JsHttpRequest=1-xml"
			cookies = {"mac": self.mac, "stb_lang": "en", "timezone": "Europe/London"}
			headers = {"User-Agent": REQUEST_USER_AGENT, "Authorization": "Bearer " + token}
			response = session.get(url, cookies=cookies, headers=headers)
			genre_data = response.json()["js"]
			if genre_data:
				genres = []
				for i in genre_data:
					gid = i["id"]
					if isinstance(gid, int):
						gid = str(gid)
					name = i["title"]
					genres.append({'category_name': name, 'category_type': 'SERIES', 'category_id': gid})
				dest_file = USER_IPTV_SERIES_CATEGORIES_FILE % self.scheme
				return self.getDataToFile(genres, dest_file)
		except Exception as ex:
			print("[M3UIPTV][Stalker] Error getting series genres: " + str(ex))
			pass

	def get_server_timezone_offset(self, session, token):
		try:
			url = f"{self.getPortalUrl()}?type=stb&action=get_profile&JsHttpRequest=1-xml"
			cookies = {"mac": self.mac, "stb_lang": "en", "timezone": "Europe/London"}
			headers = {"User-Agent": REQUEST_USER_AGENT, "Authorization": "Bearer " + token}
			response = session.get(url, cookies=cookies, headers=headers)
			profile_data = response.json()["js"]
			if profile_data:
				zone = ZoneInfo(profile_data["default_timezone"])
				server_timezone_offset = (datetime.now(timezone.utc).astimezone().utcoffset().total_seconds() - zone.utcoffset(datetime.now()).total_seconds())//3600
				server_timezone_offset_string = f"{server_timezone_offset :+03.0f}00"
				if server_timezone_offset_string != self.server_timezone_offset:
					self.server_timezone_offset = server_timezone_offset_string
					self.epg_time_offset = int(server_timezone_offset)
					from .plugin import writeProviders  # deferred import
					writeProviders()  # save to config so it doesn't get lost on reboot
		except Exception as ex:
			print("[M3UIPTV][Stalker] Error getting default timezone: " + str(ex))
			pass

	def get_channels_for_group(self, groups, services, session, cookies, headers, genre_id):
		page_number = 1
		blacklist = self.readBlacklist()
		total_services_count = 0
		while True:
			time.sleep(0.05)
			url = f"{self.getPortalUrl()}?type=itv&action=get_ordered_list&genre={genre_id}&fav=0&p={page_number}&JsHttpRequest=1-xml&from_ch_id=0"
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
						surl = f"{self.scheme}%3a//{channel['id']}?cmd={channel['cmd'].replace('ffmpeg ', '').replace('&','|amp|').replace(':', '%3a')}"
						if self.create_bouquets_strategy > 0:  # config option here: for user-optional, all-channels bouquet
							if genre_id not in groups or groups[genre_id][0] not in blacklist:
								groups["ALL_CHANNELS"][1].append(Channel(channel["id"], channel["number"], channel["name"], surl, channel["tv_archive_duration"], channel["logo"], channel["xmltv_id"]))
						if self.create_bouquets_strategy != 1:  # config option here: for sections bouquets
							services.append(Channel(channel["id"], channel["number"], channel["name"], surl, channel["tv_archive_duration"], channel["logo"], channel["xmltv_id"]))
						total_services_count += 1

					total_items = response_json["js"]["total_items"]
					if total_services_count >= total_items:
						break
					page_number += 1
				except ValueError:
					print("[M3UIPTV][Stalker] Invalid JSON format in response")
			else:
				print(f"[M3UIPTV][Stalker] IPTV Request failed for page {page_number}")
	
	def get_all_channels(self, session, token, genres):
		groups = {} 
		censored_groups = []
		blacklist = self.readBlacklist()
		for group in genres:
			groups[group["genre_id"]] = (group["name"], [])
			censored = False
			try:
				censored = group["censored"] == "1"
			except:
				pass
			if "adult" in group["name"].lower() or "sex" in group["name"].lower() or "xxx" in group["name"].lower() or censored:
				censored_groups.append(group["genre_id"])

		cookies = {"mac": self.mac, "stb_lang": "en", "timezone": "Europe/London"}
		headers = {"User-Agent": REQUEST_USER_AGENT, "Authorization": "Bearer " + token}
		url = f"{self.getPortalUrl()}?type=itv&action=get_all_channels&JsHttpRequest=1-xml"
		response = session.get(url, cookies=cookies, headers=headers)
		channel_data = response.json()["js"]['data']
		for channel in channel_data:
			surl = f"{self.scheme}%3a//{channel['id']}?cmd={channel['cmd'].replace('ffmpeg ', '').replace('&','|amp|').replace(':', '%3a')}"
			if self.output_format == "ts":
				surl = surl.replace("extension=m3u8", "extension=ts")
			elif self.output_format == "m3u8":
				surl = surl.replace("extension=ts", "extension=m3u8")
			if genre_id := channel["tv_genre_id"]:
				if isinstance(genre_id, int):
					genre_id = str(genre_id)
				category_id = genre_id
				if self.create_bouquets_strategy > 0:  # config option here: for user-optional, all-channels bouquet
					if category_id not in groups or groups[category_id][0] not in blacklist:
						groups["ALL_CHANNELS"][1].append(Channel(channel["id"], channel["number"], channel["name"], surl, channel["tv_archive_duration"], channel["logo"], channel["xmltv_id"]))

				if self.create_bouquets_strategy != 1:  # config option here: for sections bouquets
					groups[category_id if category_id and category_id in groups else "EMPTY"][1].append(Channel(channel["id"], channel["number"], channel["name"], surl, channel["tv_archive_duration"], channel["logo"], channel["xmltv_id"]))
		
		for censored_group in censored_groups:
			self.get_channels_for_group(groups, groups[censored_group][1], session, cookies, headers, censored_group)

		return groups
	
	def get_stream_play_url(self, cmd, session, token):
		cookies = {"mac": self.mac, "stb_lang": "en", "timezone": "Europe/London"}
		headers = {"User-Agent": REQUEST_USER_AGENT, "Authorization": "Bearer " + token}
		url = f"{self.getPortalUrl()}?type=itv&action=create_link&cmd={cmd}&series=&forced_storage=undefined&disable_ad=0&download=0&JsHttpRequest=1-xml"
		response = session.get(url, cookies=cookies, headers=headers)
		try:
			stream_data = response.json()["js"]
			return stream_data["cmd"], True
		except: # probably token has expired
			return cmd, False
	
	def getVoDPlayUrl(self, url, series=0):
		if ("http://" in url or "https://" in url) and "localhost" not in url:
			return url.replace("ffmpeg ", "")
		if not self.token:
			self.token = self.get_token(self.session)
		cookies = {"mac": self.mac, "stb_lang": "en", "timezone": "Europe/London"}
		headers = {"User-Agent": REQUEST_USER_AGENT, "Authorization": "Bearer " + self.token}
		url = f"{self.getPortalUrl()}?type=vod&action=create_link&cmd={url.replace('ffmpeg ', '')}&JsHttpRequest=1-xml&series={str(series)}"
		response = self.session.get(url, cookies=cookies, headers=headers)
		try:
			stream_data = response.json()["js"]
			return stream_data["cmd"].replace("ffmpeg ", "")
		except: # probably token has expired
			self.token = self.get_token(self.session)
			headers = {"User-Agent": REQUEST_USER_AGENT, "Authorization": "Bearer " + self.token}
			response = self.session.get(url, cookies=cookies, headers=headers)
			try:
				stream_data = response.json()["js"]
				return stream_data["cmd"].replace("ffmpeg ", "")
			except:
				pass
			return url.replace("ffmpeg ", "")

	def processService(self, nref, iptvinfodata, callback=None, event=None):
		cmd = ""
		splittedRef = nref.toString().split(":")
		sRef = nref and ServiceReference(nref.toString())
		orig_name = sRef and sRef.getServiceName()
		origRef = ":".join(splittedRef[:10])
		nnref = nref
		match = re.search(r"(?:cmd=)([^&]+)", iptvinfodata)
		if match:
			cmd = match.group(1)

		match = re.search(r"catchupdays=(\d+)", iptvinfodata)
		catchup_days = ""
		if match:
			catchup_days = match.group(1)
	
		if "localhost/ch" not in cmd:
			surl = cmd.replace(":", "%3a").replace("|amp|", "&")
			surl = self.constructCatchupSuffix(catchup_days, surl, CATCHUP_STALKER_TEXT)
			nref_new = origRef + ":" + surl + ":" + orig_name + "•" + self.iptv_service_provider
			nnref = eServiceReference(nref_new)
			self.isPlayBackup = False
			if callback:
				callback(nnref)
			return nnref, nref, False
		self.checkForNetwrok()
		if not self.token:
			self.token = self.get_token(self.session)
		if self.token:
			iptv_url, token_valid = self.get_stream_play_url(cmd.replace("%3a", ":").replace("|amp|", "&"), self.session, self.token)
			if not token_valid:
				self.token = self.get_token(self.session)
				iptv_url, token_valid = self.get_stream_play_url(cmd.replace("%3a", ":").replace("|amp|", "&"), self.session, self.token)
			if catchup_days:
				iptv_url = self.constructCatchupSuffix(catchup_days, iptv_url, CATCHUP_STALKER_TEXT)

			if self.output_format == "ts":
				iptv_url = iptv_url.replace("extension=m3u8", "extension=ts")
			elif self.output_format == "m3u8":
				iptv_url = iptv_url.replace("extension=ts", "extension=m3u8")
			nref_new = "%s:%s%s:%s•%s" % (origRef, iptv_url.replace(":", "%3a").replace("ffmpeg ", ""), "" if self.custom_user_agent == "off" else ("#User-Agent=" + USER_AGENTS[self.custom_user_agent]), orig_name, self.iptv_service_provider)
			nref_new = origRef + ":" + iptv_url.replace(":", "%3a").replace("ffmpeg ", "") + ":" + orig_name + "•" + self.iptv_service_provider
			nnref = eServiceReference(nref_new)
			try: #type2 distros support
				nnref.setCompareSref(nref.toString())
			except:
				pass
			self.isPlayBackup = False
		if callback:
			callback(nnref)
		return nnref, nref, False
	
	def get_vod(self):
		if not self.token:
			self.token = self.get_token(self.session)
		cookies = {"mac": self.mac, "stb_lang": "en", "timezone": "Europe/London"}
		headers = {"User-Agent": REQUEST_USER_AGENT, "Authorization": "Bearer " + self.token}
		page_number = 1
		total_pages = 0
		total_pages_series = 0
		self.progress_percentage = 0
		movies = []
		series = []
		while True:
			time.sleep(0.05)
			url = f"{self.getPortalUrl()}?type=vod&action=get_ordered_list&p={page_number}&JsHttpRequest=1-xml"
			try:
				response = self.session.get(url, cookies=cookies, headers=headers)
			except:
				time.sleep(2)
				response = self.session.get(url, cookies=cookies, headers=headers)
			if response.status_code != 200:
				time.sleep(2)
				response = self.session.get(url, cookies=cookies, headers=headers)

			try:
				url_series = f"{self.getPortalUrl()}?type=series&action=get_ordered_list&p=1&JsHttpRequest=1-xml"
				response_series = self.session.get(url_series, cookies=cookies, headers=headers)
				if response_series.status_code == 200:
					response_series_json = response_series.json()
					total_items_series = response_series_json["js"]["total_items"]
					max_page_items_series = response_series_json["js"]["max_page_items"]
					total_pages_series = math.ceil(total_items_series / max_page_items_series)
			except:
				pass

			if response.status_code == 200:
				# print("[M3UIPTV] GETTING CHANNELS FOR PAGE %d" % page_number)
				try:
					response_json = response.json()
					vods_data = response_json["js"]["data"]
					for vod in vods_data:
						item = {}
						item["num"] = vod["id"]
						item["name"] = vod["name"]
						item["stream_type"] = "movie" if vod["is_movie"] == 1 else "series"
						item["stream_id"] = vod["id"]
						item["stream_icon"] = vod["screenshot_uri"]
						item["cover"] = vod["screenshot_uri"]
						item["rating"] = vod["rating_imdb"] if "rating_imdb" in vod else vod["rating_kinopoisk"]
						item["added"] = vod["added"]
						item["is_adult"] = vod["censored"]
						item["category_id"] = vod["category_id"]
						item["hd"] = vod["hd"]
						item["tmdb_id"] = vod["tmdb_id"]
						item["plot"] = vod["description"]
						item["director"] = vod["director"]
						item["actors"] = vod["actors"]
						item["year"] = vod["year"]
						item["genres_str"] = vod["genres_str"]
						item["play_url"] = vod["cmd"]
						movies.append(item)
					if total_pages == 0:
						total_items = response_json["js"]["total_items"]
						max_page_items = response_json["js"]["max_page_items"]
						total_pages = math.ceil(total_items / max_page_items)
					self.progress_percentage = int((page_number / (total_pages + total_pages_series)) * 100)
					for x in self.onProgressChanged:
						x()
					#print("[M3UIPTV][Stalker][VOD] progress %d / Page Number: %d / Total Pages: %d" % (self.progress_percentage, page_number, total_pages))
					page_number += 1
					if page_number >= total_pages:
						break
				except ValueError:
					print("[M3UIPTV][Stalker] Invalid JSON format in response")
			else:
				print(f"[M3UIPTV][Stalker] IPTV Request failed for page {page_number}")

		# Series retrival
		page_number = 1
		while True:
			time.sleep(0.05)
			url = f"{self.getPortalUrl()}?type=series&action=get_ordered_list&p={page_number}&JsHttpRequest=1-xml"
			try:
				response = self.session.get(url, cookies=cookies, headers=headers)
			except:
				time.sleep(2)
				response = self.session.get(url, cookies=cookies, headers=headers)
			if response.status_code != 200:
				time.sleep(2)
				response = self.session.get(url, cookies=cookies, headers=headers)

			if response.status_code == 200:
				# print("[M3UIPTV] GETTING CHANNELS FOR PAGE %d" % page_number)
				try:
					response_json = response.json()
					vods_data = response_json["js"]["data"]
					for vod in vods_data:
						item = {}
						item["num"] = vod["id"]
						item["name"] = vod["name"]
						item["stream_type"] = "movie" if vod["is_movie"] == 1 else "series"
						item["series_id"] = vod["id"]
						item["stream_icon"] = vod["screenshot_uri"]
						item["rating"] = vod["rating_imdb"] if "raating_imdb" in vod else vod["rating_kinopoisk"]
						item["added"] = vod["added"]
						item["is_adult"] = vod["censored"]
						item["category_id"] = vod["category_id"]
						item["hd"] = vod["hd"]
						item["tmdb_id"] = vod["tmdb_id"]
						item["plot"] = vod["description"]
						item["director"] = vod["director"]
						item["actors"] = vod["actors"]
						item["year"] = vod["year"]
						item["genres_str"] = vod["genres_str"]
						item["play_url"] = vod["cmd"]
						series.append(item)
					total_items = response_json["js"]["total_items"]
					self.progress_percentage = int(((page_number + total_pages) / (total_pages + total_pages_series)) * 100)
					for x in self.onProgressChanged:
						x()
					#print("[M3UIPTV][Stalker][VOD] progress %d / Page Number: %d / Total Pages: %d" % (self.progress_percentage, page_number, total_pages))
					page_number += 1
					if page_number >= total_pages_series:
						break
				except ValueError:
					print("[M3UIPTV][Stalker] Invalid JSON format in response")
			else:
				print(f"[M3UIPTV][Stalker] IPTV Request failed for page {page_number}")

		self.progress_percentage = -1
		for x in self.onProgressChanged:
			x()
		return movies, series

	def store_vod(self, data):
		vod_movies, vod_series = data
		if len(vod_movies) > 0:
			dest_file_movies = USER_IPTV_VOD_MOVIES_FILE % self.scheme
			self.v_movies = self.getDataToFile(vod_movies, dest_file_movies)
		if len(vod_series) > 0:
			dest_file_series = USER_IPTV_VOD_SERIES_FILE % self.scheme
			self.v_series = self.getDataToFile(vod_series, dest_file_series)
		self.loadVoDMoviesFromFile()
		self.loadVoDSeriesFromFile()

	def makeVodListFromJson(self, json_string):
		if json_string:
			vod_json_obj = json.loads(json_string)
			for movie in vod_json_obj:
				name = movie["name"]
				#ext = movie["container_extension"]
				id = int(movie["stream_id"])
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

	def getSeriesById(self, series_id):
		if not self.token:
			self.token = self.get_token(self.session)
		cookies = {"mac": self.mac, "stb_lang": "en", "timezone": "Europe/London"}
		headers = {"User-Agent": REQUEST_USER_AGENT, "Authorization": "Bearer " + self.token}
		ret = []
		titles = []  # this is a temporary hack to avoid duplicates when there are multiple container extensions
		#file = path.join(self.getTempDir(), series_id)
		page_number = 1
		total_vod_count = 0
		while True:
			url = f"{self.getPortalUrl()}?type=series&action=get_ordered_list&p={page_number}&JsHttpRequest=1-xml&movie_id={series_id}"
			response = self.session.get(url, cookies=cookies, headers=headers)
			if response.status_code == 200:
				response_json = response.json()
				seasons_data = response_json["js"]["data"]
				for season in reversed(seasons_data):
					for episode in season["series"]:
						id = season.get("id") and str(season["id"])
						title = season.get("name") and str(season["name"]) + " - Episode " + str(episode)
						info = {}
						info["plot"] = season.get("description")
						print("getSeriesById info", info)
						marker = []
						# if info and info.get("season"):
						# 	marker.append(_("S%s") % str(info.get("season")))
						episode_num = str(episode)
						if episode_num:
							marker.append(_("Ep%s") % episode_num)
						if marker:
							marker = ["[%s]" % " ".join(marker)]
						# if info and (duration := info.get("duration")):
						# 	marker.insert(0, _("Duration: %s") % str(duration))
						# if info and (date := info.get("release_date") or info.get("releasedate") or info.get("air_date")):
						# 	if date[:4].isdigit():
						# 		date = date[:4]
						# 	marker.insert(0, _("Released: %s") % str(date))
						episode_url = f"{season['cmd']}||{str(episode)}" #self.getVoDPlayUrl(season["cmd"], episode)
						if title and info and title not in titles:
							ret.append((episode_url, title, info, self, ", ".join(marker), id.split(":")[0]))
							titles.append(title)
					total_vod_count += 1
				total_items = response_json["js"]["total_items"]
				page_number += 1
				if total_vod_count >= total_items:
					break
		return ret
