"""CLI: play a game, a trial or a batch of games, report on a batch, watch one (terminal or browser),
render a transcript, print a token report, preflight the cast, measure clue balance (`solve`) and run
scripted-bot sweeps (`bots`)."""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

from .config import ConfigError, config_from_dict, load_config, load_raw, parse_set, trial_config
from .batch import new_game_id, save_game
from .engine import Game
from .llm import ClaudeCLI, MockLLM
from .log import read_log
from .rawlog import RawLog, code_fingerprint
from .results import token_report
from .transcript import render


def make_client(cfg):
    """The real model client (tests replace this to check the preflight without model calls): a
    plain `ClaudeCLI` for an all-Claude cast, else a `RoutedLLM` that sends ids with a "/" to
    OpenRouter (docs/OPENROUTER.md)."""
    from .openrouter import build_client
    return build_client(cfg)


def openrouter_gate(cfg, args, mock: bool) -> int:
    """Apply --budget-usd, refuse a real run whose OpenRouter seats have no key or no budget, and
    start this process's spend ledger. 0 = go on, 2 = refuse (docs/OPENROUTER.md)."""
    budget = getattr(args, "budget_usd", None)
    if budget is not None:
        if not budget > 0:
            print("--budget-usd must be a number of dollars > 0", file=sys.stderr)
            return 2
        cfg.openrouter.budget_usd = float(budget)
    if mock or not cfg.openrouter_models():
        return 0
    from .openrouter import readiness_problems, start_ledger
    problems = readiness_problems(cfg)
    for msg in problems:
        print(f"refusing to start: {msg}", file=sys.stderr)
    if problems:
        return 2
    start_ledger(cfg.openrouter.budget_usd)
    print(f"OpenRouter seats: {', '.join(cfg.openrouter_models())}; spend budget for this process "
          f"${cfg.openrouter.budget_usd:.2f}", file=sys.stderr, flush=True)
    return 0


def spend_note() -> str | None:
    """The spend guard's stop reason in this process, if it has stopped."""
    from . import openrouter
    led = openrouter._LEDGER
    return led.stop_reason if led is not None else None


def cmd_run(args) -> int:
    try:
        cfg = load_config(args.config)
    except (ConfigError, OSError) as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    return play(cfg, args, trial=None)


def cmd_trial(args) -> int:
    try:
        cfg = trial_config(load_raw(args.config), args.kind, args.test, args.reference)
    except (ConfigError, OSError) as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    trial = {"kind": args.kind, "test_model": args.test, "reference_model": args.reference}
    return play(cfg, args, trial=trial)


def do_preflight(cfg, client) -> int:
    from .preflight import failures, format_checks, run_preflight
    print("preflight: one real mole discussion call and one real vote call per model ...",
          file=sys.stderr, flush=True)
    checks = run_preflight(cfg, client)
    print(format_checks(checks), file=sys.stderr)
    if cfg.openrouter_models():
        from . import openrouter
        led = openrouter._LEDGER
        if led is not None:
            print(f"preflight: OpenRouter billed ${led.billed_usd:.4f} so far in this process "
                  f"(budget ${led.budget_usd or 0:.2f})", file=sys.stderr)
    bad = failures(checks)
    for c in bad:
        what = "blocked by its safety filter" if c.status == "blocked" else "erroring"
        print(f"preflight: {c.model} is {what} on both tries ({c.phase} call).", file=sys.stderr)
    return 2 if bad else 0


def play(cfg, args, trial) -> int:
    out = Path(args.out)
    if openrouter_gate(cfg, args, args.mock) != 0:
        return 2
    if args.mock:
        llm = MockLLM(args.seed)
    else:
        llm = make_client(cfg)
        if not args.no_preflight:
            if do_preflight(cfg, llm) != 0:
                if not args.force:
                    print("refusing to start (use --force to play anyway, --no-preflight to skip the check)",
                          file=sys.stderr)
                    return 2
                print("--force: starting anyway", file=sys.stderr)
    out.mkdir(parents=True, exist_ok=True)
    game_id = new_game_id(out, args.seed)               # `-2`, `-3`, ... for two games in the same second
    log_path = out / f"{game_id}.jsonl"
    renderer = None
    if args.watch:
        from .live import Renderer, want_color
        renderer = Renderer(args.view, color=want_color(sys.stdout, args.no_color))
        progress = None
    else:
        progress = (lambda m: print(m, file=sys.stderr, flush=True))
    game = Game(cfg, llm, args.seed, game_id=game_id, log_path=log_path, progress=progress, trial=trial,
                on_event=renderer.feed if renderer else None,
                raw=None if args.no_raw else RawLog(log_path), provenance=code_fingerprint())
    from .openrouter import SpendStop
    try:
        game.run()
    except SpendStop as e:
        game.log.close()
        print(f"\nSTOPPED: {e}. Game {game_id} was cut off mid-way: it is not in {out / 'index.jsonl'} "
              f"and was not finished with fallback moves (its partial log: {log_path}).")
        return 3
    events = game.log.events
    md_path, _ = save_game(game, out, log_path)
    end = game.result
    print(f"\n{game_id}: {end['winner']} win ({end['reason']}) after {end['rounds']} rounds")
    print(f"log: {log_path}\ntranscript: {md_path}\nindex: {out / 'index.jsonl'}\n"
          + (f"raw: {game.raw.final_path}\n" if game.raw is not None and game.raw.final_path else ""))
    if not (renderer and renderer.view == "audience"):      # the audience view already printed it
        print(token_report(events))
    note = spend_note() if not args.mock and cfg.openrouter_models() else None
    if note:
        print(f"\nnote: {note} (reached on this game's last paid calls; the game itself finished).")
    return 0


def cmd_batch(args) -> int:
    """Play seeds seed .. seed+games-1 in this process (SPEC section 2, "batch")."""
    from .batch import (BatchState, finished_seeds, game_line, resume_command, run_batch, summary_table,
                        totals_line)
    try:
        cfg = load_config(args.config)
    except (ConfigError, OSError) as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    if args.games < 1 or args.parallel_games < 1:
        print("batch: --games and --parallel-games must be at least 1", file=sys.stderr)
        return 2
    if not (0 <= args.max_fallback_share <= 1):
        print("batch: --max-fallback-share must be between 0 and 1", file=sys.stderr)
        return 2
    if openrouter_gate(cfg, args, args.mock) != 0:
        return 2
    out = Path(args.out)
    seeds = list(range(args.seed, args.seed + args.games))
    done_before = finished_seeds(out / "index.jsonl", args.name)
    skipped = [s for s in seeds if s in done_before]
    state = BatchState(pending=[s for s in seeds if s not in done_before])
    print(f"batch {args.name}: seeds {seeds[0]}..{seeds[-1]} with {args.config}, "
          f"{args.parallel_games} at a time{', mock model' if args.mock else ''}; out {out}", flush=True)
    if skipped:
        print(f"skipping {len(skipped)} seed(s) already finished in this batch: "
              f"{', '.join(map(str, skipped))}", flush=True)
    if not state.pending:
        print("nothing to play: every seed is finished.")
        return 0
    if not args.mock and not args.no_preflight:
        if do_preflight(cfg, make_client(cfg)) != 0:
            if not args.force:
                print("refusing to start (use --force to play anyway, --no-preflight to skip the check)",
                      file=sys.stderr)
                return 2
            print("--force: starting anyway", file=sys.stderr)

    def client_for(seed):
        # One client per game: each ClaudeCLI bounds its own calls by max_parallel_calls.
        return MockLLM(seed) if args.mock else make_client(cfg)

    total = len(state.pending)

    def on_start(seed, game_id):
        print(f"start seed {seed}: {game_id}", file=sys.stderr, flush=True)

    def on_end(g, st):
        print(game_line(g, len(st.done), total), flush=True)
        print(totals_line(st.done), flush=True)

    t0 = time.monotonic()
    try:
        asyncio.run(run_batch(cfg, name=args.name, state=state, parallel=args.parallel_games, out=out,
                              client_for=client_for, max_share=args.max_fallback_share,
                              on_start=on_start, on_end=on_end, raw=not args.no_raw,
                              provenance=code_fingerprint(),
                              spend_stop=spend_note if not args.mock and cfg.openrouter_models() else (lambda: None)))
    except KeyboardInterrupt:
        fin = sorted(g.seed for g in state.done if not g.spoiled)
        cut = sorted(state.running)
        print(f"\ninterrupted after {time.monotonic() - t0:.1f}s.")
        print(f"finished this run: {', '.join(map(str, fin)) or 'none'}"
              + (f"; cut off (will be replayed): {', '.join(map(str, cut))}" if cut else ""))
        if state.done:
            print("\n" + summary_table(state.done))
        print(f"\nresume with:\n  {resume_command(args)}")
        return 130
    print(f"\nbatch {args.name}: {len(state.done)} game(s) played in {time.monotonic() - t0:.1f}s"
          + (f", {len(skipped)} skipped" if skipped else ""))
    if state.done:
        print("\n" + summary_table(state.done))
    if state.stopped:
        left = sorted(state.pending)
        print(f"\nSTOPPED: {state.stop_reason}.")
        if state.cut:
            print(f"cut off by the spend guard, not indexed (will be replayed): "
                  f"{', '.join(map(str, sorted(state.cut)))}")
        if left:
            print(f"not started: {', '.join(map(str, left))}")
        print(f"resume with:\n  {resume_command(args)}")
        return 1 if state.errors else 3
    return 0


def cmd_transcript(args) -> int:
    events = read_log(args.log)
    text = render(events)
    if args.o:
        Path(args.o).write_text(text, encoding="utf-8")
        print(f"wrote {args.o}")
    else:
        sys.stdout.write(text)
    return 0


def cmd_usage(args) -> int:
    print(token_report(read_log(args.log)))
    return 0


def cmd_report(args) -> int:
    """The Markdown pilot report for one batch (SPEC section 2, "report")."""
    from .report import build_report, load_batch
    out = Path(args.out)
    logs = load_batch(out, args.batch)
    if not logs.known:
        print(f"report: no batch named {args.batch!r} in {out / 'index.jsonl'} (and no log of it in {out})",
              file=sys.stderr)
        return 2
    if not logs.games:
        ex = logs.excluded
        print(f"report: batch {args.batch!r} has no finished, unspoiled games yet ({len(ex.spoiled)} spoiled, "
              f"{len(ex.unfinished)} unfinished, {len(ex.missing)} with an unreadable log)", file=sys.stderr)
        return 2
    text = build_report(logs.games, args.batch, logs.excluded)
    sys.stdout.write(text)
    if args.write:
        path = Path(args.write)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path}", file=sys.stderr)
    return 0


def cmd_watch(args) -> int:
    from .live import Renderer, newest_log, want_color, watch
    if args.latest:
        path = newest_log(args.out)
    elif args.log:
        path = Path(args.log)
    else:
        print("watch: give a log path or --latest", file=sys.stderr)
        return 2
    if not path.exists():
        print(f"watch: {path} not found", file=sys.stderr)
        return 2
    r = Renderer(args.view, color=want_color(sys.stdout, args.no_color), pace=args.pace)
    watch(path, r, from_start=True if args.from_start else None)
    return 0


def cmd_view(args) -> int:
    from .viewer import run_view
    return run_view(args)


def cmd_preflight(args) -> int:
    try:
        cfg = load_config(args.config)
    except (ConfigError, OSError) as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    if openrouter_gate(cfg, args, False) != 0:
        return 2
    return do_preflight(cfg, make_client(cfg))


def cmd_solve(args) -> int:
    from .solver import format_solve, simulate_deals
    try:
        cfg = config_from_dict(parse_set(load_raw(args.config), args.set))
    except (ConfigError, OSError) as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    print(format_solve(simulate_deals(cfg, args.deals, args.rounds, args.seed), cfg))
    return 0


def cmd_bots(args) -> int:
    from .bots import run_sweep
    t0 = time.monotonic()
    try:
        results = run_sweep(load_raw(args.config), games=args.games, seed=args.seed, sets=args.set,
                            sweeps=args.sweep, out_dir=args.out,
                            bot_kw={"crew": args.crew, "crew_skill": args.crew_skill, "moles": args.moles,
                                    "mole_cards": args.mole_cards, "eject_threshold": args.eject_threshold,
                                    "approve_threshold": args.approve_threshold,
                                    "mole_approve": args.mole_approve})
    except (ConfigError, ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    total = sum(r["games"] for r in results)
    wall = time.monotonic() - t0
    # v0.4 bot options are named only when away from their defaults (the line is otherwise unchanged).
    v04_opts = [f"{name} {val}" for name, val, default in
                (("eject threshold", args.eject_threshold, 0.5), ("approve threshold", args.approve_threshold, 0.45),
                 ("mole approve", args.mole_approve, "blend")) if val != default]
    print(f"\n{total} games in {wall:.1f}s ({total / wall:.1f} games/s). crew {args.crew} skill {args.crew_skill}, "
          f"moles {args.moles}, mole cards {args.mole_cards}, "
          + "".join(f"{o}, " for o in v04_opts)
          + f"seeds {args.seed}..{args.seed + args.games - 1}"
          + (f". Wrote {args.out}/bots-cells.jsonl and bots-games.jsonl" if args.out else ""))
    return 0


def cmd_fingerprint(args) -> int:
    """Print the code hash and per-file hashes; with --check, compare a log's stamp (docs/RAWLOG.md).
    Exit 0 equal, 1 different, 2 the log has no stamp (or cannot be read)."""
    fp = code_fingerprint()
    print(f"code_hash {fp['code_hash']}")
    for rel, h in fp["code_files"].items():
        print(f"  {h}  {rel}")
    if not args.check:
        return 0
    import json
    start = None
    try:
        with open(args.check, encoding="utf-8") as f:
            for line in f:
                try:
                    ev = json.loads(line)
                except ValueError:
                    break
                if isinstance(ev, dict) and ev.get("type") == "game_start":
                    start = ev
                    break
    except OSError as e:
        print(f"check: cannot read {args.check}: {e.strerror}", file=sys.stderr)
        return 2
    stamped = (start or {}).get("code_hash")
    if not stamped:
        print(f"check: {args.check} has no code stamp (played before stamping, or by a direct Game)")
        return 2
    if stamped == fp["code_hash"]:
        print(f"check: {args.check} was played by this code (code_hash {stamped})")
        return 0
    print(f"check: {args.check} was played by different code (stamped {stamped})")
    old = start.get("code_files") or {}
    for rel in sorted(set(old) | set(fp["code_files"])):
        if old.get(rel) != fp["code_files"].get(rel):
            print(f"  differs: {rel}")
    return 1


def cmd_examples(args) -> int:
    from .examples import render_examples
    text = render_examples(args.config, args.seed)
    Path(args.o).write_text(text, encoding="utf-8")
    print(f"wrote {args.o}")
    return 0


def cmd_probes(args) -> int:
    from .probes import COMMANDS
    return COMMANDS[args.probes_cmd](args)


def cmd_moves(args) -> int:
    from .moves import COMMANDS
    return COMMANDS[args.moves_cmd](args)


def _game_flags(p):
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--mock", action="store_true", help="use the mock model (no model calls, no preflight)")
    p.add_argument("--out", default="games")
    p.add_argument("--watch", action="store_true", help="print the game as it is played instead of progress lines")
    p.add_argument("--view", choices=["audience", "table"], default="audience")
    p.add_argument("--no-color", action="store_true")
    p.add_argument("--no-preflight", action="store_true", help="skip the preflight check")
    p.add_argument("--force", action="store_true", help="start even if the preflight fails")
    p.add_argument("--no-raw", action="store_true", help="do not write the raw sidecar file (docs/RAWLOG.md)")
    p.add_argument("--budget-usd", type=float, default=None,
                   help="OpenRouter spend budget for this process (overrides [openrouter] budget_usd)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python3.11 -m inside_job", description="Inside Job game engine")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="play one game")
    r.add_argument("--config", required=True)
    _game_flags(r)
    r.set_defaults(fn=cmd_run)
    tr = sub.add_parser("trial", help="play one benchmark trial (test model vs reference model)")
    tr.add_argument("--kind", required=True, choices=["mole", "crew"])
    tr.add_argument("--test", required=True, help="model id under test")
    tr.add_argument("--reference", required=True, help="reference model id")
    tr.add_argument("--config", default="config/bench.toml")
    _game_flags(tr)
    tr.set_defaults(fn=cmd_trial)
    bt = sub.add_parser("batch", help="play many seeds in one process (resume, parallel games, stop rule)")
    bt.add_argument("--config", required=True)
    bt.add_argument("--name", required=True, help="batch name, recorded on every game; used to resume")
    bt.add_argument("--games", type=int, required=True)
    bt.add_argument("--seed", type=int, required=True, help="first seed; plays seed .. seed+games-1")
    bt.add_argument("--parallel-games", type=int, default=1,
                    help="games at once (each keeps its own max_parallel_calls)")
    bt.add_argument("--out", default="games")
    bt.add_argument("--mock", action="store_true", help="use the mock model (no model calls, no preflight)")
    bt.add_argument("--no-preflight", action="store_true", help="skip the preflight check")
    bt.add_argument("--force", action="store_true", help="start even if the preflight fails")
    bt.add_argument("--max-fallback-share", type=float, default=0.10,
                    help="stop starting games once a finished game has fallbacks/calls above this")
    bt.add_argument("--no-raw", action="store_true", help="do not write raw sidecar files (docs/RAWLOG.md)")
    bt.add_argument("--budget-usd", type=float, default=None,
                    help="OpenRouter spend budget for this process, all games together "
                         "(overrides [openrouter] budget_usd)")
    bt.set_defaults(fn=cmd_batch)
    rp = sub.add_parser("report", help="Markdown report on a batch's finished games (reads logs only)")
    rp.add_argument("--batch", required=True, help="batch name, as given to `batch --name`")
    rp.add_argument("--out", default="games", help="directory holding index.jsonl and the logs")
    rp.add_argument("--write", default=None, metavar="FILE", help="also save the report here")
    rp.set_defaults(fn=cmd_report)
    t = sub.add_parser("transcript", help="render a log as Markdown")
    t.add_argument("log")
    t.add_argument("-o", help="output file (default stdout)")
    t.set_defaults(fn=cmd_transcript)
    u = sub.add_parser("usage", help="print the token report for a log")
    u.add_argument("log")
    u.set_defaults(fn=cmd_usage)
    w = sub.add_parser("watch", help="follow a game log as it is written (or replay a finished one)")
    w.add_argument("log", nargs="?")
    w.add_argument("--latest", action="store_true", help="the newest log in --out (waits for one)")
    w.add_argument("--out", default="games")
    w.add_argument("--view", choices=["audience", "table"], default="audience")
    w.add_argument("--pace", type=float, default=0.0, help="at least this many seconds between turns")
    w.add_argument("--from-start", action="store_true", help="print from the first event (default when over)")
    w.add_argument("--no-color", action="store_true")
    w.set_defaults(fn=cmd_watch)
    vw = sub.add_parser("view", help="browser viewer: replay a game or follow one live (127.0.0.1 only)")
    vw.add_argument("log", nargs="?", help="log path or game id (default: open the game list)")
    vw.add_argument("--latest", action="store_true", help="open the newest log in --out")
    vw.add_argument("--out", default="games", help="folder holding the logs and index.jsonl")
    vw.add_argument("--port", type=int, default=8765)
    vw.add_argument("--no-open", action="store_true", help="do not open a browser")
    vw.add_argument("--view", choices=["audience", "table"], default="audience")
    vw.add_argument("--export", metavar="FILE.html", default=None,
                    help="write one self-contained HTML file for the game and exit (no server)")
    vw.set_defaults(fn=cmd_view)
    pf = sub.add_parser("preflight", help="two real calls (discussion, vote) per model in the cast; exit 2 if any is blocked or erroring")
    pf.add_argument("--config", default="config/default.toml")
    pf.add_argument("--budget-usd", type=float, default=None,
                    help="OpenRouter spend budget (overrides [openrouter] budget_usd)")
    pf.set_defaults(fn=cmd_preflight)
    sv = sub.add_parser("solve", help="ideal-reasoner balance check: clues only, no play")
    sv.add_argument("--config", default="config/default.toml")
    sv.add_argument("--deals", type=int, default=400)
    sv.add_argument("--rounds", type=int, default=4)
    sv.add_argument("--seed", type=int, default=0)
    sv.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="override a [game] key")
    sv.set_defaults(fn=cmd_solve)
    b = sub.add_parser("bots", help="scripted-bot games for tuning the dials")
    b.add_argument("--games", type=int, default=500)
    b.add_argument("--seed", type=int, default=1)
    b.add_argument("--config", default="config/default.toml")
    b.add_argument("--crew", default="logician", choices=["logician"])
    b.add_argument("--crew-skill", type=float, default=0.7)
    b.add_argument("--moles", default="smart", choices=["always", "never", "smart", "hold1"])
    b.add_argument("--mole-cards", default="decoy", choices=["none", "decoy"])
    b.add_argument("--eject-threshold", type=float, default=0.5,
                   help="v0.4 vote_nobody: crew vote their top suspect only at this belief or above")
    b.add_argument("--approve-threshold", type=float, default=0.45,
                   help="v0.4 team_approval: approve when P(a mole on the team) is below this")
    b.add_argument("--mole-approve", default="blend", choices=["blend", "team"],
                   help="v0.4 team_approval: moles approve like a public-evidence logician, or iff a mole is on the team")
    b.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    b.add_argument("--sweep", action="append", default=[], metavar="KEY=V1,V2",
                   help="a [game] key, or bot.eject_threshold / bot.approve_threshold")
    b.add_argument("--out", default=None, help="write per-cell and per-game rows here (default: nothing)")
    b.set_defaults(fn=cmd_bots)
    fp = sub.add_parser("fingerprint", help="print the code hash; --check a log's stamp against this code")
    fp.add_argument("--check", default=None, metavar="LOG", help="exit 0 same code, 1 different, 2 no stamp")
    fp.set_defaults(fn=cmd_fingerprint)
    ex = sub.add_parser("examples", help="regenerate docs/example_prompts.md from a scripted mock game")
    ex.add_argument("--config", default="config/default.toml")
    ex.add_argument("--seed", type=int, default=4)
    ex.add_argument("-o", default="docs/example_prompts.md")
    ex.set_defaults(fn=cmd_examples)
    pr = sub.add_parser("probes", help="Read probes: freeze logged vote turns, replay them to a model, score (docs/PROBES.md)")
    pr.set_defaults(fn=cmd_probes)
    psub = pr.add_subparsers(dest="probes_cmd", required=True)
    pb = psub.add_parser("build", help="freeze a probe set from finished games (never overwrites)")
    pb.add_argument("--batch", action="append", required=True, help="batch name; repeat for several")
    pb.add_argument("--n", type=int, required=True)
    pb.add_argument("--seed", type=int, required=True)
    pb.add_argument("--out", required=True, metavar="FILE.jsonl")
    pb.add_argument("--games", default="games", help="directory holding index.jsonl and the logs (read only)")
    pv = psub.add_parser("verify", help="recompute every probe_id and the file hash; exit 1 on a mismatch")
    pv.add_argument("--set", required=True)
    pn = psub.add_parser("run", help="replay the probes to one model, one call each (resumes)")
    pn.add_argument("--set", required=True)
    pn.add_argument("--model", required=True)
    pn.add_argument("--effort", default="", help="--effort level; empty = flag not passed")
    pn.add_argument("--max-thinking-tokens", type=int, default=-1)
    pn.add_argument("--parallel", type=int, default=2)
    pn.add_argument("--limit", type=int, default=None, help="only the first N probes in set order")
    pn.add_argument("--timeout", type=float, default=240)
    pn.add_argument("--mock", action="store_true", help="use the mock model (no model calls)")
    pn.add_argument("--runs", default="probes/runs", help="runs directory")
    ps = psub.add_parser("score", help="Markdown scores of every run of a set")
    ps.add_argument("--set", required=True)
    ps.add_argument("--runs", default="probes/runs")
    ps.add_argument("--write", default=None, metavar="FILE.md")
    from .moves import add_subcommands as moves_subcommands
    mv = sub.add_parser("moves", help="The one-move test: freeze mole moments, run speakers and listeners, score "
                                      "(docs/MOVES.md)")
    mv.set_defaults(fn=cmd_moves)
    moves_subcommands(mv)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
