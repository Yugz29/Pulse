"""La citation d'un `recorded_statement` n'est affichée que si elle ajoute au texte."""

import pytest

from pulse_intelligence.session_input import split_open_text
from pulse_intelligence.session_summary import quote_adds_to_text, render_open_items

PREFIX = "Point déclaré dans un commit : "
SENTENCE = "La règle de candidature existe en deux copies (Core, Intelligence) qui ont divergé entre #98 et 0.8.3.0"


def statement(text, quote="Pas de verdict.", evidence="o40"):
    item = {"kind": "recorded_statement", "text": text, "evidence": [evidence]}
    if quote is not None:
        item["quote"] = quote
    return item


def test_text_identical_to_the_quote_is_shown_once():
    # Cas b6262f70 du lot du 2026-09-17 : le modèle recopie la phrase du commit.
    rendered = render_open_items([statement(SENTENCE + ".", quote=SENTENCE + ".")])

    assert rendered == PREFIX + SENTENCE + "."
    assert "«" not in rendered and rendered.count("deux copies") == 1


def test_text_containing_the_quote_is_shown_without_it():
    text = "Le rapport le dit lui-même : pas de verdict, la décision reste à prendre"

    rendered = render_open_items([statement(text, quote="Pas de verdict.")])

    assert rendered == PREFIX + text + "."


def test_a_different_text_keeps_its_quote():
    text = "Aucun verdict n'a été rendu sur l'adoption de l'entrée compacte en production"

    rendered = render_open_items([statement(text, quote="Pas de verdict.")])

    assert rendered == PREFIX + text + " (« Pas de verdict. »)."


def test_a_quote_longer_than_the_text_is_kept():
    # Le texte est un fragment de la citation : elle en dit plus que lui.
    rendered = render_open_items([statement("Pas de verdict", quote="Pas de verdict. Mesure à refaire sur secteur.")])

    assert rendered.endswith("(« Pas de verdict. Mesure à refaire sur secteur. »).")


@pytest.mark.parametrize(
    "text, quote",
    [
        ("La mesure n'a pas été lancée : Mac sur batterie", "La mesure n’a pas été lancée : Mac sur batterie."),
        ("la  mesure n'a pas été\nlancée, mac sur batterie !", "La mesure n'a pas été lancée : Mac sur batterie."),
        ("« Pas de verdict »", "pas de verdict."),
        ("Reste à voir (cas 04) — o7", "reste à voir, cas 04 : o7"),
    ],
)
def test_whitespace_case_and_punctuation_do_not_make_a_quote_new(text, quote):
    assert not quote_adds_to_text(text, quote)
    assert " (« " not in render_open_items([statement(text, quote=quote)])


def test_inclusion_is_by_whole_words_and_in_order():
    # « verdict » n'est pas « verdicts », et l'ordre des mots compte.
    assert quote_adds_to_text("Plusieurs verdicts ont été rendus", "verdict")
    assert quote_adds_to_text("verdict de pas", "Pas de verdict.")
    assert not quote_adds_to_text("Donc : pas de verdict ce soir", "Pas de verdict.")


def test_a_missing_or_empty_quote_renders_the_text_alone():
    assert render_open_items([statement("Reste à voir", quote=None)]) == PREFIX + "Reste à voir."
    assert render_open_items([statement("Reste à voir", quote=" … ")]) == PREFIX + "Reste à voir."
    assert not quote_adds_to_text("Reste à voir", None)


def test_other_kinds_and_the_sentence_count_are_unchanged():
    failure = {"kind": "command_failure", "text": "make test a échoué", "evidence": ["o4"]}
    items = [failure, statement(SENTENCE, quote=SENTENCE), statement("Autre chose", quote="Pas de verdict")]

    rendered = render_open_items(items)

    assert rendered.startswith("Échec observé, sans résolution correspondante observée en fin de session : make test a échoué.")
    # Une phrase par point : l'alignement avec open_items (fiche `show`, annexe) tient.
    assert len(split_open_text(rendered)) == len(items)
    assert rendered.count("«") == 1
