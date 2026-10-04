# Stride Coach mobile

An Expo SDK 57, TypeScript, and Expo Router app for iOS and Android. It connects to your own
Stride Coach FastAPI server. The server stores Garmin session tokens; Garmin passwords are never saved.
All native dependencies are Expo-compatible; no custom native code or ejecting is required.

## Local development

Install Node 22.13 or later (Node 22 LTS is used in CI), then run from this directory:

```sh
npm ci
npm start -- --go
```

Open the QR code in an **SDK 57-compatible Expo Go**. Android emulators and iOS simulators can
also be launched with `npm run android -- --go` or `npm run ios -- --go`. An iOS simulator
requires macOS and Xcode. The development client is optional; `--go` explicitly selects Expo Go.

Expo Go's store version can lag the stable SDK. Follow the [SDK 57 release notes](https://expo.dev/changelog/sdk-57)
and [Expo Go installation guide](https://docs.expo.dev/get-started/set-up-your-environment/)
for the compatible Android build, iOS simulator build, or `eas go` for an iOS device.
If the store build cannot open SDK 57, use the matching Expo Go build or the EAS development
profile below. SDK 58 is not used while it is on npm's prerelease channel.

## Connect your server

1. Start the server using the root [HTTP server guide](../README.md#json-api-for-a-phone-client).
   Keep the generated bearer token in the server environment. Pairing transfers it securely.
2. Put the server behind HTTPS with a trusted certificate. Point the phone at a URL such as
   `https://coach.example.com`, optionally with a reverse-proxy path prefix.
3. On a fresh install, the first-run wizard opens automatically. Use **Scan to connect** with
   a [pairing QR code](#pair-with-a-qr-code), check the server address, then **Connect to server**.
   Alternatively enter the URL and bearer token, tap **Test connection**, then **Save connection**.
   Manual saving is enabled only after an authenticated test passes. A server without a plan
   is a valid connection and proceeds to goal setup.
4. Choose **Connect Garmin** after entering your Garmin email and password, or **Skip Garmin
   for now**. The app sends credentials once over the authenticated connection and clears the
   password immediately. If requested, enter the MFA code Garmin sends. The challenge expires
   after five minutes. After a failed completion, use **Restart Garmin sign-in** for a new
   explicit login. After connecting, tap **Continue to import**. You can also connect later in **Settings**.
5. **Import past runs** offers 12 weeks, 6 calendar months, or everything. Wait for Complete,
   then **Continue to goal** so the imported runs inform the initial fitness estimate. **Skip import
   for now** continues using the history already stored on the server. Skipping Garmin bypasses import.
6. Choose your goal, Monday start, race or completion date, weekly running days, long-run day,
   and heart rates. **Review goal** shows the exact constraints before **Confirm new plan**
   creates it. Review any starting-fitness warnings, then tap **Go to Today**. If the server
   already has a plan, the wizard opens that plan instead of attempting to replace it.

### Pair with a QR code

Keep the server running. On its computer, [generate a pairing code](../docs/self-hosting.md#phone-pairing) with your HTTPS hostname.

The terminal shows a QR code and a plain-text code. Tap **Scan to connect** in the wizard or
**Settings > Manage connection**, allow camera access, and scan the terminal. Confirm that the
server URL belongs to you, then tap **Connect to server**. Pairing tests the connection and saves
it through the same device-only SecureStore path as manual entry. In Settings, this replaces
the previous connection and clears connected screen state and pending previews.

If camera access is denied or unavailable, close the scanner and choose **Enter pairing code**
to enter the URL and 24-character code. Manual URL and token fields also remain available.
Invalid, expired, and already-used codes show an error and do not change the saved connection.
For expired codes, lost responses, or rate limits, follow [pairing recovery](../docs/self-hosting.md#phone-pairing).
If secure storage fails after exchange, retry **Connect to server**
without leaving that screen; the token is retained only in memory for that retry.

An installed app also opens `stridecoach://pair?server=...&code=...` links scanned by the phone's
camera, whether the app is closed or running. The link still requires you to confirm the host.
Rebuild the native app after this change to register the `stridecoach` scheme and camera
permission. The existing `stride-coach` scheme remains supported for existing routes. Expo Go
can use the in-app scanner but cannot register this app's custom scheme. Camera scanning needs
a physical device; emulator workflows can use **Enter pairing code**.

Keep the QR and code private. See [pairing operations](../docs/self-hosting.md#phone-pairing) for credential handling and server limits.

The server supports one plan per database. For a later goal, the operator must configure a
fresh database; the app cannot replace the plan. If setup is interrupted after saving the
connection, the next launch opens the main app: **Set a running goal** in the empty-plan state
continues setup, and Garmin remains available in Settings. Wizard progress and Garmin
credentials are not persisted.

If plan creation fails or times out, the app reads server status to find an existing plan.
If that read succeeds, tap **Go to Today**.
If it fails, tap **Check plan status** to retry the read before submitting the goal again.

The **Import past runs** step uses `HistoryImport` through the `ImportPastRunsStep` slot in
`src/screens/onboarding.tsx`. The same controls in Settings show progress and offer **Resume import**
after a connection failure. Imports run on the server and resume after server restarts.
The app requests an activity sync on open or resume.
See [automatic sync behavior](../docs/self-hosting.md#automatic-sync-and-import-recovery) for intervals and disconnected accounts.

In **Settings**, **Manage connection** opens the server form. Test and save a changed URL or
bearer token there. **Forget connection** opens a confirmation showing what will be removed.
The onboarding and settings screens follow the phone’s light or dark appearance using
`src/theme/index.ts` and `src/components/ui.tsx`. Expo system UI enables appearance changes in
Android builds, as described in [Expo’s color theme guide](https://docs.expo.dev/develop/user-interface/color-themes/).

Before sending workouts, follow the [one-plan setup guide](../README.md#use-one-training-plan-on-your-watch) for Garmin controls, app reminders, and limitations.

**Refresh Garmin status** shows the connected account (when available) and access-token expiry.
**Disconnect Garmin** opens a confirmation; only **Confirm disconnect** deletes tokens from
the server and cancels pending login. It does not erase
synced runs or Garmin workouts. Sync and live Garmin actions prompt you to connect when needed;
local previews still work without a Garmin connection. Login is never automatically retried.
After a failed or timed-out request, refresh Garmin status before another login attempt.
The server renews access tokens once per request when needed, without using your password.
Connected settings show activity coverage from `/status` separately from the Garmin session.
Without a plan, `/status` fails and the app shows coverage as unavailable, even when stored activities exist.
After creating a plan, use **Retry activity coverage** to load coverage.
The empty coverage message appears only after a successful response without coverage.
Settings, Today, and Actions also show the last successful sync timestamp and latest sync error
from `/sync/status`, which works before a plan exists. Reconnect guidance does not claim that every
request failure is an expired session. Progress shows saved reasons for each applied adjustment.

See the root [Garmin guide](../README.md#garmin-authentication-and-first-live-check) for container
storage, server configuration, MFA worker requirements, upstream login limitations, and CLI commands.

Both server settings are saved together in `expo-secure-store`.
In the confirmation, **Forget server connection** removes the saved URL and bearer token, discards pending previews, and returns to onboarding.
The server keeps its plan, activities, and Garmin connection. **Keep connection** cancels without removing credentials.
Garmin email, password, and MFA code are never put in SecureStore. Tokens are never put in URLs, analytics,
logs, source files, or build configuration. Changing connections invalidates pending previews.
Saving or forgetting a connection clears recovery inspection, acknowledgement, and the selected week.
The app ignores late responses from the previous connection.

A physical phone's `localhost` is the phone itself. Use the server's HTTPS address for phones.
For local simulator development only, HTTP loopback is accepted: `http://127.0.0.1:8000` for an
iOS simulator, or `http://10.0.2.2:8000` for the Android emulator. Release networking policies
can require HTTPS even there. Native apps do not require CORS settings.
Keep the server timezone aligned with the athlete's local timezone.

## Screens and actions

Today, Week, Plan, Progress and Settings are the primary tabs.
Today, Week and Plan link to Actions. A missing-plan error links to Goal setup.

- **Today:** local-calendar current week and today's workouts, with rest-day and before/after-plan states.
  The app reads `/status` and `/plan` to identify the week, then `/weeks/{number}`.
- Week: seven days of rest, planned sessions and inferred matches, with previous/next navigation.
  The view starts at the current week, or the first available week when the current week is absent.
  An unavailable selection uses the same fallback.
- **Plan:** weeks with workouts, expandable into workout steps, target pace, and heart-rate ranges.
- **Goal:** distance, Monday start, completion date, weekly frequency, long-run day, and heart rates.
  The server remains authoritative for validation and uses activities already stored there.
- **Progress:** `/load` and `/compliance`, including missing-heart-rate notices.
- **Actions:** sync Garmin activities into the server; review adjustment reasons before applying;
  preview a Garmin push, optionally filtered by week.
  See the [calendar workflow](../docs/self-hosting.md#garmin-calendar-window) for window limits, combined previews, and cleanup.
  Push previews show workout names, dates, step durations or distances, and targets.
  Show payload details reveals the raw payload.
  Removal previews list ownership candidates across all weeks, including workouts never uploaded.
  These counts do not establish how many remote workouts exist. Live removal affects only matching Garmin workouts.
- **Settings:** secure server connection storage, an explicit server test, and Garmin login/MFA, status, and disconnect.

Push and removal first send `dry_run: true, apply: false`. Only the separate **Confirm live**
button sends `dry_run: false, apply: true`. Editing the week, cancelling, changing connections,
or leaving the Actions screen invalidates the preview. Empty or failed previews cannot be
confirmed. Weekly adjustment eligibility and confirmation follow the
[weekly loop](../README.md#weekly-loop). For daily changes, see
[recovery and step feedback](#recovery-and-step-feedback).
If the server rejects a stale proposal, tap **Preview adjustment** and review it again.
The separate Garmin push and manual removal actions recalculate operations on confirmation without an immutable preview identifier.
Avoid concurrent changes from another client while reviewing those operations.
For failed writes, follow the [recovery guidance](#runner-design-and-api-limits) before another attempt.
The app shows errors, including 401 and timeouts, on screen. Read screens offer Retry and reload on focus or app resume.
Today and Week also reload at local midnight.
The server runs daily activity sync at a configurable time and imports history in paced pages.
See [sync configuration](../docs/self-hosting.md#automatic-sync-and-import-recovery).
There is no notification service or multi-user account.
See [API limits](#runner-design-and-api-limits) for excluded features.

## Generated API contract

`src/api/schema.ts` is generated from `../docs/openapi.json`. Do not edit it by hand.
`src/api/client.ts` provides typed operations, bearer auth, error handling, and a default 15-second timeout.
See [run capture timing](../docs/activity-data.md) for the longer sync timeout.

```sh
npm run generate:api
npm run typecheck
npm run lint
npm test -- --ci
npm run export:mobile
npx expo install --check
npx expo-doctor
```

The generator uses `--default-non-nullable false` so schema fields with server defaults remain
optional in requests. TypeScript is pinned to 5.9 because openapi-typescript 7 requires TypeScript
5; this deliberate tooling exception is listed in `expo.install.exclude`. SDK 57's native
packages stay aligned with Expo's installer. `test-renderer` 1.2 is pinned for React 19.2 because
newer versions use React 19.3's reconciler.

Jest uses `jest-expo` and React Native Testing Library with an in-memory mocked HTTP transport
and mocked SecureStore. Tests run offline and never access Garmin or real credentials. GitHub
Actions checks generated-type drift, typecheck, lint, tests, and both native bundle exports
alongside the existing Python jobs. `tests/onboarding.test.tsx` walks a fresh install through
Today with both Garmin login and skip paths, and exercises the settings states in both themes.
`tests/routing.test.tsx` uses the real Expo navigator to check that a Settings deep link still
finishes onboarding on Today. The existing screen tests cover preview invalidation when the
server changes and ensure credentials are never saved.

For a real local HTTP proof, install the root Python dependencies (`uv sync --locked`), start
the [disposable PostgreSQL](../docs/self-hosting.md#local-offline-tests-and-synthetic-proof),
export `TEST_DATABASE_URL`, and run:

```sh
npm run proof
```

This starts the actual FastAPI server on a temporary loopback port, uses a generated ephemeral
bearer token, invokes the real pairing CLI, exchanges the one-time code with the mobile client,
checks reuse rejection and secret-free logs, and exercises the mobile TypeScript client: rejected auth, goal creation, plan and
week reads, load/compliance, an empty synthetic activity import, adjustment proposal, and Garmin
dry-run previews. It asserts zero scheduled Garmin workouts. No Garmin login or network calls
are made. The proof uses an isolated PostgreSQL schema that is removed on shutdown. Server logs stay
under ignored `.local/mobile-proof-*` in the repository. The proof stops its server on completion. Bundle exports prove compilation, not
physical device behavior; test both devices before distributing a release.

## EAS builds

The committed `eas.json` has these profiles:

| Profile       | Use                                                                      |
| ------------- | ------------------------------------------------------------------------ |
| `development` | Internal development client, connects to Metro                           |
| `preview`     | Internal standalone app; Android APK, provisioned iOS devices            |
| `production`  | Android app bundle and iOS store archive, remote build-number increments |

### Build your own app copy

Create your own [Expo account](https://expo.dev/signup). From `app/`, install dependencies
with `npm ci`. Cloud builds use your Expo account's build allowance; iOS device builds also
require an Apple Developer membership. You do not need the maintainer's Expo access.

Before running EAS, edit **your fork's** `app/app.json`:

| Field under `expo`       | Change                                                                   |
| ------------------------ | ------------------------------------------------------------------------ |
| `owner`                  | Replace `junlov` with your Expo username or organization                 |
| `extra.eas.projectId`    | Delete this property, then let `eas init` generate your own ID           |
| `android.package`        | Replace `org.stridecoach.app` with your unique reverse-domain identifier |
| `ios.bundleIdentifier`   | Replace `org.stridecoach.app` with your unique reverse-domain identifier |
| `name`, `slug`, `scheme` | Choose names and a URL scheme for your copy                              |

**The committed project ID `1292c8fc-a736-43a2-be85-a0fb899f9475` belongs to the maintainer.
It must be replaced, not reused.** Keep `extra.router` and the other configuration intact.
Then run:

```sh
npx eas-cli@latest login
npx eas-cli@latest whoami
npx eas-cli@latest init
npx eas-cli@latest project:info
npx eas-cli@latest build:configure
```

Verify that `project:info` names your account/project and that `extra.eas.projectId` now
contains a different ID. Preserve the existing build profiles. Commit your identifiers to your
fork, not an upstream contribution. Never embed the server bearer token or Garmin credentials.
See Expo's [build setup guide](https://docs.expo.dev/build/setup/).

Build an Android APK that runs without Metro:

```sh
npx eas-cli@latest build --platform android --profile preview
```

Open the finished EAS build's install link on Android, download the APK, and allow installation
from that browser when prompted. Only install builds you trust. Share the build link with your
testers. The production Android profile creates an AAB for Google Play, not a directly
installable APK.

For an iPhone build, register each test device **before** building:

```sh
npx eas-cli@latest device:create
npx eas-cli@latest build --platform ios --profile preview
```

Follow EAS's Apple signing prompts with your own Apple Developer account. Open the finished
build's install link in Safari on a registered iPhone. Ad hoc builds only install on devices
included in their provisioning profile; adding devices requires rebuilding or re-signing.
See [internal distribution](https://docs.expo.dev/build/internal-distribution/).

For an iOS store archive, use:

```sh
npx eas-cli@latest build --platform ios --profile production
```

A production archive is distributed through App Store Connect/TestFlight or the App Store
after the owner's submission and Apple's processing. Users install a TestFlight build through
an invitation in TestFlight. An IPA is not a universal iPhone download. Store listings and
submission are outside this guide. EAS build completion alone does not prove device installation.

After installing either preview app, follow the [connection steps](#connect-your-server).
For a development build instead, use the
`development` profile and start Metro with `npm start -- --dev-client`.

The Expo build-properties plugin enables SDK 57's scene lifecycle support for iOS builds using
Xcode 27. See [SDK 57 release notes](https://expo.dev/changelog/sdk-57) and the
[EAS build guide](https://docs.expo.dev/build/introduction/). Server URL and bearer token are
entered after installation, not embedded in EAS secrets or JavaScript bundles.

## Runner design and API limits

Runner screens follow the approved slate/green Open Design board. `src/theme/index.ts`
owns the light/dark palette, spacing and type scale; `useTheme()` follows device appearance.
`expo-system-ui` enables automatic appearance in Android builds. Shared primitives remain
in `src/components/ui.tsx`. See [Screens and actions](#screens-and-actions) for navigation.

A match detail shows the server's activity ID and matching method, without asserting an
athlete-confirmed association. Progress charts use `/compliance` planned/recorded minutes;
missing-heart-rate runs make the known TRIMP subtotal incomplete, not zero. Plan history
shows the server's saved adjustment totals and reasons. Apply still requires server-side
eligibility checks and does not send Garmin workouts.

The [run detail API](../docs/activity-data.md#streams-and-read-api) exposes stored measurements by activity ID.
Opening **Review matched run** on Today or Week reads `/activities/{id}` and shows recorded
duration, distance, average pace, average heart rate, and ordered laps beside planned minutes.
Missing measurements are labeled unavailable, separately from zero; an empty lap list says
no laps recorded. Loading and failed reads use the shared loading and retry UI. Streams and
routes are not displayed.
The API still lacks an unmatched activity list, distance history, and heart-rate coverage minutes.
For daily changes, the API provides the before and after workouts described in the
[daily recovery contract](../docs/training-rules.md#daily-recovery-proposal).
It still lacks personalized workout explanations, weekly per-workout adjustment diffs, downstream adjustment diffs, and adjustment timestamps.
The repeated-interval design, imports, exports and offline cache are outside this implementation.

After a write fails with an uncertain result, Actions disables further operations. **Inspect
current state** reads `/status`; failed inspection keeps the controls disabled. The runner
must also inspect Garmin directly and acknowledge the check before requesting a new preview.
The API exposes a server-owned workout count, not an authoritative remote list or operation
receipt, so inspection cannot automatically establish whether a Garmin write completed.
Explicit server rejection (4xx) clears the preview and displays the reason instead. Nothing
retries or queues writes. Uncertainty is held in screen memory, not an offline cache; after an
app restart, follow the same inspect-before-retry rule.

`tests/runner-screens.test.tsx` covers the J2 Today-to-Garmin entry point and the J3 applied
reason history, plus seven-day matching, progress accessibility, unavailable data, both
appearances, authentication recovery, eligibility rejection and unknown-write inspection.
The existing screen tests continue to prove explicit apply, empty/failed previews,
cancellation, scope edits and connection changes.

`tests/run-detail.test.tsx` covers matched-run measurements on Today and Week, partial and
missing sensors, zero values, loading, late responses after close, and failed reads with retry.

## Recovery and step feedback

Today shows the current server-day Training Readiness, HRV status, and sleep score, with
unavailable readings labeled. A poor-recovery proposal links to Actions. Tap **Preview
tomorrow's change** to review the current and proposed workout plus reasons, then **Confirm
tomorrow’s change** to save it. Cancelling makes no change. A stale preview must be reviewed
again. A saved change appears in Progress. Existing Garmin workouts require a separate
**Preview Garmin push** and live confirmation to update the watch.

Opening a matched run shows **Step compliance**, including scored/unavailable counts, each
step's duration check, and its lap-average target result. See the
[training rules](../docs/training-rules.md#step-compliance-from-captured-laps) for alignment
limits and thresholds. Missing data is never presented as a failed step.
