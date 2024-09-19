from enigma import eDVBDB
from Components.config import config
from Tools.Directories import fileExists
import socket
from twisted.internet import threads
import requests
import json
import time
from .IPTVProcessor import IPTVProcessor
from .VoDItem import VoDItem
from .Variables import USER_IPTV_VOD_MOVIES_FILE, USER_AGENT

from os import fsync, rename

import threading
write_lock = threading.Lock()

db = eDVBDB.getInstance()

class Channel():
	def __init__(self, id, name, cmd):
		self.id = id
		self.name = name
		self.cmd = cmd

class StalkerProvider(IPTVProcessor):
	def __init__(self):
		IPTVProcessor.__init__(self)
		self.type = "Stalker"
		self.refresh_interval = -1
		self.vod_movies = []
		self.progress_percentage = -1
		
	def storePlaylistAndGenBouquet(self):
		is_check_network_val = config.plugins.m3uiptv.check_internet.value
		if is_check_network_val != "off":
			socket.setdefaulttimeout(int(is_check_network_val))
			socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("8.8.8.8", 53))

		session = requests.Session()
		token = self.get_token(session)
		if token:
			genres = self.get_genres(session, token)
			# print("GETTING CHANNELS FOR GENRE %s/%s" % (genres[0]["genre_id"], genres[0]["name"]))
			threads.deferToThread(self.get_channels, session, token, genres[0]["genre_id"]).addCallback(self.channels_callback)


	def channels_callback(self, channels):
		tsid = 1000
		services = []
		for service in channels:
			surl = service.cmd
			ch_name = service.name.replace(":", "|")
			stype = "1"
			if ("UHD" in ch_name or "4K" in ch_name) and not " HD" in ch_name:
				stype = "1F"
			elif "HD" in ch_name:
				stype = "19"
			sref = "%s:0:%s:%d:%d:1:CCCC0000:0:0:0:%s:%s•%s" % (self.play_system, stype, tsid, self.onid, surl.replace(":", "%3a"), ch_name, self.iptv_service_provider)
			tsid += 1
			services.append(sref)

		if not self.ignore_vod:
			self.getVoDMovies()

		db.addOrUpdateBouquet(self.iptv_service_provider, services, 1)
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
			print("EXCEPTION: " + str(ex))
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
			print("EXCEPTION: " + str(ex))
			pass

	def get_channels(self, session, token, genre_id):
		try:
			channels = []
			cookies = {"mac": self.mac, "stb_lang": "en", "timezone": "Europe/London"}
			headers = {"User-Agent": USER_AGENT, "Authorization": "Bearer " + token}
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
					print("GETTING CHANNELS FOR PAGE %d" % page_number)
					try:
						response_json = response.json()
						channels_data = response_json["js"]["data"]
						
						for channel in channels_data:
							surl = channel["cmd"].replace("ffmpeg ", "")
							if self.play_system != "1":
								surl = surl.replace("extension=ts","extension=m3u8")
							channels.append(Channel(channel["id"], channel["name"], channel["cmd"].replace("ffmpeg ", "")))
						total_items = response_json["js"]["total_items"]
						if len(channels) >= total_items:
							self.progress_percentage = -1
							break
						print("CURRENT PROGRESS: (%d//%d)*100 = %d" % (len(channels), total_items, (len(channels)/total_items) * 100))
						self.progress_percentage = int((len(channels)/total_items) * 100)
						page_number += 1
					except ValueError:
						print("EXCEPTION: Invalid JSON format in response")
				else:
					print(f"EXCEPTION: IPTV Request failed for page {page_number}")

			return channels
		except Exception as ex:
			print("EXCEPTION: " + str(ex))
			self.bouquetCreated(ex)
			pass

	def getVoDMovies(self):
		# is_check_network_val = config.plugins.m3uiptv.check_internet.value
		# if is_check_network_val != "off":
		# 	socket.setdefaulttimeout(int(is_check_network_val))
		# 	socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("8.8.8.8", 53))
		# url = "%s/player_api.php?username=%s&password=%s&action=get_vod_streams" % (self.url, self.username, self.password)
		# req = urllib.request.Request(url, headers={'User-Agent' : "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36 Edg/127.0.0.0"}) 
		# req_timeout_val = config.plugins.m3uiptv.req_timeout.value
		# if req_timeout_val != "off":
		# 	response = urllib.request.urlopen(req, timeout=int(req_timeout_val))
		# else:
		# 	response = urllib.request.urlopen(req)
		# vod_response = response.read()
		# dest_file = USER_IPTV_VOD_MOVIES_FILE % self.scheme
		# with write_lock:
		# 	f = open(dest_file + ".writing", 'w')
		# 	f.write(vod_response.decode('utf-8'))
		# 	f.flush()
		# 	fsync(f.fileno())
		# 	f.close()
		# 	rename(dest_file + ".writing", dest_file)

		# vod_json_obj = json.loads(vod_response)
		# self.vod_movies = []
		# for movie in vod_json_obj:
		# 	name = movie["name"]
		# 	ext = movie["container_extension"]
		# 	id = movie["stream_id"]
		# 	url = "%s/movie/%s/%s/%s.%s" % (self.url, self.username, self.password, id, ext)
		# 	vod_item = VoDItem(url, name)
		# 	self.vod_movies.append(vod_item)
		# self.vod_movies.reverse()
		pass

	def loadVoDMoviesFromFile(self):
		vodFile = USER_IPTV_VOD_MOVIES_FILE % self.scheme
		if not fileExists(vodFile):
			self.vod_movies = []
			return
		fd = open(vodFile, 'rb')
		json_string = fd.read()
		fd.close()
		vod_json_obj = json.loads(json_string)
		self.vod_movies = []
		for movie in vod_json_obj:
			name = movie["name"]
			ext = movie["container_extension"]
			id = movie["stream_id"]
			url = "%s/movie/%s/%s/%s.%s" % (self.url, self.username, self.password, id, ext)
			vod_item = VoDItem(url, name)
			self.vod_movies.append(vod_item)
		self.vod_movies.reverse()