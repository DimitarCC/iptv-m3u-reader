from enigma import eDVBDB
from Components.config import config
import twisted.python.runtime
import socket
import urllib
import json
from .IPTVProcessor import IPTVProcessor
from .VoDItem import VoDItem

db = eDVBDB.getInstance()

class XtreemProvider(IPTVProcessor):
	def __init__(self):
		IPTVProcessor.__init__(self)
		self.type = "Xtreem"
		self.refresh_interval = -1
		self.vod_movies = []
		
	def storePlaylistAndGenBouquet(self):
		is_check_network_val = config.plugins.m3uiptv.check_internet.value
		if is_check_network_val != "off":
			socket.setdefaulttimeout(int(is_check_network_val))
			socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("8.8.8.8", 53))
		url = "%s/player_api.php?username=%s&password=%s&action=get_live_streams" % (self.url, self.username, self.password)
		req = urllib.request.Request(url, headers={'User-Agent' : "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36 Edg/127.0.0.0"}) 
		req_timeout_val = config.plugins.m3uiptv.req_timeout.value
		if req_timeout_val != "off":
			response = urllib.request.urlopen(req, timeout=int(req_timeout_val))
		else:
			response = urllib.request.urlopen(req)
		services_response = response.read()
		services_json_obj = json.loads(services_response)
		tsid = 1000
		services = []
		for service in services_json_obj:
			surl = "%s/live/%s/%s/%s.%s" % (self.url, self.username, self.password, service["stream_id"], "ts" if self.play_system == "1" else "m3u8")
			ch_name = service["name"].replace(":", "|")
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

	def getVoDMovies(self):
		is_check_network_val = config.plugins.m3uiptv.check_internet.value
		if is_check_network_val != "off":
			socket.setdefaulttimeout(int(is_check_network_val))
			socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("8.8.8.8", 53))
		url = "%s/player_api.php?username=%s&password=%s&action=get_vod_streams" % (self.url, self.username, self.password)
		req = urllib.request.Request(url, headers={'User-Agent' : "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36 Edg/127.0.0.0"}) 
		req_timeout_val = config.plugins.m3uiptv.req_timeout.value
		if req_timeout_val != "off":
			response = urllib.request.urlopen(req, timeout=int(req_timeout_val))
		else:
			response = urllib.request.urlopen(req)
		vod_response = response.read()
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