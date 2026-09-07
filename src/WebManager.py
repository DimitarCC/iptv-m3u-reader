# for localized messages
from . import _

import json
import shutil
from os import makedirs
from binascii import a2b_base64

from twisted.web import resource, server
from twisted.internet import reactor

from Components.config import config

from .IPTVProviders import providers
from .M3UProvider import M3UProvider
from .XtreemProvider import XtreemProvider
from .StalkerProvider import StalkerProvider
from .TVHeadendProvider import TVHeadendProvider
from .VODProvider import VODProvider
from .Variables import PROVIDER_FOLDER, CATCHUP_DEFAULT, CATCHUP_APPEND, CATCHUP_SHIFT, CATCHUP_XTREME, CATCHUP_XTREME_60, CATCHUP_STALKER, CATCHUP_FLUSSONIC, CATCHUP_VOD

PROVIDER_TYPES = ("M3U", "Xtreeme", "Stalker", "TVH", "VOD")

CATCHUP_TYPE_CHOICES = [CATCHUP_DEFAULT, CATCHUP_APPEND, CATCHUP_SHIFT, CATCHUP_XTREME, CATCHUP_XTREME_60, CATCHUP_STALKER, CATCHUP_FLUSSONIC, CATCHUP_VOD]


def _getWriteProviders():
	# imported lazily to avoid a circular import between plugin.py and this module
	from .plugin import writeProviders
	return writeProviders


def providerToDict(providerObj):
	return {
		"scheme": providerObj.scheme,
		"type": providerObj.type,
		"iptv_service_provider": providerObj.iptv_service_provider,
		"url": providerObj.url,
		"playlist_type": getattr(providerObj, "playlist_type", "m3u"),
		"refresh_interval": providerObj.refresh_interval,
		"static_urls": providerObj.static_urls,
		"search_criteria": providerObj.search_criteria,
		"ignore_vod": providerObj.ignore_vod,
		"create_epg": providerObj.create_epg,
		"epg_url": providerObj.epg_url,
		"is_custom_xmltv": providerObj.is_custom_xmltv,
		"custom_xmltv_url": providerObj.custom_xmltv_url,
		"epg_match_strategy": providerObj.epg_match_strategy,
		"username": providerObj.username,
		"password": providerObj.password,
		"mac": providerObj.mac,
		"custom_serial": getattr(providerObj, "custom_serial", ""),
		"custom_device_id1": getattr(providerObj, "custom_device_id1", ""),
		"custom_device_id2": getattr(providerObj, "custom_device_id2", ""),
		"custom_signature": getattr(providerObj, "custom_signature", ""),
		"epg_time_offset": getattr(providerObj, "epg_time_offset", 0),
		"play_system": providerObj.play_system,
		"play_system_catchup": providerObj.play_system_catchup,
		"output_format": providerObj.output_format,
		"catchup_type": providerObj.catchup_type,
		"picons": providerObj.picons,
		"picon_gen_strategy": providerObj.picon_gen_strategy,
		"picon_threads": providerObj.picon_threads,
		"create_bouquets_strategy": providerObj.create_bouquets_strategy,
		"use_provider_tsid": providerObj.use_provider_tsid,
		"user_provider_ch_num": providerObj.user_provider_ch_num,
		"provider_tsid_search_criteria": providerObj.provider_tsid_search_criteria,
		"ch_order_strategy": providerObj.ch_order_strategy,
		"custom_user_agent": providerObj.custom_user_agent,
		"auto_updates": providerObj.auto_updates,
		"has_media_library": providerObj.has_media_library,
		"media_library_type": providerObj.media_library_type,
		"media_library_url": providerObj.media_library_url,
		"media_library_username": providerObj.media_library_username,
		"media_library_password": providerObj.media_library_password,
		"media_library_token": providerObj.media_library_token,
	}


def newProviderForType(ptype, existing=None):
	cls = {"M3U": M3UProvider, "Xtreeme": XtreemProvider, "Stalker": StalkerProvider, "TVH": TVHeadendProvider, "VOD": VODProvider}[ptype]
	if existing is not None and isinstance(existing, cls):
		return existing
	return cls()


def applyProviderData(providerObj, data, is_edit):
	ptype = providerObj.type
	providerObj.iptv_service_provider = data.get("iptv_service_provider", "").strip()
	providerObj.url = data.get("url", "").strip()
	providerObj.ignore_vod = bool(data.get("ignore_vod", providerObj.ignore_vod))
	providerObj.auto_updates = bool(data.get("auto_updates", providerObj.auto_updates))

	if ptype != "VOD":
		providerObj.play_system = str(data.get("play_system", providerObj.play_system))
		providerObj.play_system_catchup = str(data.get("play_system_catchup", providerObj.play_system_catchup))
		providerObj.create_epg = bool(data.get("create_epg", providerObj.create_epg))
		providerObj.picons = bool(data.get("picons", providerObj.picons))
		providerObj.picon_gen_strategy = int(data.get("picon_gen_strategy", providerObj.picon_gen_strategy))
		providerObj.picon_threads = int(data.get("picon_threads", providerObj.picon_threads))
		providerObj.create_bouquets_strategy = int(data.get("create_bouquets_strategy", providerObj.create_bouquets_strategy))
		providerObj.use_provider_tsid = bool(data.get("use_provider_tsid", providerObj.use_provider_tsid))
		providerObj.user_provider_ch_num = bool(data.get("user_provider_ch_num", providerObj.user_provider_ch_num))
		providerObj.provider_tsid_search_criteria = data.get("provider_tsid_search_criteria", providerObj.provider_tsid_search_criteria)
		providerObj.custom_user_agent = data.get("custom_user_agent", providerObj.custom_user_agent)
		providerObj.ch_order_strategy = int(data.get("ch_order_strategy", providerObj.ch_order_strategy))

		if ptype in ("Xtreeme", "M3U"):
			providerObj.catchup_type = int(data.get("catchup_type", providerObj.catchup_type))

		if ptype == "M3U":
			providerObj.refresh_interval = int(data.get("refresh_interval", providerObj.refresh_interval))
			providerObj.static_urls = bool(data.get("static_urls", providerObj.static_urls))
			providerObj.search_criteria = data.get("search_criteria", providerObj.search_criteria)
			providerObj.epg_url = data.get("epg_url", providerObj.epg_url)
			providerObj.is_custom_xmltv = bool(data.get("is_custom_xmltv", providerObj.is_custom_xmltv))
			providerObj.custom_xmltv_url = data.get("custom_xmltv_url", providerObj.custom_xmltv_url)
			providerObj.epg_match_strategy = int(data.get("epg_match_strategy", providerObj.epg_match_strategy))
			providerObj.has_media_library = bool(data.get("has_media_library", providerObj.has_media_library))
			providerObj.media_library_type = data.get("media_library_type", providerObj.media_library_type)
			providerObj.media_library_url = data.get("media_library_url", providerObj.media_library_url)
			providerObj.media_library_username = data.get("media_library_username", providerObj.media_library_username)
			providerObj.media_library_password = data.get("media_library_password", providerObj.media_library_password)
			providerObj.media_library_token = data.get("media_library_token", providerObj.media_library_token)
		elif ptype in ("Xtreeme", "TVH"):
			providerObj.username = data.get("username", providerObj.username)
			providerObj.password = data.get("password", providerObj.password)
			providerObj.is_custom_xmltv = bool(data.get("is_custom_xmltv", providerObj.is_custom_xmltv))
			providerObj.custom_xmltv_url = data.get("custom_xmltv_url", providerObj.custom_xmltv_url)
			if ptype == "Xtreeme":
				providerObj.output_format = data.get("output_format", providerObj.output_format)
		elif ptype == "Stalker":
			new_mac = data.get("mac", providerObj.mac)
			new_serial = data.get("custom_serial", providerObj.custom_serial)
			new_devid1 = data.get("custom_device_id1", providerObj.custom_device_id1)
			new_devid2 = data.get("custom_device_id2", providerObj.custom_device_id2)
			new_signature = data.get("custom_signature", providerObj.custom_signature)
			if new_mac != providerObj.mac:
				providerObj.serial = ""
				providerObj.devid = ""
				providerObj.devid2 = ""
				providerObj.signature = ""
			if new_serial != providerObj.custom_serial:
				providerObj.serial = ""
			if new_devid1 != providerObj.custom_device_id1:
				providerObj.devid = ""
			if new_devid2 != providerObj.custom_device_id2:
				providerObj.devid2 = ""
			if new_signature != providerObj.custom_signature or new_serial != providerObj.custom_serial or new_devid1 != providerObj.custom_device_id1 or new_devid2 != providerObj.custom_device_id2:
				providerObj.signature = ""
			providerObj.mac = new_mac
			providerObj.custom_serial = new_serial
			providerObj.custom_device_id1 = new_devid1
			providerObj.custom_device_id2 = new_devid2
			providerObj.custom_signature = new_signature
			providerObj.output_format = data.get("output_format", providerObj.output_format)
			providerObj.epg_time_offset = int(data.get("epg_time_offset", providerObj.epg_time_offset))
	else:
		providerObj.playlist_type = data.get("playlist_type", providerObj.playlist_type)

	if getattr(providerObj, "onid", None) is None:
		used = {x.onid for x in providers.values() if hasattr(x, "onid")}
		providerObj.onid = min(set(range(1, len(used) + 2)) - used)

	return providerObj


def validateProviderData(ptype, data, scheme, is_edit):
	if ptype not in PROVIDER_TYPES:
		return _("Invalid provider type.")
	if not data.get("iptv_service_provider", "").strip():
		return _("Provider name must be filled in.")
	if not data.get("url", "").strip():
		return _("URL must be filled in.")
	if not scheme:
		return _("Scheme must be filled in.")
	if not is_edit and scheme in providers:
		return _("Scheme must be unique. \"%s\" is already in use. Please update this field.") % scheme
	if ptype == "Xtreeme" and (not data.get("username", "").strip() or not data.get("password", "")):
		return _("Username and password must be filled in for Xtreme Codes providers.")
	if ptype == "Stalker" and not data.get("mac", "").strip():
		return _("MAC address must be filled in for Stalker providers.")
	return None


def checkAuth(request):
	username = config.plugins.m3uiptv.webmanager_username.value
	password = config.plugins.m3uiptv.webmanager_password.value
	if not username:
		return True
	auth_header = request.requestHeaders.getRawHeaders(b"authorization")
	if not auth_header:
		return False
	try:
		scheme, _sep, creds = auth_header[0].partition(b" ")
		if scheme.lower() != b"basic":
			return False
		decoded = a2b_base64(creds).decode("utf-8")
		user, _sep2, pwd = decoded.partition(":")
	except Exception:
		return False
	return user == username and pwd == password


def requireAuth(request):
	request.setResponseCode(401)
	request.setHeader(b"WWW-Authenticate", b'Basic realm="M3UIPTV Playlist Manager"')
	request.setHeader(b"Content-Type", b"text/plain; charset=utf-8")
	return b"Authentication required"


class JsonResource(resource.Resource):
	def jsonResponse(self, request, obj, code=200):
		request.setResponseCode(code)
		request.setHeader(b"Content-Type", b"application/json; charset=utf-8")
		return json.dumps(obj).encode("utf-8")

	def readJsonBody(self, request):
		try:
			raw = request.content.read()
			return json.loads(raw.decode("utf-8")) if raw else {}
		except Exception:
			return None

	def render(self, request):
		if not checkAuth(request):
			return requireAuth(request)
		return resource.Resource.render(self, request)


class ProviderItemResource(JsonResource):
	isLeaf = True

	def __init__(self, scheme):
		JsonResource.__init__(self)
		self.scheme = scheme

	def render_GET(self, request):
		providerObj = providers.get(self.scheme)
		if providerObj is None:
			return self.jsonResponse(request, {"error": _("Provider not found.")}, 404)
		return self.jsonResponse(request, providerToDict(providerObj))

	def render_PUT(self, request):
		providerObj = providers.get(self.scheme)
		if providerObj is None:
			return self.jsonResponse(request, {"error": _("Provider not found.")}, 404)
		data = self.readJsonBody(request)
		if data is None:
			return self.jsonResponse(request, {"error": _("Invalid JSON body.")}, 400)
		ptype = providerObj.type
		error = validateProviderData(ptype, data, self.scheme, True)
		if error:
			return self.jsonResponse(request, {"error": error}, 400)
		providerObj = applyProviderData(providerObj, data, True)
		providers[self.scheme] = providerObj
		_getWriteProviders()()
		return self.jsonResponse(request, providerToDict(providerObj))

	def render_DELETE(self, request):
		providerObj = providers.get(self.scheme)
		if providerObj is None:
			return self.jsonResponse(request, {"error": _("Provider not found.")}, 404)
		try:
			providerObj.removeBouquets()
			providerObj.removeVoDData()
			providerObj.removeEpgSources()
			providerObj.removePicons()
		except Exception as err:
			print("[M3UIPTV][WebManager] error during provider cleanup on delete:", err)
		del providers[self.scheme]
		_getWriteProviders()()
		shutil.rmtree(PROVIDER_FOLDER % self.scheme, True)
		return self.jsonResponse(request, {"ok": True})


class ProvidersResource(JsonResource):
	def getChild(self, name, request):
		scheme = name.decode("utf-8") if isinstance(name, bytes) else name
		if not scheme:
			return self
		return ProviderItemResource(scheme)

	def render_GET(self, request):
		result = [providerToDict(providers[scheme]) for scheme in sorted(providers, key=lambda s: providers[s].iptv_service_provider.lower())]
		return self.jsonResponse(request, result)

	def render_POST(self, request):
		data = self.readJsonBody(request)
		if data is None:
			return self.jsonResponse(request, {"error": _("Invalid JSON body.")}, 400)
		ptype = data.get("type", "M3U")
		scheme = M3UProvider().cleanFilename(data.get("scheme", "").strip())
		error = validateProviderData(ptype, data, scheme, False)
		if error:
			return self.jsonResponse(request, {"error": error}, 400)
		providerObj = newProviderForType(ptype)
		providerObj.scheme = scheme
		providerObj = applyProviderData(providerObj, data, False)
		makedirs(PROVIDER_FOLDER % scheme, exist_ok=True)
		providers[scheme] = providerObj
		_getWriteProviders()()
		return self.jsonResponse(request, providerToDict(providerObj), 201)


class MetaResource(JsonResource):
	isLeaf = True

	def render_GET(self, request):
		return self.jsonResponse(request, {
			"provider_types": PROVIDER_TYPES,
			"catchup_types": CATCHUP_TYPE_CHOICES,
		})


class IndexResource(resource.Resource):
	isLeaf = True

	def render_GET(self, request):
		if not checkAuth(request):
			return requireAuth(request)
		request.setHeader(b"Content-Type", b"text/html; charset=utf-8")
		return WEB_UI_HTML.encode("utf-8")


class WebManagerRoot(resource.Resource):
	def __init__(self):
		resource.Resource.__init__(self)
		self.putChild(b"", IndexResource())
		api = resource.Resource()
		api.putChild(b"providers", ProvidersResource())
		api.putChild(b"meta", MetaResource())
		self.putChild(b"api", api)


_site_port = None


def startWebManager():
	global _site_port
	if _site_port is not None:
		return
	port = config.plugins.m3uiptv.webmanager_port.value
	site = server.Site(WebManagerRoot())
	_site_port = reactor.listenTCP(port, site)


WEB_UI_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>M3UIPTV Playlist Manager</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root {
    color-scheme: light dark;
    --bg: #f2f2f2;
    --text: #222;
    --text-muted: #777;
    --header-bg: #1d3557;
    --header-text: #fff;
    --surface: #fff;
    --surface-alt: #f7f7f7;
    --surface-hover: #fafafa;
    --border: #e0e0e0;
    --input-border: #ccc;
    --input-bg: #fff;
    --shadow: rgba(0,0,0,.15);
    --backdrop: rgba(0,0,0,.5);
    --accent: #1d3557;
    --accent-text: #fff;
    --danger: #c0392b;
    --danger-text: #fff;
    --secondary-bg: #ddd;
    --secondary-text: #222;
    --badge-bg: #e0e6f0;
    --badge-text: #1d3557;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #16181d;
      --text: #e6e6e6;
      --text-muted: #9a9a9a;
      --header-bg: #12233f;
      --header-text: #fff;
      --surface: #22252c;
      --surface-alt: #2a2d35;
      --surface-hover: #2f333c;
      --border: #383c46;
      --input-border: #4a4e59;
      --input-bg: #1b1e24;
      --shadow: rgba(0,0,0,.4);
      --backdrop: rgba(0,0,0,.65);
      --accent: #3a6ea5;
      --accent-text: #fff;
      --danger: #e0574a;
      --danger-text: #fff;
      --secondary-bg: #3a3e47;
      --secondary-text: #e6e6e6;
      --badge-bg: #2c3a52;
      --badge-text: #a9c5eb;
    }
  }
  body { font-family: sans-serif; margin: 0; padding: 0; background: var(--bg); color: var(--text); }
  header { background: var(--header-bg); color: var(--header-text); padding: 16px 24px; }
  header h1 { margin: 0; font-size: 20px; }
  main { max-width: 960px; margin: 24px auto; padding: 0 16px; }
  table { width: 100%; border-collapse: collapse; background: var(--surface); box-shadow: 0 1px 3px var(--shadow); }
  th, td { text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--border); font-size: 14px; }
  th { background: var(--surface-alt); }
  tr:hover td { background: var(--surface-hover); }
  .actions button { margin-right: 6px; }
  button { cursor: pointer; border: none; border-radius: 4px; padding: 6px 12px; font-size: 13px; }
  .btn-primary { background: var(--accent); color: var(--accent-text); }
  .btn-danger { background: var(--danger); color: var(--danger-text); }
  .btn-secondary { background: var(--secondary-bg); color: var(--secondary-text); }
  .toolbar { margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center; }
  .modal-backdrop { position: fixed; inset: 0; background: var(--backdrop); display: none; align-items: center; justify-content: center; padding: 16px; }
  .modal-backdrop.open { display: flex; }
  .modal { background: var(--surface); border-radius: 6px; width: 100%; max-width: 640px; max-height: 90vh; overflow-y: auto; padding: 20px 24px; }
  .modal h2 { margin-top: 0; }
  .field { margin-bottom: 12px; display: flex; flex-direction: column; gap: 4px; }
  .field label { font-size: 13px; font-weight: 600; }
  .field input[type=text], .field input[type=password], .field input[type=number], .field select {
    padding: 6px 8px; font-size: 14px; border: 1px solid var(--input-border); border-radius: 4px;
    background: var(--input-bg); color: var(--text);
  }
  .field.checkbox { flex-direction: row; align-items: center; }
  .field.checkbox label { font-weight: normal; }
  .row { display: flex; gap: 12px; }
  .row .field { flex: 1; }
  .modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
  .error { color: var(--danger); font-size: 13px; margin-bottom: 8px; }
  .type-badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 12px; background: var(--badge-bg); color: var(--badge-text); }
  .empty { padding: 24px; text-align: center; color: var(--text-muted); }
  fieldset { border: 1px solid var(--border); border-radius: 4px; margin: 0 0 12px 0; }
  legend { font-size: 13px; font-weight: 600; padding: 0 6px; }
</style>
</head>
<body>
<header><h1>M3UIPTV &mdash; Playlist Manager</h1></header>
<main>
  <div class="toolbar">
    <div id="count"></div>
    <button class="btn-primary" id="btnAdd">+ Add provider</button>
  </div>
  <div id="tableWrap">
    <table id="table">
      <thead><tr><th>Name</th><th>Type</th><th>URL</th><th>Scheme</th><th></th></tr></thead>
      <tbody id="tbody"></tbody>
    </table>
  </div>
</main>

<div class="modal-backdrop" id="backdrop">
  <div class="modal">
    <h2 id="modalTitle">Add provider</h2>
    <div class="error" id="formError" style="display:none"></div>
    <form id="providerForm">
      <div class="field">
        <label>Provider Type</label>
        <select name="type" id="fType">
          <option value="M3U">M3U/M3U8</option>
          <option value="Xtreeme">Xtreme Codes</option>
          <option value="Stalker">Stalker portal</option>
          <option value="TVH">TVHeadend server</option>
          <option value="VOD">Video on Demand</option>
        </select>
      </div>
      <div class="field">
        <label>Provider name</label>
        <input type="text" name="iptv_service_provider" required>
      </div>
      <div class="field">
        <label>URL</label>
        <input type="text" name="url" required>
      </div>
      <div class="field" id="fSchemeWrap">
        <label>Scheme (unique id)</label>
        <input type="text" name="scheme" required>
      </div>

      <fieldset id="fsM3U"><legend>M3U options</legend>
        <div class="field checkbox"><input type="checkbox" name="static_urls" id="staticurl"><label for="staticurl">Use static URLs</label></div>
        <div class="field">
          <label>Refresh interval (hours, -1=off, 0=on)</label>
          <input type="number" name="refresh_interval" value="1">
        </div>
        <div class="field">
          <label>Filter (search criteria)</label>
          <input type="text" name="search_criteria" value='tvg-id="{SID}"'>
        </div>
      </fieldset>

      <fieldset id="fsUserPass"><legend>Authentication</legend>
        <div class="row">
          <div class="field"><label>Username</label><input type="text" name="username"></div>
          <div class="field"><label>Password</label><input type="password" name="password"></div>
        </div>
      </fieldset>

      <fieldset id="fsStalker"><legend>Stalker portal</legend>
        <div class="field"><label>MAC address</label><input type="text" name="mac" placeholder="00:1A:79:XX:XX:XX"></div>
        <div class="row">
          <div class="field"><label>Serial (optional)</label><input type="text" name="custom_serial"></div>
          <div class="field"><label>Device ID 1 (optional)</label><input type="text" name="custom_device_id1"></div>
        </div>
        <div class="row">
          <div class="field"><label>Device ID 2 (optional)</label><input type="text" name="custom_device_id2"></div>
          <div class="field"><label>Signature (optional)</label><input type="text" name="custom_signature"></div>
        </div>
      </fieldset>

      <div class="field checkbox" id="fNoVodWrap"><input type="checkbox" name="ignore_vod" id="novod"><label for="novod">Skip VOD entries</label></div>

      <fieldset id="fsEpg"><legend>EPG</legend>
        <div class="field checkbox"><input type="checkbox" name="create_epg" id="createepg" checked><label for="createepg">Generate EPG files for EPGImport plugin</label></div>
        <div class="field checkbox"><input type="checkbox" name="is_custom_xmltv" id="customxmltv"><label for="customxmltv">Use custom XMLTV URL</label></div>
        <div class="field"><label>Custom XMLTV URL</label><input type="text" name="custom_xmltv_url"></div>
      </fieldset>

      <fieldset id="fsPlayback"><legend>Playback</legend>
        <div class="row">
          <div class="field">
            <label>Playback system</label>
            <select name="play_system">
              <option value="4097">GStreamer / HiSilicon</option>
              <option value="1">DVB</option>
              <option value="5002">Exteplayer3</option>
            </select>
          </div>
          <div class="field">
            <label>Catchup playback system</label>
            <select name="play_system_catchup">
              <option value="4097">GStreamer / HiSilicon</option>
              <option value="1">DVB</option>
              <option value="5002">Exteplayer3</option>
            </select>
          </div>
        </div>
        <div class="row">
          <div class="field" id="fOutputFormatWrap">
            <label>Stream output format</label>
            <select name="output_format">
              <option value="ts">Transport stream (TS)</option>
              <option value="m3u8">HLS (M3U8)</option>
            </select>
          </div>
          <div class="field" id="fCatchupTypeWrap">
            <label>Catchup type</label>
            <select name="catchup_type">
              <option value="1">Standard</option>
              <option value="2">Append</option>
              <option value="3">Shift</option>
              <option value="4">Xtreme Codes</option>
              <option value="8">Xtreme Codes 60</option>
              <option value="5">Stalker</option>
              <option value="6">Flussonic</option>
              <option value="7">VoD</option>
            </select>
          </div>
        </div>
      </fieldset>

      <fieldset id="fsVod"><legend>Video on Demand</legend>
        <div class="field">
          <label>VOD playlist format</label>
          <select name="playlist_type">
            <option value="m3u">M3U/M3U8</option>
            <option value="txt">TXT</option>
          </select>
        </div>
      </fieldset>

      <fieldset><legend>Picons &amp; bouquets</legend>
        <div class="field checkbox"><input type="checkbox" name="picons" id="picons"><label for="picons">Download picons</label></div>
        <div class="field">
          <label>Bouquet creation strategy</label>
          <select name="create_bouquets_strategy">
            <option value="0">Only bouquets for groups</option>
            <option value="1">Only bouquet for 'All Channels'</option>
            <option value="2">Bouquets for 'All Channels' and groups</option>
            <option value="3">Bouquet for provider and sub-bouquets for groups</option>
          </select>
        </div>
        <div class="field">
          <label>Channel ordering criteria</label>
          <select name="ch_order_strategy">
            <option value="0">Use provider order</option>
            <option value="1">By channel number</option>
            <option value="2">Alphabetically</option>
          </select>
        </div>
      </fieldset>

      <div class="field checkbox"><input type="checkbox" name="auto_updates" id="autoupdates"><label for="autoupdates">Include in scheduled auto updates</label></div>

      <div class="modal-actions">
        <button type="button" class="btn-secondary" id="btnCancel">Cancel</button>
        <button type="submit" class="btn-primary" id="btnSave">Save</button>
      </div>
    </form>
  </div>
</div>

<script>
var API = "api/providers";
var editingScheme = null;

function qs(sel, root) { return (root || document).querySelector(sel); }
function qsa(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

function fmtBool(v) { return v ? "yes" : "no"; }

function loadProviders() {
  fetch(API).then(function(r) { return r.json(); }).then(function(list) {
    var tbody = qs("#tbody");
    tbody.innerHTML = "";
    qs("#count").textContent = list.length + (list.length === 1 ? " provider" : " providers");
    if (!list.length) {
      tbody.innerHTML = '<tr><td colspan="5" class="empty">No playlists yet. Click "Add provider" to create one.</td></tr>';
      return;
    }
    list.forEach(function(p) {
      var tr = document.createElement("tr");
      tr.innerHTML =
        "<td>" + escapeHtml(p.iptv_service_provider) + "</td>" +
        '<td><span class="type-badge">' + escapeHtml(p.type) + "</span></td>" +
        "<td style='max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'>" + escapeHtml(p.url) + "</td>" +
        "<td>" + escapeHtml(p.scheme) + "</td>" +
        '<td class="actions"></td>';
      var actionsTd = tr.querySelector(".actions");
      var editBtn = document.createElement("button");
      editBtn.className = "btn-secondary";
      editBtn.textContent = "Edit";
      editBtn.onclick = function() { openEdit(p); };
      var delBtn = document.createElement("button");
      delBtn.className = "btn-danger";
      delBtn.textContent = "Delete";
      delBtn.onclick = function() { deleteProvider(p); };
      actionsTd.appendChild(editBtn);
      actionsTd.appendChild(delBtn);
      tbody.appendChild(tr);
    });
  });
}

function escapeHtml(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, function(c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
  });
}

function setFormValues(data) {
  var form = qs("#providerForm");
  qsa("input, select", form).forEach(function(el) {
    var name = el.name;
    if (!name || name === "scheme") return;
    if (el.type === "checkbox") {
      el.checked = !!data[name];
    } else if (data[name] !== undefined && data[name] !== null) {
      el.value = data[name];
    } else {
      el.value = el.tagName === "SELECT" ? el.value : "";
    }
  });
}

function updateVisibility() {
  var type = qs("#fType").value;
  qs("#fsM3U").style.display = type === "M3U" ? "" : "none";
  qs("#fsUserPass").style.display = (type === "Xtreeme" || type === "TVH") ? "" : "none";
  qs("#fsStalker").style.display = type === "Stalker" ? "" : "none";
  qs("#fNoVodWrap").style.display = (type === "Xtreeme" || type === "Stalker") ? "" : "none";
  qs("#fsEpg").style.display = type !== "VOD" ? "" : "none";
  qs("#fsPlayback").style.display = type !== "VOD" ? "" : "none";
  qs("#fOutputFormatWrap").style.display = (type === "Xtreeme" || type === "Stalker") ? "" : "none";
  qs("#fCatchupTypeWrap").style.display = (type === "Xtreeme" || type === "M3U") ? "" : "none";
  qs("#fsVod").style.display = type === "VOD" ? "" : "none";
  qs("#fSchemeWrap input").disabled = !!editingScheme;
  qs("#fType").disabled = !!editingScheme;
}

function openAdd() {
  editingScheme = null;
  qs("#modalTitle").textContent = "Add provider";
  qs("#providerForm").reset();
  setFormValues({});
  qs("#fSchemeWrap input").value = "";
  qs("#fSchemeWrap input").placeholder = "";
  hideError();
  updateVisibility();
  qs("#backdrop").classList.add("open");
}

function openEdit(p) {
  editingScheme = p.scheme;
  qs("#modalTitle").textContent = "Edit provider: " + p.iptv_service_provider;
  qs("#fType").value = p.type;
  setFormValues(p);
  qs("#fSchemeWrap input").value = "";
  qs("#fSchemeWrap input").placeholder = p.scheme;
  hideError();
  updateVisibility();
  qs("#backdrop").classList.add("open");
}

function closeModal() {
  qs("#backdrop").classList.remove("open");
}

function showError(msg) {
  var el = qs("#formError");
  el.textContent = msg;
  el.style.display = "";
}
function hideError() {
  qs("#formError").style.display = "none";
}

function collectFormData() {
  var form = qs("#providerForm");
  var data = {};
  qsa("input, select", form).forEach(function(el) {
    if (!el.name) return;
    if (el.type === "checkbox") {
      data[el.name] = el.checked;
    } else if (el.type === "number") {
      data[el.name] = el.value === "" ? 0 : Number(el.value);
    } else {
      data[el.name] = el.value;
    }
  });
  if (data.catchup_type !== undefined) data.catchup_type = Number(data.catchup_type);
  return data;
}

function deleteProvider(p) {
  if (!confirm('Permanently remove provider "' + p.iptv_service_provider + '"?')) return;
  fetch(API + "/" + encodeURIComponent(p.scheme), { method: "DELETE" }).then(function(r) {
    if (r.ok) loadProviders();
    else r.json().then(function(j) { alert(j.error || "Delete failed"); });
  });
}

qs("#btnAdd").onclick = openAdd;
qs("#btnCancel").onclick = closeModal;
qs("#fType").onchange = updateVisibility;

qs("#providerForm").onsubmit = function(ev) {
  ev.preventDefault();
  hideError();
  var data = collectFormData();
  var url = editingScheme ? API + "/" + encodeURIComponent(editingScheme) : API;
  var method = editingScheme ? "PUT" : "POST";
  fetch(url, { method: method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) })
    .then(function(r) { return r.json().then(function(j) { return { ok: r.ok, body: j }; }); })
    .then(function(res) {
      if (!res.ok) { showError(res.body.error || "Save failed"); return; }
      closeModal();
      loadProviders();
    })
    .catch(function(err) { showError(String(err)); });
};

loadProviders();
</script>
</body>
</html>
"""
