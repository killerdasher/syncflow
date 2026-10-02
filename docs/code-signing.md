# Windows Code Signing — Evaluation Notes

Status: **v1 ships unsigned.** Evaluation of better options tracked here.

## Context

Unsigned Windows installers trigger SmartScreen ("Windows protected your PC").
Your own Win10 testing showed **no problem** for personal use — this doc
tracks the improvement path for public distribution.

## Option A — Unsigned (current)

- Zero cost, zero setup. Users click **More info → Run anyway** if SmartScreen
  appears (often it doesn't on Windows 10/11 for direct downloads).
- **Pros:** works today. **Cons:** occasional SmartScreen friction; no
  reputation history.

## Option B — SignPath OSS (recommended next step)

[SignPath.io](https://signpath.org) provides **free code signing for
open-source projects** (repository must be public on GitHub).

Steps once the repo is public:

1. Apply at signpath.org with the GitHub repo URL (open-source tier).
2. Add repository secret `SIGNPATH_API_KEY`.
3. Add a signing step to `.github/workflows/release.yml` after
   `electron-builder`:

   ```yaml
   - name: Sign Windows artifacts (SignPath)
     if: runner.os == 'Windows'
     uses: signpath/github-action-submit-signing-request@v1
     with:
       api-token: ${{ secrets.SIGNPATH_API_KEY }}
       organization-id: ${{ secrets.SIGNPATH_ORG_ID }}
       project-id: ${{ secrets.SIGNPATH_PROJECT_ID }}
       signing-policy-id: ${{ secrets.SIGNPATH_POLICY_ID }}
       github-artifact-name: unsigned-windows
       wait-for-completion: true
   ```

   (Requires uploading the unsigned exe as an artifact named
   `unsigned-windows` and downloading the signed result — follow SignPath's
   current action docs when wiring it up.)

4. Verify: `signtool verify /pa SyncFlow*.exe` or right-click → Properties →
   Digital Signatures.

**Pros:** free, real Authenticode certificate, removes SmartScreen warnings
over time. **Cons:** application/review process, approval wait.

## Option C — Paid OV/EV certificate

- OV codesigning certs start ~$100-400/yr; EV removes SmartScreen warnings
  fastest (but costs more and requires hardware token/HSM — CI integration
  via cloud HSM services).
- **Only pursue if B is rejected and friction is proven real.**

## Decision log

| Date | Decision |
|------|----------|
| 2026-10-02 | v1 ships unsigned (Option A) — verified acceptable on user's Win10 |
| next | Apply SignPath once repo is public (Option B), re-evaluate in a test release |
