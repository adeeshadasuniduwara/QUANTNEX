# QUANTNEX Telegram Gold Reports

## Setup

Connect the user's Telegram bot in QUANTNEX as usual, then send:

- `/gold_setup` — enable scheduled gold images and send an initial report image.
- `/gold` — request a fresh image at any time.
- `/gold_status` — inspect the scheduled-report setting.
- `/gold_off` — disable scheduled images.

The Telegram bot command menu is refreshed automatically when the worker sees the new command registration version.

## Schedule

Enabled users receive reports at **00:00 and 12:00 Asia/Colombo**. Each slot is delivered once per Colombo calendar date/hour. Delivery is retried during the first ten minutes of the slot if a transient failure occurs.

## Image contents

A branded monochrome QUANTNEX 4K portrait image contains:
- Indicative 24K and 22K LKR prices per gram.
- 1g, 2g, 4g, 8g, 10g and 100g values for both purities.
- 24-hour percentage movement when a saved snapshot between 23 and 25 hours old is available.
- Capture time, USD/LKR reference and feed labels.

The image is 2160×3840 JPEG for Telegram photo delivery. Price conversion is derived from XAU/USD spot per troy ounce and the USD/LKR reference rate. 22K is calculated as 22/24 of the 24K spot conversion. These are indicative international spot conversions, not Sri Lankan jeweller retail quotes; taxes, workmanship and dealer premiums are excluded.

## 24-hour history

The local QUANTNEX database stores a small rolling history of the user's report snapshots. During the first 24 hours after enabling, the image explicitly says the comparison is building rather than inventing a percentage. Once a comparable 23–25 hour sample exists, the report displays the percentage change separately for 24K and 22K.

## Privacy and scope

The report is sent only to the Telegram destination already connected for that QUANTNEX user. No new bot token or chat ID is requested by the feature. User preferences and snapshots are stored in the existing local user database.

WhatsApp delivery is not included in this release; it requires a separate WhatsApp Business Cloud API integration and user authorization. The Telegram feature does not send to WhatsApp.
