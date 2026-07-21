from document_core.processing import RuleBasedProcessor, WorkflowRules


def test_rule_based_processing_extracts_type_and_metadata():
    text = """Arztbrief\nPatient: Erika Mustermann\nGeburtsdatum: 12.03.1980\nFallnummer: F-123"""
    document_type, metadata = RuleBasedProcessor().process(text)
    assert document_type == "arztbrief"
    assert metadata == {
        "patient_name": "Erika Mustermann",
        "birth_date": "12.03.1980",
        "case_id": "F-123",
    }


def test_unknown_document_is_quarantined_by_rules():
    assert WorkflowRules().validate("unknown", {}) == ["Dokumenttyp konnte nicht bestimmt werden"]

