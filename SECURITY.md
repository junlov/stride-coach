# Security policy

Please report vulnerabilities privately. Do not put credentials, personal activity data,
exploit instructions, or unpatched security details in a public issue or pull request.

Use GitHub's [private vulnerability reporting](https://github.com/junlov/stride-coach/security/advisories/new)
when the repository offers it. If that page is unavailable, open a public issue containing
only "Please enable private vulnerability reporting so I can send a confidential report."
Wait for the private channel before sharing details. This repository does not currently
promise a monitored security email or a response deadline.

In the private report, include affected versions/commit, impact, a minimal synthetic
reproduction, and suggested mitigation if known. Omit live secrets and other people's data.
Maintainers will coordinate a fix and disclosure with the reporter. Security fixes target
the current default branch; older snapshots have no guaranteed support window.

For deployment hardening, HTTPS, token storage, and backups, see
[the self-hosting guide](docs/self-hosting.md). Rotate any exposed bearer or Garmin credentials
through the relevant service and remove leaked material from shared logs.
