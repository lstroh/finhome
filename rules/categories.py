"""
Categorisation rules for your transactions.

HOW THIS WORKS
--------------
Each category maps to a list of keywords. If a transaction's description
contains any of the keywords (case-insensitive), it gets that category.
Rules are checked in the order they appear below — first match wins —
so put more specific rules above more general ones.

HOW TO EDIT
-----------
- To add a new merchant to an existing category: just add a keyword to
  that category's list.
- To create a new category: add a new "CATEGORY_NAME": [...] entry.
- To see what's currently falling into "Uncategorised", run:
      python3 analyze.py --uncategorised
  Then add keywords here for whatever shows up.

Keywords are matched against the transaction description in UPPERCASE,
so write your keywords in uppercase too (easier to scan).
"""

# Order matters: first match wins. Keep specific/unusual merchants near
# the top, broad/generic words near the bottom.
CATEGORY_RULES = {
    # ---- Income ----
    "Income": [
        "SALARY", "PAYROLL", "WAGES", "HMRC", "TAX REFUND",
        "VISTRA IE UK LTD",
        "INTEREST (GROSS)", "CASHBACK",
        "ACCT FEE DISCOUNT", "CLUB LLOYDS WAIVED",
    ],

    # ---- Transfers (own accounts / family — excluded from spending) ----
    "Transfer": [
        "F/FLOW",
        "L STROH", "EFRAT STROH",
        "SAVETHECHANGE",
        "CARESWELL",
        "INSTALMENT PLAN",
        "TRANSFER TO", "TRANSFER FROM", "TO SAVINGS", "FROM SAVINGS",
    ],

    # ---- Credit card payment from current account ----
    "Credit Card Payment": [
        "AMERICAN EXPRESS",
        "PAYMENT RECEIVED - THANK YOU",
        "CREDIT CARD PAYMENT", "CARD PAYMENT TO",
    ],

    # ---- Housing & bills (fixed) ----
    "Housing": [
        "RENT", "MORTGAGE", "BARCLAYS UK MTGES",
        "COUNCIL TAX", "L B OF MERTON", "LANDLORD",
        "CAPITAL SURVEYORS", "CARESWELL PROPERTY",
        "SPECTOR AND CONSTA", "ART NOTARIAL SERVI",
        "FANTASTIC SERVICES",
    ],
    "Utilities": [
        "BRITISH GAS", "BG SERVICES", "OCTOPUS ENERGY", "EDF ENERGY", "OVO ENERGY",
        "THAMES WATER", "SEVERN TRENT", "BT GROUP", "VIRGIN MEDIA",
        "SKY", "TALKTALK", "VODAFONE", "EE LIMITED", "O2",
        "THREE", "GIFFGAFF", "WATER", "ELECTRIC", "ENERGY",
        "TV LICENCE",
    ],
    "Insurance": [
        "INSURANCE", "AVIVA", "ADMIRAL", "AXA", "LV=", "DIRECT LINE",
        "CHURCHILL", "BUPA", "VITALITY",
        "D&G AO CARE PLAN", "WHATEVERHAPPENS",
    ],

    "Bank Fees": [
        "ACCOUNT FEE", "CLUB LLOYDS FEE", "INSTALMENT PLAN FEE",
    ],

    # ---- Education & childcare ----
    "Education & Childcare": [
        "BROMCOM", "MYCHILDATSCHOOL",
        "WE MAKE FOOTBALLER", "PEE WEE KARATE",
    ],

    # ---- Subscriptions ----
    "Subscriptions": [
        "NETFLIX", "SPOTIFY", "AMAZON PRIME", "DISNEY", "APPLE.COM/BILL",
        "APPLE.COM/UK",
        "YOUTUBE PREMIUM", "ICLOUD", "PURE GYM", "PUREGYM", "PEAR",
        "PARAMOUNT", "NOW TV", "AUDIBLE", "KINDLE UNLTD", "ADOBE",
        "MICROSOFT 365", "GYM", "MEMBERSHIP",
        "CLAUDE.AI", "CURSOR AI", "OPENROUTER",
        "HOSTINGER", "NAME-CHEAP", "SCREENIL.COM",
        "HPI INSTANT INK", "BIKE CLUB",
        "WHO GIVES A CRAP",
    ],

    # ---- Groceries vs dining (variable) ----
    "Groceries": [
        "TESCO", "SAINSBURY", "ASDA", "MORRISONS", "W M MORRISON",
        "WAITROSE", "ALDI", "LIDL", "CO-OP", "ICELAND", "M&S FOOD", "OCADO",
        "MARKS&SPENCER", "MARKS & SPENCER", "M&S SIMPLY", "M&S SOUTHBANK PLACE",
        "G S MINI MARKET",
        "MACE - SW19", "PINCOTT CONVENIENC", "OSEYO",
        "SBR TRADING", "WIMBLEDON EXPRESS",
        "SOUTHBANK PLACE LE",
    ],
    "Dining & Takeaway": [
        "DELIVEROO", "UBER EATS", "JUST EAT", "MCDONALD", "GREGGS",
        "COSTA", "STARBUCKS", "PRET", "NANDO", "WAGAMAMA", "RESTAURANT",
        "CAFE", "COFFEE", "PUB", "BAR ",
        "ATISFOOD", "ATISLIFE", "AMORINO", "BURGER KING", "BILL'S WIMBLED",
        "CH&CO", "DIGBY'S PATISSERIE", "DOMINO S PIZZA", "GAILS WIMBLEDON",
        "ITSU", "JOE  THE JUICE", "KRISPY KREME",
        "OLE AND STEEN", "OLIVE CORNER", "PIZZA EXPRESS", "ROSA'S WIMBLEDON",
        "SUBWAY", "TORTILLA", "TAMPOPO", "WWW.TORTILLA", "PAPAJOHN",
        "THE CHEEKY PEA", "BAXTER STOREY", "OSBORNES OF LONDON",
        "153 LONDON WIMBLED", "601 QUEENS ROAD", "NO. 601 QUEENS ROA",
        "SIMONS", "WEYSIDE", "SUMUP", "ZETTLE",
        "SP LOLAS CUPCAKES", "TIPJAR",
    ],

    # ---- Transport ----
    "Transport": [
        "TFL", "TRAINLINE", "UBER", "BOLT", "ADDISON LEE", "SHELL",
        "BP ", "ESSO", "TEXACO", "RONTEC", "PARKING", "NATIONAL RAIL", "TRENITALIA",
        "GWR", "AVANTI", "LNER", "CITYMAPPER",
        "GTR RAIL", "LUL TICKET", "SWRAILWAY", "SE LONDON BRIDGE",
        "FOREST", "EVANS CYCLES", "GET PEDAL READY",
        "SOUTH WIMBLEDON ST", "PPOINT_",
    ],

    # ---- Shopping ----
    "Shopping": [
        "AMAZON", "AMZNMKTPLACE", "EBAY", "JOHN LEWIS", "ARGOS", "IKEA", "ZARA",
        "H&M", "H & M", "NEXT", "ASOS", "BOOTS", "SUPERDRUG", "CURRYS",
        "B&Q", "CEX", "CLARKS", "ROBERT DYAS", "RYMAN", "T K MAXX",
        "THE ENTERTAINER", "PANDORA JEWELLERY", "SPORTSDIRECT",
        "SP BLUNDSTONE", "WH SMITH", "THEWORKS", "CKM.NORD",
        "CARDS GALORE", "AVOLTA", "LHR T4 WDF", "ONLINE REDIRECTION",
        "WATCH ME", "POST OFFICE COUNTE",
    ],

    # ---- Health & personal care ----
    "Health": [
        "PHARMACY", "DENTAL", "DENTIST", "OPTICIAN", "NHS", "GP SURGERY",
        "SPECSAVERS", "TURKISH BARBER",
    ],

    # ---- Entertainment ----
    "Entertainment": [
        "CINEMA", "VUE", "ODEON", "CINEWORLD", "THEATRE", "TICKETMASTER",
        "EVENTBRITE", "STEAM", "PLAYSTATION", "XBOX", "NINTENDO",
        "SCIENCE MUSEUM", "NATURAL HISTORY MU", "THE NATURAL HISTOR",
        "HISTORIC ROYAL PAL", "NATIONAL TRUST", "KIDSPACE",
        "TENPIN", "URBAN FUN", "THFC TICKET",
        "TMG EVENTS", "SP MURDER IN PRAGU", "NATIONAL LOTTERY",
        "COLLCTIV", "COLLECTION POT",
        "FRASER PORTRAITS", "BOTTONS FAMILY",
    ],

    # ---- Travel/holidays ----
    "Travel": [
        "AIRBNB", "BOOKING.COM", "EXPEDIA", "EASYJET", "RYANAIR",
        "BRITISH AIRWAYS", "WIZZ AIR", "HOTEL", "AIRLINE", "FLIGHT",
        "UKVI", "VMS WEWORK",
    ],

    # ---- Charity & donations ----
    "Charity & Donations": [
        "FRIENDS OF PELHAM", "WWW.BETTER.ORG.UK",
    ],

    # ---- Cash ----
    "Cash": [
        "ATM", "CASH WITHDRAWAL", "LNK NOTEMACHINE", "RETAIL 24",
        "LOYD LOYD 4 QUEENS",
    ],
}

# Categories that should be EXCLUDED from spending totals/insights
# (these are money moving between your own accounts, not real spending)
NON_SPENDING_CATEGORIES = {
    "Transfer", "Credit Card Payment", "Income",
}

# For the 50/30/20 benchmark: which categories count as "Needs" vs "Wants"
NEEDS_CATEGORIES = {
    "Housing", "Utilities", "Insurance", "Groceries", "Transport",
    "Health", "Cash", "Bank Fees", "Education & Childcare",
}
WANTS_CATEGORIES = {
    "Subscriptions", "Dining & Takeaway", "Shopping", "Entertainment",
    "Travel", "Charity & Donations",
}
