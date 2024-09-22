from enigma import eDVBDB
from Components.config import config
from Tools.Directories import fileExists
import socket
import urllib
import json
from .IPTVProcessor import IPTVProcessor
from .VoDItem import VoDItem
from .Variables import USER_IPTV_VOD_MOVIES_FILE, USER_AGENT
from Tools.Directories import sanitizeFilename

from os import fsync, rename

import threading
write_lock = threading.Lock()

db = eDVBDB.getInstance()

class XtreemProvider(IPTVProcessor):
	def __init__(self):
		IPTVProcessor.__init__(self)
		self.type = "Xtreeme"
		self.refresh_interval = -1
		self.vod_movies = []
		self.progress_percentage = -1
		self.create_groups = True
		
	def storePlaylistAndGenBouquet(self):
		is_check_network_val = config.plugins.m3uiptv.check_internet.value
		if is_check_network_val != "off":
			socket.setdefaulttimeout(int(is_check_network_val))
			socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("8.8.8.8", 53))
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

		groups["EMPTY"] = ("UNCATEGORIZED", [])

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

		for service in services_json_obj:
			surl = "%s/live/%s/%s/%s.%s" % (self.url, self.username, self.password, service["stream_id"], "ts" if self.play_system == "1" else "m3u8")
			ch_name = service["name"].replace(":", "|")
			stype = "1"
			if ("UHD" in ch_name or "4K" in ch_name) and not " HD" in ch_name:
				stype = "1F"
			elif "HD" in ch_name:
				stype = "19"
			sref = self.generateChannelReference(stype, tsid, surl.replace(":", "%3a"), ch_name)
			tsid += 1
			groups[(service["category_id"] if service["category_id"] else "EMPTY")][1].append(sref)

		if not self.ignore_vod:
			self.getVoDMovies()

		for groupItem in groups.values():
			bfilename =  sanitizeFilename(f"userbouquet.m3uiptv.{self.iptv_service_provider}.{groupItem[0]}.tv".replace(" ", "").replace("(", "").replace(")", "").replace("&", ""))
			db.addOrUpdateBouquet(self.iptv_service_provider.upper() + " - " + groupItem[0], bfilename, groupItem[1], False)
		self.bouquetCreated(None)

	def getVoDMovies(self):
		is_check_network_val = config.plugins.m3uiptv.check_internet.value
		if is_check_network_val != "off":
			socket.setdefaulttimeout(int(is_check_network_val))
			socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("8.8.8.8", 53))
		url = "%s/player_api.php?username=%s&password=%s&action=get_vod_streams" % (self.url, self.username, self.password)
		req = urllib.request.Request(url, headers={'User-Agent' : USER_AGENT}) 
		req_timeout_val = config.plugins.m3uiptv.req_timeout.value
		if req_timeout_val != "off":
			response = urllib.request.urlopen(req, timeout=int(req_timeout_val))
		else:
			response = urllib.request.urlopen(req)
		vod_response = response.read()
		dest_file = USER_IPTV_VOD_MOVIES_FILE % self.scheme
		with write_lock:
			f = open(dest_file + ".writing", 'w')
			f.write(vod_response.decode('utf-8'))
			f.flush()
			fsync(f.fileno())
			f.close()
			rename(dest_file + ".writing", dest_file)

		vod_json_obj = json.loads(vod_response)
		self.vod_movies = []
		for movie in vod_json_obj:
			name = movie["name"]
			ext = movie["container_extension"]
			id = movie["stream_id"]
			url = "%s/movie/%s/%s/%s.%s" % (self.url, self.username, self.password, id, ext)
			vod_item = VoDItem(url, name)
			self.vod_movies.append(vod_item)
		self.vod_movies.reverse()

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