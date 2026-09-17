"""
Tune DSL — AST node definitions.

Kept as plain dataclasses (no behavior) so the parser, semantic analyzer,
and codegen stages can all import the same shapes without coupling.
"""

from dataclasses import dataclass, field
from typing import List, Union


# ---- expressions ----

@dataclass
class Num:
    value: Union[int, float]
    line: int = 0
    col: int = 0


@dataclass
class Ident:
    name: str
    line: int = 0
    col: int = 0


@dataclass
class Pitch:
    name: str  # e.g. "C4", "Cs4", "Bb3"
    line: int = 0
    col: int = 0


@dataclass
class BinOp:
    op: str          # '+' '-' '*' '/'
    left: object
    right: object
    line: int = 0
    col: int = 0


@dataclass
class UnaryOp:
    op: str          # '-'
    operand: object
    line: int = 0
    col: int = 0


# ---- top-level statements ----

@dataclass
class TempoStmt:
    bpm: object
    line: int = 0


@dataclass
class InstrumentDecl:
    name: str
    waveform: str
    attack: object = None     # expr (seconds) or None -> use default envelope
    release: object = None    # expr (seconds) or None -> use default envelope
    line: int = 0


@dataclass
class LetStmt:
    name: str
    expr: object
    line: int = 0


@dataclass
class PatternDecl:
    name: str
    body: List[object] = field(default_factory=list)
    line: int = 0


@dataclass
class PlayStmt:
    instrument: str
    pattern: str
    line: int = 0


# ---- pattern-body statements ----

@dataclass
class NoteStmt:
    pitch: Pitch
    duration: object
    velocity: object = None   # expr or None (defaults to 1.0 in semantic analysis)
    line: int = 0


@dataclass
class ChordStmt:
    pitches: List[Pitch]
    duration: object
    velocity: object = None
    line: int = 0


@dataclass
class RestStmt:
    duration: object
    line: int = 0


@dataclass
class RepeatStmt:
    count: object
    body: List[object] = field(default_factory=list)
    line: int = 0


@dataclass
class EffectStmt:
    name: str
    args: List[object] = field(default_factory=list)
    line: int = 0


@dataclass
class SlideStmt:
    pitch: Pitch
    duration: object
    velocity: object = None
    line: int = 0


@dataclass
class StrumStmt:
    pitches: List[Pitch]
    duration: object
    delay: object = None      # expr (seconds) or None -> default strum delay
    velocity: object = None
    line: int = 0


@dataclass
class Program:
    statements: List[object] = field(default_factory=list)