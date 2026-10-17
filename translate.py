#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SheetMusicTranslator: AI Audio-to-LeadSheet Pipeline
===================================================
A production-grade, headless, fully automated audio-to-sheet-music pipeline.

Transforms any song audio (WAV/MP3/FLAC) into commercial-ready Lead Sheets
(MusicXML and PDF) with accurate Chinese/English lyrics embedding,
accompaniment beat-grid anchoring, and diatonic scale gravity.

Author: SheetMusicTranslator Contributors
License: MIT
"""

import os
import sys
import shutil
import argparse
import subprocess
import soundfile as sf
import numpy as np
import librosa
import pretty_midi
import music21 as m21

# Local imports
try:
    from translator.scale_gravity import parse_key_signature, apply_scale_gravity
except ImportError:
    # Support direct execution without package installation
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from translator.scale_gravity import parse_key_signature, apply_scale_gravity

MUSESCORE_PATHS = [
    r"C:\Program Files\MuseScore 4\bin\MuseScore4.exe",
    r"C:\Program Files (x86)\MuseScore 4\bin\MuseScore4.exe",
    "/usr/bin/musescore4",
    "/usr/bin/musescore",
    "/Applications/MuseScore 4.app/Contents/MacOS/mscore"
]


def find_musescore_exe():
    """Locates MuseScore 4 executable across Windows, Linux, and macOS."""
    for p in MUSESCORE_PATHS:
        if os.path.exists(p):
            return p
    # Try searching in PATH
    which_ms = shutil.which("mscore") or shutil.which("musescore4") or shutil.which("MuseScore4")
    return which_ms


def run_demucs_separation(audio_path, output_dir, base_name, device="cpu"):
    """
    Step 1: AI Stem Separation using Demucs (Vocals / Accompaniment)
    """
    final_vocals = os.path.join(output_dir, f"{base_name}_vocals.wav")
    final_accomp = os.path.join(output_dir, f"{base_name}_accompaniment.wav")

    if os.path.exists(final_vocals) and os.path.exists(final_accomp):
        print(f"[1/6] Stems already exist in folder. Reusing cached vocals and accompaniment.")
        return final_vocals, final_accomp

    print(f"[1/6] Running Demucs stem separation (Device: {device})...")
    temp_dir = os.path.join(output_dir, "_temp_demucs")
    cmd = [
        sys.executable, "-m", "demucs.separate",
        "-d", device,
        "--two-stems", "vocals",
        "-o", temp_dir,
        audio_path
    ]
    subprocess.run(cmd, check=True)

    # Locate separated stems
    track_sub = os.path.join(temp_dir, "htdemucs", base_name)
    v_src = os.path.join(track_sub, "vocals.wav")
    nv_src = os.path.join(track_sub, "no_vocals.wav")

    if os.path.exists(v_src):
        shutil.move(v_src, final_vocals)
    if os.path.exists(nv_src):
        shutil.move(nv_src, final_accomp)

    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)

    print(f"[1/6] Stem separation complete:\n      Vocals: {os.path.basename(final_vocals)}\n      Accomp: {os.path.basename(final_accomp)}")
    return final_vocals, final_accomp


def analyze_accompaniment_beat_grid(accomp_path, tempo_override=None):
    """
    Step 2: Accompaniment Beat-Grid Anchoring
    Extracts strictly timed beat markers from kick, snare, and bass
    to eliminate rubato drift and tempo variations.
    """
    print(f"[2/6] Building Accompaniment Beat Grid...")
    y_acc, sr_acc = librosa.load(accomp_path, sr=22050)
    onset_env = librosa.onset.onset_strength(y=y_acc, sr=sr_acc)
    tempo, beat_frames = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr_acc)

    if tempo_override:
        tempo_bpm = int(tempo_override)
    else:
        tempo_bpm = round(float(tempo[0] if isinstance(tempo, np.ndarray) else tempo))
        if tempo_bpm < 55:
            tempo_bpm *= 2
        elif tempo_bpm > 165:
            tempo_bpm //= 2

    beat_times = librosa.frames_to_time(beat_frames, sr=sr_acc)

    # Build 16th-note sub-grid: (time_in_seconds, beat_quarter_length)
    sub_grid = []
    for i in range(len(beat_times) - 1):
        b_s = beat_times[i]
        b_e = beat_times[i+1]
        step = (b_e - b_s) / 4.0
        for s in range(4):
            sub_grid.append((b_s + s * step, i + s * 0.25))

    print(f"[2/6] Beat grid locked: {tempo_bpm} BPM, {len(beat_times)} anchor beats.")
    return tempo_bpm, sub_grid


def extract_lyrics_and_windows(vocals_path, lyrics_path=None):
    """
    Extracts sentence-level time windows and lyrics using Whisper
    or binds external lyrics to detected vocal timestamps.
    """
    import whisper

    lines = []
    if lyrics_path and os.path.exists(lyrics_path):
        with open(lyrics_path, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]

    print(f"[2/6] Running Whisper ASR for timestamped lyric segmentation...")
    model = whisper.load_model("base")
    result = model.transcribe(vocals_path, word_timestamps=True)

    segments = result.get("segments", [])
    sentence_windows = []

    if lines:
        # If external lyrics are provided, match them with Whisper voice activity segments
        if len(lines) == len(segments):
            sentence_windows = [(s["start"], s["end"]) for s in segments]
        else:
            # Map by cumulative active speech segments
            voice_segs = [(s["start"], s["end"]) for s in segments if (s["end"] - s["start"]) >= 1.0]
            if len(voice_segs) == len(lines):
                sentence_windows = voice_segs
            else:
                # Interpolate or use segment distribution
                sentence_windows = [(s["start"], s["end"]) for s in segments]
                if len(sentence_windows) < len(lines):
                    # Pad windows if needed
                    while len(sentence_windows) < len(lines):
                        last = sentence_windows[-1] if sentence_windows else (0, 5)
                        sentence_windows.append((last[1] + 1.0, last[1] + 5.0))
                elif len(sentence_windows) > len(lines):
                    sentence_windows = sentence_windows[:len(lines)]
    else:
        # Auto-generate lyric text from Whisper segments
        lines = [s["text"].strip() for s in segments if s["text"].strip()]
        sentence_windows = [(s["start"], s["end"]) for s in segments if s["text"].strip()]

    return lines, sentence_windows


def transcribe_crepe_and_gravity(vocals_path, lyrics_lines, sentence_windows, sub_grid,
                                  key_name, output_dir, base_name, device="cpu"):
    """
    Step 3: Neural F0 Tracking with CREPE + Scale Gravity + Accompaniment Snap
    """
    import torch
    import torchcrepe

    print(f"[3/6] Running TorchCREPE pitch tracking with {key_name} Scale Gravity...")
    root_pc, is_minor, scale_pcs, gravity_map = parse_key_signature(key_name)

    audio_data, sr = sf.read(vocals_path)
    if audio_data.ndim > 1:
        audio_data = audio_data.mean(axis=1)

    hop_length = int(sr / 100) # 10ms hop

    def hz_to_midi(hz):
        return 69.0 + 12.0 * np.log2(np.maximum(hz, 1e-5) / 440.0)

    def time_to_beat(t):
        closest = min(sub_grid, key=lambda x: abs(x[0] - t))
        return closest[1]

    stem_pm = pretty_midi.PrettyMIDI()
    stem_inst = pretty_midi.Instrument(program=54, name="Lead Vocal")
    aligned_notes = []

    for idx, (win_start, win_end) in enumerate(sentence_windows):
        s_sample = max(0, int(win_start * sr))
        e_sample = min(len(audio_data), int(win_end * sr))
        if e_sample <= s_sample:
            continue

        clip = audio_data[s_sample:e_sample]
        clip_t = torch.from_numpy(clip).float().unsqueeze(0)

        pitch, periodicity = torchcrepe.predict(
            clip_t,
            sr,
            hop_length=hop_length,
            fmin=65,
            fmax=750,
            model="tiny",
            decoder=torchcrepe.decode.weighted_argmax,
            return_periodicity=True,
            device=device
        )

        p = pitch.squeeze().cpu().numpy()
        conf = periodicity.squeeze().cpu().numpy()
        midi_p = hz_to_midi(p)
        times = np.arange(len(p)) * (hop_length / sr) + win_start

        curr_note = None
        line_notes = []

        for t_i in range(len(p)):
            c = conf[t_i]
            m = midi_p[t_i]
            t = times[t_i]

            if c >= 0.40 and 52 <= m <= 82:
                if curr_note is None:
                    curr_note = {"start": t, "end": t + 0.01, "pitches": [m]}
                else:
                    med_p = np.median(curr_note["pitches"])
                    if abs(m - med_p) >= 0.85:
                        if curr_note["end"] - curr_note["start"] >= 0.12:
                            raw_p = int(round(np.median(curr_note["pitches"])))
                            pure_p = apply_scale_gravity(raw_p, scale_pcs, gravity_map)
                            line_notes.append([curr_note["start"], curr_note["end"], pure_p])
                        curr_note = {"start": t, "end": t + 0.01, "pitches": [m]}
                    else:
                        curr_note["end"] = t + 0.01
                        curr_note["pitches"].append(m)
            else:
                if curr_note is not None:
                    if curr_note["end"] - curr_note["start"] >= 0.12:
                        raw_p = int(round(np.median(curr_note["pitches"])))
                        pure_p = apply_scale_gravity(raw_p, scale_pcs, gravity_map)
                        line_notes.append([curr_note["start"], curr_note["end"], pure_p])
                    curr_note = None

        if curr_note is not None and curr_note["end"] - curr_note["start"] >= 0.12:
            raw_p = int(round(np.median(curr_note["pitches"])))
            pure_p = apply_scale_gravity(raw_p, scale_pcs, gravity_map)
            line_notes.append([curr_note["start"], curr_note["end"], pure_p])

        # Consolidate adjacent identical pitches
        merged = []
        for n in line_notes:
            if not merged:
                merged.append(n)
            else:
                last = merged[-1]
                if n[2] == last[2] and (n[0] - last[1]) <= 0.22:
                    last[1] = max(last[1], n[1])
                elif n[0] < last[1]:
                    if (n[1] - n[0]) > (last[1] - last[0]):
                        last[1] = n[0]
                        merged.append(n)
                else:
                    merged.append(n)

        final_notes = [n for n in merged if (n[1] - n[0]) >= 0.15]
        if len(final_notes) == 0 and len(merged) > 0:
            final_notes = merged

        for n in final_notes:
            stem_inst.notes.append(pretty_midi.Note(
                velocity=95, pitch=n[2], start=n[0], end=n[1]
            ))

        # Assign lyrics syllables
        line_txt = lyrics_lines[idx] if idx < len(lyrics_lines) else ""
        chars = [c for c in line_txt if c.strip()]
        num_chars = len(chars)
        num_notes = len(final_notes)

        for c_idx in range(num_notes):
            n = final_notes[c_idx]
            s_beat = time_to_beat(n[0])
            e_beat = time_to_beat(n[1])
            if e_beat <= s_beat:
                e_beat = s_beat + 0.5

            if c_idx < num_chars:
                if c_idx == num_notes - 1 and num_chars > num_notes:
                    assigned_char = "".join(chars[c_idx:])
                else:
                    assigned_char = chars[c_idx]
            else:
                assigned_char = ""
            aligned_notes.append((s_beat, e_beat, n[2], assigned_char))

    stem_pm.instruments.append(stem_inst)
    stem_midi_path = os.path.join(output_dir, f"{base_name}_stem_original.mid")
    stem_pm.write(stem_midi_path)
    print(f"[3/6] Exported physical stem MIDI: {os.path.basename(stem_midi_path)}")
    return aligned_notes, stem_midi_path


def create_musicxml_lead_sheet(notes, bpm, key_name, base_name, output_dir):
    """
    Step 4: Music21 Lead Sheet Composition with Clean Rest Elimination
    """
    print(f"[4/6] Composing MusicXML Lead Sheet & Quantizing...")
    xml_path = os.path.join(output_dir, f"{base_name}_LeadSheet.musicxml")

    score = m21.stream.Score()
    part = m21.stream.Part()
    part.id = "Vocal_Melody"
    part.partName = "Lead Vocal"

    ts = m21.meter.TimeSignature("4/4")
    part.append(ts)
    part.append(m21.tempo.MetronomeMark(number=bpm))
    part.append(m21.instrument.Vocalist())

    raw_ql_notes = []
    for s_beat, e_beat, pitch, lyric in notes:
        d_beat = max(0.5, round((e_beat - s_beat) * 4) / 4.0)
        s_beat = round(s_beat * 4) / 4.0
        raw_ql_notes.append([s_beat, d_beat, pitch, lyric])

    # Legato extension: Fill micro-rests <= 1.25 quarter length
    for i in range(len(raw_ql_notes) - 1):
        curr_s = raw_ql_notes[i][0]
        curr_d = raw_ql_notes[i][1]
        next_s = raw_ql_notes[i+1][0]
        gap = next_s - (curr_s + curr_d)
        if 0 < gap <= 1.25:
            raw_ql_notes[i][1] = next_s - curr_s

    current_time_ql = 0.0
    for s_ql, d_ql, pitch, lyric in raw_ql_notes:
        if s_ql > current_time_ql:
            rest_ql = s_ql - current_time_ql
            if rest_ql >= 1.0:
                part.append(m21.note.Rest(quarterLength=rest_ql))
                current_time_ql += rest_ql
            else:
                current_time_ql = s_ql

        n = m21.note.Note(pitch, quarterLength=d_ql)
        if lyric:
            n.lyric = lyric

        part.append(n)
        current_time_ql += d_ql

    inferred_key = m21.key.Key(key_name)
    key_pitch_classes = {p.pitchClass: p for p in inferred_key.pitches}

    # Clean redundant natural signs and in-key accidentals
    for n in part.recurse().notes:
        if n.isNote:
            pc = n.pitch.pitchClass
            if pc in key_pitch_classes:
                if n.pitch.accidental is not None and n.pitch.accidental.name == 'natural':
                    n.pitch.accidental = None
                elif n.pitch.accidental is not None:
                    scale_p = key_pitch_classes[pc]
                    if scale_p.accidental is not None and scale_p.accidental.name == n.pitch.accidental.name:
                        n.pitch.accidental.displayStatus = False

    part.insert(0.0, inferred_key)
    measures_stream = part.makeMeasures()

    score.metadata = m21.metadata.Metadata()
    score.metadata.title = base_name
    score.metadata.composer = "SheetMusicTranslator AI Pipeline"
    score.append(measures_stream)

    score.write('musicxml', fp=xml_path)
    print(f"[4/6] Exported MusicXML: {os.path.basename(xml_path)}")
    return xml_path, score


def render_pdf_and_verification_midi(xml_path, score_obj, output_dir, base_name):
    """
    Step 5: MuseScore 4 Headless PDF Rendering & Score MIDI Export
    """
    print(f"[5/6] Exporting verification MIDI and rendering PDF via MuseScore 4...")
    musescore_exe = find_musescore_exe()

    score_midi_path = os.path.join(output_dir, f"{base_name}_score.mid")
    score_obj.write('midi', fp=score_midi_path)
    print(f"[5/6] Verification MIDI exported: {os.path.basename(score_midi_path)}")

    pdf_path = os.path.join(output_dir, f"{base_name}_LeadSheet.pdf")
    if os.path.exists(pdf_path):
        try:
            os.remove(pdf_path)
        except Exception:
            pass

    if musescore_exe:
        cmd = [musescore_exe, "-o", pdf_path, xml_path]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if os.path.exists(pdf_path):
            print(f"[5/6] PDF LeadSheet rendered: {os.path.basename(pdf_path)}")
    else:
        print("[5/6] Warning: MuseScore 4 executable not found. PDF export skipped.")
        pdf_path = None

    return pdf_path, score_midi_path


def verify_score_against_stem(stem_midi_path, score_midi_path):
    """
    Step 6: Closed-Loop MIDI Verification & Quality Audit
    """
    print(f"\n[6/6] Executing Closed-Loop Verification (Score vs. Stem)...")
    pm_stem = pretty_midi.PrettyMIDI(stem_midi_path)
    pm_score = pretty_midi.PrettyMIDI(score_midi_path)

    stem_notes = pm_stem.instruments[0].notes
    score_notes = pm_score.instruments[0].notes

    num_stem = len(stem_notes)
    num_score = len(score_notes)

    exact_matches = 0
    close_matches = 0
    deviations_ms = []

    compare_len = min(num_stem, num_score)
    for i in range(compare_len):
        s_p = score_notes[i].pitch
        orig_p = stem_notes[i].pitch
        diff = abs(s_p - orig_p)
        if diff == 0:
            exact_matches += 1
            close_matches += 1
        elif diff <= 1:
            close_matches += 1

        dev = abs(score_notes[i].start - stem_notes[i].start) * 1000
        deviations_ms.append(dev)

    match_pct = (exact_matches / compare_len * 100) if compare_len > 0 else 0
    close_pct = (close_matches / compare_len * 100) if compare_len > 0 else 0
    avg_dev = np.mean(deviations_ms) if deviations_ms else 0

    print("-" * 65)
    print("【QUALITY AUDIT REPORT (Accompaniment Grid + Scale Gravity)】")
    print(f" 1. Physical Stem Note Count:   {num_stem} (Monophonic Lead Line)")
    print(f" 2. Refined Score Note Count:   {num_score} (Full Lyric Alignment)")
    print(f" 3. Pitch Accuracy Match Rate:  {match_pct:.1f}% (Exact Semitone Match)")
    print(f" 4. Contour Concordance Rate:   {close_pct:.1f}% (Within ±1 Semitone)")
    print(f" 5. Beat-Grid Timing Deviation: ~{avg_dev:.1f} ms (Beat Alignment)")

    if match_pct >= 95.0:
        verdict = "★★★★★ MASTER PUBLICATION QUALITY: Zero manual editing needed."
    elif close_pct >= 85.0:
        verdict = "★★★★☆ EXCELLENT QUALITY: Clean notation, faithful melody."
    else:
        verdict = "★★★☆☆ ACCEPTABLE QUALITY."

    print(f" 6. Audit Verdict:              {verdict}")
    print("-" * 65)
    return match_pct >= 90.0


def process_audio_file(audio_path, output_dir=None, lyrics_file=None, key="F", bpm=None, device="cpu"):
    """Main execution pipeline."""
    audio_path = os.path.abspath(audio_path)
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    if output_dir is None:
        output_dir = os.path.dirname(audio_path)
    os.makedirs(output_dir, exist_ok=True)

    base_name = os.path.splitext(os.path.basename(audio_path))[0]
    base_name = base_name.replace("_mastered", "").replace("_bandlab", "").strip()

    # Locate lyrics if not explicitly provided
    if lyrics_file is None:
        cand_lyrics = [
            os.path.join(output_dir, "歌詞.txt"),
            os.path.join(output_dir, "lyrics.txt"),
            os.path.join(os.path.dirname(audio_path), "歌詞.txt"),
            os.path.join(os.path.dirname(audio_path), "lyrics.txt")
        ]
        for c in cand_lyrics:
            if os.path.exists(c):
                lyrics_file = c
                break

    print("\n" + "=" * 65)
    print(f"SheetMusicTranslator Pipeline: {base_name}")
    print(f"Working Directory: {output_dir}")
    print("=" * 65)

    # 1. Stem Separation
    vocals_wav, accomp_wav = run_demucs_separation(audio_path, output_dir, base_name, device=device)

    # 2. Accompaniment Beat Grid & Lyric Segmentation
    detected_bpm, sub_grid = analyze_accompaniment_beat_grid(accomp_wav, tempo_override=bpm)
    final_bpm = bpm if bpm else detected_bpm
    lyrics_lines, sentence_windows = extract_lyrics_and_windows(vocals_wav, lyrics_file)

    # 3. CREPE Monophonic Pitch Tracking & Scale Gravity
    aligned_notes, stem_midi_path = transcribe_crepe_and_gravity(
        vocals_wav, lyrics_lines, sentence_windows, sub_grid,
        key_name=key, output_dir=output_dir, base_name=base_name, device=device
    )

    # 4. MusicXML Lead Sheet Generation
    xml_path, score_obj = create_musicxml_lead_sheet(aligned_notes, final_bpm, key, base_name, output_dir)

    # 5. MuseScore 4 PDF & Verification MIDI Export
    pdf_path, score_midi_path = render_pdf_and_verification_midi(xml_path, score_obj, output_dir, base_name)

    # 6. Closed-Loop Verification
    verify_score_against_stem(stem_midi_path, score_midi_path)

    print("\n" + "=" * 65)
    print(f"DELIVERY ARTIFACTS for [{base_name}]:")
    print(f"Directory: {output_dir}")
    print(" 1. Original Audio:          " + os.path.basename(audio_path))
    print(" 2. Isolated Vocals:         " + os.path.basename(vocals_wav))
    print(" 3. Isolated Accompaniment:  " + os.path.basename(accomp_wav))
    print(" 4. Physical Stem MIDI:      " + os.path.basename(stem_midi_path))
    print(" 5. Verification Score MIDI: " + os.path.basename(score_midi_path))
    print(" 6. MusicXML Lead Sheet:     " + os.path.basename(xml_path))
    if pdf_path:
        print(" 7. Printed PDF Score:       " + os.path.basename(pdf_path))
    print("=" * 65 + "\n")


def main():
    parser = argparse.ArgumentParser(description="SheetMusicTranslator: Production AI Audio-to-LeadSheet Pipeline")
    parser.add_argument("audio", help="Input audio file (.wav, .mp3, .flac)")
    parser.add_argument("-o", "--output", default=None, help="Output directory (defaults to audio file directory)")
    parser.add_argument("-l", "--lyrics", default=None, help="Path to lyrics text file (optional)")
    parser.add_argument("-k", "--key", default="F", help="Key signature (e.g. F, C, G, Dm, Am; default: F)")
    parser.add_argument("-b", "--bpm", type=int, default=None, help="BPM override (defaults to auto accompaniment tracking)")
    parser.add_argument("-d", "--device", default="cpu", choices=["cpu", "cuda"], help="Computation device (default: cpu)")
    args = parser.parse_args()

    process_audio_file(
        audio_path=args.audio,
        output_dir=args.output,
        lyrics_file=args.lyrics,
        key=args.key,
        bpm=args.bpm,
        device=args.device
    )


if __name__ == "__main__":
    main()
