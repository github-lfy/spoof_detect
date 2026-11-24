#!/usr/bin/env python3
"""Decode BDS D1 almanac pages carried in UT986 BDSRAWSUBFRAMEA logs.

The UT986 log transports ten 30-bit BDS navigation words in Data[0..9].
For this UT986 log layout, words 2..10 carry information in their low
22 bits. Their upper bits are ignored, not interpreted as navigation data.

Supports basic D1 almanacs and expanded pages with an explicit AmEpID context.
Use generate_almanac_report.py to process a log and track that context per SV.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, asdict


WORD_MASK = (1 << 30) - 1


def unsigned(bits: str, start: int, length: int) -> int:
    """Read ICD bit positions, which are one-based and MSB-first."""
    value = bits[start - 1 : start - 1 + length]
    if len(value) != length:
        raise ValueError(f"bit range {start}..{start + length - 1} is outside a 300-bit subframe")
    return int(value, 2)


def signed(bits: str, start: int, length: int) -> int:
    value = unsigned(bits, start, length)
    return value - (1 << length) if value & (1 << (length - 1)) else value


def joined_unsigned(bits: str, parts: list[tuple[int, int]]) -> int:
    value = 0
    for start, length in parts:
        value = (value << length) | unsigned(bits, start, length)
    return value


def joined_signed(bits: str, parts: list[tuple[int, int]]) -> int:
    width = sum(length for _, length in parts)
    value = joined_unsigned(bits, parts)
    return value - (1 << width) if value & (1 << (width - 1)) else value


def raw_parts(bits: str, parts: list[tuple[int, int]], is_signed: bool) -> int:
    return joined_signed(bits, parts) if is_signed else joined_unsigned(bits, parts)


@dataclass
class Almanac:
    prn: int
    subframe_id: int
    page_number: int
    sqrt_a_m_half: float
    semi_major_axis_m: float
    eccentricity: float
    inclination_offset_rad: float
    inclination_offset_semicircles: float
    omega0_rad: float
    omega0_semicircles: float
    omega_dot_rad_per_s: float
    omega_dot_semicircles_per_s: float
    argument_of_perigee_rad: float
    argument_of_perigee_semicircles: float
    mean_anomaly_rad: float
    mean_anomaly_semicircles: float
    toa_s: int
    clock_a0_s: float
    clock_a1_s_per_s: float
    expanded_almanac_id: int | None
    time_sharing_id: int | None
    raw: dict[str, int]


def parse_sentence(sentence: str) -> tuple[dict[str, object], list[int]]:
    """Parse an ASCII BDSRAWSUBFRAME / BDSRAWSUBFRAMEA sentence."""
    text = sentence.strip()
    if not text.startswith(("#BDSRAWSUBFRAME,", "#BDSRAWSUBFRAMEA,")):
        raise ValueError("expected an ASCII #BDSRAWSUBFRAME sentence")
    if ";" not in text:
        raise ValueError("missing ';' between the UT986 header and payload")
    if "*" not in text:
        raise ValueError("missing ASCII CRC32")
    body, checksum = text.rsplit("*", 1)
    if len(checksum) != 8:
        raise ValueError("CRC32 must contain eight hexadecimal digits")
    computed = crc32_unicore(body[1:].encode("ascii"))
    if computed != int(checksum, 16):
        raise ValueError(f"CRC32 mismatch: expected {checksum}, computed {computed:08x}")
    header, payload = body.split(";", 1)
    h = header.lstrip("#").split(",")
    if len(h) < 10:
        raise ValueError("incomplete UT986 ASCII header")
    fields = [part.strip() for part in payload.split(",")]
    if len(fields) != 14:
        raise ValueError("payload must contain channel, satellite, source, subframe ID, and ten Data words")
    try:
        channel = int(fields[0], 10)
        satellite_id = int(fields[1], 10)
        data_source = fields[2]
        subframe_id = int(fields[3], 10)
        words = [int(item, 16) for item in fields[4:14]]
    except ValueError as exc:
        raise ValueError(f"invalid BDSRAWSUBFRAME payload: {exc}") from exc
    if any(word < 0 or word > WORD_MASK for word in words):
        raise ValueError("each Data word must fit in the transmitted 30-bit BDS navigation word")
    return {
        "message": h[0], "channel": channel, "satellite_id": satellite_id,
        "data_source": data_source, "subframe_id": subframe_id,
        "gps_week": int(h[4]), "gps_tow_ms": float(h[5]),
        "crc32": checksum.lower(), "crc_valid": True,
    }, words


def crc32_unicore(data: bytes) -> int:
    """Reflected CRC32, polynomial 0xEDB88320, init=0, xorout=0."""
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xEDB88320 if crc & 1 else 0)
    return crc


def words_to_bits(words: list[int]) -> str:
    if len(words) != 10:
        raise ValueError("exactly ten Data words are required")
    # Reconstruct ICD positions, inserting zero placeholders for absent parity.
    # Word 1: original information at bits 29..4; words 2..10: low 22 bits.
    return f"{words[0] >> 4:026b}" + "0000" + "".join(
        f"{word & 0x3FFFFF:022b}" + "00000000" for word in words[1:]
    )


def decode_d1_almanac(metadata: dict[str, object], words: list[int],
                      expanded_context: int | None = None) -> Almanac | None:
    if metadata["data_source"] != "D1":
        return None
    bits = words_to_bits(words)
    fraid = unsigned(bits, 16, 3)
    pnum = unsigned(bits, 44, 7)
    declared = int(metadata["subframe_id"])
    if fraid != declared:
        raise ValueError(f"subframe ID conflict: payload={declared}, D1 bits 16..18={fraid}")
    if fraid == 4 and 1 <= pnum <= 24:
        prn = pnum
    elif fraid == 5 and 1 <= pnum <= 6:
        prn = 24 + pnum
    elif fraid == 5 and 11 <= pnum <= 23 and expanded_context == 3:
        amid = unsigned(bits, 291, 2)
        if amid == 1:
            prn = 31 + pnum - 11
        elif amid == 2:
            prn = 44 + pnum - 11
        elif amid == 3 and pnum <= 17:
            prn = 57 + pnum - 11
        else:
            return None
    else:
        return None

    # ICD B1I D1 Figure 5-11-1.  Every tuple is (first one-based ICD bit, length).
    layout = {
        "sqrt_a": ([(51, 2), (61, 22)], False, 2.0 ** -11),
        "a1": ([(91, 11)], True, 2.0 ** -38),
        "a0": ([(102, 11)], True, 2.0 ** -20),
        "omega0": ([(121, 22), (151, 2)], True, math.pi * 2.0 ** -23),
        "e": ([(153, 17)], False, 2.0 ** -21),
        "delta_i": ([(170, 3), (181, 13)], True, math.pi * 2.0 ** -19),
        "toa": ([(194, 8)], False, 2.0 ** 12),
        "omega_dot": ([(202, 1), (211, 16)], True, math.pi * 2.0 ** -38),
        "omega": ([(227, 6), (241, 18)], True, math.pi * 2.0 ** -23),
        "m0": ([(259, 4), (271, 20)], True, math.pi * 2.0 ** -23),
        "amepid": ([(291, 2)], False, 1.0),
    }
    raw = {name: raw_parts(bits, parts, signed_value) for name, (parts, signed_value, _) in layout.items()}
    value = {name: raw[name] * scale for name, (_, _, scale) in layout.items()}
    sqrt_a = value["sqrt_a"]
    return Almanac(
        prn=prn, subframe_id=fraid, page_number=pnum,
        sqrt_a_m_half=sqrt_a, semi_major_axis_m=sqrt_a * sqrt_a,
        eccentricity=value["e"],
        inclination_offset_rad=value["delta_i"], inclination_offset_semicircles=raw["delta_i"] * 2.0 ** -19,
        omega0_rad=value["omega0"], omega0_semicircles=raw["omega0"] * 2.0 ** -23,
        omega_dot_rad_per_s=value["omega_dot"], omega_dot_semicircles_per_s=raw["omega_dot"] * 2.0 ** -38,
        argument_of_perigee_rad=value["omega"], argument_of_perigee_semicircles=raw["omega"] * 2.0 ** -23,
        mean_anomaly_rad=value["m0"], mean_anomaly_semicircles=raw["m0"] * 2.0 ** -23,
        toa_s=int(value["toa"]), clock_a0_s=value["a0"], clock_a1_s_per_s=value["a1"],
        expanded_almanac_id=raw["amepid"] if fraid == 4 or pnum <= 6 else None,
        time_sharing_id=raw["amepid"] if fraid == 5 and pnum >= 11 else None,
        raw={k: v for k, v in raw.items() if k != "amepid"},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sentence", nargs="?", help="one complete #BDSRAWSUBFRAME line; omit to read stdin")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument("--expanded-context", type=int, choices=range(4),
                        help="AmEpID from the same broadcasting SV and frame; 3 enables expanded pages")
    args = parser.parse_args()
    sentence = args.sentence if args.sentence else sys.stdin.read().strip()
    if not sentence:
        parser.error("provide one BDSRAWSUBFRAME sentence as an argument or through stdin")
    try:
        metadata, words = parse_sentence(sentence)
        almanac = decode_d1_almanac(metadata, words, args.expanded_context)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    result = {"ut986": metadata, "data_words_hex": [f"{word:08X}" for word in words]}
    if almanac is None:
        result["status"] = "not_d1_almanac_page"
        result["detail"] = "No enabled D1 almanac on this page. Expanded pages require same-SV AmEpID=3 context and a valid AmID/page combination. D2 is not supported."
    else:
        result["status"] = "decoded"
        result["almanac"] = asdict(almanac)
        result["missing"] = ["almanac_week_WNa", "satellite_health"]
        if almanac.sqrt_a_m_half == 0 or almanac.toa_s > 602112:
            result["status"] = "candidate_with_issues"
            result["detail"] = "Zero orbit or out-of-week toa: do not use as a valid almanac."
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) if args.json else json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
