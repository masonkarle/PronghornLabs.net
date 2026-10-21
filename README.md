# Pronghorn Labs downloads

Direct Mac downloads of [Pronghorn Labs](https://pronghornlabs.net) apps, outside the Mac App Store and TestFlight. Each download is a signed, notarized `.dmg`.

| App | What it does |
|---|---|
| [Fireweed](fireweed/) | A web browser where every link opens in the right place |
| [Pika](pika/) | Quick video clips for signing |
| [Switchback](switchback/) | Scripture citations stamped onto the ASL note-taking worksheet |
| [Aspen](aspen/) | Log your interpreting jobs, bill each client by its own rules, and get paid |
| [Kestrel](kestrel/) | A stage timer for speakers |
| [Talus](talus/) | Meetings, minutes and follow-ups for the body of elders |

All downloads are on the [Releases](https://github.com/masonkarle/PronghornLabs.net/releases) page. Questions or ideas: hello@pronghornlabs.net.

## Making a release

`Tools/release.sh <app> [--publish]` builds the app's `main` as a Developer ID–signed, notarized DMG and adds it here as a release tagged `<app>-v<version>-<build>` (a draft unless `--publish`). It prints the line to put in the site's `public/_redirects`, so pronghornlabs.net/download/&lt;app&gt; serves the new DMG; then build and deploy the site.

On the Mac mini, run it with `ASC_KEY_ID=BZ448G9XQ3`. The Mac needs the "Developer ID Application: Prairie Fire, LLC" certificate in its keychain. Apps that use iCloud also need Developer ID provisioning profiles: `Tools/profiles.py <bundle id>…` makes and installs them, once per app and again after a new certificate. A new app goes in the list at the top of `release.sh`.
