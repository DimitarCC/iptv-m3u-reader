# for localized messages
from . import _, PluginLanguageDomain

from sys import modules
from time import time, localtime, mktime, strftime
from glob import glob
from urllib.error import HTTPError, URLError
from twisted.web import server, resource
from twisted.internet import threads, reactor
from enigma import eServiceCenter, eServiceReference, eTimer, getBestPlayableServiceReference, iPlayableService, ePicLoad
try:
	from enigma import pNavigation
except ImportError:
	pNavigation = None
from Plugins.Plugin import PluginDescriptor
from .M3UProvider import M3UProvider
from .IPTVProcessor import IPTVProcessor
from .XtreemProvider import XtreemProvider
from .StalkerProvider import StalkerProvider
from .TVHeadendProvider import TVHeadendProvider
from .VODProvider import VODProvider
from .IPTVProviders import providers, processService as processIPTVService
from .IPTVCatchupPlayer import injectCatchupInEPG
from .epgimport_helper import overwriteEPGImportEPGSourceInit
from .Variables import PROVIDER_FOLDER, USER_IPTV_PROVIDERS_FILE, USER_IPTV_PROVIDER_SUBSTITUTIONS_FILE, CATCHUP_DEFAULT, CATCHUP_APPEND, CATCHUP_SHIFT, CATCHUP_XTREME, CATCHUP_STALKER, CATCHUP_FLUSSONIC, CATCHUP_VOD, REQUEST_USER_AGENT
from Screens.Screen import Screen, ScreenSummary
from Screens.InfoBar import InfoBar, MoviePlayer
from Screens.InfoBarGenerics import streamrelay
from Screens.PictureInPicture import PictureInPicture
from Screens.Setup import Setup
from Screens.Menu import Menu
from Screens.MessageBox import MessageBox
from Screens.TextBox import TextBox
from Screens.VirtualKeyBoard import VirtualKeyBoard
from Components.ServiceEventTracker import ServiceEventTracker
from Components.ActionMap import ActionMap, HelpableActionMap, NumberActionMap
from Components.config import config, ConfigSubsection, ConfigYesNo, ConfigSelection, ConfigText, ConfigPassword, ConfigSelectionNumber, ConfigNumber, ConfigClock, ConfigSubDict, ConfigEnableDisable
from Components.ParentalControl import parentalControl
from Components.SelectionList import SelectionList, SelectionEntryComponent
from Components.Sources.StaticText import StaticText
from Components.Label import Label
from Components.Pixmap import Pixmap
from Components.Sources.List import List
from Components.Sources.Progress import Progress
from Components.SystemInfo import BoxInfo
from Tools.Directories import fileExists, isPluginInstalled, resolveFilename, SCOPE_CURRENT_SKIN
from Tools.BoundFunction import boundFunction
from Tools.LoadPixmap import LoadPixmap
from Navigation import Navigation

try:
	from Plugins.SystemPlugins.QuadPiP.qpip import QuadPiP
except ImportError:
	QuadPiP = None

try:
	from Screens.InfoBarGenerics import resumePointsInstance
	saveResumePoints = resumePointsInstance.saveResumePoints
	resumePointCache = resumePointsInstance.resumePointCache
	delResumePoint = resumePointsInstance.delResumePoint
except ImportError:
	from Screens.InfoBarGenerics import saveResumePoints, resumePointCache, delResumePoint

try:
	from Plugins.Extensions.tmdb.tmdb import tmdbScreen, tmdbScreenMovie, tempDir as tmdbTempDir, tmdb
except ImportError:
	tmdbScreen = None
	tmdbTempDir = ""
	tmdb = None
	try:
		from Plugins.Extensions.IMDb.plugin import IMDB
	except ImportError:
		IMDB = None

try:
	from Components.Renderer.Picon import searchPaths
except ImportError:
	try:
		from Components.Renderer.Picon import piconLocator
		searchPaths = piconLocator.searchPaths
	except ImportError:
		searchPaths = None

# Add imports for SubsSupport plugin if installed
try:
	from Plugins.Extensions.SubsSupport import SubsSupport, SubsSupportStatus
except ImportError:
	class SubsSupport(object):
		def __init__(self, *args, **kwargs):
			pass

	class SubsSupportStatus(object):
		def __init__(self, *args, **kwargs):
			pass

from os import path, fsync, rename, makedirs, remove
from xml.etree.cElementTree import iterparse

import json
import base64
import shutil
import xml
import re
import threading
import urllib
import os

write_lock = threading.Lock()

config.plugins.m3uiptv = ConfigSubsection()
config.plugins.m3uiptv.enabled = ConfigYesNo(default=True)
choicelist = [("off", _("off"))] + [(str(i), ngettext("%d second", "%d seconds", i) % i) for i in [1, 2, 3, 5, 7, 10]]  # noqa: F821
config.plugins.m3uiptv.check_internet = ConfigSelection(default="2", choices=choicelist)
config.plugins.m3uiptv.req_timeout = ConfigSelection(default="2", choices=choicelist)
config.plugins.m3uiptv.epg_loc_port = ConfigNumber(default=9010)
config.plugins.m3uiptv.inmenu = ConfigYesNo(default=True)
config.plugins.m3uiptv.inextensions = ConfigYesNo(default=False)
config.plugins.m3uiptv.display_poster = ConfigYesNo(default=True)
config.plugins.m3uiptv.picon_threads = ConfigSelectionNumber(min=50, max=1000, stepwidth=50, default=100, wraparound=True)
config.plugins.m3uiptv.bouquet_names_case = ConfigSelection(default=2, choices=[(0, _("Original case")), (1, _("lower case")), (2, _("UPPER case"))])
fpicon_locs = []
if searchPaths:
	fpicon_locs = [(x.removesuffix("/"), x.removesuffix("/")) for x in searchPaths]
config.plugins.m3uiptv.fallback_picon_loc = ConfigSelection(default="/picon", choices=fpicon_locs)
vod_play_system_choices = [("4097", "HiSilicon" if BoxInfo.getItem("mediaservice") == "servicehisilicon" else "GStreamer")]
if isPluginInstalled("ServiceApp"):
	vod_play_system_choices.append(("5002", "Exteplayer3"))
config.plugins.m3uiptv.vod_play_system = ConfigSelection(default="4097", choices=vod_play_system_choices)

# for AutoScheduleTimer
config.plugins.m3uiptv.schedule = ConfigYesNo(default=False)
config.plugins.m3uiptv.scheduletime = ConfigClock(default=0)  # 1:00
config.plugins.m3uiptv.days = ConfigSubDict()
for i in range(7):
	config.plugins.m3uiptv.days[i] = ConfigEnableDisable(default=True)

distro = BoxInfo.getItem("distro")

type0_distros = ["openvix", "openpli", "openbh"]
type2_distros = ["openatv", "egami"]

plugin_dir = path.dirname(modules[__name__].__file__)
file = open("%s/menu.xml" % plugin_dir, 'r')
mdom = xml.etree.cElementTree.parse(file)
file.close()


class StalkerEPG(resource.Resource):
	isLeaf = True

	def render_GET(self, request):
		request.responseHeaders.setRawHeaders('Content-Disposition', ['attachment; filename="epg.xml"'])
		provider = request.args[b"p"][0].decode("utf-8")
		try:
			return providers[provider].generateXMLTVFile()
		except:
			return None
		
class Substition():
	def __init__(self, key, regex):
		self.search_key = key
		self.search_regex = regex
		self.substitions = {}

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

def readSubstitions(scheme):
	def make_result_obj():
		res = {}
		res["#EXTINF"] = []
		res["#URL"] = []
		return res

	def subIter(elements, result_obj):
		for sname_subst in elements:
			for sname_subst_elem in sname_subst.findall("substitution"):
				subst_item = Substition(sname_subst_elem.get("search-line"), sname_subst_elem.get("search-regex"))
				content = sname_subst_elem.text
				content_lines = content.splitlines()
				content_dict = {}
				for line in content_lines:
					line = line.rstrip(",").strip().replace("\t", "")
					if line:
						k,v = line.split(":")
						content_dict[k] = v
				subst_item.substitions = content_dict
				result_obj[subst_item.search_key].append(subst_item)

	if not fileExists(USER_IPTV_PROVIDER_SUBSTITUTIONS_FILE % scheme):
		return {}, {}
	fd = open(USER_IPTV_PROVIDER_SUBSTITUTIONS_FILE % scheme, 'rb')
	result = make_result_obj()
	result_epg = make_result_obj()
	for subst, elem in iterparse(fd):
		if elem.tag == "substitutions":
			subIter(elem.findall("servicename"), result)
			subIter(elem.findall("epgid"), result_epg)
	return result, result_epg

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
				providerObj.play_system_catchup = provider.find("system_catchup").text if provider.find("system_catchup") is not None and provider.find("system_catchup").text is not None else providerObj.play_system
				providerObj.catchup_type = int(provider.find("catchup_type").text) if provider.find("catchup_type") is not None and provider.find("catchup_type").text is not None else str(CATCHUP_DEFAULT)
				providerObj.ignore_vod = provider.find("novod") is not None and provider.find("novod").text == "on"
				providerObj.static_urls = provider.find("staticurl") is not None and provider.find("staticurl").text == "on"
				providerObj.onid = int(provider.find("onid").text)
				providerObj.create_epg = provider.find("epg") is not None and provider.find("epg").text == "on"
				providerObj.epg_url = provider.find("epg_url").text or providerObj.epg_url if provider.find("epg_url") is not None and provider.find("epg_url").text is not None else providerObj.epg_url
				providerObj.is_custom_xmltv = provider.find("is_custom_xmltv") is not None and provider.find("is_custom_xmltv").text == "on"
				providerObj.custom_xmltv_url = provider.find("custom_xmltv_url").text if provider.find("custom_xmltv_url") is not None and provider.find("custom_xmltv_url").text is not None else providerObj.custom_xmltv_url
				providerObj.picons = provider.find("picons") is not None and provider.find("picons").text == "on"
				providerObj.picon_gen_strategy = int(provider.find("picon_gen_strategy").text) if provider.find("picon_gen_strategy") is not None else 0
				providerObj.create_bouquets_strategy = int(provider.find("create_bouquets_strategy").text) if provider.find("create_bouquets_strategy") is not None else 0
				providerObj.use_provider_tsid = provider.find("use_provider_tsid") is not None and provider.find("use_provider_tsid").text == "on"
				providerObj.user_provider_ch_num = provider.find("user_provider_ch_num") is not None and provider.find("user_provider_ch_num").text == "on"
				providerObj.epg_match_strategy = int(provider.find("epg_match_strategy").text) if provider.find("epg_match_strategy") is not None else 0
				providerObj.custom_user_agent = provider.find("custom_user_agent").text if provider.find("custom_user_agent") is not None else "off"
				providerObj.ch_order_strategy = int(provider.find("ch_order_strategy").text) if provider.find("ch_order_strategy") is not None else 0
				if provider.find("provider_tsid_search_criteria") is not None:
					providerObj.provider_tsid_search_criteria = provider.find("provider_tsid_search_criteria").text
				providerObj.auto_updates = provider.find("auto_updates") is not None and provider.find("auto_updates").text == "on"

				# media library nodes
				providerObj.has_media_library = provider.find("has_media_library") is not None and provider.find("has_media_library").text == "on"
				providerObj.media_library_type = provider.find("media_library_type").text if provider.find("media_library_type") is not None else "xc"
				providerObj.media_library_url = provider.find("media_library_url").text if provider.find("media_library_url") is not None and provider.find("media_library_url").text is not None else ""
				providerObj.media_library_username = provider.find("media_library_username").text if provider.find("media_library_username") is not None and provider.find("media_library_username").text is not None else ""
				providerObj.media_library_password = provider.find("media_library_password").text if provider.find("media_library_password") is not None and provider.find("media_library_password").text is not None else ""
				providerObj.media_library_token = provider.find("media_library_token").text if provider.find("media_library_token") is not None and provider.find("media_library_token").text is not None else ""

				if providerObj.has_media_library:
					providerObj.media_library_object = XtreemProvider()
					providerObj.media_library_object.scheme = providerObj.scheme
					providerObj.media_library_object.url = providerObj.media_library_url
					providerObj.media_library_object.ignore_vod = False
					providerObj.media_library_object.create_epg = False
					if providerObj.media_library_type == "xc":
						providerObj.media_library_object.username = providerObj.media_library_username
						providerObj.media_library_object.password = providerObj.media_library_password
					else:
						providerObj.media_library_object.username = providerObj.media_library_token
						providerObj.media_library_object.password = providerObj.media_library_token

				makedirs(PROVIDER_FOLDER % providerObj.scheme, exist_ok=True) # create provider subfolder if not exists
				providerObj.loadMedialLibraryItems()
				providerObj.servicename_substitutions, providerObj.epg_substitions = readSubstitions(providerObj.scheme)

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
				providerObj.play_system_catchup = provider.find("system_catchup").text if provider.find("system_catchup") is not None and provider.find("system_catchup").text is not None else providerObj.play_system
				providerObj.create_epg = provider.find("epg") is not None and provider.find("epg").text == "on"
				providerObj.ignore_vod = provider.find("novod") is not None and provider.find("novod").text == "on"
				providerObj.onid = int(provider.find("onid").text)
				providerObj.server_timezone_offset = int(provider.find("server_timezone_offset").text) if provider.find("server_timezone_offset") is not None else providerObj.server_timezone_offset
				providerObj.is_custom_xmltv = provider.find("is_custom_xmltv") is not None and provider.find("is_custom_xmltv").text == "on"
				providerObj.custom_xmltv_url = provider.find("custom_xmltv_url").text if provider.find("custom_xmltv_url") is not None and provider.find("custom_xmltv_url").text is not None else providerObj.custom_xmltv_url
				providerObj.use_provider_tsid = provider.find("use_provider_tsid") is not None and provider.find("use_provider_tsid").text == "on"
				providerObj.user_provider_ch_num = provider.find("user_provider_ch_num") is not None and provider.find("user_provider_ch_num").text == "on"
				providerObj.custom_user_agent = provider.find("custom_user_agent").text if provider.find("custom_user_agent") is not None else "off"
				providerObj.output_format = provider.find("output_format").text if provider.find("output_format") is not None and provider.find("output_format").text is not None else providerObj.output_format
				providerObj.ch_order_strategy = int(provider.find("ch_order_strategy").text) if provider.find("ch_order_strategy") is not None else 0
				if provider.find("provider_tsid_search_criteria") is not None:
					providerObj.provider_tsid_search_criteria = provider.find("provider_tsid_search_criteria").text
				makedirs(PROVIDER_FOLDER % providerObj.scheme, exist_ok=True) # create provider subfolder if not exists
				providerObj.loadInfoFromFile()
				providerObj.loadMedialLibraryItems()
				providerObj.picons = provider.find("picons") is not None and provider.find("picons").text == "on"
				providerObj.picon_gen_strategy = int(provider.find("picon_gen_strategy").text) if provider.find("picon_gen_strategy") is not None else 0
				providerObj.create_bouquets_strategy = int(provider.find("create_bouquets_strategy").text) if provider.find("create_bouquets_strategy") is not None else 0
				providerObj.auto_updates = provider.find("auto_updates") is not None and provider.find("auto_updates").text == "on"
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
				providerObj.play_system_catchup = provider.find("system_catchup").text if provider.find("system_catchup") is not None and provider.find("system_catchup").text is not None else providerObj.play_system
				providerObj.create_epg = provider.find("epg") is not None and provider.find("epg").text == "on"
				providerObj.ignore_vod = provider.find("novod") is not None and provider.find("novod").text == "on"
				providerObj.onid = int(provider.find("onid").text)
				providerObj.picons = provider.find("picons") is not None and provider.find("picons").text == "on"
				providerObj.picon_gen_strategy = int(provider.find("picon_gen_strategy").text) if provider.find("picon_gen_strategy") is not None else 0
				providerObj.use_provider_tsid = provider.find("use_provider_tsid") is not None and provider.find("use_provider_tsid").text == "on"
				providerObj.user_provider_ch_num = provider.find("user_provider_ch_num") is not None and provider.find("user_provider_ch_num").text == "on"
				providerObj.custom_user_agent = provider.find("custom_user_agent").text if provider.find("custom_user_agent") is not None else "off"
				providerObj.output_format = provider.find("output_format").text if provider.find("output_format") is not None and provider.find("output_format").text is not None else providerObj.output_format
				providerObj.ch_order_strategy = int(provider.find("ch_order_strategy").text) if provider.find("ch_order_strategy") is not None else 0
				providerObj.epg_time_offset = int(provider.find("epg_time_offset").text) if provider.find("epg_time_offset") is not None else providerObj.epg_time_offset
				providerObj.server_time_offset = provider.find("server_time_offset").text if provider.find("server_time_offset") is not None and provider.find("server_time_offset").text is not None else ""
				if provider.find("provider_tsid_search_criteria") is not None:
					providerObj.provider_tsid_search_criteria = provider.find("provider_tsid_search_criteria").text
				makedirs(PROVIDER_FOLDER % providerObj.scheme, exist_ok=True) # create provider subfolder if not exists
				providerObj.loadInfoFromFile()
				providerObj.loadMedialLibraryItems()
				providerObj.create_bouquets_strategy = int(provider.find("create_bouquets_strategy").text) if provider.find("create_bouquets_strategy") is not None else 0
				providerObj.portal_entry_point_type = int(provider.find("portal_entry_point_type").text) if provider.find("portal_entry_point_type") is not None else -1
				providerObj.auto_updates = provider.find("auto_updates") is not None and provider.find("auto_updates").text == "on"
				providers[providerObj.scheme] = providerObj
			for provider in elem.findall("tvhprovider"):
				providerObj = TVHeadendProvider()
				providerObj.type = "TVH"
				providerObj.scheme = provider.find("scheme").text
				providerObj.iptv_service_provider = provider.find("servicename").text
				providerObj.url = provider.find("url").text
				providerObj.refresh_interval = int(provider.find("refresh_interval").text)
				providerObj.username = provider.find("username").text
				providerObj.password = provider.find("password").text
				providerObj.play_system = provider.find("system").text
				providerObj.play_system_catchup = provider.find("system_catchup").text if provider.find("system_catchup") is not None and provider.find("system_catchup").text is not None else providerObj.play_system
				providerObj.create_epg = provider.find("epg") is not None and provider.find("epg").text == "on"
				providerObj.ignore_vod = provider.find("novod") is not None and provider.find("novod").text == "on"
				providerObj.onid = int(provider.find("onid").text)
				providerObj.is_custom_xmltv = provider.find("is_custom_xmltv") is not None and provider.find("is_custom_xmltv").text == "on"
				providerObj.custom_xmltv_url = provider.find("custom_xmltv_url").text if provider.find("custom_xmltv_url") is not None and provider.find("custom_xmltv_url").text is not None else providerObj.custom_xmltv_url
				providerObj.picons = provider.find("picons") is not None and provider.find("picons").text == "on"
				providerObj.picon_gen_strategy = int(provider.find("picon_gen_strategy").text) if provider.find("picon_gen_strategy") is not None else 0
				providerObj.create_bouquets_strategy = int(provider.find("create_bouquets_strategy").text) if provider.find("create_bouquets_strategy") is not None else 0
				providerObj.use_provider_tsid = provider.find("use_provider_tsid") is not None and provider.find("use_provider_tsid").text == "on"
				providerObj.user_provider_ch_num = provider.find("user_provider_ch_num") is not None and provider.find("user_provider_ch_num").text == "on"
				providerObj.custom_user_agent = provider.find("custom_user_agent").text if provider.find("custom_user_agent") is not None else "off"
				providerObj.ch_order_strategy = int(provider.find("ch_order_strategy").text) if provider.find("ch_order_strategy") is not None else 0
				if provider.find("provider_tsid_search_criteria") is not None:
					providerObj.provider_tsid_search_criteria = provider.find("provider_tsid_search_criteria").text
				providerObj.auto_updates = provider.find("auto_updates") is not None and provider.find("auto_updates").text == "on"
				providerObj.last_vod_update_time = float(provider.find("last_vod_update_time").text) if provider.find("last_vod_update_time") is not None else 0
				makedirs(PROVIDER_FOLDER % providerObj.scheme, exist_ok=True) # create provider subfolder if not exists
				providers[providerObj.scheme] = providerObj
			for provider in elem.findall("vodprovider"):
				providerObj = VODProvider()
				providerObj.type = "VOD"
				providerObj.playlist_type = provider.find("playlist_type").text if provider.find("playlist_type") is not None and provider.find("playlist_type").text is not None else providerObj.playlist_type
				providerObj.scheme = provider.find("scheme").text
				providerObj.iptv_service_provider = provider.find("servicename").text
				providerObj.url = provider.find("url").text
				providerObj.ignore_vod = False
				providerObj.onid = int(provider.find("onid").text)
				providerObj.auto_updates = provider.find("auto_updates") is not None and provider.find("auto_updates").text == "on"
				makedirs(PROVIDER_FOLDER % providerObj.scheme, exist_ok=True) # create provider subfolder if not exists
				providerObj.loadMedialLibraryItems()
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
			xml.append(f"\t\t<is_custom_xmltv>{'on' if val.is_custom_xmltv else 'off'}</is_custom_xmltv>\n")
			xml.append(f"\t\t<custom_xmltv_url><![CDATA[{val.custom_xmltv_url}]]></custom_xmltv_url>\n")
			xml.append(f"\t\t<picons>{'on' if val.picons else 'off'}</picons>\n")
			xml.append(f"\t\t<picon_gen_strategy>{val.picon_gen_strategy}</picon_gen_strategy>\n")
			xml.append(f"\t\t<create_bouquets_strategy>{val.create_bouquets_strategy}</create_bouquets_strategy>\n")
			xml.append(f"\t\t<use_provider_tsid>{'on' if val.use_provider_tsid else 'off'}</use_provider_tsid>\n")
			xml.append(f"\t\t<user_provider_ch_num>{'on' if val.user_provider_ch_num else 'off'}</user_provider_ch_num>\n")
			xml.append(f"\t\t<provider_tsid_search_criteria>{val.provider_tsid_search_criteria}</provider_tsid_search_criteria>\n")
			xml.append(f"\t\t<epg_match_strategy>{val.epg_match_strategy}</epg_match_strategy>\n")
			xml.append(f"\t\t<custom_user_agent>{val.custom_user_agent}</custom_user_agent>\n")
			xml.append(f"\t\t<ch_order_strategy>{val.ch_order_strategy}</ch_order_strategy>\n")
			xml.append(f"\t\t<auto_updates>{'on' if val.auto_updates else 'off'}</auto_updates>\n")

			# media library nodes
			xml.append(f"\t\t<has_media_library>{'on' if val.has_media_library else 'off'}</has_media_library>\n")
			xml.append(f"\t\t<media_library_type>{val.media_library_type}</media_library_type>\n")
			xml.append(f"\t\t<media_library_url><![CDATA[{val.media_library_url}]]></media_library_url>\n")
			xml.append(f"\t\t<media_library_username><![CDATA[{val.media_library_username}]]></media_library_username>\n")
			xml.append(f"\t\t<media_library_password><![CDATA[{val.media_library_password}]]></media_library_password>\n")
			xml.append(f"\t\t<media_library_token><![CDATA[{val.media_library_token}]]></media_library_token>\n")

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
			xml.append(f"\t\t<server_timezone_offset>{val.server_timezone_offset}</server_timezone_offset><!-- timezone offset of the server in seconds from the perspective of the client -->\n")
			xml.append(f"\t\t<is_custom_xmltv>{'on' if val.is_custom_xmltv else 'off'}</is_custom_xmltv>\n")
			xml.append(f"\t\t<custom_xmltv_url><![CDATA[{val.custom_xmltv_url}]]></custom_xmltv_url>\n")
			xml.append(f"\t\t<picons>{'on' if val.picons else 'off'}</picons>\n")
			xml.append(f"\t\t<picon_gen_strategy>{val.picon_gen_strategy}</picon_gen_strategy>\n")
			xml.append(f"\t\t<create_bouquets_strategy>{val.create_bouquets_strategy}</create_bouquets_strategy>\n")
			xml.append(f"\t\t<use_provider_tsid>{'on' if val.use_provider_tsid else 'off'}</use_provider_tsid>\n")
			xml.append(f"\t\t<user_provider_ch_num>{'on' if val.user_provider_ch_num else 'off'}</user_provider_ch_num>\n")
			xml.append(f"\t\t<provider_tsid_search_criteria>{val.provider_tsid_search_criteria}</provider_tsid_search_criteria>\n")
			xml.append(f"\t\t<custom_user_agent>{val.custom_user_agent}</custom_user_agent>\n")
			xml.append(f"\t\t<output_format>{val.output_format}</output_format>\n")
			xml.append(f"\t\t<ch_order_strategy>{val.ch_order_strategy}</ch_order_strategy>\n")
			xml.append(f"\t\t<auto_updates>{'on' if val.auto_updates else 'off'}</auto_updates>\n")
			xml.append("\t</xtreemprovider>\n")
		elif isinstance(val, TVHeadendProvider):
			xml.append("\t<tvhprovider>\n")
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
			xml.append(f"\t\t<server_timezone_offset>{val.server_timezone_offset}</server_timezone_offset><!-- timezone offset of the server in seconds from the perspective of the client -->\n")
			xml.append(f"\t\t<is_custom_xmltv>{'on' if val.is_custom_xmltv else 'off'}</is_custom_xmltv>\n")
			xml.append(f"\t\t<custom_xmltv_url><![CDATA[{val.custom_xmltv_url}]]></custom_xmltv_url>\n")
			xml.append(f"\t\t<picons>{'on' if val.picons else 'off'}</picons>\n")
			xml.append(f"\t\t<picon_gen_strategy>{val.picon_gen_strategy}</picon_gen_strategy>\n")
			xml.append(f"\t\t<create_bouquets_strategy>{val.create_bouquets_strategy}</create_bouquets_strategy>\n")
			xml.append(f"\t\t<use_provider_tsid>{'on' if val.use_provider_tsid else 'off'}</use_provider_tsid>\n")
			xml.append(f"\t\t<user_provider_ch_num>{'on' if val.user_provider_ch_num else 'off'}</user_provider_ch_num>\n")
			xml.append(f"\t\t<provider_tsid_search_criteria>{val.provider_tsid_search_criteria}</provider_tsid_search_criteria>\n")
			xml.append(f"\t\t<custom_user_agent>{val.custom_user_agent}</custom_user_agent>\n")
			xml.append(f"\t\t<ch_order_strategy>{val.ch_order_strategy}</ch_order_strategy>\n")
			xml.append(f"\t\t<auto_updates>{'on' if val.auto_updates else 'off'}</auto_updates>\n")
			xml.append("\t</tvhprovider>\n")
		elif isinstance(val, StalkerProvider):
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
			xml.append(f"\t\t<epg_time_offset>{val.epg_time_offset}</epg_time_offset>\n")
			xml.append(f"\t\t<onid>{val.onid}</onid>\n")
			xml.append(f"\t\t<picons>{'on' if val.picons else 'off'}</picons>\n")
			xml.append(f"\t\t<picon_gen_strategy>{val.picon_gen_strategy}</picon_gen_strategy>\n")
			xml.append(f"\t\t<create_bouquets_strategy>{val.create_bouquets_strategy}</create_bouquets_strategy>\n")
			xml.append(f"\t\t<use_provider_tsid>{'on' if val.use_provider_tsid else 'off'}</use_provider_tsid>\n")
			xml.append(f"\t\t<user_provider_ch_num>{'on' if val.user_provider_ch_num else 'off'}</user_provider_ch_num>\n")
			xml.append(f"\t\t<provider_tsid_search_criteria>{val.provider_tsid_search_criteria}</provider_tsid_search_criteria>\n")
			xml.append(f"\t\t<custom_user_agent>{val.custom_user_agent}</custom_user_agent>\n")
			xml.append(f"\t\t<output_format>{val.output_format}</output_format>\n")
			xml.append(f"\t\t<ch_order_strategy>{val.ch_order_strategy}</ch_order_strategy>\n")
			xml.append(f"\t\t<server_time_offset>{val.server_timezone_offset}</server_time_offset>\n")
			xml.append(f"\t\t<portal_entry_point_type>{val.portal_entry_point_type}</portal_entry_point_type>\n")
			xml.append(f"\t\t<auto_updates>{'on' if val.auto_updates else 'off'}</auto_updates>\n")
			xml.append(f"\t\t<last_vod_update_time>{val.last_vod_update_time}</last_vod_update_time>\n")
			xml.append("\t</stalkerprovider>\n")
		else:
			xml.append("\t<vodprovider>\n")
			xml.append(f"\t\t<servicename>{val.iptv_service_provider}</servicename>\n")
			xml.append(f"\t\t<playlist_type>{val.playlist_type}</playlist_type>\n")
			xml.append(f"\t\t<url><![CDATA[{val.url}]]></url>\n")
			xml.append(f"\t\t<novod>{'on' if val.ignore_vod else 'off'}</novod>\n")
			xml.append(f"\t\t<scheme><![CDATA[{val.scheme}]]></scheme>\n")
			xml.append(f"\t\t<onid>{val.onid}</onid>\n")
			xml.append(f"\t\t<auto_updates>{'on' if val.auto_updates else 'off'}</auto_updates>\n")
			xml.append("\t</vodprovider>\n")
	xml.append("</providers>\n")
	makedirs(path.dirname(USER_IPTV_PROVIDERS_FILE), exist_ok=True)  # create config folder recursive if not exists
	makedirs(PROVIDER_FOLDER % val.scheme, exist_ok=True) # create provider subfolder if not exists
	with write_lock:
		f = open(USER_IPTV_PROVIDERS_FILE + ".writing", 'w')
		f.write("".join(xml))
		f.flush()
		fsync(f.fileno())
		f.close()
		rename(USER_IPTV_PROVIDERS_FILE + ".writing", USER_IPTV_PROVIDERS_FILE)

# Function for overwrite/extend some functions from Navigation.py so to inject own code
def injectIntoNavigation(session):
	import NavigationInstance
	if hasattr(NavigationInstance.instance, "playServiceExtensions") and playServiceExtension not in NavigationInstance.instance.playServiceExtensions:
		NavigationInstance.instance.playServiceExtensions.append(playServiceExtension)
	elif not hasattr(NavigationInstance.instance, "playServiceExtensions"):
		if not hasattr(NavigationInstance.instance, "firstStart"):
			NavigationInstance.instance.firstStart = False
		Navigation.originalPlayingServiceReference = None
		NavigationInstance.instance.playService = playServiceWithIPTVATV.__get__(NavigationInstance.instance, Navigation)
	if hasattr(NavigationInstance.instance, "recordServiceExtensions") and record_pipServiceExtension not in NavigationInstance.instance.recordServiceExtensions:
		NavigationInstance.instance.recordServiceExtensions.append(record_pipServiceExtension)
	elif not hasattr(NavigationInstance.instance, "recordServiceExtensions"):
		NavigationInstance.instance.recordService = recordServiceWithIPTVATV.__get__(NavigationInstance.instance, Navigation)
	if hasattr(PictureInPicture, "playServiceExtensions") and record_pipServiceExtension not in PictureInPicture.playServiceExtensions:
		PictureInPicture.playServiceExtensions.append(record_pipServiceExtension)
	elif not hasattr(PictureInPicture, "playServiceExtensions"):
		PictureInPicture.playService = playServiceWithIPTVPiPATV
	if QuadPiP and hasattr(QuadPiP, "playServiceExtensions" ) and playServiceQPiPExtension not in QuadPiP.playServiceExtensions:
		QuadPiP.playServiceExtensions.append(playServiceQPiPExtension)

	NavigationInstance.instance.playRealService = playRealService.__get__(NavigationInstance.instance, Navigation)

	if not hasattr(NavigationInstance.instance, "getCurrentServiceReferenceOriginal"):
		NavigationInstance.instance.getCurrentServiceReferenceOriginal = getCurrentServiceReferenceOriginal.__get__(NavigationInstance.instance, Navigation)
		NavigationInstance.instance.getCurrentlyPlayingServiceOrGroup = getCurrentlyPlayingServiceOrGroup.__get__(NavigationInstance.instance, Navigation)

	injectCatchupInEPG()
	overwriteEPGImportEPGSourceInit()

def getCurrentServiceReferenceOriginal(self):
	return self.originalPlayingServiceReference

def getCurrentlyPlayingServiceOrGroup(self):
	if not self.currentlyPlayingServiceOrGroup:
		return None
	return self.originalPlayingServiceReference or self.currentlyPlayingServiceOrGroup

def playServiceQPiPExtension(instance, playref):
	return playServiceExtension(None, playref, None, None)


def playServiceExtension(navigation_instance, playref, event, infoBar_instance):
	if callable(processIPTVService):
		result = processIPTVService(playref, navigation_instance and navigation_instance.playRealService, event)
		playref = result[0]
		if infoBar_instance:
			infoBar_instance.session.screen["Event_Now"].updateSource(playref)
			infoBar_instance.session.screen["Event_Next"].updateSource(playref)
		return result[0], result[2]
	return playref, False
		
def record_pipServiceExtension(navigation_instance, playref):
	if callable(processIPTVService):
		return processIPTVService(playref, None)[0]
	return playref

def playServiceWithIPTVATV(self, ref, checkParentalControl=True, forceRestart=False, adjust=True, ignoreStreamRelay=False, event=None):
		oldref = self.currentlyPlayingServiceOrGroup
		if ref and oldref and ref == oldref and not forceRestart:
			print("[Navigation] Ignore request to play already running service.  (1)")
			return 1
		if ref is None:
			self.stopService()
			return 0
		from Components.ServiceEventTracker import InfoBarCount
		InfoBarInstance = InfoBarCount == 1 and InfoBar.instance
		isStreamRelay = False
		if not checkParentalControl or parentalControl.isServicePlayable(ref, boundFunction(self.playService, checkParentalControl=False, forceRestart=forceRestart, adjust=adjust)):
			if ref.flags & eServiceReference.isGroup:
				oldref = self.currentlyPlayingServiceReference or eServiceReference()
				playref = getBestPlayableServiceReference(ref, oldref)
				if not ignoreStreamRelay:
					playref, isStreamRelay = streamrelay.streamrelayChecker(playref)
				if not isStreamRelay:
					try: # OpenATV 7.4 support
						playref, wrappererror = self.serviceHook(playref)
						if wrappererror:
							return 1
					except:
						pass
				print(f"[Navigation] Playref is '{str(playref)}'.")
				if playref and oldref and playref == oldref and not forceRestart:
					print("[Navigation] Ignore request to play already running service.  (2)")
					return 1
				if not playref:
					alternativeref = getBestPlayableServiceReference(ref, eServiceReference(), True)
					self.stopService()
					if alternativeref and self.pnav:
						self.currentlyPlayingServiceReference = alternativeref
						self.currentlyPlayingServiceOrGroup = ref
						if self.pnav.playService(alternativeref):
							print(f"[Navigation] Failed to start '{alternativeref.toString()}'.")
							self.currentlyPlayingServiceReference = None
							self.currentlyPlayingServiceOrGroup = None
							if oldref and ("://" in oldref.getPath() or streamrelay.checkService(oldref)):
								print("[Navigation] Streaming was active, try again.")  # Use timer to give the stream server the time to deallocate the tuner.
								self.retryServicePlayTimer = eTimer()
								self.retryServicePlayTimer.callback.append(boundFunction(self.playService, ref, checkParentalControl, forceRestart, adjust))
								self.retryServicePlayTimer.start(500, True)
						else:
							print(f"[Navigation] Alternative ref as simulate is '{alternativeref.toString()}'.")
					return 0
				elif checkParentalControl and not parentalControl.isServicePlayable(playref, boundFunction(self.playService, checkParentalControl=False)):
					if self.currentlyPlayingServiceOrGroup and InfoBarInstance and InfoBarInstance.servicelist.servicelist.setCurrent(self.currentlyPlayingServiceOrGroup, adjust):
						self.currentlyPlayingServiceOrGroup = InfoBarInstance.servicelist.servicelist.getCurrent()
					return 1
			else:
				playref = ref
			if self.pnav:
				if not BoxInfo.getItem("FCCactive"):
					self.pnav.stopService()
				else:
					self.skipServiceReferenceReset = True
				self.currentlyPlayingServiceReference = playref
				if not ignoreStreamRelay:
					playref, isStreamRelay = streamrelay.streamrelayChecker(playref)
				if not isStreamRelay:
					try: # OpenATV 7.4 support
						playref, wrappererror = self.serviceHook(playref)
						if wrappererror:
							return 1
					except:
						pass
				is_dynamic = False
				if callable(processIPTVService):
					playref, old_ref, is_dynamic, ref_type = processIPTVService(playref, self.playRealService, event)
				print(f"[Navigation] Playref is '{playref.toString()}'.")
				self.currentlyPlayingServiceOrGroup = ref
				if InfoBarInstance and InfoBarInstance.servicelist.servicelist.setCurrent(ref, adjust):
					self.currentlyPlayingServiceOrGroup = InfoBarInstance.servicelist.servicelist.getCurrent()
				# self.skipServiceReferenceReset = True
				if (config.misc.softcam_streamrelay_delay.value and self.isCurrentServiceStreamRelay) or (self.firstStart and isStreamRelay):
					self.skipServiceReferenceReset = False
					self.isCurrentServiceStreamRelay = False
					self.currentlyPlayingServiceReference = None
					self.currentlyPlayingServiceOrGroup = None
					print("[Navigation] Stream relay was active, delay the zap till tuner is freed.")
					self.retryServicePlayTimer = eTimer()
					self.retryServicePlayTimer.callback.append(boundFunction(self.playService, ref, checkParentalControl, forceRestart, adjust))
					delay = 2000 if self.firstStart else config.misc.softcam_streamrelay_delay.value
					self.firstStart = False
					self.retryServicePlayTimer.start(delay, True)
					return 0
				elif not is_dynamic and self.pnav.playService(playref):
					print(f"[Navigation] Failed to start '{playref.toString()}'.")
					self.currentlyPlayingServiceReference = None
					self.currentlyPlayingServiceOrGroup = None
					if oldref and ("://" in oldref.getPath() or streamrelay.checkService(oldref)):
						print("[Navigation] Streaming was active, try again.")  # Use timer to give the stream server the time to deallocate the tuner.
						self.retryServicePlayTimer = eTimer()
						self.retryServicePlayTimer.callback.append(boundFunction(self.playService, ref, checkParentalControl, forceRestart, adjust))
						self.retryServicePlayTimer.start(500, True)
				self.skipServiceReferenceReset = False
				if isStreamRelay and not self.isCurrentServiceStreamRelay:
					self.isCurrentServiceStreamRelay = True
				return 0
		elif oldref and InfoBarInstance and InfoBarInstance.servicelist.servicelist.setCurrent(oldref, adjust):
			self.currentlyPlayingServiceOrGroup = InfoBarInstance.servicelist.servicelist.getCurrent()
		return 1

def playServiceWithIPTVPiPATV(self, service):
		if service is None:
			return False
		from Screens.InfoBarGenerics import streamrelay
		from .IPTVProviders import processService
		ref, isStreamRelay = streamrelay.streamrelayChecker(self.resolveAlternatePipService(service))
		ref = processService(ref, None)[0]
		if ref:
			import Tools.Notifications
			if self.isPlayableForPipService(ref):
				print("playing pip service", ref and ref.toString())
			else:
				if not config.usage.hide_zap_errors.value:
					Tools.Notifications.AddPopup(text=_("No free tuner!"), type=MessageBox.TYPE_ERROR, timeout=5, id="ZapPipError")
				return False
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
					Tools.Notifications.AddPopup(text=_("Incorrect type service for PiP!"), type=MessageBox.TYPE_ERROR, timeout=5, id="ZapPipError")
		return False

def recordServiceWithIPTVATV(self, ref, simulate=False, type=8):
		import ServiceReference
		service = None
		if not simulate:
			print(f"[Navigation] Recording service is '{str(ref)}'.")
		if isinstance(ref, ServiceReference.ServiceReference):
			ref = ref.ref
		if ref:
			if ref.flags & eServiceReference.isGroup:
				ref = getBestPlayableServiceReference(ref, eServiceReference(), simulate)
			if type != (pNavigation.isPseudoRecording | pNavigation.isFromEPGrefresh):
				ref, isStreamRelay = streamrelay.streamrelayChecker(ref)
				ref = processIPTVService(ref, None)[0]
			service = ref and self.pnav and self.pnav.recordService(ref, simulate, type)
			if service is None:
				print("[Navigation] Record returned non-zero.")
		return service

def playRealService(self, nnref):
	# self.pnav.stopService()
	self.currentlyPlayingServiceReference = nnref
	self.pnav.playService(nnref)

	from Components.ServiceEventTracker import InfoBarCount
	InfoBarInstance = InfoBarCount == 1 and InfoBar.instance
	if InfoBarInstance and distro not in type2_distros:
		current_service_source = InfoBarInstance.session.screen["CurrentService"]
		if hasattr(current_service_source, "newService"):
			if "%3a//" in nnref.toString():
				current_service_source.newService(nnref)
			else:
				current_service_source.newService(True)

		InfoBarInstance.serviceStarted()

class VoDMoviePlayer(MoviePlayer, SubsSupport, SubsSupportStatus):
	def __init__(self, session, service, slist=None, lastservice=None):
		MoviePlayer.__init__(self, session, service=service, slist=slist, lastservice=lastservice)
		SubsSupport.__init__(self, searchSupport=True, embeddedSupport=True)
		SubsSupportStatus.__init__(self)
		self.skinName = ["CatchupPlayer", "VoDMoviePlayer", "MoviePlayer"]
		self.onPlayStateChanged.append(self.__playStateChanged)
		self.skip_progress_update = False
		self.current_seek_step = 0
		self.current_pos = -1
		self["progress"] = Progress()
		self["progress_summary"] = Progress()
		self["progress"].value = 0
		self["progress_summary"].value = 0
		self["time_info"] = Label("")
		self["time_elapsed"] = Label("")
		self["time_duration"] = Label("")
		self["time_remaining"] = Label("")
		self["time_info_summary"] = StaticText("")
		self["time_elapsed_summary"] = StaticText("")
		self["time_duration_summary"] = StaticText("")
		self["time_remaining_summary"] = StaticText("")
		self.progress_timer = eTimer()
		self.progress_timer.callback.append(self.onProgressTimer)
		self.onProgressTimer()
		self.seek_timer = eTimer()
		self.seek_timer.callback.append(self.onSeekRequest)
		self["NumberSeekActions"] = NumberActionMap(["NumberActions"],
		{
			"1": self.numberSeek,
			"3": self.numberSeek,
			"4": self.numberSeek,
			"6": self.numberSeek,
			"7": self.numberSeek,
			"9": self.numberSeek,
		}, -10)  # noqa: E123
		self.__event_tracker = ServiceEventTracker(screen=self, eventmap={
			iPlayableService.evStart: self.__evServiceStart,
			iPlayableService.evEnd: self.__evServiceEnd,})
		
	def getLength(self):
		seek = self.getSeek()
		if seek is None:
			return None
		length = seek.getLength()
		if length[0]:
			return 0
		return length[1] / 90000
	
	def getPosition(self):
		seek = self.getSeek()
		if seek is None:
			return None
		pos = seek.getPlayPosition()
		if pos[0]:
			return 0
		return pos[1] / 90000

	def numberSeek(self, key):
		if self.getSeek() is None:  # not currently seekable, so skip this key press
			return
		self.seek_timer.stop()
		p = self.getPosition()
		self.current_seek_step += {1: - config.seek.selfdefined_13.value, 3: config.seek.selfdefined_13.value, 4: - config.seek.selfdefined_46.value, 6: config.seek.selfdefined_46.value, 7: - config.seek.selfdefined_79.value, 9: config.seek.selfdefined_79.value}[key]
		self.progress_timer.stop()
		self.seek_timer.start(1000, 1)
		p += self.current_seek_step
		self.skip_progress_update = True
		self.current_pos = p
		self.setProgress(p)
		self.showAfterSeek()  # show infobar

	def onSeekRequest(self):
		self.seek_timer.stop()
		self.doSeekRelative(self.current_seek_step * 90000)
		self.current_seek_step = 0
		self.current_pos = -1
		self.skip_progress_update = False
		self.progress_timer.start(1000)

	def setProgress(self, pos):
		len = self.getLength()
		if len == 0:
			self["progress"].value = 0
			self["progress_summary"].value = 0
			text = "-00:00:00         00:00:00         +00:00:00"
			self["time_info"].setText(text)
			self["time_info_summary"].setText(text)
			text_elapsed = "-00:00:00"
			self["time_elapsed"].setText(text_elapsed)
			self["time_elapsed_summary"].setText(text_elapsed)
			text_duration = "00:00:00"
			self["time_duration"].setText(text_duration)
			self["time_duration_summary"].setText(text_duration)
			text_remaining = "+00:00:00"
			self["time_remaining"].setText(text_remaining)
			self["time_remaining_summary"].setText(text_remaining)
			return

		r = self.getLength() - pos  # Remaining
		progress_val = i if (i := int((pos / len) * 100)) and i >= 0 else 0
		self["progress"].value = progress_val
		self["progress_summary"].value = progress_val
		text = "-%d:%02d:%02d         %d:%02d:%02d         +%d:%02d:%02d" % (pos / 3600, pos % 3600 / 60, pos % 60, len / 3600, len % 3600 / 60, len % 60, r / 3600, r % 3600 / 60, r % 60)
		self["time_info"].setText(text)
		self["time_info_summary"].setText(text)
		text_elapsed = "-%d:%02d:%02d" % (pos / 3600, pos % 3600 / 60, pos % 60)
		self["time_elapsed"].setText(text_elapsed)
		self["time_elapsed_summary"].setText(text_elapsed)
		text_duration = "%d:%02d:%02d" % (len / 3600, len % 3600 / 60, len % 60)
		self["time_duration"].setText(text_duration)
		self["time_duration_summary"].setText(text_duration)
		text_remaining = "+%d:%02d:%02d" % (r / 3600, r % 3600 / 60, r % 60)
		self["time_remaining"].setText(text_remaining)
		self["time_remaining_summary"].setText(text_remaining)

	def onProgressTimer(self):
		curr_pos = self.getPosition()
		if not self.skip_progress_update:
			self.setProgress(curr_pos if self.current_pos == -1 else self.current_pos)

	def __evServiceStart(self):
		self.jumpPreviousNextMark(lambda x: 0, start=True) # Reset the stream to beginning since some network streams jumps to the end marker
		if self.progress_timer:
			self.progress_timer.start(1000)

	def __evServiceEnd(self):
		if self.progress_timer:
			self.progress_timer.stop()

	def __playStateChanged(self, state):
		playstateString = state[3]
		if playstateString == '>':
			self.progress_timer.start(1000)
		elif playstateString == '||':
			self.progress_timer.stop()
		elif playstateString == 'END':
			self.progress_timer.stop()

	def leavePlayer(self):
		self.setResumePoint()
		self.handleLeave("quit")

	def leavePlayerOnExit(self):
		if self.shown:
			self.hide()
		else:
			self.leavePlayer()

	def setResumePoint(self):
		service = self.session.nav.getCurrentService()
		ref = self.session.nav.getCurrentServiceReferenceOriginal()
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
		ref = self.session.nav.getCurrentServiceReferenceOriginal()
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
		 	<widget name="overlay" position="%d,%d" zPosition="12" size="%d,%d" halign="center" valign="center" font="Regular;%d" transparent="1" shadowColor="black" shadowOffset="-1,-1"/>
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
		 	<widget name="poster" position="%d,%d" size="%d,%d"/>
			<widget source="description" render="Label" position="%d,%d" zPosition="10" size="%d,%d" halign="center" valign="center" font="Regular;%d" transparent="1" shadowColor="black" shadowOffset="-1,-1" />
		</screen>""",
			980, 600,  # screen
			15, 60, 950, 430, 22,  # overlay
			15, 60, 640, 430,  # Listbox
			2, 0, 630, 26,  # template
			22,  # fonts
			26,  # ItemHeight
			665, 60, 300, 430,  # Poster
			5, 500, 940, 50, 22,  # description
			]  # noqa: E124

	def __init__(self, session):
		Screen.__init__(self, session)
		self.skinName = [self.skinName, "M3UIPTVVoDMovies"]
		self["list"] = List([])
		self["description"] = StaticText()
		self["overlay"] = Label(_("Please wait! Loading data from server."))
		self["overlay"].hide()
		self.picload = ePicLoad()
		self.picload.PictureData.get().append(self.showPic)
		self["poster"] = Pixmap()
		self.mode = self.MODE_GENRE
		self.allseries = {}
		allEpisodes = []
		self.all = _("All")
		for provider in providers:
			series = providers[provider].vod_series
			for genre in series:
				if genre not in self.allseries:
					self.allseries[genre] = []
				for series_id, name, plot, poster in series[genre]:
					if name:
						self.allseries[genre].append((series_id, name, provider, plot, poster))
						allEpisodes.append((series_id, name, provider, plot, poster))
		self.categories = list(sorted(self.allseries.keys()))
		self.allseries[self.all] = allEpisodes  # insert after the sort so it does not affect the sort
		self.categories.insert(0, self.all)  # insert "All" category at the start of the list
		self.category = self.categories[0] if self.categories else None
		self.stack = []
		self.episodes = []
		self.episodesHistory = [self.episodes]
		self.searchTexts = []
		self.searchTerms = []
		self.processing_cover = False
		self.deferred_cover_url = None

		if self.selectionChanged not in self["list"].onSelectionChanged:
			self["list"].onSelectionChanged.append(self.selectionChanged)

		self["key_red"] = StaticText(_("Cancel"))
		self["key_green"] = StaticText(_("Search"))
		self["key_yellow"] = StaticText()
		# self["key_blue"] = StaticText()

		self["actions"] = ActionMap(["M3UIPTVConfigActions", "M3UIPTVPlayActions"],
			{
				"cancel": self.keyCancel,  # KEY_RED / KEY_EXIT
				"save": self.keySearch,  # KEY_GREEN
				"ok": self.keySelect,
				"yellow": self.mdb,
				# "blue": self.blue,
				"play": self.key_play,
				"menu": self.closeRecursive,
			}, -1)  # noqa: E123
		self.buildList()
		# self.onClose.append(self.mdbCleanup)

	def showPic(self, picInfo=""):
		ptr = self.picload.getData()
		if ptr is not None:
			if not self.deferred_cover_url:
				self["poster"].instance.setPixmap(ptr.__deref__())
		self.processing_cover = False
		if self.deferred_cover_url:
			cover_url = self.deferred_cover_url
			self.deferred_cover_url = None
			threads.deferToThread(self.downloadCover, cover_url)

	def downloadCover(self, current_cover_url):
		if not current_cover_url:
			self["poster"].instance.setPixmap(None)
			return
		current_cover_url = current_cover_url.replace("\\", "")
		if self.deferred_cover_url and self.deferred_cover_url == current_cover_url:
			return
		
		if self.processing_cover:
			self.deferred_cover_url = current_cover_url
			return

		self.processing_cover = True
		if not self.deferred_cover_url:
			try:
				req = urllib.request.Request(current_cover_url, headers={
        										'User-Agent': REQUEST_USER_AGENT #'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/35.0.1916.47 Safari/537.36'
    										})
				response = urllib.request.urlopen(req, timeout=5)
				if response.status != 200:
					self.processing_cover = False
					self.deferred_cover_url = None
					self["poster"].instance.setPixmap(None)
					return
				makedirs('/tmp/M3UIPTV', exist_ok=True)
				with open('/tmp/M3UIPTV/poster.png', 'wb') as handler:
					handler.write(response.read())
				
				piconsize = self["poster"].instance.size()
				self.picload.setPara((piconsize.width(), piconsize.height(), 1, 1, 1, 1, '#FF111111'))
				
				if path.exists('/tmp/M3UIPTV/poster.png'):
					self.picload.startDecode('/tmp/M3UIPTV/poster.png')
				else:
					self["poster"].instance.setPixmap(None)
			except:
				self.processing_cover = False
				self.deferred_cover_url = None
				self["poster"].instance.setPixmap(None)

	def selectionChanged(self):
		current_cover_url = None
		if self.mode == self.MODE_GENRE:
			current_cover_url = None
			self["poster"].instance.setPixmap(None)
			self.processing_cover = False
		elif self.mode == self.MODE_EPISODE:
			if (current := self["list"].getCurrent()) and ((info := current[2]) is not None and (plot := info.get("plot")) is not None or current[4]):
				self["description"].text = (plot + " " if plot else "") + ("%s" % current[4] if current[4] else "")
				current_cover_url = current[6] or info.get("cover")
			else:
				self["description"].text = _("Press OK to access selected item")
				current_cover_url = None
				self["poster"].instance.setPixmap(None)
		elif self.mode == self.MODE_SERIES or self.mode == self.MODE_SEARCH:
			if (current := self["list"].getCurrent()) and (plot := current[3]):
				self["description"].text = plot
				current_cover_url = current[4]
			else:
				self["description"].text = _("Press OK to select a series")
				current_cover_url = None
				self["poster"].instance.setPixmap(None)
		if self.mode != self.MODE_GENRE and config.plugins.m3uiptv.display_poster.value:
			threads.deferToThread(self.downloadCover, current_cover_url)

	def keyCancel(self):
		lastmode, lastindex = self.popStack()
		if len(self.allseries) > 1 and (self.mode == self.MODE_SERIES or self.mode == self.MODE_SEARCH and lastmode == self.MODE_GENRE):
			self.mode = self.MODE_GENRE
			self.buildList()
			self["list"].index = lastindex
		elif self.mode in (self.MODE_EPISODE, self.MODE_SEARCH):
			self.mode = lastmode
			self.buildList()
			self["list"].index = lastindex
		else:
			self.close()

	def closeRecursive(self):
		self.close(True)

	def keySelect(self):
		if current := self["list"].getCurrent():
			if self.mode == self.MODE_GENRE:
				self.pushStack()
				self.mode = self.MODE_SERIES
				self.category = current[0]
				self.buildList()
				self["list"].index = 0
			elif self.mode in (self.MODE_SERIES, self.MODE_SEARCH):
				id = current[0]
				provider = current[2]
				self["overlay"].show()
				self["list"].master.master.hide()
				threads.deferToThread(self.getSeriesById, provider, id).addCallback(self.loadSeriesList)
			elif self.mode == self.MODE_EPISODE:
				self.playMovie()

	def getSeriesById(self, provider, id):
		try:
			self.episodes = providers[provider].getSeriesById(id)
			return True
		except (TimeoutError, HTTPError, URLError) as err:
			print("[M3UIPTVVoDSeries] keySelect, failure in getSeriesById, %s:" % type(err).__name__, err)
			return False
		
	def loadSeriesList(self, state):
		if not state:
			self["overlay"].hide()
			self["list"].master.master.show()
			self["list"].index = 0
			return
		if current := self["list"].getCurrent():
			self["overlay"].hide()
			self.pushStack()
			self.seriesName = current[1]
			self.mode = self.MODE_EPISODE
			self.buildList()
			self["list"].index = 0
			self["list"].master.master.show()


	def key_play(self):
		if self.mode == self.MODE_EPISODE:
			self.playMovie()

	def keySearch(self):
		if (current := self["list"].getCurrent()) and self.mode == self.MODE_GENRE:
			self.category = current[1]  # remember where we were (for when we use keyCancel)
		self.session.openWithCallback(self.keySearchCallback, VirtualKeyBoard, title=_("VoD Series: enter search terms"), text=" ".join(self.searchTerms))

	def keySearchCallback(self, retval=None):
		if retval is not None:
			if not self.searchTexts:
				self.searchTexts = [re.split(r"\b", series[1].lower()) for series in self.allseries[self.all]]
			self.searchTerms = retval.lower().split()
			self.pushStack()
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
		if not self.categories:
			return
		if path.exists('/tmp/M3UIPTV/poster.png'):
			os.remove('/tmp/M3UIPTV/poster.png')
		self.processing_cover = False
		if len(self.allseries) == 1 and self.mode == self.MODE_GENRE:  # go straight into series mode if no categories are available
			self.mode = self.MODE_SERIES
			self.pushStack()
		if self.mode == self.MODE_GENRE:
			self.title = _("VoD Series Categories")
			self["description"].text = _("Press OK to select a category")
			self["list"].setList([(x, x) for x in self.categories])
			self["poster"].instance and self["poster"].instance.setPixmap(None)
		elif self.mode == self.MODE_SERIES:
			self.title = _("VoD Series Category: %s") % self.category
			self["description"].text = _("Press OK to select a series")
			self["list"].setList([x for x in sorted(self.allseries[self.category], key=lambda x: x[1].lower())])
		elif self.mode == self.MODE_EPISODE:
			self.title = _("VoD Series: %s") % self.seriesName
			self["description"].text = _("Press OK to play selected show")
			self["list"].setList([x for x in self.episodes])
		elif self.mode == self.MODE_SEARCH:
			self.title = _("VoD Series Search")
			self["description"].text = _("Press OK to select the current item")
			self["list"].setList(sorted([(series[0], series[1], series[2], series[3], series[4], c) for i, series in enumerate(self.allseries[self.all]) if (c := self.search(i))], key=lambda x: (-x[5], x[1])))
		self["key_yellow"].text = self.mdbText()

	def playMovie(self):
		if current := self["list"].getCurrent():
			infobar = InfoBar.instance
			series = 0
			if infobar:
				LastService = self.session.nav.getCurrentServiceReferenceOriginal()
				stream_data = current[0]
				stream_data_split = stream_data.split("||")
				url = stream_data_split[0]
				if len(stream_data_split) > 1:
					providerObj = current[3]
					series = int(stream_data_split[1])
					url = providerObj.getVoDPlayUrl(url, series=series)
				ref = eServiceReference("%s:0:1:%x:1009:1:CCCC0000:0:0:0:%s:%s" % (config.plugins.m3uiptv.vod_play_system.value, int(current[5]) + (10000*series), url.replace(":", "%3a"), current[1]))
				self.session.open(VoDMoviePlayer, ref, slist=infobar.servicelist, lastservice=LastService)

	def mdb(self):
		if self.mode != self.MODE_GENRE and (current := self["list"].getCurrent()):
			if tmdbScreen:
				self.session.open(tmdbScreen, current[1].replace("4K", "").replace("4k", ""), 2)
			elif IMDB:
				self.session.open(IMDB, current[1].replace("4K", "").replace("4k", ""), False)

	def mdbText(self):
		if self.mode != self.MODE_GENRE and self["list"].getCurrent():
			if tmdbScreen:
				return _("TMDb search")
			elif IMDB:
				return _("IMDb search")
		return ""

	def pushStack(self):
		self.episodesHistory.append(self.episodes)
		self.stack.append((self.mode, self["list"].index))

	def popStack(self):
		self.episodes = self.episodesHistory.pop()
		return self.stack.pop() if self.stack else (self.MODE_GENRE, 0)  # if stack is empty return defaults

	def createSummary(self):
		return PluginSummary

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
		 	<widget name="poster" position="%d,%d" size="%d,%d"/>
			<widget source="description" render="Label" position="%d,%d" zPosition="10" size="%d,%d" halign="center" valign="center" font="Regular;%d" transparent="1" shadowColor="black" shadowOffset="-1,-1" />
		</screen>""",
			980, 600,  # screen
			15, 60, 640, 430,  # Listbox
			2, 0, 630, 26,  # template
			22,  # fonts
			26,  # ItemHeight
			665, 60, 300, 430,  # Poster
			5, 500, 940, 50, 22,  # description
			]  # noqa: E124

	def __init__(self, session):
		Screen.__init__(self, session)
		self["list"] = List([])
		self["description"] = StaticText()
		self.picload = ePicLoad()
		self.picload.PictureData.get().append(self.showPic)
		self["poster"] = Pixmap()
		self.mode = self.MODE_CATEGORY
		self.allmovies = []
		for provider in providers:
			self.allmovies += [movie for movie in providers[provider].vod_movies if movie.name is not None]
		self.all = _("All")
		self.category = self.all
		self.categories = []
		self.searchTexts = []
		self.searchTerms = []
		for movie in self.allmovies:
			if movie.category is not None and movie.category not in self.categories:
				self.categories.append(movie.category)
		self.categories.sort(key=lambda x: x.lower())
		self.categories.insert(0, self.category)  # insert "All" category at the start of the list
		if self.selectionChanged not in self["list"].onSelectionChanged:
			self["list"].onSelectionChanged.append(self.selectionChanged)

		self["key_red"] = StaticText(_("Cancel"))
		self["key_green"] = StaticText(_("Search"))
		self["key_yellow"] = StaticText()
		# self["key_blue"] = StaticText()

		self["actions"] = ActionMap(["M3UIPTVConfigActions", "M3UIPTVPlayActions"],
			{
				"cancel": self.keyCancel,  # KEY_RED / KEY_EXIT
				"save": self.keySearch,  # KEY_GREEN
				"ok": self.keySelect,
				"yellow": self.mdb,
				# "blue": self.blue,
				"play": self.key_play,
				"menu": self.closeRecursive,
			}, -1)  # noqa: E123
		self.buildList()
		self.onClose.append(self.mdbCleanup)
		self.processing_cover = False
		self.deferred_cover_url = None

	def showPic(self, picInfo=""):
		ptr = self.picload.getData()
		if ptr is not None:
			if not self.deferred_cover_url:
				self["poster"].instance.setPixmap(ptr.__deref__())
		self.processing_cover = False
		if self.deferred_cover_url:
			cover_url = self.deferred_cover_url
			self.deferred_cover_url = None
			threads.deferToThread(self.downloadCover, cover_url)

	def downloadCover(self, current_cover_url):
		if not current_cover_url:
			self["poster"].instance.setPixmap(None)
			return

		current_cover_url = current_cover_url.replace("\\", "")
		if self.processing_cover:
			self.deferred_cover_url = current_cover_url
			return
		
		self.processing_cover = True
		if not self.deferred_cover_url:
			try:
				req = urllib.request.Request(current_cover_url, headers={
        										'User-Agent': REQUEST_USER_AGENT #'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/35.0.1916.47 Safari/537.36'
    										})
				response = urllib.request.urlopen(req, timeout=5)

				if response.status != 200:
					self.processing_cover = False
					self.deferred_cover_url = None
					self["poster"].instance.setPixmap(None)
					return
				makedirs('/tmp/M3UIPTV', exist_ok=True)
				with open('/tmp/M3UIPTV/poster.png', 'wb') as handler:
					handler.write(response.read())
				
				piconsize = self["poster"].instance.size()
				self.picload.setPara((piconsize.width(), piconsize.height(), 1, 1, 1, 1, '#FF111111'))
				
				if path.exists('/tmp/M3UIPTV/poster.png'):
					self.picload.startDecode('/tmp/M3UIPTV/poster.png')
				else:
					self["poster"].instance.setPixmap(None)
			except:
				self.processing_cover = False
				self.deferred_cover_url = None
				self["poster"].instance.setPixmap(None)

	def getExtraMovieInfo(self, obj):
		info_obj = obj.providerObj.getMovieById(obj.id)
		if plot := info_obj.get("plot"):
			self["description"].text = plot
		else:
			self["description"].text = _("Press OK to play selected movie")

	def selectionChanged(self):
		current_cover_url = None
		current = self["list"].getCurrent()
		if self.mode in (self.MODE_MOVIE, self.MODE_SEARCH) and current:
			if (plot := current[0].plot) is not None:
				self["description"].text = plot
			elif not current[0].plot:
				threads.deferToThread(self.getExtraMovieInfo, current[0])
			if current[0].poster_url:
				current_cover_url = current[0].poster_url
		if self.mode != self.MODE_CATEGORY and config.plugins.m3uiptv.display_poster.value:
			threads.deferToThread(self.downloadCover, current_cover_url)

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
		if self.mode in (self.MODE_MOVIE, self.MODE_SEARCH) and self["list"].getCurrent():
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
		if tmdbTempDir and path.exists(tmdbTempDir):
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
		if path.exists('/tmp/M3UIPTV/poster.png'):
			os.remove('/tmp/M3UIPTV/poster.png')
		self.processing_cover = False
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
			self["poster"].instance and self["poster"].instance.setPixmap(None)
		else:
			self.title = _("VoD Movie Category: %s") % self.category
			self["description"].text = _("Press OK to play selected movie")
			self["list"].setList(sorted([(movie, movie.name) for movie in self.allmovies if self.category == self.all or self.category == movie.category], key=lambda x: x[1].lower()))
		self["key_yellow"].text = self.mdbText()

	def playMovie(self):
		if current := self["list"].getCurrent():
			infobar = InfoBar.instance
			if infobar:
				LastService = self.session.nav.getCurrentServiceReferenceOriginal()
				url = current[0].providerObj.getVoDPlayUrl(current[0].url, current[0].id)
				ref = eServiceReference("%s:0:1:%x:1009:1:CCCC0000:0:0:0:%s:%s" % (config.plugins.m3uiptv.vod_play_system.value, current[0].id, url.replace(":", "%3a"), current[0].name))
				self.session.open(VoDMoviePlayer, ref, slist=infobar.servicelist, lastservice=LastService)

	def keyCancel(self):
		if len(self.categories) > 1 and self.mode in (self.MODE_MOVIE, self.MODE_SEARCH):
			self.mode = self.MODE_CATEGORY
			self.buildList()
		else:
			self.close()

	def closeRecursive(self):
		self.close(True)

	def createSummary(self):
		return PluginSummary

class M3UIPTVManagerConfig(Screen):
	skin = ["""
		<screen name="M3UIPTVManagerConfig" position="center,center" size="%d,%d">
			<panel name="__DynamicColorButtonTemplate__"/>
			<widget source="list" render="Listbox" position="%d,%d" size="%d,%d" scrollbarMode="showOnDemand">
				<convert type="TemplatedMultiContent">
					{"template": [
		 					MultiContentEntryPixmapAlphaBlend(pos = (%d,%d), size = (%d,%d), flags = BT_SCALE | BT_KEEP_ASPECT_RATIO, png = 2),
							MultiContentEntryText(pos = (%d,%d), size = (%d,%d), flags = RT_HALIGN_LEFT, text = 1), # index 0 is the MenuText,
		 					MultiContentEntryText(pos = (%d,%d), size = (%d,%d), flags = RT_HALIGN_LEFT, text = 4),
		 					MultiContentEntryPixmapAlphaBlend(pos = (%d,%d), size = (%d,%d), flags = BT_SCALE | BT_KEEP_ASPECT_RATIO, png = 3),
		 					MultiContentEntryPixmapAlphaBlend(pos = (%d,%d), size = (%d,%d), flags = BT_SCALE | BT_KEEP_ASPECT_RATIO, png = 5),
						],
					"fonts": [gFont("Regular",%d)],
					"itemHeight":%d
					}
				</convert>
			</widget>
			<widget source="description" render="Label" position="%d,%d" zPosition="10" size="%d,%d" halign="center" valign="center" font="Regular;%d" transparent="1" shadowColor="black" shadowOffset="-1,-1" />
			<widget source="progress" render="Progress" position="%d,%d" size="%d,%d" backgroundColor="background" foregroundColor="blue" zPosition="11" borderWidth="0" borderColor="grey" cornerRadius="%d"/>
		</screen>""",
			980, 600,  # screen
			15, 60, 950, 430,  # Listbox
			2, 5, 66, 16,  # logo
			80, 0, 302, 26,  # template
			392, 0, 200, 26,  # progress
			570, 0, 26, 26,  # vod ico
			602, 1, 24, 24,  # active ico
			22,  # fonts
			26,  # ItemHeight
			5, 500, 940, 50, 22,  # description
			5, 500, 940, 6, 3,  # progress
			]  # noqa: E124

	def __init__(self, session):
		Screen.__init__(self, session)
		self.setTitle(_("M3U IPTV Manager - providers"))
		self["list"] = List([])
		self["progress"] = Progress()
		self.vod_ico = LoadPixmap(resolveFilename(SCOPE_CURRENT_SKIN, "icons/vod.png"))
		if not self.vod_ico:
			self.vod_ico = LoadPixmap("%s/vod.png" % plugin_dir)
		self.active_ico = LoadPixmap(resolveFilename(SCOPE_CURRENT_SKIN, "icons/iptv_active.png"))
		if not self.active_ico:
			self.active_ico = LoadPixmap("%s/iptv_active.png" % plugin_dir)
		self.inactive_ico = LoadPixmap(resolveFilename(SCOPE_CURRENT_SKIN, "icons/iptv_inactive.png"))
		if not self.inactive_ico:
			self.inactive_ico = LoadPixmap("%s/iptv_inactive.png" % plugin_dir)
		self.activity_icons = {"0": self.active_ico, "1": self.inactive_ico, "2": None}
		m3u_ico = LoadPixmap(resolveFilename(SCOPE_CURRENT_SKIN, "icons/m3u.png"))
		if not m3u_ico:
			m3u_ico = LoadPixmap("%s/m3u.png" % plugin_dir)
		xtream_ico = LoadPixmap(resolveFilename(SCOPE_CURRENT_SKIN, "icons/xc.png"))
		if not xtream_ico:
			xtream_ico = LoadPixmap("%s/xc.png" % plugin_dir)
		stalker_ico = LoadPixmap(resolveFilename(SCOPE_CURRENT_SKIN, "icons/stalker.png"))
		if not stalker_ico:
			stalker_ico = LoadPixmap("%s/stalker.png" % plugin_dir)
		tvh_ico = LoadPixmap(resolveFilename(SCOPE_CURRENT_SKIN, "icons/tvheadend.png"))
		if not tvh_ico:
			tvh_ico = LoadPixmap("%s/tvheadend.png" % plugin_dir)
		vod_ico = LoadPixmap(resolveFilename(SCOPE_CURRENT_SKIN, "icons/vod_p.png"))
		if not vod_ico:
			vod_ico = LoadPixmap("%s/vod_p.png" % plugin_dir)
		self.logos = {}
		self.logos["M3U"] = m3u_ico
		self.logos["Xtreeme"] = xtream_ico
		self.logos["Stalker"] = stalker_ico
		self.logos["TVH"] = tvh_ico
		self.logos["VOD"] = vod_ico
		self.generate_timer = eTimer()
		self.generate_timer.callback.append(self.generateBouquets)
		self.buildList()
		for provider in providers:
			providers[provider].onProgressChanged.append(self.onProgressChanged)
		
		threads.deferToThread(self.loadInfoForProviders).addCallback(self.onProgressChanged)
			
		self["key_red"] = StaticText(_("Close"))
		self["key_green"] = StaticText(_("Add provider"))
		self["key_yellow"] = StaticText(_("Generate bouquets"))
		self["key_blue"] = StaticText(_("Clear all data"))
		self["key_info"] = StaticText()
		self["description"] = StaticText(_("Press OK to edit the currently selected provider"))
		self.updateCallbacks()
		if self.selectionChanged not in self["list"].onSelectionChanged:
			self["list"].onSelectionChanged.append(self.selectionChanged)
		self.onClose.append(self.__onClose)

		self["actions"] = ActionMap(["M3UIPTVConfigActions",],
			{
				"cancel": self.close,  # KEY_RED / KEY_EXIT
				"save": self.addProvider,  # KEY_GREEN
				"ok": self.editProvider,
				"yellow": self.keyYellow,
				"blue": self.clearData,
			}, -1)  # noqa: E123

		self["infoActions"] = ActionMap(["M3UIPTVConfigActions",],
			{
				"info": self.info,
			}, -1)  # noqa: E123

	def __onClose(self):
		self.removeCallbacks()

	def removeCallbacks(self):
		for provider in providers:
			providerObj = providers[provider]
			while self.updateDescription in providerObj.update_status_callback:
				providerObj.update_status_callback.remove(self.updateDescription)
			while self.onProgressChanged in providerObj.onProgressChanged:
				providerObj.onProgressChanged.remove(self.onProgressChanged)

	def loadInfoForProviders(self):
		for provider in providers:
			providers[provider].getProviderInfo()

	def updateCallbacks(self):
		for provider in providers:
			providerObj = providers[provider]
			if self.updateDescription not in providerObj.update_status_callback:
				providerObj.update_status_callback.append(self.updateDescription)

	def buildList(self):
		self["list"].list = list(sorted([(provider, providers[provider].iptv_service_provider,self.logos[providers[provider].type], self.vod_ico if len(providers[provider].vod_movies) > 0 or len(providers[provider].vod_series) > 0 else None,  "" if providers[provider].progress_percentage == -1 else (_("Fetching VoD items") + " " + str(providers[provider].progress_percentage) + "%"), self.activity_icons[providers[provider].getAccountActive()]) for provider in providers], key=lambda x: x[1]))

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
			providerObj.progress_percentage = -1
			try:
				providerObj.onBouquetCreated.append(self.onBouquetCreated)
				providerObj.onProgressChanged.append(self.onProgressChanged)
				providerObj.getPlaylistAndGenBouquet()
			except Exception as ex:
				import traceback
				err = traceback.format_exc()
				print("[M3UIPTV] Error has occured during bouquet creation:", err)
				self.updateDescription(_("%s: an error occured during bouquet creation\n\nError type: %s") % (providerObj.iptv_service_provider, type(ex).__name__))
				self.session.open(MessageBox, _("%s: an error occured during bouquet creation\n\nError type: %s") % (providerObj.iptv_service_provider, type(ex).__name__), MessageBox.TYPE_ERROR)

	def onProgressChanged(self):
		try:
			self["list"].setList(list(sorted([(provider, providers[provider].iptv_service_provider,self.logos[providers[provider].type], self.vod_ico if len(providers[provider].vod_movies) > 0 or len(providers[provider].vod_series) > 0 else None,  "" if providers[provider].progress_percentage == -1 else (_("Fetching VoD items") + " " + str(providers[provider].progress_percentage) + "%"), self.activity_icons[providers[provider].getAccountActive()]) for provider in providers], key=lambda x: x[1])))
		except:
			pass

	def onBouquetCreated(self, providerObj, error):
		if not hasattr(self, "session") or not self.session:
			return
		if error:
			self.updateDescription(_("%s: unable to create bouquet") % providerObj.iptv_service_provider)
			self.session.open(MessageBox, _("Unable to create bouquet \"%s\"!\nPossible reason can be no network available.") % providerObj.iptv_service_provider, MessageBox.TYPE_ERROR, timeout=5)
		else:
			self.updateDescription(_("%s: bouquets generated successfully") % providerObj.iptv_service_provider)
			self.session.open(MessageBox, _("\"%s\" bouquets have been generated successfully") % providerObj.iptv_service_provider, MessageBox.TYPE_INFO, timeout=5)
		self["actions"].setEnabled(True)
		self.onProgressChanged()

	def updateDescription(self, desc):
		try:
			self["description"].text = desc
		except KeyError:  # if MessageBox is open
			pass

	def clearData(self):
		if current := self["list"].getCurrent():
			provider = current[0]
			providerObj = providers[provider]
			providerObj.removeAllData()
			self.updateDescription(_("%s: data removed successfully") % providerObj.iptv_service_provider)
			self.onProgressChanged()

	def selectionChanged(self):
		if (current := self["list"].getCurrent()) and providers[current[0]].provider_info:
			self["infoActions"].setEnabled(True)
			self["key_info"].text = _("INFO")
		else:
			self["infoActions"].setEnabled(False)
			self["key_info"].text = ""

	def info(self):
		if (current := self["list"].getCurrent()):
			providerObj = providers[current[0]]
			provider_info = providerObj.provider_info
			title = _("M3U IPTV Provider Info") + " - " + providerObj.iptv_service_provider
			text = []
			if provider_info.get("user_info"):
				if status := provider_info["user_info"].get("status"):
					text.append(_("Account status") + ": " + status)
				if (created_at := provider_info["user_info"].get("created_at")) and str(created_at).isdigit():
					text.append(_("Account created") + ": " + strftime("%d/%m/%Y", localtime(int(created_at))))
				if (exp_date := provider_info["user_info"].get("exp_date")) and str(exp_date).isdigit():
					text.append(_("Account expires") + ": " + strftime("%d/%m/%Y", localtime(int(exp_date))))
				if (exp_date := provider_info["user_info"].get("exp_date")) and  not str(exp_date).isdigit():
					text.append(_("Account expires") + ": " + exp_date)
				if is_trial := provider_info["user_info"].get("is_trial"):
					text.append(_("Is trial") + ": " + ("no" if str(is_trial) == "0" else "yes"))
				if max_connections := provider_info["user_info"].get("max_connections"):
					text.append(_("Maximum connections") + ": " + max_connections)
			if provider_info.get("server_info"):
				if url := provider_info["server_info"].get("url"):
					text.append(_("Server url") + ": " + str(url))
				if port := provider_info["server_info"].get("port"):
					text.append(_("Server port") + ": " + str(port))
				if https_port := provider_info["server_info"].get("https_port"):
					text.append(_("Server https port") + ": " + str(https_port))
				if rtmp_port := provider_info["server_info"].get("rtmp_port"):
					text.append(_("Server rtmp port") + ": " + str(rtmp_port))
				if server_protocol := provider_info["server_info"].get("server_protocol"):
					text.append(_("Server protocol") + ": " + str(server_protocol))
				if timezone := provider_info["server_info"].get("timezone"):
					text.append(_("Server timezone") + ": " + str(timezone))
				if version := provider_info["server_info"].get("version"):
					text.append(_("Portal version") + ": " + str(version))
			self.session.open(ShowText, text="\n".join(text), title=title)

	def createSummary(self):
		return PluginSummary

class M3UIPTVProviderEdit(Setup):
	def __init__(self, session, provider=None):
		self.edit = provider in providers
		providerObj = providers.get(provider, IPTVProcessor())
		self.blacklist = self.edit and bool(providerObj.readExampleBlacklist())
		self.providerObj = providerObj
		self.type = ConfigSelection(default=providerObj.type, choices=[("M3U", _("M3U/M3U8")), ("Xtreeme", _("Xtreme Codes")), ("Stalker", _("Stalker portal")), ("TVH", _("TVHeadend server")), ("VOD", _("Video on Demand"))])
		self.playlist_type = ConfigSelection(default=providerObj.playlist_type, choices=[("m3u", _("M3U/M3U8")), ("txt", _("TXT"))])
		self.iptv_service_provider = ConfigText(default=providerObj.iptv_service_provider, fixed_size=False)
		self.url = ConfigText(default=providerObj.url, fixed_size=False)
		refresh_interval_choices = [(-1, _("off")), (0, _("on"))] + [(i, ngettext("%d hour", "%d hours", i) % i) for i in [1, 2, 3, 4, 5, 6, 12, 24]]  # noqa: F821
		self.refresh_interval = ConfigSelection(default=providerObj.refresh_interval, choices=refresh_interval_choices)
		self.novod = ConfigYesNo(default=providerObj.ignore_vod)
		self.create_epg = ConfigYesNo(default=providerObj.create_epg)
		self.staticurl = ConfigYesNo(default=providerObj.static_urls)
		self.search_criteria = ConfigText(default=providerObj.search_criteria, fixed_size=False)
		self.scheme = ConfigText(default=providerObj.scheme, fixed_size=False)
		self.username = ConfigText(default=providerObj.username, fixed_size=False)
		self.password = ConfigPassword(default=providerObj.password, fixed_size=False)
		self.mac = ConfigText(default=providerObj.mac, fixed_size=False)
		self.is_custom_xmltv = ConfigYesNo(default=providerObj.is_custom_xmltv)
		self.custom_xmltv_url = ConfigText(default=providerObj.custom_xmltv_url, fixed_size=False)
		self.use_provider_tsid = ConfigYesNo(default=providerObj.use_provider_tsid)
		self.user_provider_ch_num = ConfigYesNo(default=providerObj.user_provider_ch_num)
		self.provider_tsid_search_criteria = ConfigText(default=providerObj.provider_tsid_search_criteria, fixed_size=False)
		self.picon_gen_strategy = ConfigSelection(default=providerObj.picon_gen_strategy, choices=[(0, _("Picons by name (SNP)")), (1, _("Picons by service reference (SRP)"))])
		self.epg_match_strategy = ConfigSelection(default=providerObj.epg_match_strategy, choices=[(0, _("By tvg-id")), (1, _("By channel name"))])
		self.custom_user_agent = ConfigSelection(default=providerObj.custom_user_agent, choices=[("off", _("off")), ("android", "Android 15"), ("ios", "IOS 17"), ("windows", "Windows 11 (Edge)"), ("vlc", "VLC 3.0.18")])
		self.output_format = ConfigSelection(default=providerObj.output_format, choices=[("ts", _("Transport stream (TS)")), ("m3u8", _("HLS (M3U8)"))])
		epg_offset_choices = [(i, ngettext("%d hour", "%d hours", i) % i) for i in list(range(-12,12))]  # noqa: F821
		self.epg_time_offset = ConfigSelection(default=providerObj.epg_time_offset, choices=epg_offset_choices)
		isServiceAppInstalled = isPluginInstalled("ServiceApp")
		play_system_choices = [("1", "DVB"), ("4097", "HiSilicon" if BoxInfo.getItem("mediaservice") == "servicehisilicon" else "GStreamer")]
		if isServiceAppInstalled:
			play_system_choices.append(("5002", "Exteplayer3"))
		self.play_system = ConfigSelection(default=providerObj.play_system, choices=play_system_choices)
		catchup_play_system_choices = [("4097", "HiSilicon" if BoxInfo.getItem("mediaservice") == "servicehisilicon" else "GStreamer")]
		if isServiceAppInstalled:
			catchup_play_system_choices.append(("5002", "Exteplayer3"))
		self.play_system_catchup = ConfigSelection(default=providerObj.play_system_catchup, choices=catchup_play_system_choices)
		catchup_type_choices = [(CATCHUP_DEFAULT, _("Standard")), (CATCHUP_APPEND, _("Append")), (CATCHUP_SHIFT, _("Shift")), (CATCHUP_XTREME, _("Xtreme Codes")), (CATCHUP_STALKER, _("Stalker")), (CATCHUP_FLUSSONIC, _("Flussonic")), (CATCHUP_VOD, _("VoD"))]
		self.catchup_type = ConfigSelection(default=providerObj.catchup_type, choices=catchup_type_choices)
		self.epg_url = ConfigText(default=providerObj.epg_url, fixed_size=False)
		self.picons = ConfigYesNo(default=providerObj.picons)
		self.create_bouquets_strategy = ConfigSelection(default=providerObj.create_bouquets_strategy, choices=[(0, _("Only bouquets for groups")), (1, _("Only bouquet for 'All Channels'")), (2, _("Bouquets for 'All Channels' and groups")), (3, _("Bouquet for provider and sub-bouquets for groups"))])
		self.ch_order_strategy = ConfigSelection(default=providerObj.ch_order_strategy, choices=[(0, _("Use provider order")), (1, _("By channel number")), (2, _("Alphabetically"))])
		self.auto_updates = ConfigYesNo(default=providerObj.auto_updates)

		self.bouquetsblacklist = ConfigSelection(choices=[("1", _("Press OK"))], default="1")
		self.movieblacklist = ConfigSelection(choices=[("1", _("Press OK"))], default="1")
		self.seriesblacklist = ConfigSelection(choices=[("1", _("Press OK"))], default="1")

		# media library fields
		self.has_media_library = ConfigYesNo(default=providerObj.has_media_library)
		self.media_library_type = ConfigSelection(default=providerObj.media_library_type, choices=[("xc", _("Xtream Codes (Username/Password)")), ("xc-token", _("Xtream Codes (Token)"))])
		self.media_library_url = ConfigText(default=providerObj.media_library_url, fixed_size=False)
		self.media_library_username = ConfigText(default=providerObj.media_library_username, fixed_size=False)
		self.media_library_password = ConfigText(default=providerObj.media_library_password, fixed_size=False)
		self.media_library_token = ConfigText(default=providerObj.media_library_token, fixed_size=False)
		Setup.__init__(self, session, None)
		self.title = _("M3UIPTVManager") + " - " + (_("edit provider") if self.edit else _("add new provider"))
		if self.edit:
			self["key_yellow"] = StaticText(_("Delete \"%s\"") % providerObj.iptv_service_provider)
			self["yellowactions"] = HelpableActionMap(self, ["ColorActions"], {
				"yellow": (self.keyRemove, _("Permanently remove provider \"%s\" from your configuration.") % providerObj.iptv_service_provider)
			}, prio=0)

	def createSetup(self):
		configlist = []
		if not self.edit:  # Only show when adding a provider so to select the output type.
			configlist.append((_("Provider Type"), self.type, _("Specify the provider type.")))
		configlist.append((_("Provider name"), self.iptv_service_provider, _("Specify the provider user friendly name that will be used for the bouquet name and for displaying in the infobar.")))
		configlist.append((_("URL"), self.url, _("The playlist URL (*.m3u; *.m3u8) or streaming server URL. Including the port if differs from 80.") + " " + _("If the playlist is already stored on a local device you can use the local file path in this field, e.g. /tmp/myplaylist.m3u")))
		if self.type.value == "VOD":
			configlist.append((_("VOD playlist format"), self.playlist_type, _("The format of the VOD playlist (m3u; m3u8; txt)")))
		if self.type.value == "M3U":
			configlist.append((_("Use static URLs"), self.staticurl, _("If enabled URL will be static and not aliases. That means if the URL of a service changes in the playlist bouquet entry will stop working.")))
			if not self.staticurl.value:
				configlist.append((_("Refresh interval"), self.refresh_interval, _("Interval in which the playlist will be automatically updated")))
				configlist.append((_("Filter"), self.search_criteria, _("The search criteria by which the service will be searched in the playlist file.")))
		elif self.type.value == "Xtreeme" or self.type.value == "TVH":
			configlist.append((_("Username"), self.username, _("User name used for authenticating in the streaming server.")))
			configlist.append((_("Password"), self.password, _("Password used for authenticating in the streaming server.")))
		elif self.type.value == "Stalker":
			configlist.append((_("MAC address"), self.mac, _("MAC address used for authenticating in Stalker portal.")))
		if self.type.value == "Xtreeme" or self.type.value == "Stalker":
			configlist.append((_("Skip VOD entries"), self.novod, _("Skip VOD entries in the playlist")))
		if self.type.value != "VOD":
			configlist.append((_("Generate EPG files for EPGImport plugin"), self.create_epg, _("Creates files needed for importing EPG via EPGImport plugin")))
			if self.create_epg.value:
				if self.type.value == "M3U":
					configlist.append((_("EPG matching condition"), self.epg_match_strategy, _("Specify how xmltv entries will be matched to channels.")))
				configlist.append((_("Use custom XMLTV URL"), self.is_custom_xmltv, _("Use your own XMLTV url for EPG importing.")))
				if self.is_custom_xmltv.value:
					configlist.append((_("Custom XMLTV URL"), self.custom_xmltv_url, _("The URL where EPG data for this provider can be downloaded.")))
				#if self.type.value == "Stalker" and self.create_epg.value and not self.is_custom_xmltv.value:
				#	configlist.append((_("EPG entry GMT offset"), self.epg_time_offset, _("Set time offset in hours towards GMT.")))
		configlist.append((_("Scheme"), self.scheme, _("Specifying the URL scheme that unicly identify the provider.\nCan be anything you like without spaces and special characters.")))
		if self.type.value != "VOD":
			configlist.append((_("Playback system"), self.play_system, _("The player used. Can be DVB, GStreamer, HiSilicon, Extplayer3")))
			configlist.append((_("Playback system for Catchup/Archive"), self.play_system_catchup, _("The player used for playing Catchup/Archive. Can be GStreamer/HiSilicon, Extplayer3")))
			if self.type.value in ("Xtreeme", "Stalker"):
				configlist.append((_("Stream output format"), self.output_format, _("The format used to deliver the streams. Can be TS or HLS.\nNOTE: Setting playback system to DVB will make it impossible to use HLS as output format.")))
			if self.type.value == "M3U":
				configlist.append((_("Catchup Type"), self.catchup_type, _("The catchup API used.")))
				configlist.append((_("Enable Media Library"), self.has_media_library, _("Specify is there media library available on separate url.")))
				if self.has_media_library.value:
					configlist.append((_("Media Library type"), self.media_library_type, _("Specify media library type.")))
					configlist.append((_("Media Library URL"), self.media_library_url, _("Specify media library URL.")))
					if self.media_library_type.value == "xc":
						configlist.append((_("Media Library Username"), self.media_library_username, _("User name used for authenticating in the Media Library server.")))
						configlist.append((_("Media Library Password"), self.media_library_password, _("Password used for authenticating in Media Library server.")))
					else:
						configlist.append((_("Media Library Access Token"), self.media_library_token, _("Access token used for authenticating in Media Library server.")))

			configlist.append((_("Download picons"), self.picons, _("Download picons, if available from the provider, and install them. Picon download is done in the background after bouquet generation.")))
			if self.picons.value:
				configlist.append((_("Picons type"), self.picon_gen_strategy, _("Determine how the picons will be named - SNP or SRP.")))
			configlist.append((_("Bouquet creation strategy"), self.create_bouquets_strategy, _("Configure what type of bouquets should be created.")))
			configlist.append((_("Use provider TSID"), self.use_provider_tsid, _("Use the TSID provided from the IPTV provider (if available).\nUseful when want to always have same service references for EPG.")))
			if self.use_provider_tsid.value:
				configlist.append((_("Use channel numbers from provider"), self.user_provider_ch_num, _("Use channel numbers and ordering provided by the IPTV provider.\nIt will work only for 'ALL' bouquets.\nIf is configured global numbering the channel numbers may be offset depending on how many bouquets are before that one.")))
				if self.type.value in ("M3U", "TVH"):
					configlist.append((_("Provider TSID retrival condition"), self.provider_tsid_search_criteria, _("Search condition to get TSID provided from IPTV provider.\nUseful when want to always have same service references for EPG.")))
			if not self.user_provider_ch_num.value or not self.use_provider_tsid.value:
				configlist.append((_("Channel ordering criteria"), self.ch_order_strategy, _("Specify how channels will be ordered in bouquets.")))
			configlist.append((_("Custom User-Agent"), self.custom_user_agent, _("Sets custom User-Agent for use with services that requires specific one.")))
		if config.plugins.m3uiptv.schedule.value:
			configlist.append((_("Auto updates"), self.auto_updates, _("Include this provider when the global update schedule runs.") + " " + _("Requires the scheduler to be set up in the settings screen.")))

		if self.blacklist:
			configlist.append((_("Bouquets blacklist"), self.bouquetsblacklist, _("Press OK to select which bouquets/categories will be blacklisted.")))
		if self.type.value == "Stalker" and not self.novod.value:
			configlist.append((_("Blacklist VoD movie categories"), self.movieblacklist, _("Press OK to select which categories will be blacklisted.")))
			configlist.append((_("Blacklist VoD series categories"), self.seriesblacklist, _("Press OK to select which categories will be blacklisted.")))

		self["config"].list = configlist

	def keySelect(self):
		current = self["config"].getCurrent()
		if current and len(current) > 1 and current[1] is self.bouquetsblacklist:
			self.session.open(BouquetBlacklist, self.providerObj)
		elif current and len(current) > 1 and current[1] is self.movieblacklist:
			self.session.open(BouquetBlacklist, self.providerObj, 1)
		elif current and len(current) > 1 and current[1] is self.seriesblacklist:
			self.session.open(BouquetBlacklist, self.providerObj, 2)
		else:
			Setup.keySelect(self)

	def keySave(self):
		self.scheme.value = self.providerObj.cleanFilename(self.scheme.value)
		if not self.iptv_service_provider.value or not self.url.value or not self.scheme.value or not self.edit and self.scheme.value in providers or self.type.value == "Xtreeme" and (not self.username.value or not self.password.value):  # empty mandatory fields or scheme is not unique
			msg = _("Scheme must be unique. \"%s\" is already in use. Please update this field.") % self.scheme.value if not self.edit and self.scheme.value and self.scheme.value in providers else _("All fields must be filled in.")
			self.session.open(MessageBox, msg, MessageBox.TYPE_ERROR, timeout=30)
			return

		if self.type.value == "M3U":
			providerObj = self.providerObj if isinstance(self.providerObj, M3UProvider) else M3UProvider()
		elif self.type.value == "Xtreeme":
			providerObj = self.providerObj if isinstance(self.providerObj, XtreemProvider) else XtreemProvider()
		elif self.type.value == "TVH":
			providerObj = self.providerObj if isinstance(self.providerObj, TVHeadendProvider) else TVHeadendProvider()
		elif self.type.value == "Stalker":
			providerObj = self.providerObj if isinstance(self.providerObj, StalkerProvider) else StalkerProvider()
		else:
			providerObj = self.providerObj if isinstance(self.providerObj, VODProvider) else VODProvider()
		providerObj.iptv_service_provider = self.iptv_service_provider.value
		providerObj.url = self.url.value
		providerObj.iptv_service_provider = self.iptv_service_provider.value
		if not self.edit:  # Only show when adding a provider. scheme is the key so must not be edited.
			providerObj.scheme = self.scheme.value
		providerObj.ignore_vod = self.novod.value
		providerObj.auto_updates = self.auto_updates.value
		if self.type.value != "VOD":
			providerObj.play_system = self.play_system.value
			providerObj.play_system_catchup = self.play_system_catchup.value
			providerObj.create_epg = self.create_epg.value
			providerObj.picons = self.picons.value
			providerObj.picon_gen_strategy = self.picon_gen_strategy.value
			providerObj.create_bouquets_strategy = self.create_bouquets_strategy.value
			providerObj.use_provider_tsid = self.use_provider_tsid.value
			providerObj.user_provider_ch_num = self.user_provider_ch_num.value
			providerObj.provider_tsid_search_criteria = self.provider_tsid_search_criteria.value
			providerObj.custom_user_agent = self.custom_user_agent.value
			providerObj.ch_order_strategy = self.ch_order_strategy.value
			if self.type.value == "M3U":
				providerObj.refresh_interval = self.refresh_interval.value
				providerObj.static_urls = self.staticurl.value
				providerObj.search_criteria = self.search_criteria.value
				providerObj.catchup_type = self.catchup_type.value
				providerObj.epg_url = self.epg_url.value
				providerObj.is_custom_xmltv = self.is_custom_xmltv.value
				providerObj.custom_xmltv_url = self.custom_xmltv_url.value
				providerObj.epg_match_strategy = self.epg_match_strategy.value
				providerObj.has_media_library = self.has_media_library.value
				providerObj.media_library_type = self.media_library_type.value
				providerObj.media_library_url = self.media_library_url.value
				providerObj.media_library_username = self.media_library_username.value
				providerObj.media_library_password = self.media_library_password.value
				providerObj.media_library_token = self.media_library_token.value
			elif self.type.value == "Xtreeme" or self.type.value == "TVH":
				providerObj.username = self.username.value
				providerObj.password = self.password.value
				providerObj.is_custom_xmltv = self.is_custom_xmltv.value
				providerObj.custom_xmltv_url = self.custom_xmltv_url.value
				if self.type.value == "Xtreeme":
					providerObj.output_format = self.output_format.value
			else:
				providerObj.mac = self.mac.value
				providerObj.output_format = self.output_format.value
				providerObj.epg_time_offset = self.epg_time_offset.value
		else:
			providerObj.playlist_type = self.playlist_type.value

		if getattr(providerObj, "onid", None) is None:
			providerObj.onid = min(set(range(1, len(L := [x.onid for x in providers.values() if hasattr(x, "onid")]) + 2)) - set(L))
		providers[self.scheme.value if not self.edit else providerObj.scheme] = providerObj
		writeProviders()
		self.close(True)

	def keyRemove(self):
		self.session.openWithCallback(self.keyRemoveCallback, MessageBox, _("Are you sure you want to permanently remove provider \"%s\" from your configuration?") % self.scheme.value, MessageBox.TYPE_YESNO)

	def keyRemoveCallback(self, answer=None):
		if answer:
			providerObj = providers[self.scheme.value]
			providerObj.removeBouquets()
			providerObj.removeVoDData()
			providerObj.removeEpgSources()
			providerObj.removePicons()
			del providers[self.scheme.value]
			writeProviders()
			shutil.rmtree(PROVIDER_FOLDER % self.scheme.value, True)
			self.close(True)

class BouquetBlacklist(Screen):
	def __init__(self, session, providerObj, blacklist_type=0):
		self.providerObj = providerObj
		self.blacklist_type = blacklist_type
		Screen.__init__(self, session)
		self.title = _("%s: Blacklist Bouquets") % self.providerObj.iptv_service_provider
		self.skinName = ["Setup"]
		self["config"] = SelectionList([], enableWrapAround=True)
		self["key_red"] = StaticText(_("Cancel"))
		self["key_green"] = StaticText(_("Save"))
		self["key_yellow"] = StaticText(_("Toggle all"))
		self["description"] = StaticText(_("Select the bouquets you want to blacklist and press ok. Blacklisted bouquets will be removed and not regenerated on rebuild. To reactive a bouquet, deselect it and regenerate bouquets."))
		self["actions"] = ActionMap(["M3UIPTVConfigActions"],
		{
			"ok": self["config"].toggleSelection,
			"save": self.keySave,
			"cancel": self.close,
			"yellow": self["config"].toggleAllSelection,
		}, -2)
		if blacklist_type == 1:
			self.providerObj.getVODCategories()
		elif blacklist_type == 2:
			self.providerObj.getSeriesCategories()
		examples = self.providerObj.readExampleBlacklist(blacklist_type)
		blacklist = self.providerObj.readBlacklist(blacklist_type)
		self["config"].setList([SelectionEntryComponent(x.split("|gid|")[0], x.split("|gid|")[-1], "", x.split("|gid|")[-1] in blacklist) for x in examples if not x.startswith("#")])

	def keySave(self):
		blacklist = [x[0][1] for x in self["config"].list if x[0][3]]
		self.providerObj.writeBlacklist(blacklist, self.blacklist_type)
		if self.blacklist_type == 0:
			for bouquet in blacklist:
				self.providerObj.removeBouquet(self.providerObj.cleanFilename(f"userbouquet.m3uiptv.{self.providerObj.iptv_service_provider}.{bouquet}.tv"))
		self.close()

class IPTVPluginConfig(Setup):
	def __init__(self, session):
		self.dayscreen = ConfigSelection(choices=[("1", _("Press OK"))], default="1")
		Setup.__init__(self, session, None)
		self.title = _("IPTV Settings")
		self.addSaveNotifier(self.updateSchedule)

	def createSetup(self):
		configlist = []
		configlist.append((_("Enable IPTV manager") + " *", config.plugins.m3uiptv.enabled, _("Enable IPTV functionality and managment.")))
		configlist.append((_("Check for Network"), config.plugins.m3uiptv.check_internet, _("Do a check is network available before try to retrieve the iptv playlist. If no network try backup services.")))
		configlist.append((_("Request timeout"), config.plugins.m3uiptv.req_timeout, _("Timeout in seconds for the requests of getting playlist.")))
		configlist.append((_("Picon max threads"), config.plugins.m3uiptv.picon_threads, _("Maximum number of threads during picon downloads. If the box returns errors or fails to download some picons, set a lower number.")))
		configlist.append((_("Show 'Video on Demand' menu entry") + " *", config.plugins.m3uiptv.inmenu, _("Allow showing of 'Video on Demand' menu entry in Main Menu.")))
		configlist.append((_("Show 'Video on Demand' extensions entry") + " *", config.plugins.m3uiptv.inextensions, _("Allow showing of 'Video on Demand' entry in the extensions (BLUE button) menu.") + " *"))
		configlist.append((_("Bouquet name character case"), config.plugins.m3uiptv.bouquet_names_case, _("Specify the character case used for bouquet names and titles.")))
		configlist.append((_("VoD playback system"), config.plugins.m3uiptv.vod_play_system, _("Specify the type of services that will be generated for VoD items.")))
		configlist.append((_("Download and display posters for VoD items"), config.plugins.m3uiptv.display_poster, _("Download and display posters for VoD items if available.")))
		if searchPaths:
			configlist.append((_("Fallback location for picons"), config.plugins.m3uiptv.fallback_picon_loc, _("Fallback loction for picons used when current active picon location can not be detected.")))
		configlist.append(("---",))
		configlist.append((_("Enable catchup/archive entries in EPG screens for period"), config.epg.histminutes, _("Enables possibility to return back in epg screens so to use old entries for invoke catchup/archive/timeshift.")))
		configlist.append((_("Local EPG server listening port") + " *", config.plugins.m3uiptv.epg_loc_port, _("Enables possibility to return back in epg screens so to use old entries for invoke catchup/archive/timeshift.")))
		configlist.append(("---",))
		if hasattr(config, "recording") and hasattr(config.recording, "setstreamto1"):
			configlist.append((_("Recordings - convert IPTV servicetypes to  1"), config.recording.setstreamto1, _("Recording 4097, 5001 and 5002 streams not possible with external players, so convert recordings to servicetype 1.")))
			configlist.append((_("Enable new GStreamer playback"), config.misc.usegstplaybin3, _("If enabled, the new GStreamer playback engine will be used.")))
			configlist.append(("---",))
		if hasattr(config, "timeshift"):
			if hasattr(config.timeshift, "startdelay"):
				configlist.append((_("Automatically start timeshift after"), config.timeshift.startdelay, _("When enabled, timeshift starts automatically in background after the specified time.")))
			elif hasattr(config.timeshift, "startDelay"):
				configlist.append((_("Automatically start time shift after"), config.timeshift.startDelay, _("When enabled, time shift starts automatically in background after specified time.")))
			if hasattr(config.timeshift, "check"):
				configlist.append((_("Show warning when time shift is stopped"), config.timeshift.check, _("When enabled, a warning will be displayed and the user will get an option to stop or to continue the time shift.")))
			else:
				configlist.append((_("Show warning when timeshift is stopped"), config.usage.check_timeshift, _("When enabled, a warning will be displayed and the user will get an option to stop or to continue the timeshift.")))
			if hasattr(config.timeshift, "favoriteSaveAction"):
				# configlist.append((_("Time shift save action on zap"), config.timeshift.favoriteSaveAction, _("Select if time shift must continue when set to record.")))
				configlist.append((_("Timeshift-save action on zap"), config.timeshift.favoriteSaveAction, _("Select if timeshift should continue when set to record.")))
			if hasattr(config.timeshift, "stopwhilerecording"):
				configlist.append((_("Stop timeshift while recording?"), config.timeshift.stopwhilerecording, _("Stops timeshift being used if a recording is in progress. (Advisable for USB sticks)")))
			elif hasattr(config.timeshift, "stopWhileRecording"):
				configlist.append((_("Stop time shift while recording"), config.timeshift.stopWhileRecording, _("Stops time shift being used if a recording is in progress. (Advisable for USB sticks.)")))
			if hasattr(config.timeshift, "showinfobar"):
				configlist.append((_("Use timeshift seekbar while timeshifting?"), config.timeshift.showinfobar, _("If set to 'yes', allows you to use the seekbar to jump to a point within the event.")))
			elif hasattr(config.timeshift, "showInfobar"):
				configlist.append((_("Use time shift SeekBar while time shifting"), config.timeshift.showInfobar, _("Select 'Yes' to allow use of the seek bar to jump to a selected point within the event.")))
			if hasattr(config.timeshift, "skipReturnToLive"):
				configlist.append((_("Skip jumping to live while timeshifting with plugins"), config.timeshift.skipReturnToLive, _("If set to 'yes', allows you to use timeshift with alternative audio plugins.")))
		if hasattr(config.usage, "timeshift_skipreturntolive"):
			configlist.append((_("Skip jumping to live TV while timeshifting with plugins"), config.usage.timeshift_skipreturntolive, _("If set to 'yes', allows you to use timeshift with alternative audio plugins.")))
		if isPluginInstalled("ServiceApp"):
			configlist.append(("---",))
			configlist.append((_("Enigma2 playback system"), config.plugins.serviceapp.servicemp3.replace, _("Change the playback system to one of the players available in ServiceApp plugin.")))
			if config.plugins.serviceapp.servicemp3.replace.value:
				configlist.append((_("Select the player which will be used for Enigma2 playback."), config.plugins.serviceapp.servicemp3.player, _("Select a player to be in use.")))
		configlist.append(("---",))
		configlist.append((_("Schedule update"), config.plugins.m3uiptv.schedule, _("Select 'yes' for automated updates of providers.") + " " + _("Also requires enabling in each individual provider that is to be updated.")))
		if config.plugins.m3uiptv.schedule.value:
			configlist.append(("  " + _("Schedule time of day"), config.plugins.m3uiptv.scheduletime, _("Set the time of day to perform the update.")))
			configlist.append(("  " + _("Schedule days of the week"), self.dayscreen, _("Press OK to select which days of the week to perform the update.")))
		self["config"].list = configlist

	def keySelect(self):
		current = self["config"].getCurrent()
		if current and len(current) > 1 and current[1] is self.dayscreen:
			self.session.open(DaysScreen)
		else:
			Setup.keySelect(self)

	def updateSchedule(self):
		if autoScheduleTimer is not None:
			if config.plugins.m3uiptv.enabled.isChanged() or config.plugins.m3uiptv.schedule.isChanged() or config.plugins.m3uiptv.scheduletime.isChanged():
				autoScheduleTimer.setSchedule()

class DaysScreen(Setup):
	def __init__(self, session):
		self.config = config.plugins.m3uiptv
		Setup.__init__(self, session, None)
		self.title = _("M3UIPTV schedule") + " - " + _("Select days")
		self.addSaveNotifier(self.updateSchedule)
		
	def createSetup(self):
		configlist = []
		days = (_("Monday"), _("Tuesday"), _("Wednesday"), _("Thursday"), _("Friday"), _("Saturday"), _("Sunday"))
		for i in sorted(list(self.config.days.keys())):
			configlist.append((days[i], self.config.days[i]))
		self["config"].list = configlist

	def keySave(self):
		if not any([self.config.days[i].value for i in self.config.days]):
			info = self.session.open(MessageBox, _("At least one day of the week must be selected"), MessageBox.TYPE_ERROR, timeout=30)
			info.setTitle(_("M3UIPTV schedule") + " - " + _("Select days"))
			return
		Setup.keySave(self)

	def updateSchedule(self):
		if autoScheduleTimer is not None:
			if any([self.config.days[i].isChanged() for i in self.config.days.keys()]):
				autoScheduleTimer.setSchedule()

class ShowText(TextBox):
	def __init__(self, session, text, title):
		TextBox.__init__(self, session, text=text, title=title, label="AboutScrollLabel")
		self.skinName = ["AboutOE", "About"]

	def createSummary(self):
		return ShowTextSummary

class ShowTextSummary(ScreenSummary):
	def __init__(self, session, parent):
		ScreenSummary.__init__(self, session, parent=parent)
		self.skinName = "AboutSummary"
		self["AboutText"] = StaticText(parent.title + "\n\n" + parent["AboutScrollLabel"].getText())

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
	for node in mdom.getroot():
		if node.tag == "menu" and node.get("key") == "iptvmenu":
			if "PluginLanguageDomain" in Menu.__init__.__code__.co_varnames:
				session.openWithCallback(boundFunction(MenuCallback, close), Menu, node, PluginLanguageDomain=PluginLanguageDomain)
			else:
				session.openWithCallback(boundFunction(MenuCallback, close), Menu, node)

def M3UIPTVVoDMenu(session, close=None, **kwargs):
	for node in mdom.getroot():
		if node.tag == "menu" and node.get("key") == "vod_menu":
			if "PluginLanguageDomain" in Menu.__init__.__code__.co_varnames:
				session.openWithCallback(boundFunction(MenuCallback, close), Menu, node, PluginLanguageDomain=PluginLanguageDomain)
			else:
				session.openWithCallback(boundFunction(MenuCallback, close), Menu, node)

def MenuCallback(close, answer=None):
	if close and answer:
		close(True)

def main(session, **kwargs):
	session.open(M3UIPTVManagerConfig)

def startSetup(menuid):
	if menuid != "setup":
		return []
	return [(_("IPTV"), M3UIPTVMenu, "iptvmenu", 10)]

def startVoDSetup(menuid):
	if menuid != "mainmenu":
		return []
	return [(_("Video on Demand"), M3UIPTVVoDMenu, "iptv_vod_menu", 100)]

autoScheduleTimer = None

def sessionstart(reason, session, **kwargs):
	global autoScheduleTimer
	if config.plugins.m3uiptv.enabled.value:
		injectIntoNavigation(session)
		readProviders()
		threads.deferToThread(startingCustomEPGExternal).addCallback(lambda ignore: finishedCustomEPGExternal())
		if autoScheduleTimer is None:
			autoScheduleTimer = AutoScheduleTimer()

class AutoScheduleTimer():
	def __init__(self):
		self.config = config.plugins.m3uiptv
		self.scheduletimer = eTimer()
		self.scheduletimer.timeout.get().append(self.doUpdate)
		self.setSchedule()

	def setSchedule(self):
		self.scheduletimer.stop()  # this is here because maybe the call came from the Notifier
		if self.config.enabled.value and self.config.schedule.value:
			now = int(time())
			if now < 1735689600:  # Wednesday, January 1, 2025 12:00:00 AM ... if clock is not set give up
				print("[M3UIPTV][setSchedule] System clock not set")
				return
			scheduleTime = self.getScheduleTime()
			if scheduleTime + 86400 > now:  # sanity, this should always be True
				if scheduleTime < now or not self.config.days[self.getToday()].value:
					scheduleTime += 86400 * self.getScheduleDayOfWeek()
				self.scheduletimer.startLongTimer(scheduleTime - now)
				print("[M3UIPTV][setSchedule] Next scheduled update set to", strftime("%c", localtime(scheduleTime)), strftime("(now=%c)", localtime(now)))
		else:
			print("[M3UIPTV][setSchedule] Scheduled updates disabled")

	def getScheduleTime(self):
		now = localtime(time())
		return int(mktime((now.tm_year, now.tm_mon, now.tm_mday, self.config.scheduletime.value[0], self.config.scheduletime.value[1], 0, now.tm_wday, now.tm_yday, now.tm_isdst)))

	def getScheduleDayOfWeek(self):
		today = self.getToday()
		for i in range(1, 8):
			if self.config.days[(today + i) % 7].value:
				return i

	def getToday(self):
		return localtime(time()).tm_wday

	def doUpdate(self):
		self.scheduletimer.stop()
		for provider in providers:
			providerObj = providers[provider]
			if providerObj.auto_updates:
				try:
					providerObj.getPlaylistAndGenBouquet()
					print(f"[M3UIPTV] Auto updating provider '{providerObj.iptv_service_provider}' succeeded")
				except Exception as err:
					print(f"[M3UIPTV] Auto updating provider '{providerObj.iptv_service_provider}' failed with error: {str(err)}")
		self.setSchedule()

def startingCustomEPGExternal():
	port = config.plugins.m3uiptv.epg_loc_port.value
	site = server.Site(StalkerEPG())
	reactor.listenTCP(port, site)
	try:
		reactor.run()
	except:
		pass

def finishedCustomEPGExternal():
	pass

def Plugins(path, **kwargs):
	try:
		result = [
			PluginDescriptor(where=PluginDescriptor.WHERE_SESSIONSTART, fnc=sessionstart, needsRestart=False),
			PluginDescriptor(where=PluginDescriptor.WHERE_MENU, needsRestart=False, fnc=startSetup),
			PluginDescriptor(name=_("M3UIPTV"), description=_("IPTV manager Plugin"), where=PluginDescriptor.WHERE_PLUGINMENU, icon='plugin.png', fnc=main)
		]
		if config.plugins.m3uiptv.inmenu.value:
			result += [PluginDescriptor(where=PluginDescriptor.WHERE_MENU, needsRestart=False, fnc=startVoDSetup)]
		if config.plugins.m3uiptv.inextensions.value:
			result += [PluginDescriptor(name=_("Video On Demand"), where=PluginDescriptor.WHERE_EXTENSIONSMENU, fnc=M3UIPTVVoDMenu, needsRestart=True)]

		return result
	except ImportError:
		return PluginDescriptor()
