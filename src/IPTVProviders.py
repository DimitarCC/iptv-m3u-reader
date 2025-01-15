import re

providers = dict()


def processService(nref, callback, event=None):
	sRef = nref.toString()
	if sRef.find("%3a//") > -1 and sRef.find("127.0.0.1") == -1:
		splittedRef = nref.toString().split(":")
		iptvinfo = splittedRef[10:11][0]
		url_data = iptvinfo.split("%3a//")
		if len(url_data) < 2:
			return nref, nref, False, nref.type
		iptv_service = url_data[0]
		iptvinfodata = url_data[1] if len(url_data) == 2 else "%3a//".join(url_data[1:])
		if iptv_service not in providers:
			match_cplay_system = re.search(r"catchupstype\=(.*?)[&]", sRef)
			cplay_system = nref.type
			if match_cplay_system:
				cplay_system = int(match_cplay_system.group(1))
			return nref, nref, False, cplay_system
		prov = providers[iptv_service]
		ref, old_ref, is_dynamic = prov.processService(nref, iptvinfodata, callback, event)
		return ref, old_ref, not prov.isPlayBackup, int(prov.play_system_catchup)
	else:
		return nref, nref, False, nref.type
