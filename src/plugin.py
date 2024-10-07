# for localized messages
from . import _

from sys import modules
from time import time
from glob import glob
import json
import base64
from enigma import eServiceCenter, eServiceReference, eTimer, getBestPlayableServiceReference, setPreferredTuner
from Plugins.Plugin import PluginDescriptor
from .M3UProvider import M3UProvider
from .IPTVProcessor import IPTVProcessor
from .XtreemProvider import XtreemProvider
from .StalkerProvider import StalkerProvider
from .IPTVProviders import providers, processService as processIPTVService
from .IPTVCatchupPlayer import injectCatchupInEPG
from .epgimport_helper import overwriteEPGImportInit
from .Variables import USER_IPTV_PROVIDERS_FILE, CATCHUP_DEFAULT, CATCHUP_APPEND, CATCHUP_SHIFT, CATCHUP_XTREME, CATCHUP_STALKER
from Screens.Screen import Screen, ScreenSummary
from Screens.InfoBar import InfoBar, MoviePlayer
from Screens.InfoBarGenerics import streamrelay, saveResumePoints, resumePointCache, resumePointCacheLast, delResumePoint
from Screens.PictureInPicture import PictureInPicture
from Screens.Setup import Setup
from Screens.Menu import Menu
from Screens.MessageBox import MessageBox
from Screens.VirtualKeyBoard import VirtualKeyBoard
from Components.ActionMap import ActionMap
from Components.config import config, ConfigSubsection, ConfigYesNo, ConfigSelection, ConfigText, ConfigPassword
from Components.ParentalControl import parentalControl
from Components.Sources.StaticText import StaticText
from Components.Sources.List import List
from Components.Sources.Progress import Progress
from Components.SystemInfo import SystemInfo
from Tools.Directories import fileExists, isPluginInstalled
from Tools.BoundFunction import boundFunction
from Navigation import Navigation

try:
	from Plugins.Extensions.tmdb.tmdb import tmdbScreen, tmdbScreenMovie, tempDir as tmdbTempDir, tmdb
except ImportError:
	tmdbScreen = None
	try:
		from Plugins.Extensions.IMDb.plugin import IMDB
	except ImportError:
		IMDB = None

from os import path, fsync, rename, makedirs, remove
import xml
from xml.etree.cElementTree import iterparse
import re

import threading
write_lock = threading.Lock()

config.plugins.m3uiptv = ConfigSubsection()
config.plugins.m3uiptv.enabled = ConfigYesNo(default=True)
choicelist = [("off", _("off"))] + [(str(i), ngettext("%d second", "%d seconds", i) % i) for i in [1, 2, 3, 5, 7, 10]] 
config.plugins.m3uiptv.check_internet = ConfigSelection(default="2", choices=choicelist)
config.plugins.m3uiptv.req_timeout = ConfigSelection(default="2", choices=choicelist)
config.plugins.m3uiptv.inmenu = ConfigYesNo(default=True)


file = open("%s/menu.xml" % path.dirname(modules[__name__].__file__), 'r')
mdom = xml.etree.cElementTree.parse(file)
file.close()

file_vod = open("%s/vod_menu.xml" % path.dirname(modules[__name__].__file__), 'r')
mdom_vod = xml.etree.cElementTree.parse(file_vod)
file_vod.close()


def tmdbScreenMovieHelper(VoDObj):
	url = "%s/player_api.php?username=%s&password=%s&action=get_vod_info&vod_id=%s" % (VoDObj.providerObj.url, VoDObj.providerObj.username, VoDObj.providerObj.password, VoDObj.id)
	if json_string := VoDObj.providerObj.getUrl(url):
		if json_obj := json.loads(json_string):
			if info := json_obj.get('info'):
				tmdb_id = info.get('tmdb_id') and str(info.get('tmdb_id'))
				if cover := info.get('cover_big') or json_obj.get('movie_image'):
					cover = cover.rsplit("/", 1)[-1]
				if backdrop := info.get('backdrop_path'):
					if isinstance(backdrop, list):
						backdrop = backdrop[0]
					backdrop = backdrop.rsplit("/", 1)[-1]
				if tmdb_id and cover and backdrop:
					url_cover = "http://image.tmdb.org/t/p/%s/%s" % (config.plugins.tmdb.themoviedb_coversize.value, cover)
					url_backdrop = "http://image.tmdb.org/t/p/%s/%s" % (config.plugins.tmdb.themoviedb_coversize.value, backdrop)
					tmdb.API_KEY = base64.b64decode('ZDQyZTZiODIwYTE1NDFjYzY5Y2U3ODk2NzFmZWJhMzk=')
					return (VoDObj.name, "movie", tmdbTempDir + tmdb_id + ".jpg", tmdb_id, 2, url_backdrop), url_cover


def readProviders():
	if not fileExists(USER_IPTV_PROVIDERS_FILE):
		return
	fd = open(USER_IPTV_PROVIDERS_FILE, 'rb')
	for prov, elem in iterparse(fd):
		if elem.tag == "providers":
			for provider in elem.findall("provider"):
				providerObj = M3UProvider()
				providerObj.iptv_service_provider = provider.find("servicename").text
				providerObj.url = provider.find("url").text
				providerObj.refresh_interval = int(provider.find("refresh_interval").text)
				providerObj.search_criteria = provider.find("filter").text
				providerObj.scheme = provider.find("scheme").text
				providerObj.play_system = provider.find("system").text
				providerObj.play_system_catchup = provider.find("system_catchup").text if provider.find("system_catchup") is not None else providerObj.play_system
				providerObj.catchup_type = int(provider.find("catchup_type").text) if provider.find("catchup_type") is not None else str(CATCHUP_DEFAULT)
				providerObj.ignore_vod = provider.find("novod") is not None and provider.find("novod").text == "on"
				providerObj.static_urls = provider.find("staticurl") is not None and provider.find("staticurl").text == "on"
				providerObj.onid = int(provider.find("onid").text)
				providerObj.create_epg = provider.find("epg") is not None and provider.find("epg").text == "on"
				providerObj.epg_url = provider.find("epg_url").text if provider.find("epg_url") is not None else providerObj.epg_url
				providers[providerObj.scheme] = providerObj
			for provider in elem.findall("xtreemprovider"):
				providerObj = XtreemProvider()
				providerObj.type = "Xtreeme"
				providerObj.scheme = provider.find("scheme").text
				providerObj.iptv_service_provider = provider.find("servicename").text
				providerObj.url = provider.find("url").text
				providerObj.refresh_interval = int(provider.find("refresh_interval").text)
				providerObj.username = provider.find("username").text
				providerObj.password = provider.find("password").text
				providerObj.play_system = provider.find("system").text
				providerObj.play_system_catchup = provider.find("system_catchup").text if provider.find("system_catchup") is not None else providerObj.play_system
				providerObj.create_epg = provider.find("epg") is not None and provider.find("epg").text == "on"
				providerObj.ignore_vod = provider.find("novod") is not None and provider.find("novod").text == "on"
				providerObj.onid = int(provider.find("onid").text)
				if not providerObj.ignore_vod:
					providerObj.loadMovieCategoriesFromFile()
					providerObj.loadVoDMoviesFromFile()
					providerObj.loadVoDSeriesFromFile()
				providers[providerObj.scheme] = providerObj
			for provider in elem.findall("stalkerprovider"):
				providerObj = StalkerProvider()
				providerObj.type = "Stalker"
				providerObj.scheme = provider.find("scheme").text
				providerObj.iptv_service_provider = provider.find("servicename").text
				providerObj.url = provider.find("url").text
				providerObj.refresh_interval = int(provider.find("refresh_interval").text)
				providerObj.mac = provider.find("mac").text
				providerObj.play_system = provider.find("system").text
				providerObj.play_system_catchup = provider.find("system_catchup").text if provider.find("system_catchup") is not None else providerObj.play_system
				providerObj.create_epg = provider.find("epg") is not None and provider.find("epg").text == "on"
				providerObj.ignore_vod = provider.find("novod") is not None and provider.find("novod").text == "on"
				providerObj.onid = int(provider.find("onid").text)
				if not providerObj.ignore_vod:
					providerObj.loadVoDMoviesFromFile()
					providerObj.loadVoDSeriesFromFile()
				providers[providerObj.scheme] = providerObj
	fd.close()

def writeProviders():
	xml = []
	xml.append("<providers>\n")
	for key, val in providers.items():
		if isinstance(val, M3UProvider):
			xml.append("\t<provider>\n")
			xml.append(f"\t\t<servicename>{val.iptv_service_provider}</servicename>\n")
			xml.append(f"\t\t<url><![CDATA[{val.url}]]></url>\n")
			xml.append(f"\t\t<refresh_interval>{val.refresh_interval}</refresh_interval>\n")
			xml.append(f"\t\t<novod>{'on' if val.ignore_vod else 'off'}</novod>\n")
			xml.append(f"\t\t<staticurl>{'on' if val.static_urls else 'off'}</staticurl>\n")
			xml.append(f"\t\t<filter>{val.search_criteria}</filter>\n")
			xml.append(f"\t\t<scheme><![CDATA[{val.scheme}]]></scheme>\n")
			xml.append(f"\t\t<system>{val.play_system}</system>\n")
			xml.append(f"\t\t<system_catchup>{val.play_system_catchup}</system_catchup>\n")
			xml.append(f"\t\t<catchup_type>{val.catchup_type}</catchup_type>\n")
			xml.append(f"\t\t<onid>{val.onid}</onid>\n")
			xml.append(f"\t\t<epg>{'on' if val.create_epg else 'off'}</epg>\n")
			xml.append(f"\t\t<epg_url><![CDATA[{val.epg_url}]]></epg_url>\n")
			xml.append("\t</provider>\n")
		elif isinstance(val, XtreemProvider):
			xml.append("\t<xtreemprovider>\n")
			xml.append(f"\t\t<servicename>{val.iptv_service_provider}</servicename>\n")
			xml.append(f"\t\t<url><![CDATA[{val.url}]]></url>\n")
			xml.append(f"\t\t<refresh_interval>{val.refresh_interval}</refresh_interval>\n")
			xml.append(f"\t\t<novod>{'on' if val.ignore_vod else 'off'}</novod>\n")
			xml.append(f"\t\t<groups>{'on' if val.ignore_vod else 'off'}</groups>\n")
			xml.append(f"\t\t<username><![CDATA[{val.username}]]></username>\n")
			xml.append(f"\t\t<password><![CDATA[{val.password}]]></password>\n")
			xml.append(f"\t\t<scheme><![CDATA[{val.scheme}]]></scheme>\n")
			xml.append(f"\t\t<system>{val.play_system}</system>\n")
			xml.append(f"\t\t<system_catchup>{val.play_system_catchup}</system_catchup>\n")
			xml.append(f"\t\t<epg>{'on' if val.create_epg else 'off'}</epg>\n")
			xml.append(f"\t\t<onid>{val.onid}</onid>\n")
			xml.append("\t</xtreemprovider>\n")
		else:
			xml.append("\t<stalkerprovider>\n")
			xml.append(f"\t\t<servicename>{val.iptv_service_provider}</servicename>\n")
			xml.append(f"\t\t<url><![CDATA[{val.url}]]></url>\n")
			xml.append(f"\t\t<refresh_interval>{val.refresh_interval}</refresh_interval>\n")
			xml.append(f"\t\t<novod>{'on' if val.ignore_vod else 'off'}</novod>\n")
			xml.append(f"\t\t<groups>{'on' if val.ignore_vod else 'off'}</groups>\n")
			xml.append(f"\t\t<mac>{val.mac}</mac>\n")
			xml.append(f"\t\t<scheme><![CDATA[{val.scheme}]]></scheme>\n")
			xml.append(f"\t\t<system>{val.play_system}</system>\n")
			xml.append(f"\t\t<system_catchup>{val.play_system_catchup}</system_catchup>\n")
			xml.append(f"\t\t<epg>{'on' if val.create_epg else 'off'}</epg>\n")
			xml.append(f"\t\t<onid>{val.onid}</onid>\n")
			xml.append("\t</stalkerprovider>\n")
	xml.append("</providers>\n")
	makedirs(path.dirname(USER_IPTV_PROVIDERS_FILE), exist_ok=True)  # create config folder recursive if not exists
	with write_lock:
		f = open(USER_IPTV_PROVIDERS_FILE + ".writing", 'w')
		f.write("".join(xml))
		f.flush()
		fsync(f.fileno())
		f.close()
		rename(USER_IPTV_PROVIDERS_FILE + ".writing", USER_IPTV_PROVIDERS_FILE)


# Function for overwrite some functions from Navigation.py so to inject own code
def injectIntoNavigation():
	import NavigationInstance
	NavigationInstance.instance.playService  = playServiceWithIPTV.__get__(NavigationInstance.instance, Navigation)
	NavigationInstance.instance.playRealService = playRealService.__get__(NavigationInstance.instance, Navigation)
	NavigationInstance.instance.recordService = recordServiceWithIPTV.__get__(NavigationInstance.instance, Navigation)
	PictureInPicture.playService = playServiceWithIPTVPiP
	injectCatchupInEPG()
	overwriteEPGImportInit()
	

def playServiceWithIPTVPiP(self, service):
		if service is None:
			return False
		from Screens.InfoBarGenerics import streamrelay
		from .IPTVProviders import processService
		ref = streamrelay.streamrelayChecker(service)
		ref = processService(ref, None)[0]
		if ref:
			if SystemInfo["CanNotDoSimultaneousTranscodeAndPIP"] and StreamServiceList:
				self.pipservice = None
				self.currentService = None
				self.currentServiceReference = None
				if not config.usage.hide_zap_errors.value:
					Tools.Notifications.AddPopup(text="PiP...\n" + _("Connected transcoding, limit - no PiP!"), type=MessageBox.TYPE_ERROR, timeout=5, id="ZapPipError")
				return False
			#if ref.toString().startswith("4097"):		#  Change to service type 1 and try to play a stream as type 1
			#	ref = eServiceReference("1" + ref.toString()[4:])
			if not self.isPlayableForPipService(ref):
				if not config.usage.hide_zap_errors.value:
					Tools.Notifications.AddPopup(text="PiP...\n" + _("No free tuner!"), type=MessageBox.TYPE_ERROR, timeout=5, id="ZapPipError")
				return False
			print("[PictureInPicture] playing pip service", ref and ref.toString())
			self.pipservice = eServiceCenter.getInstance().play(ref)
			if self.pipservice and not self.pipservice.setTarget(1, True):
				if hasattr(self, "dishpipActive") and self.dishpipActive is not None:
					self.dishpipActive.startPiPService(ref)
				self.pipservice.start()
				self.currentService = service
				self.currentServiceReference = ref
				return True
			else:
				self.pipservice = None
				self.currentService = None
				self.currentServiceReference = None
				if not config.usage.hide_zap_errors.value:
					Tools.Notifications.AddPopup(text=_("Incorrect service type for PiP!"), type=MessageBox.TYPE_ERROR, timeout=5, id="ZapPipError")
		return False


def playServiceWithIPTV(self, ref, checkParentalControl=True, forceRestart=False, adjust=True, event=None):
	from Components.ServiceEventTracker import InfoBarCount
	InfoBarInstance = InfoBarCount == 1 and InfoBar.instance
	
	oldref = self.currentlyPlayingServiceOrGroup
	if "%3a//" in ref.toString():
		self.currentlyPlayingServiceReference = None
		self.currentlyPlayingServiceOrGroup = None
		self.currentlyPlayingService = None
		if InfoBarInstance:
			InfoBarInstance.session.screen["CurrentService"].newService(False)
	if ref and oldref and ref == oldref and not forceRestart:
		print("[Navigation] ignore request to play already running service(1)")
		return 1
	print("[Navigation] playing ref", ref and ref.toString())

	if path.exists("/proc/stb/lcd/symbol_signal") and hasattr(config.lcd, "mode"):
		open("/proc/stb/lcd/symbol_signal", "w").write("1" if ref and "0:0:0:0:0:0:0:0:0" not in ref.toString() and config.lcd.mode.value else "0")

	if ref is None:
		self.stopService() 
		return 0
		
	self.currentlyPlayingServiceReference = ref
	self.currentlyPlayingServiceOrGroup = ref
	
	if InfoBarInstance:
		InfoBarInstance.session.screen["CurrentService"].newService(ref)
		InfoBarInstance.session.screen["Event_Now"].updateSource(ref)
		InfoBarInstance.session.screen["Event_Next"].updateSource(ref)
		InfoBarInstance.serviceStarted()
		
	if not checkParentalControl or parentalControl.isServicePlayable(ref, boundFunction(self.playService, checkParentalControl=False, forceRestart=forceRestart, adjust=adjust)):
		if ref.flags & eServiceReference.isGroup:
			oldref = self.currentlyPlayingServiceReference or eServiceReference()
			playref = getBestPlayableServiceReference(ref, oldref)
			print("[Navigation] playref", playref)
			if playref and oldref and playref == oldref and not forceRestart:
				print("[Navigation] ignore request to play already running service(2)")
				return 1
			if not playref:
				alternativeref = getBestPlayableServiceReference(ref, eServiceReference(), True)
				self.stopService()
				if alternativeref and self.pnav:
					self.currentlyPlayingServiceReference = alternativeref
					self.currentlyPlayingServiceOrGroup = ref
					if self.pnav.playService(alternativeref):
						print("[Navigation] Failed to start: ", alternativeref.toString())
						self.currentlyPlayingServiceReference = None
						self.currentlyPlayingServiceOrGroup = None
						if oldref and "://" in oldref.getPath():
							print("[Navigation] Streaming was active -> try again")  # use timer to give the streamserver the time to deallocate the tuner
							self.retryServicePlayTimer = eTimer()
							self.retryServicePlayTimer.callback.append(boundFunction(self.playService, ref, checkParentalControl, forceRestart, adjust))
							self.retryServicePlayTimer.start(500, True)
					else:
						print("[Navigation] alternative ref as simulate: ", alternativeref.toString())
				return 0
			elif checkParentalControl and not parentalControl.isServicePlayable(playref, boundFunction(self.playService, checkParentalControl=False)):
				if self.currentlyPlayingServiceOrGroup and InfoBarInstance and InfoBarInstance.servicelist.servicelist.setCurrent(self.currentlyPlayingServiceOrGroup, adjust):
					self.currentlyPlayingServiceOrGroup = InfoBarInstance.servicelist.servicelist.getCurrent()
				return 1
		else:
			playref = ref
		if self.pnav:
			if not SystemInfo["FCCactive"]:
				self.pnav.stopService()
			else:
				self.skipServiceReferenceReset = True
			self.currentlyPlayingServiceReference = playref
			playref = streamrelay.streamrelayChecker(playref)
			is_dynamic = False
			if callable(processIPTVService):
				playref, old_ref, is_dynamic, ref_type = processIPTVService(playref, self.playRealService, event)
				if InfoBarInstance:
					InfoBarInstance.session.screen["Event_Now"].updateSource(playref)
					InfoBarInstance.session.screen["Event_Next"].updateSource(playref)

			self.currentlyPlayingServiceOrGroup = ref
			if InfoBarInstance and InfoBarInstance.servicelist.servicelist.setCurrent(ref, adjust):
				self.currentlyPlayingServiceOrGroup = InfoBarInstance.servicelist.servicelist.getCurrent()
			setPriorityFrontend = False
			if SystemInfo["DVB-T_priority_tuner_available"] or SystemInfo["DVB-C_priority_tuner_available"] or SystemInfo["DVB-S_priority_tuner_available"] or SystemInfo["ATSC_priority_tuner_available"]:
				str_service = playref.toString()
				if '%3a//' not in str_service and not str_service.rsplit(":", 1)[1].startswith("/"):
					type_service = playref.getUnsignedData(4) >> 16
					if type_service == 0xEEEE:
						if SystemInfo["DVB-T_priority_tuner_available"] and config.usage.frontend_priority_dvbt.value != "-2":
							if config.usage.frontend_priority_dvbt.value != config.usage.frontend_priority.value:
								setPreferredTuner(int(config.usage.frontend_priority_dvbt.value))
								setPriorityFrontend = True
						if SystemInfo["ATSC_priority_tuner_available"] and config.usage.frontend_priority_atsc.value != "-2":
							if config.usage.frontend_priority_atsc.value != config.usage.frontend_priority.value:
								setPreferredTuner(int(config.usage.frontend_priority_atsc.value))
								setPriorityFrontend = True
					elif type_service == 0xFFFF:
						if SystemInfo["DVB-C_priority_tuner_available"] and config.usage.frontend_priority_dvbc.value != "-2":
							if config.usage.frontend_priority_dvbc.value != config.usage.frontend_priority.value:
								setPreferredTuner(int(config.usage.frontend_priority_dvbc.value))
								setPriorityFrontend = True
						if SystemInfo["ATSC_priority_tuner_available"] and config.usage.frontend_priority_atsc.value != "-2":
							if config.usage.frontend_priority_atsc.value != config.usage.frontend_priority.value:
								setPreferredTuner(int(config.usage.frontend_priority_atsc.value))
								setPriorityFrontend = True
					else:
						if SystemInfo["DVB-S_priority_tuner_available"] and config.usage.frontend_priority_dvbs.value != "-2":
							if config.usage.frontend_priority_dvbs.value != config.usage.frontend_priority.value:
								setPreferredTuner(int(config.usage.frontend_priority_dvbs.value))
								setPriorityFrontend = True
			if config.misc.softcam_streamrelay_delay.value and self.currentServiceIsStreamRelay:
				self.currentServiceIsStreamRelay = False
				self.currentlyPlayingServiceReference = None
				self.currentlyPlayingServiceOrGroup = None
				print("[Navigation] Streamrelay was active -> delay the zap till tuner is freed")
				self.retryServicePlayTimer = eTimer()
				self.retryServicePlayTimer.callback.append(boundFunction(self.playService, ref, checkParentalControl, forceRestart, adjust))
				self.retryServicePlayTimer.start(config.misc.softcam_streamrelay_delay.value, True)
			elif not is_dynamic and self.pnav.playService(playref):
				self.currentlyPlayingServiceReference = None
				self.currentlyPlayingServiceOrGroup = None
				if oldref and "://" in oldref.getPath():
					print("[Navigation] Streaming was active -> try again")  # use timer to give the streamserver the time to deallocate the tuner
					self.retryServicePlayTimer = eTimer()
					self.retryServicePlayTimer.callback.append(boundFunction(self.playService, ref, checkParentalControl, forceRestart, adjust))
					self.retryServicePlayTimer.start(500, True)

			self.skipServiceReferenceReset = False
			if setPriorityFrontend:
				setPreferredTuner(int(config.usage.frontend_priority.value))
			if self.currentlyPlayingServiceReference and self.currentlyPlayingServiceReference.toString() in streamrelay.data:
				self.currentServiceIsStreamRelay = True
			if InfoBarInstance and playref.toString().find("%3a//") > -1 and not is_dynamic:
				InfoBarInstance.serviceStarted()
			return 0
	elif oldref and InfoBarInstance and InfoBarInstance.servicelist.servicelist.setCurrent(oldref, adjust):
		self.currentlyPlayingServiceOrGroup = InfoBarInstance.servicelist.servicelist.getCurrent()
	return 1


def playRealService(self, nnref):
	self.pnav.stopService()
	self.currentlyPlayingServiceReference = nnref
	self.pnav.playService(nnref)

	from Components.ServiceEventTracker import InfoBarCount
	InfoBarInstance = InfoBarCount == 1 and InfoBar.instance
	if InfoBarInstance:
		if "%3a//" in nnref.toString():
			InfoBarInstance.session.screen["CurrentService"].newService(nnref)
		else:
			InfoBarInstance.session.screen["CurrentService"].newService(True)
		InfoBarInstance.serviceStarted()


def recordServiceWithIPTV(self, ref, simulate=False):
	service = None
	if not simulate:
		print("[Navigation] recording service:", (ref and ref.toString()))
	if ref:
		if ref.flags & eServiceReference.isGroup:
			ref = getBestPlayableServiceReference(ref, eServiceReference(), simulate)
		ref = streamrelay.streamrelayChecker(ref)
		ref = processIPTVService(ref, None)[0]
		service = ref and self.pnav and self.pnav.recordService(ref, simulate)
		if service is None:
			print("[Navigation] record returned non-zero")
	return service

class VoDMoviePlayer(MoviePlayer):
	def __init__(self, session, service, slist=None, lastservice=None):
		MoviePlayer.__init__(self, session, service=service, slist=slist, lastservice=lastservice)
		self.skinName = ["VoDMoviePlayer", "MoviePlayer"]

	def leavePlayer(self):
		self.setResumePoint()
		self.handleLeave("quit")

	def leavePlayerOnExit(self):
		if self.shown:
			self.hide()
		else:
			self.leavePlayer()

	def setResumePoint(self):
		global resumePointCache, resumePointCacheLast
		service = self.session.nav.getCurrentService()
		ref = self.session.nav.getCurrentlyPlayingServiceOrGroup()
		if (service is not None) and (ref is not None):
			seek = service.seek()
			if seek:
				pos = seek.getPlayPosition()
				if not pos[0]:
					key = ref.toString()
					lru = int(time())
					sl = seek.getLength()
					if sl:
						sl = sl[1]
					else:
						sl = None
					resumePointCache[key] = [lru, pos[1], sl]
					saveResumePoints()
	
	def doEofInternal(self, playing):
		if not self.execing:
			return
		if not playing:
			return
		ref = self.session.nav.getCurrentlyPlayingServiceOrGroup()
		if ref:
			delResumePoint(ref)
		self.handleLeave("quit")

	def up(self):
		pass

	def down(self):
		pass


class M3UIPTVVoDSeries(Screen):
	MODE_GENRE = 0
	MODE_SERIES = 1
	MODE_SEARCH = 2
	MODE_EPISODE = 3

	skin = ["""
		<screen name="M3UIPTVVoDSeries" position="center,center" size="%d,%d">
			<panel name="__DynamicColorButtonTemplate__"/>
			<widget source="list" render="Listbox" position="%d,%d" size="%d,%d" scrollbarMode="showOnDemand">
				<convert type="TemplatedMultiContent">
					{"template": [
							MultiContentEntryText(pos = (%d,%d), size = (%d,%d), flags = RT_HALIGN_LEFT, text = 1), # index 0 is the MenuText,
						],
					"fonts": [gFont("Regular",%d)],
					"itemHeight":%d
					}
				</convert>
			</widget>
			<widget source="description" render="Label" position="%d,%d" zPosition="10" size="%d,%d" halign="center" valign="center" font="Regular;%d" transparent="1" shadowColor="black" shadowOffset="-1,-1" />
		</screen>""",
			610, 410,  # screen
			15, 60, 580, 286,  # Listbox
			2, 0, 590, 26,  # template
			22,  # fonts
			26,  # ItemHeight
			5, 360, 600, 50, 22,  # description
			]  # noqa: E124

	def __init__(self, session):
		Screen.__init__(self, session)
		self.skinName = [self.skinName, "M3UIPTVVoDMovies"]
		self["list"] = List([])
		self["description"] = StaticText()
		self.mode = self.MODE_GENRE
		self.allseries = {}
		for provider in providers:
			series = providers[provider].vod_series
			for genre in series:
				if genre not in self.allseries:
					self.allseries[genre] = []
				for series_id, name in series[genre]:
					self.allseries[genre].append((series_id, name, provider))
		self.categories = list(sorted(self.allseries.keys()))
		self.category = self.categories[0] if self.categories else None
		self.seriesindex = 0
		if self.selectionChanged not in self["list"].onSelectionChanged:
			self["list"].onSelectionChanged.append(self.selectionChanged)

		self["key_red"] = StaticText(_("Cancel"))
		#self["key_green"] = StaticText(_("Search"))
		#self["key_yellow"] = StaticText()
		# self["key_blue"] = StaticText()

		self["actions"] = ActionMap(["SetupActions", "ColorActions", "InfobarSeekActions"],
			{
				"cancel": self.keyCancel,  # KEY_RED / KEY_EXIT
				#"save": self.keySearch,  # KEY_GREEN
				"ok": self.keySelect,
				#"yellow": self.mdb,
				# "blue": self.blue,
				"playpauseService": self.key_play,
			}, -1)  # noqa: E123
		self.buildList()
		# self.onClose.append(self.mdbCleanup)

	def selectionChanged(self):
		if self.mode in (self.MODE_EPISODE, self.MODE_SEARCH):
			if (current := self["list"].getCurrent()) and (info := current[2]) is not None and (plot := info.get("plot")) is not None:
				self["description"].text = plot + " [%s]" % current[4]
			else:
				self["description"].text = _("Press OK to access selected item")
				
	def keyCancel(self):
		if len(self.allseries) > 1 and self.mode in (self.MODE_SERIES, self.MODE_SEARCH):
			self.mode = self.MODE_GENRE
			self.seriesindex = 0
			self.buildList()
		elif self.mode == self.MODE_EPISODE:
			self.mode = self.MODE_SERIES
			self.buildList()
		else:
			self.close()

	def keySelect(self):
		if current := self["list"].getCurrent():
			if self.mode == self.MODE_GENRE:
				self.mode = self.MODE_SERIES
				self.category = current[0]
				self.buildList()
				self["list"].index = 0
			elif self.mode == self.MODE_SERIES:
				self.seriesindex = self["list"].index
				id = current[0]
				print("[M3UIPTVVoDSeries] keySelect, Series_id", id)
				self.seriesName = current[1]
				provider = current[2]
				self.episodes = providers[provider].getSeriesById(id)
				self.mode = self.MODE_EPISODE
				self.buildList()
				self["list"].index = 0
			elif self.mode == self.MODE_EPISODE:
				self.playMovie()

	def key_play(self):
		if self.mode == self.MODE_EPISODE:
			self.playMovie()
				

	def buildList(self):
		if not self.categories:
			return
		if len(self.allseries) == 1 and self.mode == self.MODE_GENRE:  # go straight into series mode if no categories are available
			self.mode = self.MODE_SERIES
		if self.mode == self.MODE_GENRE:
			self.title = _("VoD Series Categories")
			self["description"].text = _("Press OK to select a category")
			self["list"].setList([(x, x) for x in self.categories])
			self["list"].index = self.categories.index(self.category)
		elif self.mode == self.MODE_SERIES:
			self.title = _("VoD Series Category: %s") % self.category
			self["description"].text = _("Press OK to select a series")
			self["list"].setList([x for x in sorted(self.allseries[self.category], key=lambda x: x[1].lower())])
			self["list"].index = self.seriesindex
		elif self.mode == self.MODE_EPISODE:
			self.title = _("VoD Series: %s") % self.seriesName
			self["description"].text = _("Press OK to play selected show")
			self["list"].setList([x for x in self.episodes])

	def playMovie(self):
		if current := self["list"].getCurrent():
			infobar = InfoBar.instance
			if infobar:
				LastService = self.session.nav.getCurrentlyPlayingServiceOrGroup()
				ref = eServiceReference("4097:0:1:9999:1009:1:CCCC0000:0:0:0:%s:%s" % (current[0].replace(":", "%3a"), current[1]))
				self.session.open(VoDMoviePlayer, ref, slist=infobar.servicelist, lastservice=LastService)


class M3UIPTVVoDMovies(Screen):
	MODE_CATEGORY = 0
	MODE_MOVIE = 1
	MODE_SEARCH = 2

	skin = ["""
		<screen name="M3UIPTVVoDMovies" position="center,center" size="%d,%d">
			<panel name="__DynamicColorButtonTemplate__"/>
			<widget source="list" render="Listbox" position="%d,%d" size="%d,%d" scrollbarMode="showOnDemand">
				<convert type="TemplatedMultiContent">
					{"template": [
							MultiContentEntryText(pos = (%d,%d), size = (%d,%d), flags = RT_HALIGN_LEFT, text = 1), # index 0 is the MenuText,
						],
					"fonts": [gFont("Regular",%d)],
					"itemHeight":%d
					}
				</convert>
			</widget>
			<widget source="description" render="Label" position="%d,%d" zPosition="10" size="%d,%d" halign="center" valign="center" font="Regular;%d" transparent="1" shadowColor="black" shadowOffset="-1,-1" />
		</screen>""",
			610, 410,  # screen
			15, 60, 580, 286,  # Listbox
			2, 0, 590, 26,  # template
			22,  # fonts
			26,  # ItemHeight
			5, 360, 600, 50, 22,  # description
			]  # noqa: E124

	def __init__(self, session):
		Screen.__init__(self, session)
		self["list"] = List([])
		self["description"] = StaticText()
		self.mode = self.MODE_CATEGORY
		self.allmovies = []
		for provider in providers:
			self.allmovies += [movie for movie in providers[provider].vod_movies if movie.name is not None]
		self.category = "All"
		self.categories = []
		self.searchTexts = []
		self.searchTerms = []
		for movie in self.allmovies:
			if movie.category is not None and movie.category not in self.categories:
				self.categories.append(movie.category)
		self.categories.sort(key=lambda x: x.lower())
		self.categories.insert(0, self.category)
		if self.selectionChanged not in self["list"].onSelectionChanged:
			self["list"].onSelectionChanged.append(self.selectionChanged)

		self["key_red"] = StaticText(_("Cancel"))
		self["key_green"] = StaticText(_("Search"))
		self["key_yellow"] = StaticText()
		# self["key_blue"] = StaticText()

		self["actions"] = ActionMap(["SetupActions", "ColorActions", "InfobarSeekActions"],
			{
				"cancel": self.keyCancel,  # KEY_RED / KEY_EXIT
				"save": self.keySearch,  # KEY_GREEN
				"ok": self.keySelect,
				"yellow": self.mdb,
				# "blue": self.blue,
				"playpauseService": self.key_play,
			}, -1)  # noqa: E123
		self.buildList()
		self.onClose.append(self.mdbCleanup)

	def selectionChanged(self):
		if self.mode in (self.MODE_MOVIE, self.MODE_SEARCH):
			if (current := self["list"].getCurrent()) and (plot := current[0].plot) is not None:
				self["description"].text = plot
			else:
				self["description"].text = _("Press OK to play selected movie")

	def mdb(self):
		if self.mode in (self.MODE_MOVIE, self.MODE_SEARCH) and (current := self["list"].getCurrent()):
			if tmdbScreen:
				args = tmdbScreenMovieHelper(current[0])
				if args and args[0]:
					url_cover = args[1]
					args = args[0]
					if not fileExists(args[2]):
						self.mbpTimer = eTimer()
						self.mbpTimer.callback.append(boundFunction(self.mdbCover, url_cover, args[2], current[0]))
						self.mbpTimer.start(100, True)
					self.tmdbScreenMovie = self.session.open(tmdbScreenMovie, *args)
				else:
					self.session.open(tmdbScreen, current[1].replace("4K", "").replace("4k", ""), 2)
			elif IMDB:
				self.session.open(IMDB, current[1].replace("4K", "").replace("4k", ""), False)

	def mdbText(self):
		if self.mode in (self.MODE_MOVIE, self.MODE_SEARCH) and (current := self["list"].getCurrent()):
			if tmdbScreen:
				return _("TMDb search")
			elif IMDB:
				return _("IMDb search")
		return ""

	def mdbCover(self, url_cover, cover_file, VoDObj):
		makedirs(tmdbTempDir, exist_ok=True)
		if VoDObj.providerObj.getUrlToFile(url_cover, cover_file):
			self.tmdbScreenMovie.decodeCover(cover_file)

	def mdbCleanup(self):
		if path.exists(tmdbTempDir):
			for jpg in glob(tmdbTempDir + '*.jpg'):
				remove(jpg)

	def keySelect(self):
		if self.mode == self.MODE_CATEGORY:
			if current := self["list"].getCurrent():
				self.mode = self.MODE_MOVIE
				self.category = current[0]
				self.buildList()
				self["list"].index = 0
		else:
			self.playMovie()

	def key_play(self):
		if self.mode != self.MODE_CATEGORY:
			self.playMovie()

	def keySearch(self):
		self.session.openWithCallback(self.keySearchCallback, VirtualKeyBoard, title=_("VoD Movie: enter search terms"), text=" ".join(self.searchTerms))

	def keySearchCallback(self, retval=None):
		if retval is not None:
			if not self.searchTexts:
				self.searchTexts = [re.split(r"\b", movie.name.lower()) for movie in self.allmovies]
			self.searchTerms = retval.lower().split()
			self.mode = self.MODE_SEARCH
			self.buildList()
			self["list"].index = 0

	def search(self, i):
		count = 0
		for t in self.searchTexts[i]:
			for term in self.searchTerms:
				if t == term:
					count += 2
				elif t.startswith(term):
					count += 1
		return count

	def buildList(self):
		if len(self.categories) == 1 and self.mode == self.MODE_CATEGORY:  # go straight into movie mode if no categories are available
			self.mode = self.MODE_MOVIE
		if self.mode == self.MODE_SEARCH:
			self.title = _("VoD Movie Search")
			self["description"].text = _("Press OK to play selected movie")
			self["list"].setList(sorted([(movie, movie.name, c) for i, movie in enumerate(self.allmovies) if (c := self.search(i))], key=lambda x: (-x[2], x[1])))
		elif self.mode == self.MODE_CATEGORY:
			self.title = _("VoD Movie Categories")
			self["description"].text = _("Press OK to select a category")
			self["list"].setList([(x, x) for x in self.categories])
			self["list"].index = self.categories.index(self.category)
		else:
			self.title = _("VoD Movie Category: %s") % self.category
			self["description"].text = _("Press OK to play selected movie")
			self["list"].setList(sorted([(movie, movie.name) for movie in self.allmovies if self.category == "All" or self.category == movie.category], key=lambda x: x[1].lower()))
		self["key_yellow"].text = self.mdbText()

	def playMovie(self):
		if current := self["list"].getCurrent():
			infobar = InfoBar.instance
			if infobar:
				LastService = self.session.nav.getCurrentlyPlayingServiceOrGroup()
				ref = eServiceReference("4097:0:1:9999:1009:1:CCCC0000:0:0:0:%s:%s" % (current[0].url.replace(":", "%3a"), current[0].name))
				self.session.open(VoDMoviePlayer, ref, slist=infobar.servicelist, lastservice=LastService)

	def keyCancel(self):
		if len(self.categories) > 1 and self.mode in (self.MODE_MOVIE, self.MODE_SEARCH):
			self.mode = self.MODE_CATEGORY
			self.buildList()
		else:
			self.close()

	def createSummary(self):
		return PluginSummary


class M3UIPTVManagerConfig(Screen):
	skin = ["""
		<screen name="M3UIPTVManagerConfig" position="center,center" size="%d,%d">
			<panel name="__DynamicColorButtonTemplate__"/>
			<widget source="list" render="Listbox" position="%d,%d" size="%d,%d" scrollbarMode="showOnDemand">
				<convert type="TemplatedMultiContent">
					{"template": [
							MultiContentEntryText(pos = (%d,%d), size = (%d,%d), flags = RT_HALIGN_LEFT, text = 1), # index 0 is the MenuText,
						],
					"fonts": [gFont("Regular",%d)],
					"itemHeight":%d
					}
				</convert>
			</widget>
			<widget source="description" render="Label" position="%d,%d" zPosition="10" size="%d,%d" halign="center" valign="center" font="Regular;%d" transparent="1" shadowColor="black" shadowOffset="-1,-1" />
		 	<widget source="progress" render="Progress" position="%d,%d" size="%d,%d" backgroundColor="background" foregroundColor="blue" zPosition="11" borderWidth="0" borderColor="grey" cornerRadius="%d"/>
		</screen>""",
			610, 410,  # screen
			15, 60, 580, 286,  # Listbox
			2, 0, 330, 26,  # template
			22,  # fonts
			26,  # ItemHeight
			5, 360, 600, 50, 22,  # description
			5, 360, 600, 6, 3,  # progress
			]  # noqa: E124

	def __init__(self, session):
		Screen.__init__(self, session)
		self.setTitle(_("M3U IPTV Manager - providers"))
		self["list"] = List([])
		self["progress"] = Progress()
		self.generate_timer = eTimer()
		self.generate_timer.callback.append(self.generateBouquets)
		self.progress_timer = eTimer()
		self.progress_timer.callback.append(self.onProgressTimer)
		self.progress_timer.start(1000)
		self.onProgressTimer()
		self.buildList()
		self["key_red"] = StaticText(_("Close"))
		self["key_green"] = StaticText(_("Add provider"))
		self["key_yellow"] = StaticText(_("Generate bouquets"))
		self["key_blue"] = StaticText(_("Clear bouquets"))
		self["description"] = StaticText(_("Press OK to edit the currently selected provider"))
		self.updateCallbacks()
		self.onClose.append(self.__onClose)

		self["actions"] = ActionMap(["SetupActions", "ColorActions",],
			{
				"cancel": self.close,  # KEY_RED / KEY_EXIT
				"save": self.addProvider,  # KEY_GREEN
				"ok": self.editProvider,
				"yellow": self.keyYellow,
				"blue": self.clearBouquets,
			}, -1)  # noqa: E123

	def __onClose(self):
		self.removeCallbacks()

	def removeCallbacks(self):
		for provider in providers:
			providerObj = providers[provider]
			while self.updateDescription in providerObj.update_status_callback:
				providerObj.update_status_callback.remove(self.updateDescription)
		
	def updateCallbacks(self):
		for provider in providers:
			providerObj = providers[provider]
			if self.updateDescription not in providerObj.update_status_callback:
				providerObj.update_status_callback.append(self.updateDescription)
		
	def onProgressTimer(self):
		providers_updating = 0
		providers_overal_progress = 0
		for provider in providers:
			prov = providers[provider]
			if prov.progress_percentage > -1:
				providers_updating += 1
				providers_overal_progress += prov.progress_percentage

		if providers_updating == 0:
			self.progress_timer.stop()
		else:
			progress_val = int(providers_overal_progress // providers_updating)
			self["progress"].value = progress_val if progress_val >= 0 else 0

	def buildList(self):
		self["list"].list = [(provider, providers[provider].iptv_service_provider) for provider in providers]

	def addProvider(self):
		self.session.openWithCallback(self.providerCallback, M3UIPTVProviderEdit)

	def editProvider(self):
		if current := self["list"].getCurrent():
			self.session.openWithCallback(self.providerCallback, M3UIPTVProviderEdit, current[0])

	def providerCallback(self, result=None):
		if result:
			self.updateCallbacks()
			self.buildList()

	def keyYellow(self):  # needed to force message update
		if current := self["list"].getCurrent():
			provider = current[0]
			providerObj = providers[provider]
			self.updateDescription(_("%s: starting bouquet creation") % providerObj.iptv_service_provider)
			self.generate_timer.start(10, 1)

	def generateBouquets(self):
		if current := self["list"].getCurrent():
			provider = current[0]
			providerObj = providers[provider]
			providerObj.progress_percentage = 0
			self.progress_timer.stop()
			self.progress_timer.start(1000)
			try:
				providerObj.onBouquetCreated.append(self.onBouquetCreated)
				providerObj.getPlaylistAndGenBouquet()
			except Exception as ex:
				print("[M3UIPTV] Error has occured during bouquet creation: " + str(ex))
				import traceback
				traceback.print_exc()
				self.progress_timer.stop()
				self["progress"].value = -1
				self.updateDescription(_("%s: an error occured during bouquet creation") % providerObj.iptv_service_provider)
				self.session.open(MessageBox, _("Unable to create bouquet \"%s\"!\nPossible reason can be no network available.") % providerObj.iptv_service_provider, MessageBox.TYPE_ERROR, timeout=5)

	def onBouquetCreated(self, providerObj, error):
		if not hasattr(self, "session") or not self.session:
			return
		self.progress_timer.stop()
		self["progress"].value = -1
		if error:
			self.updateDescription(_("%s: unable to create bouquet") % providerObj.iptv_service_provider)
			self.session.open(MessageBox, _("Unable to create bouquet \"%s\"!\nPossible reason can be no network available.") % providerObj.iptv_service_provider, MessageBox.TYPE_ERROR, timeout=5)
		else:
			self.updateDescription(_("%s: bouquets generated successfully") % providerObj.iptv_service_provider)
			self.session.open(MessageBox, _("\"%s\" bouquets have been generated successfully") % providerObj.iptv_service_provider, MessageBox.TYPE_INFO, timeout=5)
		self["actions"].setEnabled(True)

	def updateDescription(self, desc):
		try:
			self["description"].text = desc
		except KeyError:  # if MessageBox is open
			pass

	def clearBouquets(self):
		if current := self["list"].getCurrent():
			provider = current[0]
			providerObj = providers[provider]
			providerObj.removeBouquets()
			self.updateDescription(_("%s: bouquets removed successfully") % providerObj.iptv_service_provider)

	def createSummary(self):
		return PluginSummary


class M3UIPTVProviderEdit(Setup):
	def __init__(self, session, provider=None):
		self.edit = provider in providers
		providerObj = providers.get(provider, IPTVProcessor())
		self.providerObj = providerObj
		self.type = ConfigSelection(default=providerObj.type, choices=[("M3U", _("M3U/M3U8")), ("Xtreeme", _("Xtreme Codes")), ("Stalker", _("Stalker portal"))])
		self.iptv_service_provider = ConfigText(default=providerObj.iptv_service_provider, fixed_size=False)
		self.url = ConfigText(default=providerObj.url, fixed_size=False)
		refresh_interval_choices = [(-1, _("off")), (0, _("on"))] + [(i, ngettext("%d hour", "%d hours", i) % i) for i in [1, 2, 3, 4, 5, 6, 12, 24]] 
		self.refresh_interval = ConfigSelection(default=providerObj.refresh_interval, choices=refresh_interval_choices)
		self.novod = ConfigYesNo(default=providerObj.ignore_vod)
		self.create_epg = ConfigYesNo(default=providerObj.create_epg)
		self.staticurl = ConfigYesNo(default=providerObj.static_urls)
		self.search_criteria = ConfigText(default=providerObj.search_criteria, fixed_size=False)
		self.scheme = ConfigText(default=providerObj.scheme, fixed_size=False)
		self.username = ConfigText(default=providerObj.username, fixed_size=False)
		self.password = ConfigPassword(default=providerObj.password, fixed_size=False)
		self.mac = ConfigText(default=providerObj.mac, fixed_size=False)
		play_system_choices = [("1", "DVB"), ("4097", "GStreamer")]
		if isPluginInstalled("ServiceApp"):
			play_system_choices.append(("5002", "Exteplayer3"))
		self.play_system = ConfigSelection(default=providerObj.play_system, choices=play_system_choices)
		self.play_system_catchup = ConfigSelection(default=providerObj.play_system_catchup, choices=play_system_choices)
		catchup_type_choices = [(CATCHUP_DEFAULT, _("Standard")), (CATCHUP_APPEND, _("Append")), (CATCHUP_SHIFT, _("Shift")), (CATCHUP_XTREME, _("Xtreme Codes")), (CATCHUP_STALKER, _("Stalker"))]
		self.catchup_type = ConfigSelection(default=providerObj.catchup_type, choices=catchup_type_choices)
		self.epg_url = ConfigText(default=providerObj.epg_url, fixed_size=False)
		Setup.__init__(self, session, yellow_button={"text": _("Delete provider \"%s\"") % providerObj.iptv_service_provider, "helptext": _("Permanently remove provider \"%s\" from your configuration.") % providerObj.iptv_service_provider, "function": self.keyRemove} if self.edit else None)
		self.title = _("M3UIPTVManager") + " - " + (_("edit provider") if self.edit else _("add new provider"))

	def createSetup(self):
		configlist = []
		if not self.edit:  # Only show when adding a provider so to select the output type.
			configlist.append((_("Provider Type"), self.type, _("Specify the provider type.")))
		configlist.append((_("Provider name"), self.iptv_service_provider, _("Specify the provider user friendly name that will be used for the bouquet name and for displaying in the infobar.")))
		configlist.append(("URL", self.url, _("The playlist URL (*.m3u; *.m3u8) or the Xtreme codes server URL.")))
		if self.type.value == "M3U":
			configlist.append((_("Use static URLs"), self.staticurl, _("If enabled URL will be static and not aliases. That means if the URL of a service changes in the playlist bouquet entry will stop working.")))
			if not self.staticurl.value:
				configlist.append((_("Refresh interval"), self.refresh_interval, _("Interval in which the playlist will be automatically updated")))
			configlist.append((_("Filter"), self.search_criteria, _("The search criter by which the service will be searched in the playlist file.")))
		elif self.type.value == "Xtreeme":
			configlist.append((_("Username"), self.username, _("User name used for authenticating in Xtreme codes server.")))
			configlist.append((_("Password"), self.password, _("Password used for authenticating in Xtreme codes server.")))
		else:
			configlist.append((_("MAC address"), self.mac, _("MAC address used for authenticating in Stalker portal.")))
		if self.type.value == "Xtreeme":
			configlist.append((_("Skip VOD entries"), self.novod, _("Skip VOD entries in the playlist")))
		configlist.append((_("Generate EPG files for EPGImport plugin"), self.create_epg, _("Creates files needed for importing EPG via EPGImport plugin")))
		if self.type.value == "M3U" and self.create_epg.value:
			configlist.append((_("EPG URL"), self.epg_url, _("The URL where EPG data for this provider can be downloaded. If available in the M3U playlist it will be addeed automatically.")))
		if not self.edit:  # Only show when adding a provider. scheme is the key so must not be edited. 
			configlist.append((_("Scheme"), self.scheme, _("Specifying the URL scheme that unicly identify the provider.\nCan be anything you like without spaces and special characters.")))
		configlist.append((_("Playback system"), self.play_system, _("The player used. Can be DVB, GStreamer, HiSilicon, Extplayer3")))
		configlist.append((_("Playback system for Catchup/Archive"), self.play_system_catchup, _("The player used for playing Catchup/Archive. Can be DVB, GStreamer, HiSilicon, Extplayer3")))
		if self.type.value == "M3U":
			configlist.append((_("Catchup Type"), self.catchup_type, _("The catchup API used.")))
		self["config"].list = configlist

	def keySave(self):
		self.scheme.value = self.providerObj.cleanFilename(self.scheme.value)
		if not self.iptv_service_provider.value or not self.url.value or not self.scheme.value or not self.edit and self.scheme.value in providers or self.type.value == "Xtreeme" and (not self.username.value or not self.password.value):  # empty mandatory fields or scheme is not unique
			msg = _("Scheme must be unique. \"%s\" is already in use. Please update this field.") % self.scheme.value if not self.edit and self.scheme.value and self.scheme.value in providers else _("All fields must be filled in.")
			self.session.open(MessageBox, msg, MessageBox.TYPE_ERROR, timeout=30)
			return

		if self.type.value == "M3U":
			providerObj = M3UProvider() 
		elif self.type.value == "Xtreeme":
			providerObj = XtreemProvider() 
		else:
			providerObj = StalkerProvider() 
		providerObj.iptv_service_provider = self.iptv_service_provider.value
		providerObj.url = self.url.value
		providerObj.iptv_service_provider = self.iptv_service_provider.value
		providerObj.scheme = self.scheme.value
		providerObj.play_system = self.play_system.value
		providerObj.ignore_vod = self.novod.value
		providerObj.play_system_catchup = self.play_system_catchup.value
		providerObj.create_epg = self.create_epg.value
		if self.type.value == "M3U":
			providerObj.refresh_interval = self.refresh_interval.value
			providerObj.static_urls = self.staticurl.value
			providerObj.search_criteria = self.search_criteria.value
			providerObj.catchup_type = self.catchup_type.value
			providerObj.epg_url = self.epg_url.value
		elif self.type.value == "Xtreeme":
			providerObj.username = self.username.value
			providerObj.password = self.password.value
		else:
			providerObj.mac = self.mac.value

		if getattr(providerObj, "onid", None) is None:
			providerObj.onid = min(set(range(1, len(L := [x.onid for x in providers.values() if hasattr(x, "onid")]) + 2)) - set(L))
		providers[self.scheme.value] = providerObj
		writeProviders()
		self.close(True)

	def keyRemove(self):
		self.session.openWithCallback(self.keyRemoveCallback, MessageBox, _("Are you sure you want to permanently remove provider \"%s\" from your configuration?") % self.scheme.value, MessageBox.TYPE_YESNO)

	def keyRemoveCallback(self, answer=None):
		if answer:
			providerObj = providers[self.scheme.value]
			providerObj.removeBouquets()
			del providers[self.scheme.value]
			writeProviders()
			self.close(True)

class IPTVPluginConfig(Setup):
	def __init__(self, session):
		Setup.__init__(self, session)
		self.title = _("IPTV Settings")

	def createSetup(self):
		configlist = []
		configlist.append((_("Enable IPTV manager") + " *", config.plugins.m3uiptv.enabled, _("Enable IPTV functionality and managment.")))
		configlist.append((_("Check for Network"), config.plugins.m3uiptv.check_internet, _("Do a check is network available before try to retrieve the iptv playlist. If no network try backup services.")))
		configlist.append((_("Request timeout"), config.plugins.m3uiptv.req_timeout, _("Timeout in seconds for the requests of getting playlist.")))
		configlist.append((_("Show 'Video on Demand' menu entry") + " *", config.plugins.m3uiptv.inmenu, _("Allow showing of 'Video on Demand' menu entry in Main Menu.")))
		configlist.append(("---",))
		configlist.append((_("Recordings - convert IPTV servicetypes to  1"), config.recording.setstreamto1, _("Recording 4097, 5001 and 5002 streams not possible with external players, so convert recordings to servicetype 1.")))
		configlist.append((_("Enable new GStreamer playback"), config.misc.usegstplaybin3, _("If enabled, the new GStreamer playback engine will be used.")))
		configlist.append(("---",))
		configlist.append((_("Automatically start timeshift after"), config.timeshift.startdelay, _("When enabled, timeshift starts automatically in background after the specified time.")))
		configlist.append((_("Show warning when timeshift is stopped"), config.usage.check_timeshift, _("When enabled, a warning will be displayed and the user will get an option to stop or to continue the timeshift.")))
		configlist.append((_("Timeshift-save action on zap"), config.timeshift.favoriteSaveAction, _("Select if timeshift should continue when set to record.")))
		configlist.append((_("Stop timeshift while recording?"), config.timeshift.stopwhilerecording, _("Stops timeshift being used if a recording is in progress. (Advisable for USB sticks)")))
		configlist.append((_("Use timeshift seekbar while timeshifting?"), config.timeshift.showinfobar, _("If set to 'yes', allows you to use the seekbar to jump to a point within the event.")))
		configlist.append((_("Skip jumping to live TV while timeshifting with plugins"), config.usage.timeshift_skipreturntolive, _("If set to 'yes', allows you to use timeshift with alternative audio plugins.")))
		if isPluginInstalled("ServiceApp"):
			configlist.append(("---",))
			configlist.append((_("Enigma2 playback system"), config.plugins.serviceapp.servicemp3.replace, _("Change the playback system to one of the players available in ServiceApp plugin.")))
			configlist.append((_("Select the player which will be used for Enigma2 playback."), config.plugins.serviceapp.servicemp3.player, _("Select a player to be in use.")))
		self["config"].list = configlist


class PluginSummary(ScreenSummary):
	def __init__(self, session, parent):
		ScreenSummary.__init__(self, session, parent=parent)
		self.skinName = "SetupSummary"
		self["SetupTitle"] = StaticText()
		self["SetupEntry"] = StaticText()
		self["SetupValue"] = StaticText()
		if self.addWatcher not in self.onShow:
			self.onShow.append(self.addWatcher)
		if self.removeWatcher not in self.onHide:
			self.onHide.append(self.removeWatcher)

	def addWatcher(self):
		if self.selectionChanged not in self.parent["list"].onSelectionChanged:
			self.parent["list"].onSelectionChanged.append(self.selectionChanged)
		self.selectionChanged()

	def removeWatcher(self):
		if self.selectionChanged in self.parent["list"].onSelectionChanged:
			self.parent["list"].onSelectionChanged.remove(self.selectionChanged)

	def selectionChanged(self):
		self["SetupTitle"].text = self.parent.title
		self["SetupEntry"].text = item[1] if (item := (self.parent["list"].getCurrent())) else ""
		self["SetupValue"].text = self.parent["description"].text


def M3UIPTVMenu(session, close=None, **kwargs):
	session.openWithCallback(boundFunction(M3UIPTVMenuCallback, close), Menu, mdom.getroot())

def M3UIPTVMenuCallback(close, answer=None):
	if close and answer:
		close(True)

def M3UIPTVVoDMenu(session, close=None, **kwargs):
	session.openWithCallback(boundFunction(M3UIPTVVoDMenuCallback, close), Menu, mdom_vod.getroot())

def M3UIPTVVoDMenuCallback(close, answer=None):
	if close and answer:
		close(True)

def startSetup(menuid):
	if menuid != "setup":
		return []
	return [(_("IPTV"), M3UIPTVMenu, "iptvmenu", 10)]

def startVoDSetup(menuid):
	if menuid != "mainmenu":
		return []
	return [(_("Video on Demand"), M3UIPTVVoDMenu, "iptv_vod_menu", 100)]


def sessionstart(reason, **kwargs):
	if config.plugins.m3uiptv.enabled.value:
		injectIntoNavigation()
		readProviders()


def Plugins(path, **kwargs):
	try:
		result = [PluginDescriptor(where=PluginDescriptor.WHERE_SESSIONSTART, fnc=sessionstart, needsRestart=False),
		  		PluginDescriptor(where=PluginDescriptor.WHERE_MENU, needsRestart=False, fnc=startSetup)
		]
		if config.plugins.m3uiptv.inmenu.value:
			result += [PluginDescriptor(where=PluginDescriptor.WHERE_MENU, needsRestart=False, fnc=startVoDSetup)]

		return result
	except ImportError:
		return PluginDescriptor()

