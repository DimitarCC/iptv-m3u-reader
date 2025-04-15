# for localized messages
from . import _

from enigma import eServiceReference, eTimer, iPlayableService
from Screens.InfoBar import InfoBar, MoviePlayer
from Screens.MinuteInput import MinuteInput
from Screens.Screen import Screen
from Screens.AudioSelection import AudioSelection
from Screens.MessageBox import MessageBox
from Components.ServiceEventTracker import ServiceEventTracker
from Components.Sources.Progress import Progress
from Components.Label import Label
from Components.Sources.StaticText import StaticText
from Components.MultiContent import MultiContentEntryPixmapAlphaBlend
from Components.config import config
from Components.ActionMap import NumberActionMap, HelpableActionMap
from Tools.BoundFunction import boundFunction
from Tools.Directories import resolveFilename, SCOPE_CURRENT_SKIN
from Tools.LoadPixmap import LoadPixmap
from Tools import Notifications
from Components.SystemInfo import BoxInfo
from .IPTVProcessor import constructCatchUpUrl
from .IPTVProviders import processService as processIPTVService
from time import time
import datetime
import re

try:
	from Screens.InfoBarGenerics import resumePointsInstance
	saveResumePoints = resumePointsInstance.saveResumePoints
	resumePointCache = resumePointsInstance.resumePointCache
except ImportError:
	from Screens.InfoBarGenerics import saveResumePoints, resumePointCache
try:
	from Screens.EpgSelectionGrid import EPGSelectionGrid
except ImportError:
	EPGSelectionGrid = None
try:
	from Screens.EpgSelectionSingle import EPGSelectionSingle
except ImportError:
	EPGSelectionSingle = None
try:
	from Plugins.Extensions.GraphMultiEPG.GraphMultiEpg import EPGList, GraphMultiEPG
except ImportError:
	EPGList = None
	GraphMultiEPG = None


def injectCatchupInEPG():
	if EPGSelectionGrid:
		EPGSelectionGrid.catchupPlayerFunc = playM3UIPTVArchiveEntry

	if EPGSelectionSingle:
		EPGSelectionSingle.catchupPlayerFunc = playM3UIPTVArchiveEntry

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
			self["CatchUpActions"] = HelpableActionMap(self, "M3UIPTVPlayActions",
			{
				"play": (self.playArchiveEntry, _("Play Archive")),
			}, -2)

		GraphMultiEPG.__init__ = __new_GraphMultiEPG_init__


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
			xpos, ewidth = obj.calcEntryPosAndWidthHelper(stime, duration, start, end, width)
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

	

def playM3UIPTVArchiveEntry(self, event, service):
	stime = event.getBeginTime()
	duration = event.getDuration()
	playref, old_ref, is_dynamic, catchup_ref_type = processIPTVService(service, None, event)
	sref = playref.toString()
	sref_split = sref.split(":")
	url = sref_split[10:][0]
	playref = constructCompleteCatchupSref(catchup_ref_type, service.toString(), url, stime, stime + duration, duration)
	playref.setName(event.getEventName())
	infobar = InfoBar.instance
	if infobar:
		LastService = infobar.session.nav.getCurrentServiceReferenceOriginal()
		infobar.session.open(CatchupPlayer, playref, sref_ret=sref, slist=infobar.servicelist, lastservice=LastService, event=event, orig_url=url, start_orig=stime, end_org=stime + duration, duration=duration, catchup_ref_type=catchup_ref_type, orig_sref=service.toString())

def constructCompleteCatchupSref(catchup_service_type, sref, url_play, stime, etime, duration):
	url = constructCatchUpUrl(sref, url_play, stime, etime, duration)
	split_ref = sref.split(":")
	split_ref[0] = str(catchup_service_type)
	result_sref = ":".join(split_ref[:10]) + ":" + url.replace(":", "%3a")
	return eServiceReference(result_sref)


class CatchupPlayer(MoviePlayer):
	def __init__(self, session, service, sref_ret="", slist=None, lastservice=None, event=None, orig_sref="", orig_url="", start_orig=0, end_org=0, duration=0, catchup_ref_type=4097):
		MoviePlayer.__init__(self, session, service=service, slist=slist, lastservice=lastservice)
		self.skinName = ["CatchupPlayer", "ArchiveMoviePlayer", "MoviePlayer"]
		self["NumberSeekActions"] = NumberActionMap(["NumberActions"],
		{
			"1": self.numberSeek,
			"3": self.numberSeek,
			"4": self.numberSeek,
			"6": self.numberSeek,
			"7": self.numberSeek,
			"9": self.numberSeek,
		}, -10)  # noqa: E123
		self.onPlayStateChanged.append(self.__playStateChanged)
		self["progress"] = Progress()
		self["progress_summary"] = Progress()
		self.seek_steps = [15, 30, 60, 180, 300, 600, 1200]
		self.current_seek_step = 0
		self.current_seek_step_multiplier = 1
		self.skip_progress_update = False
		self.progress_change_interval = 1000
		self.catchup_ref_type = catchup_ref_type
		self.event = event
		self.orig_sref = orig_sref
		self.duration = duration
		self.orig_url = orig_url
		self.sref_ret = sref_ret
		self.start_orig = start_orig
		self.end_orig = end_org
		self.start_curr = start_orig
		self.duration_curr = duration
		self.current_time_manual = 0
		self.progress_timer = eTimer()
		self.progress_timer.callback.append(self.onProgressTimer)
		self.progress_timer.start(self.progress_change_interval)
		self.seek_timer = eTimer()
		self.seek_timer.callback.append(self.onSeekRequest)
		self.seekTo_pos = 0
		self.invoked_seek_stime = -1
		self.resume_point = None
		self.isSeeking = False
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
		self.onProgressTimer()
		self.onClose.append(self._onClose)
		self.__event_tracker = ServiceEventTracker(screen=self, eventmap={
			iPlayableService.evSeekableStatusChanged: self.__seekableStatusChanged,
			iPlayableService.evStart: self.__evServiceStart,
			iPlayableService.evEnd: self.__evServiceEnd, })
		self["SeekActions"].setEnabled(True)
		if hasattr(AudioSelection, "audioHooks") and self.onAudioSubTrackChanged not in AudioSelection.audioHooks:
			AudioSelection.audioHooks.append(self.onAudioSubTrackChanged)

	def _onClose(self):
		if hasattr(AudioSelection, "audioHooks") and self.onAudioSubTrackChanged in AudioSelection.audioHooks:
			AudioSelection.audioHooks.remove(self.onAudioSubTrackChanged)

	def setProgress(self, pos):
		r = self.duration - pos
		progress_val = i if (i := int((pos / self.duration) * 100)) and i >= 0 else 0
		self["progress"].value = progress_val
		self["progress_summary"].value = progress_val
		text = "-%d:%02d:%02d         %d:%02d:%02d         +%d:%02d:%02d" % (pos / 3600, pos % 3600 / 60, pos % 60, self.duration / 3600, self.duration % 3600 / 60, self.duration % 60, r / 3600, r % 3600 / 60, r % 60)
		self["time_info"].setText(text)
		self["time_info_summary"].setText(text)
		text_elapsed = "-%d:%02d:%02d" % (pos / 3600, pos % 3600 / 60, pos % 60)
		self["time_elapsed"].setText(text_elapsed)
		self["time_elapsed_summary"].setText(text_elapsed)
		text_duration = "%d:%02d:%02d" % (self.duration / 3600, self.duration % 3600 / 60, self.duration % 60)
		self["time_duration"].setText(text_duration)
		self["time_duration_summary"].setText(text_duration)
		text_remaining = "+%d:%02d:%02d" % (r / 3600, r % 3600 / 60, r % 60)
		self["time_remaining"].setText(text_remaining)
		self["time_remaining_summary"].setText(text_remaining)

	def onAudioSubTrackChanged(self):
		self.doServiceRestart()

	def invokeSeek(self, direction=0):
		self.seek_timer.stop()
		self.showAfterSeek()
		self.isSeeking = True
		if self.invoked_seek_stime == -1:
			curr_pos = self.start_curr + self.getPosition()
			self.invoked_seek_stime = curr_pos
		else:
			curr_pos = self.invoked_seek_stime
		p = curr_pos - self.start_orig
		if direction:  # if direction == 0 skip the incrementing stuff and use self.current_seek_step directly
			try:
				index = self.seek_steps.index(abs(self.current_seek_step))
				if index < len(self.seek_steps) - 1:
					self.current_seek_step = self.seek_steps[index + 1] * direction
				else:
					self.current_seek_step_multiplier += 1
			except ValueError:
				self.current_seek_step = self.seek_steps[0] * direction
		p += self.current_seek_step * self.current_seek_step_multiplier
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
		curr_pos = self.start_curr + self.getPosition()
		self.current_time_manual += 1
		if curr_pos >= self.end_orig:
			self.doEofInternal(True)
		p = curr_pos - self.start_orig
		if not self.skip_progress_update:
			self.setProgress(p)

	def getPosition(self):
		if BoxInfo.getItem("mediaservice") == "servicehisilicon" and self.catchup_ref_type == 4097:
			return self.current_time_manual
		seekable = self.getSeek()
		if seekable is not None:
			pos = seekable.getPlayPosition()
			if not pos[0]:
				return pos[1] // 90000
		return 0

	def playLastCB(self, answer):
		if answer is True and self.resume_point:
			self.isSeeking = True
			self.seekTo_pos = self.resume_point
			self.doSeekRelative(self.seekTo_pos)

	def getResumePoint(self):
		key = self.orig_sref + "|st=" + str(self.start_orig)
		if key in resumePointCache:
			entry = resumePointCache[key]
			entry[0] = int(time())  # update LRU timestamp
			return entry[1]

	def delResumePoint(self):
		key = self.orig_sref + "|st=" + str(self.start_orig)
		if key in resumePointCache:
			del resumePointCache[key]
			saveResumePoints()

	def __evServiceStart(self):
		self.current_time_manual = 0
		if self.progress_timer:
			self.progress_timer.start(self.progress_change_interval)
		self.start_curr = self.start_orig + self.seekTo_pos
		self.seekTo_pos = 0
		self.invoked_seek_stime = -1
		self.onProgressTimer()
		if not self.isSeeking:
			self.resume_point = self.getResumePoint()
			if self.resume_point is not None:
				x = self.resume_point
				Notifications.AddNotificationWithCallback(self.playLastCB, MessageBox, _("Do you want to resume playback?") + "\n" + (_("Resume position at %s") % ("%d:%02d:%02d" % (x / 3600, x % 3600 / 60, x % 60))), timeout=30, default="yes" in config.usage.on_movie_start.value)
		self.isSeeking = False

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

	def doServiceRestart(self):
		curr_pos = self.start_curr + self.getPosition()
		self.seekTo_pos = curr_pos - self.start_orig
		self.doSeekRelative(self.seekTo_pos + 2)

	def doSeekRelative(self, pts):
		self.progress_timer.stop()

		prevstate = self.seekstate
		if self.seekstate == self.SEEK_STATE_EOF:
			if prevstate == self.SEEK_STATE_PAUSE:
				self.setSeekState(self.SEEK_STATE_PAUSE)
			else:
				self.setSeekState(self.SEEK_STATE_PLAY)

		new_start = self.start_orig + pts

		if pts >= self.duration:
			self.doEofInternal(True)

		if pts == 0:
			self.duration_curr = self.duration
		else:
			self.duration_curr = self.duration - pts
		sref_split = self.sref_ret.split(":")
		sref_ret = sref_split[10:][0]
		newPlayref = constructCompleteCatchupSref(self.catchup_ref_type, self.orig_sref, sref_ret, new_start, new_start + self.duration_curr, self.duration_curr)
		newPlayref.setName(self.event.getEventName())
		self.session.nav.playService(newPlayref, forceRestart=True)
		self.onProgressTimer()

	def setResumePoint(self):
		service = self.session.nav.getCurrentService()
		if (service is not None):
			curr_pos = self.start_curr + self.getPosition()
			pos = curr_pos - self.start_orig
			key = self.orig_sref + "|st=" + str(self.start_orig)
			lru = int(time())
			sl = self.duration
			resumePointCache[key] = [lru, pos, sl]
			saveResumePoints()

	def doEofInternal(self, playing):
		if not self.execing:
			return
		if not playing:
			return
		if self.progress_timer:
			self.progress_timer.stop()
			self.progress_timer.callback.remove(self.onProgressTimer)
		self.delResumePoint()
		self.handleLeave("quit")

	def up(self):
		self.current_seek_step += 600
		self.invokeSeek()

	def down(self):
		self.current_seek_step += -600
		self.invokeSeek()

	def seekBack(self):
		self.invokeSeek(-1)

	def seekFwd(self):
		self.invokeSeek(1)

	def numberSeek(self, key):
		self.current_seek_step_multiplier = 1
		self.current_seek_step += {1: - config.seek.selfdefined_13.value, 3: config.seek.selfdefined_13.value, 4: - config.seek.selfdefined_46.value, 6: config.seek.selfdefined_46.value, 7: - config.seek.selfdefined_79.value, 9: config.seek.selfdefined_79.value}[key]
		self.invokeSeek()

	def seekFwdSeekbar(self):
		seek = self.session.openWithCallback(boundFunction(self.SeekTo, 1), MinuteInput)
		seek.title = _("Seek forwards")

	def seekBackSeekbar(self):
		seek = self.session.openWithCallback(boundFunction(self.SeekTo, -1), MinuteInput)
		seek.title = _("Seek back")

	def SeekTo(self, direction, minutes):
		if minutes:
			self.current_seek_step_multiplier = 1
			self.current_seek_step = minutes * 60 * direction
			self.invokeSeek()

	def createSummary(self):
		return CatchupPlayerSummary


class CatchupPlayerSummary(Screen):
	skin = """
	<screen position="0,0" size="800,480" resolution="800,480">
		<widget source="session.CurrentService" render="Label" position="40,90" size="720,260" font="Regular;30" halign="center" valign="center" zPosition="2">
			<convert type="ServiceName">Name</convert>
		</widget>
		<widget source="parent.progress_summary" render="Progress" position="40,340" size="720,30" borderColor="white" borderWidth="2" zPosition="2"/>
		<widget source="parent.time_elapsed_summary" render="Label" position="40,385" size="320,70" font="Regular;25" halign="left" valign="center"/>
		<widget source="parent.time_remaining_summary" render="Label" position="440,385" size="320,70" font="Regular;25" halign="right" valign="center"/>
		<widget source="global.CurrentTime" render="Label" position="540,10" size="220,84" font="Regular;35" halign="left">
			<convert type="ClockToText">Default</convert>
		</widget>
	</screen>"""

def playArchiveEntry(self):
	now = time()
	event, service = self["list"].getCurrent()[:2]
	playref, old_ref, is_dynamic, catchup_ref_type = processIPTVService(service, None, event)
	sref = playref.toString()
	if event is not None:
		stime = event.getBeginTime()
		if "catchupdays=" in service.toString() and stime < now:
			match = re.search(r"catchupdays=(\d*)", service.toString())
			catchup_days = int(match.group(1))
			if now - stime <= datetime.timedelta(days=catchup_days).total_seconds():
				duration = event.getDuration()
				sref_split = sref.split(":")
				url = sref_split[10:][0]
				playref = constructCompleteCatchupSref(catchup_ref_type, service.toString(), url, stime, stime + duration, duration)
				playref.setName(event.getEventName())
				infobar = InfoBar.instance
				if infobar:
					LastService = self.session.nav.getCurrentServiceReferenceOriginal()
					self.session.open(CatchupPlayer, playref, sref_ret=sref, slist=infobar.servicelist, lastservice=LastService, event=event, orig_url=url, start_orig=stime, end_org=stime + duration, duration=duration, catchup_ref_type=catchup_ref_type, orig_sref=service.toString())
