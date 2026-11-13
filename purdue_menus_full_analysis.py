import os
import re
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import product
from typing import Optional
import requests as rq
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

PURDUE_TZ = ZoneInfo("America/Indiana/Indianapolis")


def get_purdue_now():
    return datetime.now(PURDUE_TZ)


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

# Stations and item markers requiring special orders, custom tickets, or made-to-order prep
SPECIAL_ORDER_STATION_MARKERS = [
    'by request',
    'upon request',
    'special order',
    'custom order',
    'made to order',
    'made-to-order',
    'omelet bar',
    'omelette bar',
    'stir fry bar',
    'stir-fry bar',
    'pasta bar',
]

SPECIAL_ORDER_ITEM_MARKERS = [
    'by request',
    'upon request',
    'made to order',
    'made-to-order',
    'custom omelet',
    'custom omelette',
    'custom stir fry',
    'custom stir-fry',
    'custom pasta',
    'special request',
]

# Non-meat keywords used for vegetarian fallback detection
MEAT_SEAFOOD_KEYWORDS = [
    'chicken', 'beef', 'pork', 'turkey', 'ham', 'bacon', 'sausage', 'steak',
    'lamb', 'veal', 'duck', 'venison', 'bison', 'meatball', 'pepperoni',
    'salami', 'prosciutto', 'chorizo', 'bratwurst', 'hot dog', 'gyro',
    'barbacoa', 'carnitas', 'brisket', 'rib', 'wings', 'drumstick',
    'salmon', 'tuna', 'cod', 'tilapia', 'shrimp', 'crab', 'lobster',
    'clam', 'mussel', 'oyster', 'scallop', 'anchovy', 'fish', 'seafood',
    'gelatin', 'lard', 'tallow', 'chicken broth', 'beef broth', 'fish sauce'
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


def _extract_allergens_and_diet(detail_data: Optional[dict]) -> tuple[list[str], Optional[bool]]:
    """
    Extracts normalized allergen names and vegetarian status from a Purdue HFS
    item detail payload.
    """
    if not detail_data:
        return [], None

    allergens: list[str] = []
    is_vegetarian: Optional[bool] = None

    raw_allergens = detail_data.get('Allergens') or []
    for entry in raw_allergens:
        if isinstance(entry, str):
            val = entry.strip().lower()
            if val:
                allergens.append(val)
        elif isinstance(entry, dict):
            name = str(entry.get('Name') or '').strip().lower()
            has_flag = entry.get('Value', True)
            if not name:
                continue
            if name == 'vegetarian':
                is_vegetarian = bool(has_flag)
            elif name == 'vegan' and has_flag:
                is_vegetarian = True
            elif has_flag:
                allergens.append(name)

    if is_vegetarian is None and 'IsVegetarian' in detail_data:
        is_vegetarian = bool(detail_data.get('IsVegetarian'))

    # Deduplicate while preserving order
    return list(dict.fromkeys(allergens)), is_vegetarian


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
    Unpacks self-serve composite stations (such as 'Salad Bar') into individual
    ready-to-grab whole-food staples so items like Hard-Boiled Eggs, Garbanzo Beans,
    Fresh Spinach, and Extra Virgin Olive Oil can be combined independently.
    """
    station_lower = base_item['station'].lower()
    name_lower = base_item['name'].lower().strip()
    ingredients_lower = (base_item['ingredients'] or '').lower().strip()

    is_composite = any(
        kw in station_lower or kw in name_lower
        for kw in ['salad bar', 'toppings', 'condiments']
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
        ('Fresh Spinach', 'fresh spinach', [], True),
        ('Hard-Boiled Eggs', 'hard-boiled eggs', ['eggs'], True),
        ('Garbanzo Beans', 'garbanzo beans', [], True),
        ('Extra Virgin Olive Oil', 'extra virgin olive oil', [], True),
        ('Plain Grilled Chicken Breast', 'plain grilled chicken breast', [], False),
        ('Plain Brown Rice', 'plain brown rice', [], True),
    ]

    unpacked = []
    expose_default_bar = (
        ingredients_lower in ('', 'n/a')
        and ('salad bar' in name_lower or 'salad bar' in station_lower)
    )

    for display_name, fallback_key, staple_allergens, staple_veg in staple_aliases:
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
                'allergens': list(staple_allergens),
                'is_vegetarian': staple_veg,
                'used_fallback': True,
            })
            unpacked.append(sub_item)

    return unpacked if unpacked else [base_item]


def hydrate_missing_macros(items: list[dict]) -> list[dict]:
    """
    Fills in ordered USDA macro estimates when Purdue's API returns an empty
    Nutrients array (calories == 0 and protein == 0).
    """
    hydrated = []
    for item in items:
        copy_item = dict(item)
        copy_item.setdefault('allergens', [])
        copy_item.setdefault('is_vegetarian', None)
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
    details (including Nutrients, Ingredients, and Allergens) concurrently.
    """
    date_str = target_date or get_purdue_now().strftime('%Y-%m-%d')
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

    unique_item_ids = set()
    for meal in data['Meals']:
        for station in meal.get('Stations', []):
            for item in station.get('Items', []):
                item_id = item.get('ID')
                if item_id:
                    unique_item_ids.add(item_id)

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
                allergens, is_vegetarian = _extract_allergens_and_diet(detail_data)

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
                    'allergens': allergens,
                    'is_vegetarian': is_vegetarian,
                    'used_fallback': used_fallback,
                }

                normalized_items.extend(_unpack_composite_items(base_record))

    return hydrate_missing_macros(normalized_items)


def merge_external_menus(
    menu_items: list[dict], static_menu_path: Optional[str] = None
) -> list[dict]:
    """Hook to merge off-API venues or custom static JSON menus."""
    if not static_menu_path or not os.path.exists(static_menu_path):
        return menu_items

    try:
        with open(static_menu_path, 'r', encoding='utf-8') as f:
            external_data = json.load(f)
    except (OSError, ValueError):
        return menu_items

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
            'allergens': [str(a).lower() for a in entry.get('allergens', [])],
            'is_vegetarian': entry.get('is_vegetarian'),
            'used_fallback': bool(entry.get('used_fallback', False)),
        }
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
    """
    today_str = get_purdue_now().strftime('%Y-%m-%d')
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
# MODULE 2: EXPANDED USDA DRI & SINGLE-MEAL MACRO CALCULATOR
# ==============================================================================

def calculate_meal_targets(
    sex: str,
    age: int,
    weight_lbs: float,
    height_in: float,
    activity_level: str,
    meals_per_day: int,
    meal_goal: str = 'Balanced Maintenance',
    health_intensity: str = 'High',
) -> dict:
    """
    Computes daily Calories via Mifflin-St Jeor and derives per-meal macro ranges
    across five tailored student nutrition goals.
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
    maintenance_calories = bmr * multiplier

    goal_norm = meal_goal.strip().lower()

    if 'high protein' in goal_norm or 'muscle' in goal_norm:
        daily_calories = maintenance_calories * 1.08
        daily_protein_min = weight_kg * 1.35
        daily_protein_target = weight_kg * 1.65
        daily_protein_max = weight_kg * 1.85
        daily_carbs_min = max((daily_calories * 0.32) / 4.0, 130.0)
        daily_carbs_target = max((daily_calories * 0.40) / 4.0, 150.0)
        daily_carbs_max = (daily_calories * 0.50) / 4.0
        daily_fat_min = (daily_calories * 0.20) / 9.0
        daily_fat_target = (daily_calories * 0.25) / 9.0
        daily_fat_max = (daily_calories * 0.32) / 9.0

    elif 'lean cut' in goal_norm or 'fat loss' in goal_norm:
        daily_calories = maintenance_calories * 0.825  # ~17.5% moderate deficit
        daily_protein_min = weight_kg * 1.4
        daily_protein_target = weight_kg * 1.55
        daily_protein_max = weight_kg * 1.75
        daily_carbs_min = max((daily_calories * 0.25) / 4.0, 130.0)
        daily_carbs_target = max((daily_calories * 0.33) / 4.0, 135.0)
        daily_carbs_max = (daily_calories * 0.42) / 4.0
        daily_fat_min = (daily_calories * 0.20) / 9.0
        daily_fat_target = (daily_calories * 0.25) / 9.0
        daily_fat_max = (daily_calories * 0.32) / 9.0

    elif 'athletic' in goal_norm or 'endurance' in goal_norm:
        daily_calories = maintenance_calories * 1.05
        daily_protein_min = weight_kg * 1.15
        daily_protein_target = weight_kg * 1.35
        daily_protein_max = weight_kg * 1.55
        daily_carbs_min = max((daily_calories * 0.43) / 4.0, 160.0)
        daily_carbs_target = max((daily_calories * 0.48) / 4.0, 180.0)
        daily_carbs_max = (daily_calories * 0.55) / 4.0
        daily_fat_min = (daily_calories * 0.20) / 9.0
        daily_fat_target = (daily_calories * 0.24) / 9.0
        daily_fat_max = (daily_calories * 0.30) / 9.0

    elif 'low-carb' in goal_norm or 'low carb' in goal_norm or 'blood sugar' in goal_norm:
        daily_calories = maintenance_calories
        daily_protein_min = weight_kg * 1.3
        daily_protein_target = weight_kg * 1.5
        daily_protein_max = weight_kg * 1.75
        daily_carbs_min = 60.0
        daily_carbs_target = (daily_calories * 0.20) / 4.0
        daily_carbs_max = (daily_calories * 0.26) / 4.0
        daily_fat_min = (daily_calories * 0.32) / 9.0
        daily_fat_target = (daily_calories * 0.38) / 9.0
        daily_fat_max = (daily_calories * 0.46) / 9.0

    else:
        # Balanced Maintenance (USDA DRI baseline)
        daily_calories = maintenance_calories
        daily_protein_min = weight_kg * 0.8
        daily_protein_target = weight_kg * 1.1
        daily_protein_max = weight_kg * 1.4
        daily_carbs_min = 130.0
        daily_carbs_target = max((daily_calories * 0.40) / 4.0, 145.0)
        daily_carbs_max = (daily_calories * 0.50) / 4.0
        daily_fat_min = (daily_calories * 0.20) / 9.0
        daily_fat_target = (daily_calories * 0.26) / 9.0
        daily_fat_max = (daily_calories * 0.33) / 9.0

    if health_intensity.strip().lower() == 'high':
        daily_sugar_max = min(daily_aha_sugar_cap, 20.0)
    else:
        daily_sugar_max = daily_aha_sugar_cap

    meals = max(1, int(meals_per_day))

    return {
        'goal_label': meal_goal,
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
    """Extracts HH:MM(:SS) from Purdue HFS timestamps in PURDUE_TZ."""
    if not time_str:
        return None
    clean = str(time_str).strip()

    for fmt in ('%I:%M %p', '%I:%M:%S %p'):
        try:
            parsed_t = datetime.strptime(clean, fmt).time()
            return datetime.combine(base_date, parsed_t, tzinfo=PURDUE_TZ)
        except ValueError:
            continue

    after_t = clean.split('T')[-1]
    match = re.search(r'(\d{1,2}:\d{2}(?::\d{2})?)', after_t)
    if match:
        time_part = match.group(1)
        fmt = '%H:%M:%S' if time_part.count(':') == 2 else '%H:%M'
        try:
            parsed_t = datetime.strptime(time_part, fmt).time()
            return datetime.combine(base_date, parsed_t, tzinfo=PURDUE_TZ)
        except ValueError:
            return None
    return None


def _format_display_time(dt_obj: datetime) -> str:
    return dt_obj.strftime('%I:%M %p').lstrip('0').lower()


def filter_open_locations(
    items: list[dict], current_time: Optional[datetime] = None
) -> list[dict]:
    """
    Filters items to dining locations currently open or opening within 30 minutes.
    If run between meal periods, falls back to the next upcoming meal today.
    """
    now = current_time or get_purdue_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=PURDUE_TZ)
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
# MODULE 4: EASY-LINE FILTER, ALLERGEN/DIETARY FILTER & 3-TIER HEALTH SCORING
# ==============================================================================

def _is_special_order_item(item: dict) -> bool:
    """
    Returns True if the item or station requires placing a special request,
    custom ticket, or made-to-order preparation (e.g., 'By Request' station,
    custom omelets, made-to-order stir-fry/pasta).
    """
    station_lower = (item.get('station') or '').lower().strip()
    name_lower = (item.get('name') or '').lower().strip()

    if any(marker in station_lower for marker in SPECIAL_ORDER_STATION_MARKERS):
        return True
    if any(marker in name_lower for marker in SPECIAL_ORDER_ITEM_MARKERS):
        return True
    return False


def _passes_dietary_filters(item: dict, dietary_filters: list[str]) -> bool:
    """
    Checks an item against selected allergen and dietary filters using both the
    Purdue HFS API Allergens array and ingredient/name text fallbacks.
    Supported filters:
      gluten-free, dairy-free, egg-free, soy-free, peanut-free,
      tree-nut-free, shellfish-free, vegetarian
    """
    if not dietary_filters:
        return True

    active = {f.strip().lower() for f in dietary_filters if f}
    allergens = {str(a).strip().lower() for a in (item.get('allergens') or [])}
    name_lower = (item.get('name') or '').lower()
    ing_lower = (item.get('ingredients') or '').lower()
    combined = f'{name_lower} {ing_lower}'

    allergen_rules = {
        'gluten-free': {
            'api_tags': {'gluten', 'wheat'},
            'keywords': ['wheat', 'barley', 'rye', 'semolina', 'flour', 'bread', 'pasta', 'tortilla', 'crouton', 'panko', 'bagel', 'muffin', 'pancake', 'pita'],
            'safe_override': ['gluten-free', 'gluten free', 'gf '],
        },
        'dairy-free': {
            'api_tags': {'milk', 'dairy'},
            'keywords': ['milk', 'cheese', 'butter', 'cream', 'whey', 'casein', 'yogurt', 'mozzarella', 'cheddar', 'parmesan', 'feta', 'ricotta', 'queso'],
            'safe_override': ['dairy-free', 'dairy free', 'vegan', 'violife'],
        },
        'egg-free': {
            'api_tags': {'eggs', 'egg'},
            'keywords': ['egg', 'mayonnaise', 'aioli'],
            'safe_override': ['egg-free', 'egg free', 'vegan'],
        },
        'soy-free': {
            'api_tags': {'soy', 'soybeans'},
            'keywords': ['soy', 'soybean', 'tofu', 'edamame', 'tamari', 'teriyaki', 'miso'],
            'safe_override': ['soy-free', 'soy free'],
        },
        'peanut-free': {
            'api_tags': {'peanuts', 'peanut'},
            'keywords': ['peanut', 'kung pao', 'reese'],
            'safe_override': ['peanut-free', 'peanut free'],
        },
        'tree-nut-free': {
            'api_tags': {'tree nuts', 'tree nut', 'nuts'},
            'keywords': ['almond', 'walnut', 'pecan', 'cashew', 'pistachio', 'hazelnut', 'macadamia', 'pine nut', 'coconut'],
            'safe_override': ['nut-free', 'nut free'],
        },
        'shellfish-free': {
            'api_tags': {'shellfish', 'crustacean shellfish'},
            'keywords': ['shrimp', 'crab', 'lobster', 'clam', 'mussel', 'oyster', 'scallop', 'crawfish'],
            'safe_override': [],
        },
    }

    for filter_key, rule in allergen_rules.items():
        if filter_key not in active:
            continue

        # 1. Explicit API allergen match
        if allergens & rule['api_tags']:
            return False

        # 2. Text fallback check unless item explicitly declares itself safe
        if not any(safe in name_lower for safe in rule['safe_override']):
            if any(re.search(rf'\b{re.escape(kw)}s?\b', combined) for kw in rule['keywords']):
                return False

    if 'vegetarian' in active:
        is_veg = item.get('is_vegetarian')
        if is_veg is False:
            return False
        if is_veg is None:
            if any(re.search(rf'\b{re.escape(m)}s?\b', combined) for m in MEAT_SEAFOOD_KEYWORDS):
                return False

    return True


def _is_whole_fruit(name_lower: str) -> bool:
    if any(d in name_lower for d in DESSERT_KEYWORDS + ['sauce', 'syrup', 'juice']):
        return False
    return any(fr in name_lower for fr in WHOLE_FRUIT_KEYWORDS)


def _is_verified_na_whole_food(item: dict) -> bool:
    name_lower = item['name'].lower().strip()
    station_lower = item['station'].lower().strip()

    if 'salad bar' in station_lower or '(salad bar)' in name_lower:
        if any(
            st in name_lower
            for st in ['spinach', 'greens', 'hard-boiled egg', 'garbanzo', 'chickpea', 'olive oil', 'grilled chicken', 'brown rice']
        ):
            return True

    if _is_whole_fruit(name_lower):
        return True

    unverified_risk_words = [
        'salad', 'bowl', 'stir fry', 'moo shu', 'teriyaki', 'sauce', 'glaze',
        'fried', 'crispy', 'breaded', 'dip', 'queso', 'cheese', 'creamy', 'casserole'
    ]
    if any(risk in name_lower for risk in unverified_risk_words):
        return False

    return any(vf in name_lower for vf in VERIFIED_NA_WHOLE_FOODS)


def evaluate_item_health(item: dict, health_intensity: str) -> tuple[bool, float, str]:
    """
    Evaluates an item against the selected mode ('High' = Healthiest,
    'Mid' = Balanced, 'Low' = Yummiest), enforcing easy-line self-serve rules
    and the strict 'Ingredients: N/A' guardrail in Healthiest mode.
    """
    tier = health_intensity.strip().lower()
    name_lower = item['name'].lower().strip()
    ing_raw = (item['ingredients'] or '').strip()
    ing_lower = ing_raw.lower()
    combined_text = f'{name_lower} {ing_lower}'

    # Exclude special-order / custom-ticket items and station headers
    if _is_special_order_item(item):
        return False, -100.0, 'Excluded: requires custom or special-request order'
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
        if ing_raw.upper() == 'N/A' and not _is_verified_na_whole_food(item):
            return False, -100.0, 'Excluded from Healthiest mode: unverified ingredients (N/A)'
        if has_seed_oil:
            return False, -100.0, 'Excluded: contains seed oils'
        if is_deep_fried:
            return False, -100.0, 'Excluded: deep-fried or battered'
        if has_artificial:
            return False, -100.0, 'Excluded: artificial dyes or preservatives'
        if is_dessert or is_dip_or_sauce:
            return False, -100.0, 'Excluded: dessert, dip, or heavy sauce'
        if has_high_sugar or (item['sugar'] > 10.0 and not whole_fruit):
            return False, -100.0, 'Excluded: high added/refined sugar'

        bonus = 18.0 + min(item['protein'] * 0.35, 12.0)
        if 'salad bar' in item['station'].lower() or '(salad bar)' in name_lower:
            bonus += 6.0
        if 'olive oil' in combined_text or 'butter' in combined_text:
            bonus += 4.0
        return True, round(bonus, 1), 'Zero seed oils & verified whole-food ingredients'

    elif tier == 'mid':
        if is_deep_fried:
            return False, -100.0, 'Excluded: deep-fried or heavily battered'
        if has_artificial:
            return False, -100.0, 'Excluded: artificial dyes or preservatives'
        if is_dessert:
            return False, -100.0, 'Excluded: dessert item'
        if (has_high_sugar and item['protein'] < 10.0) or (item['sugar'] > 18.0 and not whole_fruit):
            return False, -100.0, 'Excluded: sugary glaze or high-sugar item'

        clean_bonus = 12.0 if (not has_seed_oil and ing_raw.upper() != 'N/A') else 5.0
        protein_bonus = min(item['protein'] * 0.3, 10.0)
        reason = (
            'Clean whole-food protein/base without seed oils'
            if (not has_seed_oil and ing_raw.upper() != 'N/A')
            else 'Balanced everyday entree & lean protein pick'
        )
        return True, round(clean_bonus + protein_bonus, 1), reason

    else:  # 'low' -> Yummiest
        if is_dip_or_sauce and item['protein'] < 5.0:
            return False, -100.0, 'Excluded standalone sauce/condiment'
        bonus = min(item['protein'] * 0.55, 22.0) + min(item['calories'] * 0.015, 8.0)
        return True, round(bonus, 1), 'Top flavor & protein-packed comfort favorite'


def _classify_item_role(item: dict) -> str:
    """
    Categorizes a menu item into 'protein', 'carb', or 'side' so suggested
    plates compose naturally like a real meal.
    """
    name_lower = item['name'].lower().strip()

    if (
        name_lower in STATION_HEADER_NAMES
        or any(d in name_lower for d in DESSERT_KEYWORDS)
        or any(ds in name_lower for ds in DIP_SAUCE_KEYWORDS)
    ):
        return 'side'

    if any(k in name_lower for k in ['olive oil', 'spinach', 'greens', 'broccoli', 'asparagus', 'brussels', 'vegetable', 'salad', 'edamame']):
        return 'side'

    if _is_whole_fruit(name_lower):
        return 'side'

    # Main entree protein (high protein density or explicit entree meat/tofu/eggs)
    entree_protein_hints = ['chicken', 'beef', 'steak', 'pork', 'salmon', 'fish', 'shrimp', 'turkey', 'tofu', 'egg', 'gyro', 'burger']
    if item['protein'] >= 11.0 and (
        item['protein'] >= item['carbs'] * 0.55
        or any(h in name_lower for h in entree_protein_hints)
    ):
        return 'protein'

    # Complementary carb / grain base
    if item['carbs'] >= 15.0 and item['carbs'] > item['protein']:
        return 'carb'

    return 'side'


def _range_error(val: float, low: float, high: float) -> float:
    if val < low:
        return (low - val) / max(low, 1.0)
    if val > high:
        return (val - high) / max(high, 1.0)
    return 0.0


def _build_why_top_pick(
    location: str,
    plate_items: list[dict],
    totals: dict,
    health_intensity: str,
    dri_enabled: bool,
    per_meal: Optional[dict],
    dietary_filters: list[str],
) -> str:
    """Generates a concise, human-friendly summary explaining why this court won."""
    tier_map = {
        'high': 'seed-oil-free whole foods',
        'mid': 'balanced everyday nutrition',
        'low': 'flavor & protein density',
    }
    mode_desc = tier_map.get(health_intensity.strip().lower(), 'quality nutrition')
    stations = list(dict.fromkeys(i['station'] for i in plate_items))
    station_str = ', '.join(stations[:2])

    filter_note = ''
    if dietary_filters:
        pretty_filters = ', '.join(f.replace('-', ' ').title() for f in dietary_filters[:3])
        filter_note = f' Verified {pretty_filters}.'

    if dri_enabled and per_meal:
        cal_pct = int(round((totals['calories'] / max(per_meal['calories'], 1.0)) * 100))
        return (
            f"Best {mode_desc} match at {station_str} — hits {totals['protein']}g protein "
            f"and {cal_pct}% of your {int(round(per_meal['calories']))} kcal meal target.{filter_note}"
        )

    return (
        f"Top {mode_desc} pairing ready on the regular line at {station_str} "
        f"({totals['protein']}g protein, {int(round(totals['calories']))} kcal).{filter_note}"
    )


# ==============================================================================
# MODULE 5: COHESIVE PLATE BUILDER & OPTIONAL DRI PORTION-SIZING SOLVER
# ==============================================================================

def build_optimal_plates(
    open_items: list[dict],
    meal_targets: Optional[dict],
    meal_goal: str,
    health_intensity: str,
    dri_enabled: bool = False,
    dietary_filters: Optional[list[str]] = None,
    top_n: int = 3,
) -> list[dict]:
    """
    Builds cohesive, non-repetitive multi-item plates (Protein + Carb/Grain + Side)
    for open Purdue dining courts:
    - When dri_enabled is False: ranks courts purely on mode quality, allergen
      compliance, and balanced 1x meal pairings without personal macro targets.
    - When dri_enabled is True: solves for clean serving multipliers (1x, 1.5x, 2x)
      to hit per-meal USDA DRI ranges accurately without repeating rows.
    """
    active_filters = dietary_filters or []
    per_meal = (meal_targets or {}).get('per_meal') if dri_enabled else None
    goal_norm = meal_goal.strip().lower()
    is_high_protein = ('high protein' in goal_norm) or ('lean cut' in goal_norm)

    by_location: dict[str, list[dict]] = {}
    for item in open_items:
        if not _passes_dietary_filters(item, active_filters):
            continue
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
            key=lambda x: (x['_health_bonus'] + x['protein'] * 0.8),
            reverse=True,
        )[:8]
        carbs = sorted(
            [i for i in pool if i['_role'] == 'carb'],
            key=lambda x: (x['_health_bonus'] + x['carbs'] * 0.35),
            reverse=True,
        )[:6]
        sides = sorted(
            [i for i in pool if i['_role'] == 'side'],
            key=lambda x: (x['_health_bonus'] + x['protein'] * 0.5 + x['calories'] * 0.04),
            reverse=True,
        )[:6]

        # Allow vegetarian / allergen-restricted menus to pair a hearty legume/grain bowl
        # even if no >=11g single meat item is present
        if not proteins:
            fallback_mains = sorted(
                [i for i in pool if i['protein'] >= 6.0 and i['calories'] >= 100.0],
                key=lambda x: (x['_health_bonus'] + x['protein']),
                reverse=True,
            )[:4]
            if not fallback_mains:
                continue
            proteins = fallback_mains

        carb_choices = carbs if carbs else [None]
        side_choices = sides if sides else [None]

        # Portion multipliers: strictly 1.0x when DRI is OFF; solver multipliers when DRI is ON
        if dri_enabled and per_meal:
            p_mults = [1.0, 1.5, 2.0]
            c_mults = [1.0, 1.5, 2.0]
            s_mults = [1.0, 1.5]
        else:
            p_mults = [1.0]
            c_mults = [1.0]
            s_mults = [1.0]

        best_plate_score = -1e9
        best_plate_data = None

        for p_item, c_item, s_item in product(proteins, carb_choices, side_choices):
            # Ensure every item on the plate is strictly distinct
            chosen_names = [p_item['name']]
            if c_item:
                if c_item['name'] in chosen_names:
                    continue
                chosen_names.append(c_item['name'])
            if s_item:
                if s_item['name'] in chosen_names:
                    continue
                chosen_names.append(s_item['name'])

            for pm in p_mults:
                for cm in (c_mults if c_item else [1.0]):
                    for sm in (s_mults if s_item else [1.0]):
                        # Avoid scaling a plain fruit side above 1x
                        if s_item and s_item['_is_fruit'] and sm > 1.0:
                            continue

                        slots = [('Main Protein', p_item, pm)]
                        if c_item:
                            slots.append(('Grain / Carb Base', c_item, cm))
                        if s_item:
                            slots.append(('Veggie / Fruit Side', s_item, sm))

                        tot_cal = sum(it['calories'] * m for _, it, m in slots)
                        tot_pro = sum(it['protein'] * m for _, it, m in slots)
                        tot_carb = sum(it['carbs'] * m for _, it, m in slots)
                        tot_fat = sum(it['fat'] * m for _, it, m in slots)
                        tot_sugar = sum(it['sugar'] * m for _, it, m in slots)

                        avg_health = sum(it['_health_bonus'] for _, it, _ in slots) / len(slots)
                        cohesion_bonus = (4.0 if c_item else 0.0) + (4.0 if s_item else 0.0)

                        if dri_enabled and per_meal:
                            cal_err = abs(tot_cal - per_meal['calories']) / max(per_meal['calories'], 1.0)
                            pro_err = abs(tot_pro - per_meal['protein_target']) / max(per_meal['protein_target'], 1.0)
                            carb_err = _range_error(tot_carb, per_meal['carbs_min'], per_meal['carbs_max'])
                            fat_err = _range_error(tot_fat, per_meal['fat_min'], per_meal['fat_max'])

                            pro_shortfall = 0.0
                            if tot_pro < per_meal['protein_min']:
                                pro_shortfall = (
                                    (per_meal['protein_min'] - tot_pro) / max(per_meal['protein_min'], 1.0)
                                ) * 38.0

                            # Slight preference for simpler 1x portions when macro fit is tied
                            portion_complexity = ((pm - 1.0) + (cm - 1.0) + (sm - 1.0)) * 1.2

                            if is_high_protein:
                                macro_penalty = (pro_err * 40.0) + (cal_err * 22.0) + (carb_err * 10.0) + (fat_err * 10.0)
                            else:
                                macro_penalty = (cal_err * 24.0) + (pro_err * 26.0) + (carb_err * 15.0) + (fat_err * 15.0)

                            total_score = 100.0 + avg_health + cohesion_bonus - macro_penalty - pro_shortfall - portion_complexity
                        else:
                            # Non-DRI mode: score by mode quality, meal balance, and satisfying protein
                            protein_yield_bonus = min(tot_pro * 0.35, 16.0)
                            satiety_bonus = 5.0 if 400.0 <= tot_cal <= 950.0 else 0.0
                            total_score = 100.0 + avg_health + cohesion_bonus + protein_yield_bonus + satiety_bonus

                        if total_score > best_plate_score:
                            best_plate_score = total_score
                            formatted_items = []
                            for role_label, it, mult in slots:
                                mult_clean = int(mult) if float(mult).is_integer() else round(mult, 1)
                                formatted_items.append({
                                    'role': role_label,
                                    'station': it['station'],
                                    'name': it['name'],
                                    'servings': mult_clean,
                                    'calories': round(it['calories'] * mult, 1),
                                    'protein': round(it['protein'] * mult, 1),
                                    'carbs': round(it['carbs'] * mult, 1),
                                    'fat': round(it['fat'] * mult, 1),
                                    'allergens': it.get('allergens', []),
                                    'used_fallback': it['used_fallback'],
                                    'reason': it['_health_reason'],
                                })

                            totals_obj = {
                                'calories': round(tot_cal, 1),
                                'protein': round(tot_pro, 1),
                                'carbs': round(tot_carb, 1),
                                'fat': round(tot_fat, 1),
                                'sugar': round(tot_sugar, 1),
                            }

                            why_pick = _build_why_top_pick(
                                location=location,
                                plate_items=formatted_items,
                                totals=totals_obj,
                                health_intensity=health_intensity,
                                dri_enabled=dri_enabled,
                                per_meal=per_meal,
                                dietary_filters=active_filters,
                            )

                            best_plate_data = {
                                'location': location,
                                'hours_status': p_item['hours_status'],
                                'closing_time': p_item['closing_time'],
                                'score': round(total_score, 1),
                                'items': formatted_items,
                                'totals': totals_obj,
                                'why_top_pick': why_pick,
                                'filter_summary': '; '.join(
                                    dict.fromkeys(it['_health_reason'] for _, it, _ in slots)
                                ),
                            }

        if best_plate_data:
            location_results.append(best_plate_data)

    location_results.sort(key=lambda r: r['score'], reverse=True)
    return location_results[:top_n]


def recommend_meals(
    sex: Optional[str] = None,
    age: Optional[int] = None,
    weight_lbs: Optional[float] = None,
    height_in: Optional[float] = None,
    activity_level: Optional[str] = None,
    meals_per_day: Optional[int] = None,
    meal_goal: str = 'Balanced Maintenance',
    health_intensity: str = 'High',
    dri_enabled: bool = False,
    dietary_filters: Optional[list[str]] = None,
    include_quick_bites: bool = False,
    static_menu_path: Optional[str] = None,
    current_time: Optional[datetime] = None,
) -> dict:
    """
    Top-level orchestrator function. Supports both instant zero-biometric mode
    (dri_enabled=False) and personalized USDA DRI portion-sizing mode (dri_enabled=True).
    """
    targets = None
    if dri_enabled:
        if not all([sex, age, weight_lbs, height_in, activity_level, meals_per_day]):
            raise ValueError('Please fill in all biometric fields to enable USDA DRI portion sizing.')
        targets = calculate_meal_targets(
            sex=str(sex),
            age=int(age),
            weight_lbs=float(weight_lbs),
            height_in=float(height_in),
            activity_level=str(activity_level),
            meals_per_day=int(meals_per_day),
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
        dri_enabled=dri_enabled,
        dietary_filters=dietary_filters or [],
        top_n=3,
    )

    return {
        'timestamp': (current_time or get_purdue_now()).strftime('%Y-%m-%d %I:%M %p'),
        'loaded_from_cache': from_cache,
        'dri_enabled': dri_enabled,
        'health_intensity': health_intensity,
        'dietary_filters': dietary_filters or [],
        'targets': targets,
        'open_locations_count': len({i['location'] for i in open_items}),
        'recommendations': recommendations,
    }


def _parse_user_time_input(raw_input: str) -> Optional[datetime]:
    """Safely parses 'HH:MM' 24-hr or '12:30 PM' input in PURDUE_TZ; returns None on empty/invalid."""
    clean = raw_input.strip()
    if not clean:
        return None
    for fmt in ('%H:%M', '%I:%M %p', '%I:%M%p'):
        try:
            parsed_t = datetime.strptime(clean, fmt).time()
            return datetime.combine(get_purdue_now().date(), parsed_t, tzinfo=PURDUE_TZ)
        except ValueError:
            continue
    return None