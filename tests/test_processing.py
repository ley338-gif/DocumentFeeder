import pytest

from document_core.connectors import parse_document_date
from document_core.processing import RuleBasedProcessor, WorkflowRules


def test_rule_based_processing_extracts_type_and_metadata():
    text = """Bericht\nBetreff: Beispielobjekt\nDatum: 12.03.2026\nReferenz: R-123"""
    document_type, metadata = RuleBasedProcessor().process(text)
    assert document_type == "report"
    assert metadata == {
        "subject_name": "Beispielobjekt",
        "document_date": "12.03.2026",
        "reference_id": "R-123",
    }


def test_unknown_document_is_quarantined_by_rules():
    assert WorkflowRules().validate("unknown") == ["Dokumenttyp konnte nicht bestimmt werden"]


def test_connector_policy_can_require_routing_reference():
    assert WorkflowRules(require_routing_reference=True).validate("report") == [
        "Routing-Referenz fehlt"
    ]


def test_invoice_extracts_supplier_and_numeric_document_date():
    document_type, metadata = RuleBasedProcessor().process(
        "Telekom Deutschland GmbH, 53171 Bonn Datum\n"
        "Rechnungsnummer 730 753 0647\nFestnetz-Rechnung\n26.06.2026"
    )

    assert document_type == "invoice"
    assert metadata["supplier_name"] == "Telekom Deutschland GmbH"
    assert metadata["document_date"] == "26.06.2026"
    assert metadata["invoice_number"] == "730 753 0647"


@pytest.mark.parametrize(
    ("value", "month"),
    [
        ("Januar 2026", 1),
        ("15. Februar 2026", 2),
        ("März 2026", 3),
        ("April 2026", 4),
        ("Mai 2026", 5),
        ("Juni 2026", 6),
        ("Juli 2026", 7),
        ("August 2026", 8),
        ("September 2026", 9),
        ("Oktober 2026", 10),
        ("November 2026", 11),
        ("Dezember 2026", 12),
    ],
)
def test_german_month_names_are_parsed(value: str, month: int):
    assert parse_document_date(value).month == month
