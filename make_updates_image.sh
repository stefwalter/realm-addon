#!/bin/bash

if [ $# -ne 1 ]; then
    echo "Path to the realmd RPM expected. Exiting."
    exit 1
fi

realmd_rpm_path="$1"

if [ `basename "$realmd_rpm_path"` = "$realmd_rpm_path" ]; then
    realmd_rpm_path="$PWD/$realmd_rpm_path"
fi

mkdir -p updates_image/usr/share/anaconda/addons/
cp -r org_fedora_realm updates_image/usr/share/anaconda/addons/
pushd updates_image
rpm2cpio "$realmd_rpm_path" | cpio -dium
find . | cpio -c -o | gzip -9cv > ../addon_updates.img
popd
rm -rf updates_image
