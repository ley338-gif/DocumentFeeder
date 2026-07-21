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
