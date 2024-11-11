from os import listdir, path, readlink, remove, symlink, makedirs as os_makedirs
from requests import get, exceptions
from shutil import rmtree
import threading
from time import sleep

from .Variables import USER_AGENT


def getPiconPath():
	try:
		from Components.Renderer.Picon import lastPiconPath
	except ImportError:
		try:
			from Components.Renderer.Picon import piconLocator
			lastPiconPath = piconLocator.activePiconPath
		except ImportError:
			lastPiconPath = None
	return lastPiconPath or "/picon"


class Fetcher():
	def __init__(self, provider):
		self.piconDir = getPiconPath()
		self.provider = provider
		self.pluginPiconDir = path.join(self.piconDir, "m3uiptv", self.provider.scheme)
		self.downloaded = []
		self.maxthreads = 500  # max simultaneous requests
		
	def downloadURL(self, url, success, fail=None):
		try:
			file = self.provider.picon_database[url][0] + ".png"
			if not path.exists(piconname := path.join(self.pluginPiconDir, file)):
				response = get(url, timeout=2.50, headers={"User-Agent": USER_AGENT})
				response.raise_for_status()
				if response.headers['content-type'] != 'image/png':
					if callable(fail):
						fail("Wrong content type: %s , Link: %s" % (response.headers['content-type'], url))
					return
				with open(piconname, "wb") as f:
					f.write(response.content)
			success((url, file))
		except exceptions.RequestException as error:
			if callable(fail):
				fail(error)

	def fetchall(self):
		os_makedirs(self.pluginPiconDir, exist_ok=True)
		if self.provider.picon_database:
			database = list(self.provider.picon_database.keys())
			for i in range(len(self.provider.picon_database) // self.maxthreads + 1):  # split downloads in batches of "maxthreads"
				threads = [threading.Thread(target=self.downloadURL, args=(url, self.success, self.failure)) for url in database[i*self.maxthreads:i*self.maxthreads+self.maxthreads]]
				for thread in threads:
					try:
						thread.start()
					except RuntimeError:
						sleep(10)
						thread.start()
				for thread in threads:
					thread.join()
		print("[Fetcher] all fetched")

	def success(self, file):
		self.downloaded.append(file)

	def failure(self, error):
		print("[Fetcher] Error: %s" % error)

	def createSoftlinks(self):
		for url, file in self.downloaded:
			filepath = path.join(self.pluginPiconDir, file)
			for ch_name in self.provider.picon_database[url]:
				softlinkpath = path.join(self.piconDir, ch_name + ".png")
				islink = path.islink(softlinkpath)
				if not islink and path.isfile(softlinkpath):  # isfile follows symbolic links so we need to check this is not a symbolic link first
					continue  # if a file exists here don't touch it, it is not ours
				if islink:
					if readlink(softlinkpath) == filepath:
						continue
					remove(softlinkpath)
				symlink(filepath, softlinkpath)

	def removeall(self):
		for f in listdir(self.piconDir):
			item = path.join(self.piconDir, f)
			if path.islink(item) and self.pluginPiconDir in readlink(item):
				remove(item)
		rmtree(self.pluginPiconDir)
