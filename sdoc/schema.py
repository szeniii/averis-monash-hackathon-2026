"""Shared types. Kept minimal for now — extend as later stages land."""
from enum import Enum

class Category(str, Enum):
    # Check a draft Bill of Lading (BL) against the Shipping Instruction (SI)
    BL_COMPARISON = "BL_COMPARISON"

    # Create or prepare a new Shipping Instruction (SI)
    SI_REQUEST = "SI_REQUEST"

    # Handle questions or problems about invoices, charges, freight, or billing
    INVOICE_QUERY = "INVOICE_QUERY"

    # Normal business emails such as updates, reports, reminders, or greetings
    GENERAL = "GENERAL"

    # Unwanted, suspicious, phishing, or unrelated emails
    SPAM = "SPAM"