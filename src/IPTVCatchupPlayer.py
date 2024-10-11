from enigma import eServiceReference, eTimer, iPlayableService
from Screens.InfoBar import InfoBar, MoviePlayer
from Screens.InfoBarGenerics import saveResumePoints, resumePointCache, resumePointCacheLast, delResumePoint, isStandardInfoBar
from Components.config import config
from Components.ServiceEventTracker import ServiceEventTracker
from Components.Sources.Progress import Progress
from Components.Label import Label
from Components.MultiContent import MultiContentEntryPixmapAlphaBlend
from Components.ActionMap import HelpableActionMap
from Tools.Directories import resolveFilename, SCOPE_CURRENT_SKIN
from Tools.LoadPixmap import LoadPixmap
from .IPTVProcessor import constructCatchUpUrl
from .IPTVProviders import processService as processIPTVService
from time import time
import datetime
import re

try:
	from Components.EpgListGrid import EPGListGrid as EPGListGrid
except ImportError:
	EPGListGrid = None
try:
	from Screens.EpgSelectionGrid import EPGSelectionGrid as EPGSelectionGrid
except ImportError:
	EPGSelectionGrid = None
try:
	from Plugins.Extensions.GraphMultiEPG.GraphMultiEpg import EPGList as EPGList, GraphMultiEPG as GraphMultiEPG
except ImportError:
	EPGList = None
	GraphMultiEPG = None


def injectCatchupInEPG():
	if EPGListGrid:
		if injectCatchupIcon not in EPGListGrid.buildEntryExtensionFunctions:
			EPGListGrid.buildEntryExtensionFunctions.append(injectCatchupIcon)
		__init_orig__ = EPGListGrid.__init__
		def __init_new__(self, *args, **kwargs):
			self.catchUpIcon = LoadPixmap(resolveFilename(SCOPE_CURRENT_SKIN, "epg/catchup.png"))
			if not self.catchUpIcon:
				self.catchUpIcon = LoadPixmap("/usr/lib/enigma2/python/Plugins/SystemPlugins/M3UIPTV/catchup.png")
			__init_orig__(self, *args, **kwargs)
		EPGListGrid.__init__ = __init_new__

	if EPGSelectionGrid:
		__old_EPGSelectionGrid_init__ = EPGSelectionGrid.__init__
		def __new_EPGSelectionGrid_init__(self, *args, **kwargs):
			EPGSelectionGrid.playArchiveEntry = playArchiveEntry
			__old_EPGSelectionGrid_init__(self, *args, **kwargs)
			self["CatchUpActions"] = HelpableActionMap(self, "M3UIPTVPlayActions",
			{
				"play": (self.playArchiveEntry, _("Play Archive")),
			}, -2)

		EPGSelectionGrid.__init__ = __new_EPGSelectionGrid_init__

	if EPGList:
		if injectCatchupIconGMEPG not in EPGList.buildEntryExtensionFunctions:
			EPGList.buildEntryExtensionFunctions.append(injectCatchupIconGMEPG)
		__init_pli_orig__ = EPGList.__init__
		def __init_pli_new__(self, *args, **kwargs):
			self.catchUpIcon = LoadPixmap(resolveFilename(SCOPE_CURRENT_SKIN, "epg/catchup.png"))
			if not self.catchUpIcon:
				self.catchUpIcon = LoadPixmap("/usr/lib/enigma2/python/Plugins/SystemPlugins/M3UIPTV/catchup.png")
			__init_pli_orig__(self, *args, **kwargs)
		EPGList.__init__ = __init_pli_new__

	if GraphMultiEPG:
		__old_GraphMultiEPG_init__ = GraphMultiEPG.__init__
		def __new_GraphMultiEPG_init__(self, *args, **kwargs):
			GraphMultiEPG.playArchiveEntry = playArchiveEntry
			__old_GraphMultiEPG_init__(self, *args, **kwargs)
			self["CatchUpActions"] = HelpableActionMap(self, "MediaPlayerActions",
			{
				"play": (self.playArchiveEntry, _("Play Archive")),
			}, -2)

		GraphMultiEPG.__init__ = __new_GraphMultiEPG_init__

def injectCatchupIcon(res, obj, service, serviceName, events, picon, channel):
	r2 = obj.eventRect
	left = r2.left()
	top = r2.top()
	width = r2.width()
	if events:
		start = obj.timeBase
		end = start + obj.timeEpochSecs
		now = time()
		for ev in events:
			stime = ev[2]
			duration = ev[3]
			xpos, ewidth = obj.calcEventPosAndWidthHelper(stime, duration, start, end, width)
			if "catchupdays=" in service and stime < now and obj.catchUpIcon:
				pix_size = obj.catchUpIcon.size()
				pix_width = pix_size.width()
				pix_height = pix_size.height()
				match = re.search(r"catchupdays=(\d*)", service)
				catchup_days = int(match.groups(1)[0])
				if now - stime <= datetime.timedelta(days=catchup_days).total_seconds():
					res.append(MultiContentEntryPixmapAlphaBlend(
									pos=(left + xpos + ewidth - pix_width - 10, top + 10),
									size=(pix_width, pix_height),
									png=obj.catchUpIcon,
									flags=0))
					
def injectCatchupIconGMEPG(res, obj, service, service_name, events, picon, serviceref):
	r2 = obj.event_rect
	left = r2.left()
	top = r2.top()
	width = r2.width()
	if events:
		start = obj.time_base + obj.offs * obj.time_epoch * 60
		end = start + obj.time_epoch * 60
		now = time()
		for ev in events:
			stime = ev[2]
			duration = ev[3]
			xpos, ewidth = obj.calcEventPosAndWidthHelper(stime, duration, start, end, width)
			if "catchupdays=" in service and stime < now and obj.catchUpIcon:
				pix_size = obj.catchUpIcon.size()
				pix_width = pix_size.width()
				pix_height = pix_size.height()
				match = re.search(r"catchupdays=(\d*)", service)
				catchup_days = int(match.groups(1)[0])
				if now - stime <= datetime.timedelta(days=catchup_days).total_seconds():
					res.append(MultiContentEntryPixmapAlphaBlend(
									pos=(left + xpos + ewidth - pix_width - 10, top + 10),
									size=(pix_width, pix_height),
									png=obj.catchUpIcon,
									flags=0))

class CatchupPlayer(MoviePlayer):
	def __init__(self, session, service, sref_ret="", slist=None, lastservice=None, event=None, orig_sref="", orig_url="", start_orig=0, end_org=0, duration=0, catchup_ref_type=4097):
		MoviePlayer.__init__(self, session, service=service, slist=slist, lastservice=lastservice)
		self.skinName = ["CatchupPlayer", "ArchiveMoviePlayer", "MoviePlayer"]
		self.onPlayStateChanged.append(self.__playStateChanged)
		self["progress"] = Progress()
		self.seek_steps = [15, 30, 60, 180, 300, 600, 1200]
		self.current_seek_step = 0
		self.current_seek_step_multiplier = 1
		self.skip_progress_update = False
		self.progress_change_interval = 1000
		self.catchup_ref_type = catchup_ref_type
		self.cur_pos_manual = 0
		self.event = event
		self.orig_sref = orig_sref
		self.duration = duration
		self.orig_url = orig_url
		self.sref_ret = sref_ret
		self.start_orig = start_orig
		self.end_orig = end_org
		self.start_curr = start_orig
		self.duration_curr = duration
		self.progress_timer = eTimer()
		self.progress_timer.callback.append(self.onProgressTimer)
		self.progress_timer.start(self.progress_change_interval)
		self.seek_timer = eTimer()
		self.seek_timer.callback.append(self.onSeekRequest)
		self.seekTo_pos = 0
		self.invoked_seek_stime = -1
		self["progress"].value = 0
		self["time_info"] = Label("")
		self["time_elapsed"] = Label("")
		self["time_duration"] = Label("")
		self["time_remaining"] = Label("")
		self.onProgressTimer()
		self.__event_tracker = ServiceEventTracker(screen=self, eventmap={
			iPlayableService.evSeekableStatusChanged: self.__seekableStatusChanged,
			iPlayableService.evStart: self.__evServiceStart,
			iPlayableService.evEnd: self.__evServiceEnd,})
		self["SeekActions"].setEnabled(True)
		
	def setProgress(self, pos):
		r = self.duration - pos
		progress_val = int((pos / self.duration)*100)
		self["progress"].value = progress_val if progress_val >= 0 else 0
		text = "-%d:%02d:%02d         %d:%02d:%02d         +%d:%02d:%02d" % (pos / 3600, pos % 3600 / 60, pos % 60, self.duration / 3600, self.duration % 3600 / 60, self.duration % 60, r / 3600, r % 3600 / 60, r % 60)
		self["time_info"].setText(text)
		text_elapsed = "-%d:%02d:%02d" % (pos / 3600, pos % 3600 / 60, pos % 60)
		self["time_elapsed"].setText(text_elapsed)
		text_duration = "%d:%02d:%02d" % (self.duration / 3600, self.duration % 3600 / 60, self.duration % 60)
		self["time_duration"].setText(text_duration)
		text_remaining = "+%d:%02d:%02d" % (r / 3600, r % 3600 / 60, r % 60)
		self["time_remaining"].setText(text_remaining)

		
	def invokeSeek(self, direction):
		self.seek_timer.stop()
		self.showAfterSeek()
		if self.invoked_seek_stime == -1:
			curr_pos = self.start_curr + self.getPosition()
			self.invoked_seek_stime = curr_pos
		else:
			curr_pos = self.invoked_seek_stime
		p = curr_pos - self.start_orig
		try:
			index = self.seek_steps.index(abs(self.current_seek_step))
			if index < len(self.seek_steps) - 1:
				self.current_seek_step = self.seek_steps[index + 1]*direction
			else:
				self.current_seek_step_multiplier += 1
		except ValueError:
			self.current_seek_step = self.seek_steps[0]*direction
		p += self.current_seek_step*self.current_seek_step_multiplier
		if p >= self.duration:
			p = self.duration
		if p < 0:
			p = 0
		self.seekTo_pos = p
		self.skip_progress_update = True
		self.setProgress(p)
		self.seek_timer.start(1000)

	def onSeekRequest(self):
		self.seek_timer.stop()
		self.doSeekRelative(self.seekTo_pos)
		self.skip_progress_update = False
		self.current_seek_step = 0
		self.current_seek_step_multiplier = 1

	def onProgressTimer(self):
		self.cur_pos_manual += 1
		curr_pos = self.start_curr + self.getPosition()
		p = curr_pos - self.start_orig
		if not self.skip_progress_update:
			self.setProgress(p)

	def getPosition(self):
		return self.cur_pos_manual

	def __evServiceStart(self):
		if self.progress_timer:
			self.progress_timer.start(self.progress_change_interval)
		self.start_curr = self.start_orig + self.seekTo_pos
		self.seekTo_pos = 0

	def __evServiceEnd(self):
		if self.progress_timer:
			self.progress_timer.stop()

	def __playStateChanged(self, state):
		playstateString = state[3]
		if playstateString == '>':
			self.progress_timer.start(self.progress_change_interval)
		elif playstateString == '||':
			self.progress_timer.stop()
		elif playstateString == 'END':
			self.progress_timer.stop()

	def __seekableStatusChanged(self):
		self["SeekActions"].setEnabled(True)
		for c in self.onPlayStateChanged:
			c(self.seekstate)

	def destroy(self):
		if self.progress_timer:
			self.progress_timer.stop()
			self.progress_timer.callback.remove(self.onProgressTimer)
		if self.seek_timer:
			self.seek_timer.callback.remove(self.onSeekRequest)

	def leavePlayer(self):
		self.setResumePoint()
		if self.progress_timer:
			self.progress_timer.stop()
			self.progress_timer.callback.remove(self.onProgressTimer)
		self.handleLeave("quit")

	def leavePlayerOnExit(self):
		if self.shown:
			self.hide()
		else:
			self.leavePlayer()

	def doSeekRelative(self, pts):
		prevstate = self.seekstate
		if self.seekstate == self.SEEK_STATE_EOF:
			if prevstate == self.SEEK_STATE_PAUSE:
				self.setSeekState(self.SEEK_STATE_PAUSE)
			else:
				self.setSeekState(self.SEEK_STATE_PLAY)

		new_start = self.start_orig + pts

		if pts >= self.duration:
			self.seekstate = self.SEEK_STATE_EOF
			self.leavePlayer()

		if pts == 0:
			self.duration_curr = self.duration
		else:
			self.duration_curr -= pts

		sref_split = self.sref_ret.split(":")
		sref_ret = sref_split[10:][0]
		url = constructCatchUpUrl(self.orig_sref, sref_ret, new_start, new_start+self.duration_curr, self.duration_curr)
		newPlayref = eServiceReference(self.catchup_ref_type, 0, url)
		newPlayref.setName(self.event.getEventName())
		self.session.nav.playService(newPlayref)
		self.cur_pos_manual = 0
		self.invoked_seek_stime = -1
		self.onProgressTimer()

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
		self.doSeekRelative(600)
		self.onProgressTimer()

	def down(self):
		self.doSeekRelative(-600)
		self.onProgressTimer()

	def seekBack(self):
		self.invokeSeek(-1)

	def seekFwd(self):
		self.invokeSeek(1)


def playArchiveEntry(self):
	now = time()
	event, service = self["list"].getCurrent()[:2]
	playref, old_ref, is_dynamic, catchup_ref_type = processIPTVService(service, None, event)
	sref = playref.toString()
	if event is not None:
		stime = event.getBeginTime()
		if "catchupdays=" in service.toString() and stime < now:
			match = re.search(r"catchupdays=(\d*)", service.toString())
			catchup_days = int(match.groups(1)[0])
			if now - stime <= datetime.timedelta(days=catchup_days).total_seconds():
				duration = event.getDuration()
				sref_split = sref.split(":")
				url = sref_split[10:][0]
				url = constructCatchUpUrl(service.toString(), url, stime, stime+duration, duration)
				playref = eServiceReference(catchup_ref_type, 0, url)
				playref.setName(event.getEventName())
				infobar = InfoBar.instance
				if infobar:
					LastService = self.session.nav.getCurrentlyPlayingServiceOrGroup()
					self.session.open(CatchupPlayer, playref, sref_ret=sref, slist=infobar.servicelist, lastservice=LastService, event=event, orig_url=url, start_orig=stime, end_org=stime+duration, duration=duration, catchup_ref_type=catchup_ref_type, orig_sref=service.toString())