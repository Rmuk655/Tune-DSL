"""
Tune DSL — Lexer

Converts source text into a flat list of Tokens.
"""

from dataclasses import dataclass
from enum import Enum, auto


class TokType(Enum):
    # literals
    INT = auto()
    FLOAT = auto()
    IDENT = auto()
    PITCH = auto()       # e.g. C4, Ds5, Bb3  -> pitch class + octave

    # keywords
    TEMPO = auto()
    INSTRUMENT = auto()
    PATTERN = auto()
    NOTE = auto()
    CHORD = auto()
    REST = auto()
    REPEAT = auto()
    PLAY = auto()
    LET = auto()
    EFFECT = auto()
    SLIDE = auto()
    STRUM = auto()
    ENVELOPE = auto()

    # symbols
    LBRACE = auto()      # {
    RBRACE = auto()      # }
    LBRACKET = auto()     # [
    RBRACKET = auto()     # ]
    LPAREN = auto()        # (
    RPAREN = auto()        # )
    COLON = auto()        # :
    COMMA = auto()        # ,
    SLASH = auto()        # /
    PLUS = auto()         # +
    MINUS = auto()        # -
    STAR = auto()         # *
    ASSIGN = auto()        # =
    AT = auto()             # @  (velocity marker: note C4 : 1/4 @ 0.7)

    NEWLINE = auto()
    EOF = auto()


KEYWORDS = {
    "tempo": TokType.TEMPO,
    "instrument": TokType.INSTRUMENT,
    "pattern": TokType.PATTERN,
    "note": TokType.NOTE,
    "chord": TokType.CHORD,
    "rest": TokType.REST,
    "repeat": TokType.REPEAT,
    "play": TokType.PLAY,
    "let": TokType.LET,
    "effect": TokType.EFFECT,
    "slide": TokType.SLIDE,
    "strum": TokType.STRUM,
    "envelope": TokType.ENVELOPE,
}

PITCH_CLASSES = {"A", "B", "C", "D", "E", "F", "G"}


@dataclass
class Token:
    type: TokType
    value: object
    line: int
    col: int

    def __repr__(self):
        return f"Token({self.type.name}, {self.value!r}, {self.line}:{self.col})"


class LexError(Exception):
    def __init__(self, msg, line, col):
        super().__init__(f"LexError at {line}:{col}: {msg}")
        self.line = line
        self.col = col


class Lexer:
    def __init__(self, src: str):
        self.src = src
        self.pos = 0
        self.line = 1
        self.col = 1
        self.tokens = []

    def _peek(self, offset=0):
        p = self.pos + offset
        if p < len(self.src):
            return self.src[p]
        return None

    def _advance(self):
        ch = self.src[self.pos]
        self.pos += 1
        if ch == "\n":
            self.line += 1
            self.col = 1
        else:
            self.col += 1
        return ch

    def _add(self, type_, value, line, col):
        self.tokens.append(Token(type_, value, line, col))

    def _is_pitch_lookahead(self):
        """Decide if current position starts a PITCH token like C4, Ds5, Bb3.
        Pattern: [A-G] optional('s'|'b') digit  -- and NOT followed by more ident chars.
        """
        c = self._peek()
        if c is None or c.upper() not in PITCH_CLASSES:
            return False
        i = 1
        nxt = self._peek(i)
        if nxt in ("s", "b"):
            i += 1
            nxt = self._peek(i)
        if nxt is None or not nxt.isdigit():
            return False
        i += 1
        # consume all digits (octave could theoretically be multi-digit, keep simple: 1 digit)
        after = self._peek(i)
        if after is not None and (after.isalnum() or after == "_"):
            return False
        return True

    def tokenize(self):
        while self.pos < len(self.src):
            c = self._peek()

            if c in (" ", "\t", "\r"):
                self._advance()
                continue

            if c == "\n":
                line, col = self.line, self.col
                self._advance()
                self._add(TokType.NEWLINE, "\\n", line, col)
                continue

            if c == "#":
                while self._peek() is not None and self._peek() != "\n":
                    self._advance()
                continue

            line, col = self.line, self.col

            if c.isalpha() or c == "_":
                if self._is_pitch_lookahead():
                    text = self._advance()  # letter
                    if self._peek() in ("s", "b"):
                        text += self._advance()
                    text += self._advance()  # digit
                    self._add(TokType.PITCH, text, line, col)
                    continue
                text = self._advance()
                while self._peek() is not None and (self._peek().isalnum() or self._peek() == "_"):
                    text += self._advance()
                if text in KEYWORDS:
                    self._add(KEYWORDS[text], text, line, col)
                else:
                    self._add(TokType.IDENT, text, line, col)
                continue

            if c.isdigit():
                text = self._advance()
                while self._peek() is not None and self._peek().isdigit():
                    text += self._advance()
                is_float = False
                if self._peek() == "." and self._peek(1) is not None and self._peek(1).isdigit():
                    is_float = True
                    text += self._advance()
                    while self._peek() is not None and self._peek().isdigit():
                        text += self._advance()
                if is_float:
                    self._add(TokType.FLOAT, float(text), line, col)
                else:
                    self._add(TokType.INT, int(text), line, col)
                continue

            single = {
                "{": TokType.LBRACE, "}": TokType.RBRACE,
                "[": TokType.LBRACKET, "]": TokType.RBRACKET,
                ":": TokType.COLON, ",": TokType.COMMA,
                "/": TokType.SLASH, "+": TokType.PLUS,
                "-": TokType.MINUS, "*": TokType.STAR,
                "=": TokType.ASSIGN,
                "(": TokType.LPAREN, ")": TokType.RPAREN,
                "@": TokType.AT,
            }
            if c in single:
                self._advance()
                self._add(single[c], c, line, col)
                continue

            raise LexError(f"unexpected character {c!r}", line, col)

        self._add(TokType.EOF, None, self.line, self.col)
        return self.tokens


def tokenize(src: str):
    return Lexer(src).tokenize()