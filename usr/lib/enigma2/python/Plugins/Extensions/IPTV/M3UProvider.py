from Plugins.Extensions.IPTV.IPTVProcessor import IPTVProcessor

class M3UProvider(IPTVProcessor):
	def __init__(self):
		IPTVProcessor.__init__(self)
		self.last_exec = None
		self.playlist = None
		self.iptv_service_provider = ""
		self.url = ""
		self.offset = 1
		self.refresh_interval = -1
		self.search_criteria = ""
		self.scheme = ""