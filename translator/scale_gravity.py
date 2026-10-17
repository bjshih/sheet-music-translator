"""
Scale Gravity and Modal Clamping Module
Calculates diatonic scale degrees and applies musical attraction field
to eliminate vocal micro-pitch drift and out-of-key accidentals.
"""

import numpy as np

# Semitone intervals for diatonic modes
MAJOR_INTERVALS = [0, 2, 4, 5, 7, 9, 11]
NATURAL_MINOR_INTERVALS = [0, 2, 3, 5, 7, 8, 10]

NOTE_NAME_TO_PC = {
    'C': 0, 'C#': 1, 'DB': 1,
    'D': 2, 'D#': 3, 'EB': 3,
    'E': 4,
    'F': 5, 'F#': 6, 'GB': 6,
    'G': 7, 'G#': 8, 'AB': 8,
    'A': 9, 'A#': 10, 'BB': 10,
    'B': 11
}

PC_TO_NAME = {0: 'C', 1: 'C#', 2: 'D', 3: 'Eb', 4: 'E', 5: 'F', 6: 'F#', 7: 'G', 8: 'Ab', 9: 'A', 10: 'Bb', 11: 'B'}


def parse_key_signature(key_str="F"):
    """
    Parses a key string like 'F', 'F Major', 'D Minor', 'G'
    Returns (root_pc, is_minor, key_name)
    """
    key_str = key_str.strip().upper()
    is_minor = 'MINOR' in key_str or key_str.endswith('M') and not key_str.endswith('MAJ')
    
    clean_root = key_str.replace('MAJOR', '').replace('MINOR', '').replace('MAJ', '').replace('MIN', '').strip()
    root_pc = NOTE_NAME_TO_PC.get(clean_root, 5) # Default to F (5)
    
    intervals = NATURAL_MINOR_INTERVALS if is_minor else MAJOR_INTERVALS
    scale_pcs = set((root_pc + step) % 12 for step in intervals)
    
    # Precompute nearest diatonic attraction map
    gravity_map = {}
    for pc in range(12):
        if pc in scale_pcs:
            gravity_map[pc] = pc
        else:
            # Find closest pitch class in scale
            best_target = None
            min_dist = 999
            for s in scale_pcs:
                # Circular distance on pitch class circle
                dist = min((pc - s) % 12, (s - pc) % 12)
                if dist < min_dist:
                    min_dist = dist
                    best_target = s
                elif dist == min_dist:
                    # Prefer resolution downwards or root/dominant
                    best_target = s
            gravity_map[pc] = best_target
            
    return root_pc, is_minor, scale_pcs, gravity_map


def apply_scale_gravity(pitch, scale_pcs, gravity_map):
    """
    Snaps an integer MIDI pitch into the diatonic scale gravity field.
    """
    pc = pitch % 12
    if pc in scale_pcs:
        return pitch
    octave = pitch // 12
    new_pc = gravity_map.get(pc, pc)
    return octave * 12 + new_pc
