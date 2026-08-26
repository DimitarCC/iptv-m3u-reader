from . import _

from enigma import eDVBDB, eServiceReference
from ServiceReference import ServiceReference
from Components.config import config
from xml.dom import minidom
from urllib.parse import urlparse
import requests
import time
import re
import math
import json
import urllib
import random
import hashlib
from zoneinfo import ZoneInfo
from datetime import datetime
from twisted.internet import threads
from .IPTVProcessor import IPTVProcessor
from .VoDItem import VoDItem
from .Variables import USER_IPTV_VOD_MOVIES_FILE, REQUEST_USER_AGENT, USER_AGENTS, CATCHUP_STALKER, CATCHUP_STALKER_TEXT, USER_IPTV_MOVIE_CATEGORIES_FILE, \
	 				   USER_IPTV_SERIES_CATEGORIES_FILE, USER_IPTV_PROVIDER_INFO_FILE

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
		self.serial = ""
		self.devid = ""
		self.devid2 = ""
		self.signature = ""
		self.custom_serial = ""
		self.custom_device_id1 = ""
		self.custom_device_id2 = ""
		self.custom_signature = ""

	# -------------------------------------------------------------------------
	# HELPER FUNCTIONS
	# -------------------------------------------------------------------------

	def request(self, url):
		try:
			req = urllib.request.Request(url, headers={'User-Agent': REQUEST_USER_AGENT})
			req_timeout_val = config.plugins.m3uiptv.req_timeout.value
			if req_timeout_val != "off":
				response = urllib.request.urlopen(req, timeout=int(req_timeout_val))
			else:
				response = urllib.request.urlopen(req, timeout=10)  # set a timeout to prevent blocking
			return response
		except urllib.error.HTTPError as ex:
			return ex

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

	def generate_signature(self, serial, dev_id, dev_id2=None) -> str:
		"""
        Generate signature for profile request.

        Returns:
            str: Generated signature.
        """
		if dev_id2 is None:
			dev_id2 = dev_id
		data = f"{self.mac}{serial}{dev_id}{dev_id2}"
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
		return {
			"User-Agent": REQUEST_USER_AGENT,
			"Authorization": "Bearer " + self.token,
			"Referer": self.url + "/stalker_portal/c/index.html",
			"X-User-Agent": "Model: MAG250; Link: WiFi",
			"Pragma": "no-cache",
			"Host": self.get_host(),
			"Connection": "Close"}

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
			headers = {
				"User-Agent": REQUEST_USER_AGENT,
				"Referer": referrer,
				"X-User-Agent": "Model: MAG250; Link: WiFi",
				"Pragma": "no-cache",
				"Host": host,
				"Connection": "Close"}
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
							return "", ""  # give up since we can not find the right entry point
			elif response.status_code == 200 and self.portal_entry_point_type == -1:
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
		# Fetch user profile after ensuring a valid token.
		try:
			if not from_token and not self.token:
				self.get_token()

			version = self.getPortalVersion()
			if version:
				print("[M3UIPTV][Stalker] Portal version: " + version)

			if not self.serial:
				self.serial = self.custom_serial if self.custom_serial else self.generate_serial(self.mac)

			if not self.devid:
				self.devid = self.custom_device_id1 if self.custom_device_id1 else self.generate_device_id()

			if not self.devid2:
				self.devid2 = self.custom_device_id2 if self.custom_device_id2 else self.devid

			if not self.signature:
				self.signature = self.custom_signature if self.custom_signature else self.generate_signature(self.serial, self.devid, self.devid2)

			url = self.getPortalUrl()
			if version and version.strip().startswith("5.6"):
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
					"sn": self.serial,
					"stb_type": "MAG250",
					"client_type": "STB",
					"image_version": "218",
					"video_out": "hdmi",
					"device_id": self.devid,
					"device_id2": self.devid2,
					"signature": self.signature,
					"auth_second_step": "1",
					"hw_version": "1.7-BD-00",
					"not_valid_token": "0",
					"metrics": self.generate_metrics(self.serial),
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
					"sn": self.serial,
					"client_type": "STB",
					"video_out": "hdmi",
					"signature": self.signature,
					"auth_second_step": "1",
					"not_valid_token": "0",
					"metrics": self.generate_metrics(self.serial),
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
				server_timezone_offset = (self.zone.utcoffset(datetime.now()).total_seconds()) // 3600

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
				info["user_info"]["status"] = "Active" if js_data and js_data.get("blocked") == "0" else "Not active"
				info["user_info"]["exp_date"] = expiry_date or _("Unknown")
				info["server_info"] = {}
				info["server_info"]["version"] = version or ""
				info["server_info"]["url"] = self.getPortalUrl()
				info["server_info"]["timezone"] = js_data and js_data["default_timezone"]

				dest_file = USER_IPTV_PROVIDER_INFO_FILE % self.scheme
				self.provider_info = self.getDataToFile(info, dest_file)
		except Exception as ex:
			print("[M3UIPTV][Stalker] Error getting profile: " + str(ex))
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

	def getPortalVersion(self):
		try:
			url = self.url.removesuffix("/").removesuffix("/server").removesuffix("/c").removesuffix("/").removesuffix("/stalker_portal")
			url_version = url + "/version.js"
			response = self.request(url_version)
			if response.status == 404:
				url_version = url + "/c/version.js"
				response = self.request(url_version)
				if response.status == 404:
					url_version = url + "/stalker_portal/c/version.js"
					response = self.request(url_version)
					if response.status == 404:
						# url_version = url + "/stalker_portal/c/version.js"
						# req = urllib.request.Request(url_version, headers={'User-Agent': REQUEST_USER_AGENT})
						# if req_timeout_val != "off":
						# 	response = urllib.request.urlopen(req, timeout=int(req_timeout_val))
						# else:
						# 	response = urllib.request.urlopen(req, timeout=10)  # set a timeout to prevent blocking
						# if response.status == 404:
						return None

			version_response = response.read().decode("utf-8")
			return version_response.replace("var ver = '", "").replace("';", "")
		except Exception as ex:
			print("[M3UIPTV][Stalker] Error getting portal version: " + str(ex))
			return None

	# -------------------------------------------------------------------------
	# EPG HANDLING
	# -------------------------------------------------------------------------

	def getEpgUrl(self):
		return self.custom_xmltv_url if self.is_custom_xmltv and self.custom_xmltv_url else "http://localhost:9010/StalkerEPG?p=%s" % self.scheme

	def generateXMLTVFile(self):  # Use this for the timer for regenerate of EPG xml
		if self.create_epg and not self.custom_xmltv_url:
			self.checkForNetwrok()
			self.get_token()
			if self.token:
				genres = self.get_genres()
				groups = self.get_all_channels(genres)
				channels = [x for xs in groups.values() for x in xs[1]]
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

						for k, v in epg_data.items():
							channel = None

							if str(k) in channel_dict.keys():
								channel = channel_dict[str(k)]

							for epg in v:
								start_time = datetime.fromtimestamp(float(epg['start_timestamp']), self.zone)
								stop_time = datetime.fromtimestamp(float(epg['stop_timestamp']), self.zone)

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
		def do_request():
			cookies = self.generate_cookies(include_token_in_cookies)
			headers = self.generate_headers()
			if params:
				return self.session.get(url, cookies=cookies, headers=headers, params=params)
			return self.session.get(url, cookies=cookies, headers=headers)

		def extract_js(response):
			# a token/session error (e.g. MAG_TOKEN_INVALID) is still valid JSON, just without a "js" key,
			# so an HTTP error status or a body with no "js" key must also be treated as an auth failure
			if response.status_code != 200:
				return None
			body = response.json()
			if not isinstance(body, dict) or "js" not in body:
				return None
			return body["js"]

		try:
			response = do_request()
			js = extract_js(response)
			if js is None and not skip_reauth:
				self.get_token(skip_profile)
				response = do_request()
				js = extract_js(response)
			return js if js is not None else {}
		except:
			return {}

	def channels_callback(self, groups):
		tsid = 1000
		blacklist = self.readBlacklist()
		srefs_for_main = []
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

			bouquet_prefix = "userbouquet"
			if self.create_bouquets_strategy == 3:
				bouquet_prefix = "subbouquet"

			if len(services) > 0:
				bfilename = self.cleanFilename(f"{bouquet_prefix}.m3uiptv.{self.scheme}.{group[0]}.tv")
				if group[0] in blacklist:
					self.removeBouquet(bfilename)  # remove blacklisted bouquet if already exists
					continue
				if self.create_bouquets_strategy == 3:
					srefs_for_main.append(f'1:7:1:0:0:0:0:0:0:0:FROM BOUQUET "{bfilename}" ORDER BY bouquet')
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

		if self.create_bouquets_strategy == 3:
			bfilename = self.cleanFilename(f"userbouquet.m3uiptv.{self.scheme}.tv")
			db.addOrUpdateBouquet(provider_name_for_titles, bfilename, srefs_for_main, False)

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

	def getVoDCategoriesBase(self, blacklist_type=0):
		url = f"{self.getPortalUrl()}?type=vod&action=get_categories&JsHttpRequest=1-xml"
		genre_data = self.pull_json_with_reauth(url, True)
		genres = []
		examples = []
		try:
			if genre_data:
				for i in genre_data:
					gid = i["id"]
					if isinstance(gid, int):
						gid = str(gid)
					name = i["title"]
					censored = i.get("censored", 0)
					genres.append({'category_name': name, 'category_type': 'VOD', 'category_id': gid, 'censored': censored})
					if gid != "*":
						examples.append(name + "|gid|" + gid)
				self.writeExampleBlacklist(examples, blacklist_type)
		except:
			pass
		return genres

	def getVODCategories(self) -> list:
		try:
			genres = self.getVoDCategoriesBase(1)
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
				examples = []
				for i in genre_data:
					gid = i["id"]
					if isinstance(gid, int):
						gid = str(gid)
					name = i["title"]
					genres.append({'category_name': name, 'category_type': 'SERIES', 'category_id': gid})
					if gid != "*":
						examples.append(name + "|gid|" + gid)
				if len(examples) > 0:
					self.writeExampleBlacklist(examples, 2)
				if len(genres) == 0:
					genres = self.getVoDCategoriesBase(1)
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
						surl = f"{self.scheme}%3a//{channel['id']}?cmd={channel['cmd'].replace('ffmpeg ', '').replace('ffrt ', '').replace('&', '|amp|').replace(':', '%3a')}"
						if self.create_bouquets_strategy > 0 and self.create_bouquets_strategy < 3:  # config option here: for user-optional, all-channels bouquet
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
			surl = f"{self.scheme}%3a//{channel['id']}?cmd={channel['cmd'].replace('ffmpeg ', '').replace('ffrt ', '').replace('&', '|amp|').replace(':', '%3a')}"
			if self.output_format == "ts":
				surl = surl.replace("extension=m3u8", "extension=ts")
			elif self.output_format == "m3u8":
				surl = surl.replace("extension=ts", "extension=m3u8")
			if genre_id := channel["tv_genre_id"]:
				if isinstance(genre_id, int):
					genre_id = str(genre_id)
				category_id = genre_id
				if self.create_bouquets_strategy > 0 and self.create_bouquets_strategy < 3:  # config option here: for user-optional, all-channels bouquet
					if category_id not in groups or groups[category_id][0] not in blacklist:
						groups["ALL_CHANNELS"][1].append(Channel(channel["id"], channel["number"], channel["name"], surl, channel["tv_archive_duration"], channel["logo"], channel["xmltv_id"]))

				if self.create_bouquets_strategy != 1:  # config option here: for sections bouquets
					groups[category_id if category_id and category_id in groups else "EMPTY"][1].append(Channel(channel["id"], channel["number"], channel["name"], surl, channel["tv_archive_duration"], channel["logo"], channel["xmltv_id"]))

		for censored_group in censored_groups:
			self.get_channels_for_group(groups, groups[censored_group][1], censored_group)

		return groups

	def get_stream_play_url(self, cmd):
		url = f"{self.getPortalUrl()}?type=itv&action=create_link&cmd={cmd}&series=&forced_storage=undefined&disable_ad=0&download=0&JsHttpRequest=1-xml"
		js = self.pull_json_with_reauth(url, True)
		try:
			return self.resolveLiveStreamUrl(js["cmd"]), True
		except:  # probably token has expired
			self.get_token()
			js = self.pull_json_with_reauth(url, True)
			try:
				return self.resolveLiveStreamUrl(js["cmd"]), True
			except:
				return cmd, False

	def resolveLiveStreamUrl(self, cmd):
		"""Some portals return an intermediate redirector link from create_link rather than the
		final playable URL: it must be followed (HEAD, to resolve any redirect) and its response body
		(itself a short M3U playlist) parsed for the actual media segment, matching reference Stalker clients.
		Other portals (and this is the common case) already return a final, single-use play_token URL from
		create_link itself - probing that with an extra HEAD request would consume the single-use token before
		the player ever connects, so only attempt resolution when the url doesn't already look like a direct,
		already-tokenized play link."""
		parts = cmd.split(" ")
		url = parts[1] if len(parts) > 1 else parts[0]
		if "?" in url:  # already carries query params (e.g. play_token=...) - treat as final, do not probe it
			return url
		start = time.time()
		try:
			response = self.session.head(url, headers=self.generate_headers(), allow_redirects=True, timeout=10)
			if response.status_code == 200 and response.text:
				lines = [line for line in response.text.splitlines() if line and not line.startswith("#")]
				if lines:
					resolved_base = response.url.split("?")[0]
					resolved_base = resolved_base[:resolved_base.rfind("/")]
					resolved = resolved_base + "/" + lines[-1]
					print("[M3UIPTV][Stalker] Resolved live stream url in %.2fs: %s -> %s" % (time.time() - start, url, resolved))
					return resolved
		except Exception as ex:
			print("[M3UIPTV][Stalker] Error resolving live stream url: " + str(ex))
		print("[M3UIPTV][Stalker] Live stream url not resolved (used as-is) after %.2fs: %s" % (time.time() - start, url))
		return url

	def getVoDPlayUrl(self, url, movie=0, series=0):
		if ("http://" in url or "https://" in url) and "localhost" not in url and self.portal_entry_point_type != 3:
			return url.replace("ffmpeg ", "").replace("ffrt ", "")
		orig_url = url
		if not self.token:
			self.get_token()
		ext = ""
		if "." in url:
			ext = url[url.rfind("."):]
		if url.startswith("/media/"):
			url = f"{self.getPortalUrl()}?type=vod&action=get_ordered_list&movie_id={movie}&p=1&JsHttpRequest=1-xml"
			stream_data_temp = self.pull_json_with_reauth(url, True)
			if stream_data_temp:
				data = stream_data_temp.get('data', [])
				if data:
					m_id = data[0].get("id")
					url = f"/media/file_{m_id}{ext}"
		url = f"{self.getPortalUrl()}?type=vod&action=create_link&cmd={url}&JsHttpRequest=1-xml&series={str(series)}"
		stream_data = self.pull_json_with_reauth(url, True)
		print(stream_data)
		cmd = stream_data["cmd"].replace("ffmpeg ", "").replace("ffrt ", "") if stream_data else orig_url.replace("ffmpeg ", "").replace("ffrt ", "")
		return cmd

	def getVodMoviesPage(self, category_id, page, search_terms=None):
		"""Fetch a single page of movies from the portal (category_id=None means the "All" pseudo-category)."""
		if not self.token:
			self.get_token()
		url = f"{self.getPortalUrl()}?type=vod&action=get_ordered_list&p={page}&JsHttpRequest=1-xml"
		if category_id:
			url += f"&category={category_id}"
		if search_terms:
			url += f"&search={urllib.parse.quote(search_terms)}"
		response_json = self.pull_json_with_reauth(url, True)
		items = []
		has_more = False
		total_items = 0
		if response_json:
			for vod in response_json.get("data", []):
				is_series_val = vod.get("is_series", 0)
				if is_series_val == "1" or is_series_val == 1:
					continue
				name = vod.get("name")
				stream_id = vod.get("id")
				if not name or stream_id is None:
					continue
				items.append(VoDItem(vod.get("cmd"), name, int(stream_id), self, self.movie_categories.get(str(vod.get("category_id"))), vod.get("description"), vod.get("screenshot_uri")))
			total_items = int(response_json.get("total_items", 0) or 0)
			max_page_items = int(response_json.get("max_page_items", 0) or 0)
			has_more = max_page_items > 0 and page * max_page_items < total_items
		return items, has_more, total_items

	def getSeriesPage(self, category_id, page, search_terms=None):
		"""Fetch a single page of series from the portal (category_id=None means the "All" pseudo-category)."""
		if not self.token:
			self.get_token()
		url = f"{self.getPortalUrl()}?type=series&action=get_ordered_list&p={page}&JsHttpRequest=1-xml"
		if category_id:
			url += f"&category={category_id}"
		if search_terms:
			url += f"&search={urllib.parse.quote(search_terms)}"
		response_json = self.pull_json_with_reauth(url, True)
		items = []
		has_more = False
		total_items = 0
		if response_json:
			for vod in response_json.get("data", []):
				name = vod.get("name")
				series_id = vod.get("id")
				if not name or series_id is None:
					continue
				items.append((str(series_id), name, vod.get("description"), vod.get("screenshot_uri")))
			total_items = int(response_json.get("total_items", 0) or 0)
			max_page_items = int(response_json.get("max_page_items", 0) or 0)
			has_more = max_page_items > 0 and page * max_page_items < total_items
		return items, has_more, total_items

	def makeVodListFromJson(self, json_string):
		if json_string:
			vod_json_obj = json.loads(json_string)
			for movie in vod_json_obj:
				name = movie["name"]
				# ext = movie["container_extension"]
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
		# file = path.join(self.getTempDir(), series_id)
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
						episode_url = f"{season['cmd']}||{str(episode)}"  # self.getVoDPlayUrl(season["cmd"], episode)
						if title and info and title not in titles:
							ret.append((episode_url, title, info, self, ", ".join(marker), id.split(":")[0], episode_image))
							titles.append(title)
					total_vod_count += 1
				total_items = response_json["js"]["total_items"]
				page_number += 1
				if total_vod_count >= total_items:
					break
		return ret

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
			if time.time() - self.last_vod_update_time > 7 * 24 * 60 * 60:
				self.generateMediaLibrary()

	def generateMediaLibrary(self):
		# VoD/series browsing is lazy-loaded page by page (see getVodMoviesPage/getSeriesPage), so only
		# the (cheap) category lists need to be refreshed here - no need to eagerly download the full catalog.
		if not self.ignore_vod:
			vod_categories = self.getVODCategories()
			if vod_categories:
				for category in vod_categories:
					self.movie_categories[category["category_id"]] = category["category_name"]
			series_categories = self.getSeriesCategories()
			if series_categories:
				for category in series_categories:
					self.series_categories[category["category_id"]] = category["category_name"]
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
		self.isPlayBackup = False
		if callback:
			# Resolving the live stream (handshake + create_link) is a blocking network round-trip; doing it
			# on the GUI thread would freeze input handling for its duration, and any key event that arrives
			# while frozen gets delivered the instant we return - right as the newly-started service appears,
			# which can immediately stop it. Resolve off the GUI thread and invoke the callback only once
			# the real URL is known, so the GUI/input loop keeps running normally throughout.
			threads.deferToThread(self.resolveLiveChannel, origRef, orig_name, cmd, catchup_days, nref).addCallback(callback)
		return nnref, nref, False

	def resolveLiveChannel(self, origRef, orig_name, cmd, catchup_days, nref):
		self.checkForNetwrok()
		if not self.token:
			self.get_token()
		nnref = nref
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
			if "?" in iptv_url and "." not in iptv_url.split("?")[0].rsplit("/", 1)[-1]:
				# no real file extension before the query string: GStreamer's own extension sniffing
				# (used only as a hint, not sent to the server) otherwise grabs a bogus ".something"
				# from the domain name, so give it an explicit one matching the configured output format
				fake_ext = ".ts" if self.output_format != "m3u8" else ".m3u8"
				base, query = iptv_url.split("?", 1)
				iptv_url = base + fake_ext + "?" + query
			nref_new = "%s:%s%s:%s•%s" % (origRef, iptv_url.replace(":", "%3a").replace("ffmpeg ", "").replace('ffrt ', ''), "" if self.custom_user_agent == "off" else ("#User-Agent=" + USER_AGENTS[self.custom_user_agent]), orig_name, self.iptv_service_provider)
			nnref = eServiceReference(nref_new)
			try:  # type2 distros support
				nnref.setCompareSref(nref.toString())
			except:
				pass
		return nnref
