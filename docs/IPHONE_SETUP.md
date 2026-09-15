# Install Touchline on your iPhone

Touchline is a native **dark-mode SwiftUI app** for the independent, automatic paper-betting engine. It uses virtual money only. You do not need to enter or approve individual simulated bets.

Dark-mode screens: [connection](mobile-images/dark-connection.png) · [initial portfolio](mobile-images/dark-overview.png).

## Install from this Mac

1. Open `ios/Touchline.xcodeproj` in Xcode. Use the **Touchline** scheme.
2. Connect your unlocked iPhone to this Mac with a USB cable. Tap **Trust This Computer** on the phone if prompted.
3. In Xcode, open **Settings → Accounts** and sign in with your Apple Account if it is not already listed.
4. Select the blue **Touchline** project in the left sidebar, then the **Touchline** app target. Open **Signing & Capabilities**, leave **Automatically manage signing** checked, and choose your **Personal Team** (or paid developer team).
5. The default bundle identifier is `com.hughnolan.touchline`. If Xcode says it is unavailable, change it to a unique value such as `com.yourname.touchline.personal`.
6. Select your physical iPhone as the run destination in Xcode's top toolbar. The app requires **iOS 17 or later**. If Xcode asks to download device support, let it finish.
7. On your iPhone, enable **Settings → Privacy & Security → Developer Mode** if requested. Restart the phone and confirm the prompt.
8. Press **⌘R** in Xcode. It builds, signs, installs, and opens Touchline on your phone.
9. If the phone shows an untrusted-developer message, open **Settings → General → VPN & Device Management**, select your developer profile, and trust it. Then open Touchline again.

Apple's free Personal Team provisioning expires after **seven days**. Connect the phone and press **⌘R** again to renew it. The server continues collecting and simulating while the phone app is unavailable. Paid developer membership changes signing/distribution options; no membership purchase or TestFlight setup is needed for this personal installation. [Apple's account and provisioning guidance](https://developer.apple.com/help/account/basics/about-your-developer-account).

## Connect the app once

The mobile backend address is prefilled:

**https://api-production-f10dd.up.railway.app**

From Terminal in this project directory, run:

```bash
python3 scripts/copy-mobile-token.py
```

This reads the private **owner token** from the Railway `api` service and copies it to your Mac clipboard without displaying or storing it locally. It requires the official Railway CLI and an authenticated `railway login`. Paste it into Touchline's **Owner token** field using Universal Clipboard, if enabled on your Mac and iPhone. Do not paste the database password or provider key into the app.

Tap **Connect securely**. The connection is stored in iPhone Keychain. The token is never compiled into the app.

## What you will see

- **Overview:** virtual bankroll, available funds, reserved stakes, latest activity, and engine status.
- **Simulations:** automatic entries, filtered by open or settled, with the recorded probability, price, stake, and result.
- **Performance:** the equity curve, virtual profit, return on stake, win rate, and drawdown.
- **Engine:** pause/resume new entries, edit rules, manage the data budget, and inspect jobs and skipped-entry reasons.

The server operates every five minutes. The phone refreshes when opened and while visible. When Touchline sees a newly recorded automatic paper bet during refresh, it asks iOS to send a local notification. Pausing entries still allows result collection and settlement. Turning off provider requests under Data & budget stops paid odds/results requests; public result collection still operates. Remote push delivery is not configured in this version.

A new portfolio starts with **£1,000 in virtual funds**. Historical archives and models are prepared automatically, so initial training may take several scheduled runs. An empty ledger is expected until a trained model and a fresh, eligible price are available. No example bets are inserted.

The app enforces a **100-credit daily ceiling** and **10-credit reserve**. Any other clients using the same Odds API subscription share the provider-level quota.

## Troubleshooting

- **Access token rejected:** recopy the current owner token. If it was rotated on the backend, disconnect and reconnect the phone.
- **Showing saved data:** check connectivity and pull to refresh. The visible timestamp tells you how old the cached data is.
- **Starting / no trained leagues:** check Engine jobs. Bootstrap downloads and training are automatic; a source outage may delay them.
- **Database unavailable:** the backend will retry automatically, check Railway database health, available disk space, and account allowance. See [reliability findings](RELIABILITY.md).
- **Overdue:** no successful tick has completed in 15 minutes. Check the Railway engine service logs.
- **Budget reached:** provider calls resume when allowed by the next UTC day or available subscription quota. Increasing the local ceiling does not purchase provider credits.
- **App stops opening after a week:** rebuild/reinstall from Xcode to renew free signing.

No physical iPhone was connected during implementation; signing and installation on your own device must be completed using the steps above.
