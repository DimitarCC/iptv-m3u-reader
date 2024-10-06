from enigma import eServiceReference, eDVBDB
from ServiceReference import ServiceReference
from Components.config import config
from time import time
from twisted.internet import threads
from Tools.Directories import sanitizeFilename
import socket
import urllib
import re
from .IPTVProcessor import IPTVProcessor
from .Variables import USER_AGENT, CATCHUP_DEFAULT, CATCHUP_DEFAULT_TEXT, CATCHUP_TYPES

db = eDVBDB.getInstance()

class M3UProvider(IPTVProcessor):
	def __init__(self):
		IPTVProcessor.__init__(self)
		self.playlist = None
		self.isPlayBackup = False
		self.offset = 0
		self.progress_percentage = -1
		self.create_epg = True
		self.catchup_type = CATCHUP_DEFAULT
		self.play_system_vod = "4097"
		self.play_system_catchup = self.play_system
		
	def storePlaylistAndGenBouquet(self):
		is_check_network_val = config.plugins.m3uiptv.check_internet.value
		if is_check_network_val != "off":
			socket.setdefaulttimeout(int(is_check_network_val))
			socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("8.8.8.8", 53))
		req = urllib.request.Request(self.url, headers={'User-Agent' : USER_AGENT}) 
		req_timeout_val = config.plugins.m3uiptv.req_timeout.value
		if req_timeout_val != "off":
			response = urllib.request.urlopen(req, timeout=int(req_timeout_val))
		else:
			response = urllib.request.urlopen(req)
		playlist = response.read().decode('utf-8')
		self.playlist = playlist
		playlist_splitted = playlist.splitlines()
		tsid = 1000
		services = []
		groups = {}
		line_nr = 0
		captchup_days = ""
		curr_group = None
		for line in playlist_splitted:
			if self.ignore_vod and "group-title=\"VOD" in line:
				continue
			if line.startswith("#EXTINF:"):
				gr_match  = re.search(r"group-title=\"(.*)\"", line)
				if gr_match:
					curr_group = gr_match.group(1)
					if curr_group not in groups:
						groups[curr_group] = []
				else:
					curr_group = None
				condition = re.escape(self.search_criteria).replace("\\{SID\\}", "(.*?)") + r".*,(.*)"
				match = re.search(condition, line)
				isFallbackMatch = False
				if not match:
					# Probably the format of the playlist is not m3u+ or for some reason it doesnt contain
					# tvg-id, tvg-name and other similar tags. In this case try matching by the name of service
					condition = r".*,(.*)"
					match = re.search(condition, line)
					isFallbackMatch = True
				if match:
					sid = match.group(1).replace(":", "%3a")
					ch_name = match.group(2) if not isFallbackMatch else sid
					if not sid:
						sid = ch_name.replace(":", "%3a")
					url = ""
					match = re.search(r".*tvg-rec=\"(\d*)\".*", line)
					if match:
						captchup_days = match.group(1)
					if self.static_urls:
						found_url = False
						next_line_nr = line_nr + 1
						while not found_url:
							if len(playlist_splitted) > next_line_nr:
								next_line = playlist_splitted[next_line_nr].strip()
								if next_line.startswith(("http://", "https://")):
									url = next_line.replace(":", "%3a")
									url = self.constructCatchupSufix(captchup_days, url, CATCHUP_TYPES[self.catchup_type])
									captchup_days = ""
									found_url = True
								else:
									next_line_nr += 1
							else:
								break
					else:
						url = self.scheme + "%3a//" + sid
						url = self.constructCatchupSufix(captchup_days, url, CATCHUP_TYPES[self.catchup_type])
						captchup_days = ""
					stype = "1"
					if "UHD" in ch_name or "4K" in ch_name:
						stype = "1F"
					elif "HD" in ch_name:
						stype = "19"
					sref = self.generateChannelReference(stype, tsid, url.replace(":", "%3a"), ch_name)
					tsid += 1
					if curr_group:
						groups[curr_group].append(sref)
					else:
						services.append(sref)
			line_nr += 1
		for groupName, srefs in groups.items():
			if len(srefs) > 0:
				bfilename =  sanitizeFilename(f"userbouquet.m3uiptv.{self.iptv_service_provider}.{groupName}.tv".replace(" ", "").replace("(", "").replace(")", "").replace("&", ""))
				db.addOrUpdateBouquet(self.iptv_service_provider.upper() + " - " + groupName, bfilename, srefs, False)

		if len(services) > 0:
			if len(groups) > 0:
				bfilename =  sanitizeFilename(f"userbouquet.m3uiptv.{self.iptv_service_provider}.UNCATEGORIZED.tv".replace(" ", "").replace("(", "").replace(")", "").replace("&", ""))
				db.addOrUpdateBouquet(self.iptv_service_provider.upper() + " - UNCATEGORIZED", bfilename, services, False)
			else:
				db.addOrUpdateBouquet(self.iptv_service_provider, services, 1)
		self.bouquetCreated(None)

	def processService(self, nref, iptvinfodata, callback=None, event=None):
		splittedRef = nref.toString().split(":")
		sRef = nref and ServiceReference(nref.toString())
		origRef = ":".join(splittedRef[:10])
		iptvInfoDataSplit = iptvinfodata.split("?")
		channelForSearch = iptvInfoDataSplit[0].split(":")[0]
		orig_name = sRef and sRef.getServiceName()
		backup_ref = nref.toString()
		try:
			backup_ref = iptvinfodata[1].split(":")[0].replace("%3a", ":")
		except:
			pass
		if callback:
			threads.deferToThread(self.processDownloadPlaylist, nref, channelForSearch, origRef, backup_ref, orig_name, event).addCallback(callback)
		else:
			return self.processDownloadPlaylist(nref, channelForSearch, origRef, backup_ref, orig_name, event) , nref, False
		return nref, nref, True
		
	def processDownloadPlaylist(self, nref, channelForSearch, origRef, backup_ref, orig_name, event=None):
		try:
			is_check_network_val = config.plugins.m3uiptv.check_internet.value
			if is_check_network_val != "off":
				socket.setdefaulttimeout(int(is_check_network_val))
				socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("8.8.8.8", 53))
			channelForSearch = channelForSearch.replace("%3a", ":")
			channelSID = self.search_criteria.replace("{SID}", channelForSearch)
			prov = self
			cache_time = 0
			if prov.refresh_interval > -1:
				cache_time = int(prov.refresh_interval * 60 * 60)
			nref_new = nref.toString()
			cur_time = time()
			time_delta = prov.last_exec and cur_time - prov.last_exec or None
			if (prov.refresh_interval == -1 and prov.playlist) or (prov.refresh_interval > 0 and time_delta and  time_delta < cache_time):
				playlist = prov.playlist
			else:
				req = urllib.request.Request(prov.url, headers={'User-Agent' : "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36 Edg/127.0.0.0"}) 
				req_timeout_val = config.plugins.m3uiptv.req_timeout.value
				if req_timeout_val != "off":
					response = urllib.request.urlopen(req, timeout=int(req_timeout_val))
				else:
					response = urllib.request.urlopen(req)
				playlist = response.read().decode('utf-8')
				prov.playlist = playlist
				if cache_time > 0:
					prov.last_exec = cur_time

			findurl = False
			catchup_source = ""
			for line in playlist.splitlines():
				line = line.strip()  # just in case there is surrounding white space present
				if line.startswith("#EXTINF:"):
					findurl = (channelSID in line) or (("," + channelForSearch) in line)
					match = re.search(r"catchup-source=\"(.*)\"\scatchup-days=", line)
					if match:
						catchup_source = match.groups(1)[0]
					else:
						catchup_source = ""
				elif findurl and line.startswith(("http://", "https://")):
					if event and catchup_source:
						iptv_url = catchup_source.replace(":", "%3a")
					else:
						iptv_url = line.replace(":", "%3a")
					nref_new = origRef + ":" + iptv_url + ":" + orig_name + "•" + prov.iptv_service_provider
					break
			self.nnref = eServiceReference(nref_new)
			self.isPlayBackup = False
			return self.nnref#, nref
		except Exception as ex:
			print("[M3UIPTV] [M3U] Error downloading playlist: " + str(ex))
			self.isPlayBackup = True
			self.nnref = eServiceReference(backup_ref + ":")
			return self.nnref#, nref