# save as play_my_song.py in your TuneDSL folder
import sys
sys.path.insert(0, "src")

from parser import parse
from semantic import analyze
import reference as ref

src = """
tempo 100
instrument lead = square
pattern melody {
  note C4 : 1/4
  note D4 : 1/4
  note E4 : 1/4
  note C4 : 1/4
  note E4 : 1/2
  note D4 : 1/2
}
play lead melody
"""

result = analyze(parse(src))
events = result.note_events["melody"]
samples = ref.render(events, result.tempo_bpm)
ref.write_wav("my_song.wav", samples)
print(f"Wrote my_song.wav — {len(samples)/ref.SAMPLE_RATE:.2f} sec")