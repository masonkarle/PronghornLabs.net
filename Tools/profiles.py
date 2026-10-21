#!/usr/bin/env python3
"""Creates and installs a Developer ID (MAC_APP_DIRECT) provisioning profile for each
bundle id, tied to this Mac's Developer ID Application certificate, and named
"<bundle id> Developer ID" as Tools/release.sh expects. Replaces one of the same name.

    Tools/profiles.py net.pronghornlabs.aspen net.pronghornlabs.fireweed.share
    ASC_KEY_ID=BZ448G9XQ3 Tools/profiles.py …     # on the Mac mini

Needed once per app (and its extensions) that uses iCloud or another capability a
profile must grant, and again after a new Developer ID certificate. Apps without such
capabilities sign without a profile.
"""
import base64
import pathlib
import subprocess
import sys
import urllib.parse

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import asc  # noqa: E402

pem = subprocess.run(["security", "find-certificate", "-c", "Developer ID Application: Prairie Fire", "-p"],
                     capture_output=True, text=True, check=True).stdout
serial = subprocess.run(["openssl", "x509", "-noout", "-serial"], input=pem,
                        capture_output=True, text=True, check=True).stdout.split("=")[1].strip()
certs = asc.get_all("/certificates?filter[certificateType]=DEVELOPER_ID_APPLICATION_G2,DEVELOPER_ID_APPLICATION&limit=200")
cert = next(c for c in certs if c["attributes"]["serialNumber"].upper().lstrip("0") == serial.upper().lstrip("0"))

dirs = [pathlib.Path.home() / "Library/MobileDevice/Provisioning Profiles",
        pathlib.Path.home() / "Library/Developer/Xcode/UserData/Provisioning Profiles"]
for identifier in sys.argv[1:]:
    bundle = next(b for b in asc.get_all(f"/bundleIds?filter[identifier]={identifier}&limit=50")
                  if b["attributes"]["identifier"] == identifier)
    name = f"{identifier} Developer ID"
    for old in asc.get_all(f"/profiles?filter[name]={urllib.parse.quote(name)}&limit=50"):
        asc.request("DELETE", f"/profiles/{old['id']}")
    profile = asc.request("POST", "/profiles", {"data": {
        "type": "profiles",
        "attributes": {"name": name, "profileType": "MAC_APP_DIRECT"},
        "relationships": {
            "bundleId": {"data": {"type": "bundleIds", "id": bundle["id"]}},
            "certificates": {"data": [{"type": "certificates", "id": cert["id"]}]},
        }}})["data"]
    content = base64.b64decode(profile["attributes"]["profileContent"])
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{profile['attributes']['uuid']}.provisionprofile").write_bytes(content)
    print(f"installed {name}")
