# Baimai (ใบไม้) brand system

Baimai turns Thai textbooks, worksheets and photos of notes into spaced-repetition flashcards.
The name means "leaf". In Thai, ใบ (bai) is also the counting word for cards, and "บ ใบไม้" is how
every Thai child learns the letter บ. Cards are leaves, reviews make them grow, and Bai the leaf
keeps you company at the edges of a session.

Status: **v0.3.** Applied to the frontend (D-027).
Previously v0.2: Name, Garden direction, colour, type, tokens and logo are agreed.
Every decision, with its reason and source, is in [decision-log.md](decision-log.md) (D-xxx below).
Round 1 ("calm leaf") was rejected for looking like a bank. It is kept in `archive/`.

---

## 1. Principles

### 1. Thai first, not Thai-themed
Draw from real Thai learning and craft: the alphabet mnemonics, looped school letterforms,
exercise-book paper, marigold, kram indigo, orchids.
- **Rules out:** elephants, tuk-tuks, temple silhouettes, Thai-flag colours, "exotic" brush fonts.
- Thai text is always real, correctly spelled words in a proper Thai typeface.

### 2. Bright, warm and friendly, not playful for its own sake
It should feel like a well-made school notebook: bright colour, rounded shapes, a friendly character.
- **Rules out:** the corporate restraint of round 1 (dark green, grey canvas, white on dark fills),
  and also gimmicks: jokes, puns, confetti storms, guilt-trip streak copy (D-021).
- Copy is plain and factual: "20 cards due", "All done for today".

### 3. The learner's eye comes first
Legible Thai script beats brand expression on the study surface.
- The card face is clean and white, in the learner's chosen font (D-013). There is no texture,
  no mascot and no deck colour behind the Thai word.
- WCAG 2.2 AA everywhere. Correct and wrong always carry ✓ / ✕ and words.

### 4. Show the workings
Be open about what the OCR and Claude guessed versus what a person checked.
- Warning orange plus a reason marks "needs checking". The original and the overrides are always one tap away.

### 5. One leaf at a time
Each view has one chunky green primary button. Everything else is outlined or neutral.

---

## 2. Colour (D-020, D-023)

| Role | Scale | Anchor | Source |
|---|---|---|---|
| Brand / primary | `leaf` | 500 `#3DA35D` | fresh leaf |
| Accent (rewards and milestones only) | `marigold` | 300 `#F2B33D` | ดาวเรือง garland |
| Canvas | `paper` | `#FFFAF2` + ruled lines `#F1E9DA` | exercise book |
| Neutrals | `neutral` | 600 `#75716A` | warm paper greys |
| Deck colours | `leaf`, `marigold`, `kram`, `orchid` | kram 700 `#2652B0`, orchid 400 `#B98ADB` | indigo, Thai orchid |
| Danger | `lacquer` | 700 `#A21F1B` | lacquerware red |
| Warning | `ember` | 500 `#C25E0A` | |
| Info | `kram` | | |
| Success | uses `leaf` | | |

See [specimen.html](specimen.html) for every shade and measured ratio. It's generated from the tokens.

### Usage rules
- **Fills are bright with dark text.** The primary button is leaf-500 with leaf-950 text (5.09:1).
  White text on leaf-500 fails (3.06:1). **Never put white text on marigold** either.
- **Chunky buttons:** the primary has a 4px leaf-600 bottom edge. Hover goes lighter (leaf-400). Pressed is leaf-300, with the edge removed and a 1px downward shift.
- **Ruled paper** is the light-mode page canvas only. Cards, sheets and inputs sit on white.
  Dark mode has no ruling.
- **Deck colours** are identity tints for decks and topics: a pale bg, dark text and a mid meter.
  Always show them with the deck name, never colour alone. They have been checked against each
  other and against danger red for colour-blind users.
- **Marigold** is for streaks, XP and milestones only.
- **Lightest text:** neutral-600 (4.54:1 on paper). neutral-500 is for borders and icons only.
  The current code's `text-gray-400` (about 2.5:1) fails and must be migrated.

### Key semantic pairs
| Token | Light | Dark |
|---|---|---|
| text.default on canvas | 12.29:1 | 13.96:1 |
| text.secondary | 6.52:1 | 7.25:1 |
| text.muted | 4.54:1 | 5.22:1 |
| action.primary | leaf-950 on leaf-500, 5.09:1 | leaf-950 on leaf-400, 6.73:1 |
| text.link | leaf-700, 6.34:1 | leaf-400, 5.46:1 |
| border.control | 3.35:1 | 3.68:1 |
| status.success / danger / warning / info | 8.17 / 8.94 / 8.64 / 8.56 | 9.19 / 9.66 / 9.43 / 9.54 |

## 3. Typography
- **Display (headings, buttons, numbers):** Mitr, rounded geometric with Thai + Latin (D-020).
- **Body and UI text:** Anuphan (D-015).
- **Card faces:** a user setting, `data-card-font` on `<html>` (D-013):

  | Setting | Font |
  |---|---|
  | Learner (default) | Noto Sans Thai Looped |
  | Classic | Sarabun (looped) |
  | Real-world | Anuphan (loopless) |
  | Handwriting | Itim |

- Thai card face 48 to 56px. Body 16px (a common web baseline, not a WCAG rule).
  Thai needs about 1.5 to 1.6 line-height for stacked vowels and tone marks.

## 4. Shape, space and elevation
- 4px grid. Radius: 8 chips, 14 buttons and inputs, 20 panels, 26 flashcards.
- Depth comes from a 2px outline plus a 3px solid bottom edge, a printed-sticker look, not soft shadows.
- Dark mode: lighter surfaces rise (canvas 950, card 900, raised 800).

## 5. Components and states
- **Primary button:** leaf-500 → hover leaf-400 → pressed leaf-300 with no edge. Dark: leaf-400 → 300 → 200. Text is always leaf-950.
- **Secondary button:** white with a 2px neutral-500 outline and a neutral-200 bottom edge.
- **Grade buttons (Again / Hard / Good / Easy):** only Good is filled. Again uses lacquer text with a ✕.
- **Focus-visible:** 2px leaf-700 ring (dark: leaf-400) with a 2px offset.
- **Disabled:** exempt from contrast under WCAG 1.4.3, but keep it readable. Prefer enabled controls that explain themselves.
- Targets ≥24×24 CSS px (WCAG 2.5.8). Review buttons should be about 44px.

## 6. Bai the leaf (D-022)
- **Where:** empty states, end of session, milestones, "needs checking" prompts, onboarding and help.
- **Never:** on the card face, during a review, or speaking in jokes. The text beside Bai is plain.
- **Expressions:** happy (default), sleeping (nothing due), thinking (needs checking). Marigold Bai is for milestones only.
- Bai is drawn with a flat fill, ink dots for eyes and soft pink cheeks. No outlines, gradients or limbs.

## 7. Logo (D-025)
Files are in [logo/](logo/). Check them all at once in [logo/preview.html](logo/preview.html).

| File | Use |
|---|---|
| `lockup.svg` / `lockup-dark.svg` | Bai + wordmark, the default sign-off |
| `wordmark.svg` / `wordmark-dark.svg` | Where Bai already appears nearby |
| `bai-mark.svg` | Avatar, splash, 24px and up |
| `favicon.svg` | Plain leaf with a midrib, below 24px (Bai's face doesn't survive) |
| `app-icon-1024.svg` / `-dark` | Bai on a paper tile, full-bleed square (the OS applies its own corner mask) |

- The wordmark is hand-drawn monoline paths (no font dependency). Its i-dots are leaves.
- Wordmark ink is leaf-800 on light (9.05:1 on paper) and leaf-300 on dark (9.50:1). Leaf dots and Bai are leaf-500 (3.06:1 on paper, 5.17:1 on dark).
- Clear space: the height of Bai's eye-to-chin around the lockup. Minimum lockup height: 24px.
- **Don't:** recolour Bai outside the leaf and marigold variants, put the lockup on a busy photo, or stretch or rotate it.

## 8. Data visualisation (D-024)
- **Mastery (sequential):** the leaf scale, 100 → 800.
- **Categorical:** light uses leaf-700, marigold-500, kram-500, orchid-600 and neutral-500. Dark uses leaf-400, marigold-300, kram-300, orchid-400 and neutral-300.
  CVD-checked with no flagged pairs. Each series is ≥3:1 on its background.
- Status colours are never series colours. Label series directly.

## 9. Motion
- Durations 120 / 220 / 420ms (card flip). Easing "settle" `cubic-bezier(0.2, 0.7, 0.2, 1)`. Buttons press down 1px.
- **Signature moment:** when a card graduates, a small leaf grows on its corner, and Bai blinks on the end-of-session screen.
- `prefers-reduced-motion` sets all durations to 0. The tokens already do this.

## 10. Marketing, README and social
- Hero: a paper canvas with large Mitr headlines, Bai, and one real Thai word on a white card.
- Social card (1200×630): paper background, the lockup at the top left, a white flashcard showing ใบไม้ / bai mai / leaf, and Bai at the lower right.
- Marketing may use bigger, brighter areas of leaf and marigold than the product UI.
- Email: use inline hex values, and check Gmail and Outlook dark-mode inversion.
- Print: no CMYK or Pantone values yet. They must be confirmed by a printer or a Pantone bridge guide.

## 11. Files
| File | What |
|---|---|
| `build_tokens.py` | **Source of truth.** Generates tokens.json, tokens.css and tailwind.preset.js |
| `build_specimen.py` | Generates specimen.html from tokens.json, with live contrast ratios |
| `tokens.json` | W3C DTCG tokens: primitives, then light/dark semantic aliases |
| `tokens.css` | `--bm-*` variables, dark theme, card-font setting, reduced motion |
| `tailwind.preset.js` | ES-module Tailwind preset: scales plus `bm-*` role classes |
| `../frontend/src/brand/tokens.css`, `../frontend/brand.preset.js` | Frontend copies (generated), with Tailwind families aliased to brand scales (D-027) |
| `garden-r3.html` | Reference mock-ups: home, review (light and dark), Bai moments |
| `logo/` | Final logo files, `preview.html`, `archive/` |
| `archive/` | Round 1 specimen and the three-direction comparison |
| `decision-log.md` | Every decision, with its reason and source |

## 12. Governance
- Product code uses role tokens (`bm-*`), not raw scales or hex values (D-017).
- A new colour needs a decision-log entry, a `palette.py contrast` result and a CVD check.
- To change a colour, edit `build_tokens.py`, then run `build_tokens.py` and `build_specimen.py`.
- Ask for an audit at any time ("audit the frontend against the brand").
