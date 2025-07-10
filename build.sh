#!/bin/sh

cd meta
version=$(grep Version control|cut -d " " -f 2)
package=$(grep Package control|cut -d " " -f 2)
mkdir -p usr/lib/enigma2/python/Plugins/SystemPlugins/M3UIPTV
cp -r ../src/. ./usr/lib/enigma2/python/Plugins/SystemPlugins/M3UIPTV
tar -cvzf data.tar.gz usr
tar -cvzf control.tar.gz control

rm -f ../${package}_${version}_all.ipk
ar -r ../${package}_${version}_all.ipk debian-binary control.tar.gz data.tar.gz

rm -fr control.tar.gz data.tar.gz usr
