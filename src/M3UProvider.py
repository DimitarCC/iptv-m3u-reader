from enigma import eServiceReference, eDVBDB
from ServiceReference import ServiceReference
from Components.config import config
from Tools.Directories import fileExists
from time import time
from twisted.internet import threads
import socket, urllib, re
from .IPTVProcessor import IPTVProcessor
from .Variables import CATCHUP_DEFAULT, CATCHUP_TYPES

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
		self.play_system_catchup = "4097"

	def getEpgUrlForSources(self):
		self.checkForNetwrok()
		req = self.constructRequest(self.url)
		req_timeout_val = config.plugins.m3uiptv.req_timeout.value
		if req_timeout_val != "off":
			response = urllib.request.urlopen(req, timeout=int(req_timeout_val))
		else:
			response = urllib.request.urlopen(req, timeout=10)  # set a timeout to prevent blocking
		playlist = response.read().decode('utf-8')
		self.playlist = playlist
		playlist_splitted = playlist.splitlines()
		for line in playlist_splitted:
			epg_match = self.searchForXMLTV(line)
			if epg_match:
				return epg_match.group(1)
		return self.getEpgUrl()
	
	def searchForXMLTV(self, line, isCustomUrl=False):
		epg_match = None
		if line.startswith("#EXTM3U") and not isCustomUrl:
			if "tvg-url" in line:
				epg_match = re.search(r"x-tvg-url=\"(.*?)\"", line, re.IGNORECASE) or re.search(r"tvg-url=\"(.*?)\"", line, re.IGNORECASE)
			elif "url-tvg" in line:
				epg_match = re.search(r"url-tvg=\"(.*?)\"", line, re.IGNORECASE)
		return epg_match

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
		line_nr = 0
		captchup_days = ""
		curr_group = None
		blacklist = self.readBlacklist()
		for line in playlist_splitted:
			if self.ignore_vod and "group-title=\"VOD" in line:
				continue
			epg_match = self.searchForXMLTV(line, self.is_custom_xmltv)
			if epg_match:
				self.epg_url = epg_match.group(1)
				self.is_dynamic_epg = not self.static_urls
			if line.startswith("#EXTINF:"):
				gr_match = re.search(r"group-title=\"(.*?)\"", line)
				if gr_match:
					curr_group = gr_match.group(1)
					if curr_group not in groups and self.create_bouquets_strategy != 1:
						groups[curr_group] = []
				else:
					curr_group = None
				epg_id = "None"
				epg_id_match = re.search(r"tvg-id=\"(.*?)\"", line, re.IGNORECASE)
				if epg_id_match:
					epg_id = epg_id_match.group(1)
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
					match = re.search(r"tvg-rec=\"(\d.*?)\"", line, re.IGNORECASE)
					if not match:
						match = re.search(r"catchup-days=\"(\d.*?)\"", line, re.IGNORECASE)
					if not match:
						match = re.search(r"timeshift=\"(\d.*?)\"", line, re.IGNORECASE)
					if match:
						captchup_days = match.group(1)
					if self.static_urls or self.isLocalPlaylist():
						found_url = False
						next_line_nr = line_nr + 1
						while not found_url:
							if len(playlist_splitted) > next_line_nr:
								next_line = playlist_splitted[next_line_nr].strip()
								if next_line.startswith("#EXTGRP:") and curr_group is None:  # only if no group was found in #EXTINF: group-title
									curr_group = next_line[8:].strip()
									if curr_group not in groups and self.create_bouquets_strategy != 1:
										groups[curr_group] = []
								if next_line.startswith(("http://", "https://")):
									url = next_line.replace(":", "%3a")
									url = self.constructCatchupSuffix(captchup_days, url, CATCHUP_TYPES[self.catchup_type])
									captchup_days = ""
									found_url = True
								else:
									next_line_nr += 1
							else:
								break
					else:
						url = self.scheme + "%3a//" + sid
						url = self.constructCatchupSuffix(captchup_days, url, CATCHUP_TYPES[self.catchup_type])
						captchup_days = ""
					stype = "1"
					if "UHD" in ch_name or "4K" in ch_name:
						stype = "1F"
					elif "HD" in ch_name:
						stype = "19"
					sref = self.generateChannelReference(stype, tsid, url.replace(":", "%3a"), ch_name)
					tsid += 1
					if self.create_bouquets_strategy != 1:
						if curr_group:
							groups[curr_group].append((sref, epg_id, ch_name))
						else:
							services.append((sref, epg_id, ch_name))
					if self.create_bouquets_strategy > 0:
						if (curr_group and curr_group not in blacklist) or not curr_group:
							groups["ALL"].append((sref, epg_id, ch_name))
					if "tvg-logo" in line and (stream_icon_match := re.search(r"tvg-logo=\"(.+?)\"", line, re.IGNORECASE)):
						self.piconsAdd(stream_icon_match.group(1), ch_name)
			line_nr += 1

		examples = []

		groups_for_epg = {}  # mimic format used in XtreemProvider.py
		for groupName, srefs in groups.items():
			if groupName != "ALL":
				examples.append(groupName)
			if len(srefs) > 0:
				bfilename = self.cleanFilename(f"userbouquet.m3uiptv.{self.scheme}.{groupName}.tv")
				if groupName in blacklist:
					self.removeBouquet(bfilename)  # remove blacklisted bouquet if already exists
					continue
				bouquet_name = self.iptv_service_provider.upper() + " - " + groupName
				if self.create_bouquets_strategy == 1:
					bouquet_name = self.iptv_service_provider.upper()
				db.addOrUpdateBouquet(bouquet_name, bfilename, [sref[0] for sref in srefs], False)
				groups_for_epg[groupName] = (groupName, srefs)

		if len(services) > 0:
			if len(groups) > 0:
				examples.append("UNCATEGORIZED")
				bfilename = self.cleanFilename(f"userbouquet.m3uiptv.{self.scheme}.UNCATEGORIZED.tv")
				if "UNCATEGORIZED" in blacklist:
					self.removeBouquet(bfilename)  # remove blacklisted bouquet if already exists
				else:
					db.addOrUpdateBouquet(self.iptv_service_provider.upper() + " - UNCATEGORIZED", bfilename, [sref[0] for sref in services], False)
			else:
				bfilename = self.cleanFilename(f"userbouquet.m3uiptv.{self.scheme}.tv")
				db.addOrUpdateBouquet(self.iptv_service_provider.upper(), bfilename, [sref[0] for sref in services], False)
			groups_for_epg["EMPTY"] = ("UNCATEGORIZED", services)
		self.writeExampleBlacklist(examples)
		self.piconsDownload()
		self.generateEPGImportFiles(groups_for_epg)
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
			match_backup = re.search(r"backupref=\"(.*?)\"", iptvInfoDataSplit[1])
			if match_backup:
				backup_ref = match_backup.group(1).replace("%3a", ":")
		except:
			pass
		if callback:
			threads.deferToThread(self.processDownloadPlaylist, nref, channelForSearch, origRef, iptvinfodata, backup_ref, orig_name, event).addCallback(callback)
		else:
			return self.processDownloadPlaylist(nref, channelForSearch, origRef, iptvinfodata, backup_ref, orig_name, event), nref, False
		return nref, nref, True

	def processDownloadPlaylist(self, nref, channelForSearch, origRef, iptvinfodata, backup_ref, orig_name, event=None):
		try:
			self.checkForNetwrok()
			channelForSearch = channelForSearch.replace("%3a", ":")
			channelSID = self.search_criteria.replace("{SID}", channelForSearch)
			prov = self
			cache_time = 0
			if prov.refresh_interval > -1:
				cache_time = int(prov.refresh_interval * 60 * 60)
			nref_new = nref.toString()
			cur_time = time()
			time_delta = prov.last_exec and cur_time - prov.last_exec or None
			if (prov.refresh_interval == -1 and prov.playlist) or (prov.refresh_interval > 0 and time_delta and time_delta < cache_time):
				playlist = prov.playlist
			else:
				req = self.constructRequest(prov.url)
				req_timeout_val = config.plugins.m3uiptv.req_timeout.value
				if req_timeout_val != "off":
					response = urllib.request.urlopen(req, timeout=int(req_timeout_val))
				else:
					response = urllib.request.urlopen(req, timeout=10)  # set a timeout to prevent blocking
				playlist = response.read().decode('utf-8')
				prov.playlist = playlist
				if cache_time > 0:
					prov.last_exec = cur_time

			findurl = False
			catchup_source = ""
			for line in playlist.splitlines():
				line = line.strip()  # just in case there is surrounding white space present
				if line.startswith("#EXTINF"):
					findurl = (channelSID in line) or (("," + channelForSearch) in line)
					match = re.search(r"catchup-source=\"(.*?)\"", line, re.IGNORECASE)
					if match:
						catchup_source = match.group(1)
					else:
						catchup_source = ""
					if event and catchup_source and findurl:
						nref_new = origRef + ":" + catchup_source.replace(":", "%3a")
						break
				elif findurl and line.startswith(("http://", "https://")):
					match = re.search(r"catchupdays=(\d.*?)", iptvinfodata)
					catchup_days = ""
					if match:
						catchup_days = match.group(1)
					iptv_url = line.replace(":", "%3a")
					iptv_url = self.constructCatchupSuffix(catchup_days, iptv_url, CATCHUP_TYPES[self.catchup_type])
					nref_new = origRef + ":" + iptv_url + ":" + orig_name + "•" + prov.iptv_service_provider
					break
			self.nnref = eServiceReference(nref_new)
			self.isPlayBackup = False
			return self.nnref  # , nref
		except Exception as ex:
			print("[M3UIPTV] [M3U] Error downloading playlist: " + str(ex))
			self.isPlayBackup = True
			self.nnref = eServiceReference(backup_ref + ":")
			return self.nnref  # , nref
