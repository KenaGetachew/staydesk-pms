# StayDesk brand assets

The mark: an arched doorway (the Aksum / Lalibela arch) over the front
desk, with the Meskel sun rising inside it - a door into a stay.

## Palette

| Token | Hex | Use |
|---|---|---|
| Highland Teal | `#0D5C63` | mark, primary buttons, `--color-brand-600` |
| Teal 700 | `#0A474D` | hover / pressed |
| Meskel Gold | `#F2B233` | the sun, accent rules (not for text on white) |
| Coffee Ink | `#2B1D14` | wordmark "Stay" |

The UI ramp lives in `frontend/src/index.css` (`--color-brand-*`, light
and dark), and the booking-page default accent in
`frontend/src/lib/accents.ts`.

## Files

- `staydesk-mark.svg` - square icon (favicons, app icons, avatars)
- `staydesk-square.svg` - stacked lockup (social profiles, print)
- `staydesk-horizontal.svg` - mark + wordmark (site headers, docs, decks)
- `staydesk-horizontal-white.svg` - the same for dark backgrounds
- `png/` - rendered exports (mark 512/1024, square 1024, horizontal
  1560x480, favicon-32, apple-touch-180)
- `source/kamra-pms-original.png` - the upstream Kamra raster, kept for reference

`kamra/public/kamra-mark.svg` is a copy of the StayDesk mark at the old
path: existing sites saved that URL as their favicon.

## Notes

- Wordmark font: geometric sans (Poppins SemiBold preferred; lockup SVGs
  fall back to Avenir Next/Montserrat). Before print/press use, convert
  the text to outlines in the SVGs.
- Regenerate PNGs: `rsvg-convert -w 512 staydesk-mark.svg -o png/staydesk-mark-512.png`
  (and likewise for the other sizes).
- Clear space: keep at least the sun's diameter around the mark.
- Only user-facing text says StayDesk. The Frappe app, module, routes
  (`/kamra`), DocTypes, roles and webhook headers keep the upstream
  `kamra` names so merges from upstream stay cheap.
