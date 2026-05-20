"""
Generates Anki .apkg files from a list of Card objects using genanki.

IMPORTANT: THAI_MODEL_ID must never change once any .apkg has been generated.
Changing it causes Anki to treat all cards as a new, duplicate note type.
"""
import os
import tempfile
from typing import List, TYPE_CHECKING

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
        ],
        templates=[
            {
                "name": "Thai → English",
                "qfmt": """
                    <div class="thai-front">{{Thai}}</div>
                    <div class="romanization">{{Romanization}}</div>
                    <div class="badge">{{CardType}}</div>
                """,
                "afmt": """
                    {{FrontSide}}
                    <hr>
                    <div class="english">{{English}}</div>
                    {{#ExampleThai}}
                    <div class="example">
                        <div class="thai-ex">{{ExampleThai}}</div>
                        <div>{{ExampleEnglish}}</div>
                    </div>
                    {{/ExampleThai}}
                """,
            },
        ],
        css=CARD_CSS,
    )


def export_deck_to_apkg(deck_name: str, deck_id_seed: int, cards: List["Card"]) -> bytes:
    """Returns raw .apkg bytes for streaming to the client."""
    import genanki

    model = _get_model()
    anki_deck = genanki.Deck(
        deck_id_seed % (2**31 - 1),
        deck_name,
    )

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
            ],
        )
        anki_deck.add_note(note)

    package = genanki.Package(anki_deck)
    tmp = tempfile.NamedTemporaryFile(suffix=".apkg", delete=False)
    tmp.close()

    try:
        package.write_to_file(tmp.name)
        with open(tmp.name, "rb") as f:
            return f.read()
    finally:
        os.unlink(tmp.name)
