# Comic render issues

## 2026-09-08: panel 14 rejected for anachronistic architecture

The one permitted image-generation call produced a golden-domed shrine resembling
the Dome of the Rock in the skyline of a first-century Jerusalem scene. Visual
review rejected the image; it was not published. Asset 14 has status `rejected`
and no public path. Panel 14 remains the earliest eligible queued panel.

The original, WebP, exact generation prompt, hashes, and review are preserved on
`raksasa` under `/home/eusebius/eusebius-comic/rejected/14/2026-09-08/`.
The database negative prompt now explicitly excludes the Dome of the Rock,
Islamic shrines, minarets, medieval/modern Jerusalem, and buildings constructed
after the first century CE. The review JSON records the old and new exclusions;
the original planner output and panel prompt remain intact.

Next run: use the revised database prompt for panel 14, inspect the skyline,
and publish only if the image passes historical review. Rejected images must
remain outside the accepted originals/web paths so they cannot obstruct a retry.

## 2026-09-01: deployed WebP returned HTTP 403

An atomic temporary derivative retained mode `0600`; site generation copied that
mode into the public tree. The live file was corrected during that run. On
2026-09-08, `publish_comic_images` was changed to set published files to `0644`.
The regression test starts with a `0600` source and checks that publication makes
the output readable without changing the canonical source's permissions.

## 2026-09-08: WebP MIME type needs hosting follow-up

After deployment, `/comic/4/1.webp` returns HTTP 200 and its bytes match the
canonical derivative, but Content-Type is `application/octet-stream` instead of
`image/webp`. A unique query-string request also returned that type with
Cloudflare `MISS`, so this is not just an old cached header. Merah's
`/usr/share/misc/mime.types` already lists `image/webp`; inspect the active vhost
MIME configuration in a hosting follow-up. No server configuration changed in
this renderer run.
