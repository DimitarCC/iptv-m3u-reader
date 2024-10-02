class VoDItem():
	def __init__(self, url, name, category=None, plot=None, stream_icon=None):
		self.url = url
		self.name = name
		self.parent = None
		self.category = category
		self.plot = plot
		self.stream_icon = stream_icon
