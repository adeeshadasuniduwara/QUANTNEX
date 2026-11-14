# QUANTNEX Telegram Release Notifications

QUANTNEX can announce every published GitHub Release in an official Telegram channel. The GitHub Actions workflow is present at `.github/workflows/telegram-release-notify.yml`.

## 1. Create the official channel

1. In Telegram, create a channel named **QUANTNEX Updates**.
2. Choose public or private. A public channel can use a username such as `@QUANTNEXUpdates`; a private channel uses its numeric chat ID.
3. Add your QUANTNEX bot as a channel administrator and grant **Post Messages** permission.

A channel is recommended for one-way official release announcements. A separate linked discussion group can be added later if the community needs replies and discussion.

## 2. Create the bot

1. Open Telegram and find the official `@BotFather`.
2. Send `/newbot`.
3. Choose a display name, e.g. `QUANTNEX Updates Bot`.
4. Choose an available username ending in `bot`.
5. Copy the bot token and keep it private.

Never paste the bot token into source code, README files, screenshots, chat messages, or GitHub commits. If it is exposed, revoke/regenerate it with BotFather.

## 3. Configure GitHub Actions secrets

In the QUANTNEX repository, open **Settings → Secrets and variables → Actions → New repository secret** and add:

- `TELEGRAM_BOT_TOKEN`: the token from BotFather.
- `TELEGRAM_CHAT_ID`: the public channel username (e.g. `@YourChannelUsername`) or the numeric ID of a private channel/group.

The bot must be an administrator with permission to post in a channel. For a group, add the bot and make sure it can send messages. The GitHub workflow now checks this with Telegram's getChatMember API before attempting to send.

### Choose the correct destination

- For a private chat, open your bot in Telegram and send `/start` first. Use your personal numeric chat ID, not the bot's own numeric ID.
- For a channel, use its public `@channelusername` or private numeric chat ID. Add the bot as an administrator and grant **Post Messages** permission.
- For a group/supergroup, add the bot and confirm it is allowed to send messages.
- QUANTNEX's local Telegram connection now checks `getMe`, `getChat` and (for groups/channels) `getChatMember`. A destination that resolves to the bot itself or lacks posting permission is rejected before credentials are saved.
- Never paste bot tokens into chat, screenshots or source files. Keep them only in the encrypted local integration or GitHub Actions secret store.

## 4. Test the connection

Open **Actions → QUANTNEX Telegram Release Announcements → Run workflow** and run it on `main`. If both secrets are configured, the bot sends a test message. If not, the workflow safely skips.

## 5. Automatic announcements

When a GitHub Release is published, the workflow sends a Telegram message containing the release name, tag/version and link to the release downloads.

Note: pushing code to `main` or generating a build artifact does not itself count as a published Release. Publish a versioned GitHub Release (for example, tag `v0.6.0`) to trigger the announcement.

## Security and scope

- The token and chat destination are stored as GitHub Actions secrets, not committed to the repository.
- The workflow only sends release announcements; it does not read messages or control user accounts.
- The bot does not yet provide private support chats, trading commands, signal delivery or account management.
