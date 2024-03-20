DESCRIPTION = "IPTV m3u lists reader and runner"
MAINTAINER = "DimitarCC"
LICENSE = "GPLv3"
LIC_FILES_CHKSUM = "file://LICENSE;md5=1ebbd3e34237af26da5dc08a4e440464"

inherit gitpkgv allarch ${PYTHON_PN}native

PV = "1.0+git${SRCPV}"
PKGV = "1.0+git${GITPKGV}"

SRCREV = "${AUTOREV}"

SRC_URI = "git://github.com/DimitarCC/iptv-m3u-reader.git;protocol=https;branch=main"

S = "${WORKDIR}/git"

do_install() {
	install -d ${D}${prefix}
	cp -r ${S}${prefix}/* ${D}${prefix}/
	python3 -m compileall -o2 -b ${D}
}

FILES:${PN} = "${prefix}/"
FILES:${PN}-src = "${prefix}/lib/enigma2/python/Components/Converter/*.py ${prefix}/lib/enigma2/python/Components/Renderer/*.py"