import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lexer import tokenize, TokType, LexError


def types(tokens):
    return [t.type for t in tokens]


def test_tempo_and_int():
    toks = tokenize("tempo 120\n")
    assert types(toks) == [TokType.TEMPO, TokType.INT, TokType.NEWLINE, TokType.EOF]
    assert toks[1].value == 120


def test_instrument_assign():
    toks = tokenize("instrument lead = sine\n")
    assert types(toks) == [
        TokType.INSTRUMENT, TokType.IDENT, TokType.ASSIGN, TokType.IDENT,
        TokType.NEWLINE, TokType.EOF,
    ]
    assert toks[1].value == "lead"
    assert toks[3].value == "sine"


def test_pitch_tokens():
    toks = tokenize("note C4 : 1/4\n")
    assert types(toks) == [
        TokType.NOTE, TokType.PITCH, TokType.COLON, TokType.INT,
        TokType.SLASH, TokType.INT, TokType.NEWLINE, TokType.EOF,
    ]
    assert toks[1].value == "C4"


def test_pitch_with_sharp_and_flat():
    toks = tokenize("note Cs4 : 1/4\nnote Bb3 : 1/8\n")
    pitches = [t.value for t in toks if t.type == TokType.PITCH]
    assert pitches == ["Cs4", "Bb3"]


def test_ident_vs_pitch_disambiguation():
    # "C4" alone -> PITCH, but "C4x" or "Cake" should NOT be treated as a pitch
    toks = tokenize("Cake\n")
    assert types(toks) == [TokType.IDENT, TokType.NEWLINE, TokType.EOF]
    assert toks[0].value == "Cake"

    toks2 = tokenize("C4x\n")
    assert types(toks2) == [TokType.IDENT, TokType.NEWLINE, TokType.EOF]
    assert toks2[0].value == "C4x"


def test_chord_brackets_and_commas():
    toks = tokenize("chord [C4, E4, G4] : 1/2\n")
    assert types(toks) == [
        TokType.CHORD, TokType.LBRACKET, TokType.PITCH, TokType.COMMA,
        TokType.PITCH, TokType.COMMA, TokType.PITCH, TokType.RBRACKET,
        TokType.COLON, TokType.INT, TokType.SLASH, TokType.INT,
        TokType.NEWLINE, TokType.EOF,
    ]


def test_pattern_block():
    src = "pattern melody {\n  note C4 : 1/4\n  rest : 1/8\n}\n"
    toks = tokenize(src)
    assert toks[0].type == TokType.PATTERN
    assert toks[1].type == TokType.IDENT
    assert toks[2].type == TokType.LBRACE
    assert TokType.RBRACE in types(toks)


def test_repeat_and_play():
    toks = tokenize("repeat 4 { note C4 : 1/4 }\nplay lead melody\n")
    assert types(toks)[:2] == [TokType.REPEAT, TokType.INT]
    play_idx = types(toks).index(TokType.PLAY)
    assert toks[play_idx + 1].type == TokType.IDENT
    assert toks[play_idx + 2].type == TokType.IDENT


def test_let_and_arithmetic():
    toks = tokenize("let x = 1/4 + 1/8\n")
    assert types(toks) == [
        TokType.LET, TokType.IDENT, TokType.ASSIGN, TokType.INT, TokType.SLASH,
        TokType.INT, TokType.PLUS, TokType.INT, TokType.SLASH, TokType.INT,
        TokType.NEWLINE, TokType.EOF,
    ]


def test_float_literal():
    toks = tokenize("let bend = 0.5\n")
    assert toks[3].type == TokType.FLOAT
    assert toks[3].value == 0.5


def test_comment_ignored():
    toks = tokenize("tempo 120 # this is a comment\nplay lead melody\n")
    assert TokType.PLAY in types(toks)
    for t in toks:
        assert t.value != "#"


def test_line_col_tracking():
    toks = tokenize("tempo 120\nplay a b\n")
    play_tok = [t for t in toks if t.type == TokType.PLAY][0]
    assert play_tok.line == 2
    assert play_tok.col == 1


def test_unexpected_char_raises():
    try:
        tokenize("tempo 120\n$bad\n")
        assert False, "expected LexError"
    except LexError as e:
        assert e.line == 2
        assert e.col == 1


def test_negative_via_minus_token_not_negative_int():
    # lexer emits MINUS + INT separately; sign handling is a parser concern
    toks = tokenize("let x = -3\n")
    assert types(toks) == [
        TokType.LET, TokType.IDENT, TokType.ASSIGN, TokType.MINUS, TokType.INT,
        TokType.NEWLINE, TokType.EOF,
    ]


def test_parens():
    toks = tokenize("let x = (1 + 2) * 3\n")
    assert types(toks) == [
        TokType.LET, TokType.IDENT, TokType.ASSIGN,
        TokType.LPAREN, TokType.INT, TokType.PLUS, TokType.INT, TokType.RPAREN,
        TokType.STAR, TokType.INT,
        TokType.NEWLINE, TokType.EOF,
    ]


def test_at_and_effect_tokens():
    toks = tokenize("note C4 : 1/4 @ 0.7\neffect lowpass 800\n")
    types_list = types(toks)
    assert TokType.AT in types_list
    assert TokType.EFFECT in types_list
    at_idx = types_list.index(TokType.AT)
    assert toks[at_idx + 1].value == 0.7


if __name__ == "__main__":
    import pytest, sys as _s
    raise SystemExit(pytest.main([__file__, "-v"]))