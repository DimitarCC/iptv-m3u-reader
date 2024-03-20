from enigma import eServiceReference, eTimer, getBestPlayableServiceReference, setPreferredTuner
from Plugins.Plugin import PluginDescriptor
from Plugins.Extensions.IPTV.M3UProvider import M3UProvider
from Plugins.Extensions.IPTV.IPTVProviders import providers
from Plugins.Extensions.IPTV.IPTVProviders import processService as processIPTVService
from Screens.InfoBar import InfoBar
from Screens.InfoBarGenerics import streamrelay
from Components.config import config
from Components.ParentalControl import parentalControl
from Components.SystemInfo import SystemInfo
from Tools.Directories import resolveFilename, SCOPE_CONFIG
from Tools.BoundFunction import boundFunction
from Navigation import Navigation

from os import path
from xml.etree.cElementTree import ElementTree, Element, SubElement, tostring, iterparse

USER_IPTV_PROVIDERS_FILE = path.realpath(resolveFilename(SCOPE_CONFIG)) + "/IPTV/providers.xml"

def readProviders():
	fd = open(USER_IPTV_PROVIDERS_FILE, 'rb')
	for provider, elem in iterparse(fd):
		if elem.tag == "providers":
			for provider in elem.findall("provider"):
				providerObj = M3UProvider()
				providerObj.iptv_service_provider = provider.find("servicename").text
				providerObj.url = provider.find("url").text
				providerObj.offset = int(provider.find("offset").text)
				providerObj.refresh_interval = int(provider.find("refresh_interval").text)
				providerObj.search_criteria = provider.find("filter").text
				providerObj.scheme = provider.find("sheme").text
				providerObj.play_system = provider.find("system").text
				providers[providerObj.scheme] = providerObj
	fd.close()

# Function for overwrite some functions from Navigation.py so to inject own code
def injectIntoNavigation():
	import NavigationInstance
	NavigationInstance.instance.playService  = playServiceWithIPTV.__get__(NavigationInstance.instance, Navigation) # playService overwrite
	NavigationInstance.instance.playRealService = playRealService.__get__(NavigationInstance.instance, Navigation) # add callback so to process the parsed service ref
	NavigationInstance.instance.recordService = recordServiceWithIPTV.__get__(NavigationInstance.instance, Navigation) # recordService overwrite
	
def playServiceWithIPTV(self, ref, checkParentalControl=True, forceRestart=False, adjust=True):
	from Components.ServiceEventTracker import InfoBarCount
	InfoBarInstance = InfoBarCount == 1 and InfoBar.instance
	
	oldref = self.currentlyPlayingServiceOrGroup
	self.currentlyPlayingServiceReference = None
	self.currentlyPlayingServiceOrGroup = None
	self.currentlyPlayingService = None
	if InfoBarInstance:
		InfoBarInstance.session.screen["CurrentService"].newService(False)
	if ref and oldref and ref == oldref and not forceRestart:
		print("[Navigation] ignore request to play already running service(1)")
		return 1
	print("[Navigation] playing ref", ref and ref.toString())
	if path.exists("/proc/stb/lcd/symbol_signal") and config.lcd.mode.value == "1":
		try:
			if "0:0:0:0:0:0:0:0:0" not in ref.toString():
				signal = 1
			else:
				signal = 0
			f = open("/proc/stb/lcd/symbol_signal", "w")
			f.write(str(signal))
			f.close()
		except:
			f = open("/proc/stb/lcd/symbol_signal", "w")
			f.write("0")
			f.close()
	elif path.exists("/proc/stb/lcd/symbol_signal") and config.lcd.mode.value == "0":
		f = open("/proc/stb/lcd/symbol_signal", "w")
		f.write("0")
		f.close()

	if ref is None:
		self.stopService() 
		return 0
		
	self.currentlyPlayingServiceReference = ref
	self.currentlyPlayingServiceOrGroup = ref
	
	if InfoBarInstance:
		#InfoBarInstance.session.screen["CurrentService"].newService(ref)
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
			playref, old_ref, is_dynamic = processIPTVService(playref, self.playRealService)
			if InfoBarInstance:
				InfoBarInstance.session.screen["CurrentService"].newService(playref)
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
			InfoBarInstance.session.screen["Event_Now"].updateSource(nnref)
			InfoBarInstance.session.screen["Event_Next"].updateSource(nnref)
		else:
			InfoBarInstance.session.screen["CurrentService"].newService(True)
			InfoBarInstance.session.screen["Event_Now"].updateSource(nnref)
			InfoBarInstance.session.screen["Event_Next"].updateSource(nnref)
			
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
			
def sessionstart(reason, **kwargs):
	injectIntoNavigation()
	readProviders()

def Plugins(path, **kwargs):
	try:
		return [PluginDescriptor(where=PluginDescriptor.WHERE_SESSIONSTART, fnc=sessionstart, needsRestart=False)]
	except ImportError:
		return PluginDescriptor()

