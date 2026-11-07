#!/usr/bin/env python3
"""Refresh the calculator's default yield and price per crop from USDA NASS.

Source: USDA NASS Quick Stats bulk file "qs.crops_YYYYMMDD.txt.gz", listed at
https://www.nass.usda.gov/datasets (keyless, public domain, refreshed daily by NASS).
No API key or account is needed. Python standard library only.

Usage:
    python3 scripts/update_prices.py [--cache-dir DIR] [--file PATH] [--out PATH]

What it does:
  1. Reads CROPS and DEFAULTS from symm-calculator.html (the calculator stays the single
     list of crops and units).
  2. Downloads the newest qs.crops file (about 1.1 GB gzipped) unless it is already cached.
  3. Streams it once and keeps only SURVEY rows, ANNUAL frequency, NATIONAL or STATE level,
     domain TOTAL, statistic PRICE RECEIVED or YIELD, reference period MARKETING YEAR or YEAR,
     and only the exact series named in MAPPING below.
  4. For each crop and geography (US plus each state) picks the most recent year for which
     BOTH price and yield exist (so price x yield is one season's value per acre), using the
     fresh-market price where NASS has one (see FRESH), converts to the calculator unit
     (DEFAULTS u), and writes data/crop-defaults.json. Seasons older than MAX_AGE_YEARS are
     ignored.
  5. Prints every value next to the built-in default and flags anything off by more than 3x.

The JSON is rewritten only when the crop figures change, so the weekly workflow commits only
when NASS publishes something new. "generated" is therefore the date the figures last changed.

Mapping principle (decision 2026-11-07, Aidan): our buyers are fresh-market specialty growers, so
WHERE NASS REPORTS FRESH AND PROCESSING SEPARATELY, THE FRESH-MARKET PRICE IS USED (FRESH below).
NASS publishes no fresh-market yield series (fresh/processing acreage splits were discontinued),
so yield is the all-utilization yield for every crop. Each record carries "basis": "fresh" or
"all-uses" so the price series behind it is visible. A geography with no fresh price for the
chosen season falls back to its own all-uses price ("all-uses"), unless that price is under half
the same season's national fresh price (a processing-dominated state, e.g. Florida lemons,
California tomatoes): that state is then left out and the calculator shows the national figure.
Exceptions are noted per crop.

Marketing-year prices ("MARKETING YEAR") are preferred over calendar-year averages ("YEAR")
because they come from the same annual summaries as the yields and exist at state level.
The calendar-year fresh apple price (2025: $0.69/lb) is a monthly first-sale average and is
not used.

Unit conversions (exact): 1 ton = 2,000 lb; 1 cwt = 100 lb; 1 bu sorghum = 56 lb.
Citrus box weights (NASS Citrus Fruits summary, net lb per box): oranges CA 80, FL 90, TX 85,
AZ 75 (no current AZ orange series); lemons CA 80, AZ 80, FL 90.
"""
import argparse
import datetime as dt
import gzip
import json
import os
import re
import shutil
import sys
import urllib.request

INDEX_URL = "https://www.nass.usda.gov/datasets"
FILE_BASE = "https://www.nass.usda.gov/sites/default/files/datasets/"
UA = {"User-Agent": "Mozilla/5.0 (symm-site crop defaults updater)"}
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CALC = os.path.join(ROOT, "symm-calculator.html")
OUT = os.path.join(ROOT, "data", "crop-defaults.json")
MAX_AGE_YEARS = 2  # ignore a geography whose newest complete pair is older than this
PROCESSING_RATIO = 0.5  # all-uses price under this share of national fresh = processing-dominated
# Fresh price above this multiple of the same place's all-uses price means the all-uses yield is
# processing-dominated (e.g. WA sweet corn, carrots), so fresh price x that yield overstates value.
# Then the state is skipped and the calculator shows the national fresh figure. The national record
# keeps the fresh price (Aidan, 7 Nov: fresh where USDA splits). Added 2026-11-07 after checks.
FRESH_PREMIUM_MAX = 1.5
EXCLUDE = {("kale", "CA"): "2025 yield 40,000 lb is 2.4x 2024 and 3-4x extension yields"}

LB_PER_TON = 2000.0
LB_PER_CWT = 100.0
LB_PER_BU_SORGHUM = 56.0
ORANGE_BOX_LB = {"CA": 80, "FL": 90, "TX": 85, "AZ": 75}
LEMON_BOX_LB = {"CA": 80, "AZ": 80, "FL": 90, "US": 80}  # US: CA is about 90% of lemon output


def S(desc):
    return desc  # readability helper in MAPPING


# cropKey (lowercase, as in DEFAULTS) -> spec
#   unit:  calculator unit the factors convert to (checked against DEFAULTS u)
#   price: list of (NASS SHORT_DESC, factor) tried in order; value * factor = $ per calc unit
#   yield: list of (NASS SHORT_DESC, factor); value * factor = calc units per acre
#   factor may be a dict {state_alpha: factor} for citrus (box weights differ by state)
#   price_only: True -> yield left to the calculator's built-in default
#   states_only: True -> no national record (the calculator's built-in default is the national)
#   newest_year_lag: N -> ignore seasons newer than this_year - N (preliminary prices)
#   no_processing_check: True -> keep a state's all-uses price even if under half national fresh
#   yield_if_fresh_dominant: True -> a geography's yield is used only when its all-uses price is
#         at least PROCESSING_RATIO of the fresh price (its crop is mainly fresh); else price only
# Fresh-market price series per crop live in FRESH, after MAPPING.
MAPPING = {
    # ---- tree fruit and nuts ----
    # Almonds: price is $/lb shelled; utilized yield LB/ACRE is shelled. Same basis, no conversion.
    "almonds": {"unit": "lb",
                "price": [(S("ALMONDS - PRICE RECEIVED, MEASURED IN $ / LB"), 1)],
                "yield": [(S("ALMONDS, UTILIZED - YIELD, MEASURED IN LB / ACRE"), 1)]},
    # Apples: all-utilization price $/lb (fallback; fresh price in FRESH) vs total yield LB/ACRE.
    "apples": {"unit": "lb",
               "price": [(S("APPLES - PRICE RECEIVED, MEASURED IN $ / LB"), 1)],
               "yield": [(S("APPLES - YIELD, MEASURED IN LB / ACRE"), 1)]},
    # Apricots: $/TON -> $/lb (/2000); TONS/ACRE -> lb (x2000).
    "apricots": {"unit": "lb",
                 "price": [(S("APRICOTS - PRICE RECEIVED, MEASURED IN $ / TON"), 1 / LB_PER_TON)],
                 "yield": [(S("APRICOTS - YIELD, MEASURED IN TONS / ACRE"), LB_PER_TON)]},
    # Avocado: $/TON -> $/lb; TONS/ACRE -> lb. Florida's all-uses price is about 40% of the
    # national fresh price because Florida grows lower-priced green-skin varieties sold fresh, not
    # because it is processed, so the processing-dominated check is off for avocados.
    "avocado": {"unit": "lb", "no_processing_check": True,
                "price": [(S("AVOCADOS - PRICE RECEIVED, MEASURED IN $ / TON"), 1 / LB_PER_TON)],
                "yield": [(S("AVOCADOS - YIELD, MEASURED IN TONS / ACRE"), LB_PER_TON)]},
    # Cherries: sweet cherries (the larger crop by value). $/TON -> $/lb; TONS/ACRE -> lb.
    "cherries": {"unit": "lb",
                 "price": [(S("CHERRIES, SWEET - PRICE RECEIVED, MEASURED IN $ / TON"), 1 / LB_PER_TON)],
                 "yield": [(S("CHERRIES, SWEET - YIELD, MEASURED IN TONS / ACRE"), LB_PER_TON)]},
    # Citrus: oranges, all types. On-tree equivalent price $/box (what the grower nets after
    # picking and hauling) / box weight -> $/lb; BOXES/ACRE x box weight -> lb. State only:
    # the US box mixes 80 lb and 90 lb boxes, so no clean national lb figure.
    "citrus": {"unit": "lb", "states_only": True,
               "price": [(S("ORANGES - PRICE RECEIVED, MEASURED IN $ / BOX, ON TREE EQUIV"),
                          {k: 1.0 / v for k, v in ORANGE_BOX_LB.items()})],
               "yield": [(S("ORANGES - YIELD, MEASURED IN BOXES / ACRE"), dict(ORANGE_BOX_LB))]},
    # Lemons: on-tree $/box / box lb; BOXES/ACRE x box lb.
    "lemons": {"unit": "lb",
               "price": [(S("LEMONS - PRICE RECEIVED, MEASURED IN $ / BOX, ON TREE EQUIV"),
                          {k: 1.0 / v for k, v in LEMON_BOX_LB.items()})],
               "yield": [(S("LEMONS - YIELD, MEASURED IN BOXES / ACRE"), dict(LEMON_BOX_LB))]},
    # Peaches: all-uses price is the fallback (fresh price in FRESH). $/TON -> $/lb; TONS/ACRE -> lb.
    "peaches": {"unit": "lb",
                "price": [(S("PEACHES - PRICE RECEIVED, MEASURED IN $ / TON"), 1 / LB_PER_TON)],
                "yield": [(S("PEACHES - YIELD, MEASURED IN TONS / ACRE"), LB_PER_TON)]},
    # Pistachios: $/lb in-shell; utilized yield LB/ACRE in-shell.
    "pistachios": {"unit": "lb",
                   "price": [(S("PISTACHIOS - PRICE RECEIVED, MEASURED IN $ / LB"), 1)],
                   "yield": [(S("PISTACHIOS, UTILIZED - YIELD, MEASURED IN LB / ACRE"), 1)]},
    # Plums: $/TON -> $/lb; TONS/ACRE -> lb.
    "plums": {"unit": "lb",
              "price": [(S("PLUMS - PRICE RECEIVED, MEASURED IN $ / TON"), 1 / LB_PER_TON)],
              "yield": [(S("PLUMS - YIELD, MEASURED IN TONS / ACRE"), LB_PER_TON)]},
    # ---- berries ----
    # Blueberries: cultivated ("TAME"); all-uses price is the fallback (fresh in FRESH). $/lb; LB/ACRE.
    "blueberries": {"unit": "lb",
                    "price": [(S("BLUEBERRIES, TAME - PRICE RECEIVED, MEASURED IN $ / LB"), 1)],
                    "yield": [(S("BLUEBERRIES, TAME - YIELD, MEASURED IN LB / ACRE"), 1)]},
    "raspberries": {"unit": "lb",
                    "price": [(S("RASPBERRIES - PRICE RECEIVED, MEASURED IN $ / LB"), 1)],
                    "yield": [(S("RASPBERRIES - YIELD, MEASURED IN LB / ACRE"), 1)]},
    # Strawberries: all-uses price is the fallback (fresh in FRESH). $/CWT -> $/lb (/100);
    # CWT/ACRE -> lb (x100).
    "strawberries": {"unit": "lb",
                     "price": [(S("STRAWBERRIES - PRICE RECEIVED, MEASURED IN $ / CWT"), 1 / LB_PER_CWT)],
                     "yield": [(S("STRAWBERRIES - YIELD, MEASURED IN CWT / ACRE"), LB_PER_CWT)]},
    # ---- vegetables: $/CWT -> $/lb (/100), CWT/ACRE -> lb (x100). The all-uses price here is the
    # fallback; the fresh-market price in FRESH is used wherever NASS publishes it. ----
    "artichokes": {"unit": "lb",
                   "price": [(S("ARTICHOKES - PRICE RECEIVED, MEASURED IN $ / CWT"), 1 / LB_PER_CWT)],
                   "yield": [(S("ARTICHOKES - YIELD, MEASURED IN CWT / ACRE"), LB_PER_CWT)]},
    "asparagus": {"unit": "lb",
                  "price": [(S("ASPARAGUS - PRICE RECEIVED, MEASURED IN $ / CWT"), 1 / LB_PER_CWT)],
                  "yield": [(S("ASPARAGUS - YIELD, MEASURED IN CWT / ACRE"), LB_PER_CWT)]},
    "broccoli": {"unit": "lb",
                 "price": [(S("BROCCOLI - PRICE RECEIVED, MEASURED IN $ / CWT"), 1 / LB_PER_CWT)],
                 "yield": [(S("BROCCOLI - YIELD, MEASURED IN CWT / ACRE"), LB_PER_CWT)]},
    "carrots": {"unit": "lb",
                "price": [(S("CARROTS - PRICE RECEIVED, MEASURED IN $ / CWT"), 1 / LB_PER_CWT)],
                "yield": [(S("CARROTS - YIELD, MEASURED IN CWT / ACRE"), LB_PER_CWT)]},
    "cauliflower": {"unit": "lb",
                    "price": [(S("CAULIFLOWER - PRICE RECEIVED, MEASURED IN $ / CWT"), 1 / LB_PER_CWT)],
                    "yield": [(S("CAULIFLOWER - YIELD, MEASURED IN CWT / ACRE"), LB_PER_CWT)]},
    "celery": {"unit": "lb",
               "price": [(S("CELERY - PRICE RECEIVED, MEASURED IN $ / CWT"), 1 / LB_PER_CWT)],
               "yield": [(S("CELERY - YIELD, MEASURED IN CWT / ACRE"), LB_PER_CWT)]},
    "garlic": {"unit": "lb",
               "price": [(S("GARLIC - PRICE RECEIVED, MEASURED IN $ / CWT"), 1 / LB_PER_CWT)],
               "yield": [(S("GARLIC - YIELD, MEASURED IN CWT / ACRE"), LB_PER_CWT)]},
    # Onions: dry bulb onions (NASS "ONIONS, DRY").
    "onions": {"unit": "lb",
               "price": [(S("ONIONS, DRY - PRICE RECEIVED, MEASURED IN $ / CWT"), 1 / LB_PER_CWT)],
               "yield": [(S("ONIONS, DRY - YIELD, MEASURED IN CWT / ACRE"), LB_PER_CWT)]},
    # Peppers: bell peppers.
    "peppers": {"unit": "lb",
                "price": [(S("PEPPERS, BELL - PRICE RECEIVED, MEASURED IN $ / CWT"), 1 / LB_PER_CWT)],
                "yield": [(S("PEPPERS, BELL - YIELD, MEASURED IN CWT / ACRE"), LB_PER_CWT)]},
    # Potatoes: already $/CWT and CWT/ACRE; calculator unit is cwt. No conversion.
    "potatoes": {"unit": "cwt",
                 "price": [(S("POTATOES - PRICE RECEIVED, MEASURED IN $ / CWT"), 1)],
                 "yield": [(S("POTATOES - YIELD, MEASURED IN CWT / ACRE"), 1)]},
    # Sweet corn: yield is all uses (fresh plus processing); price fresh (FRESH).
    "sweet corn": {"unit": "lb",
                   "price": [(S("SWEET CORN - PRICE RECEIVED, MEASURED IN $ / CWT"), 1 / LB_PER_CWT)],
                   "yield": [(S("SWEET CORN - YIELD, MEASURED IN CWT / ACRE"), LB_PER_CWT)]},
    "sweet potatoes": {"unit": "cwt",
                       "price": [(S("SWEET POTATOES - PRICE RECEIVED, MEASURED IN $ / CWT"), 1)],
                       "yield": [(S("SWEET POTATOES - YIELD, MEASURED IN CWT / ACRE"), 1)]},
    # Tomatoes: EXCEPTION. The NASS tomato yield ("IN THE OPEN", ~1,000 cwt/acre nationally) is
    # dominated by processing tomatoes (California), and the all-uses price (~$8/cwt) is a
    # processing price. NASS no longer publishes a fresh-market tomato yield. So the price is
    # always fresh-market; a geography's "in the open" yield is used only where its crop is mainly
    # fresh (all-uses price at least half the fresh price, e.g. Florida 290 cwt/acre). Elsewhere,
    # including the national record, only the price is published and yield stays the
    # calculator's built-in default.
    "tomatoes": {"unit": "lb", "yield_if_fresh_dominant": True,
                 "price": [(S("TOMATOES - PRICE RECEIVED, MEASURED IN $ / CWT"), 1 / LB_PER_CWT)],
                 "yield": [(S("TOMATOES, IN THE OPEN - YIELD, MEASURED IN CWT / ACRE"), LB_PER_CWT)]},
    "cabbage": {"unit": "lb",
                "price": [(S("CABBAGE - PRICE RECEIVED, MEASURED IN $ / CWT"), 1 / LB_PER_CWT)],
                "yield": [(S("CABBAGE - YIELD, MEASURED IN CWT / ACRE"), LB_PER_CWT)]},
    # Kale: NASS "GREENS, KALE", calendar-year price (no marketing-year series exists). NASS
    # surveys kale in California only, so it is published for California only (states_only);
    # the national figure is the calculator's built-in default.
    "kale": {"unit": "lb", "states_only": True,
             "price": [(S("GREENS, KALE - PRICE RECEIVED, MEASURED IN $ / CWT"), 1 / LB_PER_CWT)],
             "yield": [(S("GREENS, KALE - YIELD, MEASURED IN CWT / ACRE"), LB_PER_CWT)]},
    # Lettuce: NASS has no all-lettuce series; head lettuce is used.
    "lettuce": {"unit": "lb",
                "price": [(S("LETTUCE, HEAD - PRICE RECEIVED, MEASURED IN $ / CWT"), 1 / LB_PER_CWT)],
                "yield": [(S("LETTUCE, HEAD - YIELD, MEASURED IN CWT / ACRE"), LB_PER_CWT)]},
    "spinach": {"unit": "lb",
                "price": [(S("SPINACH - PRICE RECEIVED, MEASURED IN $ / CWT"), 1 / LB_PER_CWT)],
                "yield": [(S("SPINACH - YIELD, MEASURED IN CWT / ACRE"), LB_PER_CWT)]},
    # Melons: calculator unit is cwt, NASS reports $/CWT and CWT/ACRE. No conversion.
    "cantaloupe": {"unit": "cwt",
                   "price": [(S("MELONS, CANTALOUP - PRICE RECEIVED, MEASURED IN $ / CWT"), 1)],
                   "yield": [(S("MELONS, CANTALOUP - YIELD, MEASURED IN CWT / ACRE"), 1)]},
    "watermelon": {"unit": "cwt",
                   "price": [(S("MELONS, WATERMELON - PRICE RECEIVED, MEASURED IN $ / CWT"), 1)],
                   "yield": [(S("MELONS, WATERMELON - YIELD, MEASURED IN CWT / ACRE"), 1)]},
    "cucumbers": {"unit": "lb",
                  "price": [(S("CUCUMBERS - PRICE RECEIVED, MEASURED IN $ / CWT"), 1 / LB_PER_CWT)],
                  "yield": [(S("CUCUMBERS - YIELD, MEASURED IN CWT / ACRE"), LB_PER_CWT)]},
    "pumpkins": {"unit": "lb",
                 "price": [(S("PUMPKINS - PRICE RECEIVED, MEASURED IN $ / CWT"), 1 / LB_PER_CWT)],
                 "yield": [(S("PUMPKINS - YIELD, MEASURED IN CWT / ACRE"), LB_PER_CWT)]},
    "squash": {"unit": "lb",
               "price": [(S("SQUASH - PRICE RECEIVED, MEASURED IN $ / CWT"), 1 / LB_PER_CWT)],
               "yield": [(S("SQUASH - YIELD, MEASURED IN CWT / ACRE"), LB_PER_CWT)]},
    # Wine grapes: "GRAPES, WINE TYPE" $/TON and TONS/ACRE (calculator unit ton). State only:
    # NASS publishes no national wine-type price or yield series.
    "wine grapes": {"unit": "ton",
                    "price": [(S("GRAPES, WINE TYPE - PRICE RECEIVED, MEASURED IN $ / TON"), 1)],
                    "yield": [(S("GRAPES, WINE TYPE - YIELD, MEASURED IN TONS / ACRE"), 1)]},
    # ---- field crops ----
    "barley": {"unit": "bu",
               "price": [(S("BARLEY - PRICE RECEIVED, MEASURED IN $ / BU"), 1)],
               "yield": [(S("BARLEY - YIELD, MEASURED IN BU / ACRE"), 1)]},
    # Canola: $/CWT -> $/lb (/100); yield already LB/ACRE.
    "canola": {"unit": "lb",
               "price": [(S("CANOLA - PRICE RECEIVED, MEASURED IN $ / CWT"), 1 / LB_PER_CWT)],
               "yield": [(S("CANOLA - YIELD, MEASURED IN LB / ACRE"), 1)]},
    # Field corn: "CORN, GRAIN" $/BU and BU/ACRE.
    "field corn": {"unit": "bu",
                   "price": [(S("CORN, GRAIN - PRICE RECEIVED, MEASURED IN $ / BU"), 1)],
                   "yield": [(S("CORN, GRAIN - YIELD, MEASURED IN BU / ACRE"), 1)]},
    # Cotton: upland cotton lint, $/lb and LB/ACRE. Upland is about 97% of US acres and,
    # unlike the all-cotton series, is published by state.
    "cotton": {"unit": "lb",
               "price": [(S("COTTON, UPLAND - PRICE RECEIVED, MEASURED IN $ / LB"), 1)],
               "yield": [(S("COTTON, UPLAND - YIELD, MEASURED IN LB / ACRE"), 1)]},
    # Dry beans: all dry edible beans excl chickpeas. $/CWT; LB/ACRE -> cwt (/100).
    "dry beans": {"unit": "cwt",
                  "price": [(S("BEANS, DRY EDIBLE, (EXCL CHICKPEAS) - PRICE RECEIVED, MEASURED IN $ / CWT"), 1)],
                  "yield": [(S("BEANS, DRY EDIBLE, (EXCL CHICKPEAS) - YIELD, MEASURED IN LB / ACRE"), 1 / LB_PER_CWT)]},
    "hops": {"unit": "lb",
             "price": [(S("HOPS - PRICE RECEIVED, MEASURED IN $ / LB"), 1)],
             "yield": [(S("HOPS - YIELD, MEASURED IN LB / ACRE"), 1)]},
    "peanuts": {"unit": "lb",
                "price": [(S("PEANUTS - PRICE RECEIVED, MEASURED IN $ / LB"), 1)],
                "yield": [(S("PEANUTS - YIELD, MEASURED IN LB / ACRE"), 1)]},
    # Rice: $/CWT; yield LB/ACRE -> cwt (/100).
    "rice": {"unit": "cwt",
             "price": [(S("RICE - PRICE RECEIVED, MEASURED IN $ / CWT"), 1)],
             "yield": [(S("RICE - YIELD, MEASURED IN LB / ACRE"), 1 / LB_PER_CWT)]},
    # Sorghum: price $/CWT -> $/bu (x 56 lb/bu / 100 = x0.56); yield BU/ACRE.
    "sorghum": {"unit": "bu",
                "price": [(S("SORGHUM, GRAIN - PRICE RECEIVED, MEASURED IN $ / CWT"), LB_PER_BU_SORGHUM / LB_PER_CWT)],
                "yield": [(S("SORGHUM, GRAIN - YIELD, MEASURED IN BU / ACRE"), 1)]},
    "soybeans": {"unit": "bu",
                 "price": [(S("SOYBEANS - PRICE RECEIVED, MEASURED IN $ / BU"), 1)],
                 "yield": [(S("SOYBEANS - YIELD, MEASURED IN BU / ACRE"), 1)]},
    # Sugar beets: the price for the crop harvested last fall is a preliminary payment estimate
    # (processors settle over 12 to 18 months) and NASS revises it a year later; the 2025 US
    # preliminary was $40/ton against $69.40 settled for 2024, with no 2025 state prices yet.
    # So only seasons at least 2 years back are used (newest_year_lag).
    "sugar beets": {"unit": "ton", "newest_year_lag": 2,
                    "price": [(S("SUGARBEETS - PRICE RECEIVED, MEASURED IN $ / TON"), 1)],
                    "yield": [(S("SUGARBEETS - YIELD, MEASURED IN TONS / ACRE"), 1)]},
    # Wheat: all wheat (winter, spring, durum).
    "wheat": {"unit": "bu",
              "price": [(S("WHEAT - PRICE RECEIVED, MEASURED IN $ / BU"), 1)],
              "yield": [(S("WHEAT - YIELD, MEASURED IN BU / ACRE"), 1)]},
}

def _fresh_cwt(name):
    return [(S(name + ", FRESH MARKET - PRICE RECEIVED, MEASURED IN $ / CWT"), 1 / LB_PER_CWT)]


# Fresh-market price series (decision 2026-11-07). Same conversions as the all-uses series in
# MAPPING. Crops not listed have no fresh/processing split in NASS (nuts, field crops) or are
# processed by definition (wine grapes).
FRESH = {
    "apples": [(S("APPLES, FRESH MARKET - PRICE RECEIVED, MEASURED IN $ / LB"), 1)],
    "apricots": [(S("APRICOTS, FRESH MARKET - PRICE RECEIVED, MEASURED IN $ / TON"), 1 / LB_PER_TON)],
    "avocado": [(S("AVOCADOS, FRESH MARKET - PRICE RECEIVED, MEASURED IN $ / TON"), 1 / LB_PER_TON)],
    "cherries": [(S("CHERRIES, SWEET, FRESH MARKET - PRICE RECEIVED, MEASURED IN $ / TON"), 1 / LB_PER_TON)],
    "citrus": [(S("ORANGES, FRESH MARKET - PRICE RECEIVED, MEASURED IN $ / BOX, ON TREE EQUIV"),
                {k: 1.0 / v for k, v in ORANGE_BOX_LB.items()})],
    "lemons": [(S("LEMONS, FRESH MARKET - PRICE RECEIVED, MEASURED IN $ / BOX, ON TREE EQUIV"),
                {k: 1.0 / v for k, v in LEMON_BOX_LB.items()})],
    "peaches": [(S("PEACHES, FRESH MARKET - PRICE RECEIVED, MEASURED IN $ / TON"), 1 / LB_PER_TON)],
    "plums": [(S("PLUMS, FRESH MARKET - PRICE RECEIVED, MEASURED IN $ / TON"), 1 / LB_PER_TON)],
    "blueberries": [(S("BLUEBERRIES, TAME, FRESH MARKET - PRICE RECEIVED, MEASURED IN $ / LB"), 1)],
    "raspberries": [(S("RASPBERRIES, FRESH MARKET - PRICE RECEIVED, MEASURED IN $ / LB"), 1)],
    "strawberries": _fresh_cwt("STRAWBERRIES"),
    "artichokes": _fresh_cwt("ARTICHOKES"),
    "asparagus": _fresh_cwt("ASPARAGUS"),
    "broccoli": _fresh_cwt("BROCCOLI"),
    "carrots": _fresh_cwt("CARROTS"),
    "cauliflower": _fresh_cwt("CAULIFLOWER"),
    "celery": _fresh_cwt("CELERY"),
    "garlic": _fresh_cwt("GARLIC"),
    "onions": _fresh_cwt("ONIONS, DRY"),
    "peppers": _fresh_cwt("PEPPERS, BELL"),
    "potatoes": [(S("POTATOES, FRESH MARKET - PRICE RECEIVED, MEASURED IN $ / CWT"), 1)],
    "sweet corn": _fresh_cwt("SWEET CORN"),
    "sweet potatoes": [(S("SWEET POTATOES, FRESH MARKET - PRICE RECEIVED, MEASURED IN $ / CWT"), 1)],
    "tomatoes": _fresh_cwt("TOMATOES"),
    "cabbage": _fresh_cwt("CABBAGE"),
    "kale": _fresh_cwt("GREENS, KALE"),
    "lettuce": _fresh_cwt("LETTUCE, HEAD"),
    "spinach": _fresh_cwt("SPINACH"),
    "cantaloupe": [(S("MELONS, CANTALOUP, FRESH MARKET - PRICE RECEIVED, MEASURED IN $ / CWT"), 1)],
    "watermelon": [(S("MELONS, WATERMELON, FRESH MARKET - PRICE RECEIVED, MEASURED IN $ / CWT"), 1)],
    "cucumbers": _fresh_cwt("CUCUMBERS"),
    "pumpkins": _fresh_cwt("PUMPKINS"),
    "squash": _fresh_cwt("SQUASH"),
}

# Not mapped (calculator keeps its built-in default):
#   bananas, eggplant: no current NASS price/yield series.
#   hemp: NASS splits hemp into floral, grain, fiber and seed with prices from $0.21/lb to
#         $70/lb; no single series fits a generic "hemp" row.

STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
    "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee",
    "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}


def read_calculator():
    html = open(CALC, encoding="utf-8").read()
    m = re.search(r"const CROPS=\[(.*?)\];", html, re.S)
    crops = re.findall(r'"([^"]+)"', m.group(1))
    m = re.search(r"const DEFAULTS=\{(.*?)\n\s*\};", html, re.S)
    defaults = {}
    for k, u, p, y in re.findall(r'"([^"]+)":\{u:"([^"]+)",p:([\d.]+),y:([\d.]+)\}', m.group(1)):
        defaults[k] = {"u": u, "p": float(p), "y": float(y)}
    return crops, defaults


def latest_filename():
    req = urllib.request.Request(INDEX_URL, headers=UA)
    html = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
    names = sorted(set(re.findall(r"qs\.crops_(\d{8})\.txt\.gz", html)))
    if not names:
        sys.exit("No qs.crops file listed at " + INDEX_URL)
    return "qs.crops_%s.txt.gz" % names[-1]


def download(name, cache_dir):
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, name)
    url = FILE_BASE + name
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r:
        size = int(r.headers.get("Content-Length", "0"))
        if os.path.exists(path) and size and os.path.getsize(path) == size:
            print("cached:", path)
            return path
        print("downloading %s (%.0f MB)" % (url, size / 1e6))
        tmp = path + ".part"
        with open(tmp, "wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)
    os.replace(tmp, path)
    return path


def parse_value(s):
    s = s.strip().replace(",", "")
    try:
        v = float(s)
    except ValueError:
        return None  # (D) withheld, (NA), (Z), (X), (S) etc.
    return v if v > 0 else None


def scan(path, wanted):
    """Return {(short_desc, geo, ref_period): {year: value}}."""
    out = {}
    with gzip.open(path, "rb") as f:
        header = f.readline().decode().rstrip("\n").split("\t")
        ix = {n: i for i, n in enumerate(header)}
        need = ["SOURCE_DESC", "STATISTICCAT_DESC", "SHORT_DESC", "DOMAIN_DESC", "AGG_LEVEL_DESC",
                "STATE_ALPHA", "YEAR", "FREQ_DESC", "REFERENCE_PERIOD_DESC", "VALUE"]
        for n in need:
            if n not in ix:
                sys.exit("NASS file layout changed: missing column " + n)
        for raw in f:
            if b"PRICE RECEIVED" not in raw and b"\tYIELD\t" not in raw:
                continue
            c = raw.decode("utf-8", "replace").rstrip("\n").split("\t")
            if (c[ix["SOURCE_DESC"]] != "SURVEY" or c[ix["FREQ_DESC"]] != "ANNUAL"
                    or c[ix["DOMAIN_DESC"]] != "TOTAL"):
                continue
            sd = c[ix["SHORT_DESC"]]
            if sd not in wanted:
                continue
            agg = c[ix["AGG_LEVEL_DESC"]]
            if agg == "NATIONAL":
                geo = "US"
            elif agg == "STATE":
                geo = c[ix["STATE_ALPHA"]]
            else:
                continue
            ref = c[ix["REFERENCE_PERIOD_DESC"]]
            if ref not in ("MARKETING YEAR", "YEAR"):
                continue  # skip in-season forecasts
            v = parse_value(c[ix["VALUE"]])
            if v is None:
                continue
            out.setdefault((sd, geo, ref), {})[int(c[ix["YEAR"]])] = v
    return out


def factor_for(f, geo):
    if isinstance(f, dict):
        return f.get(geo)
    return f


def series(data, specs, geo, refs):
    """First spec with data for this geo -> {year: converted value}."""
    for sd, f in specs:
        fac = factor_for(f, geo)
        if fac is None:
            continue
        for ref in refs:
            s = data.get((sd, geo, ref))
            if s:
                return {y: v * fac for y, v in s.items()}
    return {}


def rnd(v):
    if v >= 100:
        return round(v, 1) if round(v, 1) != round(v) else round(v)
    if v >= 10:
        return round(v, 1)
    if v >= 1:
        return round(v, 2)
    return round(v, 3)


def build(data, defaults, this_year):
    crops = {}
    flags = []
    geos = ["US"] + sorted(STATE_NAMES)
    for key, spec in MAPPING.items():
        d = defaults.get(key)
        if not d:
            # Crop is in CROPS but has no built-in default (hops): publish NASS figures in the
            # mapped unit; the calculator fills them when the row's unit is untouched.
            print("NOTE %s: no built-in default; using NASS only, no sanity baseline" % key)
            d = {"u": spec["unit"], "p": None, "y": None}
        if d["u"] != spec["unit"]:
            print("SKIP %s: calculator unit %s != mapped unit %s" % (key, d["u"], spec["unit"]))
            continue
        entry = {"unit": spec["unit"], "national": None, "states": {}}
        refs = ("MARKETING YEAR", "YEAR")  # marketing year preferred, calendar year fallback
        us_fresh = series(data, FRESH.get(key, []), "US", refs)
        for geo in geos:
            if geo == "US" and spec.get("states_only"):
                continue
            fr = series(data, FRESH.get(key, []), geo, refs)
            pr = series(data, spec["price"], geo, refs)
            yl = {} if spec.get("price_only") else series(data, spec["yield"], geo, ("YEAR",))

            def fresh_ref(y):  # fresh price to judge a processing-dominated all-uses price
                return fr.get(y) or us_fresh.get(y)

            rec = None
            years = set(fr) | set(pr)
            if not (spec.get("price_only") or spec.get("yield_if_fresh_dominant")):
                years &= set(yl)
            for yr in sorted(years, reverse=True):
                if this_year - yr < spec.get("newest_year_lag", 0):
                    continue
                if this_year - yr > MAX_AGE_YEARS:
                    break
                if (key, geo) in EXCLUDE:
                    flags.append("%s %s excluded: %s" % (key, geo, EXCLUDE[(key, geo)]))
                    break
                if (geo != "US" and yr in fr and pr.get(yr)
                        and fr[yr] > FRESH_PREMIUM_MAX * pr[yr]):
                    flags.append("%s %s %d fresh price %s is over %.1fx all-uses %s (yield is "
                                 "processing-dominated), SKIPPED" % (
                                     key, geo, yr, rnd(fr[yr]), FRESH_PREMIUM_MAX, rnd(pr[yr])))
                    break
                if yr in fr:
                    price, basis = fr[yr], "fresh"
                else:
                    price, basis = pr[yr], "all-uses"
                    if (not spec.get("no_processing_check") and fresh_ref(yr)
                            and price < PROCESSING_RATIO * fresh_ref(yr)):
                        flags.append("%s %s %d all-uses price %s is under half the fresh price %s "
                                     "(processing-dominated), SKIPPED" % (
                                         key, geo, yr, rnd(price), rnd(fresh_ref(yr))))
                        continue
                y = yl.get(yr)
                if spec.get("yield_if_fresh_dominant") and y is not None:
                    a = pr.get(yr)
                    if not (a and fresh_ref(yr) and a >= PROCESSING_RATIO * fresh_ref(yr)):
                        y = None  # yield is processing-dominated: price only
                rec = {"price": rnd(price), "yield": rnd(y) if y is not None else None,
                       "year": yr, "basis": basis}
                break
            if rec is None:
                continue
            bad = False
            for fld, dv in (("price", d["p"]), ("yield", d["y"])):
                v = rec[fld]
                lim = 4 if fld == "yield" else 3  # 4x on yield keeps real outliers like OR raspberries
                if v and dv and (v / dv > lim or dv / v > lim):
                    bad = True
                    flags.append("%s %s %s %s vs built-in %s (%.1fx), SKIPPED" % (
                        key, geo, fld, v, dv, max(v / dv, dv / v)))
            # A figure more than 3x from the built-in default is usually a processing-market or
            # single-state series that would mislead a grower; the calculator then keeps its
            # built-in default for that crop and place.
            if bad:
                continue
            if geo == "US":
                entry["national"] = rec
            else:
                entry["states"][geo] = rec
        if entry["national"] is None:
            del entry["national"]
        if "national" in entry or entry["states"]:
            crops[key] = entry
    return crops, flags


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache-dir", default=os.environ.get("NASS_CACHE_DIR", "/tmp/nass"))
    ap.add_argument("--file", help="use an already downloaded qs.crops_*.txt.gz")
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()

    calc_crops, defaults = read_calculator()
    for c in calc_crops:
        if c.lower() not in MAPPING:
            print("no NASS mapping (built-in default stays):", c)

    path = a.file or download(latest_filename(), a.cache_dir)
    fname = os.path.basename(path)
    m = re.search(r"(\d{4})(\d{2})(\d{2})", fname)
    file_date = "%s-%s-%s" % m.groups() if m else None

    wanted = {sd for spec in MAPPING.values() for k in ("price", "yield") for sd, _ in spec[k]}
    wanted |= {sd for specs in FRESH.values() for sd, _ in specs}
    print("scanning", path)
    data = scan(path, wanted)
    missing = sorted(w for w in wanted if not any(k[0] == w for k in data))
    for w in missing:
        print("WARNING: series not found in file:", w)

    crops, flags = build(data, defaults, dt.date.today().year)

    print("\ncrop            unit  built-in price/yield   ->  USDA US price/yield (year)  states")
    for key in sorted(set(defaults) | set(crops)):
        d = defaults[key] if key in defaults else {"u": crops[key]["unit"], "p": "-", "y": "-"}
        e = crops.get(key)
        n = e.get("national") if e else None
        print("%-15s %-5s %8s / %-9s -> %s  %s" % (
            key, d["u"], d["p"], d["y"],
            ("%s / %s (%s, %s)" % (n["price"], n["yield"], n["year"], n["basis"])) if n else "no national",
            len(e["states"]) if e else 0))
    if flags:
        print("\nFLAGGED (more than 3x from built-in default, or processing-dominated):")
        for f in flags:
            print("  " + f)

    old = None
    if os.path.exists(a.out):
        try:
            old = json.load(open(a.out, encoding="utf-8"))
        except ValueError:
            old = None
    if old and old.get("crops") == json.loads(json.dumps(crops)):
        print("\nno change in crop figures; %s left as is" % a.out)
        return
    doc = {
        "generated": dt.date.today().isoformat(),
        "source": "USDA NASS Quick Stats (survey, annual price received and yield per acre)",
        "source_url": INDEX_URL,
        "source_file": fname,
        "source_file_date": file_date,
        "state_names": STATE_NAMES,
        "crops": crops,
    }
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, sort_keys=True)
        f.write("\n")
    print("\nwrote", a.out, "(%d crops)" % len(crops))


if __name__ == "__main__":
    main()
