# Project skills (Expo and EAS)

Claude Code loads these skills only in sessions started inside this repository. They support the
mobile app in `app/` (Expo). Refresh them by re-copying the folders from a current install
(`~/.agents/skills/<name>`, resolving symlinks), then update the date below.

All skills below come from the `expo/skills` repository (https://github.com/expo/skills), copied on 2026-10-19.
Files are vendored verbatim from upstream (including its punctuation). `expo-skill-eval/scripts`
is excluded from Ruff (`extend-exclude` in `pyproject.toml`).

| Skill | Purpose | Source | Copied |
|---|---|---|---|
| eas-app-stores | Build and submit iOS and Android apps with EAS to TestFlight, App Store, or Google Play | expo/skills | 2026-10-19 |
| eas-hosting | Deploy Expo websites and API routes to EAS Hosting | expo/skills | 2026-10-19 |
| eas-observe | Add and use EAS Observe (`expo-observe`) app metrics | expo/skills | 2026-10-19 |
| eas-simulator | Run and control an app on a remote EAS cloud simulator | expo/skills | 2026-10-19 |
| eas-update | Configure over-the-air updates with expo-updates and EAS Update | expo/skills | 2026-10-19 |
| eas-update-insights | Check crash rates, installs, and payload size of published updates | expo/skills | 2026-10-19 |
| eas-workflows | Write and understand EAS workflow YAML files | expo/skills | 2026-10-19 |
| expo-animation | Build animations in React Native and Expo | expo/skills | 2026-10-19 |
| expo-app-clip | Add an iOS App Clip target to an Expo app | expo/skills | 2026-10-19 |
| expo-brownfield | Embed Expo and React Native in an existing native app | expo/skills | 2026-10-19 |
| expo-data-fetching | Network requests, API calls, and data fetching | expo/skills | 2026-10-19 |
| expo-design-system | Build a design system (tokens and themes) inside an Expo app | expo/skills | 2026-10-19 |
| expo-dev-client | Build and distribute Expo development clients | expo/skills | 2026-10-19 |
| expo-dom | Use Expo DOM components to run web code in a webview | expo/skills | 2026-10-19 |
| expo-examples | Official Expo example projects (`with-*` integrations) | expo/skills | 2026-10-19 |
| expo-migrate-module | Migrate Swift Expo native modules to the Modules API 2.0 | expo/skills | 2026-10-19 |
| expo-module | Create Expo native modules and views | expo/skills | 2026-10-19 |
| expo-native-ui | Native-feeling Expo screens (Apple HIG, controls, SF Symbols) | expo/skills | 2026-10-19 |
| expo-overview | Entry point and router for any Expo or EAS task | expo/skills | 2026-10-19 |
| expo-project-structure | Folder structure for a new Expo app | expo/skills | 2026-10-19 |
| expo-router | Navigation and routing with Expo Router | expo/skills | 2026-10-19 |
| expo-skill-eval | Evaluate Expo skills (trigger accuracy, code quality) | expo/skills | 2026-10-19 |
| expo-skill-feedback | Submit feedback on an Expo skill and control its telemetry | expo/skills | 2026-10-19 |
| expo-ui | Native SwiftUI and Jetpack Compose UI with `@expo/ui` | expo/skills | 2026-10-19 |
| expo-upgrade | Upgrade Expo SDK versions and fix dependency issues | expo/skills | 2026-10-19 |
| expo-web-to-native | Migrate a web React app to a native Expo app | expo/skills | 2026-10-19 |
