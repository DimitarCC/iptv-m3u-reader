from distutils import cmd
from distutils.command.build import build as _build
import os


class build_trans(cmd.Command):
	description = 'Compile .po files into .mo files'

	def initialize_options(self):
		pass

	def finalize_options(self):
		pass

	def run(self):
		tool = "/usr/bin/msgfmt"
		repo_root = os.path.dirname(os.path.abspath(__file__))
		src_folder = os.path.join(repo_root, "src")
		po_folder = os.path.join(repo_root, "po")
		PluginLanguageDomain = "m3uiptv"  # same as in __init__.py
		for lang in [f[:-3] for f in os.listdir(po_folder) if f.endswith(".po")]:
			os.makedirs((destdir := os.path.join(src_folder, 'locale', lang, 'LC_MESSAGES')), exist_ok=True)
			command = "%s '%s' -o '%s'" % (tool, os.path.join(po_folder, "%s.po" % lang), os.path.join(destdir, "%s.mo" % PluginLanguageDomain))
			if os.system(command) != 0:
				raise Exception("Failed to compile: " + command)


class build(_build):
	sub_commands = _build.sub_commands + [('build_trans', None)]

	def run(self):
		_build.run(self)


cmdclass = {
	'build': build,
	'build_trans': build_trans,
}