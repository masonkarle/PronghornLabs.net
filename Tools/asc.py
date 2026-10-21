#!/usr/bin/env python3
"""A small App Store Connect API client, for the listing.

    Tools/asc.py apps                          # the team's apps
    Tools/asc.py versions <app-id>             # every version, its platform and state
    Tools/asc.py screenshots <version-id>      # the sets and what is in them, per localization
    Tools/asc.py upload <version-id> <display-type> <png>...   # replace one set with these files
    Tools/asc.py bundle <identifier>           # the registered bundle id, if any
    Tools/asc.py register <identifier> <name>  # register a universal (iOS + macOS) bundle id
    Tools/asc.py builds <app-id>               # recent builds and their processing state
    Tools/asc.py get <path>                    # any GET, printed as JSON
    Tools/asc.py patch <path> <json>           # any PATCH with a JSON body
    Tools/asc.py post <path> <json>            # any POST with a JSON body

Copied from Magpie (and Cephas before it). Authenticates with the same App Store Connect API key
`Tools/testflight-export.sh` uploads with: `AuthKey_<id>.p8` in
`~/.appstoreconnect/private_keys/`, with the key id and issuer id below or
in `ASC_KEY_ID` / `ASC_ISSUER_ID`. There is no PyJWT on this machine and
the script should not need one: the ES256 token is signed with `openssl`
and the DER signature it gives is turned into the raw r||s the token wants.

Display types Apple names the screenshot slots by, the ones this app uses:
APP_IPHONE_67 (the 6.9-inch iPhone), APP_IPAD_PRO_3GEN_129 (the 13-inch
iPad), APP_DESKTOP (the Mac).
"""
import base64
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

KEY_ID = os.environ.get("ASC_KEY_ID", "RDX9DNYR8T")
ISSUER_ID = os.environ.get("ASC_ISSUER_ID", "e3711453-f981-418d-b645-118b00287b37")
KEY_PATH = os.environ.get("ASC_KEY_PATH", os.path.expanduser(f"~/.appstoreconnect/private_keys/AuthKey_{KEY_ID}.p8"))
API = "https://api.appstoreconnect.apple.com/v1"


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def der_to_raw(der: bytes) -> bytes:
    """An ECDSA signature as DER (SEQUENCE of two INTEGERs) to r||s, 32 bytes each."""
    assert der[0] == 0x30
    i = 2 if der[1] < 0x80 else 2 + (der[1] & 0x7F)
    out = b""
    for _ in range(2):
        assert der[i] == 0x02
        length = der[i + 1]
        value = der[i + 2:i + 2 + length].lstrip(b"\x00")
        out += value.rjust(32, b"\x00")
        i += 2 + length
    return out


_token = None


def token() -> str:
    global _token
    if _token and _token[1] > time.time() + 60:
        return _token[0]
    now = int(time.time())
    header = b64url(json.dumps({"alg": "ES256", "kid": KEY_ID, "typ": "JWT"}).encode())
    payload = b64url(json.dumps({"iss": ISSUER_ID, "iat": now, "exp": now + 1200, "aud": "appstoreconnect-v1"}).encode())
    signing_input = f"{header}.{payload}".encode()
    der = subprocess.run(["openssl", "dgst", "-sha256", "-sign", KEY_PATH], input=signing_input,
                         capture_output=True, check=True).stdout
    _token = (f"{header}.{payload}.{b64url(der_to_raw(der))}", now + 1200)
    return _token[0]


def request(method: str, path: str, body=None, raw: bytes = None, content_type: str = None):
    url = path if path.startswith("http") else API + path
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(url, data=data, method=method)
    if not raw:
        req.add_header("Authorization", f"Bearer {token()}")
    if content_type:
        req.add_header("Content-Type", content_type)
    elif data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as response:
            text = response.read()
            return json.loads(text) if text else None
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        raise SystemExit(f"{method} {path} → {error.code}\n{detail}")


def get_all(path: str):
    """Every page of a collection."""
    items = []
    url = path
    while url:
        page = request("GET", url)
        items += page.get("data", [])
        url = page.get("links", {}).get("next")
    return items


# MARK: - Commands

def cmd_apps():
    for app in get_all("/apps?limit=200"):
        a = app["attributes"]
        print(app["id"], a["bundleId"], "—", a["name"], f"(sku {a.get('sku')})")


def cmd_versions(app_id: str):
    for v in get_all(f"/apps/{app_id}/appStoreVersions?limit=200"):
        a = v["attributes"]
        print(v["id"], a["platform"], a["versionString"], a["appStoreState"], a.get("createdDate", "")[:10])


def cmd_screenshots(version_id: str):
    for loc in get_all(f"/appStoreVersions/{version_id}/appStoreVersionLocalizations"):
        print("localization", loc["id"], loc["attributes"]["locale"])
        for s in get_all(f"/appStoreVersionLocalizations/{loc['id']}/appScreenshotSets"):
            shots = get_all(f"/appScreenshotSets/{s['id']}/appScreenshots")
            print("  set", s["id"], s["attributes"]["screenshotDisplayType"], f"{len(shots)} screenshots")
            for shot in shots:
                a = shot["attributes"]
                print("     ", shot["id"], a.get("fileName"), a.get("assetDeliveryState", {}).get("state"))


def localization(version_id: str, locale: str = "en-US"):
    locs = get_all(f"/appStoreVersions/{version_id}/appStoreVersionLocalizations")
    for loc in locs:
        if loc["attributes"]["locale"] == locale:
            return loc
    raise SystemExit(f"no {locale} localization on {version_id}; have {[l['attributes']['locale'] for l in locs]}")


def cmd_upload(version_id: str, display_type: str, files):
    """Replaces the set for one display type with the given files, in order."""
    loc = localization(version_id)
    sets = get_all(f"/appStoreVersionLocalizations/{loc['id']}/appScreenshotSets")
    the_set = next((s for s in sets if s["attributes"]["screenshotDisplayType"] == display_type), None)
    if the_set is None:
        the_set = request("POST", "/appScreenshotSets", {"data": {
            "type": "appScreenshotSets",
            "attributes": {"screenshotDisplayType": display_type},
            "relationships": {"appStoreVersionLocalization": {"data": {"type": "appStoreVersionLocalizations", "id": loc["id"]}}},
        }})["data"]
        print("made set", the_set["id"], display_type)
    # Out with the old.
    for old in get_all(f"/appScreenshotSets/{the_set['id']}/appScreenshots"):
        request("DELETE", f"/appScreenshots/{old['id']}")
        print("  removed", old["attributes"].get("fileName"))
    # In with the new: reserve, upload the parts, commit with the checksum.
    ids = []
    for path in files:
        data = open(path, "rb").read()
        reservation = request("POST", "/appScreenshots", {"data": {
            "type": "appScreenshots",
            "attributes": {"fileName": os.path.basename(path), "fileSize": len(data)},
            "relationships": {"appScreenshotSet": {"data": {"type": "appScreenshotSets", "id": the_set["id"]}}},
        }})["data"]
        for op in reservation["attributes"]["uploadOperations"]:
            chunk = data[op["offset"]:op["offset"] + op["length"]]
            req = urllib.request.Request(op["url"], data=chunk, method=op["method"])
            for h in op["requestHeaders"]:
                req.add_header(h["name"], h["value"])
            with urllib.request.urlopen(req) as response:
                response.read()
        request("PATCH", f"/appScreenshots/{reservation['id']}", {"data": {
            "type": "appScreenshots", "id": reservation["id"],
            "attributes": {"uploaded": True, "sourceFileChecksum": hashlib.md5(data).hexdigest()},
        }})
        ids.append(reservation["id"])
        print("  uploaded", os.path.basename(path), f"{len(data)} bytes")
    # The order they were given in.
    request("PATCH", f"/appScreenshotSets/{the_set['id']}/relationships/appScreenshots",
            {"data": [{"type": "appScreenshots", "id": i} for i in ids]})
    print("set", the_set["id"], display_type, "→", len(ids), "screenshots")


def main(argv):
    if len(argv) < 2:
        raise SystemExit(__doc__)
    command, args = argv[1], argv[2:]
    if command == "apps":
        cmd_apps()
    elif command == "versions":
        cmd_versions(*args)
    elif command == "screenshots":
        cmd_screenshots(*args)
    elif command == "upload":
        cmd_upload(args[0], args[1], args[2:])
    elif command == "get":
        print(json.dumps(request("GET", args[0]), indent=2))
    elif command == "patch":
        print(json.dumps(request("PATCH", args[0], json.loads(args[1])), indent=2))
    elif command == "post":
        print(json.dumps(request("POST", args[0], json.loads(args[1])), indent=2))
    elif command == "bundle":
        found = get_all(f"/bundleIds?filter[identifier]={urllib.parse.quote(args[0])}")
        for b in found:
            if b["attributes"]["identifier"] == args[0]:
                a = b["attributes"]
                print(b["id"], a["identifier"], a["platform"], "—", a["name"])
                return
        print("not registered:", args[0])
    elif command == "register":
        made = request("POST", "/bundleIds", {"data": {"type": "bundleIds", "attributes": {
            "identifier": args[0], "name": args[1], "platform": "UNIVERSAL"}}})["data"]
        print("registered", made["id"], made["attributes"]["identifier"])
    elif command == "builds":
        for b in get_all(f"/builds?filter[app]={args[0]}&sort=-uploadedDate&limit=20")[:20]:
            a = b["attributes"]
            print(b["id"], a["version"], a["processingState"], a.get("uploadedDate", "")[:16])
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
