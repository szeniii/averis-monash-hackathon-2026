"""A small inbox for instances that have no dataset.

The organisers' 520-email bundle is gitignored, so a deployed instance has
nothing to browse. These thirteen emails stand in: written for this repo,
shaped like the real records, and spread across all five categories so the
classification stage has something to show.

Nothing here is hard-coded to a category. The classifier reads these exactly
as it reads the real inbox, which is the point -- a demo that announced the
answer would prove nothing.

`DemoInbox` implements the slice of `sdoc.loader.Inbox` the pipeline uses,
so it drops straight into `pipeline.process_email`.
"""
from __future__ import annotations

from web.demo_cases import BY_ID

# Attachment text, keyed by the path the email records refer to. The four
# comparison pairs are the same documents the Demo tab uses.
ATTACHMENTS: dict = {}
for _cid, _case in BY_ID.items():
    ATTACHMENTS[f"attachments/{_cid}_SI.txt"] = _case["si"]
    ATTACHMENTS[f"attachments/{_cid}_BL.txt"] = _case["bl"]


def _email(eid, sender, subject, body, attachments=()):
    return {"email_id": eid, "from": sender, "subject": subject,
            "body": body, "attachments": list(attachments)}


EMAILS = [
    # --- comparison requests, one per branch of the decision gate ---------
    _email(
        "demo_001", "docs@meridianpulp.com.my",
        "REQUEST BL DRAFT _ PO 41882 _ BLEACHED KRAFT PULP",
        "Hi Mitchelle,\n\nAttached are the SI and draft BL for OC 7MRD-04412.\n"
        "Please check the details and confirm.\n\nBest Regards,\nSiti Rahmah\n"
        "Shipping Documentation\nMeridian Pulp (M) Sdn Bhd",
        ["attachments/clean_SI.txt", "attachments/clean_BL.txt"]),

    _email(
        "demo_002", "exports@apexboard.sg",
        "AFSG - GENOA_ITALY - APEXB(MCLSIN4471092) - 3TQW-11847",
        "Dear team,\n\nTo confirm docs for the shipment below. SI and draft BL "
        "attached.\n\nRegards,\nLee Wei Ming\nApex Board Mills Limited",
        ["attachments/mismatch_SI.txt", "attachments/mismatch_BL.txt"]),

    _email(
        "demo_003", "shipping@harboursidetimber.com",
        "Draft BL for your confirmation - HAMBURG",
        "Hello,\n\nPlease verify the draft BL against our SI and revert with "
        "any amendments.\n\nThanks,\nAndreas Koll",
        ["attachments/blank_SI.txt", "attachments/blank_BL.txt"]),

    _email(
        "demo_004", "documentation@cedarpoint.com.my",
        "Check the details - JEBEL ALI shipment",
        "Hi,\n\nAttached are the SI and the draft BL. Kindly compare and "
        "confirm before we finalise.\n\nRegards,\nNur Aisyah",
        ["attachments/wrongdoc_SI.txt", "attachments/wrongdoc_BL.txt"]),

    _email(
        "demo_005", "ops@northwindshipping.com",
        "REQUEST BL DRAFT - urgent, please confirm docs",
        "Hi Mitchelle,\n\nPlease find attached the SI and draft BL for this "
        "week's booking. Let me know if anything differs.\n\nThanks,\n"
        "Gregor Halvorsen",
        []),   # refers to attachments that are not there -> escalation

    # --- requests to prepare a new SI -------------------------------------
    _email(
        "demo_006", "cs@pacificrimlogistics.com",
        "SI - BOOKING ONEYSIN4471203 - PORT KLANG",
        "Dear Documentation Team,\n\nKindly submit SI for the booking below by "
        "Thursday cut-off.\n\nBooking: ONEYSIN4471203\nVessel: MAERSK "
        "SENTOSA\n\nThank you,\nCarmen Ho"),

    _email(
        "demo_007", "bookings@tradewindfreight.com",
        "CUST SI needed for AUG shipment",
        "Hi,\n\nWe need SI prepared for the August shipment to Rotterdam. "
        "Please send us the SI once ready.\n\nRegards,\nPieter van Leeuwen"),

    # --- invoice and billing ----------------------------------------------
    _email(
        "demo_008", "accounts@globalfreightsolutions.com",
        "Invoice INV-2026-04471 - local charges query",
        "Dear Sir/Madam,\n\nWe note the local charges on invoice "
        "INV-2026-04471 differ from the quoted rate. Could you clarify the "
        "THC component?\n\nRegards,\nAccounts Payable"),

    _email(
        "demo_009", "billing@oceanlinkcarriers.com",
        "Demurrage and detention charges - container MSKU7741029",
        "Hello,\n\nPlease find our debit note for demurrage accrued on the "
        "container above. Payment terms 30 days.\n\nBilling Department"),

    # --- operational noise -------------------------------------------------
    _email(
        "demo_010", "noreply@portauthority.gov.my",
        "Weekly report - berthing report week 38",
        "Automated notice.\n\nThe berthing report for week 38 is now "
        "available on the portal. No action required."),

    _email(
        "demo_011", "hr@aprilasia.com",
        "Public holiday notice - Malaysia Day",
        "Dear all,\n\nPlease note the office will be closed on 16 September "
        "for the public holiday. Normal operations resume the following "
        "day.\n\nHuman Resources"),

    # --- spam ---------------------------------------------------------------
    _email(
        "demo_012", "no-reply@parcel-delivery-notice.info",
        "Your unclaimed parcel is waiting - customs fee of USD 2.99",
        "Congratulations! You have an unclaimed parcel held at our depot. "
        "Click here to pay the outstanding customs fee of USD 2.99 and "
        "release your delivery."),

    _email(
        "demo_013", "alerts@mail-storage-secure.net",
        "Action required: your mailbox is full",
        "Your mailbox storage is full and incoming messages are being "
        "rejected. Verify your account within 24 hours to restore service. "
        "Click the link below to continue."),
]

BY_EMAIL_ID = {e["email_id"]: e for e in EMAILS}


class DemoInbox:
    """The slice of sdoc.loader.Inbox that the pipeline actually calls."""

    source = "built-in demo inbox"
    is_real = False

    def emails(self):
        return [dict(e) for e in EMAILS]

    def __iter__(self):
        return iter(self.emails())

    def get(self, email_id):
        record = BY_EMAIL_ID.get(email_id)
        return dict(record) if record else None

    def read_bytes(self, att_path):
        text = ATTACHMENTS.get(att_path)
        if text is None:
            raise FileNotFoundError(att_path)
        return text.encode("utf-8")

    def read_text(self, att_path, encoding="utf-8"):
        return self.read_bytes(att_path).decode(encoding, errors="replace")
