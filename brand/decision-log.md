# Baimai brand: decision log

Every decision records what was decided, why, how strong the evidence is, and who chose it.
Evidence labels: `standard` (normative spec), `research` (empirical study), `convention` (industry practice), `judgement` (design reasoning).
Contrast ratios come from `palette.py contrast` (WCAG 2.2 relative luminance), not from estimates.

## Questions asked

| # | Date | Question | Answer |
|---|---|---|---|
| Q-1 | 2026-11-26 | Personality / feel | "Rooted in Thailand" |
| Q-2 | 2026-11-26 | Open to renaming from Dek-Kard? | Explore alternatives |
| Q-3 | 2026-11-26 | Keep the current purple? | Open to a new primary |
| Q-4 | 2026-11-26 | Surfaces in scope | Web app UI + tokens, logo + app icon, dark mode, marketing / README / social |
| Q-5 | 2026-11-26 | Shortlist names | Baimai |
| Q-6 | 2026-11-26 | Lock in Baimai? | "Yes. But just check for any rude connotations" |
| Q-7 | 2026-11-26 | Colour direction | "A okay for colour" (banana leaf + marigold) |
| Q-8 | 2026-11-26 | Accessibility target | WCAG 2.2 AA |
| Q-9 | 2026-11-26 | Thai typeface | "There should be a setting for different fonts. There are fonts that are sometimes harder to read for new learners" |
| Q-10 | 2026-11-26 | Round 1 feedback; which direction | "They look like a bank"; "B looks best… the schoolbook background has some strengths. I don't like the jokes" |
| Q-11 | 2026-11-26 | Mascot | "Actually the leaf can stay" |
| Q-12 | 2026-11-26 | App icon | "bai on the paper" |

## Decisions

### D-001 Rename from Dek-Kard to Baimai (ใบไม้)
- **Decision:** The product is called Baimai, written ใบไม้ in Thai. The working name Dek-Kard is retired.
- **Why:** เด็ก ("kid") makes the old name read as a children's product to Thai speakers. ใบไม้ means "leaf", and ใบ (bai) is also the Thai classifier for cards, so a deck of cards is literally a pile of leaves. This gives a growth metaphor for spaced repetition and an obvious visual world.
- **Evidence:** judgement
- **Sources:** naming method from Alexandra Watkins, *Hello, My Name Is Awesome* (SMILE/SCRATCH tests).
- **Alternatives considered:** Jamdai (จำได้, "I remember"), Sip Bai (สิบใบ, "ten cards"), Rianroo, Gor Gai (a "Kor Kai" baby flashcard app exists), Kaojai (kaojai.app taken), keeping Dek-Kard.
- **User input:** Q-5, Q-6
- **Assumed:** no

### D-002 First-pass clearance for Baimai: risk low to moderate
- **Decision:** Proceed with Baimai. A trade mark attorney should advise before any filing.
- **Why:** TMview (searched 2026-11-26) shows about 100 BAIMAI-like marks. The only exact BAIMAI in a likely class (9 software, 41 education, 42 software services) is CNIPA 15949274, class 41, China, owned by a medical-investment company. Nothing exact was found in UK, EU or US registers in 9/41/42. Thailand (DIP) has many BAIMAI / ใบไม้ marks in unrelated classes (cosmetics, food, apparel), because it's an everyday word. That makes the name weak to defend in Thailand, but it isn't blocked. No app called Baimai was found in the App Store. Domains: baimai.com is taken. baimai.app, baimai.co.uk, baimai.io, baimai.dev and getbaimai.com have no nameservers (likely free; this is a DNS check, not a registrar check).
- **Evidence:** convention (first-pass search, not legal clearance)
- **Sources:** TMview https://www.tmdn.org/tmview/ (basic search "baimai"); App Store search via web.
- **Likely Nice classes:** 9, 41, 42.
- **Assumed:** no

### D-003 Connotation check for Baimai
- **Decision:** No rude or negative connotation found.
- **Why:** Thai and Lao: ใบไม้ / ໃບໄມ້ means "leaf", which is neutral to positive. A tone slip by learners gives harmless phrases such as ไปไหม ("shall we go?"). Vietnamese "bài mai" reads as "tomorrow's lesson", a happy accident. Mandarin homophones include 百脉 (a TCM term) and 白卖 ("sell for nothing", unflattering but not rude). In Hindi and Marathi, "bai" can mean a domestic worker, which is mild. A web search for slang meanings found nothing.
- **Evidence:** judgement (Claude's language knowledge plus one web search). **Get a native Thai speaker to check before launch.**
- **Assumed:** no

### D-004 Primary colour: banana-leaf green #2E7D4F (brand-600)
- **Decision:** The brand anchor is #2E7D4F, oklch(0.529 0.106 154.6).
- **Why:** It ties directly to the name (a leaf). Mid-dark lightness and moderate chroma read as calm and competent rather than loud (Labrecque & Milne 2012: saturation and value shape perceived personality; effects are modest and depend on context). It is deliberately darker and bluer than Duolingo's lime #58CC02, which is the dominant green in language learning. White text on it measures 5.05:1, so it works as a button fill.
- **Evidence:** judgement, supported by research (with caveats)
- **Sources:** Labrecque & Milne (2012), doi:10.1007/s11747-010-0245-y
- **Alternatives considered:** B, celadon #1F6B52 with lacquer red; C, kram indigo #2B3F8C with marigold.
- **User input:** Q-7
- **Assumed:** no

### D-005 Accent colour: marigold #E8A317
- **Decision:** Marigold (ดาวเรือง, the flower of offering garlands) is the accent, used only for reward moments: streaks, XP, achievements, celebration.
- **Why:** It gives warm contrast to the green and has a clear Thai source. White on marigold measures 2.17:1 (fails), so text on marigold is always marigold-950 (7.66:1). As text on white, marigold-700 #775100 measures 7.09:1.
- **Evidence:** judgement, with standard contrast checks
- **Sources:** WCAG 2.2 SC 1.4.3 https://www.w3.org/TR/WCAG22/#contrast-minimum
- **Assumed:** no

### D-006 Scales: 11-step OKLCH, 50 to 950
- **Decision:** Every hue gets an 11-step scale from `palette.py scale` with constant hue, even L steps and chroma reduced to fit sRGB. brand-900 has reduced chroma (sRGB clip).
- **Why:** In OKLCH, equal L steps look like equal lightness steps; HSL doesn't do this. 50 to 950 matches Tailwind, which the app already uses.
- **Evidence:** research (OKLab), convention (step naming)
- **Sources:** Ottosson (2020) https://bottosson.github.io/posts/oklab/ ; CSS Color 4 https://www.w3.org/TR/css-color-4/ ; Tailwind colours https://tailwindcss.com/docs/colors
- **Assumed:** no

### D-007 Neutrals tinted towards leaf green
- **Decision:** The neutral scale is seeded at oklch(0.55 0.012 154.6), anchor #6c746e.
- **Why:** A small chroma in the brand hue makes the greys feel related to the brand. Radix and Tailwind ship tinted greys.
- **Evidence:** judgement / convention
- **Sources:** Radix Colors https://www.radix-ui.com/colors/docs/palette-composition/understanding-the-scale
- **Assumed:** no

### D-008 Success uses the brand green, always with an icon and a label
- **Decision:** There is no separate success hue. "Correct" and "success" use the brand scale (brand-100 bg with brand-800 text, 8.05:1) and always carry a ✓ icon and words.
- **Why:** A distinct teal success colour (#0F7A6E) was tested. Its OKLab distance from the brand green was 0.051 in normal vision and 0.007 under tritanopia, so the two were effectively indistinguishable. Leaf green meaning "you got it, it grew" also fits the name. WCAG requires that colour is never the only cue.
- **Evidence:** standard (1.4.1), judgement
- **Sources:** WCAG 2.2 SC 1.4.1 https://www.w3.org/TR/WCAG22/#use-of-color ; Machado et al. (2009) CVD model (palette.py cvd)
- **Assumed:** no

### D-009 Danger: lacquer red, anchored at #A21F1B (danger-700)
- **Decision:** The danger scale comes from #B8322A, but the danger role uses the darker #A21F1B for text and fills.
- **Why:** At equal lightness, brand-600 and #B8322A collapse under deuteranopia (OKLab distance 0.054, flagged). Darkening danger to #A21F1B adds a lightness difference (deuteranopia 0.073, not flagged). Correct and wrong is the most important colour pair in a flashcard app, so it also always carries ✓ / ✕ icons. #A21F1B on white measures 7.64:1.
- **Evidence:** standard, judgement
- **Sources:** WCAG 2.2 SC 1.4.1 ; Machado et al. (2009)
- **Assumed:** no

### D-010 Warning: burnt orange #C25E0A; info: kram indigo #3D539F
- **Decision:** Warning is built on #C25E0A, used as a tinted bg (#FFE8DA) with text #6C3000 (8.64:1). Solid warning fills use #E28A54 with text #4F2100 (5.16:1). Info uses kram (Sakon Nakhon indigo) #3D539F; white on it measures 7.15:1.
- **Why:** Warning has to stay apart from the marigold accent: OKLab distance from marigold is 0.183, and from danger it is ≥0.076 in every simulation. The #C25E0A solid sat close to brand green under protanopia (0.059), so solid warning fills use the lighter #E28A54 (0.115). Indigo reuses direction C's Thai source for a role that needs a cool, non-green hue.
- **Evidence:** convention (semantic hues per Material/Apple HIG), judgement
- **Sources:** Material 3 colour roles https://m3.material.io/styles/color/system/overview
- **Assumed:** yes, review

### D-011 Text and border steps (light mode)
- **Decision:** Body text neutral-900 (13.07:1 on white). Secondary text neutral-700 (6.90:1). The lightest allowed text is neutral-600 (4.82:1). neutral-500 (3.55:1) is for input borders and icons only, never text. Dividers (neutral-200) are decorative and exempt.
- **Why:** WCAG 1.4.3 requires 4.5:1 for text and 1.4.11 requires 3:1 for UI boundaries. The app currently uses `text-gray-400` 197 times, which is about 2.5:1 on white and fails.
- **Evidence:** standard
- **Sources:** WCAG 2.2 SC 1.4.3, SC 1.4.11 https://www.w3.org/TR/WCAG22/#non-text-contrast
- **Assumed:** no

### D-012 Dark mode is re-mapped, not inverted
- **Decision:** Page neutral-950 #1c201d, cards neutral-900. Body text neutral-100 (14.10:1). Secondary text neutral-400 (6.55:1). Brand filled buttons use brand-400 #79b38c with brand-950 text (6.65:1). Links use brand-400 (6.78:1). Danger text #EA8073 (6.15:1). Marigold keeps marigold-300 with marigold-950 text.
- **Why:** Inverting puts a saturated mid green on a near-black background, which glares and fails contrast. Re-picking scale steps keeps every pair at AA or better.
- **Evidence:** standard (contrast), convention (Material 3 / Apple HIG dark elevation)
- **Sources:** WCAG 2.2 SC 1.4.3 ; Apple HIG Color https://developer.apple.com/design/human-interface-guidelines/color
- **Assumed:** no

### D-013 Thai card-face font is a user setting; looped by default (pending review of specimen)
- **Decision:** Card faces render Thai in a font the user chooses in Settings: Learner (looped), Classic, Real-world (loopless) or Handwriting. The proposed default is Noto Sans Thai Looped. The UI chrome uses Anuphan.
- **Why:** The user asked for a setting (Q-9). The evidence on looped vs loopless is mixed. A 2024 Chulalongkorn study commissioned by Typotheque found readers *rated* looped fonts more legible, while reports differ on whether reading performance changed. Younger readers did better with loopless forms at small sizes. Thai school primers use looped forms, while signage and the web increasingly use loopless, so learners need both.
- **Evidence:** research (mixed, single study, partly reported by a commercial stakeholder), convention
- **Sources:** ATypI 2025 abstract https://atypi.org/?p=34632 ; Granshan / Typotheque https://granshan.com/insights/bridging-cultures-through-letters-typotheques-typographic-journey-in-thailand
- **Correction:** an earlier question in this session described Sarabun as loopless. That was wrong: Sarabun is looped.
- **Assumed:** yes, until the user reviews the specimen

### D-014 Existing config bug noted
- **Decision:** When tokens are applied, define every brand step (50 to 950).
- **Why:** `frontend/tailwind.config.js` defines only brand 50/100/500/600/700, but the code uses brand-200/300/400/800, so those classes currently produce no CSS.
- **Evidence:** judgement (code inspection)
- **Assumed:** no

### D-015 UI typeface: Anuphan
- **Decision:** UI chrome uses Anuphan (Thai + Latin, loopless, OFL). Card faces use the D-013 setting.
- **Why:** One family covers both scripts with matched metrics. Loopless forms suit short UI labels, and the learner-focused looped font is kept for card faces, where legibility matters most. Each font was confirmed available on Google Fonts (HTTP 200, 2026-11-26).
- **Evidence:** judgement
- **Assumed:** yes, review

### D-016 Chart palette
- **Decision:** Categorical series in light mode are leaf-600 #2E7D4F, kram-800 #2B3D81, marigold-500 #B37B00, orchid #A3478E and neutral-500 #828A84. Dark mode uses #79B38C, #CAD8FE, #E8A317, #C0549F and #BDC2BE. Sequential (mastery) data uses the leaf scale.
- **Why:** The first attempt flagged leaf vs kram-600 under tritanopia (0.039) and marigold-400 at 2.57:1 on white. Darkening kram and using marigold-500 cleared every pair. In dark mode, kram-400 vs orchid was flagged under protanopia and deuteranopia, which the lightness spread (kram-200, orchid #C0549F) fixed. No flagged pairs remain, and every series is ≥3:1 on its background. Status colours stay out of charts.
- **Evidence:** research (CVD model), standard (1.4.11, 1.4.1)
- **Sources:** Machado et al. (2009) ; ColorBrewer https://colorbrewer2.org/ ; WCAG 2.2 SC 1.4.11
- **Assumed:** no

### D-017 Three-tier tokens; product code uses roles only
- **Decision:** `build_tokens.py` generates tokens.json (DTCG), tokens.css and tailwind.preset.js. Light and dark differ only in the semantic tier. Product code uses `bm-*` role classes.
- **Why:** This makes a brand change a one-file edit. The preset is an ES module because the frontend has `"type": "module"`.
- **Evidence:** convention
- **Sources:** Design Tokens Format Module 2025.10 https://www.designtokens.org/TR/2025.10/format/
- **Assumed:** no

### D-018 Shape and motion follow "calm growth"
- **Decision:** Radius 6/10/14, plus an 18px "leaf" radius for flashcards. Motion durations 120/220/420ms with a "settle" ease-out curve. Reduced motion sets durations to 0.
- **Why:** These follow principle 2 (calm growth). Rounded but not bubbly suits adult learners. WCAG 2.3.3 (animation from interactions) is AAA, but users widely expect it to be honoured.
- **Evidence:** judgement, standard (2.3.3, AAA)
- **Sources:** WCAG 2.2 SC 2.3.3 https://www.w3.org/TR/WCAG22/#animation-from-interactions
- **Assumed:** yes, review

### D-019 Logo round 1: four concepts; colour fixes for graphic contrast
- **Decision:** Four concepts were shown: (3) บ ใบไม้ letter with a leaf terminal (recommended), (1) leaf card, (2) fanned deck, (4) looped leaf. In concept 3, the marigold leaf uses marigold-500 on light backgrounds (3.39:1), marigold-200 on the leaf tile (3.54:1) and marigold-300 on dark (7.60:1).
- **Why:** marigold-300 measured 2.02:1 on the light canvas and 2.33:1 on leaf-600, below the 3:1 for graphics. Flags: concept 2's three-leaf fan sits near cannabis iconography. Concept 4 starts to look like a ladle at 18px.
- **Evidence:** standard (1.4.11), judgement
- **User input:** pending
- **Assumed:** n/a

### D-020 Round 1 read as "a bank": mood reset towards Garden (direction B)
- **Decision:** Move from the calm, dark direction to "Garden", plus the ruled-paper canvas from "Schoolbook". This supersedes the mood of D-004, D-007, D-012, D-015 and D-018 (to be regenerated once confirmed).
- **Why:** The user said round 1 looked "like a bank". Causes identified: a dark, muted green with gold (Thai banks are colour-coded, and Kasikorn is green), a grey-green neutral canvas, flat geometric marks on rounded tiles (the fintech icon formula), white text on dark fills, and no character. Darker, less saturated colour reads as competent and serious (Labrecque & Milne 2012, caveats as before).
- **Changes:** primary moves to a brighter leaf #3DA35D, oklch(0.639 0.140 150.7), with leaf-950 text (5.09:1). It stays well away from Duolingo's #58CC02 (chroma 0.14 vs 0.23, L 0.64 vs 0.75). Neutrals are re-seeded warm (oklch 0.55 0.012 85, anchor #75716A) on a paper canvas #FFFAF2 with 1px ruled lines #F1E9DA. Headings use Mitr (rounded). Buttons are chunky, with a 4px darker bottom edge. Deck identity colours: leaf, marigold #F2B33D, kram #2652B0, orchid #B98ADB.
- **Evidence:** judgement, research (with caveats)
- **User input:** Q-10 (2026-11-26): "B looks best… the schoolbook background has some strengths. I don't like the jokes, they are not funny."
- **Assumed:** no

### D-021 Plain copy; no jokes
- **Decision:** Product copy is plain and factual ("20 cards due", "All done for today"). No puns or cute phrasing ("leaves to water").
- **Why:** The user's direct instruction (Q-10).
- **Evidence:** judgement
- **Assumed:** no

### D-022 Bai the leaf is the brand mascot, used only at the edges of a session
- **Decision:** Bai (a leaf with a face) appears in empty states, milestones, triage prompts and help. Bai never appears on card faces or during a review. Marigold Bai appears only for milestones.
- **Why:** User decision: "Actually the leaf can stay". Keeping Bai away from the study surface follows principle 3 (the learner's eye comes first).
- **User input:** Q-11 (2026-11-26)
- **Assumed:** no

### D-023 Deck colours re-chosen for colour-vision deficiency
- **Decision:** Deck tints are leaf-100, marigold-100, kram-100 and orchid-100, each with its 700/800 text (6.00 to 8.66:1). Progress meters inside them use leaf-600, #B17D00, kram-700 and #855BA2 (≥3:1 on their tints).
- **Why:** The first B palette flagged leaf vs pink (deuteranopia 0.034) and leaf vs blue (tritanopia 0.057). A deep lotus pink cleared green but sat beside the danger red (normal 0.078, tritanopia 0.040). Purple next to a mid blue collapsed under protanopia. The final set (#3DA35D, #F2B33D, #2652B0, #B98ADB, with danger #A21F1B) has no flagged pairs. The first meter fills (marigold-300, orchid-400) measured 1.58:1 and 2.30:1, so they were darkened.
- **Evidence:** research (CVD model), standard (1.4.11)
- **Assumed:** no

### D-024 Chart palette for Garden (supersedes D-016)
- **Decision:** Categorical series in light mode are leaf-700 #006C31, marigold-500 #B17D00, kram-500 #5B85D8, orchid-600 #855BA2 and neutral-500 #8B8780. Dark mode uses leaf-400, marigold-300, kram-300, orchid-400 and neutral-300.
- **Why:** Using deck colours directly failed. Leaf-600 vs marigold-500 was flagged under protanopia (0.048), and leaf-700 vs kram-700 under tritanopia (0.046). Lightening kram to 500 cleared every pair, and each series is ≥3:1 on white.
- **Evidence:** research (CVD model), standard (1.4.11)
- **Assumed:** no

### D-025 Logo: Bai on paper
- **Decision:** The app icon is Bai on a full-bleed paper (#FFFAF2) square. There is a dark variant on #211F1B. The lockup is Bai plus a hand-drawn monoline "baimai" wordmark with leaf i-dots. The favicon is a plain leaf with a midrib.
- **Why:** User choice from three icon options. A cream tile stands out on a home screen among green-tile apps (banks, Duolingo). At 18px Bai's face turns to mush, so a plain leaf is used below 24px. In the first render Bai filled only about 45% of the tile, so it was scaled up to about 65% (still inside common safe areas). The wordmark is drawn as stroke paths so files don't depend on fonts.
- **Contrast:** wordmark leaf-800 on paper 9.05:1, leaf-300 on dark 9.50:1. Bai and leaf dots, leaf-500, are 3.06:1 on paper and 5.17:1 on dark. All are ≥3:1 for graphics (WCAG 1.4.11).
- **User input:** Q-12 (2026-11-26): "bai on the paper"
- **Assumed:** no

### D-026 Garden tokens regenerated
- **Decision:** `build_tokens.py` now uses the Garden scales (leaf #3DA35D, marigold #F2B33D, warm neutral, kram #2652B0, orchid #B98ADB), paper primitives, deck roles, the Mitr display font, and radii 8/14/20/26. `build_specimen.py` regenerates the specimen with live contrast ratios: 0 failing pairs in light and dark.
- **Changes to roles:** text.on-brand is leaf-950 in both modes. Hover goes *lighter*, because leaf-950 on leaf-600 is only 3.47:1. Focus moves to leaf-700 in light mode.
- **Evidence:** standard (contrast), convention (token tiers)
- **Assumed:** no

### D-027 Applying the brand to the frontend
- **Decision:** `build_tokens.py` also writes `frontend/src/brand/tokens.css` and `frontend/brand.preset.js`, because the Docker build copies only `frontend/`. The preset aliases the app's existing Tailwind families onto brand scales: gray→neutral, brand/green→leaf, red→lacquer, amber→ember (amber means "needs attention" in this app), orange/yellow→marigold, blue/indigo/sky/teal→kram, purple/pink→orchid. Scales use literal hex values so opacity modifiers such as `bg-brand-50/60` keep working.
- **Contrast migration:** a one-off script raised every text step that would fail AA after remapping (434 changes: 197× `text-gray-400`, 102× `text-gray-500` → 600; brand text → 700; grey text on grey-100/200 fills → 700). Solid green buttons were changed from white on brand-600 to leaf-950 on brand-500 (20 lines). Control borders `gray-300` (about 1.8:1) became `gray-500` (3.35:1 on paper). Chart hex values in InsightsPanel were replaced with brand chart colours.
- **No automatic dark mode in the app:** the frontend token copy leaves out the `prefers-color-scheme` block. The components use fixed light classes, so flipping only the role variables would produce a half-dark UI. `[data-theme='dark']` is ready for when dark mode is built.
- **Card font:** a new server-side preference `card_font` (learner | classic | realworld | handwriting; migration a8b9c0d1e2f3, tests in `tests/test_card_font_preference.py`). Layout sets `data-card-font` on `<html>`, and `.thai` and `font-thai` read `--bm-font-card`.
- **Rename scope:** user-facing only (title, nav, FastAPI title, README, CHANGELOG, deploy comment). Not renamed: the repo, the npm package name, release artifact names, the Azure User-Agent and the Anki note-type name "Dek-Kard Thai". Renaming the note type could make Anki create a duplicate note type for people re-importing decks.
- **Evidence:** standard (contrast), convention (token tiers), judgement (scope)
- **Assumed:** yes, for the rename scope and the amber→warning mapping

## Sources
- Design Tokens Format Module 2025.10: https://www.designtokens.org/TR/2025.10/format/
- ColorBrewer: https://colorbrewer2.org/
- WCAG 2.2: https://www.w3.org/TR/WCAG22/
- CSS Color Module Level 4: https://www.w3.org/TR/css-color-4/
- Ottosson, "A perceptual color space for image processing" (2020): https://bottosson.github.io/posts/oklab/
- Machado, Oliveira & Fernandes (2009), IEEE TVCG 15(6): https://www.inf.ufrgs.br/~oliveira/pubs_files/CVD_Simulation/CVD_Simulation.html
- Labrecque & Milne (2012), J. Academy of Marketing Science 40, 711–727, doi:10.1007/s11747-010-0245-y
- Radix Colors: https://www.radix-ui.com/colors/docs/palette-composition/understanding-the-scale
- Tailwind CSS colours: https://tailwindcss.com/docs/colors
- Material Design 3 colour: https://m3.material.io/styles/color/system/overview
- Apple HIG colour: https://developer.apple.com/design/human-interface-guidelines/color
- TMview: https://www.tmdn.org/tmview/
- ATypI 2025, looped vs loopless Thai: https://atypi.org/?p=34632
- Granshan / Typotheque: https://granshan.com/insights/bridging-cultures-through-letters-typotheques-typographic-journey-in-thailand
- Alexandra Watkins, *Hello, My Name Is Awesome*
