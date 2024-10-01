class VoDItem():
	def __init__(self, url, name, category=None):
		self.url = url
		self.name = name
		self.parent = None
		self.category = category