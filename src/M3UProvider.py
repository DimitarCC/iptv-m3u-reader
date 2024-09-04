from .IPTVProcessor import IPTVProcessor

class M3UProvider(IPTVProcessor):
	def __init__(self):
		IPTVProcessor.__init__(self)
		self.last_exec = None
		self.playlist = None
		self.iptv_service_provider = ""
		self.url = ""
		self.offset = 1
		self.refresh_interval = -1
		self.search_criteria = "tvg-id=\"{SID}\""
		self.scheme = ""
		self.play_system = "4097"
		self.static_urls = False
		self.ignore_vod = True
