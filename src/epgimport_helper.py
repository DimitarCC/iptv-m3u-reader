import os
from xml.sax.saxutils import escape

from enigma import eEPGCache, eTimer

try:
	import Plugins.Extensions.EPGImport.EPGConfig as EPGConfig
	import Plugins.Extensions.EPGImport.EPGImport as EPGImport
except ImportError:  # plugin not available
	EPGImport = None
	EPGConfig = None


EPGIMPORTPATH = '/etc/epgimport/'

class epgimport_helper():
	def __init__(self, provider):
		self.provider = provider
		self.update_status_timer = eTimer()
		self.update_status_timer.callback.append(self.update_status)

	@staticmethod
	def xml_escape(string):
		return escape(string, {'"': '&quot;', "'": "&apos;"})
	
	def getSourcesFilename(self):
		return os.path.join(EPGIMPORTPATH, 'm3uiptv.%s.sources.xml' % self.provider.scheme)
	
	def getChannelsFilename(self):
		return os.path.join(EPGIMPORTPATH, 'm3uiptv.%s.channels.xml' % self.provider.scheme)
	
	def createSourcesFile(self):
		if not EPGImport:
			return

		sources_out = [
			'<?xml version="1.0" encoding="utf-8"?>', 
			'<sources>',
			' <sourcecat sourcecatname="M3UIPTV plugin">',
			'  <source type="gen_xmltv" nocheck="1" channels="%s">' % self.getChannelsFilename(),
			'   <description>%s</description>' % self.xml_escape(self.provider.iptv_service_provider),
			'   <url><![CDATA[%s]]></url>' % self.provider.getEpgUrl(),
			'  </source>',
			' </sourcecat>',
			'</sources>']
		with open(os.path.join(self.getSourcesFilename()), "w") as f:
			f.write("\n".join(sources_out))

	def createChannelsFile(self, groups):
		if not EPGImport:
			return

		channels_out = ['<?xml version="1.0" encoding="utf-8"?>', '<channels>']
		for group in groups:
			channels_out.append(f' <!-- {groups[group][0]} -->')
			for service in groups[group][1]:
				sref, epg_id, ch_name = service
				channels_out.append(f' <channel id="{epg_id}">{self.provider.generateEPGChannelReference(sref)}</channel> <!-- {ch_name.replace("--", "")} -->')
		channels_out.append('</channels>')
		with open(os.path.join(self.getChannelsFilename()), "w") as f:
			f.write("\n".join(channels_out))

	#  not working yet
	def importepg(self):
		if EPGImport and EPGConfig and os.path.exists(f := self.getSourcesFilename()):
			self.update_status_timer.start(1000)
			self.epgimport = EPGImport.EPGImport(eEPGCache.getInstance(), lambda x: True)
			self.epgimport.sources = [s for s in self.epgimport_sources([f])]
			self.epgimport.onDone = self.epgimport_done
			self.epgimport.beginImport()

	def update_status(self):
		if self.epgimport and self.epgimport.isImportRunning():
			for f in self.provider.update_status_callback:
				f(_("EPG Import: Importing %s %s events") % (self.epgimport.source.description, self.epgimport.eventCount))
			

	def epgimport_sources(self, sourcefiles):
	    for sourcefile in sourcefiles:
	        try:
	            for s in EPGConfig.enumSourcesFile(sourcefile):
	                yield s
	        except Exception as e:
	            print('[M3UIPTV] epgimport_sources Failed to open epg source ', sourcefile, ' Error: ', e)

	def epgimport_done(self, reboot=False, epgfile=None):
		self.update_status_timer.stop()
		for f in self.provider.update_status_callback:
			f(_("EPG Import: Importing events for %s completed") % self.provider.iptv_service_provider)
