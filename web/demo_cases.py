"""Built-in demo pairs for the deployed instance.

These are written for this repo, not taken from the organisers' dataset --
the dataset stays out of git. They are shaped like the real documents and
each one exercises a different branch of the decision gate, so the deployed
URL demonstrates the whole system without needing the data bundle.
"""

DEMO_CASES = [
    {
        "id": "clean",
        "title": "Clean pair",
        "blurb": "All seven fields agree once ports and weights are normalised.",
        "si": """SHIPPING INSTRUCTION
========================================

Shipper: MERIDIAN PULP (M) SDN BHD
  LEVEL 12, MENARA SENTRAL; 50470 KUALA LUMPUR, MALAYSIA
Consignee (Non-Negotiable): NORDKAP PAPER A/S
  HAVNEGADE 44; 2100 COPENHAGEN, DENMARK
Notify: NORDKAP PAPER A/S
Port of Loading (POL): PORT KLANG, MALAYSIA (MYPKG)
POD: AARHUS, DENMARK (DKAAR)
Total Containers: 4 x 40'HC
Gross Wt (kgs): 88,400 KG
Vessel: MAERSK SENTOSA
Description of Goods: BLEACHED KRAFT PULP
Freight: PREPAID
""",
        "bl": """BILL OF LADING (DRAFT)
========================================

SHIPPER: Meridian Pulp (M) Sdn. Bhd.
  LEVEL 12, MENARA SENTRAL; 50470 KUALA LUMPUR, MALAYSIA
To the Order of: Nordkap Paper A/S
  HAVNEGADE 44; 2100 COPENHAGEN, DENMARK
Notify Party: Nordkap Paper A/S
Load Port: PORT KLANG, MALAYSIA
Discharge Port: AARHUS, DENMARK
Container Count: 4 x 40'HC
Gross Weight (KG): 88.4 MT
Export Carrier (vessel, voyage): MAERSK SENTOSA
Commodity: BLEACHED KRAFT PULP
Freight: PREPAID
""",
    },
    {
        "id": "mismatch",
        "title": "Real discrepancy",
        "blurb": "Consignee switched and the container count is wrong. "
                 "Everything else matches, so only those two are flagged.",
        "si": """SHIPPING INSTRUCTION
========================================

Shipper: APEX BOARD MILLS LIMITED
  22 INDUSTRIAL WAY; SINGAPORE 628300
Consignee (Non-Negotiable): CASTELLO CARTA SRL
  VIA DEL PORTO 18; 16126 GENOA, ITALY
Notify Party/Intermediate Consignee: CASTELLO CARTA SRL
Port of Loading: SINGAPORE (SGSIN)
Port of Discharge (POD): GENOA, ITALY (ITGOA)
No. of Containers: 3 x 20'GP
Gross Weight毛重(KGS): 54,300 KG
Vessel Name: ONE HARBOUR
Freight: COLLECT
""",
        "bl": """BILL OF LADING (DRAFT)
========================================

Shipper/Exporter: Apex Board Mills Ltd.
  22 INDUSTRIAL WAY; SINGAPORE 628300
To the Order of: VALMARA LOGISTICA SPA
  VIA DEL PORTO 18; 16126 GENOA, ITALY
NOTIFY PARTY: Castello Carta SRL
POL: SINGAPORE
POD: GENOA, ITALY
Container Count: 5 x 20'GP
GROSS WEIGHT: 54,300 KG
Ocean Vessel: ONE HARBOUR
Freight: COLLECT
""",
    },
    {
        "id": "blank",
        "title": "Blank value",
        "blurb": "The BL prints the weight as a placeholder. Blank is "
                 "uncertainty, not a discrepancy, so this escalates rather "
                 "than raising a false alarm.",
        "si": """SHIPPING INSTRUCTION
========================================

Shipper: HARBOURSIDE TIMBER CO
Consignee: LUMINA TRADING GMBH
Notify: LUMINA TRADING GMBH
Port of Loading (POL): TANJUNG PELEPAS, MALAYSIA (MYTPP)
POD: HAMBURG, GERMANY (DEHAM)
Total Containers: 2 x 40'HC
Gross Wt (kgs): 41,900 KG
Freight: PREPAID
""",
        "bl": """BILL OF LADING (DRAFT)
========================================

SHIPPER: Harbourside Timber Company
To the Order of: Lumina Trading GmbH
Notify Party: Lumina Trading GmbH
Load Port: TANJUNG PELEPAS
Discharge Port: HAMBURG
Container Count: 2 x 40'HC
Gross Weight (KG): ________
Freight: PREPAID
""",
    },
    {
        "id": "wrongdoc",
        "title": "Wrong document",
        "blurb": "The attachment labelled BL is a commercial invoice. "
                 "The system refuses to compare it and says why.",
        "si": """SHIPPING INSTRUCTION
========================================

Shipper: CEDAR POINT EXPORTS SDN BHD
Consignee: ORIENT PACKAGING LLC
Notify: ORIENT PACKAGING LLC
Port of Loading (POL): PENANG, MALAYSIA (MYPEN)
POD: JEBEL ALI, UAE (AEJEA)
Total Containers: 1 x 40'HC
Gross Wt (kgs): 19,750 KG
Freight: PREPAID
""",
        "bl": """COMMERCIAL INVOICE
========================================

Invoice No.: INV-2026-04471
Invoice Date: 12 MAR 2026
Seller: CEDAR POINT EXPORTS SDN BHD
Buyer: ORIENT PACKAGING LLC
Description: CORRUGATED LINERBOARD
Total Amount: USD 42,880.00
Payment Terms: 30 DAYS NET
""",
    },
]

BY_ID = {case["id"]: case for case in DEMO_CASES}


def listing():
    return [{k: case[k] for k in ("id", "title", "blurb")}
            for case in DEMO_CASES]
