from twisted.internet import threads

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
		self.create_groups = True
		self.refresh_interval = 1  # used by M3UProvider, default here for Setup
		self.search_criteria = "tvg-id=\"{SID}\""  # used by M3UProvider, default here for Setup
		self.static_urls = False  # used by M3UProvider, default here for Setup
		self.username = ""  # used by XtreemProvider, default here for Setup
		self.password = ""  # used by XtreemProvider, default here for Setup
		self.mac = ""  # used by StalkerProvider, default here for Setup
		self.vod_movies = []
		self.onBouquetCreated = []
		self.progress_percentage = -1
		
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
	
	def generateEPGImportFiles(self, groups):
		pass

	def generateEPGChannelReference(self, type, tsid):
		return "%s:0:%s:%x:%x:1:CCCC0000:0:0:0:http%3a//m3u.iptv.com" % (self.play_system, type, tsid, self.onid)
