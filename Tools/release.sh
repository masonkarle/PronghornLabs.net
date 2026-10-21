#!/usr/bin/env bash
# Builds one app's main branch as a Developer ID–signed, notarized, stapled DMG and
# adds it to this repo's Releases as a draft (or published, with --publish).
#
#     Tools/release.sh pika                  # build, notarize, draft release
#     Tools/release.sh fireweed --publish    # same, and publish it
#     ASC_KEY_ID=BZ448G9XQ3 Tools/release.sh aspen    # on the Mac mini
#
# Needs, on this Mac: the "Developer ID Application: Prairie Fire, LLC" certificate
# with its private key (Xcode → Settings → Accounts → Manage Certificates, Account
# Holder only), the App Store Connect key in ~/.appstoreconnect/private_keys/, and
# for apps listed with profiles below, those profiles (Tools/profiles.py makes them).
# The API key can't use cloud-managed Developer ID certificates, so signing is local.
#
# Afterwards, point pronghornlabs.net/download/<app> at the new DMG: the line this
# prints goes in PronghornLabs/public/_redirects, then build and deploy the site.
set -euo pipefail

APP_SLUG="${1:?usage: $0 <fireweed|pika|switchback|aspen|kestrel|talus> [--publish]}"
PUBLISH=0; [ "${2:-}" = --publish ] && PUBLISH=1

# slug → GitHub repo, Mac scheme, and the Developer ID profiles of apps that use iCloud
# and other capabilities a profile must grant ("bundle.id=profile name;…").
case "$APP_SLUG" in
    fireweed)   REPO=Fireweed   SCHEME=Fireweed   PROFILES="net.pronghornlabs.fireweed=net.pronghornlabs.fireweed Developer ID;net.pronghornlabs.fireweed.share=net.pronghornlabs.fireweed.share Developer ID" ;;
    pika)       REPO=Pika       SCHEME=PikaMac    PROFILES="" ;;
    switchback) REPO=Switchback SCHEME=Switchback PROFILES="" ;;
    aspen)      REPO=Aspen      SCHEME=Aspen      PROFILES="net.pronghornlabs.aspen=net.pronghornlabs.aspen Developer ID" ;;
    kestrel)    REPO=Kestrel    SCHEME=Kestrel    PROFILES="net.pronghornlabs.kestrel=net.pronghornlabs.kestrel Developer ID" ;;
    talus)      REPO=Talus      SCHEME=Talus      PROFILES="net.pronghornlabs.talus=net.pronghornlabs.talus Developer ID" ;;
    *) echo "unknown app: $APP_SLUG" >&2; exit 2 ;;
esac

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}"
ASC_KEY_ID="${ASC_KEY_ID:-RDX9DNYR8T}"
ASC_ISSUER_ID="${ASC_ISSUER_ID:-e3711453-f981-418d-b645-118b00287b37}"
ASC_KEY_PATH="${ASC_KEY_PATH:-$HOME/.appstoreconnect/private_keys/AuthKey_$ASC_KEY_ID.p8}"
[ -r "$ASC_KEY_PATH" ] || { echo "no App Store Connect key at $ASC_KEY_PATH" >&2; exit 2; }
AUTH=(-authenticationKeyPath "$ASC_KEY_PATH" -authenticationKeyID "$ASC_KEY_ID" -authenticationKeyIssuerID "$ASC_ISSUER_ID")
NOTARY=(--key "$ASC_KEY_PATH" --key-id "$ASC_KEY_ID" --issuer "$ASC_ISSUER_ID" --wait)
IDENTITY="Developer ID Application: Prairie Fire, LLC (U6947SF6NY)"

WORK="$ROOT/build/$REPO"
rm -rf "$WORK"; mkdir -p "$WORK/src" "$ROOT/build/out"

echo "==> $REPO: fetching main"
gh api "repos/masonkarle/$REPO/tarball/main" > "$WORK/src.tar.gz"
tar -xzf "$WORK/src.tar.gz" -C "$WORK/src" --strip-components 1
cd "$WORK/src"
if [ -f project.yml ]; then xcodegen generate --quiet; fi

# Notarization requires the hardened runtime; not every project turns it on.
echo "==> $REPO: archiving"
xcodebuild -project "$REPO.xcodeproj" -scheme "$SCHEME" -configuration Release \
    -destination 'generic/platform=macOS' -archivePath "$WORK/app.xcarchive" \
    -allowProvisioningUpdates "${AUTH[@]}" ENABLE_HARDENED_RUNTIME=YES archive -quiet

SIGNING="<key>signingStyle</key><string>automatic</string>"
if [ -n "$PROFILES" ]; then
    SIGNING="<key>signingStyle</key><string>manual</string>
	<key>signingCertificate</key><string>Developer ID Application</string>
	<key>provisioningProfiles</key><dict>"
    IFS=';' read -ra pairs <<< "$PROFILES"
    for pair in "${pairs[@]}"; do
        SIGNING+="<key>${pair%%=*}</key><string>${pair#*=}</string>"
    done
    SIGNING+="</dict>"
fi
cat > "$WORK/ExportOptions.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>method</key><string>developer-id</string>
	<key>teamID</key><string>U6947SF6NY</string>
	$SIGNING
</dict>
</plist>
PLIST

echo "==> $REPO: exporting with Developer ID"
xcodebuild -exportArchive -archivePath "$WORK/app.xcarchive" -exportPath "$WORK/export" \
    -exportOptionsPlist "$WORK/ExportOptions.plist" -allowProvisioningUpdates "${AUTH[@]}"

APP="$(ls -d "$WORK"/export/*.app | head -1)"
NAME="$(basename "$APP" .app)"
VERSION="$(plutil -extract CFBundleShortVersionString raw "$APP/Contents/Info.plist")"
BUILD="$(plutil -extract CFBundleVersion raw "$APP/Contents/Info.plist")"
MACOS="$(plutil -extract LSMinimumSystemVersion raw "$APP/Contents/Info.plist")"
MACOS="${MACOS%.0}"

# notarytool exits 0 even when Apple rejects the upload; the staple fails instead.
# Read why with: xcrun notarytool log <submission id> --key … --key-id … --issuer …
echo "==> $REPO: notarizing $NAME $VERSION ($BUILD)"
ditto -c -k --keepParent "$APP" "$WORK/notarize.zip"
xcrun notarytool submit "$WORK/notarize.zip" "${NOTARY[@]}"
xcrun stapler staple "$APP"

echo "==> $REPO: making the DMG"
mkdir -p "$WORK/dmg"
cp -R "$APP" "$WORK/dmg/"
ln -s /Applications "$WORK/dmg/Applications"
FILE="$NAME-$VERSION-$BUILD.dmg"
DMG="$ROOT/build/out/$FILE"
rm -f "$DMG"
hdiutil create -volname "$NAME" -srcfolder "$WORK/dmg" -fs HFS+ -format UDZO -ov "$DMG" -quiet
codesign --sign "$IDENTITY" --timestamp "$DMG"

echo "==> $REPO: notarizing the DMG"
xcrun notarytool submit "$DMG" "${NOTARY[@]}"
xcrun stapler staple "$DMG"
spctl -a -vv -t exec "$APP"
spctl -a -vv -t open --context context:primary-signature "$DMG"

TAG="$APP_SLUG-v$VERSION-$BUILD"
GH_REPO=masonkarle/PronghornLabs.net
echo "==> $REPO: release $TAG"
gh release create "$TAG" "$DMG" -R "$GH_REPO" --draft --target main --title "$NAME $VERSION ($BUILD)" --notes "$NAME for Mac, version $VERSION (build $BUILD). Requires macOS $MACOS or later.

Download **$FILE** below, open it and drag $NAME to Applications. Signed with Developer ID and notarized by Apple.

About $NAME: https://github.com/$GH_REPO/tree/main/$APP_SLUG"
# Not "Latest": that label is repo-wide, and each app's link points at its own release.
if [ "$PUBLISH" = 1 ]; then gh release edit "$TAG" -R "$GH_REPO" --draft=false --latest=false; fi

echo
echo "pronghornlabs.net redirect (PronghornLabs/public/_redirects):"
printf '/download/%-9s https://github.com/%s/releases/download/%s/%s  302\n' "$APP_SLUG" "$GH_REPO" "$TAG" "$FILE"
