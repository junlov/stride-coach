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
   Configure the same long bearer token on the server and phone.
2. Put the server behind HTTPS with a trusted certificate. Point the phone at a URL such as
   `https://coach.example.com`, optionally with a reverse-proxy path prefix.
3. Open **Settings**, enter the URL and token, tap **Test connection**, then **Save connection**.
   The test calls `/status` with the entered values, even before saving. A server with no plan
   will tell you to open Goal setup after saving.
4. In the **Garmin** section, tap **Connect Garmin** after entering your Garmin email and password.
   The app sends them once over the authenticated HTTPS connection and clears the password field
   immediately. If requested, enter the MFA code Garmin sends. The server's challenge expires after five minutes.
   After a server restart or a failed completion, start a new explicit login.
5. Open **Goal** to create the initial plan. The server supports one plan per database. For a
   later goal, the operator must configure a fresh database; the app cannot replace the plan.

**Refresh Garmin status** shows the connected account (when available) and access-token expiry.
**Disconnect Garmin** deletes tokens from the server and cancels pending login. It does not erase
synced runs or Garmin workouts. Sync and live Garmin actions prompt you to connect when needed;
local previews still work without a Garmin connection. Login is never automatically retried.
After a failed or timed-out request, refresh Garmin status before another login attempt.
The server renews access tokens once per request when needed, without using your password.

See the root [Garmin guide](../README.md#garmin-authentication-and-first-live-check) for container
storage, server configuration, MFA worker requirements, upstream login limitations, and CLI commands.

Both server settings are saved together in `expo-secure-store`. **Forget connection** removes the
saved server URL/bearer token and clears connected screen state. It does not disconnect Garmin
on the server. Garmin email, password, and MFA code are never put in SecureStore. Tokens are never put in URLs, analytics,
logs, source files, or build configuration. Changing connections invalidates pending previews.

A physical phone's `localhost` is the phone itself. Use the server's HTTPS address for phones.
For local simulator development only, HTTP loopback is accepted: `http://127.0.0.1:8000` for an
iOS simulator, or `http://10.0.2.2:8000` for the Android emulator. Release networking policies
can require HTTPS even there. Native apps do not require CORS settings.
Keep the server timezone aligned with the athlete's local timezone.

## Screens and actions

- **Today:** local-calendar current week and today's workouts, with rest-day and before/after-plan states.
  The app reads `/status` and `/plan` to identify the week, then `/weeks/{number}`.
- **Plan:** weeks with workouts, expandable into workout steps, target pace, and heart-rate ranges.
- **Goal:** distance, Monday start, completion date, weekly frequency, long-run day, and heart rates.
  The server remains authoritative for validation and uses activities already stored there.
- **Progress:** `/load` and `/compliance`, including missing-heart-rate notices.
- **Actions:** sync Garmin activities into the server; review adjustment reasons before applying;
  preview a selected week or all future workouts before pushing to Garmin. Removal previews
  **all** workouts owned by the server, independent of the week field.
- **Settings:** secure server connection storage, an explicit server test, and Garmin login/MFA, status, and disconnect.

Push and removal first send `dry_run: true, apply: false`. Only the separate **Confirm live**
button sends `dry_run: false, apply: true`. Editing the week, cancelling, changing connections,
or leaving the Actions screen invalidates the preview. Empty or failed previews cannot be
confirmed. Applying an adjustment requires the target Monday and a sync covering the previous
two complete weeks. Reductions can also affect later weeks; the server checks this when applying.

The API recalculates operations on confirmation; it has no immutable preview identifier. Avoid
concurrent changes from another client while reviewing. The app never retries writes automatically.
If a connection fails during a write, inspect the server state before trying again. Errors,
including 401 and timeouts, are shown on screen. Read screens offer Retry and reload on focus or app resume.
Today also reloads at local midnight.
There is no offline workout cache, background sync, notification service, or multi-user account.

## Generated API contract

`src/api/schema.ts` is generated from `../docs/openapi.json`. Do not edit it by hand.
`src/api/client.ts` provides typed operations, bearer auth, error handling, and a 15-second timeout.

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
alongside the existing Python jobs.

For a real local HTTP proof, install the root Python dependencies (`uv sync --locked`), start
the [disposable PostgreSQL](../docs/self-hosting.md#local-offline-tests-and-synthetic-proof),
export `TEST_DATABASE_URL`, and run:

```sh
npm run proof
```

This starts the actual FastAPI server on a temporary loopback port, uses a generated ephemeral
bearer token, and exercises the mobile TypeScript client: rejected auth, goal creation, plan and
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

Before your first build, choose your own unique `ios.bundleIdentifier` and `android.package`
in `app.json`. The repository uses `org.stridecoach.app` as its starting identifier. Set the
Expo owner for your account, then link your own EAS project (which adds its project ID):

```sh
npx eas-cli@latest login
npx eas-cli@latest init
npx eas-cli@latest build:configure
npx eas-cli@latest build --platform all --profile development
npm start -- --dev-client
npx eas-cli@latest build --platform all --profile preview
npx eas-cli@latest build --platform ios --profile production
npx eas-cli@latest build --platform android --profile production
```

EAS handles native project generation and signing. iOS device and store builds require an Apple
Developer account and provisioning; register test devices for internal distribution. Android
production builds use a signing keystore managed through EAS credentials. Production builds
can be uploaded to App Store Connect and Google Play Console by their owner. Store submission,
listing assets, and review are outside this task; no EAS builds or store uploads are performed by
local tests. Replace the starter app icons with your release artwork before store distribution.

The Expo build-properties plugin enables SDK 57's scene lifecycle support for iOS builds using
Xcode 27. See [SDK 57 release notes](https://expo.dev/changelog/sdk-57) and the
[EAS build guide](https://docs.expo.dev/build/introduction/). Server URL and bearer token are
entered after installation, not embedded in EAS secrets or JavaScript bundles.

## Runner design and API limits

Runner screens follow the approved slate/green Open Design board. `src/theme/index.ts`
owns the light/dark palette, spacing and type scale; `useTheme()` follows device appearance.
`expo-system-ui` enables automatic appearance in Android builds. Shared primitives remain
in `src/components/ui.tsx`. Today, Week, Plan, Progress and Settings are the primary tabs;
Today and Plan link to Actions, and a missing-plan error links to Goal setup.

The seven-day Week view labels rest, planned sessions and inferred matches separately.
A match detail shows the server's activity ID and matching method, without asserting an
athlete-confirmed association. Progress charts use `/compliance` planned/recorded minutes;
missing-heart-rate runs make the known TRIMP subtotal incomplete, not zero. Plan history
shows the server's saved adjustment totals and reasons. Apply still requires server-side
eligibility checks and does not send Garmin workouts.

The current API does not return recorded activity measurements or unmatched activity rows,
activity provenance/laps/routes, distance history, heart-rate coverage minutes, personalized
workout explanations, per-workout adjustment diffs, downstream adjustment diffs or adjustment
timestamps. The UI discloses these gaps and renders the available totals, steps and reasons.
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
