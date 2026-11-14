import os
import re
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
import requests as rq
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

PURDUE_TZ = ZoneInfo("America/Indiana/Indianapolis")


def get_purdue_now() -> datetime:
    return datetime.now(PURDUE_TZ)


BASE_DIR = os.path.abspath(os.path.dirname(__file__))

DEFAULT_DINING_COURTS = ['Earhart', 'Ford', 'Hillenbrand', 'Wiley', 'Windsor']

DEFAULT_MEAL_WINDOWS = {
    'breakfast': ('07:00:00', '10:00:00'),
    'brunch': ('10:00:00', '14:00:00'),
    'lunch': ('11:00:00', '14:00:00'),
    'late lunch': ('14:00:00', '17:00:00'),
    'dinner': ('17:00:00', '20:30:00'),
}

# ==============================================================================
# CONFIGURABLE 5-PILLAR SCORING WEIGHTS & MODE PROFILES
# ==============================================================================

DEFAULT_SCORING_WEIGHTS = {
    'culinary_compatibility': 0.30,
    'meal_completeness': 0.20,
    'food_quality': 0.20,
    'nutrition_balance': 0.20,
    'variety_presentation': 0.10,
}

MODE_SCORING_PROFILES = {
    'high': {  # Healthiest
        'label': 'Healthiest',
        'weights': {
            'culinary_compatibility': 0.25,
            'meal_completeness': 0.18,
            'food_quality': 0.27,
            'nutrition_balance': 0.20,
            'variety_presentation': 0.10,
        },
        'strict_clean_ingredients': True,
        'target_cal_range': (380.0, 820.0),
        'min_protein_ideal': 26.0,
    },
    'mid': {   # Balanced
        'label': 'Balanced',
        'weights': {
            'culinary_compatibility': 0.30,
            'meal_completeness': 0.20,
            'food_quality': 0.20,
            'nutrition_balance': 0.20,
            'variety_presentation': 0.10,
        },
        'strict_clean_ingredients': False,
        'target_cal_range': (420.0, 920.0),
        'min_protein_ideal': 22.0,
    },
    'low': {   # Yummiest (Estimated Culinary Appeal)
        'label': 'Yummiest',
        'weights': {
            'culinary_compatibility': 0.38,
            'meal_completeness': 0.20,
            'food_quality': 0.22,
            'nutrition_balance': 0.08,
            'variety_presentation': 0.12,
        },
        'strict_clean_ingredients': False,
        'target_cal_range': (400.0, 1050.0),
        'min_protein_ideal': 15.0,
    },
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
    # 1. Filled Sandwiches, Burgers, Wraps & Burritos (checked BEFORE standalone bread/buns)
    ('chicken sandwich', (440.0, 30.0, 42.0, 16.0, 5.0)),
    ('turkey sandwich', (410.0, 28.0, 42.0, 13.0, 5.0)),
    ('ham sandwich', (420.0, 26.0, 42.0, 15.0, 5.0)),
    ('roast beef sandwich', (450.0, 30.0, 42.0, 16.0, 5.0)),
    ('pulled pork sandwich', (480.0, 28.0, 46.0, 18.0, 9.0)),
    ('fish sandwich', (430.0, 24.0, 44.0, 17.0, 5.0)),
    ('veggie burger', (390.0, 18.0, 44.0, 14.0, 5.0)),
    ('cheeseburger', (510.0, 30.0, 38.0, 25.0, 5.0)),
    ('hamburger', (450.0, 27.0, 37.0, 20.0, 5.0)),
    ('burger', (460.0, 27.0, 38.0, 21.0, 5.0)),
    ('panini', (440.0, 24.0, 42.0, 18.0, 4.0)),
    ('banh mi', (490.0, 24.0, 56.0, 17.0, 7.0)),
    ('burrito', (540.0, 24.0, 62.0, 20.0, 4.0)),
    ('quesadilla', (460.0, 22.0, 38.0, 24.0, 3.0)),
    ('gyro', (470.0, 25.0, 44.0, 20.0, 4.0)),
    ('wrap', (430.0, 23.0, 42.0, 17.0, 4.0)),
    ('sandwich', (430.0, 25.0, 42.0, 16.0, 5.0)),

    # 2. Standalone buns, breads, and bakery items
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

    # 3. Desserts, pastries, and baked sweets
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

    # 4. Dips, sauces, and spreads
    ('queso dip', (220.0, 8.0, 10.0, 16.0, 2.0)),
    ('queso', (210.0, 8.0, 9.0, 16.0, 2.0)),
    ('spinach dip', (230.0, 6.0, 11.0, 18.0, 2.0)),
    ('dip', (190.0, 5.0, 12.0, 14.0, 2.0)),
    ('gravy', (90.0, 2.0, 8.0, 5.5, 1.0)),
    ('sauce', (80.0, 1.5, 10.0, 4.0, 5.0)),

    # 5. Composite pasta, bowls, stir-fries, and dressed salads
    ('mac and cheese', (380.0, 15.0, 40.0, 18.0, 5.0)),
    ('macaroni and cheese', (380.0, 15.0, 40.0, 18.0, 5.0)),
    ('lasagna', (390.0, 22.0, 34.0, 18.0, 6.0)),
    ('pizza', (310.0, 13.0, 34.0, 13.0, 4.0)),
    ('grain bowl', (420.0, 18.0, 52.0, 14.0, 5.0)),
    ('rice bowl', (440.0, 22.0, 54.0, 14.0, 6.0)),
    ('burrito bowl', (460.0, 24.0, 50.0, 16.0, 4.0)),
    ('poke bowl', (430.0, 24.0, 52.0, 12.0, 6.0)),
    ('moo shu', (290.0, 24.0, 16.0, 14.0, 6.0)),
    ('stir fry', (280.0, 22.0, 18.0, 13.0, 6.0)),
    ('teriyaki', (290.0, 24.0, 22.0, 10.0, 12.0)),
    ('sweet and sour', (330.0, 18.0, 36.0, 12.0, 18.0)),
    ('general tso', (360.0, 18.0, 38.0, 15.0, 16.0)),
    ('orange chicken', (350.0, 19.0, 36.0, 14.0, 15.0)),
    ('southwest chicken salad', (380.0, 28.0, 20.0, 20.0, 4.0)),
    ('caesar salad', (240.0, 8.0, 12.0, 18.0, 3.0)),
    ('cobb salad', (340.0, 22.0, 12.0, 22.0, 4.0)),
    ('greek salad', (220.0, 7.0, 14.0, 15.0, 5.0)),
    ('chicken salad', (290.0, 20.0, 8.0, 20.0, 4.0)),
    ('tuna salad', (270.0, 19.0, 7.0, 18.0, 3.0)),
    ('egg salad', (280.0, 14.0, 6.0, 22.0, 3.0)),
    ('pasta salad', (230.0, 6.0, 32.0, 9.0, 4.0)),
    ('macaroni salad', (240.0, 5.0, 30.0, 11.0, 5.0)),
    ('potato salad', (220.0, 4.0, 26.0, 11.0, 5.0)),
    ('fruit salad', (85.0, 1.0, 21.0, 0.3, 16.0)),

    # 6. Single proteins & dairy anchors
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

    # 7. Legumes, grains, and complex carbohydrates
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
    ('couscous', (180.0, 6.0, 36.0, 0.5, 0.5)),
    ('sweet potato', (165.0, 3.5, 38.0, 0.3, 7.0)),
    ('potato', (160.0, 3.5, 36.0, 0.3, 1.5)),
    ('pasta', (210.0, 7.0, 42.0, 1.2, 1.5)),
    ('noodle', (210.0, 7.0, 42.0, 1.2, 1.5)),
    ('oatmeal', (160.0, 5.5, 28.0, 3.0, 1.0)),
    ('oat', (160.0, 5.5, 28.0, 3.0, 1.0)),

    # 8. Vegetables and whole fruits
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

# Explicit oil & refined-fat terms (avoids flagging whole sunflower seeds or soybeans/edamame)
SEED_OILS = [
    'canola oil', 'canola',
    'soybean oil', 'soya oil',
    'corn oil',
    'cottonseed oil',
    'sunflower oil', 'high oleic sunflower oil',
    'safflower oil', 'high oleic safflower oil',
    'rapeseed oil', 'grapeseed oil', 'rice bran oil',
    'vegetable oil', 'vegetable shortening',
    'margarine', 'shortening', 'hydrogenated'
]

HIGH_SUGAR_ADDITIVES = [
    'high fructose corn syrup', 'corn syrup', 'cane sugar', 'brown sugar',
    'dextrose', 'maltodextrin', 'invert sugar', 'icing', 'frosting', 'glaze'
]

STRICT_REFINED_SUGAR_INGREDIENTS = [
    'high fructose corn syrup', 'corn syrup', 'invert sugar', 'icing', 'frosting'
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

# Checked BEFORE standalone bakery rules so "Chicken Sandwich on Wheat Bread" is classified as sandwich
SANDWICH_ENTREE_MARKERS = [
    'sandwich', 'burger', 'cheeseburger', 'panini', 'wrap', 'sub',
    'hoagie', 'banh mi', 'gyro', 'melt', 'sliders', 'slider'
]

COMPLETE_ENTREE_MARKERS = [
    'burrito', 'quesadilla', 'enchilada', 'taco', 'tacos', 'pizza',
    'calzone', 'stromboli', 'casserole', 'pot pie', 'shepherd pie',
    'shepherds pie', 'chili', 'stew', 'gumbo', 'jambalaya', 'paella',
    'curry with rice', 'biryani'
]

PASTA_ENTREE_MARKERS = [
    'pasta', 'spaghetti', 'penne', 'fettuccine', 'lasagna', 'ravioli',
    'tortellini', 'linguine', 'mac and cheese', 'macaroni and cheese',
    'lo mein', 'chow mein', 'pad thai', 'ramen', 'udon', 'pho', 'noodle bowl'
]

BOWL_ENTREE_MARKERS = [
    'grain bowl', 'rice bowl', 'burrito bowl', 'poke bowl', 'buddha bowl',
    'power bowl', 'harvest bowl', 'teriyaki bowl', 'fajita bowl', 'bowl'
]

BREAKFAST_ENTREE_MARKERS = [
    'omelet', 'omelette', 'frittata', 'quiche', 'scrambled egg', 'scrambled eggs',
    'breakfast burrito', 'breakfast sandwich', 'egg sandwich', 'eggs benedict',
    'pancake', 'waffle', 'french toast', 'breakfast skillet'
]

STARCH_SALAD_KEYWORDS = [
    'pasta salad', 'macaroni salad', 'potato salad', 'orzo salad',
    'couscous salad', 'tortellini salad', 'noodle salad', 'ramen salad',
    'quinoa salad'
]

FRUIT_SALAD_KEYWORDS = [
    'fruit salad', 'fresh fruit salad', 'mixed fruit salad',
    'berry salad', 'tropical fruit salad', 'melon salad'
]

DESSERT_SALAD_KEYWORDS = [
    'ambrosia salad', 'jello salad', 'gelatin salad', 'marshmallow salad',
    'cookie salad', 'snickers salad', 'dessert salad', 'watergate salad'
]

ENTREE_PROTEIN_SALAD_KEYWORDS = [
    'chicken salad', 'tuna salad', 'egg salad', 'cobb salad', 'chef salad',
    'taco salad', 'steak salad', 'salmon salad', 'shrimp salad', 'turkey salad',
    'fajita salad', 'buffalo chicken', 'southwest chicken', 'chicken caesar'
]

VEGETABLE_KEYWORDS = [
    'broccoli', 'asparagus', 'brussels', 'cauliflower', 'zucchini', 'carrot',
    'carrots', 'green bean', 'green beans', 'spinach', 'kale', 'mixed vegetables',
    'roasted vegetables', 'steamed vegetables', 'peas', 'squash', 'bok choy',
    'cabbage', 'edamame', 'bell pepper', 'peppers', 'mushrooms', 'corn on the cob',
    'sweet corn', 'corn'
]

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

# Plant-based analogs and non-dairy plant milks/butters excluded from meat/dairy keyword regexes
PLANT_BASED_ANALOG_PATTERNS = [
    r'\b(?:plant[- ]based|plant|vegan|vegetarian|meatless|faux|mock|imitation|soy|tofu|seitan|tempeh|cauliflower|jackfruit|mushroom|black\s+bean|chickpea|veggie|impossible|beyond|gardein|morningstar|quorn)\s+(?:chicken|chick\'?n|beef|pork|turkey|ham|bacon|sausage|steak|burger|meatball|pepperoni|salami|chorizo|bratwurst|hot\s+dog|gyro|barbacoa|carnitas|brisket|rib|wing|drumstick|tender|nugget|patty|crab|lobster|shrimp|fish|tuna|salmon|seafood)s?\b',
    r'\b(?:buffalo|bbq|barbecue|honey\s+mustard|korean|teriyaki)\s+cauliflower\s+(?:wing|bite|nugget|tender)s?\b',
    r'\bcauliflower\s+(?:wing|bite|nugget|tender)s?\b',
    r'\bplant[- ]based\b',
]

NON_DAIRY_EXCEPTION_PATTERNS = [
    r'\b(?:coconut|almond|oat|soy|soya|rice|cashew|hemp|pea|flax|macadamia|hazelnut|pistachio|walnut|plant[- ]based|plant|non[- ]?dairy)\s+milks?\b',
    r'\bsoymilks?\b',
    r'\b(?:coconut|oat|soy|plant[- ]based|non[- ]?dairy|vegan)\s+(?:cream|creamer|yogurt|cheese|butter|mozzarella|cheddar|parmesan|feta|ricotta|queso)\b',
    r'\b(?:peanut|almond|cashew|sunflower|seed|apple|pumpkin|cocoa|shea|nut)\s+butters?\b',
    r'\bbutternut\b',
    r'\bcream\s+of\s+(?:tartar|wheat|rice|coconut)\b',
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


def get_daily_menus(
    locations: Optional[list[str]] = None,
    force_refresh: bool = False,
    target_date: Optional[str] = None,
) -> tuple[list[dict], bool]:
    date_str = target_date or get_purdue_now().strftime('%Y-%m-%d')
    cache_path = os.path.join(BASE_DIR, f'purdue_menu_cache_{date_str}.json')
    target_locations = list(locations or DEFAULT_DINING_COURTS)
    allowed_set = set(target_locations)

    if not force_refresh and os.path.exists(cache_path):
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                raw_cache = json.load(f)

            if isinstance(raw_cache, dict):
                cached_date = raw_cache.get('date')
                cached_locs = set(raw_cache.get('locations') or [])
                cached_items = raw_cache.get('items') or []
                if cached_date == date_str and allowed_set.issubset(cached_locs) and cached_items:
                    filtered = [it for it in cached_items if it.get('location') in allowed_set]
                    return hydrate_missing_macros(filtered), True
            elif isinstance(raw_cache, list) and raw_cache:
                filtered = [it for it in raw_cache if it.get('location') in allowed_set]
                if filtered:
                    return hydrate_missing_macros(filtered), True
        except (OSError, ValueError):
            pass

    all_items = []
    with ThreadPoolExecutor(max_workers=len(target_locations) or 1) as executor:
        location_futures = [
            executor.submit(fetch_detailed_purdue_menu, loc, date_str)
            for loc in target_locations
        ]
        for future in as_completed(location_futures):
            all_items.extend(future.result())

    if all_items:
        try:
            envelope = {
                'date': date_str,
                'locations': target_locations,
                'items': all_items,
            }
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(envelope, f, indent=2)
        except OSError:
            pass

    return hydrate_missing_macros(all_items), False


# ==============================================================================
# MODULE 2: EXPANDED USDA DRI & SINGLE-MEAL MACRO CALCULATOR (WITH AGE SAFETY)
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
    is_minor = int(age) < 18

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
    safety_note = (
        'General dining portion estimate only, not medical or clinical nutrition advice.'
    )

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
        if is_minor:
            daily_calories = maintenance_calories
            safety_note = (
                'Calorie deficits are disabled for users under 18; showing balanced '
                'maintenance portions. Consult a healthcare provider for personalized guidance.'
            )
        else:
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
        daily_carbs_min = 90.0 if is_minor else 60.0
        daily_carbs_target = (daily_calories * (0.28 if is_minor else 0.20)) / 4.0
        daily_carbs_max = (daily_calories * (0.35 if is_minor else 0.26)) / 4.0
        daily_fat_min = (daily_calories * 0.28) / 9.0
        daily_fat_target = (daily_calories * 0.35) / 9.0
        daily_fat_max = (daily_calories * 0.44) / 9.0

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
        'is_minor_safeguarded': is_minor,
        'disclaimer': safety_note,
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
            seconds_left = (end_dt - now).total_seconds()
            updated = dict(item)
            if seconds_left <= 1800:
                updated['hours_status'] = f'Closes at {formatted_end}'
            else:
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
# MODULE 4: DIETARY FILTERS, INGREDIENT CERTAINTY & MODE FOOD QUALITY
# ==============================================================================

def _is_special_order_item(item: dict) -> bool:
    station_lower = (item.get('station') or '').lower().strip()
    name_lower = (item.get('name') or '').lower().strip()

    if any(marker in station_lower for marker in SPECIAL_ORDER_STATION_MARKERS):
        return True
    if any(marker in name_lower for marker in SPECIAL_ORDER_ITEM_MARKERS):
        return True
    return False


def _assess_ingredient_certainty(item: dict) -> str:
    """
    Distinguishes verified ingredient transparency from unknown N/A metadata:
      - 'verified': Explicit ingredient list provided by Purdue HFS API
      - 'verified_whole_food': Single-ingredient whole food with N/A metadata
      - 'unknown': Missing/N/A ingredient list on a multi-component dish
    """
    ing_raw = (item.get('ingredients') or '').strip()
    if ing_raw and ing_raw.upper() != 'N/A':
        return 'verified'
    if _is_verified_na_whole_food(item):
        return 'verified_whole_food'
    return 'unknown'


def _sanitize_plant_based_text(text: str) -> str:
    """Strips plant-based meat/poultry/seafood analog phrases before meat keyword regexes."""
    cleaned = text
    for pat in PLANT_BASED_ANALOG_PATTERNS:
        cleaned = re.sub(pat, ' ', cleaned, flags=re.IGNORECASE)
    return cleaned


def _sanitize_non_dairy_text(text: str) -> str:
    """Strips non-dairy plant milks and nut/plant butters before dairy keyword regexes."""
    cleaned = text
    for pat in NON_DAIRY_EXCEPTION_PATTERNS:
        cleaned = re.sub(pat, ' ', cleaned, flags=re.IGNORECASE)
    return cleaned


def _passes_dietary_filters(item: dict, dietary_filters: list[str]) -> bool:
    if not dietary_filters:
        return True

    active = {f.strip().lower() for f in dietary_filters if f}
    allergens = {str(a).strip().lower() for a in (item.get('allergens') or [])}
    name_lower = (item.get('name') or '').lower()
    ing_raw = (item.get('ingredients') or '').strip()
    ing_lower = ing_raw.lower()
    combined = f'{name_lower} {ing_lower}'
    has_verified_ing = bool(ing_raw and ing_raw.upper() != 'N/A')

    meat_check_text = _sanitize_plant_based_text(combined)
    dairy_check_text = _sanitize_non_dairy_text(combined)

    allergen_rules = {
        'gluten-free': {
            'api_tags': {'gluten', 'wheat'},
            'keywords': ['wheat', 'barley', 'rye', 'semolina', 'flour', 'bread', 'pasta', 'tortilla', 'crouton', 'panko', 'bagel', 'muffin', 'pancake', 'pita'],
            'safe_override': ['gluten-free', 'gluten free', 'gf '],
            'text_source': combined,
        },
        'dairy-free': {
            'api_tags': {'milk', 'dairy'},
            'keywords': ['milk', 'cheese', 'butter', 'cream', 'whey', 'casein', 'yogurt', 'mozzarella', 'cheddar', 'parmesan', 'feta', 'ricotta', 'queso'],
            'safe_override': ['dairy-free', 'dairy free', 'vegan', 'violife'],
            'text_source': dairy_check_text,
        },
        'egg-free': {
            'api_tags': {'eggs', 'egg'},
            'keywords': ['egg', 'mayonnaise', 'aioli'],
            'safe_override': ['egg-free', 'egg free', 'vegan'],
            'text_source': combined,
        },
        'soy-free': {
            'api_tags': {'soy', 'soybeans'},
            'keywords': ['soy', 'soybean', 'tofu', 'edamame', 'tamari', 'teriyaki', 'miso'],
            'safe_override': ['soy-free', 'soy free'],
            'text_source': combined,
        },
        'peanut-free': {
            'api_tags': {'peanuts', 'peanut'},
            'keywords': ['peanut', 'kung pao', 'reese'],
            'safe_override': ['peanut-free', 'peanut free'],
            'text_source': combined,
        },
        'tree-nut-free': {
            'api_tags': {'tree nuts', 'tree nut', 'nuts'},
            'keywords': ['almond', 'walnut', 'pecan', 'cashew', 'pistachio', 'hazelnut', 'macadamia', 'pine nut', 'coconut'],
            'safe_override': ['nut-free', 'nut free'],
            'text_source': combined,
        },
        'shellfish-free': {
            'api_tags': {'shellfish', 'crustacean shellfish'},
            'keywords': ['shrimp', 'crab', 'lobster', 'clam', 'mussel', 'oyster', 'scallop', 'crawfish'],
            'safe_override': [],
            'text_source': meat_check_text,
        },
        'fish-free': {
            'api_tags': {'fish'},
            'keywords': ['fish', 'salmon', 'tuna', 'cod', 'tilapia', 'anchovy', 'anchovies', 'pollock', 'haddock', 'halibut', 'trout', 'mahi', 'catfish', 'sardine', 'worcestershire'],
            'safe_override': ['fish-free', 'fish free', 'vegan', 'vegetarian'],
            'text_source': meat_check_text,
        },
        'sesame-free': {
            'api_tags': {'sesame', 'sesame seeds'},
            'keywords': ['sesame', 'tahini', 'hummus', 'halvah', 'benne', 'gomashio'],
            'safe_override': ['sesame-free', 'sesame free'],
            'text_source': combined,
        },
    }

    for filter_key, rule in allergen_rules.items():
        if filter_key not in active:
            continue

        if allergens & rule['api_tags']:
            return False

        # Never treat composite dishes with missing ingredient & allergen metadata as guaranteed allergen-safe
        if not has_verified_ing and not allergens and not _is_verified_na_whole_food(item):
            if not any(safe in name_lower for safe in rule['safe_override']):
                return False

        if not any(safe in name_lower for safe in rule['safe_override']):
            target_text = rule['text_source']
            if any(re.search(rf'\b{re.escape(kw)}s?\b', target_text) for kw in rule['keywords']):
                return False

    if 'vegetarian' in active:
        is_veg = item.get('is_vegetarian')
        if is_veg is False:
            return False
        if is_veg is None:
            if any(re.search(rf'\b{re.escape(m)}s?\b', meat_check_text) for m in MEAT_SEAFOOD_KEYWORDS):
                return False

    if 'vegan' in active:
        is_vegan = item.get('is_vegan')
        if is_vegan is False or item.get('is_vegetarian') is False:
            return False
        if allergens & {'milk', 'dairy', 'eggs', 'egg', 'shellfish', 'crustacean shellfish', 'fish'}:
            return False
        if is_vegan is None and 'vegan' not in name_lower:
            if any(re.search(rf'\b{re.escape(m)}s?\b', meat_check_text) for m in MEAT_SEAFOOD_KEYWORDS):
                return False
            if any(re.search(rf'\b{re.escape(a)}s?\b', dairy_check_text) for a in ANIMAL_BYPRODUCT_KEYWORDS):
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

    if any(ent in name_lower for ent in SANDWICH_ENTREE_MARKERS + COMPLETE_ENTREE_MARKERS):
        return False

    return any(re.search(rf'\b{re.escape(ds)}s?\b', name_lower) for ds in DIP_SAUCE_KEYWORDS)


def _is_standalone_bakery(item: dict) -> bool:
    """
    Recognizes standalone bakery items (buns, rolls, slices of bread, bagels)
    ONLY AFTER verifying the item is not a filled sandwich, burger, wrap, or entree.
    """
    name_lower = (item.get('name') or '').lower().strip()

    if any(re.search(rf'\b{re.escape(m)}\b', name_lower) for m in SANDWICH_ENTREE_MARKERS + COMPLETE_ENTREE_MARKERS + BREAKFAST_ENTREE_MARKERS):
        return False

    return any(re.search(rf'\b{re.escape(bk)}\b', name_lower) for bk in STANDALONE_BAKERY_KEYWORDS)


def _is_verified_na_whole_food(item: dict) -> bool:
    name_lower = item['name'].lower().strip()

    if _is_whole_fruit(name_lower):
        return True

    if 'cottage cheese' in name_lower or 'paneer' in name_lower:
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
    Evaluates individual item eligibility and returns (allowed, quality_score_0_to_100, explanation).
    Distinct logic across High (Healthiest), Mid (Balanced), and Low (Yummiest).
    """
    tier = health_intensity.strip().lower()
    name_lower = item['name'].lower().strip()
    ing_raw = (item['ingredients'] or '').strip()
    ing_lower = ing_raw.lower()
    combined_text = f'{name_lower} {ing_lower}'
    certainty = _assess_ingredient_certainty(item)

    if _is_special_order_item(item):
        return False, 0.0, 'Excluded: custom ticket'
    if name_lower in STATION_HEADER_NAMES:
        return False, 0.0, 'Excluded: station header'
    if _is_dip_or_condiment(item):
        return False, 0.0, 'Excluded: standalone dip, sauce, or condiment'
    if _is_standalone_bakery(item) and any(b in name_lower for b in ['hamburger bun', 'hot dog bun', 'sesame bun', 'wheat bun', 'white bun', 'bun', 'buns']):
        return False, 0.0, 'Excluded: standalone bun'

    zero_cal_items = ('water', 'ice', 'salt', 'black pepper', 'tea', 'black coffee', 'mustard', 'vinegar')
    if any(z == name_lower or f' {z}' in name_lower for z in zero_cal_items):
        return False, 0.0, 'Negligible macro contribution'

    has_seed_oil = any(
        re.search(rf'\b{re.escape(oil)}s?\b', combined_text) for oil in SEED_OILS
    )
    has_sugar_marker = any(s in combined_text for s in HIGH_SUGAR_ADDITIVES)
    has_strict_refined_ing = any(s in ing_lower for s in STRICT_REFINED_SUGAR_INGREDIENTS)
    is_deep_fried = any(f in combined_text for f in DEEP_FRIED_MARKERS)
    has_artificial = any(a in combined_text for a in ARTIFICIAL_ADDITIVES)
    is_dessert = any(d in name_lower for d in DESSERT_KEYWORDS) or any(ds in name_lower for ds in DESSERT_SALAD_KEYWORDS)
    whole_fruit = _is_whole_fruit(name_lower) or any(fs in name_lower for fs in FRUIT_SALAD_KEYWORDS)

    # Gate high-sugar triggers against actual gram threshold (> 8.0g) rather than title substrings alone
    has_high_sugar = (not whole_fruit) and (
        item['sugar'] > 8.0
        or (has_sugar_marker and item['sugar'] > 8.0)
        or has_strict_refined_ing
    )

    if tier == 'high':
        # Healthiest: Strict seed-oil-free, dye-free, deep-fry-free, added-sugar-free
        if certainty == 'unknown':
            return False, 0.0, 'Excluded from Healthiest: unverified ingredients'
        if has_seed_oil:
            return False, 0.0, 'Excluded: contains seed oils'
        if is_deep_fried:
            return False, 0.0, 'Excluded: deep-fried'
        if has_artificial:
            return False, 0.0, 'Excluded: artificial dyes or preservatives'
        if is_dessert:
            return False, 0.0, 'Excluded: dessert'
        if has_high_sugar:
            return False, 0.0, 'Excluded: added sugar (>8g)'

        score = 68.0
        if certainty == 'verified':
            score += 10.0
        else:
            score += 5.0
        if 'olive oil' in combined_text or 'butter' in combined_text or 'avocado oil' in combined_text:
            score += 8.0
        score += min(item['protein'] * 0.45, 14.0)
        reason = (
            'Verified seed-oil-free whole food'
            if certainty == 'verified'
            else 'Whole food staple (N/A ingredient list)'
        )
        return True, round(min(score, 100.0), 1), reason

    elif tier == 'mid':
        # Balanced: Allows everyday dining staples, blocks deep-fried/desserts/artificial dyes
        if is_deep_fried:
            return False, 0.0, 'Excluded: deep-fried'
        if has_artificial:
            return False, 0.0, 'Excluded: artificial additives'
        if is_dessert:
            return False, 0.0, 'Excluded: dessert'
        if (has_high_sugar and item['protein'] < 10.0) or (item['sugar'] > 18.0 and not whole_fruit):
            return False, 0.0, 'Excluded: high sugar glaze'

        score = 58.0
        if certainty == 'verified' and not has_seed_oil:
            score += 18.0
            reason = 'Verified seed-oil-free whole food'
        elif certainty == 'unknown':
            score += 4.0
            reason = 'Dining court staple (unverified ingredients)'
        else:
            score += 9.0
            reason = 'Balanced dining court staple'
        score += min(item['protein'] * 0.35, 14.0)
        return True, round(min(score, 100.0), 1), reason

    else:
        # 'low' -> Yummiest: Evaluates culinary appeal, flavor richness, and recognizable dishes
        if is_dessert:
            return False, 0.0, 'Excluded: standalone dessert'

        appeal = 52.0
        flavor_markers = [
            'grilled', 'roasted', 'seared', 'braised', 'smoked', 'marinated',
            'teriyaki', 'parmesan', 'pesto', 'marinara', 'alfredo', 'garlic',
            'herb', 'honey', 'chipotle', 'carnitas', 'barbacoa', 'carne asada',
            'tikka', 'masala', 'curry', 'sesame', 'ginger', 'bourbon', 'bbq',
            'barbecue', 'buffalo', 'lemon', 'balsamic', 'glazed', 'crispy',
            'baked', 'cheddar', 'mozzarella', 'feta', 'bacon', 'avocado'
        ]
        matched_flavors = sum(1 for fm in flavor_markers if fm in name_lower)
        appeal += min(matched_flavors * 9.0, 32.0)

        if any(m in name_lower for m in SANDWICH_ENTREE_MARKERS + COMPLETE_ENTREE_MARKERS + PASTA_ENTREE_MARKERS + BOWL_ENTREE_MARKERS):
            appeal += 10.0
        if certainty == 'verified':
            appeal += 4.0

        reason = (
            'Estimated culinary appeal: rich flavor profile & preparation'
            if matched_flavors > 0
            else 'Estimated culinary appeal: classic campus favorite'
        )
        return True, round(min(appeal, 100.0), 1), reason


# ==============================================================================
# MODULE 5: GRANULAR FOOD CLASSIFICATION, CULINARY COMPATIBILITY & SCORING
# ==============================================================================

def _detect_cuisine_profile(item: dict) -> str:
    text = f"{item.get('name', '')} {item.get('station', '')}".lower()

    if any(k in text for k in [
        'teriyaki', 'stir fry', 'stir-fry', 'jasmine', 'basmati', 'fried rice',
        'lo mein', 'chow mein', 'noodle', 'dumpling', 'potsticker', 'edamame',
        'sesame', 'ginger', 'tofu', 'curry', 'tikka', 'masala', 'naan',
        'banh mi', 'pho', 'ramen', 'miso', 'general tso', 'orange chicken',
        'kung pao', 'moo shu', 'bulgogi', 'kimchi', 'bok choy', 'one world', 'asian'
    ]):
        return 'asian'

    if any(k in text for k in [
        'taco', 'burrito', 'fajita', 'carnitas', 'barbacoa', 'carne asada',
        'quesadilla', 'enchilada', 'cilantro lime', 'black bean', 'pinto bean',
        'spanish rice', 'mexican rice', 'plantain', 'tortilla', 'chipotle',
        'elote', 'chorizo', 'poblano', 'latin', 'salsa'
    ]):
        return 'latin'

    if any(k in text for k in [
        'pasta', 'marinara', 'alfredo', 'spaghetti', 'penne', 'fettuccine',
        'lasagna', 'ravioli', 'tortellini', 'parmesan', 'mozzarella', 'pesto',
        'meatball', 'italian', 'garlic bread', 'breadstick', 'focaccia',
        'risotto', 'bruschetta', 'pizza', 'flatbread', 'caprese', '2mato'
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
        'burger', 'cheeseburger', 'grilled chicken', 'steak', 'roast beef',
        'meatloaf', 'pork chop', 'pork loin', 'barbecue', 'bbq', 'pulled pork',
        'mac and cheese', 'mashed potato', 'roasted potato', 'baked potato',
        'sweet potato', 'corn on the cob', 'coleslaw', 'cornbread', 'turkey',
        'grill', 'homestyle', 'comfort'
    ]):
        return 'grill_comfort'

    return 'neutral'


def _detect_cooking_method(item: dict) -> str:
    text = f"{item.get('name', '')} {item.get('ingredients', '')}".lower()
    if any(k in text for k in ['grilled', 'charbroiled', 'seared']):
        return 'grilled'
    if any(k in text for k in ['roasted', 'baked', 'oven']):
        return 'roasted_baked'
    if any(k in text for k in ['steamed', 'boiled', 'poached']):
        return 'steamed'
    if any(k in text for k in ['stir fry', 'stir-fry', 'sauteed', 'sautéed', 'pan']):
        return 'sauteed'
    if any(k in text for k in ['braised', 'slow cooked', 'pulled', 'stewed']):
        return 'braised'
    if any(k in text for k in ['crispy', 'fried', 'breaded', 'battered']):
        return 'crispy'
    return 'fresh_prepared'


def _detect_flavor_tags(item: dict) -> set[str]:
    text = f"{item.get('name', '')} {item.get('ingredients', '')}".lower()
    tags = set()
    flavor_map = {
        'teriyaki_sweet_savory': ['teriyaki', 'honey', 'bourbon', 'sweet and sour', 'orange', 'glaze'],
        'garlic_herb': ['garlic', 'herb', 'oregano', 'basil', 'rosemary', 'thyme', 'pesto', 'lemon'],
        'tomato_savory': ['marinara', 'tomato', 'parmesan', 'bolognese', 'lasagna'],
        'creamy_rich': ['alfredo', 'cream', 'creamy', 'cheddar', 'mozzarella', 'cheese', 'mac and cheese'],
        'smoky_bbq': ['bbq', 'barbecue', 'smoked', 'chipotle', 'pulled pork'],
        'spiced_bold': ['taco', 'fajita', 'carnitas', 'barbacoa', 'carne asada', 'curry', 'tikka', 'masala', 'cajun', 'buffalo'],
        'clean_neutral': ['plain', 'steamed', 'jasmine', 'basmati', 'brown rice', 'white rice', 'quinoa', 'baked potato'],
    }
    for tag, keywords in flavor_map.items():
        if any(kw in text for kw in keywords):
            tags.add(tag)
    return tags


def _extract_main_ingredient_key(item: dict) -> str:
    name_lower = item['name'].lower()
    ingredients_order = [
        'chicken', 'turkey', 'beef', 'steak', 'burger', 'pork', 'ham', 'bacon',
        'sausage', 'salmon', 'tilapia', 'cod', 'shrimp', 'tuna', 'tofu',
        'tempeh', 'paneer', 'egg', 'black bean', 'chickpea', 'lentil',
        'quinoa', 'pasta', 'spaghetti', 'lasagna', 'pizza', 'burrito'
    ]
    for ing in ingredients_order:
        if re.search(rf'\b{re.escape(ing)}(?:s|es)?\b', name_lower):
            return ing
    return _clean_food_short_name(item['name']).lower()


def _is_composed_salad(item: dict) -> bool:
    """
    Identifies leafy/vegetable composed salads (Caesar Salad, Greek Salad, Garden Salad)
    that can serve as standalone salad mains or foundations for lean proteins,
    while excluding fruit salads, starch/pasta salads, dessert salads, and complete
    protein-topped entree salads.
    """
    name_lower = (item.get('name') or '').lower().strip()
    if 'salad' not in name_lower:
        return False

    if any(k in name_lower for k in (
        STARCH_SALAD_KEYWORDS
        + FRUIT_SALAD_KEYWORDS
        + DESSERT_SALAD_KEYWORDS
        + ENTREE_PROTEIN_SALAD_KEYWORDS
    )):
        return False

    protein_in_salad_title = [
        'chicken', 'turkey', 'beef', 'steak', 'pork', 'ham', 'bacon',
        'salmon', 'tuna', 'shrimp', 'crab', 'lobster', 'fish', 'tofu'
    ]
    if any(re.search(rf'\b{re.escape(p)}(?:s|es)?\b', name_lower) for p in protein_in_salad_title):
        return False

    return True


def _is_plant_veg_anchor(item: dict) -> bool:
    name_lower = item['name'].lower().strip()
    return any(re.search(rf'\b{re.escape(kw)}(?:s|es)?\b', name_lower) for kw in PLANT_VEG_ANCHOR_KEYWORDS)


def classify_food_item(item: dict) -> str:
    """
    Granular food role classifier using item name, ingredients, and macro structure.
    Returns one of:
      - 'exclude'
      - 'sandwich'        (complete hand-held filled sandwich/burger/wrap/gyro)
      - 'complete_entree' (burrito, quesadilla, taco plate, pizza, casserole, chili)
      - 'pasta_entree'    (pasta dish, lasagna, lo mein, mac & cheese, ramen)
      - 'bowl'            (grain bowl, rice bowl, burrito bowl, poke bowl)
      - 'composed_salad'  (caesar salad, greek salad, garden salad)
      - 'breakfast_entree'(omelet, scrambled eggs, pancakes, waffles, breakfast sandwich)
      - 'protein_entree'  (standalone meat, fish, tofu, paneer, eggs, or complete protein entree salad)
      - 'carb_base'       (rice, quinoa, couscous, potatoes, beans, pasta/macaroni salad, standalone bread/roll)
      - 'vegetable'       (broccoli, asparagus, green beans, spinach, roasted veg)
      - 'side'            (whole fruit, fruit salad, cottage cheese, yogurt, light side)
    """
    name_lower = (item.get('name') or '').lower().strip()
    ing_lower = (item.get('ingredients') or '').lower()

    if (
        name_lower in STATION_HEADER_NAMES
        or any(d in name_lower for d in DESSERT_KEYWORDS)
        or any(ds in name_lower for ds in DESSERT_SALAD_KEYWORDS)
        or _is_dip_or_condiment(item)
    ):
        return 'exclude'

    # 0. Explicit Salad Sub-Classifications (before pasta/carb rules)
    if 'salad' in name_lower:
        if any(fs in name_lower for fs in FRUIT_SALAD_KEYWORDS):
            return 'side'
        if any(ss in name_lower for ss in STARCH_SALAD_KEYWORDS):
            return 'carb_base'
        if any(es in name_lower for es in ENTREE_PROTEIN_SALAD_KEYWORDS):
            return 'protein_entree'
        if _is_composed_salad(item):
            return 'composed_salad'
        # Salads with explicit protein in title (e.g., "Southwest Chicken Salad", "Grilled Salmon Salad")
        return 'protein_entree'

    # 1. Filled Sandwiches & Burgers (MUST precede standalone bread/bun rules)
    if any(re.search(rf'\b{re.escape(m)}\b', name_lower) for m in SANDWICH_ENTREE_MARKERS):
        if 'breakfast' in name_lower or 'egg' in name_lower:
            return 'breakfast_entree'
        return 'sandwich'

    # 2. Breakfast Entrees
    if any(re.search(rf'\b{re.escape(m)}\b', name_lower) for m in BREAKFAST_ENTREE_MARKERS):
        return 'breakfast_entree'

    # 3. Complete Entrees (burrito, pizza, taco, casserole, etc.)
    if any(re.search(rf'\b{re.escape(m)}\b', name_lower) for m in COMPLETE_ENTREE_MARKERS):
        return 'complete_entree'

    # 4. Bowls (grain bowl, rice bowl, burrito bowl, etc.)
    if any(re.search(rf'\b{re.escape(m)}\b', name_lower) for m in BOWL_ENTREE_MARKERS):
        return 'bowl'

    # 5. Pasta Entrees
    if any(re.search(rf'\b{re.escape(m)}\b', name_lower) for m in PASTA_ENTREE_MARKERS):
        return 'pasta_entree'

    # 6. Standalone Bakery (only after sandwich/complete entree overrides)
    if _is_standalone_bakery(item):
        if any(b in name_lower for b in ['hamburger bun', 'hot dog bun', 'bun', 'buns']):
            return 'exclude'
        return 'carb_base'

    # 7. Vegetables
    if any(re.search(rf'\b{re.escape(v)}\b', name_lower) for v in VEGETABLE_KEYWORDS):
        if 'edamame' in name_lower:
            return 'protein_entree'
        return 'vegetable'

    # 8. Whole Fruits
    if _is_whole_fruit(name_lower):
        return 'side'

    # 9. Protein Entrees (checked via protein keywords + macro profile + ingredient metadata)
    entree_protein_hints = [
        'chicken', 'beef', 'steak', 'pork', 'salmon', 'fish', 'shrimp',
        'turkey', 'tofu', 'tempeh', 'seitan', 'egg', 'meatball',
        'carnitas', 'barbacoa', 'tilapia', 'cod', 'ham', 'tuna',
        'paneer', 'cottage cheese', 'greek yogurt'
    ]
    has_protein_word = any(
        re.search(rf'\b{re.escape(h)}(?:s|es)?\b', name_lower)
        for h in entree_protein_hints
    )
    has_protein_ing = any(
        re.search(rf'\b{re.escape(h)}\b', ing_lower)
        for h in ['chicken breast', 'beef', 'pork', 'salmon', 'turkey', 'tofu', 'egg']
    )

    if item['protein'] >= 12.0 and (
        item['protein'] >= item['carbs'] * 0.65
        or has_protein_word
        or has_protein_ing
    ):
        return 'protein_entree'

    # 10. Carbohydrate / Grain / Legume Bases
    if item['carbs'] >= 15.0 and item['carbs'] > item['protein']:
        return 'carb_base'

    return 'side'


def _build_option_b_anchors(pool: list[dict], existing_proteins: list[dict]) -> list[dict]:
    """
    Option B Fallback: Ensures strictly seed-oil-free whole-food anchors are available
    when a dining court has fewer than 3 traditional meat entrees.
    """
    anchors = list(existing_proteins)
    seen_names = {p['name'] for p in anchors}

    tier1 = sorted(
        [
            i for i in pool
            if i['name'] not in seen_names
            and not _is_standalone_bakery(i)
            and i['_role'] != 'composed_salad'
            and (i['protein'] >= 6.0 and any(k in i['name'].lower() for k in ['egg', 'tofu', 'paneer', 'cottage cheese', 'greek yogurt', 'edamame']))
        ],
        key=lambda x: (x['_quality_score'] + x['protein'] * 1.1),
        reverse=True,
    )
    for item in tier1:
        anchors.append(item)
        seen_names.add(item['name'])

    if len(anchors) >= 3:
        return anchors[:8]

    tier2 = sorted(
        [
            i for i in pool
            if i['name'] not in seen_names
            and not _is_standalone_bakery(i)
            and i['_role'] != 'composed_salad'
            and (_is_plant_veg_anchor(i) or (i['protein'] >= 6.0 and i['calories'] >= 100.0))
        ],
        key=lambda x: (x['_quality_score'] + x['protein'] * 1.1 + x['calories'] * 0.03),
        reverse=True,
    )
    for item in tier2:
        anchors.append(item)
        seen_names.add(item['name'])

    if len(anchors) >= 2:
        return anchors[:8]

    tier3 = sorted(
        [
            i for i in pool
            if i['name'] not in seen_names
            and i['_role'] == 'carb_base'
            and not _is_standalone_bakery(i)
            and i['calories'] >= 110.0
        ],
        key=lambda x: (x['_quality_score'] + x['protein'] * 0.9 + x['calories'] * 0.03),
        reverse=True,
    )
    for item in tier3:
        anchors.append(item)
        seen_names.add(item['name'])

    return anchors[:8]


def evaluate_culinary_compatibility(
    slots: list[tuple[str, dict]],
    template_name: str,
) -> tuple[bool, float, list[str]]:
    """
    Positive, multi-dimensional culinary compatibility engine (returns 0..100 score).
    """
    items = [it for _, it in slots]
    if not items:
        return False, 0.0, []

    roles = [it['_role'] for it in items]
    names_lower = [it['name'].lower() for it in items]

    # 1. Hard structural guards
    complete_roles = {'sandwich', 'complete_entree', 'pasta_entree', 'bowl', 'breakfast_entree'}
    if sum(1 for r in roles if r in complete_roles) > 1:
        return False, 0.0, ['Rejected: multiple complete entrees']

    # Reject redundant starch bases (e.g., pasta + rice, sandwich + bread, rice + rice)
    starch_count = 0
    for it in items:
        n = it['name'].lower()
        r = it['_role']
        if r in ('pasta_entree', 'sandwich', 'complete_entree', 'bowl') or any(
            g in n for g in ['rice', 'pasta', 'noodle', 'spaghetti', 'penne', 'potato', 'bread', 'roll', 'tortilla', 'naan', 'pita', 'couscous', 'quinoa', 'macaroni']
        ):
            starch_count += 1
    if starch_count > 1:
        return False, 0.0, ['Rejected: redundant carbohydrate/starch components']

    # Reject any salad paired with heavy hot rice/pasta starches
    has_any_salad = 'composed_salad' in roles or any('salad' in n for n in names_lower)
    if has_any_salad and any(
        any(g in n for g in ['rice', 'pasta', 'noodle', 'spaghetti', 'penne', 'mac'])
        for n in names_lower
    ):
        return False, 0.0, ['Rejected: salad paired with heavy starch']

    # 2. Cuisine compatibility check
    cuisines = [it['_cuisine'] for it in items if it['_cuisine'] != 'neutral']
    distinct_cuisines = set(cuisines)

    if 'breakfast' in distinct_cuisines and len(distinct_cuisines) > 1:
        return False, 0.0, ['Rejected: breakfast mixed with non-breakfast items']

    incompatible_pairs = [
        {'asian', 'italian'},
        {'latin', 'italian'},
        {'asian', 'latin'},
    ]
    for bad_pair in incompatible_pairs:
        if bad_pair.issubset(distinct_cuisines):
            return False, 0.0, ['Rejected: conflicting cuisine profiles']

    # Single-item complete entree or standalone salad main baseline
    if len(items) == 1:
        single_role = items[0]['_role']
        single_name = items[0]['name'].lower()
        if single_role in ('complete_entree', 'bowl', 'sandwich', 'pasta_entree', 'breakfast_entree'):
            return True, 78.0, [f'Self-contained {single_role.replace("_", " ")}']
        if single_role == 'composed_salad' or 'salad' in single_name:
            return True, 76.0, ['Standalone composed salad main']
        return True, 64.0, ['Single-component plate']

    # 3. Positive Compatibility Scoring
    score = 50.0
    reasons: list[str] = []

    # A. Cuisine alignment
    if len(cuisines) >= 2 and len(distinct_cuisines) == 1:
        score += 18.0
        reasons.append(f'Cohesive {cuisines[0]} cuisine pairing')
    elif len(distinct_cuisines) == 1 and 'neutral' in [it['_cuisine'] for it in items]:
        score += 11.0
        reasons.append('Clean neutral accompaniment')
    elif len(distinct_cuisines) == 0:
        score += 9.0

    # B. Recognizable classic meal pairing bonuses
    joined_names = ' | '.join(names_lower)
    classic_pairings = [
        (['teriyaki', 'orange chicken', 'general tso', 'stir fry', 'bulgogi', 'curry', 'tikka'], ['jasmine rice', 'white rice', 'brown rice', 'basmati rice', 'rice'], 16.0, 'Classic Asian protein & steamed rice pairing'),
        (['chicken parmesan', 'meatball', 'italian chicken', 'bolognese', 'marinara'], ['pasta', 'spaghetti', 'penne', 'fettuccine', 'broccoli', 'green beans'], 15.0, 'Classic Italian entree pairing'),
        (['taco', 'carnitas', 'barbacoa', 'carne asada', 'fajita', 'chorizo'], ['spanish rice', 'mexican rice', 'cilantro lime', 'black bean', 'pinto bean'], 16.0, 'Traditional Latin plate pairing'),
        (['grilled chicken', 'steak', 'salmon', 'pork loin', 'turkey'], ['roasted potato', 'sweet potato', 'mashed potato', 'quinoa', 'asparagus', 'broccoli', 'green beans', 'pasta salad', 'potato salad'], 14.0, 'Classic grill & vegetable/starch balance'),
        (['gyro', 'shawarma', 'lemon herb', 'mediterranean', 'greek'], ['couscous', 'quinoa', 'chickpea', 'garbanzo', 'greek salad'], 15.0, 'Mediterranean flavor pairing'),
        (['burger', 'cheeseburger', 'sandwich', 'panini', 'wrap'], ['fruit', 'apple', 'berries', 'watermelon', 'broccoli', 'salad', 'sweet potato'], 12.0, 'Balanced sandwich/burger & crisp side'),
        (['scrambled', 'omelet', 'frittata', 'pancake', 'waffle'], ['bacon', 'sausage', 'fruit', 'berries', 'banana', 'oatmeal'], 14.0, 'Classic breakfast pairing'),
    ]
    for anchor_kws, partner_kws, bonus_pts, label in classic_pairings:
        if any(ak in joined_names for ak in anchor_kws) and any(pk in joined_names for pk in partner_kws):
            score += bonus_pts
            reasons.append(label)
            break

    # C. Flavor & sauce profile harmony
    flavor_sets = [it['_flavors'] for it in items if it['_flavors']]
    if len(flavor_sets) >= 2:
        shared_flavors = flavor_sets[0].intersection(*flavor_sets[1:])
        if shared_flavors:
            score += 8.0
            reasons.append('Shared flavor notes')
        elif any('clean_neutral' in fs for fs in flavor_sets):
            score += 6.0

    # D. Texture & cooking-method contrast
    methods = {it['_method'] for it in items}
    if len(methods) >= 2:
        score += 7.0
        reasons.append('Complementary cooking textures')

    # E. Modest same-station convenience bonus
    stations = [it['station'].lower().strip() for it in items]
    if len(stations) >= 2 and len(set(stations)) == 1:
        score += 5.0

    return True, round(min(score, 100.0), 1), reasons


def _generate_meal_templates(pool: list[dict], health_intensity: str) -> list[tuple[str, list[tuple[str, dict]]]]:
    """
    Intelligent candidate generation across multiple meal structures.
    """
    by_role: dict[str, list[dict]] = {}
    for it in pool:
        by_role.setdefault(it['_role'], []).append(it)

    def _diverse_top(items_list: list[dict], limit: int) -> list[dict]:
        if len(items_list) <= limit:
            return items_list
        sorted_items = sorted(items_list, key=lambda x: x['_quality_score'], reverse=True)
        picked = []
        seen_cuisines: dict[str, int] = {}
        for it in sorted_items:
            c = it['_cuisine']
            if seen_cuisines.get(c, 0) < 3:
                picked.append(it)
                seen_cuisines[c] = seen_cuisines.get(c, 0) + 1
                if len(picked) >= limit:
                    return picked
        for it in sorted_items:
            if it not in picked:
                picked.append(it)
                if len(picked) >= limit:
                    break
        return picked

    proteins = _diverse_top(by_role.get('protein_entree', []), 12)
    if len(proteins) < 3:
        proteins = _build_option_b_anchors(pool, proteins)

    carbs = _diverse_top(by_role.get('carb_base', []), 10)
    vegs = _diverse_top(by_role.get('vegetable', []), 8)
    sides = _diverse_top(by_role.get('side', []), 8)
    sandwiches = _diverse_top(by_role.get('sandwich', []), 6)
    complete_entrees = _diverse_top(by_role.get('complete_entree', []), 6)
    pasta_entrees = _diverse_top(by_role.get('pasta_entree', []), 6)
    bowls = _diverse_top(by_role.get('bowl', []), 6)
    salads = _diverse_top(by_role.get('composed_salad', []), 5)
    breakfasts = _diverse_top(by_role.get('breakfast_entree', []), 6)

    veg_and_sides = vegs + sides
    light_sides = [s for s in veg_and_sides if s['calories'] <= 240.0][:10]

    candidates: list[tuple[str, list[tuple[str, dict]]]] = []

    # Template 1 & 2: Protein-anchored meals (with special handling for entree protein salads)
    for p in proteins:
        is_protein_salad = 'salad' in p['name'].lower()
        if is_protein_salad:
            # Complete entree salads (e.g., Southwest Chicken Salad, Cobb Salad) stand alone or pair with a crisp side
            candidates.append(('salad_meal', [('Main', p)]))
            for ls in light_sides[:5]:
                if ls['name'] != p['name']:
                    candidates.append(('salad_side', [('Main', p), ('Side', ls)]))
            continue

        main_label = 'Main' if p['_role'] == 'protein_entree' else 'Base'
        for c in carbs:
            if c['name'] == p['name']:
                continue
            for vs in (veg_and_sides[:8] + [None]):
                if vs and vs['name'] in (p['name'], c['name']):
                    continue
                slots = [(main_label, p), ('Base', c)]
                if vs:
                    slots.append(('Side', vs))
                candidates.append(('protein_carb_veg', slots))
        for vs in veg_and_sides[:8]:
            if vs['name'] != p['name']:
                candidates.append(('protein_veg', [(main_label, p), ('Side', vs)]))

    # Template 3: Complete Entree (Burrito, Pizza, etc.) + Optional Light Side
    for ce in complete_entrees:
        candidates.append(('complete_entree', [('Main', ce)]))
        for ls in light_sides[:5]:
            if ls['name'] != ce['name']:
                candidates.append(('complete_entree_side', [('Main', ce), ('Side', ls)]))

    # Template 4: Sandwich / Burger + Optional Crisp Side
    for sw in sandwiches:
        candidates.append(('sandwich_meal', [('Main', sw)]))
        for ls in light_sides[:5]:
            if ls['name'] != sw['name']:
                candidates.append(('sandwich_side', [('Main', sw), ('Side', ls)]))

    # Template 5: Pasta Entree + Optional Vegetable/Light Side
    for pa in pasta_entrees:
        candidates.append(('pasta_meal', [('Main', pa)]))
        for v in vegs[:5]:
            if v['name'] != pa['name']:
                candidates.append(('pasta_veg', [('Main', pa), ('Side', v)]))

    # Template 6: Bowl + Optional Vegetable
    for bw in bowls:
        candidates.append(('bowl_meal', [('Main', bw)]))
        for v in vegs[:4]:
            if v['name'] != bw['name']:
                candidates.append(('bowl_veg', [('Main', bw), ('Side', v)]))

    # Template 7: Composed Salad (standalone salad main OR foundation paired with lean protein)
    for sal in salads:
        candidates.append(('salad_meal', [('Main', sal)]))
        for side_opt in sides[:4]:
            if side_opt['name'] != sal['name']:
                candidates.append(('salad_side', [('Main', sal), ('Side', side_opt)]))
        for p in proteins[:6]:
            if p['name'] == sal['name'] or p['_role'] != 'protein_entree' or 'salad' in p['name'].lower():
                continue
            candidates.append(('salad_protein', [('Main', p), ('Base', sal)]))
            for side_opt in sides[:3]:
                if side_opt['name'] not in (p['name'], sal['name']):
                    candidates.append(('salad_protein_side', [('Main', p), ('Base', sal), ('Side', side_opt)]))

    # Template 8: Breakfast Entree + Complementary Side
    for bf in breakfasts:
        candidates.append(('breakfast_meal', [('Main', bf)]))
        for ls in light_sides[:5]:
            if ls['name'] != bf['name']:
                candidates.append(('breakfast_side', [('Main', bf), ('Side', ls)]))

    return candidates


def _score_meal_completeness(slots: list[tuple[str, dict]], template_name: str) -> float:
    """
    Evaluates whether the meal feels complete, coherent, and satisfying.
    """
    items = [it for _, it in slots]
    roles = {it['_role'] for it in items}
    tot_cal = sum(it['calories'] for it in items)
    tot_pro = sum(it['protein'] for it in items)

    score = 62.0

    if roles & {'complete_entree', 'sandwich', 'pasta_entree', 'bowl', 'breakfast_entree'}:
        score += 22.0
        if len(items) == 2:
            score += 8.0
    elif 'composed_salad' in roles and 'protein_entree' in roles:
        score += 26.0
    elif 'composed_salad' in roles or ('protein_entree' in roles and any('salad' in it['name'].lower() for it in items)):
        score += 20.0
        if len(items) == 2:
            score += 6.0
    elif 'protein_entree' in roles and 'carb_base' in roles and ('vegetable' in roles or 'side' in roles):
        score += 28.0
    elif 'protein_entree' in roles and ('carb_base' in roles or 'vegetable' in roles):
        score += 18.0
    elif len(items) >= 2:
        score += 12.0

    if tot_cal < 220.0:
        score -= 20.0
    elif tot_cal > 1150.0:
        score -= 15.0

    if tot_pro >= 18.0:
        score += 6.0

    return round(max(0.0, min(score, 100.0)), 1)


def _score_nutrition_balance(
    totals: dict,
    per_meal: Optional[dict],
    dri_enabled: bool,
    meal_goal: str,
    health_intensity: str,
) -> float:
    cal = totals['calories']
    pro = totals['protein']
    carb = totals['carbs']
    fat = totals['fat']
    sugar = totals['sugar']

    if dri_enabled and per_meal:
        cal_err = abs(cal - per_meal['calories']) / max(per_meal['calories'], 1.0)
        pro_err = abs(pro - per_meal['protein_target']) / max(per_meal['protein_target'], 1.0)
        carb_err = _range_error(carb, per_meal['carbs_min'], per_meal['carbs_max'])
        fat_err = _range_error(fat, per_meal['fat_min'], per_meal['fat_max'])

        goal_norm = meal_goal.strip().lower()
        if 'high protein' in goal_norm or 'lean cut' in goal_norm:
            penalty = (pro_err * 36.0) + (cal_err * 24.0) + (carb_err * 14.0) + (fat_err * 14.0)
        else:
            penalty = (cal_err * 26.0) + (pro_err * 26.0) + (carb_err * 18.0) + (fat_err * 18.0)

        if pro < per_meal['protein_min']:
            penalty += ((per_meal['protein_min'] - pro) / max(per_meal['protein_min'], 1.0)) * 25.0

        return round(max(0.0, min(100.0 - penalty, 100.0)), 1)

    profile = MODE_SCORING_PROFILES.get(health_intensity.strip().lower(), MODE_SCORING_PROFILES['mid'])
    low_cal, high_cal = profile['target_cal_range']

    score = 72.0
    if low_cal <= cal <= high_cal:
        score += 14.0
    elif cal < low_cal:
        score -= min(((low_cal - cal) / low_cal) * 30.0, 22.0)
    else:
        score -= min(((cal - high_cal) / high_cal) * 25.0, 20.0)

    total_macro_cal = max((pro * 4.0) + (carb * 4.0) + (fat * 9.0), 1.0)
    p_share = (pro * 4.0) / total_macro_cal
    c_share = (carb * 4.0) / total_macro_cal
    f_share = (fat * 9.0) / total_macro_cal

    if 0.16 <= p_share <= 0.45:
        score += 8.0
    if 0.20 <= c_share <= 0.60:
        score += 4.0
    if 0.15 <= f_share <= 0.42:
        score += 4.0

    if sugar > 24.0:
        score -= min((sugar - 24.0) * 0.8, 12.0)

    return round(max(0.0, min(score, 100.0)), 1)


def _score_variety_and_presentation(slots: list[tuple[str, dict]]) -> float:
    items = [it for _, it in slots]
    if len(items) == 1:
        role = items[0]['_role']
        return 74.0 if role in ('bowl', 'composed_salad', 'complete_entree', 'sandwich') else 55.0

    score = 55.0
    distinct_roles = {it['_role'] for it in items}
    distinct_methods = {it['_method'] for it in items}

    score += min((len(distinct_roles) - 1) * 14.0, 28.0)
    score += min((len(distinct_methods) - 1) * 8.0, 12.0)

    if 'vegetable' in distinct_roles or 'composed_salad' in distinct_roles:
        score += 8.0

    return round(max(0.0, min(score, 100.0)), 1)


def _build_match_summary(
    slots: list[tuple[str, dict]],
    compat_reasons: list[str],
    health_intensity: str,
) -> str:
    """
    Builds a compact human-readable match rationale for UI recommendation cards
    (e.g., "Classic Asian protein & steamed rice pairing • Verified seed-oil-free").
    """
    items = [it for _, it in slots]
    culinary_note = 'Balanced campus plate'
    if compat_reasons:
        specific = [
            r for r in compat_reasons
            if not r.startswith('Cohesive ') and r != 'Clean neutral accompaniment'
        ]
        culinary_note = specific[0] if specific else compat_reasons[0]

    tier = health_intensity.strip().lower()
    reasons_text = ' '.join((it.get('_health_reason') or '').lower() for it in items)
    if 'verified seed-oil-free' in reasons_text:
        quality_note = 'Verified seed-oil-free'
    elif tier == 'low':
        quality_note = 'High culinary appeal'
    elif tier == 'high':
        quality_note = 'Clean whole-food plate'
    else:
        quality_note = 'Balanced dining staple'

    if culinary_note.lower() == quality_note.lower():
        return culinary_note
    return f'{culinary_note} • {quality_note}'


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


def _compute_similarity_penalty(
    cand_meta: dict,
    selected_metas: list[dict],
) -> float:
    if not selected_metas:
        return 0.0

    max_penalty = 0.0
    for prev in selected_metas:
        pen = 0.0
        shared_items = cand_meta['item_names'] & prev['item_names']
        pen += len(shared_items) * 14.0

        if cand_meta['anchor_name'] == prev['anchor_name']:
            pen += 22.0
        elif cand_meta['main_ingredient'] == prev['main_ingredient']:
            pen += 10.0

        if cand_meta['cuisine'] == prev['cuisine'] and cand_meta['cuisine'] != 'neutral':
            pen += 5.0

        if cand_meta['template'] == prev['template']:
            pen += 4.0

        if cand_meta['anchor_method'] == prev['anchor_method']:
            pen += 2.5

        if pen > max_penalty:
            max_penalty = pen

    return max_penalty


def build_optimal_plates(
    open_items: list[dict],
    meal_targets: Optional[dict],
    meal_goal: str,
    health_intensity: str,
    dri_enabled: bool = False,
    dietary_filters: Optional[list[str]] = None,
    top_n: int = 3,
    custom_weights: Optional[dict] = None,
) -> list[dict]:
    active_filters = dietary_filters or []
    per_meal = (meal_targets or {}).get('per_meal') if dri_enabled else None
    tier_key = health_intensity.strip().lower()
    profile = MODE_SCORING_PROFILES.get(tier_key, MODE_SCORING_PROFILES['mid'])
    weights = custom_weights or profile['weights']

    by_location: dict[str, list[dict]] = {}
    for item in open_items:
        if not _passes_dietary_filters(item, active_filters):
            continue
        allowed, quality_score, reason = evaluate_item_health(item, health_intensity)
        if not allowed:
            continue
        role = classify_food_item(item)
        if role == 'exclude':
            continue

        enriched = dict(item)
        enriched['_quality_score'] = quality_score
        enriched['_health_reason'] = reason
        enriched['_cuisine'] = _detect_cuisine_profile(enriched)
        enriched['_method'] = _detect_cooking_method(enriched)
        enriched['_flavors'] = _detect_flavor_tags(enriched)
        enriched['_role'] = role
        enriched['_certainty'] = _assess_ingredient_certainty(enriched)
        enriched['_main_ing'] = _extract_main_ingredient_key(enriched)
        by_location.setdefault(item['location'], []).append(enriched)

    location_results = []

    for location, items in by_location.items():
        unique_items = {}
        for it in items:
            if it['name'] not in unique_items:
                unique_items[it['name']] = it
        pool = list(unique_items.values())

        template_candidates = _generate_meal_templates(pool, health_intensity)
        if not template_candidates:
            continue

        scored_candidates = []
        seen_signatures = set()

        for template_name, slots in template_candidates:
            sig = tuple(sorted(it['name'] for _, it in slots))
            if sig in seen_signatures:
                continue
            seen_signatures.add(sig)

            compatible, compat_score, compat_reasons = evaluate_culinary_compatibility(slots, template_name)
            if not compatible:
                continue

            tot_cal = sum(it['calories'] for _, it in slots)
            tot_pro = sum(it['protein'] for _, it in slots)
            tot_carb = sum(it['carbs'] for _, it in slots)
            tot_fat = sum(it['fat'] for _, it in slots)
            tot_sugar = sum(it['sugar'] for _, it in slots)

            totals_obj = {
                'calories': round(tot_cal, 1),
                'protein': round(tot_pro, 1),
                'carbs': round(tot_carb, 1),
                'fat': round(tot_fat, 1),
                'sugar': round(tot_sugar, 1),
            }

            completeness_score = _score_meal_completeness(slots, template_name)
            food_quality_score = round(sum(it['_quality_score'] for _, it in slots) / len(slots), 1)
            nutrition_score = _score_nutrition_balance(
                totals_obj, per_meal, dri_enabled, meal_goal, health_intensity
            )
            variety_score = _score_variety_and_presentation(slots)

            weighted_total = (
                (compat_score * weights['culinary_compatibility']) +
                (completeness_score * weights['meal_completeness']) +
                (food_quality_score * weights['food_quality']) +
                (nutrition_score * weights['nutrition_balance']) +
                (variety_score * weights['variety_presentation'])
            )

            anchor_item = slots[0][1]
            meta = {
                'item_names': {it['name'] for _, it in slots},
                'anchor_name': anchor_item['name'],
                'main_ingredient': anchor_item['_main_ing'],
                'cuisine': anchor_item['_cuisine'],
                'template': template_name,
                'anchor_method': anchor_item['_method'],
            }

            breakdown = {
                'culinary_compatibility': compat_score,
                'meal_completeness': completeness_score,
                'food_quality': food_quality_score,
                'nutrition_balance': nutrition_score,
                'variety_presentation': variety_score,
                'compatibility_notes': compat_reasons,
                'match_summary': _build_match_summary(slots, compat_reasons, health_intensity),
            }

            scored_candidates.append((weighted_total, anchor_item, slots, totals_obj, breakdown, meta))

        if not scored_candidates:
            continue

        scored_candidates.sort(key=lambda x: x[0], reverse=True)

        selected_combos = []
        selected_metas: list[dict] = []
        remaining = list(scored_candidates)

        while remaining and len(selected_combos) < 3:
            best_idx = 0
            best_adjusted = -1e9
            for idx, (base_score, anchor_item, slots, totals_obj, breakdown, meta) in enumerate(remaining):
                div_penalty = _compute_similarity_penalty(meta, selected_metas)
                adjusted = base_score - div_penalty
                if adjusted > best_adjusted:
                    best_adjusted = adjusted
                    best_idx = idx

            chosen = remaining.pop(best_idx)
            selected_combos.append(chosen)
            selected_metas.append(chosen[5])

        formatted_combos = []
        for idx, (score_val, anchor_item, slots, totals_obj, breakdown, _meta) in enumerate(selected_combos, start=1):
            slot_items = [it for _, it in slots]
            dominant_cuisine = anchor_item['_cuisine']
            combo_name = _generate_combo_title(slot_items, dominant_cuisine)
            macro_split = _compute_macro_split(
                totals_obj['protein'], totals_obj['carbs'], totals_obj['fat']
            )

            formatted_items = []
            for role_label, it in slots:
                formatted_items.append({
                    'role': role_label,
                    'food_type': it['_role'],
                    'station': it['station'],
                    'name': it['name'],
                    'calories': round(it['calories'], 1),
                    'protein': round(it['protein'], 1),
                    'carbs': round(it['carbs'], 1),
                    'fat': round(it['fat'], 1),
                    'allergens': it.get('allergens', []),
                    'ingredient_certainty': it['_certainty'],
                    'used_fallback': it['used_fallback'],
                    'reason': it['_health_reason'],
                })

            formatted_combos.append({
                'combo_id': f"{location.lower().replace(' ', '_')}_{idx}",
                'combo_name': combo_name,
                'station_tag': anchor_item['station'],
                'score': round(score_val, 1),
                'score_breakdown': breakdown,
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
    current_time: Optional[datetime] = None,
    prebuilt_items: Optional[list[dict]] = None,
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

    if prebuilt_items is not None:
        all_items, from_cache = hydrate_missing_macros(prebuilt_items), False
    else:
        all_items, from_cache = get_daily_menus(
            target_date=now.strftime('%Y-%m-%d'),
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