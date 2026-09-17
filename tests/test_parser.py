import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from parser import parse, ParseError
from ast_nodes import (
    Program, TempoStmt, InstrumentDecl, LetStmt, PatternDecl, PlayStmt,
    NoteStmt, ChordStmt, RestStmt, RepeatStmt, EffectStmt,
    Num, Ident, Pitch, BinOp, UnaryOp,
)


def test_tempo_stmt():
    prog = parse("tempo 120\n")
    assert len(prog.statements) == 1
    stmt = prog.statements[0]
    assert isinstance(stmt, TempoStmt)
    assert isinstance(stmt.bpm, Num)
    assert stmt.bpm.value == 120


def test_instrument_decl():
    prog = parse("instrument lead = sine\n")
    stmt = prog.statements[0]
    assert isinstance(stmt, InstrumentDecl)
    assert stmt.name == "lead"
    assert stmt.waveform == "sine"


def test_let_with_fraction_expr():
    prog = parse("let x = 1/4 + 1/8\n")
    stmt = prog.statements[0]
    assert isinstance(stmt, LetStmt)
    assert stmt.name == "x"
    # top level should be a '+' BinOp of two '/' BinOps
    assert isinstance(stmt.expr, BinOp)
    assert stmt.expr.op == "+"
    assert isinstance(stmt.expr.left, BinOp) and stmt.expr.left.op == "/"
    assert isinstance(stmt.expr.right, BinOp) and stmt.expr.right.op == "/"
    assert stmt.expr.left.left.value == 1
    assert stmt.expr.left.right.value == 4
    assert stmt.expr.right.left.value == 1
    assert stmt.expr.right.right.value == 8


def test_operator_precedence_mul_over_add():
    # 2 + 3 * 4  ->  2 + (3*4), not (2+3)*4
    prog = parse("let x = 2 + 3 * 4\n")
    expr = prog.statements[0].expr
    assert isinstance(expr, BinOp) and expr.op == "+"
    assert expr.left.value == 2
    assert isinstance(expr.right, BinOp) and expr.right.op == "*"
    assert expr.right.left.value == 3
    assert expr.right.right.value == 4


def test_unary_minus():
    prog = parse("let x = -3\n")
    expr = prog.statements[0].expr
    assert isinstance(expr, UnaryOp)
    assert expr.op == "-"
    assert expr.operand.value == 3


def test_ident_in_expr():
    prog = parse("let x = freq * 2\n")
    expr = prog.statements[0].expr
    assert isinstance(expr, BinOp) and expr.op == "*"
    assert isinstance(expr.left, Ident) and expr.left.name == "freq"
    assert expr.right.value == 2


def test_note_stmt():
    prog = parse("pattern m {\n  note C4 : 1/4\n}\n")
    pat = prog.statements[0]
    assert isinstance(pat, PatternDecl)
    assert pat.name == "m"
    assert len(pat.body) == 1
    note = pat.body[0]
    assert isinstance(note, NoteStmt)
    assert note.pitch.name == "C4"
    assert note.duration.op == "/"


def test_chord_stmt():
    prog = parse("pattern m {\n  chord [C4, E4, G4] : 1/2\n}\n")
    chord = prog.statements[0].body[0]
    assert isinstance(chord, ChordStmt)
    assert [p.name for p in chord.pitches] == ["C4", "E4", "G4"]
    assert chord.duration.left.value == 1
    assert chord.duration.right.value == 2


def test_rest_stmt():
    prog = parse("pattern m {\n  rest : 1/8\n}\n")
    rest = prog.statements[0].body[0]
    assert isinstance(rest, RestStmt)
    assert rest.duration.right.value == 8


def test_repeat_nested_body():
    src = "pattern m {\n  repeat 4 {\n    note C4 : 1/4\n    rest : 1/8\n  }\n}\n"
    prog = parse(src)
    pat = prog.statements[0]
    rep = pat.body[0]
    assert isinstance(rep, RepeatStmt)
    assert rep.count.value == 4
    assert len(rep.body) == 2
    assert isinstance(rep.body[0], NoteStmt)
    assert isinstance(rep.body[1], RestStmt)


def test_play_stmt():
    prog = parse("play lead melody\n")
    stmt = prog.statements[0]
    assert isinstance(stmt, PlayStmt)
    assert stmt.instrument == "lead"
    assert stmt.pattern == "melody"


def test_full_program_end_to_end():
    src = (
        "tempo 120\n"
        "instrument lead = sine\n"
        "pattern melody {\n"
        "  note C4 : 1/4\n"
        "  note E4 : 1/4\n"
        "  chord [C4, E4, G4] : 1/2\n"
        "  rest : 1/4\n"
        "  repeat 2 {\n"
        "    note G4 : 1/8\n"
        "  }\n"
        "}\n"
        "play lead melody\n"
    )
    prog = parse(src)
    kinds = [type(s).__name__ for s in prog.statements]
    assert kinds == ["TempoStmt", "InstrumentDecl", "PatternDecl", "PlayStmt"]
    pat = prog.statements[2]
    assert len(pat.body) == 5  # note, note, chord, rest, repeat
    assert isinstance(pat.body[4], RepeatStmt)


def test_blank_lines_between_statements_ignored():
    src = "tempo 120\n\n\ninstrument lead = sine\n\n"
    prog = parse(src)
    assert len(prog.statements) == 2


def test_comments_ignored_by_parser():
    src = "tempo 120 # bpm\nplay lead melody # go\n"
    prog = parse(src)
    assert len(prog.statements) == 2


def test_missing_newline_between_stmts_raises():
    with pytest.raises(ParseError):
        parse("tempo 120 instrument lead = sine\n")


def test_unclosed_brace_raises():
    with pytest.raises(ParseError):
        parse("pattern m {\n  note C4 : 1/4\n")


def test_unknown_top_level_token_raises():
    with pytest.raises(ParseError):
        parse("note C4 : 1/4\n")  # 'note' only valid inside a pattern


def test_parens_override_precedence():
    # (2 + 3) * 4  ->  (2+3)*4, not 2 + (3*4)
    prog = parse("let x = (2 + 3) * 4\n")
    expr = prog.statements[0].expr
    assert isinstance(expr, BinOp) and expr.op == "*"
    assert isinstance(expr.left, BinOp) and expr.left.op == "+"
    assert expr.left.left.value == 2
    assert expr.left.right.value == 3
    assert expr.right.value == 4


def test_parens_in_duration_expr():
    prog = parse("pattern m {\n  note C4 : (1 + 1) / 8\n}\n")
    note = prog.statements[0].body[0]
    assert note.duration.op == "/"
    assert note.duration.left.op == "+"
    assert note.duration.right.value == 8


def test_nested_parens():
    prog = parse("let x = ((1 + 2) * (3 + 4))\n")
    expr = prog.statements[0].expr
    assert isinstance(expr, BinOp) and expr.op == "*"
    assert expr.left.op == "+" and expr.left.left.value == 1 and expr.left.right.value == 2
    assert expr.right.op == "+" and expr.right.left.value == 3 and expr.right.right.value == 4


def test_unclosed_paren_raises():
    with pytest.raises(ParseError):
        parse("let x = (1 + 2\n")


def test_empty_parens_raises():
    with pytest.raises(ParseError):
        parse("let x = ()\n")


def test_single_line_pattern_body():
    prog = parse("pattern m { note C4 : 1/4 }\n")
    pat = prog.statements[0]
    assert len(pat.body) == 1
    assert isinstance(pat.body[0], NoteStmt)


def test_note_with_velocity():
    prog = parse("pattern m {\n  note C4 : 1/4 @ 0.7\n}\n")
    note = prog.statements[0].body[0]
    assert note.velocity is not None
    assert note.velocity.value == 0.7


def test_note_without_velocity_defaults_to_none():
    prog = parse("pattern m {\n  note C4 : 1/4\n}\n")
    note = prog.statements[0].body[0]
    assert note.velocity is None


def test_chord_with_velocity():
    prog = parse("pattern m {\n  chord [C4, E4] : 1/2 @ 0.5\n}\n")
    chord = prog.statements[0].body[0]
    assert chord.velocity.value == 0.5


def test_effect_stmt_one_arg():
    prog = parse("effect lowpass 800\n")
    stmt = prog.statements[0]
    assert isinstance(stmt, EffectStmt)
    assert stmt.name == "lowpass"
    assert len(stmt.args) == 1
    assert stmt.args[0].value == 800


def test_effect_stmt_two_args():
    prog = parse("effect delay 0.25 0.4\n")
    stmt = prog.statements[0]
    assert stmt.name == "delay"
    assert len(stmt.args) == 2


def test_trailing_stmt_without_final_newline():
    # file with no trailing newline should still parse (EOF ends stmt)
    prog = parse("tempo 120")
    assert len(prog.statements) == 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))