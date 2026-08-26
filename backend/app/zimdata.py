"""Reference data for a Zimbabwean retail pharmacy.

Drawn from an actual month of trading at a Harare pharmacy: two Detail Analysis
exports covering June and July 2026, a claim summary, and a script register.
What was taken from them is the *shape* of the business, which is the part that
cannot be invented convincingly:

  * **5,056 cash invoices over 61 days** — a median basket of $5.00, a mean of
    $7.84, a ninetieth percentile of $18 and a largest sale of $299. A demo
    seeded with tidy $45 baskets looks like software; this looks like a counter.
  * **The trading day runs 07:00 to 22:00 and peaks at 18:00**, not at lunchtime.
    People collect medicine on the way home.
  * **One till doing 5,055 of those invoices.** Not six.
  * **The schemes that actually appear**, with the split between them: FMH and
    CIMAS carry most of the claimed value, and 396 of 434 scripts in a fortnight
    were private cash.

**No real patient is reproduced here.** The name pool is genuine — 27 surnames
and 32 given names as they occur in Zimbabwe — but they are recombined, so every
person in the seeded database is a new one. Member numbers, ID numbers and
authorisation codes are generated. Copying a live pharmacy's patients into a
system shown to their competitors would be a disclosure, and the demo does not
need it: what makes the data convincing is the distribution, not the individuals.
"""
from __future__ import annotations

# --- who the pharmacy is ---------------------------------------------------

PHARMACY = {
    "name": "RX5000 Pharmacy",
    "trading_name": "RX5000 Pharmacy Central",
    "address": "114 Samora Machel Avenue, Harare",
    "phone": "0242 704 118",
    "licence": "MCAZ-RP-2026-0417",
}

# --- medical aid schemes ---------------------------------------------------
#
# The ones that turn up on a Harare counter, with the currency each settles in.
# Zimbabwe runs two currencies and the schemes do not agree with each other about
# which: a USD scheme rejecting a ZiG claim is a daily event, and a demo that
# pretends otherwise is not showing the problem the product solves.
#
# `levy` is the shortfall the patient pays at the counter. `admin` is what the
# scheme keeps. Both are as they appear in the claim summary.
SCHEMES = [
    # name,                       code,       currency, levy %, notes
    ("CIMAS Medical Aid",         "CIMAS",    "USD", 24.0, "Largest private scheme; biometric capture required"),
    ("First Mutual Health",       "FMH",      "USD", 18.6, "Heaviest script volume on most counters"),
    ("First Mutual Health ZWG",   "FMHZWA",   "ZWG",  0.0, "The ZiG book of the same scheme"),
    ("Alliance Health",           "ALLIANCE", "USD",  0.0, "No levy; settles slowly"),
    ("BonVie Medical Aid",        "BONVIE",   "USD", 13.0, ""),
    ("FBC Health",                "FBC",      "USD",  0.0, ""),
    ("Fidelity Life Medical Aid", "FLIMAS",   "ZWG",  0.0, ""),
    ("Generation Health",         "FMGU",     "ZWG", 10.9, ""),
    ("PSMAS",                     "PSMAS",    "ZWG", 20.0, "Public service; slowest payer of the set"),
    ("Nyaradzo Medical Aid",      "NYAR",     "USD", 49.6, "High co-payment"),
    ("AHSS Zimbabwe",             "AHSSZWA",  "ZWG",  0.0, ""),
]

# --- the catalogue ---------------------------------------------------------
#
# Schedules follow the Medicines and Allied Substances Control Act: S1 and S2 sell
# over the counter, S3 upward needs a prescription, and S3+ is entered in the
# controlled register with the checking pharmacist named.
#
# Prices are USD, and they are small on purpose. The median line on this counter
# is a couple of dollars: a strip of paracetamol, one course of amoxicillin, a
# single day's blood pressure tablets bought because that is what the money runs
# to today. Selling medicine in part-packs is ordinary here.
#
# (name, form, strength, pack, schedule, price, cost, category)
CATALOGUE = [
    # Analgesics and antipyretics
    ("Panadol",                 "Tablet",  "500mg",  "24s",   1, 2.50, 1.55, "Analgesic"),
    ("Paracetamol",             "Tablet",  "500mg",  "1000s", 1, 9.00, 5.40, "Analgesic"),
    ("Ibuprofen",               "Tablet",  "400mg",  "100s",  2, 5.00, 3.05, "Analgesic"),
    ("Brufen",                  "Tablet",  "400mg",  "30s",   2, 4.50, 2.80, "Analgesic"),
    ("Diclofenac",              "Tablet",  "50mg",   "30s",   2, 3.50, 2.10, "Analgesic"),
    ("Aspirin",                 "Tablet",  "300mg",  "100s",  1, 3.00, 1.75, "Analgesic"),
    ("Cataflam",                "Tablet",  "50mg",   "20s",   3, 7.50, 4.90, "Analgesic"),
    ("Tramadol",                "Capsule", "50mg",   "20s",   4, 6.00, 3.60, "Analgesic"),
    ("Panadeine",               "Tablet",  "500/8mg", "24s",  3, 4.20, 2.60, "Analgesic"),

    # Antibiotics
    ("Amoxicillin",             "Capsule", "500mg",  "21s",   4, 4.00, 2.35, "Antibiotic"),
    ("Amoxil",                  "Capsule", "500mg",  "21s",   4, 7.00, 4.40, "Antibiotic"),
    ("Augmentin",               "Tablet",  "625mg",  "14s",   4, 14.00, 9.20, "Antibiotic"),
    ("Azithromycin",            "Tablet",  "500mg",  "3s",    4, 5.50, 3.30, "Antibiotic"),
    ("Ciprofloxacin",           "Tablet",  "500mg",  "10s",   4, 4.50, 2.65, "Antibiotic"),
    ("Doxycycline",             "Capsule", "100mg",  "10s",   4, 3.00, 1.70, "Antibiotic"),
    ("Metronidazole",           "Tablet",  "400mg",  "21s",   4, 2.50, 1.35, "Antibiotic"),
    ("Flagyl",                  "Tablet",  "400mg",  "21s",   4, 6.00, 3.80, "Antibiotic"),
    ("Cephalexin",              "Capsule", "500mg",  "20s",   4, 6.50, 4.10, "Antibiotic"),
    ("Erythromycin",            "Tablet",  "250mg",  "20s",   4, 4.00, 2.30, "Antibiotic"),
    ("Cotrimoxazole",           "Tablet",  "480mg",  "100s",  4, 5.00, 2.80, "Antibiotic"),

    # Antimalarials — endemic, and seasonal
    ("Coartem",                 "Tablet",  "20/120mg", "24s", 4, 8.00, 5.10, "Antimalarial"),
    ("Artemether-Lumefantrine", "Tablet",  "20/120mg", "24s", 4, 5.50, 3.20, "Antimalarial"),
    ("Quinine",                 "Tablet",  "300mg",  "30s",   4, 6.00, 3.60, "Antimalarial"),

    # Chronic — hypertension and cardiac
    ("Amlodipine",              "Tablet",  "5mg",    "30s",   4, 3.00, 1.65, "Cardiovascular"),
    ("Amlodipine",              "Tablet",  "10mg",   "30s",   4, 3.80, 2.15, "Cardiovascular"),
    ("Enalapril",               "Tablet",  "10mg",   "30s",   4, 3.20, 1.80, "Cardiovascular"),
    ("Losartan",                "Tablet",  "50mg",   "30s",   4, 5.00, 2.90, "Cardiovascular"),
    ("Atenolol",                "Tablet",  "50mg",   "28s",   4, 2.80, 1.50, "Cardiovascular"),
    ("Carvedilol",              "Tablet",  "12.5mg", "30s",   4, 6.00, 3.70, "Cardiovascular"),
    ("Hydrochlorothiazide",     "Tablet",  "25mg",   "30s",   4, 2.20, 1.15, "Cardiovascular"),
    ("Furosemide",              "Tablet",  "40mg",   "30s",   4, 2.00, 1.05, "Cardiovascular"),
    ("Simvastatin",             "Tablet",  "20mg",   "30s",   4, 4.50, 2.60, "Cardiovascular"),
    ("Atorvastatin",            "Tablet",  "20mg",   "30s",   4, 6.50, 4.00, "Cardiovascular"),
    ("Aspirin Cardio",          "Tablet",  "75mg",   "30s",   2, 2.50, 1.30, "Cardiovascular"),

    # Chronic — diabetes
    ("Metformin",               "Tablet",  "500mg",  "60s",   4, 3.50, 1.90, "Antidiabetic"),
    ("Metformin",               "Tablet",  "850mg",  "60s",   4, 4.50, 2.50, "Antidiabetic"),
    ("Glibenclamide",           "Tablet",  "5mg",    "30s",   4, 2.50, 1.30, "Antidiabetic"),
    ("Gliclazide",              "Tablet",  "80mg",   "30s",   4, 5.50, 3.30, "Antidiabetic"),
    ("Insulatard",              "Injection", "100IU/ml", "10ml", 4, 18.00, 13.50, "Antidiabetic"),
    ("Actrapid",                "Injection", "100IU/ml", "10ml", 4, 18.00, 13.50, "Antidiabetic"),

    # Respiratory
    ("Salbutamol",              "Inhaler", "100mcg", "200 doses", 3, 6.00, 3.60, "Respiratory"),
    ("Ventolin",                "Inhaler", "100mcg", "200 doses", 3, 9.50, 6.40, "Respiratory"),
    ("Beclomethasone",          "Inhaler", "250mcg", "200 doses", 4, 12.00, 8.10, "Respiratory"),
    ("Prednisolone",            "Tablet",  "5mg",    "30s",   4, 2.80, 1.45, "Respiratory"),
    ("Cetirizine",              "Tablet",  "10mg",   "10s",   2, 1.50, 0.75, "Antihistamine"),
    ("Loratadine",              "Tablet",  "10mg",   "10s",   2, 1.80, 0.90, "Antihistamine"),
    ("Chlorpheniramine",        "Tablet",  "4mg",    "30s",   2, 1.00, 0.45, "Antihistamine"),
    ("Bromhexine",              "Syrup",   "8mg/5ml", "100ml", 2, 3.50, 2.00, "Respiratory"),
    ("Benylin",                 "Syrup",   "",       "100ml", 2, 5.00, 3.10, "Respiratory"),

    # Gastro
    ("Omeprazole",              "Capsule", "20mg",   "30s",   3, 4.00, 2.20, "Gastrointestinal"),
    ("Ranitidine",              "Tablet",  "150mg",  "30s",   3, 3.00, 1.60, "Gastrointestinal"),
    ("Gaviscon",                "Suspension", "",    "200ml", 1, 6.50, 4.20, "Gastrointestinal"),
    ("Buscopan",                "Tablet",  "10mg",   "20s",   2, 4.00, 2.40, "Gastrointestinal"),
    ("Loperamide",              "Capsule", "2mg",    "10s",   2, 2.00, 1.00, "Gastrointestinal"),
    ("Oral Rehydration Salts",  "Sachet",  "",       "1s",    1, 0.50, 0.22, "Gastrointestinal"),
    ("Mebendazole",             "Tablet",  "100mg",  "6s",    2, 1.50, 0.70, "Anthelmintic"),
    ("Albendazole",             "Tablet",  "400mg",  "1s",    2, 1.00, 0.45, "Anthelmintic"),

    # Antiretrovirals — dispensed on this counter every day
    ("Tenofovir/Lamivudine/Dolutegravir", "Tablet", "300/300/50mg", "30s", 4, 12.00, 8.00, "Antiretroviral"),
    ("Atazanavir/Ritonavir",    "Tablet",  "300/100mg", "30s", 4, 22.00, 16.00, "Antiretroviral"),
    ("Nevirapine",              "Tablet",  "200mg",  "60s",   4, 9.00, 6.00, "Antiretroviral"),

    # Vitamins and supplements
    ("Ferrous Sulphate",        "Tablet",  "200mg",  "30s",   1, 1.50, 0.70, "Supplement"),
    ("Folic Acid",              "Tablet",  "5mg",    "30s",   1, 1.00, 0.40, "Supplement"),
    ("Vitamin B Complex",       "Tablet",  "",       "30s",   1, 2.00, 0.95, "Supplement"),
    ("Vitamin C",               "Tablet",  "500mg",  "30s",   1, 2.50, 1.20, "Supplement"),
    ("Calcium with Vitamin D",  "Tablet",  "",       "30s",   1, 4.50, 2.70, "Supplement"),
    ("Pregnacare",              "Tablet",  "",       "30s",   1, 12.00, 8.20, "Supplement"),
    ("Zinc Sulphate",           "Tablet",  "20mg",   "30s",   1, 1.80, 0.85, "Supplement"),

    # Topical and first aid
    ("Betadine",                "Solution", "10%",   "100ml", 1, 4.00, 2.35, "Antiseptic"),
    ("Savlon",                  "Solution", "",      "100ml", 1, 3.00, 1.70, "Antiseptic"),
    ("Hydrocortisone",          "Cream",   "1%",     "15g",   3, 3.50, 2.00, "Dermatological"),
    ("Clotrimazole",            "Cream",   "1%",     "20g",   2, 3.00, 1.65, "Dermatological"),
    ("Whitfield's Ointment",    "Ointment", "",      "25g",   1, 2.00, 0.95, "Dermatological"),
    ("Zinc Oxide",              "Cream",   "",       "50g",   1, 2.50, 1.30, "Dermatological"),
    ("Elastoplast",             "Dressing", "",      "10s",   1, 1.50, 0.70, "First aid"),
    ("Cotton Wool",            "Dressing", "",      "100g",  1, 2.00, 1.00, "First aid"),
    ("Surgical Spirit",         "Solution", "70%",   "100ml", 1, 1.50, 0.65, "Antiseptic"),
    ("Crepe Bandage",           "Dressing", "75mm",  "1s",    1, 2.00, 1.00, "First aid"),

    # Front shop
    ("Surgical Face Mask",      "Consumable", "",    "50s",   1, 4.00, 2.20, "Front shop"),
    ("Glucometer Strips",       "Consumable", "",    "50s",   1, 15.00, 11.00, "Front shop"),
    ("Blood Pressure Monitor",  "Device",  "",       "1s",    1, 45.00, 33.00, "Front shop"),
    ("Digital Thermometer",     "Device",  "",       "1s",    1, 6.00, 3.60, "Front shop"),
    ("Pregnancy Test",          "Device",  "",       "1s",    1, 2.00, 0.90, "Front shop"),
    ("Male Condoms",            "Consumable", "",    "3s",    1, 1.00, 0.40, "Front shop"),
    ("Baby Wipes",              "Consumable", "",    "80s",   1, 3.50, 2.10, "Front shop"),
    ("Petroleum Jelly",         "Cream",   "",       "250ml", 1, 2.50, 1.35, "Front shop"),
    ("Sanitary Pads",           "Consumable", "",    "10s",   1, 1.50, 0.75, "Front shop"),
    ("Reading Glasses",         "Device",  "+2.00",  "1s",    1, 8.00, 4.50, "Front shop"),

    # Airtime. Sold over the counter in every pharmacy here, and it belongs in
    # the catalogue because it distorts a takings figure that ignores it: it is
    # revenue with almost no margin, and a gross-profit report that treats it as
    # stock reads as though the pharmacy is losing money on medicine.
    ("Econet Airtime $1",       "Voucher", "",       "1s",    1, 1.00, 0.96, "Airtime"),
    ("Econet Airtime $2",       "Voucher", "",       "1s",    1, 2.00, 1.92, "Airtime"),
    ("Econet Airtime $5",       "Voucher", "",       "1s",    1, 5.00, 4.80, "Airtime"),
    ("NetOne Airtime $1",       "Voucher", "",       "1s",    1, 1.00, 0.96, "Airtime"),
    ("NetOne Airtime $5",       "Voucher", "",       "1s",    1, 5.00, 4.80, "Airtime"),

    # Controlled — the register cases
    ("Diazepam",                "Tablet",  "5mg",    "30s",   5, 4.00, 2.20, "Psychotropic"),
    ("Codeine Phosphate",       "Tablet",  "30mg",   "20s",   5, 6.50, 4.00, "Analgesic"),
    ("Morphine Sulphate",       "Injection", "10mg/ml", "1ml", 6, 12.00, 8.50, "Analgesic"),
    ("Pethidine",               "Injection", "50mg/ml", "2ml", 6, 14.00, 10.00, "Analgesic"),
    ("Phenobarbitone",          "Tablet",  "30mg",   "30s",   5, 3.50, 1.90, "Anticonvulsant"),
    ("Amitriptyline",           "Tablet",  "25mg",   "30s",   4, 3.00, 1.60, "Psychotropic"),
    ("Carbamazepine",           "Tablet",  "200mg",  "30s",   4, 5.00, 3.00, "Anticonvulsant"),
    ("Fluoxetine",              "Capsule", "20mg",   "30s",   4, 6.00, 3.70, "Psychotropic"),
]

# --- people ----------------------------------------------------------------
#
# Recombined, never copied. See the module docstring.
SURNAMES = [
    "Andela", "Bamba", "Banda", "Chanakira", "Chimusoro", "Chiwara", "Deshe",
    "Faku", "Funsani", "Gotora", "Kanoyangwa", "Kapora", "Kurisa", "Kuture",
    "Madombi", "Mamhende", "Manyaira", "Masengu", "Mashingaidze", "Muchena",
    "Mudzamiri", "Mugwambi", "Muparadzi", "Musarurwa", "Mutumhe", "Ncube",
    "Nleya", "Nyapau", "Pakuru", "Parewa", "Pedzisayi", "Shazha", "Tafirenyika",
    "Tandiwe", "Taruona", "Washaru", "Zimbwa", "Moyo", "Dube", "Sibanda",
    "Chigumba", "Marimo", "Nyathi", "Zvobgo", "Mhlanga", "Gwaze",
]

GIVEN_NAMES = [
    "Admire", "Aiden", "Akuzweishe", "Alice", "Anaya", "Angela", "Anotida",
    "Bradley", "Edward", "Giveus", "Goodlaw", "Kelvin", "Kudzai", "Kudzaishe",
    "Lillian", "Loveness", "Martha", "Muchengeti", "Munyaradzi", "Patricia",
    "Peter", "Reuben", "Ruregerero", "Rutendo", "Simbarashe", "Tadiswa",
    "Tinayeshe", "Tinemufaro", "Trust", "Charmaine", "Munashe", "Kundai",
    "Adelaide", "Emissary", "Ganiere", "Tatenda", "Nicholas", "Susan",
    "Nyasha", "Ruvimbo", "Tapiwa", "Farai", "Blessing", "Memory", "Tendai",
    "Shingirai", "Privilege", "Nomatter", "Chiedza", "Rumbidzai",
]

# Prescribers. Practice numbers follow the Zimbabwean format.
DOCTORS = [
    ("Dr T Chikwanha",    "0301447", "0772 415 880"),
    ("Dr R Mabika",       "0298113", "0712 664 205"),
    ("Dr S Nyamandi",     "0311902", "0771 208 447"),
    ("Dr L Mutasa",       "0284556", "0783 550 119"),
    ("Dr P Gwenzi",       "0322870", "0774 903 662"),
    ("Dr M Chirenje",     "0269341", "0713 887 004"),
    ("Dr F Sibanda",      "0335128", "0782 116 993"),
    ("Dr A Machingura",   "0290775", "0771 442 806"),
    ("Parirenyatwa OPD",  "0100002", "0242 701 555"),
    ("Harare Central OPD", "0100003", "0242 621 111"),
]

SUPPLIERS = [
    ("Zimpharm Distributors",   "Tarisai Mhembere", "0242 621 440", "orders@zimpharm.co.zw"),
    ("Croco Motors Pharma",     "Netsai Chuma",     "0242 770 118", "sales@crocopharma.co.zw"),
    ("Geddes Limited",          "Brian Ncube",      "0242 486 200", "trade@geddes.co.zw"),
    ("Pharmanova Zimbabwe",     "Rudo Marufu",      "0242 486 771", "orders@pharmanova.co.zw"),
    ("Datlabs Bulawayo",        "Sipho Ndlovu",     "0292 888 400", "sales@datlabs.co.zw"),
    ("CAPS Holdings",           "Nyasha Gwatidzo",  "0242 621 900", "orders@caps.co.zw"),
]

# Conditions in the order a Harare dispensary actually meets them.
CHRONIC_CONDITIONS = [
    "Hypertension", "Type 2 diabetes", "Asthma", "HIV", "Epilepsy",
    "Arthritis", "Hypothyroidism", "Chronic kidney disease", "Depression",
]

ALLERGIES = [
    "Penicillin", "Sulphonamides", "Aspirin", "Codeine", "Iodine", "Latex",
]

# --- how the counter actually trades ---------------------------------------
#
# Measured, not guessed. Each entry is (hour, share of the day's invoices), from
# 5,056 invoices over 61 days. The evening is the busy part: people collect
# medicine on the way home, and a demo whose chart peaks at lunchtime is showing
# a European pharmacy.
HOURLY_SHARE = [
    (7, 0.004), (8, 0.040), (9, 0.041), (10, 0.054), (11, 0.054), (12, 0.059),
    (13, 0.065), (14, 0.070), (15, 0.065), (16, 0.085), (17, 0.100),
    (18, 0.106), (19, 0.101), (20, 0.075), (21, 0.056), (22, 0.017),
]

#: What actually walks out of the door, in roughly the order it does.
#:
#: Weighting by price band alone made oral rehydration salts the top seller by a
#: factor of four, because at fifty cents it was the only line that fitted in a
#: small basket. It is a real seller and not the top one; a top-sellers report
#: led by ORS is the sort of detail a pharmacist spots in the first minute.
STAPLES = [
    "Panadol", "Paracetamol", "Ibuprofen", "Brufen", "Aspirin", "Cetirizine",
    "Amoxicillin", "Metronidazole", "Coartem", "Salbutamol", "Omeprazole",
    "Vitamin C", "Ferrous Sulphate", "Panadeine", "Augmentin", "Loratadine",
]

#: Invoices a day, from 61 days of trading.
SALES_PER_DAY = 81

#: The basket, as measured: median $5.00, mean $7.84, ninetieth $18, largest $299.
#: Sampled as a log-normal fitted to those points rather than a flat range, which
#: is what gives a takings chart its real shape.
BASKET_MEDIAN = 5.00
BASKET_SIGMA = 1.05

#: One till carried 5,055 of 5,056 invoices. Not six.
TILL_NUMBERS = ["4", "3"]
TILL_WEIGHTS = [0.999, 0.001]


# --- what a script looks like ----------------------------------------------
#
# Directions as a Zimbabwean dispenser writes them, paired with the medicines
# they belong to. A demo where every line reads "Take as directed" is a demo
# nobody in a dispensary believes.
DIRECTIONS = {
    "Analgesic":       ["Take 2 tablets every 6 hours when needed for pain",
                        "Take 1 tablet three times a day after food",
                        "Take 2 tablets at night for pain"],
    "Antibiotic":      ["Take 1 capsule three times a day for 5 days. Finish the course",
                        "Take 1 tablet twice a day for 7 days. Finish the course",
                        "Take 1 tablet daily for 3 days"],
    "Antimalarial":    ["Take 4 tablets now, then 4 after 8 hours, then twice daily for 2 days",
                        "Take as charted. Complete the full course"],
    "Cardiovascular":  ["Take 1 tablet every morning",
                        "Take 1 tablet daily. Do not stop without seeing the doctor",
                        "Take half a tablet in the morning and half at night"],
    "Antidiabetic":    ["Take 1 tablet twice a day with meals",
                        "Take 1 tablet with breakfast",
                        "Inject as instructed. Keep refrigerated"],
    "Respiratory":     ["Two puffs when short of breath, up to four times a day",
                        "Take 1 tablet each morning with food",
                        "Two puffs morning and night. Rinse mouth after use"],
    "Gastrointestinal": ["Take 1 capsule before breakfast",
                        "Take 1 tablet when needed for heartburn",
                        "Take 10ml after meals"],
    "Antiretroviral":  ["Take 1 tablet at the same time every night",
                        "Take 1 tablet daily. Do not miss a dose"],
    "Psychotropic":    ["Take 1 tablet at night",
                        "Take half a tablet at night for the first week"],
    "Anticonvulsant":  ["Take 1 tablet twice a day. Do not stop suddenly"],
    "Antihistamine":   ["Take 1 tablet at night for itching",
                        "Take 1 tablet daily when needed"],
    "Dermatological":  ["Apply thinly to the affected area twice a day",
                        "Apply at night only"],
    "Supplement":      ["Take 1 tablet daily with food",
                        "Take 1 tablet twice a day"],
    "Anthelmintic":    ["Take 1 tablet as a single dose. Repeat in 2 weeks"],
}
DIRECTIONS_DEFAULT = ["Take as directed by the prescriber",
                      "Use as instructed. Return if not improving"]

#: ICD-10 codes a Harare dispensary actually claims against.
ICD10 = [
    ("I10",   "Essential hypertension"),
    ("E11.9", "Type 2 diabetes mellitus"),
    ("J45.9", "Asthma"),
    ("B54",   "Malaria, unspecified"),
    ("A09",   "Gastroenteritis"),
    ("J06.9", "Upper respiratory infection"),
    ("N39.0", "Urinary tract infection"),
    ("B20",   "HIV disease"),
    ("G40.9", "Epilepsy"),
    ("M79.1", "Myalgia"),
    ("K21.0", "Reflux oesophagitis"),
    ("L23.9", "Allergic contact dermatitis"),
]

#: Reminder copy. Written the way a pharmacy writes it, not the way a template
#: does: short, named, and it says what to do.
REMINDER_TEMPLATES = [
    "Good day {name}. Your {product} repeat is due on {due}. We have it in stock. RX5000 Pharmacy, 0242 704 118.",
    "Hello {name}, your {product} is ready for collection at RX5000 Pharmacy, 114 Samora Machel Ave. Open until 22:00.",
    "{name}, your {product} repeat was due on {due}. Please collect or call us on 0242 704 118 if you no longer need it.",
    "Good day {name}. The {product} we owed you has arrived. Bring your slip and we will hand it over.",
]

CAMPAIGN_TEMPLATES = [
    ("Flu vaccination now available",
     "Good day {name}. Flu vaccines are in stock at RX5000 Pharmacy. Walk in any day between 08:00 and 20:00, no appointment needed. $12 per dose."),
    ("Free blood pressure checks this week",
     "Hello {name}. We are checking blood pressure free of charge at RX5000 Pharmacy until Friday. No appointment, just walk in."),
    ("Diabetes screening, Saturday",
     "Good day {name}. Free blood sugar testing this Saturday at RX5000 Pharmacy, 114 Samora Machel Ave, 09:00 to 15:00."),
    ("Chronic medication delivery",
     "Hello {name}. We now deliver chronic medication within Harare for $3. Reply or call 0242 704 118 to arrange."),
]

#: Why a delivery failed. Every one of these has actually been written on a
#: waybill; "delivery failed" on its own tells the next driver nothing.
DELIVERY_FAILURES = [
    "Nobody home, gate locked",
    "Phone off, could not raise the patient",
    "Address not found, patient to confirm the road name",
    "Patient at work, asked us to try after 17:00",
    "Refused: wanted to pay on collection, not on delivery",
]
