"""
Generates Anki .apkg files from a list of Card objects using genanki.

IMPORTANT: THAI_MODEL_ID must never change once any .apkg has been generated.
Changing it causes Anki to treat all cards as a new, duplicate note type.
New fields go at the end of the field list (Audio/ExampleAudio were added
after the first six); Anki offers to merge the updated note type on import.

Each note's GUID is derived from the card id, so re-exporting a deck after
cards change (or gain audio) updates the notes in Anki instead of adding
duplicates.
"""
import os
import tempfile
from pathlib import Path
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.db.models.card import Card

# Fixed IDs — do not change
THAI_MODEL_ID = 1607392319
THAI_DECK_BASE_ID = 2059400110

CARD_CSS = """
.card {
  font-family: 'Sarabun', 'Noto Sans Thai', sans-serif;
  font-size: 20px;
  text-align: center;
  color: #1a1a2e;
  background: #f8f9fa;
  padding: 20px;
}
.thai-front {
  font-size: 52px;
  font-weight: bold;
  margin-bottom: 8px;
}
.romanization {
  font-size: 18px;
  color: #6c757d;
  margin-bottom: 4px;
}
.english {
  font-size: 30px;
  font-weight: 600;
  margin: 16px 0 8px;
}
.example {
  font-size: 15px;
  color: #495057;
  line-height: 1.6;
  margin-top: 12px;
  border-top: 1px solid #dee2e6;
  padding-top: 12px;
}
.badge {
  display: inline-block;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 12px;
  background: #e9ecef;
  color: #6c757d;
  margin-top: 8px;
}
"""


def _get_model():
    import genanki
    return genanki.Model(
        THAI_MODEL_ID,
        "Dek-Kard Thai",
        fields=[
            {"name": "Thai"},
            {"name": "Romanization"},
            {"name": "English"},
            {"name": "ExampleThai"},
            {"name": "ExampleEnglish"},
            {"name": "CardType"},
            {"name": "Audio"},
            {"name": "ExampleAudio"},
        ],
        templates=[
            {
                "name": "Thai → English",
                "qfmt": """
                    <div class="thai-front">{{Thai}}</div>
                    <div class="romanization">{{Romanization}}</div>
                    <div class="badge">{{CardType}}</div>
                    {{Audio}}
                """,
                "afmt": """
                    {{FrontSide}}
                    <hr>
                    <div class="english">{{English}}</div>
                    {{#ExampleThai}}
                    <div class="example">
                        <div class="thai-ex">{{ExampleThai}} {{ExampleAudio}}</div>
                        <div>{{ExampleEnglish}}</div>
                    </div>
                    {{/ExampleThai}}
                """,
            },
        ],
        css=CARD_CSS,
    )


def note_guid(card_id: int) -> str:
    import genanki
    return genanki.guid_for("dek-kard-card", card_id)


def export_deck_to_apkg(
    deck_name: str,
    deck_id_seed: int,
    cards: List["Card"],
    audio: Optional[dict[tuple[int, str], Path]] = None,
) -> bytes:
    """Returns raw .apkg bytes for streaming to the client.

    *audio* maps (card_id, "thai"|"example") to an mp3 on disk; those clips
    are bundled into the package and referenced as [sound:...] fields.
    """
    import genanki

    audio = audio or {}
    model = _get_model()
    anki_deck = genanki.Deck(
        deck_id_seed % (2**31 - 1),
        deck_name,
    )

    media_files: dict[str, str] = {}

    def sound(card_id: int, field: str) -> str:
        path = audio.get((card_id, field))
        if path is None:
            return ""
        media_files[path.name] = str(path)
        return f"[sound:{path.name}]"

    for card in cards:
        note = genanki.Note(
            model=model,
            fields=[
                card.thai or "",
                card.romanization or "",
                card.english or "",
                card.example_thai or "",
                card.example_english or "",
                card.card_type or "vocab",
                sound(card.id, "thai"),
                sound(card.id, "example"),
            ],
            guid=note_guid(card.id),
        )
        anki_deck.add_note(note)

    package = genanki.Package(anki_deck, media_files=list(media_files.values()))
    tmp = tempfile.NamedTemporaryFile(suffix=".apkg", delete=False)
    tmp.close()

    try:
        package.write_to_file(tmp.name)
        with open(tmp.name, "rb") as f:
            return f.read()
    finally:
        os.unlink(tmp.name)
