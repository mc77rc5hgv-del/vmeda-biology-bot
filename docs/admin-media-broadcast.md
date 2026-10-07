# Administrative media broadcasts

Open `/admin` → «Анонсы» → «Создать рассылку (текст, фото, видео)».
Send text, a photo/video with its caption, or a Telegram album with up to ten
photos and videos. Review the actual content, then press «Отправить всем».
`/broadcast` starts the same composer; `/broadcast text` or a command in a
photo/video caption opens a preview directly. Replying with `/broadcast` to a
single message copies that message; an additional command argument replaces its
caption. For an album, forward/send all its parts to the composer rather than
replying to a single part (Telegram does not expose the other parts through that
reply).

Captions preserve Telegram HTML formatting and must fit 1024 UTF-16 units;
text messages fit 4096. Media use existing Telegram file IDs. Photos and videos
are sent with their captions; mixed media are sent through `sendMediaGroup`.
Telegram albums cannot carry an inline keyboard, so preview controls follow in
a separate administrator message. Recipients receive only the content.

Only full administrators can compose, cancel or confirm. Draft tokens are bound
to their administrator; stale/duplicate confirmation cannot start another job.
Only one custom broadcast runs at a time. `/admin` cancels an unsent draft.
Delivery respects a per-media delay and Telegram RetryAfter. Other failed
deliveries are counted without deleting users or retrying ambiguous failures.
Completion increments the existing broadcast counter; all other statistics are
preserved. Drafts and running jobs are in memory; do not deploy during a running
broadcast. Actual broadcasts must be initiated by the administrator; tests use
mocked Telegram delivery only.
