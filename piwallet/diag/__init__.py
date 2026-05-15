"""Diagnostic checks the operator can run on the device.

Today this houses the airgap checker (radio modules, rfkill, services,
boot config, modprobe blacklists, network interfaces). Future
diagnostics — display panel parity, GPIO read-back, vault integrity —
will land in their own modules under this package.
"""
