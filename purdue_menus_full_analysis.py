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

DEFAULT_MEAL_WINDOWS = {
    'breakfast': ('07:00:00', '10:00:00'),
    'brunch': ('10:00:00', '14:00:00'),
    'lunch': ('11:00:00', '14:00:00'),
    'late lunch': ('14:00:00', '17:00:00'),
    'dinner': ('17:00:00', '20:30:00'),
}

FALLBACK_MACROS = {
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

ORDERED_KEYWORD_MACROS = [
    # 1. Standalone buns, breads, and bakery items
    ('hamburger bun', (130.0, 4.0, 24.0, 2.0, 3.0)),
    ('hot dog bun', (120.0, 4.0, 22.0, 2.0, 3.0)),
    ('brioche bun', (150.0, 4.5, 26.0, 3.0, 4.0)),
    ('sub roll', (180.0, 6.0, 34.0, 2.0, 3.0)),
    ('hoagie roll', (180.0, 6.0, 34.0, 2.0, 3.0)),
    ('dinner roll', (110.0, 3.5, 20.0, 2.0, 2.0)),
    ('english muffin', (130.0, 5.0, 25.0, 1.0, 2.0)),
    ('bagel', (250.0, 9.0, 48.0, 1.5, 5.0)),
    ('croissant', (230.0, 5.0, 26.0, 12.0, 6.0)),
    ('biscuit', (210.0, 4.0, 25.0, 10.0, 3.0)),
    ('pita', (165.0, 5.5, 33.0, 1.0, 1.0)),
    ('naan', (260.0, 8.0, 45.0, 5.0, 3.0)),
    ('tortilla', (140.0, 4.0, 24.0, 3.0, 1.0)),
    ('bread', (140.0, 5.0, 26.0, 2.0, 3.0)),
    ('bun', (130.0, 4.0, 24.0, 2.0, 3.0)),
    ('roll', (130.0, 4.0, 24.0, 2.0, 2.0)),

    # 2. Desserts, pastries, and baked sweets
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

    # 3. Dips, sauces, and spreads
    ('queso dip', (220.0, 8.0, 10.0, 16.0, 2.0)),
    ('queso', (210.0, 8.0, 9.0, 16.0, 2.0)),
    ('spinach dip', (230.0, 6.0, 11.0, 18.0, 2.0)),
    ('dip', (190.0, 5.0, 12.0, 14.0, 2.0)),
    ('gravy', (90.0, 2.0, 8.0, 5.5, 1.0)),
    ('sauce', (80.0, 1.5, 10.0, 4.0, 5.0)),

    # 4. Composite sandwiches, bowls, stir-fries, and dressed salads
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

    # 5. Single proteins & dairy anchors
    ('scrambled egg', (180.0, 12.0, 2.0, 13.5, 1.0)),
    ('hard boiled egg', (78.0, 6.3, 0.6, 5.3, 0.6)),
    ('egg', (155.0, 12.5, 1.1, 10.6, 1.0)),
    ('grilled chicken breast', (185.0, 35.0, 0.0, 4.0, 0.0)),
    ('chicken breast', (185.0, 35.0, 0.0, 4.0, 0.0)),
    ('chicken', (215.0, 28.0, 2.0, 9.5, 0.5)),
    ('turkey', (200.0, 28.0, 1.0, 8.0, 0.5)),
    ('carne asada', (250.0, 27.0, 2.0, 14.0, 0.5)),
    ('steak', (265.0, 29.0, 0.0, 16.0, 0.0)),
    ('hamburger patty', (250.0, 26.0, 1.0, 15.0, 0.0)),
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
    ('cottage cheese', (120.0, 14.0, 5.0, 4.5, 4.0)),
    ('greek yogurt', (130.0, 15.0, 6.0, 4.0, 5.0)),

    # 6. Legumes, grains, and complex carbohydrates
    ('garbanzo', (135.0, 7.3, 22.5, 2.1, 4.0)),
    ('chickpea', (135.0, 7.3, 22.5, 2.1, 4.0)),
    ('black bean', (130.0, 8.0, 23.0, 0.8, 1.0)),
    ('kidney bean', (130.0, 8.0, 23.0, 0.8, 1.0)),
    ('pinto bean', (130.0, 8.0, 23.0, 0.8, 1.0)),
    ('bean', (130.0, 7.5, 22.0, 1.0, 1.5)),
    ('lentil', (130.0, 9.0, 22.0, 0.5, 1.5)),
    ('edamame', (120.0, 11.0, 9.0, 5.0, 2.0)),
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

    # 7. Vegetables and whole fruits
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
    'dip', 'queso', 'salsa', 'guacamole', 'hummus', 'tzatziki',
    'gravy', 'dressing', 'ranch', 'vinaigrette', 'mayonnaise', 'mayo',
    'aioli', 'ketchup', 'mustard', 'bbq sauce', 'hot sauce', 'soy sauce',
    'teriyaki sauce', 'marinara', 'alfredo sauce', 'pesto', 'tartar sauce',
    'cocktail sauce', 'sour cream', 'cream cheese', 'spread', 'chutney',
    'relish', 'au jus', 'syrup', 'jam', 'jelly', 'condiment', 'topping'
]
STANDALONE_BAKERY_KEYWORDS = [
    'bun', 'buns', 'bread', 'roll', 'rolls', 'bagel', 'tortilla', 'pita',
    'naan', 'croissant', 'biscuit', 'toast', 'english muffin', 'flatbread',
    'focaccia', 'ciabatta', 'brioche', 'breadstick', 'crackers', 'chips',
    'crouton', 'panko'
]
FILLED_ENTREE_OVERRIDES = [
    'burger', 'cheeseburger', 'sandwich', 'panini', 'wrap', 'burrito',
    'quesadilla', 'taco', 'gyro', 'sub', 'hoagie', 'pizza', 'calzone',
    'french toast', 'avocado toast'
]

# Single-ingredient whole foods whose N/A ingredient strings in Purdue's API are safe
VERIFIED_NA_WHOLE_FOODS = [
    'plain white rice', 'long grain rice', 'jasmine rice', 'basmati rice',
    'plain brown rice', 'brown rice', 'steamed rice', 'steamed white rice',
    'steamed brown rice', 'baked potato', 'plain potato', 'baked sweet potato',
    'sweet potato', 'steamed broccoli', 'steamed vegetables', 'steamed asparagus',
    'steamed green beans', 'steamed cauliflower', 'steamed carrots',
    'garbanzo beans', 'chickpeas', 'black beans', 'kidney beans', 'pinto beans',
    'lentils', 'edamame', 'quinoa', 'oatmeal',
    'plain grilled chicken breast', 'grilled chicken breast',
    'hard boiled egg', 'hard-boiled egg', 'boiled egg', 'poached egg',
    'cottage cheese', 'plain greek yogurt', 'greek yogurt'
]

# Keywords identifying plant/vegetarian whole-food anchors for Option B fallback
PLANT_VEG_ANCHOR_KEYWORDS = [
    'egg', 'tofu', 'paneer', 'tempeh', 'seitan', 'cottage cheese', 'greek yogurt',
    'black bean', 'kidney bean', 'pinto bean', 'garbanzo', 'chickpea', 'lentil',
    'edamame', 'quinoa', 'bean'
]

SPECIAL_ORDER_STATION_MARKERS = [
    'by request', 'upon request', 'special order', 'custom order',
    'made to order', 'made-to-order', 'omelet bar', 'omelette bar',
    'stir fry bar', 'stir-fry bar', 'pasta bar',
]

SPECIAL_ORDER_ITEM_MARKERS = [
    'by request', 'upon request', 'made to order', 'made-to-order',
    'custom omelet', 'custom omelette', 'custom stir fry', 'custom stir-fry',
    'custom pasta', 'special request',
]

MEAT_SEAFOOD_KEYWORDS = [
    'chicken', 'beef', 'pork', 'turkey', 'ham', 'bacon', 'sausage', 'steak',
    'lamb', 'veal', 'duck', 'venison', 'bison', 'meatball', 'pepperoni',
    'salami', 'prosciutto', 'chorizo', 'bratwurst', 'hot dog', 'gyro',
    'barbacoa', 'carnitas', 'brisket', 'rib', 'wings', 'drumstick',
    'salmon', 'tuna', 'cod', 'tilapia', 'shrimp', 'crab', 'lobster',
    'clam', 'mussel', 'oyster', 'scallop', 'anchovy', 'fish', 'seafood',
    'gelatin', 'lard', 'tallow', 'chicken broth', 'beef broth', 'fish sauce'
]

ANIMAL_BYPRODUCT_KEYWORDS = [
    'milk', 'cheese', 'butter', 'cream', 'whey', 'casein', 'yogurt',
    'mozzarella', 'cheddar', 'parmesan', 'feta', 'ricotta', 'queso',
    'egg', 'mayonnaise', 'aioli', 'honey', 'ghee', 'custard',
    'sour cream', 'cream cheese', 'buttermilk', 'goat cheese'
]


# ==============================================================================
# MODULE 1: API FETCHING, NORMALIZATION, CACHING & EXTERNAL MENU HOOK
# ==============================================================================

def _parse_numeric_value(raw_val) -> float:
    if raw_val is None:
        return 0.0
    if isinstance(raw_val, (int, float)):
        return float(raw_val)
    match = re.search(r'[-+]?\d*\.?\d+', str(raw_val))
    return float(match.group()) if match else 0.0


def _extract_allergens_and_diet(detail_data: Optional[dict]) -> tuple[list[str], Optional[bool], Optional[bool]]:
    if not detail_data:
        return [], None, None

    allergens: list[str] = []
    is_vegetarian: Optional[bool] = None
    is_vegan: Optional[bool] = None

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
            elif name == 'vegan':
                is_vegan = bool(has_flag)
                if has_flag:
                    is_vegetarian = True
            elif has_flag:
                allergens.append(name)

    if is_vegetarian is None and 'IsVegetarian' in detail_data:
        is_vegetarian = bool(detail_data.get('IsVegetarian'))
    if is_vegan is None and 'IsVegan' in detail_data:
        is_vegan = bool(detail_data.get('IsVegan'))
        if is_vegan:
            is_vegetarian = True

    return list(dict.fromkeys(allergens)), is_vegetarian, is_vegan


def _match_fallback_macro(item_name: str) -> Optional[dict]:
    lower_name = item_name.lower().strip()
    if lower_name in FALLBACK_MACROS:
        return FALLBACK_MACROS[lower_name]
    for key, macros in FALLBACK_MACROS.items():
        if key in lower_name:
            return macros
    return None


def _unpack_composite_items(base_item: dict) -> list[dict]:
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
    return [base_item]


def hydrate_missing_macros(items: list[dict]) -> list[dict]:
    hydrated = []
    for item in items:
        copy_item = dict(item)
        copy_item.setdefault('allergens', [])
        copy_item.setdefault('is_vegetarian', None)
        copy_item.setdefault('is_vegan', None)
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
    if not hasattr(_thread_local, 'session'):
        session = rq.Session()
        session.headers.update({'Accept': 'application/json'})
        _thread_local.session = session
    return _thread_local.session


def _fetch_single_item_detail(item_id: str) -> tuple[str, Optional[dict]]:
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
                allergens, is_vegetarian, is_vegan = _extract_allergens_and_diet(detail_data)

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
                    'is_vegan': is_vegan,
                    'used_fallback': used_fallback,
                }

                normalized_items.extend(_unpack_composite_items(base_record))

    return hydrate_missing_macros(normalized_items)


def merge_external_menus(
    menu_items: list[dict], static_menu_path: Optional[str] = None
) -> list[dict]:
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
            'is_vegan': entry.get('is_vegan'),
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
        daily_calories = maintenance_calories * 0.825
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
# MODULE 3: RESILIENT REAL-TIME OPERATING HOURS & TIME-AWARE GREETING
# ==============================================================================

def _parse_api_time(time_str: str, base_date) -> Optional[datetime]:
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


def _build_time_greeting(now: datetime) -> tuple[str, str]:
    hour = now.hour + (now.minute / 60.0)
    if 5.0 <= hour < 10.5:
        return (
            "Morning fuel, ready.",
            "Fresh breakfast plates open across campus right now."
        )
    elif 10.5 <= hour < 14.5:
        return (
            "Between classes?",
            "Here are the best meal combinations open right now."
        )
    elif 14.5 <= hour < 17.0:
        return (
            "Afternoon recharge.",
            "Light midday options and early dinner lines."
        )
    elif 17.0 <= hour < 21.0:
        return (
            "Dinner lineup.",
            "Balanced plates built from tonight's open dining courts."
        )
    else:
        return (
            "Late-night study mode.",
            "Here is the next meal lineup ready when courts open."
        )


def filter_open_locations(
    items: list[dict], current_time: Optional[datetime] = None
) -> list[dict]:
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
            updated['hours_status'] = f'{meal_period} until {formatted_end}'
            updated['closing_time'] = formatted_end
            open_items.append(updated)
        elif start_dt > now:
            seconds_until_open = (start_dt - now).total_seconds()
            updated = dict(item)
            updated['closing_time'] = formatted_end
            if seconds_until_open <= 1800:
                updated['hours_status'] = f'Opens at {formatted_start}'
                open_items.append(updated)
            else:
                updated['hours_status'] = f'{meal_period} ({formatted_start}–{formatted_end})'
                upcoming_items.append((start_dt, updated))

    if open_items:
        return open_items

    if upcoming_items:
        earliest_start = min(dt for dt, _ in upcoming_items)
        return [it for dt, it in upcoming_items if dt == earliest_start]

    return []


# ==============================================================================
# MODULE 4: DIETARY FILTERS & 3-TIER HEALTH SCORING
# ==============================================================================

def _is_special_order_item(item: dict) -> bool:
    station_lower = (item.get('station') or '').lower().strip()
    name_lower = (item.get('name') or '').lower().strip()

    if any(marker in station_lower for marker in SPECIAL_ORDER_STATION_MARKERS):
        return True
    if any(marker in name_lower for marker in SPECIAL_ORDER_ITEM_MARKERS):
        return True
    return False


def _passes_dietary_filters(item: dict, dietary_filters: list[str]) -> bool:
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

        if allergens & rule['api_tags']:
            return False

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

    if 'vegan' in active:
        is_vegan = item.get('is_vegan')
        if is_vegan is False or item.get('is_vegetarian') is False:
            return False
        if allergens & {'milk', 'dairy', 'eggs', 'egg', 'shellfish', 'crustacean shellfish', 'fish'}:
            return False
        if is_vegan is None and 'vegan' not in name_lower:
            if any(re.search(rf'\b{re.escape(m)}s?\b', combined) for m in MEAT_SEAFOOD_KEYWORDS):
                return False
            if any(re.search(rf'\b{re.escape(a)}s?\b', combined) for a in ANIMAL_BYPRODUCT_KEYWORDS):
                return False

    return True


def _is_whole_fruit(name_lower: str) -> bool:
    if any(d in name_lower for d in DESSERT_KEYWORDS + ['sauce', 'syrup', 'juice']):
        return False
    return any(fr in name_lower for fr in WHOLE_FRUIT_KEYWORDS)


def _is_dip_or_condiment(item: dict) -> bool:
    name_lower = (item.get('name') or '').lower().strip()
    station_lower = (item.get('station') or '').lower().strip()

    if any(k in station_lower for k in ['condiment', 'topping', 'dressing']):
        return True

    if any(ent in name_lower for ent in ['sandwich', 'panini', 'wrap', 'burrito']):
        return False

    return any(re.search(rf'\b{re.escape(ds)}s?\b', name_lower) for ds in DIP_SAUCE_KEYWORDS)


def _is_standalone_bakery(item: dict) -> bool:
    name_lower = (item.get('name') or '').lower().strip()

    if any(ov in name_lower for ov in FILLED_ENTREE_OVERRIDES):
        if not any(b in name_lower for b in ['bun', 'buns', 'roll', 'rolls', 'bread']):
            return False

    return any(re.search(rf'\b{re.escape(bk)}\b', name_lower) for bk in STANDALONE_BAKERY_KEYWORDS)


def _is_verified_na_whole_food(item: dict) -> bool:
    name_lower = item['name'].lower().strip()

    if _is_whole_fruit(name_lower):
        return True

    unverified_risk_words = [
        'salad', 'bowl', 'stir fry', 'moo shu', 'teriyaki', 'sauce', 'glaze',
        'fried', 'crispy', 'breaded', 'dip', 'queso', 'cheese', 'creamy', 'casserole'
    ]
    # Allow explicit cottage cheese / paneer whole foods
    if 'cottage cheese' in name_lower or 'paneer' in name_lower:
        return True

    if any(risk in name_lower for risk in unverified_risk_words):
        return False

    return any(vf in name_lower for vf in VERIFIED_NA_WHOLE_FOODS)


def evaluate_item_health(item: dict, health_intensity: str) -> tuple[bool, float, str]:
    tier = health_intensity.strip().lower()
    name_lower = item['name'].lower().strip()
    ing_raw = (item['ingredients'] or '').strip()
    ing_lower = ing_raw.lower()
    combined_text = f'{name_lower} {ing_lower}'

    if _is_special_order_item(item):
        return False, -100.0, 'Excluded: custom ticket'
    if name_lower in STATION_HEADER_NAMES:
        return False, -100.0, 'Excluded: station header'
    if _is_dip_or_condiment(item):
        return False, -100.0, 'Excluded: standalone dip, sauce, or condiment'

    if any(b in name_lower for b in ['hamburger bun', 'hot dog bun', 'sesame bun', 'wheat bun', 'white bun']):
        return False, -100.0, 'Excluded: standalone burger bun'

    zero_cal_items = ('water', 'ice', 'salt', 'black pepper', 'tea', 'black coffee', 'mustard', 'vinegar')
    if any(z == name_lower or f' {z}' in name_lower for z in zero_cal_items):
        return False, 0.0, 'Negligible macro contribution'

    has_seed_oil = any(oil in combined_text for oil in SEED_OILS)
    has_high_sugar = any(s in combined_text for s in HIGH_SUGAR_ADDITIVES)
    is_deep_fried = any(f in combined_text for f in DEEP_FRIED_MARKERS)
    has_artificial = any(a in combined_text for a in ARTIFICIAL_ADDITIVES)
    is_dessert = any(d in name_lower for d in DESSERT_KEYWORDS)
    whole_fruit = _is_whole_fruit(name_lower)

    if tier == 'high':
        # Strictly seed-oil free, dye free, deep-fry free, and added-sugar free
        if ing_raw.upper() == 'N/A' and not _is_verified_na_whole_food(item):
            return False, -100.0, 'Excluded from Healthiest mode: unverified ingredients'
        if has_seed_oil:
            return False, -100.0, 'Excluded: contains seed oils'
        if is_deep_fried:
            return False, -100.0, 'Excluded: deep-fried'
        if has_artificial:
            return False, -100.0, 'Excluded: artificial dyes or preservatives'
        if is_dessert:
            return False, -100.0, 'Excluded: dessert'
        if has_high_sugar or (item['sugar'] > 10.0 and not whole_fruit):
            return False, -100.0, 'Excluded: added sugar'

        bonus = 18.0 + min(item['protein'] * 0.35, 12.0)
        if 'olive oil' in combined_text or 'butter' in combined_text:
            bonus += 4.0
        return True, round(bonus, 1), 'Clean whole-food ingredients & seed-oil free'

    elif tier == 'mid':
        if is_deep_fried:
            return False, -100.0, 'Excluded: deep-fried'
        if has_artificial:
            return False, -100.0, 'Excluded: artificial additives'
        if is_dessert:
            return False, -100.0, 'Excluded: dessert'
        if (has_high_sugar and item['protein'] < 10.0) or (item['sugar'] > 18.0 and not whole_fruit):
            return False, -100.0, 'Excluded: high sugar glaze'

        clean_bonus = 12.0 if (not has_seed_oil and ing_raw.upper() != 'N/A') else 5.0
        protein_bonus = min(item['protein'] * 0.3, 10.0)
        reason = (
            'Seed-oil-free whole food pick'
            if (not has_seed_oil and ing_raw.upper() != 'N/A')
            else 'Balanced everyday dining court staple'
        )
        return True, round(clean_bonus + protein_bonus, 1), reason

    else:  # 'low' -> Yummiest
        bonus = min(item['protein'] * 0.55, 22.0) + min(item['calories'] * 0.015, 8.0)
        return True, round(bonus, 1), 'Rich flavor & crowd-favorite comfort pick'


# ==============================================================================
# MODULE 5: CULINARY COHESION ENGINE & OPTION B WHOLE-FOOD FALLBACK CURATOR
# ==============================================================================

def _detect_cuisine_profile(item: dict) -> str:
    text = f"{item.get('name', '')} {item.get('station', '')}".lower()

    if any(k in text for k in [
        'teriyaki', 'stir fry', 'stir-fry', 'jasmine', 'basmati', 'fried rice',
        'lo mein', 'noodle', 'dumpling', 'potsticker', 'edamame', 'sesame',
        'ginger', 'tofu', 'curry', 'tikka', 'masala', 'naan', 'banh mi',
        'pho', 'ramen', 'miso', 'general tso', 'orange chicken', 'kung pao',
        'moo shu', 'bulgogi', 'kimchi', 'one world', 'asian'
    ]):
        return 'asian'

    if any(k in text for k in [
        'taco', 'burrito', 'fajita', 'carnitas', 'barbacoa', 'carne asada',
        'quesadilla', 'enchilada', 'cilantro lime', 'black bean', 'pinto bean',
        'spanish rice', 'mexican rice', 'plantain', 'tortilla', 'chipotle',
        'elote', 'chorizo', 'poblano', 'latin'
    ]):
        return 'latin'

    if any(k in text for k in [
        'pasta', 'marinara', 'alfredo', 'spaghetti', 'penne', 'fettuccine',
        'lasagna', 'ravioli', 'parmesan', 'mozzarella', 'pesto', 'meatball',
        'italian', 'garlic bread', 'breadstick', 'focaccia', 'risotto',
        'bruschetta', 'pizza', 'flatbread', 'caprese', '2mato'
    ]):
        return 'italian'

    if any(k in text for k in [
        'gyro', 'pita', 'couscous', 'quinoa', 'greek', 'feta', 'olive',
        'chickpea', 'garbanzo', 'shawarma', 'kebab', 'kabob', 'tabbouleh',
        'oregano', 'lemon herb', 'mediterranean', 'falafel'
    ]):
        return 'mediterranean'

    if any(k in text for k in [
        'scrambled', 'omelet', 'omelette', 'bacon', 'sausage', 'pancake',
        'waffle', 'french toast', 'hash brown', 'tater tot', 'oatmeal',
        'biscuit', 'croissant', 'bagel', 'muffin', 'frittata', 'quiche', 'breakfast'
    ]):
        return 'breakfast'

    if any(k in text for k in [
        'burger', 'grilled chicken', 'steak', 'roast beef', 'meatloaf',
        'pork chop', 'pork loin', 'barbecue', 'bbq', 'pulled pork',
        'mac and cheese', 'mashed potato', 'roasted potato', 'baked potato',
        'sweet potato', 'corn on the cob', 'coleslaw', 'cornbread', 'turkey',
        'grill', 'homestyle', 'comfort'
    ]):
        return 'grill_comfort'

    return 'neutral'


def _is_composed_salad(item: dict) -> bool:
    name_lower = item['name'].lower()
    if 'salad' not in name_lower:
        return False
    if any(k in name_lower for k in ['chicken salad', 'tuna salad', 'egg salad']):
        return False
    return True


def _is_plant_veg_anchor(item: dict) -> bool:
    name_lower = item['name'].lower().strip()
    return any(re.search(rf'\b{re.escape(kw)}(?:s|es)?\b', name_lower) for kw in PLANT_VEG_ANCHOR_KEYWORDS)


def _classify_item_role(item: dict) -> str:
    name_lower = item['name'].lower().strip()

    if (
        name_lower in STATION_HEADER_NAMES
        or any(d in name_lower for d in DESSERT_KEYWORDS)
        or _is_dip_or_condiment(item)
    ):
        return 'exclude'

    if _is_standalone_bakery(item):
        if any(b in name_lower for b in ['bun', 'buns']):
            return 'exclude'
        return 'carb'

    if _is_composed_salad(item):
        return 'side'

    if any(k in name_lower for k in ['spinach', 'greens', 'broccoli', 'asparagus', 'brussels', 'vegetable', 'cauliflower', 'zucchini', 'carrots', 'green beans', 'corn']):
        return 'side'

    if _is_whole_fruit(name_lower):
        return 'side'

    entree_protein_hints = [
        'chicken', 'beef', 'steak', 'pork', 'salmon', 'fish', 'shrimp',
        'turkey', 'tofu', 'tempeh', 'seitan', 'egg', 'gyro', 'burger',
        'meatball', 'carnitas', 'barbacoa', 'tilapia', 'cod', 'ham', 'tuna',
        'paneer', 'cottage cheese', 'greek yogurt'
    ]
    has_protein_word = any(
        re.search(rf'\b{re.escape(h)}(?:s|es)?\b', name_lower)
        for h in entree_protein_hints
    )

    if item['protein'] >= 12.0 and (
        item['protein'] >= item['carbs'] * 0.65
        or has_protein_word
    ):
        return 'protein'

    if item['carbs'] >= 15.0 and item['carbs'] > item['protein']:
        return 'carb'

    return 'side'


def _build_option_b_anchors(pool: list[dict], existing_proteins: list[dict]) -> list[dict]:
    """
    Option B: Builds a prioritized list of strictly seed-oil-free whole-food
    anchors when a dining court lacks traditional meat entrees:
      1. Clean meats / eggs / tofu / paneer / Greek yogurt (>= 10g protein)
      2. Beans / lentils / chickpeas / edamame / quinoa (>= 6g protein)
      3. Whole-food complex grains & potatoes (rice, sweet potato, oatmeal)
    """
    anchors = list(existing_proteins)
    seen_names = {p['name'] for p in anchors}

    # Tier 1: Eggs, tofu, paneer, cottage cheese, Greek yogurt (even if < 12g, e.g., hard-boiled eggs)
    tier1 = sorted(
        [
            i for i in pool
            if i['name'] not in seen_names
            and not _is_standalone_bakery(i)
            and not _is_composed_salad(i)
            and (i['protein'] >= 6.0 and any(k in i['name'].lower() for k in ['egg', 'tofu', 'paneer', 'cottage cheese', 'greek yogurt', 'edamame']))
        ],
        key=lambda x: (x['_health_bonus'] + x['protein'] * 1.1),
        reverse=True,
    )
    for item in tier1:
        anchors.append(item)
        seen_names.add(item['name'])

    if len(anchors) >= 3:
        return anchors[:8]

    # Tier 2: Beans, lentils, chickpeas, quinoa
    tier2 = sorted(
        [
            i for i in pool
            if i['name'] not in seen_names
            and not _is_standalone_bakery(i)
            and not _is_composed_salad(i)
            and (_is_plant_veg_anchor(i) or (i['protein'] >= 6.0 and i['calories'] >= 100.0))
        ],
        key=lambda x: (x['_health_bonus'] + x['protein'] * 1.1 + x['calories'] * 0.03),
        reverse=True,
    )
    for item in tier2:
        anchors.append(item)
        seen_names.add(item['name'])

    if len(anchors) >= 2:
        return anchors[:8]

    # Tier 3: Plain complex grains & potatoes (brown rice, white rice, baked/sweet potato, oatmeal)
    tier3 = sorted(
        [
            i for i in pool
            if i['name'] not in seen_names
            and i['_role'] == 'carb'
            and not _is_standalone_bakery(i)
            and i['calories'] >= 110.0
        ],
        key=lambda x: (x['_health_bonus'] + x['protein'] * 0.9 + x['calories'] * 0.03),
        reverse=True,
    )
    for item in tier3:
        anchors.append(item)
        seen_names.add(item['name'])

    return anchors[:8]


def _are_items_culinarily_compatible(p_item: dict, c_item: Optional[dict], s_item: Optional[dict]) -> tuple[bool, float]:
    items = [x for x in (p_item, c_item, s_item) if x is not None]
    if not items:
        return False, 0.0

    # Never pair a composed fruit/cheese/nut salad with rice or pasta
    if s_item and _is_composed_salad(s_item) and c_item:
        c_name = c_item['name'].lower()
        if any(g in c_name for g in ['rice', 'pasta', 'noodle', 'lo mein', 'spaghetti', 'penne', 'mac']):
            return False, -50.0

    # Never pair plain bread/rolls with rice or pasta (double starch)
    if c_item and _is_standalone_bakery(c_item):
        p_name = p_item['name'].lower()
        if any(g in p_name for g in ['pasta', 'spaghetti', 'penne', 'rice', 'pizza', 'burrito', 'sandwich', 'burger']):
            return False, -50.0

    # Never pair two identical grain types together (e.g., brown rice anchor + brown rice base)
    if c_item and p_item['_role'] == 'carb':
        p_name = p_item['name'].lower()
        c_name = c_item['name'].lower()
        if ('rice' in p_name and 'rice' in c_name) or ('potato' in p_name and 'potato' in c_name):
            return False, -50.0

    cuisines = [it['_cuisine'] for it in items if it['_cuisine'] != 'neutral']
    distinct_cuisines = set(cuisines)

    if 'breakfast' in distinct_cuisines and len(distinct_cuisines) > 1:
        return False, -50.0

    incompatible_pairs = [
        {'asian', 'italian'},
        {'latin', 'italian'},
    ]
    for bad_pair in incompatible_pairs:
        if bad_pair.issubset(distinct_cuisines):
            return False, -50.0

    synergy = 0.0

    stations = [it['station'].lower().strip() for it in items]
    if len(stations) >= 2 and len(set(stations)) == 1:
        synergy += 14.0
    elif len(stations) >= 2 and len(set(stations)) < len(stations):
        synergy += 7.0

    if len(cuisines) >= 2 and len(distinct_cuisines) == 1:
        synergy += 10.0

    if c_item and 'rice' in c_item['name'].lower():
        if p_item['_cuisine'] in ('asian', 'latin', 'mediterranean', 'grill_comfort') or _is_plant_veg_anchor(p_item):
            synergy += 6.0

    return True, synergy


def _clean_food_short_name(name: str) -> str:
    cleaned = re.sub(r'\s*\([^)]*\)', '', name).strip()
    return cleaned if len(cleaned) <= 32 else cleaned[:29].rstrip() + '...'


def _generate_combo_title(items: list[dict], cuisine: str) -> str:
    main_name = _clean_food_short_name(items[0]['name'])
    if len(items) == 1:
        return main_name

    second_name = _clean_food_short_name(items[1]['name'])
    if cuisine == 'asian' or any('rice' in it['name'].lower() or 'quinoa' in it['name'].lower() for it in items):
        return f"{main_name} & {second_name} Bowl"
    return f"{main_name} & {second_name}"


def _compute_macro_split(protein_g: float, carbs_g: float, fat_g: float) -> dict:
    p_cal = max(protein_g * 4.0, 0.0)
    c_cal = max(carbs_g * 4.0, 0.0)
    f_cal = max(fat_g * 9.0, 0.0)
    total = max(p_cal + c_cal + f_cal, 1.0)
    p_pct = round((p_cal / total) * 100)
    c_pct = round((c_cal / total) * 100)
    f_pct = max(0, 100 - p_pct - c_pct)
    return {
        'protein_pct': p_pct,
        'carbs_pct': c_pct,
        'fat_pct': f_pct,
    }


def _range_error(val: float, low: float, high: float) -> float:
    if val < low:
        return (low - val) / max(low, 1.0)
    if val > high:
        return (val - high) / max(high, 1.0)
    return 0.0


def build_optimal_plates(
    open_items: list[dict],
    meal_targets: Optional[dict],
    meal_goal: str,
    health_intensity: str,
    dri_enabled: bool = False,
    dietary_filters: Optional[list[str]] = None,
    top_n: int = 3,
) -> list[dict]:
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
        role = _classify_item_role(item)
        if role == 'exclude':
            continue
        enriched = dict(item)
        enriched['_health_bonus'] = health_bonus
        enriched['_health_reason'] = reason
        enriched['_cuisine'] = _detect_cuisine_profile(enriched)
        enriched['_role'] = role
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
        )[:10]

        # Option B: Guarantee strictly seed-oil-free whole-food anchors (eggs, beans, lentils, tofu, paneer, grains)
        if len(proteins) < 3:
            proteins = _build_option_b_anchors(pool, proteins)

        if not proteins:
            continue

        carbs = sorted(
            [i for i in pool if i['_role'] == 'carb'],
            key=lambda x: (x['_health_bonus'] + x['carbs'] * 0.35),
            reverse=True,
        )[:8]
        sides = sorted(
            [i for i in pool if i['_role'] == 'side'],
            key=lambda x: (x['_health_bonus'] + x['protein'] * 0.5 + x['calories'] * 0.04),
            reverse=True,
        )[:8]

        carb_choices = carbs + [None]
        side_choices = sides + [None]

        candidate_combos = []

        for p_item, c_item, s_item in product(proteins, carb_choices, side_choices):
            chosen_names = [p_item['name']]
            if c_item:
                if c_item['name'] in chosen_names:
                    continue
                chosen_names.append(c_item['name'])
            if s_item:
                if s_item['name'] in chosen_names:
                    continue
                chosen_names.append(s_item['name'])

            compatible, synergy_bonus = _are_items_culinarily_compatible(p_item, c_item, s_item)
            if not compatible:
                continue

            main_label = 'Main' if p_item['_role'] == 'protein' else 'Base'
            slots = [(main_label, p_item)]
            if c_item:
                slots.append(('Base', c_item))
            if s_item:
                slots.append(('Side', s_item))

            tot_cal = sum(it['calories'] for _, it in slots)
            tot_pro = sum(it['protein'] for _, it in slots)
            tot_carb = sum(it['carbs'] for _, it in slots)
            tot_fat = sum(it['fat'] for _, it in slots)
            tot_sugar = sum(it['sugar'] for _, it in slots)

            avg_health = sum(it['_health_bonus'] for _, it in slots) / len(slots)
            completeness_bonus = (4.0 if c_item else 0.0) + (4.0 if s_item else 0.0)

            if dri_enabled and per_meal:
                cal_err = abs(tot_cal - per_meal['calories']) / max(per_meal['calories'], 1.0)
                pro_err = abs(tot_pro - per_meal['protein_target']) / max(per_meal['protein_target'], 1.0)
                carb_err = _range_error(tot_carb, per_meal['carbs_min'], per_meal['carbs_max'])
                fat_err = _range_error(tot_fat, per_meal['fat_min'], per_meal['fat_max'])

                pro_shortfall = 0.0
                if tot_pro < per_meal['protein_min']:
                    pro_shortfall = (
                        (per_meal['protein_min'] - tot_pro) / max(per_meal['protein_min'], 1.0)
                    ) * 35.0

                if is_high_protein:
                    macro_penalty = (pro_err * 38.0) + (cal_err * 20.0) + (carb_err * 10.0) + (fat_err * 10.0)
                else:
                    macro_penalty = (cal_err * 22.0) + (pro_err * 24.0) + (carb_err * 14.0) + (fat_err * 14.0)

                total_score = 100.0 + avg_health + synergy_bonus + completeness_bonus - macro_penalty - pro_shortfall
            else:
                protein_yield_bonus = min(tot_pro * 0.4, 18.0)
                satiety_bonus = 6.0 if 320.0 <= tot_cal <= 920.0 else 0.0
                total_score = 100.0 + avg_health + synergy_bonus + completeness_bonus + protein_yield_bonus + satiety_bonus

            candidate_combos.append((total_score, p_item, slots, {
                'calories': round(tot_cal, 1),
                'protein': round(tot_pro, 1),
                'carbs': round(tot_carb, 1),
                'fat': round(tot_fat, 1),
                'sugar': round(tot_sugar, 1),
            }))

        if not candidate_combos:
            continue

        candidate_combos.sort(key=lambda x: x[0], reverse=True)

        selected_combos = []
        used_mains = set()
        used_signatures = set()

        # Pass 1: Pick top combos with distinct primary anchors
        for score_val, p_item, slots, totals_obj in candidate_combos:
            sig = tuple(it['name'] for _, it in slots)
            if p_item['name'] in used_mains or sig in used_signatures:
                continue
            used_mains.add(p_item['name'])
            used_signatures.add(sig)
            selected_combos.append((score_val, p_item, slots, totals_obj))
            if len(selected_combos) >= 3:
                break

        # Pass 2: If fewer than 3 distinct mains exist, fill remaining cards with distinct side/base combinations
        if len(selected_combos) < 3:
            for score_val, p_item, slots, totals_obj in candidate_combos:
                sig = tuple(it['name'] for _, it in slots)
                if sig in used_signatures:
                    continue
                used_signatures.add(sig)
                selected_combos.append((score_val, p_item, slots, totals_obj))
                if len(selected_combos) >= 3:
                    break

        formatted_combos = []
        for idx, (score_val, p_item, slots, totals_obj) in enumerate(selected_combos, start=1):
            slot_items = [it for _, it in slots]
            dominant_cuisine = p_item['_cuisine']
            combo_name = _generate_combo_title(slot_items, dominant_cuisine)
            macro_split = _compute_macro_split(
                totals_obj['protein'], totals_obj['carbs'], totals_obj['fat']
            )

            formatted_items = []
            for role_label, it in slots:
                formatted_items.append({
                    'role': role_label,
                    'station': it['station'],
                    'name': it['name'],
                    'calories': round(it['calories'], 1),
                    'protein': round(it['protein'], 1),
                    'carbs': round(it['carbs'], 1),
                    'fat': round(it['fat'], 1),
                    'allergens': it.get('allergens', []),
                    'used_fallback': it['used_fallback'],
                    'reason': it['_health_reason'],
                })

            formatted_combos.append({
                'combo_id': f"{location.lower().replace(' ', '_')}_{idx}",
                'combo_name': combo_name,
                'station_tag': p_item['station'],
                'score': round(score_val, 1),
                'items': formatted_items,
                'totals': totals_obj,
                'macro_split': macro_split,
            })

        top_combo = formatted_combos[0]
        location_results.append({
            'location': location,
            'hours_status': items[0]['hours_status'],
            'closing_time': items[0]['closing_time'],
            'score': top_combo['score'],
            'combos': formatted_combos,
            'items': top_combo['items'],
            'totals': top_combo['totals'],
        })

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
    now = current_time or get_purdue_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=PURDUE_TZ)

    greeting_title, greeting_sub = _build_time_greeting(now)

    targets = None
    if dri_enabled:
        if not all([sex, age, weight_lbs, height_in, activity_level, meals_per_day]):
            raise ValueError('Please fill in all biometric fields to enable personalized portion sizing.')
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

    open_items = filter_open_locations(all_items, current_time=now)

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
        'timestamp': now.strftime('%Y-%m-%d %I:%M %p'),
        'greeting_title': greeting_title,
        'greeting_sub': greeting_sub,
        'loaded_from_cache': from_cache,
        'dri_enabled': dri_enabled,
        'health_intensity': health_intensity,
        'dietary_filters': dietary_filters or [],
        'targets': targets,
        'open_locations_count': len({i['location'] for i in open_items}),
        'recommendations': recommendations,
    }


def _parse_user_time_input(raw_input: str) -> Optional[datetime]:
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