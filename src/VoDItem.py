class VoDItem():
	def __init__(self, url, name, id, providerObj, category=None, plot=None, poster_url=None):
		self.url = url
		self.name = name
		self.id = id
		self.category = category
		self.plot = plot
		self.parent = None
		self.poster_url = poster_url
		self.providerObj = providerObj
