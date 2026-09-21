"""Tests for the offline extraction path and the port comparison rule.

    python -m pytest tests/ -q

These cover the parts that run without an API key, which is exactly the part
the deployed app depends on.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from sdoc.compare.comparator import compare
from sdoc.compare.normalize import port, port_equal
from sdoc.extract.labels import extract_fields
from sdoc.schemas import ExtractedField, FieldStatus


# --- label reading --------------------------------------------------------

COLON_SI = """SHIPPING INSTRUCTION
Shipper: APRIL FAR EAST (M) SDN BHD
  TOWER 2, AVENUE 5; KUALA LUMPUR, MALAYSIA
Consignee (Non-Negotiable): EAST BRIGHT FZ-LLC
Notify: EAST BRIGHT FZ-LLC
Port of Loading (POL): NANTONG, CHINA (CNNTG)
POD: KARACHI, PAKISTAN (PKKHI)
Total Containers: 6 x 40'HC
Gross Wt (kgs): 131,058 KG
NET WEIGHT: 120,000 KG
"""

PIPE_BL = """BILL OF LADING (DRAFT)
Shipper (Principal or Seller) (发货人) | APRIL FINE PAPER TRADING
Consignee (收货人) | AL GURG STATIONERY LLC
Notify (通知人) | AL GURG STATIONERY LLC
PORT OF LOADING (装货港) | SINGAPORE
POD (卸货港) | KARACHI, PAKISTAN
Total Containers (箱数) | 12 x 20'FCL
Gross Wt (kgs) (毛重 KGS) | 243,588
"""

BARE_PDF = """BILL OF LADING INSTRUCTION
Shipper APRIL FINE PAPER TRADING (MIDDLE EAST) FZE
  P.O. BOX 293775, DUBAI
To the Order of TOPKOPY MIDDLE EAST FZE
Notify TOPKOPY MIDDLE EAST FZE
Port of Loading NHAVA SHEVA, INDIA
POD BUSAN, SOUTH KOREA
"""


def test_reads_colon_layout():
    fields = extract_fields(COLON_SI)
    assert fields["shipper"]["value"] == "APRIL FAR EAST (M) SDN BHD"
    assert fields["consignee"]["value"] == "EAST BRIGHT FZ-LLC"
    assert fields["port_of_loading"]["value"] == "NANTONG, CHINA (CNNTG)"
    assert fields["container_count"]["value"] == "6 x 40'HC"


def test_address_lines_are_not_part_of_the_party_name():
    assert "TOWER 2" not in extract_fields(COLON_SI)["shipper"]["value"]


def test_net_weight_is_never_read_as_gross():
    assert extract_fields(COLON_SI)["gross_weight_kg"]["value"] == "131,058 KG"


def test_reads_pipe_layout_with_bilingual_labels():
    fields = extract_fields(PIPE_BL)
    assert fields["shipper"]["value"] == "APRIL FINE PAPER TRADING"
    assert fields["gross_weight_kg"]["value"] == "243,588"
    assert fields["port_of_discharge"]["value"] == "KARACHI, PAKISTAN"


def test_reads_lines_that_lost_their_separator():
    fields = extract_fields(BARE_PDF)
    assert fields["consignee"]["value"] == "TOPKOPY MIDDLE EAST FZE"
    assert fields["port_of_loading"]["value"] == "NHAVA SHEVA, INDIA"
    assert fields["port_of_discharge"]["value"] == "BUSAN, SOUTH KOREA"


def test_notify_party_wins_over_consignee_on_a_combined_label():
    fields = extract_fields("Notify Party/Intermediate Consignee: ACME LTD\n"
                            "Consignee: OTHER LTD\n")
    assert fields["notify_party"]["value"] == "ACME LTD"
    assert fields["consignee"]["value"] == "OTHER LTD"


@pytest.mark.parametrize("printed", ["N/A", "___", "???", "  ", "TBA", "-"])
def test_placeholders_are_missing_not_values(printed):
    fields = extract_fields(f"Gross Wt (kgs): {printed}\n")
    assert fields["gross_weight_kg"]["value"] is None


# --- port comparison ------------------------------------------------------

@pytest.mark.parametrize("a,b,same", [
    ("PORT KLANG, MALAYSIA (MYPKG)", "PORT KLANG", True),
    ("ROTTERDAM", "ROTTERDAM, NETHERLANDS", True),
    ("NHAVA SHEVA, INDIA (INNSA)", "NHAVA SHEVA, INDIA", True),
    ("SINGAPORE", "SINGAPORE", True),
    ("BUSAN, SOUTH KOREA", "BUSAN, JAPAN", False),
    ("FREMANTLE, AUSTRALIA", "BUSAN, SOUTH KOREA", False),
    ("HAMBURG, GERMANY", "BREMEN, GERMANY", False),
])
def test_port_equal(a, b, same):
    assert port_equal(port(a), port(b)) is same


# --- the comparison as a whole -------------------------------------------

def _fields(values):
    return {k: ExtractedField(field=k, raw_value=v) for k, v in values.items()}


def test_a_country_suffix_on_one_side_is_not_a_discrepancy():
    si = _fields({"port_of_loading": "PORT KLANG, MALAYSIA (MYPKG)"})
    bl = _fields({"port_of_loading": "PORT KLANG"})
    row = next(c for c in compare(si, bl) if c.field == "port_of_loading")
    assert row.status is FieldStatus.MATCH


def test_a_different_port_is_still_caught():
    si = _fields({"port_of_discharge": "GENOA, ITALY"})
    bl = _fields({"port_of_discharge": "VALENCIA, SPAIN"})
    row = next(c for c in compare(si, bl) if c.field == "port_of_discharge")
    assert row.status is FieldStatus.MISMATCH


def test_units_are_reconciled_before_weights_are_compared():
    si = _fields({"gross_weight_kg": "88,400 KG"})
    bl = _fields({"gross_weight_kg": "88.4 MT"})
    row = next(c for c in compare(si, bl) if c.field == "gross_weight_kg")
    assert row.status is FieldStatus.MATCH


def test_a_blank_value_is_missing_not_a_mismatch():
    si = _fields({"container_count": "3 x 20'GP"})
    bl = _fields({"container_count": None})
    row = next(c for c in compare(si, bl) if c.field == "container_count")
    assert row.status is FieldStatus.MISSING


# --- .env loading ---------------------------------------------------------

def test_env_file_is_read(tmp_path, monkeypatch):
    from sdoc.config import load_env
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text('# a comment\nexport GEMINI_API_KEY="abc-123"\n\n'
                   'GEMINI_MODEL=gemini-3.6-pro\n')
    applied = load_env(env)
    assert applied == {"GEMINI_API_KEY": True, "GEMINI_MODEL": True}
    import os
    assert os.environ["GEMINI_API_KEY"] == "abc-123"
    assert os.environ["GEMINI_MODEL"] == "gemini-3.6-pro"


def test_a_real_environment_variable_wins_over_the_file(tmp_path, monkeypatch):
    from sdoc.config import load_env
    monkeypatch.setenv("GEMINI_API_KEY", "from-the-host")
    env = tmp_path / ".env"
    env.write_text("GEMINI_API_KEY=from-the-file\n")
    load_env(env)
    import os
    assert os.environ["GEMINI_API_KEY"] == "from-the-host"


def test_a_missing_env_file_is_not_an_error(tmp_path):
    from sdoc.config import load_env
    assert load_env(tmp_path / "nope.env") == {}


def test_describe_never_prints_the_key(monkeypatch):
    from sdoc.config import describe
    monkeypatch.setenv("GEMINI_API_KEY", "super-secret-value")
    assert "super-secret-value" not in describe()


# --- the demo inbox and stage 1 -------------------------------------------

def test_demo_inbox_covers_every_category():
    """A demo inbox that cannot show all five categories cannot show the
    classification stage working."""
    from sdoc.classify import rules
    from sdoc.schemas import Category
    from web.demo_inbox import DemoInbox

    seen = set()
    for email in DemoInbox().emails():
        category, _, _ = rules.classify(email)
        assert category is not None, f"{email['email_id']} was not classified"
        seen.add(category)
    assert seen == set(Category), f"missing: {set(Category) - seen}"


def test_demo_inbox_runs_through_the_real_pipeline():
    """DemoInbox must satisfy the slice of Inbox that process_email uses."""
    from sdoc import pipeline
    from sdoc.extract.labels import LabelExtractor
    from sdoc.schemas import Category, Status
    from web.demo_inbox import DemoInbox

    inbox = DemoInbox()
    extractor = LabelExtractor()
    results = {e["email_id"]: pipeline.process_email(inbox, e, None, extractor)
               for e in inbox.emails()}

    assert results["demo_001"].status is Status.OK           # clean pair
    assert results["demo_002"].status is Status.MISMATCH     # real discrepancy
    assert set(results["demo_002"].defect_fields) == {"consignee", "container_count"}
    assert results["demo_003"].status is Status.NEEDS_REVIEW  # blank value
    assert results["demo_004"].status is Status.NEEDS_REVIEW  # wrong document
    assert results["demo_005"].status is Status.NEEDS_REVIEW  # claims an attachment
    assert results["demo_012"].category is Category.SPAM
    assert results["demo_012"].status is Status.OK            # nothing to compare
