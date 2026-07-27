#!/usr/bin/python
# -*- coding: utf-8 -*-
import gettext
from os import path

from Components.Harddisk import harddiskmanager
from Components.Language import language
from Tools.Directories import resolveFilename, SCOPE_PLUGINS


def getMountChoices():
	choices = []
	for p in harddiskmanager.getMountedPartitions():
		if path.exists(p.mountpoint):
			d = path.join(path.normpath(p.mountpoint), "picon")
			if d.startswith(("/media/net", "/media/autofs")):
				continue
			entry = (d, d)
			if entry not in choices:
				choices.append(entry)
	choices.sort(key=lambda x: (not x[0].startswith("/picon"), x[0]))  # /picon at index(0) if present
	return choices


def getMountDefault(choices):
	try:
		from Components.Renderer.Picon import lastPiconPath, searchPaths
	except ImportError:
		try:
			from Components.Renderer.Picon import piconLocator
			lastPiconPath = piconLocator.activePiconPath
			searchPaths = piconLocator.searchPaths
		except ImportError:
			lastPiconPath = None
			searchPaths = None
	if lastPiconPath is None and searchPaths and len(searchPaths) == 1:
		lastPiconPath = searchPaths[0]
	if lastPiconPath:
		lastPiconPath = path.normpath(lastPiconPath)
	choices = {x[1]: x[0] for x in choices}
	default = lastPiconPath or choices.get("/picon")
	return default


PluginLanguageDomain = "m3uiptv"
PluginLanguagePath = "SystemPlugins/M3UIPTV/locale"


def pluginlanguagedomain():
	return PluginLanguageDomain


def localeInit():
	gettext.bindtextdomain(PluginLanguageDomain, resolveFilename(SCOPE_PLUGINS, PluginLanguagePath))


def _(txt):
	if translated := gettext.dgettext(PluginLanguageDomain, txt):
		return translated
	else:
		print("[" + PluginLanguageDomain + "] fallback to default translation for " + txt)
		return gettext.gettext(txt)


localeInit()
language.addCallback(localeInit)
