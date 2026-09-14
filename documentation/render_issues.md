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

Resolved on 2026-09-15: the single retry used the revised database exclusions
and passed visual review. No domed shrine, minarets, or readable text were
visible. The architecture remains illustrative rather than an archaeological
reconstruction. Accepted asset 15 is published at `/comic/4/2.webp`; the rejected
asset and its evidence remain intact. Original and WebP hashes were verified
against S3 downloads, and the public WebP matches the canonical derivative.
The exact prompt, source snapshot, and review are preserved under
`/home/eusebius/eusebius-comic/reviews/14/2026-09-15/` on `raksasa` and in S3.

Panel 14 is now rendered. Next eligible panel is 15, plan 4 panel 3,
"The Jerusalem church migrates to Pella". Rejected images must remain outside
the accepted originals/web paths so they cannot obstruct a retry.

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

2026-09-15 diagnosis: the active `/etc/httpd.conf` has an explicit global
`types` block containing PNG, JPEG, and GIF but no WebP mapping; it does not
load `/usr/share/misc/mime.types`. The Eusebius vhost has no MIME override.
The newly published `/comic/4/2.webp` also returns `application/octet-stream`
on a Cloudflare MISS. Both canonical and deployed derivatives are mode `0644`.

The hosting administrator should add this entry inside the existing global
`types` block, validate the configuration with `httpd -n`, reload httpd, and
verify a fresh image response:

```text
image/webp              webp
```

The `merah-personal-research-projects` skill says "Do not edit
`/etc/httpd.conf` directly. Print the stanza the user should add." This run
therefore records the diagnosed fix without changing the shared server config.
