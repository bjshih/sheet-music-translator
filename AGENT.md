# AI Agent Integration & Improvement Guide (`AGENT.md`)

> **Target Agents**: Google Gemini, OpenAI ChatGPT / GPT-4o, Anthropic Claude (Claude Code / Computer Use), Cursor, Windsurf, GitHub Copilot.

Welcome, AI Agent! This repository contains **SheetMusicTranslator**, an end-to-end automated pipeline that translates recorded songs (`.wav`, `.mp3`) into publication-grade vocal Lead Sheets (`.musicxml`, `.pdf`) with synchronized Chinese/English lyrics.

Your goal as an AI Agent is to **maintain, test, benchmark, and improve** this codebase without human intervention. Follow this guide strictly.

---

## 1. High-Level Architecture

The pipeline consists of **6 deterministic, headless stages**:

```
[Raw Audio (WAV/MP3)]
        │
        ▼ (Stage 1: Demucs HTDemucs)
[Vocals Stem] + [Accompaniment Stem]
        │              │
        │              ▼ (Stage 2: Librosa Onset/Beat Tracking)
        │      [Accompaniment Beat Grid (16th-note subgrid)]
        ▼              │
(Stage 3: TorchCREPE Neural F0 + Diatonic Scale Gravity)
  ├── Sentence Window Segmentation (Whisper ASR)
  ├── Micro-pitch Clamping (Scale Gravity Map)
  └── Beat-grid Snap (16th subgrid projection)
        │
        ├──► [Song_stem_original.mid] (Physical Stem Benchmark MIDI)
        │
        ▼ (Stage 4: Music21 Lead Sheet Composition)
  ├── Diatonic Key Setting (Remove redundant natural signs)
  ├── Legato Rest Elimination (Merge gaps <= 1.25 beats)
  └── Lyric Syllable Binding (<lyric> tags)
        │
        ├──► [Song_LeadSheet.musicxml]
        │
        ▼ (Stage 5: MuseScore 4 Headless CLI)
  ├──► [Song_LeadSheet.pdf]
  └──► [Song_score.mid] (Re-exported Verification MIDI)
        │
        ▼ (Stage 6: Closed-Loop Verification)
  [Sequential Pitch & Timing Deviation Audit] (Benchmark >= 95%)
```

---

## 2. Critical Music Theory & Notation Rules

When modifying or refining the code, you **MUST** uphold these rules:

1. **Lead Sheet Monophony**:
   - The score must contain ONLY the monophonic singing melody.
   - Do NOT mix chords or accompaniment artifacts into the vocal line.
2. **Accompaniment Beat-Grid Anchoring**:
   - Humans sing with rubato, micro-delays, and anticipation.
   - **Rule**: Never derive note onset times from vocal silence alone. Always project note start/end times onto the **Accompaniment Beat Grid** derived from kick, snare, and bass transients.
3. **Modal Scale Gravity (Pitch Clamping)**:
   - Untrained or natural vocalists drift by 20–50 cents.
   - **Rule**: All raw F0 estimates must be clamped to the song's diatonic scale (e.g., F Major: `F, G, A, Bb, C, D, E`), unless confidence for an intentional chromatic passing tone is sustained > 0.4 seconds.
4. **Music21 Redundant Accidental Bug (Crucial Gotcha)**:
   - When passing integer MIDI pitches to `m21.note.Note(pitch)`, music21 erroneously tags diatonic notes with `<accidental>natural</accidental>`.
   - **Rule**: For all diatonic notes matching the key signature, explicitly set:
     ```python
     if n.pitch.accidental is not None and n.pitch.accidental.name == 'natural':
         n.pitch.accidental = None
     ```
   - Failing to do this causes MuseScore to clutter the score with natural signs (`♮`) on every single note.
5. **No Broken Rests (Legato Extension)**:
   - Breath gaps in singing create messy 8th or 16th rests.
   - **Rule**: Extend previous note durations across gaps $\le 1.25$ beats inside melodic phrases to keep the sheet readable.

---

## 3. Platform & Dependency Gotchas

| Issue | Root Cause | Agent Action / Workaround |
| :--- | :--- | :--- |
| `ModuleNotFoundError: No module named 'pkg_resources'` | `setuptools >= 70.0.0` dropped `pkg_resources`, which `resampy` requires. | Ensure `setuptools < 70.0.0` (e.g., `pip install "setuptools<70"`). |
| `torchaudio` missing `torchcodec` on Windows | `torchcrepe.load.audio` invokes torchaudio backend that fails on Windows. | **Never** use `torchcrepe.load.audio`. Use `soundfile.read()` + `torch.from_numpy()` instead. |
| Redundant MIDI files | User confusion from intermediate debug files. | Only output **two** `.mid` files: `_stem_original.mid` and `_score.mid`. Clean up any temporary files. |
| MuseScore headless hang | GUI popups on headless environments. | Always pass `-o <output.pdf>` directly: `MuseScore4.exe -o output.pdf input.musicxml`. |

---

## 4. How an Agent Tests & Verifies Improvements

To benchmark changes, run:

```bash
python translate.py "path/to/song.wav" --key F
```

The script will automatically perform **Stage 6: Closed-Loop Verification**:
1. It compares `[Song]_score.mid` (synthesized from the final MusicXML) against `[Song]_stem_original.mid` (the neural F0 baseline).
2. It prints the **Quality Audit Report**:
   - **Pitch Accuracy Match Rate**: Must be $\ge 95.0\%$.
   - **Contour Concordance Rate**: Must be $\ge 95.0\%$.
   - **Timing Deviation**: Must be $< 1000$ ms.
3. If Pitch Match is $\ge 95\%$, the verdict is `★★★★★ MASTER PUBLICATION QUALITY`.

---

## 5. High-Impact Roadmap for Contributing Agents

Agents are encouraged to submit pull requests or generate improvements for:

* [ ] **CTC-based Phoneme Forced Alignment**:
  Replace phrase-level syllable interpolation with Wav2Vec2/CTC acoustic boundary tracking for millisecond-exact syllable-to-note binding.
* [ ] **Automated Key & Modulation Detection**:
  Integrate Krumhansl-Schmuckler (K-S) key-finding to automatically infer key signatures and detect mid-song modulations without manual `--key` flags.
* [ ] **Chord Symbol Extraction**:
  Analyze `_accompaniment.wav` using harmonic pitch class profiles (HPCP) to overlay standard lead-sheet jazz/pop chord symbols (e.g. `Fmaj7`, `Gm7`, `C7`) above the staff.
* [ ] **Pickup Measure (Anacrusis) XML Flagging**:
  Auto-detect whether measure 1 starts on beat 4, and inject `<measure implicit="yes" number="0">` into MusicXML.
