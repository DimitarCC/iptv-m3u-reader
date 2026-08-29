class VodPager():
	"""Incrementally loads pages of VoD rows from a paginated source (e.g. a Stalker portal)."""

	# Enigma2 shows its own busy cursor for the duration of any outstanding deferToThread job, so the goal
	# isn't just "don't block the GUI thread" (fetches already run off-thread) - it's to keep enough pages
	# loaded ahead of the current selection that the user rarely scrolls onto a row whose fetch is still in
	# flight in the first place. PREFETCH_BUFFER is how many rows ahead of the selection should stay loaded;
	# refills happen one page at a time (the portal API is sequential/page-indexed) but are chained back to
	# back - each completed page immediately checks whether the buffer is still short and fetches the next.
	PREFETCH_BUFFER = 60

	def __init__(self, fetch_page):
		# fetch_page(page:int) -> (items:list, has_more:bool, total_items:int); may raise on network failure
		self.fetch_page = fetch_page
		self.items = []
		self.page = 0
		self.has_more = True
		self.loading = False
		self.failed = False
		self.total_items = 0

	def reset(self):
		self.items = []
		self.page = 0
		self.has_more = True
		self.loading = False
		self.failed = False
		self.total_items = 0

	def load_next_page_sync(self):
		"""Blocking fetch of the next page. Call from a background thread."""
		if self.loading or not self.has_more:
			return []
		self.loading = True
		try:
			page_items, has_more, total_items = self.fetch_page(self.page + 1)
			self.page += 1
			self.has_more = has_more
			self.items.extend(page_items)
			self.total_items = max(total_items, len(self.items))
			self.failed = False
			return page_items
		except Exception as err:
			print("[M3UIPTV][VodPager] failed to load page %d: %s" % (self.page + 1, err))
			self.failed = True
			return []
		finally:
			self.loading = False

	def placeholder_count(self):
		"""Number of not-yet-loaded rows still to come, based on the portal-reported total."""
		if not self.has_more:
			return 0
		return max(0, self.total_items - len(self.items))

	def should_prefetch(self, visible_index):
		return self.has_more and not self.loading and len(self.items) - visible_index < self.PREFETCH_BUFFER


class EagerPager():
	"""Wraps an already fully-loaded list (Xtream/M3U/VOD providers) behind the VodPager interface."""

	def __init__(self, items):
		self.items = items
		self.has_more = False
		self.loading = False
		self.failed = False

	def reset(self):
		pass

	def load_next_page_sync(self):
		return []

	def placeholder_count(self):
		return 0

	def should_prefetch(self, visible_index):
		return False
