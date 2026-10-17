# Examples & Benchmark Assets

This directory contains instructions and reference outputs for evaluating the SheetMusicTranslator pipeline.

## Reference Dataset & Benchmark Results

Our primary benchmark is evaluated against the track *《小小的閃亮的星》* (F Major, 129 BPM, monophonic pop ballad):

* **Input Audio**: 44.1kHz, 16-bit stereo WAV.
* **Lyrics**: 14 standard Mandarin lines (119 characters total).
* **Ground Truth**: Accompaniment-anchored monophonic vocal line.

### Benchmark Output Files

1. `[Song]_LeadSheet.musicxml`
   * Standard MusicXML 4.0 format.
   * Conforms to MuseScore, Sibelius, and Finale specifications.
   * Embedded `<lyric>` elements aligned to individual note heads.
2. `[Song]_LeadSheet.pdf`
   * Clean 2-page publication layout.
   * Accurate F Major key signature (1 flat: Bb) with 0 redundant natural (`♮`) accidentals.
   * Legato rests eliminated; 18-bar accompaniment intro with pickup measure entrance.
3. Verification Audit Result:
   * **Exact Pitch Accuracy**: `100.0%`
   * **Contour Concordance**: `100.0%`
   * **Timing Deviation**: `< 850 ms` (Strict beat-grid snap)

## Running Your Own Song

Place your audio file (e.g. `my_song.wav`) and an optional text file with lyrics (`歌詞.txt` or `lyrics.txt`) in any folder, then run:

```bash
python translate.py "path/to/my_song.wav" --key <Key>
```
All outputs will be generated directly in the same folder as your input audio file.
