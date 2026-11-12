# Portrait overrides

Drop an image here to replace a character's drawn portrait in the viewer, without code changes.

- File name: the codename in lower case plus one of `.png`, `.webp`, `.jpg`, `.svg`, for example
  `rook.png` or `vesper.webp`. Only the 20 codenames in `config.CODENAMES` are used; anything else in
  this folder is ignored and never served. If several formats exist for one codename, the first of
  png, webp, jpg, svg wins.
- Framing: the image fills the character's 200 x 220 box (cropped to cover, anchored at the bottom
  centre), so a head-and-shoulders crop about 10:11 works best. A transparent background lets the
  scene's light show through.
- Behaviour: an override switches off the drawn expressions; the character gets a simple bob while
  talking and is faded when eliminated.
- Size: at most 8 MB per file. `--export` embeds every override in the exported page as a data URI,
  so keep them small if you export.
- No art ships in this folder; only this README.

## Global and per-game overrides

Codenames are dealt per game, so an image directly in this folder applies to that codename in
**every** game, whichever model holds it. To change one game only, put the images in a sub-folder
named exactly by the game id (the log's file name without `.jsonl`, for example `g-20261110-143502-s7`):

```
portraits/
  rook.png                         global: Rook in every game
  g-20261110-143502-s7/
    rook.png                       Rook in game g-20261110-143502-s7 only
    vesper.webp                    Vesper in game g-20261110-143502-s7 only
```

- Same file rules inside the game folder: lower-case codename plus png, webp, jpg or svg, at most 8 MB,
  no symlinks; anything else is ignored. The folder itself must be a real directory (not a symlink)
  whose name matches the game id exactly, case included. Folders inside it are ignored.
- Precedence, per codename, for the game being shown: that game's own image, then the global image
  in this folder, then the drawn portrait. The format order (png, webp, jpg, svg) only chooses within
  one folder; a per-game `rook.svg` still beats a global `rook.png`.
- Every other game is unaffected, and switching games in the viewer swaps to that game's set.
- An override only changes the picture. The name, model and role shown for a player, the game log and
  everything the models saw stay exactly as they were.

Worked example: in game `g-20261110-143502-s7` the moles were Rook and Vesper, and you want them in mole
masks for that game's clip. Create `portraits/g-20261110-143502-s7/` and save `rook.png` and `vesper.png` in
it. Opening `g-20261110-143502-s7` in the viewer (or `python -m inside_job view g-20261110-143502-s7 --export clip.html`)
shows the masks for Rook and Vesper; the other five players keep their global image if `portraits/` has
one for them, otherwise their drawn portrait. In the next game Rook is someone else and is drawn as usual.

The server lists one game's set at `/api/portraits?game=<game_id>` (the global set alone at
`/api/portraits`) and serves per-game files at `/portraits/<game_id>/<file>`.
