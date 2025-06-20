from . import _

from enigma import eDVBDB, eServiceReference
from ServiceReference import ServiceReference
from Components.config import config
from xml.dom import minidom
from urllib.parse import urlparse
import requests, time, re, math, json, urllib, random, hashlib, time
from zoneinfo import ZoneInfo
from datetime import datetime, timezone
from twisted.internet import threads
from .IPTVProcessor import IPTVProcessor
from .VoDItem import VoDItem
from .Variables import USER_IPTV_VOD_MOVIES_FILE, REQUEST_USER_AGENT, USER_AGENTS, CATCHUP_STALKER, CATCHUP_STALKER_TEXT, USER_IPTV_MOVIE_CATEGORIES_FILE, \
	 				   USER_IPTV_VOD_MOVIES_FILE, USER_IPTV_VOD_SERIES_FILE, USER_IPTV_SERIES_CATEGORIES_FILE, USER_IPTV_PROVIDER_INFO_FILE

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
		self.random = None
		self.portal_entry_point_type = -1
		self.v_movies = []
		self.v_series = []
		self.zone = ZoneInfo("UTC")

	# -------------------------------------------------------------------------
	# DETECT PORTAL ENTRY POINT
	# -------------------------------------------------------------------------

	def getPortalUrl(self):
		url = self.url.removesuffix("/").removesuffix("/server").removesuffix("/c").removesuffix("/stalker_portal")
		if self.portal_entry_point_type <= 0:
			url = url + "/server/load.php"
		elif self.portal_entry_point_type == 1:
			url = url + "/portal.php"
		elif self.portal_entry_point_type == 2:
			url = url + "/c/server/load.php"
		elif self.portal_entry_point_type == 3:
			url = url + "/stalker_portal/server/load.php"

		print("[M3UIPTV][Stalker] Portal URL: " + url)
		return url

	# -------------------------------------------------------------------------
	# DEFAULT VALUES AND GENERATION
	# -------------------------------------------------------------------------

	def generate_random_value(self) -> str:
		"""
        Generate a 40-character random hexadecimal string.

        Returns:
            str: Generated random value.
        """
		return ''.join(random.choices('0123456789abcdef', k=40))

	def generate_device_id(self) -> str:
		"""
        Generate a 64-character hexadecimal device ID based on the MAC address.

        Returns:
            str: Generated device ID.
        """
		mac_exact = self.mac.strip()
		sha256_hash = hashlib.sha256(mac_exact.encode()).hexdigest().upper()
		return sha256_hash

	def generate_serial(self, mac: str) -> str:
		"""
        Generate a 13-character serial based on the MD5 hash of the MAC address.

        Parameters:
            mac (str): MAC address.

        Returns:
            str: Generated serial.
        """
        # Create an MD5 hash of the MAC address
		md5_hash = hashlib.md5(mac.encode()).hexdigest()
        
        # Use the first 13 characters of the hash as the serial
		serial = md5_hash[:13].upper()  # Convert to uppercase for consistency
		return serial

	def get_host(self) -> str:
		"""
        Extract the host from the portal URL.

        Returns:
            str: Host extracted from the portal URL.
        """
		parsed_url = urlparse(self.url)
		host = parsed_url.netloc
		return host

	def generate_signature(self, serial, dev_id) -> str:
		"""
        Generate signature for profile request.

        Returns:
            str: Generated signature.
        """
		data = f"{self.mac}{serial}{dev_id}{dev_id}"
		signature = hashlib.sha256(data.encode()).hexdigest().upper()
		return signature

	def generate_metrics(self, serial) -> str:
		"""
        Generate metrics for profile request.

        Returns:
            str: JSON-formatted metrics string.
        """
		if not self.random:
			self.random = self.generate_random_value()
		metrics = {
            "mac": self.mac,
            "sn": serial,
            "type": "STB",
            "model": "MAG250",
            "uid": "",
            "random": self.random
        }
		metrics_str = json.dumps(metrics)
		return metrics_str

	def generate_headers(self):
		return { "User-Agent": REQUEST_USER_AGENT, \
				 "Authorization": "Bearer " + self.token, \
				 "Referer": self.url + "/stalker_portal/c/index.html", \
				 "X-User-Agent": "Model: MAG250; Link: WiFi", \
				 "Pragma": "no-cache", \
				 "Host": self.get_host(), \
				 "Connection": "Close" }

	def generate_cookies(self, include_token=False):
		if include_token:
			return {"mac": self.mac, "stb_lang": "en", "timezone": "Europe/London", "token": self.token}
		return {"mac": self.mac, "stb_lang": "en", "timezone": "Europe/London"}

	# -------------------------------------------------------------------------
	# PROFILE AND AUTHENTICATION
	# -------------------------------------------------------------------------

	def get_token(self, skip_profile=False):
		try:
			should_save_entry = False
			if self.portal_entry_point_type == -1:
				should_save_entry = True
			url = f"{self.getPortalUrl()}?type=stb&action=handshake&JsHttpRequest=1-xml"
			referrer = self.url + ("/stalker_portal/c/index.html" if "stalker_portal" in self.url else "/c/index.html")
			host = self.get_host()
			cookies = self.generate_cookies()
			headers = { "User-Agent": REQUEST_USER_AGENT, \
				 "Referer": referrer, \
				 "X-User-Agent": "Model: MAG250; Link: WiFi", \
				 "Pragma": "no-cache", \
				 "Host": host, \
				 "Connection": "Close" }
			response = self.session.get(url, cookies=cookies, headers=headers)
			if response.status_code == 404:
				self.portal_entry_point_type = 1
				url = f"{self.getPortalUrl()}?type=stb&action=handshake&JsHttpRequest=1-xml"
				response = self.session.get(url, cookies=cookies, headers=headers)
				if response.status_code == 404:
					self.portal_entry_point_type = 2
					url = f"{self.getPortalUrl()}?type=stb&action=handshake&JsHttpRequest=1-xml"
					response = self.session.get(url, cookies=cookies, headers=headers)
					if response.status_code == 404:
						self.portal_entry_point_type = 3
						url = f"{self.getPortalUrl()}?type=stb&action=handshake&JsHttpRequest=1-xml"
						response = self.session.get(url, cookies=cookies, headers=headers)
						if response.status_code == 404:
							self.token = ""
							self.random = ""
							return "", "" # give up since we can not find the right entry point
			elif response.status_code == 200:
				self.portal_entry_point_type = 0

			if should_save_entry:
				from .plugin import writeProviders  # deferred import
				writeProviders()  # save to config so it doesn't get lost on reboot
			token = response.json()["js"]["token"]
			random_val = response.json()["js"].get("random", {})
			if token:
				self.token = token
				self.random = random_val
				if not skip_profile:
					self.getProviderInfo(True)
				return token, random_val
		except Exception as ex:
			print("[M3UIPTV][Stalker] Error getting token: " + str(ex))
			self.token = ""
			self.random = ""
			return "", ""

	def getProviderInfo(self, from_token=False):
		"""
        Fetch user profile after ensuring a valid token.
        """
		try:
			if not from_token and not self.token:
				self.get_token()

			version = self.getPortalVersion()
			serial = self.generate_serial(self.mac)
			dev_id = self.generate_device_id()
			url = self.getPortalUrl()
			if version.strip().startswith("5.6"):
				params = {
					"type": "stb",
					"action": "get_profile",
					"hd": "1",
					"ver": (
						"ImageDescription: 0.2.18-r23-250; ImageDate: Thu Sep 13 11:31:16 EEST 2018; "
						"PORTAL version: 5.6.2; API Version: JS API version: 343; STB API version: 146; "
						"Player Engine version: 0x58c"
					),
					"num_banks": "2",
					"sn": serial,
					"stb_type": "MAG250",
					"client_type": "STB",
					"image_version": "218",
					"video_out": "hdmi",
					"device_id": dev_id,
					"device_id2": dev_id,
					"signature": self.generate_signature(serial, dev_id),
					"auth_second_step": "1",
					"hw_version": "1.7-BD-00",
					"not_valid_token": "0",
					"metrics": self.generate_metrics(serial),
					"hw_version_2": hashlib.sha1(self.mac.encode()).hexdigest(),
					"timestamp": int(time.time()),
					"api_signature": "262",
					"prehash": "",
					"JsHttpRequest": "1-xml",
				}
			else:
				params = {
					"type": "stb",
					"action": "get_profile",
					"hd": "1",
					"num_banks": "2",
					"sn": serial,
					"client_type": "STB",
					"video_out": "hdmi",
					"signature": self.generate_signature(serial, dev_id),
					"auth_second_step": "1",
					"not_valid_token": "0",
					"metrics": self.generate_metrics(serial),
					"hw_version_2": hashlib.sha1(self.mac.encode()).hexdigest(),
					"timestamp": int(time.time()),
					"api_signature": "262",
					"prehash": "",
					"JsHttpRequest": "1-xml",
				}

			json_response = self.pull_json_with_reauth(url, True, params=params, skip_profile=True)
			if not json_response:
				return

			js_data = json_response
			token = js_data.get("token", "")
			if token:
				self.token = token
				self.token_timestamp = time.time()

			if js_data:
				self.zone = ZoneInfo(js_data["default_timezone"])
				server_timezone_offset = (self.zone.utcoffset(datetime.now()).total_seconds())//3600
				
				if time.localtime().tm_isdst:
					server_timezone_offset += 1
				server_timezone_offset_string = f"{server_timezone_offset :+03.0f}00"
				if server_timezone_offset_string != self.server_timezone_offset:
					self.server_timezone_offset = server_timezone_offset_string
					self.epg_time_offset = int(server_timezone_offset)
					from .plugin import writeProviders  # deferred import
					writeProviders()  # save to config so it doesn't get lost on reboot

				url = f"{self.getPortalUrl()}?type=account_info&action=get_main_info&JsHttpRequest=1-xml"
				account_data = self.pull_json_with_reauth(url, True, skip_reauth=True)
				expiry_date = ""
				if account_data:
					expiry_date = account_data and account_data["phone"]
				info = {}
				info["user_info"] = {}
				info["user_info"]["status"] = "Active" if js_data and js_data.get("blocked") == "0" and expiry_date else "Not active"
				info["user_info"]["exp_date"] = expiry_date
				info["server_info"] = {}
				info["server_info"]["version"] = version or ""
				info["server_info"]["url"] = self.getPortalUrl()
				info["server_info"]["timezone"] = js_data and js_data["default_timezone"]

				dest_file = USER_IPTV_PROVIDER_INFO_FILE % self.scheme
				self.provider_info = self.getDataToFile(info, dest_file)
		except:
			if not from_token:
				version = self.getPortalVersion()
				info = {}
				info["user_info"] = {}
				info["user_info"]["status"] = "Not active"
				info["user_info"]["exp_date"] = ""
				info["server_info"] = {}
				info["server_info"]["version"] = version or ""
				info["server_info"]["url"] = self.getPortalUrl()
				info["server_info"]["timezone"] = ""
				dest_file = USER_IPTV_PROVIDER_INFO_FILE % self.scheme
				self.provider_info = self.getDataToFile(info, dest_file)
			else:
				pass

	# -------------------------------------------------------------------------
	# EPG HANDLING
	# -------------------------------------------------------------------------

	def getEpgUrl(self):
		return self.custom_xmltv_url if self.is_custom_xmltv and self.custom_xmltv_url else "http://localhost:9010/StalkerEPG?p=%s" % self.scheme

	def generateXMLTVFile(self): # Use this for the timer for regenerate of EPG xml
		if self.create_epg and not self.custom_xmltv_url:
			self.checkForNetwrok()
			self.get_token()
			if self.token:
				genres = self.get_genres()
				groups = self.get_all_channels(genres)
				channels = [ x for xs in groups.values() for x in xs[1]]
				channel_dict = {}
				for x in channels:
					channel_dict[x.id] = x

				try:
					url = f"{self.getPortalUrl()}?type=itv&action=get_epg_info&period=7&JsHttpRequest=1-xml"
					cookies = self.generate_cookies(True)
					headers = self.generate_headers()
					response = self.session.get(url, cookies=cookies, headers=headers)
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
								start_time 	= datetime.fromtimestamp(float(epg['start_timestamp']), self.zone)
								stop_time	= datetime.fromtimestamp(float(epg['stop_timestamp']), self.zone)
								
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
						docxml = doc.toxml(encoding='utf-8')
						return docxml
				except Exception as ex:
					print("[M3UIPTV][Stalker] Error getting epg info: " + str(ex))
					return None
		return None

	# -------------------------------------------------------------------------
	# DATA RETRIEVAL
	# -------------------------------------------------------------------------

	def pull_json_with_reauth(self, url, include_token_in_cookies, params=None, skip_profile=False, skip_reauth=False):
		try:
			json = {}
			cookies = self.generate_cookies(include_token_in_cookies)
			headers = self.generate_headers()
			if params:
				response = self.session.get(url, cookies=cookies, headers=headers, params=params)
			else:
				response = self.session.get(url, cookies=cookies, headers=headers)
			try:
				json = response.json().get("js", {})
			except: # most likely it returned empty result since not authorized/token expired
				if not skip_reauth:
					self.get_token(skip_profile)
					cookies = self.generate_cookies(True)
					headers = self.generate_headers()
					if params:
						response = self.session.get(url, cookies=cookies, headers=headers, params=params)
					else:
						response = self.session.get(url, cookies=cookies, headers=headers)
					json = response.json().get("js", {})
				else:
					pass
			return json
		except:
			return {}

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
				bouquet_name = provider_name_for_titles + " - " + group[0]
				if self.create_bouquets_strategy == 1:
					bouquet_name = provider_name_for_titles
				db.addOrUpdateBouquet(bouquet_name, bfilename, services, False)

		if not self.ignore_vod:
			self.getVoDMovies()

		self.bouquetCreated(None)

	def get_genres(self):
		try:
			url = f"{self.getPortalUrl()}?type=itv&action=get_genres&JsHttpRequest=1-xml"
			genre_data = self.pull_json_with_reauth(url, True)
			if genre_data:
				genres = []
				examples = []
				genres.append({'name': _("All channels"), 'category_type': 'IPTV', 'genre_id': "ALL_CHANNELS", 'censored': 0})
				genres.append({'name': _("UNCATEGORIZED"), 'category_type': 'IPTV', 'genre_id': "EMPTY", 'censored': 0})
				examples.append(_("UNCATEGORIZED"))
				for i in genre_data:
					gid = i["id"]
					if isinstance(gid, int):
						gid = str(gid)
					name = i["title"]
					genres.append({'name': name, 'category_type': 'IPTV', 'genre_id': gid, 'censored': i['censored']})
					if gid != "*":
						examples.append(name)
				self.writeExampleBlacklist(examples)
				return genres
		except Exception as ex:
			print("[M3UIPTV][Stalker] Error getting genres: " + str(ex))
			pass
		return []

	def getVODCategories(self) -> list:
		try:
			url = f"{self.getPortalUrl()}?type=vod&action=get_categories&JsHttpRequest=1-xml"
			genre_data = self.pull_json_with_reauth(url, True)
			if genre_data:
				genres = []
				for i in genre_data:
					gid = i["id"]
					if isinstance(gid, int):
						gid = str(gid)
					name = i["title"]
					censored = i.get("censored", 0)
					genres.append({'category_name': name, 'category_type': 'VOD', 'category_id': gid, 'censored': censored})
				dest_file = USER_IPTV_MOVIE_CATEGORIES_FILE % self.scheme
				return self.getDataToFile(genres, dest_file)
		except Exception as ex:
			print("[M3UIPTV][Stalker] Error getting vod genres: " + str(ex))
			return []

	def getSeriesCategories(self) -> list:
		try:
			url = f"{self.getPortalUrl()}?type=series&action=get_categories&JsHttpRequest=1-xml"
			genre_data = self.pull_json_with_reauth(url, True)
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
		return []

	def get_channels_for_group(self, groups, services, genre_id):
		page_number = 1
		blacklist = self.readBlacklist()
		total_services_count = 0
		while True:
			time.sleep(0.05)
			cookies = self.generate_cookies(True)
			headers = self.generate_headers()
			url = f"{self.getPortalUrl()}?type=itv&action=get_ordered_list&genre={genre_id}&fav=0&p={page_number}&JsHttpRequest=1-xml&from_ch_id=0"
			try:
				response = self.session.get(url, cookies=cookies, headers=headers)
			except:
				time.sleep(0.3)
				response = self.session.get(url, cookies=cookies, headers=headers)
			if response.status_code != 200:
				time.sleep(0.3)
				response = self.session.get(url, cookies=cookies, headers=headers)

			if response.status_code == 200:
				# print("[M3UIPTV] GETTING CHANNELS FOR PAGE %d" % page_number)
				try:
					response_json = response.json()
					channels_data = response_json["js"]["data"]
					for channel in channels_data:
						surl = f"{self.scheme}%3a//{channel['id']}?cmd={channel['cmd'].replace('ffmpeg ', '').replace('ffrt ', '').replace('&','|amp|').replace(':', '%3a')}"
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

	def get_all_channels(self, genres):
		groups = {} 
		censored_groups = []
		blacklist = self.readBlacklist()
		if not genres:
			return {}
		for group in genres:
			groups[group["genre_id"]] = (group["name"], [])
			censored = False
			try:
				censored = group["censored"] == "1"
			except:
				pass
			if "adult" in group["name"].lower() or "sex" in group["name"].lower() or "xxx" in group["name"].lower() or censored:
				censored_groups.append(group["genre_id"])

		url = f"{self.getPortalUrl()}?type=itv&action=get_all_channels&JsHttpRequest=1-xml"
		js = self.pull_json_with_reauth(url, True)
		if not js:
			return {}
		channel_data = js['data']
		for channel in channel_data:
			surl = f"{self.scheme}%3a//{channel['id']}?cmd={channel['cmd'].replace('ffmpeg ', '').replace('ffrt ', '').replace('&','|amp|').replace(':', '%3a')}"
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
			self.get_channels_for_group(groups, groups[censored_group][1], censored_group)

		return groups

	def get_stream_play_url(self, cmd):
		url = f"{self.getPortalUrl()}?type=itv&action=create_link&cmd={cmd}&series=&forced_storage=undefined&disable_ad=0&download=0&JsHttpRequest=1-xml"
		js = self.pull_json_with_reauth(url, False)
		try:
			return js["cmd"], True
		except: # probably token has expired
			self.get_token()
			js = self.pull_json_with_reauth(url, False)
			try:
				return js["cmd"], True
			except:
				return cmd, False

	def getVoDPlayUrl(self, url, series=0):
		if ("http://" in url or "https://" in url) and "localhost" not in url:
			return url.replace("ffmpeg ", "").replace("ffrt ", "")
		if not self.token:
			self.get_token()
		cookies = self.generate_cookies(True)
		headers = self.generate_headers()
		url = f"{self.getPortalUrl()}?type=vod&action=create_link&cmd={url.replace('ffmpeg ', '').replace('ffrt ', '')}&JsHttpRequest=1-xml&series={str(series)}"
		response = self.session.get(url, cookies=cookies, headers=headers)
		try:
			stream_data = response.json()["js"]
			return stream_data["cmd"].replace("ffmpeg ", "").replace("ffrt ", "")
		except: # probably token has expired
			self.get_token()
			cookies = self.generate_cookies(True)
			headers = self.generate_headers()
			response = self.session.get(url, cookies=cookies, headers=headers)
			try:
				stream_data = response.json()["js"]
				return stream_data["cmd"].replace("ffmpeg ", "").replace("ffrt ", "")
			except:
				pass
			return url.replace("ffmpeg ", "").replace("ffrt ", "")

	def get_vod(self, vod_categories):
		if not self.token:
			self.get_token()
		cookies = self.generate_cookies(True)
		headers = self.generate_headers()
		page_number = 1
		total_pages = 0
		total_pages_censored = 0
		total_pages_series = 0
		self.progress_percentage = 0
		movies = []
		series = []
		censored_groups = []
		for	group in vod_categories:
			if group["censored"] == 1:
				censored_groups.append(group)
				try:
					url_vod_censored = f"{self.getPortalUrl()}?type=vod&action=get_ordered_list&category={group['category_id']}&p=1&JsHttpRequest=1-xml"
					response_censored_json = self.pull_json_with_reauth(url_vod_censored, True)
					if response_censored_json:
						total_items_censored = response_censored_json["total_items"]
						max_page_items_censored = response_censored_json["max_page_items"]
						total_pages_censored += math.ceil(total_items_censored / max_page_items_censored)
				except:
					pass

		try:
			url_series = f"{self.getPortalUrl()}?type=series&action=get_ordered_list&p=1&JsHttpRequest=1-xml"
			series_json = self.pull_json_with_reauth(url_series, True)
			if series_json:
				total_items_series = series_json["total_items"]
				max_page_items_series = series_json["max_page_items"]
				total_pages_series = math.ceil(total_items_series / max_page_items_series)
		except:
			pass


		try:
			url_vod = f"{self.getPortalUrl()}?type=vod&action=get_ordered_list&p=1&JsHttpRequest=1-xml"
			vod_json = self.pull_json_with_reauth(url_vod, True)
			if vod_json:
				total_items_vod = vod_json["total_items"]
				max_page_items_vod = vod_json["max_page_items"]
				total_pages = math.ceil(total_items_vod / max_page_items_vod)
		except:
			pass


		page_number = 1
		for group_censored in censored_groups:
			page_number_l = 1
			total_pages_censored_l = 0
			while True:
				time.sleep(0.05)
				url = f"{self.getPortalUrl()}?type=vod&action=get_ordered_list&p={page_number}&category={group_censored['category_id']}&JsHttpRequest=1-xml"
				response_json = self.pull_json_with_reauth(url, True)
				if response_json:
					try:
						if not response_json:
							continue
						vods_data = response_json["data"]
						for vod in vods_data:
							item = {}
							item["num"] = vod.get("id")
							item["name"] = vod.get("name")
							item["stream_type"] = "movie" if vod.get("is_movie", 0) == 1 else "series"
							item["stream_id"] = vod.get("id")
							item["stream_icon"] = vod.get("screenshot_uri")
							item["cover"] = vod.get("screenshot_uri")
							item["rating"] = vod.get("rating_imdb") if "rating_imdb" in vod else vod.get("rating_kinopoisk")
							item["added"] = vod.get("added")
							item["is_adult"] = vod.get("censored")
							item["category_id"] = vod.get("category_id")
							item["hd"] = vod.get("hd", "0")
							item["tmdb_id"] = vod.get("tmdb_id", "")
							item["plot"] = vod.get("description")
							item["director"] = vod.get("director")
							item["actors"] = vod.get("actors")
							item["year"] = vod.get("year")
							item["genres_str"] = vod.get("genres_str")
							item["play_url"] = vod.get("cmd")
							movies.append(item)
						if total_pages_censored_l == 0:
							total_items = int(response_json["total_items"])
							max_page_items = int(response_json["max_page_items"])
							total_pages_censored_l = math.ceil(total_items / max_page_items)
						self.progress_percentage = int((page_number / (total_pages + total_pages_series + total_pages_censored)) * 100)
						for x in self.onProgressChanged:
							x()
						print("[M3UIPTV][Stalker][VOD CENSORED] progress %d / Page Number: %d / Total Pages: %d" % (self.progress_percentage, page_number, total_pages_censored))
						page_number += 1
						page_number_l += 1
						if page_number_l >= total_pages_censored_l:
							break
					except ValueError:
						print("[M3UIPTV][Stalker] Invalid JSON format in response")
				else:
					print(f"[M3UIPTV][Stalker] IPTV Request failed for page {page_number}")

		page_number = 1
		while True:
			time.sleep(0.05)
			url = f"{self.getPortalUrl()}?type=vod&action=get_ordered_list&p={page_number}&JsHttpRequest=1-xml"
			response_json = self.pull_json_with_reauth(url, True)
			if response_json:
				try:
					if not response_json:
						page_number += 1
						if page_number >= total_pages_series:
							break
						continue
					vods_data = response_json["data"]
					for vod in vods_data:
						item = {}
						item["num"] = vod.get("id")
						item["name"] = vod.get("name")
						item["stream_type"] = "movie" if vod.get("is_movie", 0) == 1 else "series"
						item["stream_id"] = vod.get("id")
						item["stream_icon"] = vod.get("screenshot_uri")
						item["cover"] = vod.get("screenshot_uri")
						item["rating"] = vod.get("rating_imdb") if "rating_imdb" in vod else vod.get("rating_kinopoisk")
						item["added"] = vod.get("added")
						item["is_adult"] = vod.get("censored")
						item["category_id"] = vod.get("category_id")
						item["hd"] = vod.get("hd", "0")
						item["tmdb_id"] = vod.get("tmdb_id", "")
						item["plot"] = vod.get("description")
						item["director"] = vod.get("director")
						item["actors"] = vod.get("actors")
						item["year"] = vod.get("year")
						item["genres_str"] = vod.get("genres_str")
						item["play_url"] = vod.get("cmd")
						movies.append(item)
					if total_pages == 0:
						total_items = int(response_json["total_items"])
						max_page_items = int(response_json["max_page_items"])
						total_pages = math.ceil(total_items / max_page_items)
					self.progress_percentage = int(((page_number + total_pages_censored) / (total_pages + total_pages_series + total_pages_censored)) * 100)
					for x in self.onProgressChanged:
						x()
					print("[M3UIPTV][Stalker][VOD] progress %d / Page Number: %d / Total Pages: %d" % (self.progress_percentage, page_number, total_pages))
					page_number += 1
					if page_number >= total_pages:
						break
				except ValueError:
					print("[M3UIPTV][Stalker] Invalid JSON format in response")
			else:
				print(f"[M3UIPTV][Stalker] IPTV Request failed for page {page_number}")
				if page_number >= total_pages:
					break

		# Series retrival
		page_number = 1
		while True:
			time.sleep(0.05)
			url = f"{self.getPortalUrl()}?type=series&action=get_ordered_list&p={page_number}&JsHttpRequest=1-xml"
			response_json = self.pull_json_with_reauth(url, True)
			if response_json:
				try:
					if not response_json:
						page_number += 1
						if page_number >= total_pages_series:
							break
						continue
					if isinstance(response_json, bool):
						break
					vods_data = response_json["data"]
					for vod in vods_data:
						item = {}
						item["num"] = vod.get("id")
						item["name"] = vod.get("name")
						item["stream_type"] = "movie" if vod.get("is_movie") == 1 else "series"
						item["series_id"] = vod.get("id")
						item["stream_icon"] = vod.get("screenshot_uri")
						item["rating"] = vod.get("rating_imdb") if "raating_imdb" in vod else vod.get("rating_kinopoisk")
						item["added"] = vod.get("added")
						item["is_adult"] = vod.get("censored")
						item["category_id"] = vod.get("category_id")
						item["hd"] = vod.get("hd")
						item["tmdb_id"] = vod.get("tmdb_id")
						item["plot"] = vod.get("description")
						item["director"] = vod.get("director")
						item["actors"] = vod.get("actors")
						item["year"] = vod.get("year")
						item["genres_str"] = vod.get("genres_str")
						item["play_url"] = vod.get("cmd")
						series.append(item)
					total_items = int(response_json["total_items"])
					self.progress_percentage = int(((page_number + total_pages + total_pages_censored) / (total_pages + total_pages_series + total_pages_censored)) * 100)
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
				if page_number >= total_pages:
					break

		self.progress_percentage = -1
		for x in self.onProgressChanged:
			x()
		return movies, series

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

	def getSeriesById(self, series_id):
		if not self.token:
			self.get_token()
		cookies = self.generate_cookies(True)
		headers = self.generate_headers()
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
						marker = []
						# if info and info.get("season"):
						# 	marker.append(_("S%s") % str(info.get("season")))
						episode_num = str(episode)
						episode_image = season.get("screenshot_uri", None)
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
							ret.append((episode_url, title, info, self, ", ".join(marker), id.split(":")[0], episode_image))
							titles.append(title)
					total_vod_count += 1
				total_items = response_json["js"]["total_items"]
				page_number += 1
				if total_vod_count >= total_items:
					break
		return ret

	def getPortalVersion(self):
		try:
			url = self.url.removesuffix("/").removesuffix("/server").removesuffix("/c").removesuffix("/")
			url_version = url + "/c/version.js"
			req = urllib.request.Request(url_version, headers={'User-Agent': REQUEST_USER_AGENT})
			req_timeout_val = config.plugins.m3uiptv.req_timeout.value
			if req_timeout_val != "off":
				response = urllib.request.urlopen(req, timeout=int(req_timeout_val))
			else:
				response = urllib.request.urlopen(req, timeout=10)  # set a timeout to prevent blocking
			if response.status == 404:
				url_version = url + "/stalker_portal/c/version.js"
				req = urllib.request.Request(url_version, headers={'User-Agent': REQUEST_USER_AGENT})
				if req_timeout_val != "off":
					response = urllib.request.urlopen(req, timeout=int(req_timeout_val))
				else:
					response = urllib.request.urlopen(req, timeout=10)  # set a timeout to prevent blocking
				if response.status == 404:
					url_version = url + "/stalker_portal/c/version.js"
					req = urllib.request.Request(url_version, headers={'User-Agent': REQUEST_USER_AGENT})
					if req_timeout_val != "off":
						response = urllib.request.urlopen(req, timeout=int(req_timeout_val))
					else:
						response = urllib.request.urlopen(req, timeout=10)  # set a timeout to prevent blocking
					if response.status == 404:
						return None

			version_response = response.read().decode("utf-8")
			return version_response.replace("var ver = '", "").replace("';", "")
		except:
			return None

	# -------------------------------------------------------------------------
	# DATA LOADING FROM STORAGE
	# -------------------------------------------------------------------------

	def loadVoDMoviesFromFile(self):
		self.vod_movies = []
		vodFile = USER_IPTV_VOD_MOVIES_FILE % self.scheme
		json_string = self.loadFromFile(vodFile)
		self.makeVodListFromJson(json_string)
		for x in self.onProgressChanged:
			x()

	def loadInfoFromFile(self):
		info_file = USER_IPTV_PROVIDER_INFO_FILE % self.scheme
		json_string = self.loadFromFile(info_file)
		if json_string:
			self.provider_info = json.loads(json_string)

	# -------------------------------------------------------------------------
	# DATA STORING
	# -------------------------------------------------------------------------

	def createChannelsFile(self, epghelper, groups):
		epghelper.createStalkerChannelsFile(groups)

	def storePlaylistAndGenBouquet(self):
		self.checkForNetwrok()
		if not self.token:
			self.get_token()
		if self.token:
			# self.getProviderInfo()
			genres = self.get_genres()
			groups = self.get_all_channels(genres)
			self.channels_callback(groups)
			self.piconsDownload()
			self.generateEPGImportFiles(groups)
			if time.time() - self.last_vod_update_time > 7*24*60*60:
				self.generateMediaLibrary()

	def generateMediaLibrary(self):
		if not self.ignore_vod:
			vod_categories = self.getVODCategories()
			for category in vod_categories:
				self.movie_categories[category["category_id"]] = category["category_name"]
			series_categories = self.getSeriesCategories()
			for category in series_categories:
				self.series_categories[category["category_id"]] = category["category_name"]
			threads.deferToThread(self.get_vod, vod_categories).addCallback(self.store_vod)

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
		self.last_vod_update_time = time.time()
		from .plugin import writeProviders  # deferred import
		writeProviders()  # save to config so it doesn't get lost on reboot

	# -------------------------------------------------------------------------
	# PROCESS DYNAMIC SERVICE DATA
	# -------------------------------------------------------------------------

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
			self.get_token()
		if self.token:
			iptv_url, token_valid = self.get_stream_play_url(cmd.replace("|amp|", "&"))
			if not token_valid:
				self.get_token()
				iptv_url, token_valid = self.get_stream_play_url(cmd.replace("|amp|", "&"))
			if catchup_days:
				iptv_url = self.constructCatchupSuffix(catchup_days, iptv_url, CATCHUP_STALKER_TEXT)

			if self.output_format == "ts":
				iptv_url = iptv_url.replace("extension=m3u8", "extension=ts")
			elif self.output_format == "m3u8":
				iptv_url = iptv_url.replace("extension=ts", "extension=m3u8")
			nref_new = "%s:%s%s:%s•%s" % (origRef, iptv_url.replace(":", "%3a").replace("ffmpeg ", "").replace('ffrt ', ''), "" if self.custom_user_agent == "off" else ("#User-Agent=" + USER_AGENTS[self.custom_user_agent]), orig_name, self.iptv_service_provider)
			nref_new = origRef + ":" + iptv_url.replace(":", "%3a").replace("ffmpeg ", "").replace('ffrt ', '') + ":" + orig_name + "•" + self.iptv_service_provider
			nnref = eServiceReference(nref_new)
			try: #type2 distros support
				nnref.setCompareSref(nref.toString())
			except:
				pass
			self.isPlayBackup = False
		if callback:
			callback(nnref)
		return nnref, nref, False
