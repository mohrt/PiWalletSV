#!/usr/bin/env bash
# Stop piwallet-bonnet so libcamera/Picamera2 can open the sensor exclusively.
# Source from factory-smoke or diag scripts; pair prepare + restore (or trap EXIT).
#
#   source deploy/scripts/camera-exclusive-access.sh
#   prepare_camera_exclusive_access
#   # ... run camera tests as pwsv ...
#   restore_camera_exclusive_access

CAMERA_BONNET_WAS_ACTIVE=0

prepare_camera_exclusive_access() {
    CAMERA_BONNET_WAS_ACTIVE=0
    if systemctl is-active -q piwallet-bonnet.service 2>/dev/null; then
        CAMERA_BONNET_WAS_ACTIVE=1
        systemctl stop piwallet-bonnet.service
    fi
    # Pi Zero W libcamera needs time to release the sensor after bonnet stops.
    sleep 2
}

restore_camera_exclusive_access() {
    if [[ "${CAMERA_BONNET_WAS_ACTIVE:-0}" -eq 1 ]]; then
        systemctl start piwallet-bonnet.service 2>/dev/null || true
    fi
}
