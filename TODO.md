# Eusebius To Do

## Comic Publishing

- Convert website comic derivatives to PNG, not WebP. Existing rendered WebP
  derivatives should be replaced or mirrored with PNG files in the public
  `comic/` tree.
- Build a comic-book viewer in the static site. It should show rendered panels
  grouped by plan, with image, panel title, caption, passage reference, and
  source translation.
- Render a comic-book PDF every day from the current rendered panels and publish
  it on the website.
- Keep image originals and generated derivatives out of Git; store them under
  `/home/eusebius/eusebius-comic/` on `raksasa` and publish only the derived
  website files to `merah`.

## Comic Generation

- Allow short readable text in generated images when it helps explain the
  panel: title labels, captions, map labels, document headings, or concise
  source-grounded callouts are acceptable.
- Avoid long text blocks, invented speech, or fake documentary quotations.
- Continue rendering at most one queued panel per automation run unless the
  automation policy is explicitly changed.

## Translation And Site Text

- Add a translation review step to the automation: before or after rendering a
  panel, inspect the relevant Greek and English and make small source-grounded
  corrections when the current translation is confusing or mistranslated.
- Record translation corrections in `ai_translation_runs` with model, prompt
  version, token counts, notes, and completion time; do not silently overwrite
  prior runs.
- Generate clean Greek/English side-by-side web pages weekly. Prefer reviewed
  AI translations; clearly label rough First1K English when no reviewed
  translation exists.
