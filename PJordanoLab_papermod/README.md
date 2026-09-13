

## Assets: what is local, what is still remote

Final state after mirroring (verified against the rendered `public/` on every build):

| | count |
|---|---|
| PDF/supplement files in `static/pdfs/` | 189 |
| Image files in `static/images/` | 697 |
| PDF links in rendered HTML | 187 — all resolve to a local file |
| Image references in rendered HTML | 469 — all resolve to a local file |

### How the PDFs were obtained

1. **48** downloaded from `pjordanolab.ebd.csic.es` (live).
2. **~140** could **not** be downloaded: `ebd10.ebd.csic.es` returns `502 Bad Gateway`
   for every request, including its own root, over both http and https — the legacy host
   is unreachable, it is not rejecting the crawler.
3. Those were recovered from the local archive `/Users/pedro/Documents/Sites/ebd10_new/pdfs`
   (275 PDFs, read-only grant): matched by exact filename, then by a normalisation that folds
   case, unicode hyphen variants and punctuation, then by conservative close-match.
4. The old server's abbreviated names (`HJGT98_AmNat.pdf`, `JordSchu_2000EcolMonogr.pdf`,
   `Conservacao_06.pdf`, …) were resolved by token search on surname + year and **each candidate
   was checked against that entry's own verbatim citation before acceptance** — resemblance of
   filename alone was not accepted. Candidates sharing a surname and year but belonging to a
   different paper or journal were rejected.
5. Filenames are whitespace-normalised (`_` for spaces) on copy. One link was case-corrected
   (`Prunus_Lab_Protocols` → `Prunus_Lab_protocols`) so it survives a case-sensitive web server.

### Links deliberately left pointing at the old host (21)

All on `ebd10.ebd.csic.es`, which is down, and **none of these files are in the local archive** —
press cuttings, two radio recordings, and old HTML abstract/course pages. They were not rewritten,
because pointing them at local files that do not exist would be worse than an honest external link.
If you find these files, drop them in `static/pdfs/` and rewrite the links.

- `http://ebd10.ebd.csic.es/ebd10/Media_files/RNM.pdf`
- `http://ebd10.ebd.csic.es/ebd10/Media_files/http-%3A%3Awww.andaluciainvestiga.com%3Aespanol%3Anoticias%3A2%3A8890.asp.pdf`
- `http://ebd10.ebd.csic.es/evol/cursobioevo.html`
- `http://ebd10.ebd.csic.es/evol/tecmol.html`
- `http://ebd10.ebd.csic.es/media_press/20abril06arquitectura_biodiversidad.pdf`
- `http://ebd10.ebd.csic.es/media_press/CSIC_PNAS_Modul.pdf`
- `http://ebd10.ebd.csic.es/media_press/EBD_Expo_IEG_Poster_screen.pdf`
- `http://ebd10.ebd.csic.es/media_press/EBD_Expo_Semillas_screen.pdf`
- `http://ebd10.ebd.csic.es/media_press/Eds_Choice_Science_2011_1201.pdf`
- `http://ebd10.ebd.csic.es/media_press/Frugivoros_y_semillas_Imagenes_FECYT2004.pdf`
- `http://ebd10.ebd.csic.es/media_press/PUBLICO-07.pdf`
- `http://ebd10.ebd.csic.es/media_press/Pannell_2007_CurrBiol.pdf`
- `http://ebd10.ebd.csic.es/media_press/Pedro@Fund_juan_March_04May2006.mp3`
- `http://ebd10.ebd.csic.es/media_press/REE_Pedro%20Jordano_Dispersion%20de%20semillas.mp3`
- `http://ebd10.ebd.csic.es/media_press/RedLife132.pdf`
- `http://ebd10.ebd.csic.es/media_press/S1a_PT.jpg`
- `http://ebd10.ebd.csic.es/media_press/Science-Magazine.pdf`
- `http://ebd10.ebd.csic.es/mywork/abstr/bascompte_etal_2006_Science.html`
- `http://ebd10.ebd.csic.es/mywork/abstr/diff_contrib_abs.html`
- `http://ebd10.ebd.csic.es/sci/seminarios.html`
- `http://ieg.ebd.csic.es/KimberlyHolbrook/Holbrook.htm`

### Not imported from the old site

`/markdown/` (CV) and `/outreach/` exist in the local archive but were never part of the
imported page set. `ieg.ebd.csic.es/KimberlyHolbrook/Holbrook.htm` is a third-party page and
is correctly left external.

### Three PDF links removed

`Garcia_etal_2009_MolEcol_Reply_Prunus`, `JEcolGeogr2000` and
`Mello_etal_2011_Oecologia_BatBird_networks_modularity` are absent from both the live host and
the archive. Their dead PDF icons were removed; the citations themselves are untouched.

### Other fixes in this pass

- Old-site typo `https://http://…` normalised.
- Gallery lightbox anchors (`…/pageN-…-full.html`) unwrapped: images keep their picture but no
  longer link to the dead server. Gallery pagination paths collapse onto `/gallery/`.
- Absolute links to the old domain converted to site-relative paths.
- Favicon taken from the old site archive; all five PaperMod icon params point at it.
- `.Language.LanguageCode` / `.Language.LanguageDirection` replaced with `.Locale` / `.Direction`
  in the vendored theme templates — the build is now warning-free on Hugo 0.166.0.
