from twisted.internet import threads
import twisted.python.runtime

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
		self.refresh_interval = 1  # used by M3UProvider, default here for Setup
		self.search_criteria = "tvg-id=\"{SID}\""  # used by M3UProvider, default here for Setup
		self.static_urls = False  # used by M3UProvider, default here for Setup
		self.username = ""  # used by XtreemProvider, default here for Setup
		self.password = ""  # used by XtreemProvider, default here for Setup
		self.vod_movies = [] # used by XtreemProvider, default here for Setup
		
	def getPlaylistAndGenBouquet(self, callback=None):
		if callback:
			threads.deferToThread(self.storePlaylistAndGenBouquet).addCallback(callback)
		else:
			self.storePlaylistAndGenBouquet()

	def storePlaylistAndGenBouquet(self):
		pass

	def getVoDMovies(self):
		pass

	def processService(self, nref, iptvinfodata, callback=None):
		return nref, nref, False
