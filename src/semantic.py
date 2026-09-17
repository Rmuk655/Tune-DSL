"""
Tune DSL — Semantic analysis.

Takes a Program AST and produces a SemanticResult:
  - tempo_bpm: float
  - instruments: {name: waveform}
  - note_events: {pattern_name: [NoteEvent, ...]}   (repeat unrolled, flat)
  - plays: [(instrument_name, pattern_name), ...]

A NoteEvent is (freq_hz | None, start_beat, duration_beats, waveform).
freq_hz is None for a rest. Chords expand into multiple simultaneous
NoteEvents sharing the same start_beat.

This stage evaluates all expressions down to plain floats (constant
folding over `let` variables) — there is no runtime variable state in
Tune v1, so everything resolvable now, is resolved now.
"""

from dataclasses import dataclass
from typing import Optional, List, Dict, Tuple

from ast_nodes import (
    Program, TempoStmt, InstrumentDecl, LetStmt, PatternDecl, PlayStmt,
    NoteStmt, ChordStmt, RestStmt, RepeatStmt, EffectStmt, SlideStmt, StrumStmt,
    Num, Ident, Pitch, BinOp, UnaryOp,
)
from pitch import pitch_to_freq, PitchError

VALID_WAVEFORMS = {"sine", "square", "saw", "triangle", "pulse", "noise"}
EFFECT_ARITY = {"lowpass": 1, "delay": 2, "highpass": 1, "distortion": 1, "tremolo": 2}
DEFAULT_STRUM_DELAY_SEC = 0.02


class SemanticError(Exception):
    def __init__(self, msg, line=0):
        super().__init__(f"SemanticError at line {line}: {msg}" if line else f"SemanticError: {msg}")
        self.line = line


@dataclass
class NoteEvent:
    freq_hz: Optional[float]   # None == rest
    start_beat: float
    duration_beats: float
    waveform: str
    velocity: float = 1.0        # 0..1 volume multiplier, default full volume
    slide_from_freq: Optional[float] = None  # if set, glide from this freq to freq_hz
    attack_sec: Optional[float] = None       # None -> backend's default envelope
    release_sec: Optional[float] = None      # None -> backend's default envelope


@dataclass
class SemanticResult:
    tempo_bpm: float
    instruments: Dict[str, str]
    note_events: Dict[str, List[NoteEvent]]
    plays: List[Tuple[str, str]]
    effects: List[Tuple[str, List[float]]] = None
    dce_eliminated: int = 0

    def __post_init__(self):
        if self.effects is None:
            self.effects = []


class Analyzer:
    def __init__(self, program: Program):
        self.program = program
        self.let_vars: Dict[str, float] = {}
        self.instruments: Dict[str, str] = {}
        self.instrument_envelopes: Dict[str, Tuple[Optional[float], Optional[float]]] = {}
        self.patterns: Dict[str, PatternDecl] = {}
        self.tempo_bpm: Optional[float] = None
        self.plays: List[Tuple[str, str]] = []
        self.effects: List[Tuple[str, List[float]]] = []
        self.dce_eliminated = 0

    # -- expression evaluation (constant folding) --

    def _eval(self, node) -> float:
        if isinstance(node, Num):
            return float(node.value)
        if isinstance(node, Ident):
            if node.name not in self.let_vars:
                raise SemanticError(f"undefined variable {node.name!r}", node.line)
            return self.let_vars[node.name]
        if isinstance(node, UnaryOp):
            val = self._eval(node.operand)
            if node.op == "-":
                return -val
            raise SemanticError(f"unknown unary operator {node.op!r}", node.line)
        if isinstance(node, BinOp):
            l = self._eval(node.left)
            r = self._eval(node.right)
            if node.op == "+":
                return l + r
            if node.op == "-":
                return l - r
            if node.op == "*":
                return l * r
            if node.op == "/":
                if r == 0:
                    raise SemanticError("division by zero", node.line)
                return l / r
            raise SemanticError(f"unknown operator {node.op!r}", node.line)
        raise SemanticError(f"cannot evaluate expression node {type(node).__name__}")

    def _resolve_pitch(self, pitch: Pitch) -> float:
        try:
            return pitch_to_freq(pitch.name)
        except PitchError as e:
            raise SemanticError(str(e), pitch.line)

    # -- pass 1: collect top-level declarations --

    def _collect_decls(self):
        for stmt in self.program.statements:
            if isinstance(stmt, TempoStmt):
                bpm = self._eval(stmt.bpm)
                if bpm <= 0:
                    raise SemanticError("tempo must be positive", stmt.line)
                self.tempo_bpm = bpm
            elif isinstance(stmt, InstrumentDecl):
                if stmt.waveform not in VALID_WAVEFORMS:
                    raise SemanticError(
                        f"unknown waveform {stmt.waveform!r} "
                        f"(expected one of {sorted(VALID_WAVEFORMS)})",
                        stmt.line,
                    )
                if stmt.name in self.instruments:
                    raise SemanticError(f"instrument {stmt.name!r} redeclared", stmt.line)
                self.instruments[stmt.name] = stmt.waveform
                attack_sec = self._eval(stmt.attack) if stmt.attack is not None else None
                release_sec = self._eval(stmt.release) if stmt.release is not None else None
                if attack_sec is not None and attack_sec < 0:
                    raise SemanticError("envelope attack must be non-negative", stmt.line)
                if release_sec is not None and release_sec < 0:
                    raise SemanticError("envelope release must be non-negative", stmt.line)
                self.instrument_envelopes[stmt.name] = (attack_sec, release_sec)
            elif isinstance(stmt, LetStmt):
                if stmt.name in self.let_vars:
                    raise SemanticError(f"variable {stmt.name!r} redeclared", stmt.line)
                self.let_vars[stmt.name] = self._eval(stmt.expr)
            elif isinstance(stmt, PatternDecl):
                if stmt.name in self.patterns:
                    raise SemanticError(f"pattern {stmt.name!r} redeclared", stmt.line)
                self.patterns[stmt.name] = stmt
            elif isinstance(stmt, PlayStmt):
                self.plays.append((stmt.instrument, stmt.pattern, stmt.line))
            elif isinstance(stmt, EffectStmt):
                if stmt.name not in EFFECT_ARITY:
                    raise SemanticError(
                        f"unknown effect {stmt.name!r} "
                        f"(expected one of {sorted(EFFECT_ARITY)})", stmt.line,
                    )
                expected = EFFECT_ARITY[stmt.name]
                if len(stmt.args) != expected:
                    raise SemanticError(
                        f"effect {stmt.name!r} expects {expected} argument(s), "
                        f"got {len(stmt.args)}", stmt.line,
                    )
                values = [self._eval(a) for a in stmt.args]
                self.effects.append((stmt.name, values))
            else:
                raise SemanticError(f"unexpected top-level node {type(stmt).__name__}")

        if self.tempo_bpm is None:
            self.tempo_bpm = 120.0  # sensible default if not specified

    # -- pass 2: flatten each pattern body into NoteEvents --

    def _resolve_velocity(self, velocity_expr, line):
        if velocity_expr is None:
            return 1.0
        v = self._eval(velocity_expr)
        if v < 0:
            raise SemanticError("velocity must be non-negative", line)
        return v

    def _flatten_body(self, body, start_beat: float, default_waveform: str,
                       attack_sec=None, release_sec=None, last_freq=None):
        """Returns (events, end_beat, last_freq). Applies one real,
        provably-safe dead-code elimination: a note/chord with velocity 0
        contributes exactly zero to the final mix (multiplied by 0 in
        every backend), so its synthesis is unobservable and safe to
        elide entirely -- this is the same "dead store elimination"
        reasoning a compiler applies to a write whose value is provably
        never used, just applied at the DSL's semantic level instead of
        on machine code. Timing bookkeeping (t += dur) is NOT eliminated
        -- it's a necessary side effect (later notes' start times depend
        on it), exactly like a classic DCE pass keeps a side-effecting
        statement even when its result is discarded.

        last_freq tracks the most recently emitted pitched event's
        frequency, threaded through (including across repeat unrolling),
        so `slide` can find its start frequency: the frequency of
        whatever note immediately preceded it in performance order.
        """
        events = []
        t = start_beat
        for stmt in body:
            if isinstance(stmt, NoteStmt):
                freq = self._resolve_pitch(stmt.pitch)
                dur = self._eval(stmt.duration)
                if dur <= 0:
                    raise SemanticError("note duration must be positive", stmt.line)
                vel = self._resolve_velocity(stmt.velocity, stmt.line)
                if vel > 0:
                    events.append(NoteEvent(freq, t, dur, default_waveform, vel,
                                             attack_sec=attack_sec, release_sec=release_sec))
                else:
                    self.dce_eliminated += 1
                last_freq = freq
                t += dur
            elif isinstance(stmt, ChordStmt):
                dur = self._eval(stmt.duration)
                if dur <= 0:
                    raise SemanticError("chord duration must be positive", stmt.line)
                vel = self._resolve_velocity(stmt.velocity, stmt.line)
                chord_last_freq = last_freq
                for p in stmt.pitches:
                    freq = self._resolve_pitch(p)
                    chord_last_freq = freq
                    if vel > 0:
                        events.append(NoteEvent(freq, t, dur, default_waveform, vel,
                                                 attack_sec=attack_sec, release_sec=release_sec))
                    else:
                        self.dce_eliminated += 1
                last_freq = chord_last_freq
                t += dur
            elif isinstance(stmt, RestStmt):
                dur = self._eval(stmt.duration)
                if dur <= 0:
                    raise SemanticError("rest duration must be positive", stmt.line)
                events.append(NoteEvent(None, t, dur, default_waveform))
                t += dur
            elif isinstance(stmt, SlideStmt):
                if last_freq is None:
                    raise SemanticError(
                        "slide requires a preceding pitched note/chord/slide "
                        "in the same pattern to glide from", stmt.line,
                    )
                freq_to = self._resolve_pitch(stmt.pitch)
                dur = self._eval(stmt.duration)
                if dur <= 0:
                    raise SemanticError("slide duration must be positive", stmt.line)
                vel = self._resolve_velocity(stmt.velocity, stmt.line)
                if vel > 0:
                    events.append(NoteEvent(freq_to, t, dur, default_waveform, vel,
                                             slide_from_freq=last_freq,
                                             attack_sec=attack_sec, release_sec=release_sec))
                else:
                    self.dce_eliminated += 1
                last_freq = freq_to
                t += dur
            elif isinstance(stmt, StrumStmt):
                dur = self._eval(stmt.duration)
                if dur <= 0:
                    raise SemanticError("strum duration must be positive", stmt.line)
                delay_sec = self._eval(stmt.delay) if stmt.delay is not None else DEFAULT_STRUM_DELAY_SEC
                if delay_sec < 0:
                    raise SemanticError("strum delay must be non-negative", stmt.line)
                delay_beats = delay_sec * (self.tempo_bpm / 60.0)
                vel = self._resolve_velocity(stmt.velocity, stmt.line)
                strum_last_freq = last_freq
                for i, p in enumerate(stmt.pitches):
                    freq = self._resolve_pitch(p)
                    strum_last_freq = freq
                    if vel > 0:
                        events.append(NoteEvent(freq, t + i * delay_beats, dur, default_waveform, vel,
                                                 attack_sec=attack_sec, release_sec=release_sec))
                    else:
                        self.dce_eliminated += 1
                last_freq = strum_last_freq
                # timing for what follows advances by the strum's nominal
                # duration only (matches how a chord advances timing) --
                # individual notes may ring slightly past that into the
                # next event, which is how a real strum's tail behaves
                t += dur
            elif isinstance(stmt, RepeatStmt):
                count = self._eval(stmt.count)
                if count != int(count) or count < 0:
                    raise SemanticError("repeat count must be a non-negative integer", stmt.line)
                for _ in range(int(count)):
                    sub_events, t, last_freq = self._flatten_body(
                        stmt.body, t, default_waveform, attack_sec, release_sec, last_freq,
                    )
                    events.extend(sub_events)
            else:
                raise SemanticError(f"unexpected pattern-body node {type(stmt).__name__}")
        return events, t, last_freq

    def analyze(self) -> SemanticResult:
        self._collect_decls()

        # validate plays reference known instruments/patterns, and determine
        # which waveform each pattern's events should render with (a pattern
        # could in principle be played by more than one instrument; here we
        # flatten once per (instrument, pattern) pair using that instrument's
        # waveform, keyed by pattern name -- good enough for v1's single-play
        # common case and still correct for multiple plays of a pattern with
        # the SAME instrument)
        note_events: Dict[str, List[NoteEvent]] = {}
        clean_plays: List[Tuple[str, str]] = []
        for instrument, pattern, line in self.plays:
            if instrument not in self.instruments:
                raise SemanticError(f"play references undeclared instrument {instrument!r}", line)
            if pattern not in self.patterns:
                raise SemanticError(f"play references undeclared pattern {pattern!r}", line)
            clean_plays.append((instrument, pattern))
            if pattern not in note_events:
                waveform = self.instruments[instrument]
                attack_sec, release_sec = self.instrument_envelopes.get(instrument, (None, None))
                events, _, _ = self._flatten_body(
                    self.patterns[pattern].body, 0.0, waveform, attack_sec, release_sec,
                )
                note_events[pattern] = events

        return SemanticResult(
            tempo_bpm=self.tempo_bpm,
            instruments=self.instruments,
            note_events=note_events,
            plays=clean_plays,
            effects=self.effects,
            dce_eliminated=self.dce_eliminated,
        )


def analyze(program: Program) -> SemanticResult:
    return Analyzer(program).analyze()