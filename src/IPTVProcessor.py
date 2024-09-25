from twisted.internet import threads
from .epgimport_helper import epgimport_helper
from Tools.Directories import sanitizeFilename
import re


class IPTVProcessor():
	def __init__(self):
		self.type = "M3U" # default type M3U. Possible Types: M3U, Xtreem
		self.url = ""
		self.scheme = ""
		self.isPlayBackup = False
		self.play_system = "4097"
		self.ignore_vod = True 
		self.iptv_service_provider = ""
		self.last_exec = None
		self.create_epg = True
		self.refresh_interval = 1  # used by M3UProvider, default here for Setup
		self.search_criteria = "tvg-id=\"{SID}\""  # used by M3UProvider, default here for Setup
		self.static_urls = False  # used by M3UProvider, default here for Setup
		self.username = ""  # used by XtreemProvider, default here for Setup
		self.password = ""  # used by XtreemProvider, default here for Setup
		self.mac = ""  # used by StalkerProvider, default here for Setup
		self.vod_movies = []
		self.onBouquetCreated = []
		self.progress_percentage = -1
		self.update_status_callback = []  # for passing messages
		self.epg_url = ""
		
	def getPlaylistAndGenBouquet(self, callback=None):
		if callback:
			threads.deferToThread(self.storePlaylistAndGenBouquet).addCallback(callback)
		else:
			self.storePlaylistAndGenBouquet()

	def storePlaylistAndGenBouquet(self):
		pass

	def getVoDMovies(self):
		pass

	def loadVoDMoviesFromFile(self):
		pass

	def processService(self, nref, iptvinfodata, callback=None):
		return nref, nref, False
	
	def bouquetCreated(self, error):
		for f in self.onBouquetCreated:
			f(self, error)

	def generateChannelReference(self, type, tsid, url, name):
		return "%s:0:%s:%x:%x:1:CCCC0000:0:0:0:%s:%s•%s" % (self.play_system, type, tsid, self.onid, url.replace(":", "%3a"), name, self.iptv_service_provider)
	
	def getEpgUrl(self):
		return ""
	
	def generateEPGImportFiles(self, groups):
		if not self.create_epg:
			return
		epghelper = epgimport_helper(self)
		epghelper.createSourcesFile()
		epghelper.createChannelsFile(groups)

		epghelper.importepg()  # auto epg update after bouquet generation


	def generateEPGChannelReference(self, original_sref):
		return f"{':'.join(original_sref.split(':', 10)[:10])}:http%3a//m3u.iptv.com"
	
	def constructCatchupSufix(self, days, url, catchup_type):
		if days:
			captchup_addon = "%scatchuptype=%s&catchupdays=%s" % ("&" if "?" in url else "?", catchup_type, days)
			url += captchup_addon

	def removeBouquets(self):
		from enigma import eDVBDB
		search_bouquets_criteria = re.escape(sanitizeFilename(f"userbouquet.m3uiptv.{self.iptv_service_provider}.".replace(" ", "").replace("(", "").replace(")", "").replace("&", ""))) + r".*[.]tv"
		eDVBDB.getInstance().removeBouquet(search_bouquets_criteria)