import os
import re
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from itertools import product
from typing import Optional
import requests as rq

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

DEFAULT_DINING_COURTS = ['Earhart', 'Ford', 'Hillenbrand', 'Wiley', 'Windsor']
QUICK_BITES_LOCATIONS = ['1bowl', "Pete's Za", 'Sushi Boss']

# Standard Purdue dining court windows used if API returns null Hours
DEFAULT_MEAL_WINDOWS = {
    'breakfast': ('07:00:00', '10:00:00'),
    'brunch': ('10:00:00', '14:00:00'),
    'lunch': ('11:00:00', '14:00:00'),
    'late lunch': ('14:00:00', '17:00:00'),
    'dinner': ('17:00:00', '20:30:00'),
}

# Hardcoded USDA per-serving macro estimates for custom/self-serve staples
FALLBACK_MACROS = {
    'hard-boiled egg': {
        'calories': 155.0, 'protein': 12.6, 'carbs': 1.1, 'fat': 10.6, 'sugar': 1.1,
        'ingredients': 'Hard-Boiled Eggs (2 large)'
    },
    'hard-boiled eggs': {
        'calories': 155.0, 'protein': 12.6, 'carbs': 1.1, 'fat': 10.6, 'sugar': 1.1,
        'ingredients': 'Hard-Boiled Eggs (2 large)'
    },
    'garbanzo beans': {
        'calories': 135.0, 'protein': 7.3, 'carbs': 22.5, 'fat': 2.1, 'sugar': 4.0,
        'ingredients': 'Garbanzo Beans, Water, Salt (1/2 cup)'
    },
    'chickpeas': {
        'calories': 135.0, 'protein': 7.3, 'carbs': 22.5, 'fat': 2.1, 'sugar': 4.0,
        'ingredients': 'Chickpeas, Water, Salt (1/2 cup)'
    },
    'extra virgin olive oil': {
        'calories': 119.0, 'protein': 0.0, 'carbs': 0.0, 'fat': 13.5, 'sugar': 0.0,
        'ingredients': 'Extra Virgin Olive Oil (1 tbsp)'
    },
    'olive oil': {
        'calories': 119.0, 'protein': 0.0, 'carbs': 0.0, 'fat': 13.5, 'sugar': 0.0,
        'ingredients': 'Extra Virgin Olive Oil (1 tbsp)'
    },
    'fresh spinach': {
        'calories': 14.0, 'protein': 1.7, 'carbs': 2.2, 'fat': 0.2, 'sugar': 0.3,
        'ingredients': 'Fresh Spinach Leaves (2 cups)'
    },
    'leafy greens': {
        'calories': 15.0, 'protein': 1.5, 'carbs': 2.5, 'fat': 0.2, 'sugar': 0.4,
        'ingredients': 'Mixed Leafy Greens (2 cups)'
    },
    'plain white rice': {
        'calories': 205.0, 'protein': 4.3, 'carbs': 44.5, 'fat': 0.4, 'sugar': 0.1,
        'ingredients': 'Long Grain White Rice, Water (1 cup cooked)'
    },
    'long grain rice': {
        'calories': 205.0, 'protein': 4.3, 'carbs': 44.5, 'fat': 0.4, 'sugar': 0.1,
        'ingredients': 'Long Grain White Rice, Water (1 cup cooked)'
    },
    'jasmine rice': {
        'calories': 205.0, 'protein': 4.3, 'carbs': 44.5, 'fat': 0.4, 'sugar': 0.1,
        'ingredients': 'Jasmine Rice, Water (1 cup cooked)'
    },
    'plain brown rice': {
        'calories': 216.0, 'protein': 5.0, 'carbs': 44.8, 'fat': 1.8, 'sugar': 0.7,
        'ingredients': 'Whole Grain Brown Rice, Water (1 cup cooked)'
    },
    'brown rice': {
        'calories': 216.0, 'protein': 5.0, 'carbs': 44.8, 'fat': 1.8, 'sugar': 0.7,
        'ingredients': 'Whole Grain Brown Rice, Water (1 cup cooked)'
    },
    'plain grilled chicken breast': {
        'calories': 185.0, 'protein': 35.0, 'carbs': 0.0, 'fat': 4.0, 'sugar': 0.0,
        'ingredients': 'Boneless Skinless Chicken Breast, Sea Salt, Black Pepper (4 oz)'
    },
    'grilled chicken breast': {
        'calories': 185.0, 'protein': 35.0, 'carbs': 0.0, 'fat': 4.0, 'sugar': 0.0,
        'ingredients': 'Boneless Skinless Chicken Breast, Sea Salt, Black Pepper (4 oz)'
    },
}

# Ordered from most specific composite terms to most general single ingredients
# so items like 'Apple Pie', 'Pork Banh Mi', 'Queso Dip', and 'Walnut Salad'
# never collide with single-ingredient keywords ('apple', 'pork', 'beef').
ORDERED_KEYWORD_MACROS = [
    # 1. Desserts, pastries, and baked sweets
    ('apple pie', (320.0, 2.5, 46.0, 14.0, 24.0)),
    ('peach cobbler', (310.0, 3.0, 48.0, 12.0, 26.0)),
    ('cherry pie', (325.0, 2.5, 47.0, 14.5, 25.0)),
    ('pie', (320.0, 3.0, 45.0, 14.0, 22.0)),
    ('cheesecake', (350.0, 6.0, 32.0, 22.0, 24.0)),
    ('cake', (310.0, 3.5, 46.0, 12.0, 28.0)),
    ('brownie', (290.0, 3.5, 38.0, 14.0, 24.0)),
    ('cookie', (210.0, 2.5, 28.0, 10.0, 16.0)),
    ('donut', (270.0, 3.5, 33.0, 14.0, 15.0)),
    ('muffin', (340.0, 5.0, 48.0, 14.0, 24.0)),
    ('ice cream', (230.0, 4.0, 28.0, 12.0, 22.0)),
    ('pudding', (180.0, 3.0, 30.0, 5.0, 20.0)),

    # 2. Dips, sauces, and spreads
    ('queso dip', (220.0, 8.0, 10.0, 16.0, 2.0)),
    ('queso', (210.0, 8.0, 9.0, 16.0, 2.0)),
    ('spinach dip', (230.0, 6.0, 11.0, 18.0, 2.0)),
    ('dip', (190.0, 5.0, 12.0, 14.0, 2.0)),
    ('gravy', (90.0, 2.0, 8.0, 5.5, 1.0)),
    ('sauce', (80.0, 1.5, 10.0, 4.0, 5.0)),

    # 3. Composite sandwiches, bowls, stir-fries, and dressed salads
    ('banh mi', (490.0, 24.0, 56.0, 17.0, 7.0)),
    ('burrito', (540.0, 24.0, 62.0, 20.0, 4.0)),
    ('quesadilla', (460.0, 22.0, 38.0, 24.0, 3.0)),
    ('mac and cheese', (380.0, 15.0, 40.0, 18.0, 5.0)),
    ('macaroni and cheese', (380.0, 15.0, 40.0, 18.0, 5.0)),
    ('lasagna', (390.0, 22.0, 34.0, 18.0, 6.0)),
    ('pizza', (310.0, 13.0, 34.0, 13.0, 4.0)),
    ('moo shu', (290.0, 24.0, 16.0, 14.0, 6.0)),
    ('stir fry', (280.0, 22.0, 18.0, 13.0, 6.0)),
    ('teriyaki', (290.0, 24.0, 22.0, 10.0, 12.0)),
    ('sweet and sour', (330.0, 18.0, 36.0, 12.0, 18.0)),
    ('general tso', (360.0, 18.0, 38.0, 15.0, 16.0)),
    ('orange chicken', (350.0, 19.0, 36.0, 14.0, 15.0)),
    ('goat cheese', (260.0, 9.0, 18.0, 17.0, 9.0)),
    ('walnut', (250.0, 8.0, 16.0, 17.0, 8.0)),
    ('caesar salad', (240.0, 8.0, 12.0, 18.0, 3.0)),
    ('chicken salad', (290.0, 20.0, 8.0, 20.0, 4.0)),
    ('tuna salad', (270.0, 19.0, 7.0, 18.0, 3.0)),
    ('egg salad', (280.0, 14.0, 6.0, 22.0, 3.0)),
    ('potato salad', (220.0, 4.0, 26.0, 11.0, 5.0)),

    # 4. Single whole-food fats and proteins
    ('extra virgin olive oil', (119.0, 0.0, 0.0, 13.5, 0.0)),
    ('olive oil', (119.0, 0.0, 0.0, 13.5, 0.0)),
    ('hard-boiled egg', (155.0, 12.6, 1.1, 10.6, 1.1)),
    ('hard boiled egg', (155.0, 12.6, 1.1, 10.6, 1.1)),
    ('scrambled egg', (180.0, 12.0, 2.0, 13.5, 1.0)),
    ('egg', (155.0, 12.5, 1.1, 10.6, 1.0)),
    ('grilled chicken breast', (185.0, 35.0, 0.0, 4.0, 0.0)),
    ('chicken breast', (185.0, 35.0, 0.0, 4.0, 0.0)),
    ('chicken', (215.0, 28.0, 2.0, 9.5, 0.5)),
    ('turkey', (200.0, 28.0, 1.0, 8.0, 0.5)),
    ('carne asada', (250.0, 27.0, 2.0, 14.0, 0.5)),
    ('steak', (265.0, 29.0, 0.0, 16.0, 0.0)),
    ('hamburger', (250.0, 26.0, 1.0, 15.0, 0.0)),
    ('ground beef', (250.0, 26.0, 1.0, 15.0, 0.0)),
    ('beef', (250.0, 26.0, 1.5, 15.0, 0.5)),
    ('pork loin', (220.0, 27.0, 0.0, 11.0, 0.0)),
    ('pork', (240.0, 25.0, 2.0, 14.0, 1.0)),
    ('ham', (180.0, 22.0, 2.0, 9.0, 1.5)),
    ('bacon', (160.0, 12.0, 0.5, 12.0, 0.0)),
    ('sausage', (230.0, 14.0, 2.0, 18.0, 1.0)),
    ('salmon', (235.0, 25.0, 0.0, 14.5, 0.0)),
    ('cod', (160.0, 24.0, 0.0, 6.0, 0.0)),
    ('tilapia', (165.0, 25.0, 0.0, 6.5, 0.0)),
    ('fish', (190.0, 24.0, 2.0, 8.0, 0.0)),
    ('shrimp', (140.0, 24.0, 1.0, 3.0, 0.0)),
    ('tofu', (160.0, 16.0, 4.0, 9.0, 1.0)),
    ('paneer', (260.0, 18.0, 4.0, 20.0, 2.0)),

    # 5. Legumes, grains, and complex carbohydrates
    ('garbanzo', (135.0, 7.3, 22.5, 2.1, 4.0)),
    ('chickpea', (135.0, 7.3, 22.5, 2.1, 4.0)),
    ('black bean', (130.0, 8.0, 23.0, 0.8, 1.0)),
    ('kidney bean', (130.0, 8.0, 23.0, 0.8, 1.0)),
    ('bean', (130.0, 7.5, 22.0, 1.0, 1.5)),
    ('lentil', (130.0, 9.0, 22.0, 0.5, 1.5)),
    ('brown rice', (216.0, 5.0, 44.8, 1.8, 0.7)),
    ('white rice', (205.0, 4.3, 44.5, 0.4, 0.1)),
    ('long grain rice', (205.0, 4.3, 44.5, 0.4, 0.1)),
    ('jasmine rice', (205.0, 4.3, 44.5, 0.4, 0.1)),
    ('basmati rice', (205.0, 4.3, 44.5, 0.4, 0.1)),
    ('rice', (205.0, 4.3, 44.5, 0.5, 0.1)),
    ('quinoa', (220.0, 8.0, 39.0, 3.5, 1.5)),
    ('sweet potato', (165.0, 3.5, 38.0, 0.3, 7.0)),
    ('potato', (160.0, 3.5, 36.0, 0.3, 1.5)),
    ('pasta', (210.0, 7.0, 42.0, 1.2, 1.5)),
    ('noodle', (210.0, 7.0, 42.0, 1.2, 1.5)),
    ('oatmeal', (160.0, 5.5, 28.0, 3.0, 1.0)),
    ('oat', (160.0, 5.5, 28.0, 3.0, 1.0)),
    ('tortilla', (140.0, 4.0, 24.0, 3.0, 1.0)),
    ('bread', (140.0, 5.0, 26.0, 2.0, 3.0)),
    ('roll', (140.0, 4.5, 26.0, 2.0, 3.0)),

    # 6. Vegetables and whole fruits
    ('spinach', (15.0, 1.7, 2.2, 0.2, 0.3)),
    ('leafy greens', (15.0, 1.5, 2.5, 0.2, 0.4)),
    ('greens', (15.0, 1.5, 2.5, 0.2, 0.4)),
    ('broccoli', (45.0, 3.0, 8.0, 0.5, 2.0)),
    ('asparagus', (40.0, 3.5, 6.0, 0.4, 2.0)),
    ('green bean', (45.0, 2.0, 9.0, 0.3, 3.0)),
    ('vegetable', (50.0, 2.0, 9.0, 1.0, 3.0)),
    ('applesauce', (80.0, 0.3, 21.0, 0.2, 17.0)),
    ('watermelon', (65.0, 1.0, 16.0, 0.2, 13.0)),
    ('cantaloupe', (60.0, 1.2, 15.0, 0.3, 13.0)),
    ('honeydew', (64.0, 1.0, 16.0, 0.2, 14.0)),
    ('pineapple', (80.0, 0.8, 21.0, 0.2, 16.0)),
    ('mandarin', (60.0, 1.0, 15.0, 0.2, 11.0)),
    ('orange', (65.0, 1.2, 16.0, 0.2, 12.0)),
    ('banana', (105.0, 1.3, 27.0, 0.4, 14.0)),
    ('apple', (80.0, 0.4, 21.0, 0.3, 16.0)),
    ('berries', (65.0, 1.0, 15.0, 0.4, 10.0)),
    ('strawberry', (55.0, 1.0, 13.0, 0.4, 8.0)),
    ('blueberry', (80.0, 1.0, 20.0, 0.4, 14.0)),
    ('grapes', (90.0, 0.9, 23.0, 0.2, 20.0)),
    ('fruit', (75.0, 0.8, 19.0, 0.2, 14.0)),
]

# Ingredient filter lists for the 3-tier Health Intensity engine
SEED_OILS = [
    'canola', 'soybean', 'corn oil', 'cottonseed', 'sunflower',
    'safflower', 'vegetable oil', 'margarine', 'shortening', 'hydrogenated'
]
HIGH_SUGAR_ADDITIVES = [
    'high fructose corn syrup', 'corn syrup', 'cane sugar', 'brown sugar',
    'dextrose', 'maltodextrin', 'invert sugar', 'icing', 'frosting', 'glaze'
]
DEEP_FRIED_MARKERS = [
    'deep fried', 'breaded', 'battered', 'tempura', 'crispy fried',
    'panko', 'cornmeal crust', 'fried in'
]
ARTIFICIAL_ADDITIVES = [
    'red 40', 'yellow 5', 'yellow 6', 'blue 1', 'blue 2',
    'sodium nitrite', 'sodium benzoate', 'potassium sorbate', 'bht', 'bha', 'tbhq'
]
WHOLE_FRUIT_KEYWORDS = [
    'watermelon', 'mandarin', 'orange', 'apple', 'banana', 'berries',
    'strawberry', 'blueberry', 'grapes', 'pineapple', 'cantaloupe', 'honeydew',
    'fruit mix', 'fresh fruit'
]

# Non-entree categories excluded from main Protein / Carbohydrate roles
STATION_HEADER_NAMES = {
    'pasta bar', 'salad bar', 'deli bar', 'taco bar', 'nacho bar',
    'baked potato bar', 'omelet bar', 'waffle bar', 'cereal bar',
    'soup bar', 'toppings bar', 'condiment bar'
}
DESSERT_KEYWORDS = [
    'pie', 'cake', 'cookie', 'brownie', 'cobbler', 'pudding',
    'ice cream', 'donut', 'muffin', 'pastry', 'tart', 'cupcake', 'gelato'
]
DIP_SAUCE_KEYWORDS = [
    'dip', 'queso', 'salsa', 'gravy', 'dressing', 'mayonnaise', 'aioli'
]

# Single-ingredient whole foods permitted in 'High' mode even when API Ingredients == 'N/A'
VERIFIED_NA_WHOLE_FOODS = [
    'plain white rice', 'long grain rice', 'jasmine rice', 'basmati rice',
    'plain brown rice', 'brown rice', 'steamed rice', 'steamed white rice',
    'steamed brown rice', 'baked potato', 'plain potato', 'baked sweet potato',
    'sweet potato', 'hard-boiled egg', 'hard boiled egg', 'hard-boiled eggs',
    'steamed broccoli', 'steamed vegetables', 'fresh spinach', 'leafy greens',
    'garbanzo beans', 'chickpeas', 'black beans', 'kidney beans',
    'extra virgin olive oil', 'olive oil', 'plain grilled chicken breast',
    'grilled chicken breast'
]


# ==============================================================================
# MODULE 1: API FETCHING, NORMALIZATION, CACHING & EXTERNAL MENU HOOK
# ==============================================================================

def _parse_numeric_value(raw_val) -> float:
    """Safely extracts a float from API nutrient values (e.g., 14, '14.5', '12g', None)."""
    if raw_val is None:
        return 0.0
    if isinstance(raw_val, (int, float)):
        return float(raw_val)
    match = re.search(r'[-+]?\d*\.?\d+', str(raw_val))
    return float(match.group()) if match else 0.0


def _match_fallback_macro(item_name: str) -> Optional[dict]:
    """Matches an item name against the hardcoded USDA whole-food fallback dictionary."""
    lower_name = item_name.lower().strip()
    if lower_name in FALLBACK_MACROS:
        return FALLBACK_MACROS[lower_name]
    for key, macros in FALLBACK_MACROS.items():
        if key in lower_name:
            return macros
    return None


def _unpack_composite_items(base_item: dict) -> list[dict]:
    """
    Unpacks nested/composite stations (such as 'Salad Bar') into individual
    selectable whole-food toppings so staples like Hard-Boiled Eggs, Garbanzo Beans,
    Fresh Spinach, and Extra Virgin Olive Oil can be combined independently.
    """
    station_lower = base_item['station'].lower()
    name_lower = base_item['name'].lower().strip()
    ingredients_lower = (base_item['ingredients'] or '').lower().strip()

    is_composite = any(
        kw in station_lower or kw in name_lower
        for kw in ['salad bar', 'build your own', 'toppings', 'condiments']
    )

    if not is_composite:
        return [base_item]

    direct_match = _match_fallback_macro(base_item['name'])
    if direct_match:
        item_copy = dict(base_item)
        if item_copy['calories'] == 0.0 and item_copy['protein'] == 0.0:
            item_copy.update({
                'calories': direct_match['calories'],
                'protein': direct_match['protein'],
                'carbs': direct_match['carbs'],
                'fat': direct_match['fat'],
                'sugar': direct_match['sugar'],
                'used_fallback': True,
            })
        return [item_copy]

    staple_aliases = [
        ('Fresh Spinach', 'fresh spinach'),
        ('Hard-Boiled Eggs', 'hard-boiled eggs'),
        ('Garbanzo Beans', 'garbanzo beans'),
        ('Extra Virgin Olive Oil', 'extra virgin olive oil'),
        ('Plain Grilled Chicken Breast', 'plain grilled chicken breast'),
        ('Plain Brown Rice', 'plain brown rice'),
    ]

    unpacked = []
    # If the API lists ingredients for the bar, unpack matching staples;
    # if the station/item is 'Salad Bar' with N/A ingredients, expose core whole-food staples.
    expose_default_bar = (
        ingredients_lower in ('', 'n/a')
        and ('salad bar' in name_lower or 'salad bar' in station_lower)
    )

    for display_name, fallback_key in staple_aliases:
        matched_in_ing = (
            fallback_key in ingredients_lower or display_name.lower() in ingredients_lower
        )
        default_staple = expose_default_bar and fallback_key in {
            'fresh spinach', 'hard-boiled eggs', 'garbanzo beans', 'extra virgin olive oil'
        }
        if matched_in_ing or default_staple:
            macros = FALLBACK_MACROS[fallback_key]
            sub_item = dict(base_item)
            sub_item.update({
                'name': f"{display_name} ({base_item['name']})",
                'calories': macros['calories'],
                'protein': macros['protein'],
                'carbs': macros['carbs'],
                'fat': macros['fat'],
                'sugar': macros['sugar'],
                'ingredients': macros['ingredients'],
                'used_fallback': True,
            })
            unpacked.append(sub_item)

    return unpacked if unpacked else [base_item]


def hydrate_missing_macros(items: list[dict]) -> list[dict]:
    """
    Fills in ordered USDA macro estimates when Purdue's API returns an empty
    Nutrients array (calories == 0 and protein == 0). Specific composite terms
    are evaluated before single-ingredient keywords.
    """
    hydrated = []
    for item in items:
        copy_item = dict(item)
        if copy_item['calories'] == 0.0 and copy_item['protein'] == 0.0:
            name_lower = copy_item['name'].lower().strip()
            if name_lower not in STATION_HEADER_NAMES:
                for kw, (cal, pro, carb, fat, sug) in ORDERED_KEYWORD_MACROS:
                    if kw in name_lower:
                        copy_item['calories'] = cal
                        copy_item['protein'] = pro
                        copy_item['carbs'] = carb
                        copy_item['fat'] = fat
                        copy_item['sugar'] = sug
                        copy_item['used_fallback'] = True
                        break
        hydrated.append(copy_item)
    return hydrated


_thread_local = threading.local()


def _get_thread_session() -> rq.Session:
    """Returns a thread-local requests.Session for HTTP keep-alive connection pooling."""
    if not hasattr(_thread_local, 'session'):
        session = rq.Session()
        session.headers.update({'Accept': 'application/json'})
        _thread_local.session = session
    return _thread_local.session


def _fetch_single_item_detail(item_id: str) -> tuple[str, Optional[dict]]:
    """Worker function that fetches a single item's detail JSON concurrently."""
    detail_url = f'https://api.hfs.purdue.edu/menus/v2/items/{item_id}'
    session = _get_thread_session()
    try:
        res = session.get(detail_url, timeout=10)
        if res.status_code == 200:
            return item_id, res.json()
    except (rq.exceptions.RequestException, ValueError):
        pass
    return item_id, None


def fetch_detailed_purdue_menu(location: str, target_date: Optional[str] = None) -> list[dict]:
    """
    Queries Purdue HFS v2 API for a single location and fetches all unique item
    details concurrently via ThreadPoolExecutor (~2s cold start).
    """
    date_str = target_date or datetime.now().strftime('%Y-%m-%d')
    url = f'https://api.hfs.purdue.edu/menus/v2/locations/{location}/{date_str}'
    session = _get_thread_session()

    try:
        response = session.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()
    except (rq.exceptions.RequestException, ValueError):
        return []

    if 'Meals' not in data or not data['Meals']:
        return []

    # 1. Collect all unique item IDs across meals and stations at this location
    unique_item_ids = set()
    for meal in data['Meals']:
        for station in meal.get('Stations', []):
            for item in station.get('Items', []):
                item_id = item.get('ID')
                if item_id:
                    unique_item_ids.add(item_id)

    # 2. Fetch all unique item detail payloads concurrently
    details_by_id: dict[str, dict] = {}
    if unique_item_ids:
        with ThreadPoolExecutor(max_workers=12) as executor:
            futures = [
                executor.submit(_fetch_single_item_detail, iid)
                for iid in unique_item_ids
            ]
            for future in as_completed(futures):
                iid, detail_data = future.result()
                if detail_data is not None:
                    details_by_id[iid] = detail_data

    # 3. Normalize items using the pre-fetched detail dictionary
    normalized_items = []

    for meal in data['Meals']:
        meal_period = meal.get('Name', 'Unknown')
        hours_obj = meal.get('Hours') or {}
        start_time = hours_obj.get('StartTime', '')
        end_time = hours_obj.get('EndTime', '')

        for station in meal.get('Stations', []):
            station_name = station.get('Name', 'Unknown')

            for item in station.get('Items', []):
                item_name = item.get('Name', 'Unknown')
                item_id = item.get('ID')

                calories = protein = carbs = fat = sugar = 0.0
                serving_size = 'N/A'
                ingredients = 'N/A'
                has_api_nutrients = False

                detail_data = details_by_id.get(item_id) if item_id else None
                if detail_data:
                    serving_size = (detail_data.get('ServingSize') or '').strip() or 'N/A'
                    ingredients = (detail_data.get('Ingredients') or '').strip() or 'N/A'

                    nutrients = detail_data.get('Nutrients') or []
                    if nutrients:
                        has_api_nutrients = True
                    for n in nutrients:
                        n_name = (n.get('Name') or '').lower()
                        n_val = _parse_numeric_value(n.get('Value'))
                        if 'calorie' in n_name:
                            calories = n_val
                        elif 'protein' in n_name:
                            protein = n_val
                        elif 'carbohydrate' in n_name:
                            carbs = n_val
                        elif n_name in ('total fat', 'fat'):
                            fat = n_val
                        elif 'sugar' in n_name:
                            sugar = max(sugar, n_val)

                used_fallback = False
                if not has_api_nutrients or str(serving_size).strip().upper() == 'N/A':
                    fallback = _match_fallback_macro(item_name)
                    if fallback:
                        calories = fallback['calories']
                        protein = fallback['protein']
                        carbs = fallback['carbs']
                        fat = fallback['fat']
                        sugar = fallback['sugar']
                        if ingredients == 'N/A':
                            ingredients = fallback['ingredients']
                        used_fallback = True

                base_record = {
                    'location': location,
                    'meal_period': meal_period,
                    'hours_status': 'Unknown',
                    'closing_time': '',
                    'start_time': start_time,
                    'end_time': end_time,
                    'station': station_name,
                    'name': item_name,
                    'calories': round(calories, 1),
                    'protein': round(protein, 1),
                    'carbs': round(carbs, 1),
                    'fat': round(fat, 1),
                    'sugar': round(sugar, 1),
                    'ingredients': ingredients,
                    'used_fallback': used_fallback,
                }

                normalized_items.extend(_unpack_composite_items(base_record))

    return hydrate_missing_macros(normalized_items)


def merge_external_menus(
    menu_items: list[dict], static_menu_path: Optional[str] = None
) -> list[dict]:
    """
    Hook to merge off-API venues (such as PMU restaurants) or custom static JSON
    menus into the standardized menu item list.
    """
    if not static_menu_path or not os.path.exists(static_menu_path):
        return menu_items

    try:
        with open(static_menu_path, 'r', encoding='utf-8') as f:
            external_data = json.load(f)
    except (OSError, ValueError):
        return menu_items

    required_keys = {
        'location', 'meal_period', 'hours_status', 'closing_time',
        'station', 'name', 'calories', 'protein', 'carbs', 'fat',
        'sugar', 'ingredients', 'used_fallback'
    }

    for entry in external_data:
        normalized = {
            'location': entry.get('location', 'PMU'),
            'meal_period': entry.get('meal_period', 'All Day'),
            'hours_status': entry.get('hours_status', 'Unknown'),
            'closing_time': entry.get('closing_time', ''),
            'start_time': entry.get('start_time', '08:00:00'),
            'end_time': entry.get('end_time', '21:00:00'),
            'station': entry.get('station', 'Main Counter'),
            'name': entry.get('name', 'Unknown Item'),
            'calories': float(entry.get('calories', 0.0)),
            'protein': float(entry.get('protein', 0.0)),
            'carbs': float(entry.get('carbs', 0.0)),
            'fat': float(entry.get('fat', 0.0)),
            'sugar': float(entry.get('sugar', 0.0)),
            'ingredients': entry.get('ingredients', 'N/A'),
            'used_fallback': bool(entry.get('used_fallback', False)),
        }
        if required_keys.issubset(normalized.keys()):
            menu_items.append(normalized)

    return menu_items


def get_daily_menus(
    locations: Optional[list[str]] = None,
    include_quick_bites: bool = False,
    static_menu_path: Optional[str] = None,
    force_refresh: bool = False,
) -> tuple[list[dict], bool]:
    """
    Loads today's compiled menu items from local JSON cache if available and non-empty;
    otherwise fetches live data from Purdue's API concurrently and writes the cache file.
    Returns (items, loaded_from_cache).
    """
    today_str = datetime.now().strftime('%Y-%m-%d')
    cache_path = os.path.join(BASE_DIR, f'purdue_menu_cache_{today_str}.json')

    if not force_refresh and os.path.exists(cache_path):
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                cached_items = json.load(f)
            if cached_items:
                cached_items = merge_external_menus(cached_items, static_menu_path)
                return hydrate_missing_macros(cached_items), True
        except (OSError, ValueError):
            pass

    target_locations = list(locations or DEFAULT_DINING_COURTS)
    if include_quick_bites:
        for qb in QUICK_BITES_LOCATIONS:
            if qb not in target_locations:
                target_locations.append(qb)

    all_items = []
    with ThreadPoolExecutor(max_workers=len(target_locations) or 1) as executor:
        location_futures = [
            executor.submit(fetch_detailed_purdue_menu, loc, today_str)
            for loc in target_locations
        ]
        for future in as_completed(location_futures):
            all_items.extend(future.result())

    try:
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(all_items, f, indent=2)
    except OSError:
        pass

    all_items = merge_external_menus(all_items, static_menu_path)
    return hydrate_missing_macros(all_items), False

# ==============================================================================
# MODULE 2: CALIBRATED USDA DRI & SINGLE-MEAL MACRO CALCULATOR
# ==============================================================================

def calculate_meal_targets(
    sex: str,
    age: int,
    weight_lbs: float,
    height_in: float,
    activity_level: str,
    meals_per_day: int,
    meal_goal: str = 'Balanced',
    health_intensity: str = 'High',
) -> dict:
    """
    Computes daily Calories via Mifflin-St Jeor with calibrated campus activity
    multipliers, anchors Protein to USDA DRI body-weight guidelines (g/kg),
    uses the 130g/day USDA RDA floor for Carbohydrates, and applies AHA added-sugar caps.
    """
    weight_kg = weight_lbs * 0.45359237
    height_cm = height_in * 2.54

    sex_norm = sex.strip().upper()
    if sex_norm.startswith('M'):
        bmr = (10.0 * weight_kg) + (6.25 * height_cm) - (5.0 * age) + 5.0
        daily_aha_sugar_cap = 36.0
    else:
        bmr = (10.0 * weight_kg) + (6.25 * height_cm) - (5.0 * age) - 161.0
        daily_aha_sugar_cap = 25.0

    activity_multipliers = {
        'sedentary': 1.2,
        'moderate': 1.375,
        'active': 1.55,
    }
    multiplier = activity_multipliers.get(activity_level.strip().lower(), 1.375)
    daily_calories = bmr * multiplier

    goal_norm = meal_goal.strip().lower()
    if 'high protein' in goal_norm:
        daily_protein_min = weight_kg * 1.2
        daily_protein_target = weight_kg * 1.5
        daily_protein_max = weight_kg * 1.8
        carb_share = 0.35
        fat_share = 0.25
    else:
        # USDA DRI baseline (RDA = 0.8 g/kg; balanced target = 1.1 g/kg)
        daily_protein_min = weight_kg * 0.8
        daily_protein_target = weight_kg * 1.1
        daily_protein_max = weight_kg * 1.4
        carb_share = 0.38
        fat_share = 0.25

    # USDA RDA minimum for carbs is 130g/day up to 50% of daily calories
    daily_carbs_min = 130.0
    daily_carbs_target = max((daily_calories * carb_share) / 4.0, 140.0)
    daily_carbs_max = (daily_calories * 0.50) / 4.0

    # Healthy fat range (20% - 32% of daily calories)
    daily_fat_min = (daily_calories * 0.20) / 9.0
    daily_fat_target = (daily_calories * fat_share) / 9.0
    daily_fat_max = (daily_calories * 0.32) / 9.0

    # AHA added-sugar cap tightened to 20g/day when High health intensity is selected
    if health_intensity.strip().lower() == 'high':
        daily_sugar_max = min(daily_aha_sugar_cap, 20.0)
    else:
        daily_sugar_max = daily_aha_sugar_cap

    meals = max(1, int(meals_per_day))

    return {
        'daily': {
            'calories': round(daily_calories, 1),
            'protein_target': round(daily_protein_target, 1),
            'carbs_target': round(daily_carbs_target, 1),
            'fat_target': round(daily_fat_target, 1),
            'sugar_max': round(daily_sugar_max, 1),
        },
        'per_meal': {
            'calories': round(daily_calories / meals, 1),
            'protein_min': round(daily_protein_min / meals, 1),
            'protein_target': round(daily_protein_target / meals, 1),
            'protein_max': round(daily_protein_max / meals, 1),
            'carbs_min': round(daily_carbs_min / meals, 1),
            'carbs_target': round(daily_carbs_target / meals, 1),
            'carbs_max': round(daily_carbs_max / meals, 1),
            'fat_min': round(daily_fat_min / meals, 1),
            'fat_target': round(daily_fat_target / meals, 1),
            'fat_max': round(daily_fat_max / meals, 1),
            'sugar_max': round(daily_sugar_max / meals, 1),
        },
    }


# ==============================================================================
# MODULE 3: RESILIENT REAL-TIME OPERATING HOURS FILTER
# ==============================================================================

def _parse_api_time(time_str: str, base_date) -> Optional[datetime]:
    """
    Extracts HH:MM(:SS) from Purdue HFS timestamps after stripping any ISO 'T'
    date prefix, fractional seconds, or timezone offset.
    """
    if not time_str:
        return None
    clean = str(time_str).strip()

    # Handle 12-hour strings like '12:30 PM'
    for fmt in ('%I:%M %p', '%I:%M:%S %p'):
        try:
            parsed_t = datetime.strptime(clean, fmt).time()
            return datetime.combine(base_date, parsed_t)
        except ValueError:
            continue

    # Strip ISO date prefix ('YYYY-MM-DDT') and match HH:MM(:SS) before fractional/TZ suffix
    after_t = clean.split('T')[-1]
    match = re.search(r'(\d{1,2}:\d{2}(?::\d{2})?)', after_t)
    if match:
        time_part = match.group(1)
        fmt = '%H:%M:%S' if time_part.count(':') == 2 else '%H:%M'
        try:
            parsed_t = datetime.strptime(time_part, fmt).time()
            return datetime.combine(base_date, parsed_t)
        except ValueError:
            return None
    return None


def _format_display_time(dt_obj: datetime) -> str:
    """Formats a datetime into '2:00 pm' style matching the Purdue Dining portal."""
    return dt_obj.strftime('%I:%M %p').lstrip('0').lower()


def filter_open_locations(
    items: list[dict], current_time: Optional[datetime] = None
) -> list[dict]:
    """
    Filters items to dining locations currently open or opening within 30 minutes.
    If run between meal periods, automatically falls back to the next upcoming meal today.
    """
    now = current_time or datetime.now()
    today = now.date()
    open_items = []
    upcoming_items = []

    for item in items:
        meal_period = item.get('meal_period', 'Meal')
        raw_start = item.get('start_time', '')
        raw_end = item.get('end_time', '')

        if not raw_start or not raw_end:
            fallback_win = DEFAULT_MEAL_WINDOWS.get(meal_period.strip().lower())
            if fallback_win:
                raw_start, raw_end = fallback_win

        start_dt = _parse_api_time(raw_start, today)
        end_dt = _parse_api_time(raw_end, today)

        if not start_dt or not end_dt:
            continue

        if end_dt <= start_dt:
            end_dt += timedelta(days=1)

        formatted_start = _format_display_time(start_dt)
        formatted_end = _format_display_time(end_dt)

        if start_dt <= now < end_dt:
            updated = dict(item)
            updated['hours_status'] = f'Serving {meal_period} until {formatted_end}'
            updated['closing_time'] = formatted_end
            open_items.append(updated)
        elif start_dt > now:
            seconds_until_open = (start_dt - now).total_seconds()
            updated = dict(item)
            updated['closing_time'] = formatted_end
            if seconds_until_open <= 1800:
                updated['hours_status'] = f'Opening Soon at {formatted_start}'
                open_items.append(updated)
            else:
                updated['hours_status'] = f'Next Meal: {meal_period} ({formatted_start} - {formatted_end})'
                upcoming_items.append((start_dt, updated))

    if open_items:
        return open_items

    if upcoming_items:
        earliest_start = min(dt for dt, _ in upcoming_items)
        return [it for dt, it in upcoming_items if dt == earliest_start]

    return []


# ==============================================================================
# MODULE 4: STRICT THREE-TIER HEALTH SCORING & 'INGREDIENTS: N/A' GUARDRAIL
# ==============================================================================

def _is_whole_fruit(name_lower: str) -> bool:
    """True if item is a whole/fresh fruit and not a pie, cobbler, or sugary pastry."""
    if any(d in name_lower for d in DESSERT_KEYWORDS + ['sauce', 'syrup', 'juice']):
        return False
    return any(fr in name_lower for fr in WHOLE_FRUIT_KEYWORDS)


def _is_verified_na_whole_food(item: dict) -> bool:
    """
    Returns True only if an item with 'Ingredients: N/A' is an unpacked Salad Bar
    staple or a verified single-ingredient whole food (plain rice, plain potatoes,
    hard-boiled eggs, whole fruit, steamed vegetables, or plain grilled chicken breast).
    """
    name_lower = item['name'].lower().strip()
    station_lower = item['station'].lower().strip()

    # Unpacked Salad Bar whole-food staples
    if 'salad bar' in station_lower or '(salad bar)' in name_lower:
        if any(
            st in name_lower
            for st in ['spinach', 'greens', 'hard-boiled egg', 'garbanzo', 'chickpea', 'olive oil', 'grilled chicken', 'brown rice']
        ):
            return True

    if _is_whole_fruit(name_lower):
        return True

    # Reject composite/saucy/pre-mixed items even if they contain a whole-food word
    unverified_risk_words = [
        'salad', 'bowl', 'stir fry', 'moo shu', 'teriyaki', 'sauce', 'glaze',
        'fried', 'crispy', 'breaded', 'dip', 'queso', 'cheese', 'creamy', 'casserole'
    ]
    if any(risk in name_lower for risk in unverified_risk_words):
        return False

    return any(vf in name_lower for vf in VERIFIED_NA_WHOLE_FOODS)


def evaluate_item_health(item: dict, health_intensity: str) -> tuple[bool, float, str]:
    """
    Evaluates an item against the selected Health Intensity ('High', 'Mid', 'Low').
    Enforces the strict 'Ingredients: N/A' guardrail in 'High' mode and filters
    out non-food station headers.
    """
    tier = health_intensity.strip().lower()
    name_lower = item['name'].lower().strip()
    ing_raw = (item['ingredients'] or '').strip()
    ing_lower = ing_raw.lower()
    combined_text = f'{name_lower} {ing_lower}'

    # Always exclude non-food station headers (e.g., 'Pasta Bar', 'Salad Bar')
    if name_lower in STATION_HEADER_NAMES:
        return False, -100.0, 'Excluded: station header rather than food item'

    # Exclude negligible zero-calorie condiments/beverages
    zero_cal_items = ('water', 'ice', 'salt', 'black pepper', 'tea', 'black coffee', 'mustard', 'vinegar')
    if any(z == name_lower or f' {z}' in name_lower for z in zero_cal_items):
        return False, 0.0, 'Negligible macro contribution'

    has_seed_oil = any(oil in combined_text for oil in SEED_OILS)
    has_high_sugar = any(s in combined_text for s in HIGH_SUGAR_ADDITIVES)
    is_deep_fried = any(f in combined_text for f in DEEP_FRIED_MARKERS)
    has_artificial = any(a in combined_text for a in ARTIFICIAL_ADDITIVES)
    is_dessert = any(d in name_lower for d in DESSERT_KEYWORDS)
    is_dip_or_sauce = any(ds in name_lower for ds in DIP_SAUCE_KEYWORDS)
    whole_fruit = _is_whole_fruit(name_lower)

    if tier == 'high':
        # Crucial guardrail: reject unverified N/A items in High mode
        if ing_raw.upper() == 'N/A' and not _is_verified_na_whole_food(item):
            return False, -100.0, 'Excluded from High mode: unverified ingredients (N/A) — routed to Mid'

        if has_seed_oil:
            return False, -100.0, 'Excluded: contains industrial seed oils'
        if is_deep_fried:
            return False, -100.0, 'Excluded: deep-fried or battered'
        if has_artificial:
            return False, -100.0, 'Excluded: artificial dyes or preservatives'
        if is_dessert or is_dip_or_sauce:
            return False, -100.0, 'Excluded: dessert, dip, or heavy sauce'
        if has_high_sugar or (item['sugar'] > 10.0 and not whole_fruit):
            return False, -100.0, 'Excluded: high added/refined sugar'

        bonus = 15.0
        if 'salad bar' in item['station'].lower() or '(salad bar)' in name_lower:
            bonus += 10.0
        if 'olive oil' in combined_text or 'butter' in combined_text:
            bonus += 5.0
        return True, bonus, 'Verified whole-food ingredient profile with zero seed oils'

    elif tier == 'mid':
        if is_deep_fried:
            return False, -100.0, 'Excluded: deep-fried or heavily battered'
        if has_artificial:
            return False, -100.0, 'Excluded: artificial dyes or preservatives'
        if is_dessert:
            return False, -100.0, 'Excluded: dessert item'
        if (has_high_sugar and item['protein'] < 10.0) or (item['sugar'] > 18.0 and not whole_fruit):
            return False, -100.0, 'Excluded: sugary glaze or high-sugar item'

        bonus = 10.0 if (not has_seed_oil and ing_raw.upper() != 'N/A') else 3.0
        reason = (
            'Whole-food protein/base without seed oils'
            if (not has_seed_oil and ing_raw.upper() != 'N/A')
            else 'Allowed protein/entree in Mid mode to meet protein target'
        )
        return True, bonus, reason

    else:  # 'low'
        bonus = min(item['protein'] * 0.5, 20.0)
        return True, bonus, 'Selected for maximum protein yield and flavor'


def _classify_item_role(item: dict) -> str:
    """
    Categorizes a menu item into 'protein', 'carb', or 'side', blocking
    station headers, dips/sauces, and desserts from primary entree roles.
    """
    name_lower = item['name'].lower().strip()

    if (
        name_lower in STATION_HEADER_NAMES
        or any(d in name_lower for d in DESSERT_KEYWORDS)
        or any(ds in name_lower for ds in DIP_SAUCE_KEYWORDS)
    ):
        return 'side'

    if 'olive oil' in name_lower or 'spinach' in name_lower or 'greens' in name_lower:
        return 'side'

    if _is_whole_fruit(name_lower):
        return 'side'

    if item['protein'] >= 12.0 and item['protein'] >= item['carbs'] * 0.6:
        return 'protein'

    if item['carbs'] >= 15.0 and item['carbs'] > item['protein']:
        return 'carb'

    return 'side'


def _range_error(val: float, low: float, high: float) -> float:
    """Returns 0.0 when val is inside [low, high], or normalized distance outside."""
    if val < low:
        return (low - val) / max(low, 1.0)
    if val > high:
        return (val - high) / max(high, 1.0)
    return 0.0


# ==============================================================================
# MODULE 5: SMART MULTI-ITEM PLATE BUILDER & DUAL-LOCATION RANKER
# ==============================================================================

def build_optimal_plates(
    open_items: list[dict],
    meal_targets: dict,
    meal_goal: str,
    health_intensity: str,
    top_n: int = 2,
) -> list[dict]:
    """
    Builds and scores optimal multi-item plates for each open dining court:
    - Applies zero penalty for carbs/fats inside the healthy [min, max] range.
    - Only doubles primary protein when single serving < protein_min AND doubling
      brings the plate closer to protein_target than a single portion.
    - Scales up with a second distinct carb or healthy-fat booster when
      per_meal['calories'] >= 1000 (e.g., 2-meal/day schedules) without duplicating fruit.
    """
    per_meal = meal_targets['per_meal']
    goal_norm = meal_goal.strip().lower()
    is_high_protein = 'high protein' in goal_norm
    high_calorie_meal = per_meal['calories'] >= 1000.0

    by_location: dict[str, list[dict]] = {}
    for item in open_items:
        allowed, health_bonus, reason = evaluate_item_health(item, health_intensity)
        if not allowed:
            continue
        enriched = dict(item)
        enriched['_health_bonus'] = health_bonus
        enriched['_health_reason'] = reason
        enriched['_role'] = _classify_item_role(enriched)
        enriched['_is_fruit'] = _is_whole_fruit(enriched['name'].lower())
        by_location.setdefault(item['location'], []).append(enriched)

    location_results = []

    for location, items in by_location.items():
        unique_items = {}
        for it in items:
            if it['name'] not in unique_items:
                unique_items[it['name']] = it
        pool = list(unique_items.values())

        proteins = sorted(
            [i for i in pool if i['_role'] == 'protein'],
            key=lambda x: x['protein'],
            reverse=True,
        )[:8]
        carbs = sorted(
            [i for i in pool if i['_role'] == 'carb'],
            key=lambda x: x['carbs'],
            reverse=True,
        )[:6]
        sides = sorted(
            [i for i in pool if i['_role'] == 'side'],
            key=lambda x: x['_health_bonus'] + x['calories'] * 0.05 + x['protein'],
            reverse=True,
        )[:6]

        if not proteins:
            continue

        # Smart protein doubling: only double when single serving < protein_min
        # AND doubling is strictly closer to protein_target than a single serving
        protein_combos = []
        for p in proteins:
            protein_combos.append([p])
            single_pro = p['protein']
            double_pro = single_pro * 2.0
            if (
                single_pro < per_meal['protein_min']
                and abs(double_pro - per_meal['protein_target']) < abs(single_pro - per_meal['protein_target'])
            ):
                protein_combos.append([p, p])

        carb_choices = carbs if carbs else [None]
        side_choices = sides if sides else [None]

        # Optional 4th slot booster for >=1000 kcal per-meal targets (2 meals/day)
        booster_pool = [None]
        if high_calorie_meal:
            booster_pool.extend(carbs[:4] + sides[:4])

        best_plate_score = -1e9
        best_plate_data = None

        for p_list, c_item, s_item, b_item in product(
            protein_combos, carb_choices, side_choices, booster_pool
        ):
            # Ensure booster item is distinct and never duplicates fruit
            if b_item is not None:
                used_names = {p_list[0]['name']}
                if c_item:
                    used_names.add(c_item['name'])
                if s_item:
                    used_names.add(s_item['name'])
                if b_item['name'] in used_names:
                    continue
                if s_item and s_item['_is_fruit'] and b_item['_is_fruit']:
                    continue

            plate_items = list(p_list)
            if c_item:
                plate_items.append(c_item)
            if s_item:
                plate_items.append(s_item)
            if b_item:
                plate_items.append(b_item)

            tot_cal = sum(i['calories'] for i in plate_items)
            tot_pro = sum(i['protein'] for i in plate_items)
            tot_carb = sum(i['carbs'] for i in plate_items)
            tot_fat = sum(i['fat'] for i in plate_items)
            tot_sugar = sum(i['sugar'] for i in plate_items)
            health_score = sum(i['_health_bonus'] for i in plate_items) / len(plate_items)

            cal_err = abs(tot_cal - per_meal['calories']) / max(per_meal['calories'], 1.0)
            pro_err = abs(tot_pro - per_meal['protein_target']) / max(per_meal['protein_target'], 1.0)
            carb_err = _range_error(tot_carb, per_meal['carbs_min'], per_meal['carbs_max'])
            fat_err = _range_error(tot_fat, per_meal['fat_min'], per_meal['fat_max'])

            pro_shortfall_penalty = 0.0
            if tot_pro < per_meal['protein_min']:
                pro_shortfall_penalty = (
                    (per_meal['protein_min'] - tot_pro) / max(per_meal['protein_min'], 1.0)
                ) * 40.0

            if is_high_protein:
                macro_penalty = (pro_err * 42.0) + (cal_err * 22.0) + (carb_err * 10.0) + (fat_err * 10.0)
            else:
                macro_penalty = (cal_err * 24.0) + (pro_err * 28.0) + (carb_err * 15.0) + (fat_err * 15.0)

            total_score = 100.0 + health_score - macro_penalty - pro_shortfall_penalty

            if total_score > best_plate_score:
                best_plate_score = total_score
                formatted_items = []
                for idx, it in enumerate(plate_items):
                    if idx < len(p_list):
                        role_label = 'Protein'
                    elif it is c_item:
                        role_label = 'Carbohydrate'
                    elif it is s_item:
                        role_label = 'Side / Micronutrient'
                    else:
                        role_label = 'Calorie / Macro Booster'

                    formatted_items.append({
                        'role': role_label,
                        'station': it['station'],
                        'name': it['name'],
                        'calories': it['calories'],
                        'protein': it['protein'],
                        'carbs': it['carbs'],
                        'fat': it['fat'],
                        'used_fallback': it['used_fallback'],
                        'reason': it['_health_reason'],
                    })

                best_plate_data = {
                    'location': location,
                    'hours_status': plate_items[0]['hours_status'],
                    'closing_time': plate_items[0]['closing_time'],
                    'score': round(total_score, 1),
                    'items': formatted_items,
                    'totals': {
                        'calories': round(tot_cal, 1),
                        'protein': round(tot_pro, 1),
                        'carbs': round(tot_carb, 1),
                        'fat': round(tot_fat, 1),
                        'sugar': round(tot_sugar, 1),
                    },
                    'filter_summary': (
                        f"Matched '{health_intensity.title()}' health filter: "
                        + '; '.join(dict.fromkeys(i['_health_reason'] for i in plate_items))
                    ),
                }

        if best_plate_data:
            location_results.append(best_plate_data)

    location_results.sort(key=lambda r: r['score'], reverse=True)
    return location_results[:top_n]


def recommend_meals(
    sex: str,
    age: int,
    weight_lbs: float,
    height_in: float,
    activity_level: str,
    meals_per_day: int,
    meal_goal: str = 'High Protein',
    health_intensity: str = 'High',
    include_quick_bites: bool = False,
    static_menu_path: Optional[str] = None,
    current_time: Optional[datetime] = None,
) -> dict:
    """
    Top-level orchestrator function. Ready to be called directly by a CLI,
    Flask/FastAPI web backend, or scheduled worker.
    """
    targets = calculate_meal_targets(
        sex=sex,
        age=age,
        weight_lbs=weight_lbs,
        height_in=height_in,
        activity_level=activity_level,
        meals_per_day=meals_per_day,
        meal_goal=meal_goal,
        health_intensity=health_intensity,
    )

    all_items, from_cache = get_daily_menus(
        include_quick_bites=include_quick_bites,
        static_menu_path=static_menu_path,
    )

    open_items = filter_open_locations(all_items, current_time=current_time)

    recommendations = build_optimal_plates(
        open_items=open_items,
        meal_targets=targets,
        meal_goal=meal_goal,
        health_intensity=health_intensity,
        top_n=2,
    )

    return {
        'timestamp': (current_time or datetime.now()).strftime('%Y-%m-%d %I:%M %p'),
        'loaded_from_cache': from_cache,
        'targets': targets,
        'open_locations_count': len({i['location'] for i in open_items}),
        'recommendations': recommendations,
    }


# ==============================================================================
# TERMINAL INTERFACE (UI WRAPPER ONLY)
# ==============================================================================

def _parse_user_time_input(raw_input: str) -> Optional[datetime]:
    """Safely parses 'HH:MM' 24-hr or '12:30 PM' input; returns None on empty/invalid."""
    clean = raw_input.strip()
    if not clean:
        return None
    for fmt in ('%H:%M', '%I:%M %p', '%I:%M%p'):
        try:
            parsed_t = datetime.strptime(clean, fmt).time()
            return datetime.combine(datetime.now().date(), parsed_t)
        except ValueError:
            continue
    return None


def main():
    print('====================================================')
    print('       PURDUE DINING MEAL OPTIMIZATION ENGINE       ')
    print('====================================================\n')

    sex = input('Enter Sex (M/F) [M]: ').strip() or 'M'

    try:
        age = int(input('Enter Age (years) [18]: ').strip() or 18)
    except ValueError:
        age = 18

    try:
        weight_lbs = float(input('Enter Weight (lbs) [155]: ').strip() or 155)
    except ValueError:
        weight_lbs = 155.0

    try:
        height_in = float(input('Enter Height (inches) [72]: ').strip() or 72)
    except ValueError:
        height_in = 72.0

    activity_level = input('Activity Level (Sedentary / Moderate / Active) [Moderate]: ').strip() or 'Moderate'

    try:
        meals_per_day = int(input('How many meals do you eat per day? [2]: ').strip() or 2)
    except ValueError:
        meals_per_day = 2

    meal_goal = input('Meal Goal (High Protein / Balanced) [High Protein]: ').strip() or 'High Protein'
    health_intensity = input('Health Intensity (High / Mid / Low) [High]: ').strip() or 'High'
    sim_input = input('Time to check (e.g., 12:30 or 12:30 PM, or Enter for NOW): ').strip()

    sim_time = _parse_user_time_input(sim_input)
    if sim_input and sim_time is None:
        print('Invalid time format entered—using live current time (NOW).')

    print('\nLoading daily menus and checking live dining court hours...')
    result = recommend_meals(
        sex=sex,
        age=age,
        weight_lbs=weight_lbs,
        height_in=height_in,
        activity_level=activity_level,
        meals_per_day=meals_per_day,
        meal_goal=meal_goal,
        health_intensity=health_intensity,
        current_time=sim_time,
    )

    cache_msg = (
        "Loaded instantly from today's local JSON cache."
        if result['loaded_from_cache']
        else 'Fetched live from Purdue HFS API and cached.'
    )
    print(f'Status: {cache_msg}')

    per_meal = result['targets']['per_meal']
    print('\n--- YOUR PER-MEAL USDA DRI TARGETS ---')
    print(
        f"Calories: ~{per_meal['calories']} kcal | "
        f"Protein: {per_meal['protein_target']}g (min {per_meal['protein_min']}g) | "
        f"Carbs: {per_meal['carbs_min']}-{per_meal['carbs_max']}g | "
        f"Fat: {per_meal['fat_min']}-{per_meal['fat_max']}g | "
        f"Sugar Max: {per_meal['sugar_max']}g"
    )

    recs = result['recommendations']
    if not recs:
        print('\nNo dining courts currently match your selected meal window and health filters.')
        print('Tip: Try relaxing Health Intensity to Mid if API ingredient lists are N/A today.')
        return

    for rank, rec in enumerate(recs, start=1):
        label = '#1 BEST DINING COURT' if rank == 1 else '#2 RUNNER-UP DINING COURT'
        print(f'\n====================================================')
        print(f"{label}: {rec['location'].upper()} ({rec['hours_status']})")
        print(f'====================================================')

        for item in rec['items']:
            fb_tag = ' [USDA Fallback Estimate]' if item['used_fallback'] else ''
            print(
                f"  * [{item['role']}] {item['name']} ({item['station']}){fb_tag}\n"
                f"      -> {item['calories']} kcal | {item['protein']}g P | {item['carbs']}g C | {item['fat']}g F"
            )

        t = rec['totals']
        print('\n  Combined Plate Macros vs. Per-Meal DRI Target:')
        print(f"    Calories : {t['calories']} kcal  (Target: ~{per_meal['calories']} kcal)")
        print(f"    Protein  : {t['protein']} g     (Target: {per_meal['protein_target']} g)")
        print(f"    Carbs    : {t['carbs']} g     (Healthy Range: {per_meal['carbs_min']}-{per_meal['carbs_max']} g)")
        print(f"    Fat      : {t['fat']} g     (Healthy Range: {per_meal['fat_min']}-{per_meal['fat_max']} g)")
        print(f"\n  Why it matched: {rec['filter_summary']}")


if __name__ == '__main__':
    main()