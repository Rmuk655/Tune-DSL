"""
Tune DSL — Parser

Recursive-descent parser: Tokens -> AST (see ast_nodes.py).

Grammar (informal, NEWLINE-terminated statements):

    program      := stmt*
    stmt         := tempo_stmt | instrument_decl | let_stmt
                  | pattern_decl | play_stmt | NEWLINE
    tempo_stmt   := TEMPO expr NEWLINE
    instrument_decl := INSTRUMENT IDENT ASSIGN IDENT NEWLINE
    let_stmt     := LET IDENT ASSIGN expr NEWLINE
    pattern_decl := PATTERN IDENT LBRACE NEWLINE* pattern_body RBRACE NEWLINE
    pattern_body := pattern_stmt*
    pattern_stmt := note_stmt | chord_stmt | rest_stmt | repeat_stmt
    note_stmt    := NOTE PITCH COLON expr NEWLINE
    chord_stmt   := CHORD LBRACKET PITCH (COMMA PITCH)* RBRACKET COLON expr NEWLINE
    rest_stmt    := REST COLON expr NEWLINE
    repeat_stmt  := REPEAT expr LBRACE NEWLINE* pattern_body RBRACE NEWLINE
    play_stmt    := PLAY IDENT IDENT NEWLINE

    expr  := term ((PLUS|MINUS) term)*
    term  := factor ((STAR|SLASH) factor)*
    factor:= MINUS factor | INT | FLOAT | IDENT | LPAREN expr RPAREN

`/` is just another binary operator here; whether an expr means a
"duration fraction" or a "division of frequencies" is a semantic-analysis
concern, not a parser concern.
"""

from lexer import Token, TokType, tokenize
from ast_nodes import (
    Program, TempoStmt, InstrumentDecl, LetStmt, PatternDecl, PlayStmt,
    NoteStmt, ChordStmt, RestStmt, RepeatStmt, EffectStmt, SlideStmt, StrumStmt,
    Num, Ident, Pitch, BinOp, UnaryOp,
)


class ParseError(Exception):
    def __init__(self, msg, line, col):
        super().__init__(f"ParseError at {line}:{col}: {msg}")
        self.line = line
        self.col = col


class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    # -- token helpers --

    def _cur(self) -> Token:
        return self.tokens[self.pos]

    def _at(self, type_) -> bool:
        return self._cur().type == type_

    def _advance(self) -> Token:
        tok = self.tokens[self.pos]
        if tok.type != TokType.EOF:
            self.pos += 1
        return tok

    def _expect(self, type_) -> Token:
        tok = self._cur()
        if tok.type != type_:
            raise ParseError(
                f"expected {type_.name}, got {tok.type.name} ({tok.value!r})",
                tok.line, tok.col,
            )
        return self._advance()

    def _skip_newlines(self):
        while self._at(TokType.NEWLINE):
            self._advance()

    def _end_stmt(self):
        # a statement ends at NEWLINE, EOF, or (for single-line blocks like
        # `pattern m { note C4 : 1/4 }`) right before a closing brace.
        if self._at(TokType.EOF) or self._at(TokType.RBRACE):
            return
        self._expect(TokType.NEWLINE)

    # -- entry point --

    def parse_program(self) -> Program:
        stmts = []
        self._skip_newlines()
        while not self._at(TokType.EOF):
            stmts.append(self._parse_stmt())
            self._skip_newlines()
        return Program(statements=stmts)

    # -- top level statements --

    def _parse_stmt(self):
        tok = self._cur()
        if tok.type == TokType.TEMPO:
            return self._parse_tempo()
        if tok.type == TokType.INSTRUMENT:
            return self._parse_instrument()
        if tok.type == TokType.LET:
            return self._parse_let()
        if tok.type == TokType.PATTERN:
            return self._parse_pattern()
        if tok.type == TokType.PLAY:
            return self._parse_play()
        if tok.type == TokType.EFFECT:
            return self._parse_effect()
        raise ParseError(
            f"unexpected token {tok.type.name} at top level", tok.line, tok.col
        )

    def _parse_tempo(self):
        tok = self._expect(TokType.TEMPO)
        bpm = self._parse_expr()
        self._end_stmt()
        return TempoStmt(bpm=bpm, line=tok.line)

    def _parse_instrument(self):
        tok = self._expect(TokType.INSTRUMENT)
        name = self._expect(TokType.IDENT).value
        self._expect(TokType.ASSIGN)
        waveform = self._expect(TokType.IDENT).value
        attack = None
        release = None
        if self._at(TokType.ENVELOPE):
            self._advance()
            attack = self._parse_expr()
            release = self._parse_expr()
        self._end_stmt()
        return InstrumentDecl(name=name, waveform=waveform, attack=attack, release=release, line=tok.line)

    def _parse_let(self):
        tok = self._expect(TokType.LET)
        name = self._expect(TokType.IDENT).value
        self._expect(TokType.ASSIGN)
        expr = self._parse_expr()
        self._end_stmt()
        return LetStmt(name=name, expr=expr, line=tok.line)

    def _parse_pattern(self):
        tok = self._expect(TokType.PATTERN)
        name = self._expect(TokType.IDENT).value
        self._expect(TokType.LBRACE)
        self._skip_newlines()
        body = self._parse_pattern_body()
        self._expect(TokType.RBRACE)
        self._end_stmt()
        return PatternDecl(name=name, body=body, line=tok.line)

    def _parse_play(self):
        tok = self._expect(TokType.PLAY)
        instrument = self._expect(TokType.IDENT).value
        pattern = self._expect(TokType.IDENT).value
        self._end_stmt()
        return PlayStmt(instrument=instrument, pattern=pattern, line=tok.line)

    def _parse_effect(self):
        tok = self._expect(TokType.EFFECT)
        name = self._expect(TokType.IDENT).value
        args = []
        while self._cur().type not in (TokType.NEWLINE, TokType.EOF, TokType.RBRACE):
            args.append(self._parse_expr())
        self._end_stmt()
        return EffectStmt(name=name, args=args, line=tok.line)

    def _parse_optional_velocity(self):
        if self._at(TokType.AT):
            self._advance()
            return self._parse_expr()
        return None

    # -- pattern-body statements --

    def _parse_pattern_body(self):
        stmts = []
        self._skip_newlines()
        while not self._at(TokType.RBRACE):
            stmts.append(self._parse_pattern_stmt())
            self._skip_newlines()
        return stmts

    def _parse_pattern_stmt(self):
        tok = self._cur()
        if tok.type == TokType.NOTE:
            return self._parse_note()
        if tok.type == TokType.CHORD:
            return self._parse_chord()
        if tok.type == TokType.REST:
            return self._parse_rest()
        if tok.type == TokType.REPEAT:
            return self._parse_repeat()
        if tok.type == TokType.SLIDE:
            return self._parse_slide()
        if tok.type == TokType.STRUM:
            return self._parse_strum()
        raise ParseError(
            f"unexpected token {tok.type.name} inside pattern body",
            tok.line, tok.col,
        )

    def _parse_note(self):
        tok = self._expect(TokType.NOTE)
        pitch_tok = self._expect(TokType.PITCH)
        self._expect(TokType.COLON)
        duration = self._parse_expr()
        velocity = self._parse_optional_velocity()
        self._end_stmt()
        return NoteStmt(
            pitch=Pitch(pitch_tok.value, pitch_tok.line, pitch_tok.col),
            duration=duration, velocity=velocity, line=tok.line,
        )

    def _parse_chord(self):
        tok = self._expect(TokType.CHORD)
        self._expect(TokType.LBRACKET)
        pitches = []
        p = self._expect(TokType.PITCH)
        pitches.append(Pitch(p.value, p.line, p.col))
        while self._at(TokType.COMMA):
            self._advance()
            p = self._expect(TokType.PITCH)
            pitches.append(Pitch(p.value, p.line, p.col))
        self._expect(TokType.RBRACKET)
        self._expect(TokType.COLON)
        duration = self._parse_expr()
        velocity = self._parse_optional_velocity()
        self._end_stmt()
        return ChordStmt(pitches=pitches, duration=duration, velocity=velocity, line=tok.line)

    def _parse_rest(self):
        tok = self._expect(TokType.REST)
        self._expect(TokType.COLON)
        duration = self._parse_expr()
        self._end_stmt()
        return RestStmt(duration=duration, line=tok.line)

    def _parse_slide(self):
        tok = self._expect(TokType.SLIDE)
        pitch_tok = self._expect(TokType.PITCH)
        self._expect(TokType.COLON)
        duration = self._parse_expr()
        velocity = self._parse_optional_velocity()
        self._end_stmt()
        return SlideStmt(
            pitch=Pitch(pitch_tok.value, pitch_tok.line, pitch_tok.col),
            duration=duration, velocity=velocity, line=tok.line,
        )

    def _parse_strum(self):
        tok = self._expect(TokType.STRUM)
        self._expect(TokType.LBRACKET)
        pitches = []
        p = self._expect(TokType.PITCH)
        pitches.append(Pitch(p.value, p.line, p.col))
        while self._at(TokType.COMMA):
            self._advance()
            p = self._expect(TokType.PITCH)
            pitches.append(Pitch(p.value, p.line, p.col))
        self._expect(TokType.RBRACKET)
        self._expect(TokType.COLON)
        duration = self._parse_expr()
        delay = None
        if self._at(TokType.IDENT) and self._cur().value == "delay":
            self._advance()
            delay = self._parse_expr()
        velocity = self._parse_optional_velocity()
        self._end_stmt()
        return StrumStmt(pitches=pitches, duration=duration, delay=delay,
                          velocity=velocity, line=tok.line)

    def _parse_repeat(self):
        tok = self._expect(TokType.REPEAT)
        count = self._parse_expr()
        self._expect(TokType.LBRACE)
        self._skip_newlines()
        body = self._parse_pattern_body()
        self._expect(TokType.RBRACE)
        self._end_stmt()
        return RepeatStmt(count=count, body=body, line=tok.line)

    # -- expressions (standard precedence climbing) --

    def _parse_expr(self):
        node = self._parse_term()
        while self._cur().type in (TokType.PLUS, TokType.MINUS):
            op_tok = self._advance()
            right = self._parse_term()
            node = BinOp(op=op_tok.value, left=node, right=right,
                         line=op_tok.line, col=op_tok.col)
        return node

    def _parse_term(self):
        node = self._parse_factor()
        while self._cur().type in (TokType.STAR, TokType.SLASH):
            op_tok = self._advance()
            right = self._parse_factor()
            node = BinOp(op=op_tok.value, left=node, right=right,
                         line=op_tok.line, col=op_tok.col)
        return node

    def _parse_factor(self):
        tok = self._cur()
        if tok.type == TokType.MINUS:
            self._advance()
            operand = self._parse_factor()
            return UnaryOp(op="-", operand=operand, line=tok.line, col=tok.col)
        if tok.type == TokType.INT or tok.type == TokType.FLOAT:
            self._advance()
            return Num(value=tok.value, line=tok.line, col=tok.col)
        if tok.type == TokType.IDENT:
            self._advance()
            return Ident(name=tok.value, line=tok.line, col=tok.col)
        if tok.type == TokType.LPAREN:
            self._advance()
            node = self._parse_expr()
            self._expect(TokType.RPAREN)
            return node
        raise ParseError(
            f"unexpected token {tok.type.name} in expression", tok.line, tok.col
        )


def parse(src: str) -> Program:
    return Parser(tokenize(src)).parse_program()