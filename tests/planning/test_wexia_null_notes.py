"""Correction batch (private dossier validation finding, redacted --
field path + error type only, no real value ever seen or used here) --
a JSON `null` for a piece/labour line's `notes` field is a common
encoding of "absent", not a type error at the typed boundary."""

from mcma.mapping.wexia import parse_wexia


def test_piece_line_notes_null_normalizes_to_empty_string():
    parsed = parse_wexia(
        {
            "chiffrages": [
                {
                    "lignes_pieces": [{"item_type": "part", "item_name": "x", "subtotal": 10, "notes": None}],
                    "lignes_mo": [{"operation_type": "y", "subtotal": 5, "notes": None}],
                }
            ]
        }
    )
    assert parsed.chiffrages[0].lignes_pieces[0].notes == ""
    assert parsed.chiffrages[0].lignes_mo[0].notes == ""


def test_notes_still_accepts_a_real_string():
    parsed = parse_wexia(
        {"chiffrages": [{"lignes_pieces": [{"item_type": "part", "subtotal": 10, "notes": "a real note"}]}]}
    )
    assert parsed.chiffrages[0].lignes_pieces[0].notes == "a real note"
