# QUANTNEX Windows Releases

## First release

The Windows app checks the GitHub Releases API for the latest published release. A normal commit, pull request, Actions build artifact, or source ZIP is not a published release.

After the release workflow has reached the default branch:

1. Open the repository's **Actions** tab.
2. Select **QUANTNEX Publish Release**.
3. Choose **Run workflow**.
4. Enter the version **v0.6.0** for the first release.
5. Run the workflow and wait for the Windows build and release-publishing steps to complete.
6. Open **Releases** and confirm that the release contains both `QUANTNEX.exe` and `SHA256SUMS.txt`.

The workflow can also publish automatically when a `v*` tag is pushed.

## Update behavior

- Source checkout: the desktop app fast-forwards a clean Git working tree from `main`.
- Source ZIP: the app downloads and validates the latest `main` source ZIP to the Downloads folder. It does not overwrite the running folder.
- Packaged EXE: the app downloads the latest published `QUANTNEX.exe`, checks its SHA256 against `SHA256SUMS.txt`, then offers installation and restart.
- If no GitHub Release exists, the packaged EXE reports that no release is available. This is expected until the first versioned release is published.

## Telegram announcements

Telegram announcements are optional. Configure the repository Actions secrets `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. The bot must be an administrator of the target channel with permission to post messages. If either secret is absent, the release still publishes and the Telegram step skips safely.

Never put bot tokens or API credentials in source files, commits, issues, or chat messages. If a token was exposed, revoke it with BotFather and create a replacement before configuring the repository secret.
