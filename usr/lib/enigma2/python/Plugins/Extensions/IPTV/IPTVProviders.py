providers = dict()

def processService(nref, callback):
	sRef = nref.toString()
	if sRef.find("%3a//") > -1 and sRef.find("127.0.0.1") == -1:
		splittedRef = nref.toString().split(":")
		iptvinfo = splittedRef[10:11][0]
		url_data = iptvinfo.split("%3a//")
		if len(url_data) < 2:
			return nref, nref, False
		iptv_service = url_data[0]
		iptvinfodata = url_data[1].split("@")
		if not iptv_service in providers:
			return nref, nref, False
		prov = providers[iptv_service]
		ref, old_ref, is_dynamic = prov.processService(nref, iptvinfodata, callback)
		return ref, old_ref, not prov.isPlayBackup 
	else:
		return nref, nref, False
	