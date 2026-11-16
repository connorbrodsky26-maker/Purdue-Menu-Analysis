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
    'high': {  # Healthy
        'label': 'Healthy',
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
    'low': {   # Yummy
        'label': 'Yummy',
        'weights': {
            'culinary_compatibility': 0.38,
            'meal_completeness': 0.22,
            'food_quality': 0.26,
            'nutrition_balance': 0.04,
            'variety_presentation': 0.10,
        },
        'strict_clean_ingredients': False,
        'target_cal_range': (450.0, 1350.0),
        'min_protein_ideal': 15.0,
    },
    'extreme': {  # Pure Health Mode (Unconstrained Macro Assembler & Whole-Food Stacking)
        'label': 'Pure Health',
        'weights': {
            'culinary_compatibility': 0.00,
            'meal_completeness': 0.10,
            'food_quality': 0.50,
            'nutrition_balance': 0.40,
            'variety_presentation': 0.00,
        },
        'strict_clean_ingredients': True,
        'target_cal_range': (700.0, 1350.0),
        'min_protein_ideal': 45.0,
    },
}

# Sensible default macro targets for Pure Health mode (tailored for 155 lbs individual maintaining on 2 meals/day)
DEFAULT_PURE_HEALTH_PER_MEAL = {
    'calories': 1150.0,
    'protein_min': 42.0,
    'protein_target': 55.0,
    'protein_max': 75.0,
    'carbs_min': 75.0,
    'carbs_target': 115.0,
    'carbs_max': 145.0,
    'fat_min': 22.0,
    'fat_target': 35.0,
    'fat_max': 48.0,
    'sugar_max': 20.0,
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
    'boilerq bbq chicken drumstick': {
        'calories': 105.0, 'protein': 11.0, 'carbs': 2.0, 'fat': 5.5, 'sugar': 1.0,
        'ingredients': 'Chicken Drumstick, Princess Dry Rub Seasoning (1 drumstick, approx 35g meat)'
    },
    'chicken drumstick': {
        'calories': 105.0, 'protein': 11.0, 'carbs': 2.0, 'fat': 5.5, 'sugar': 1.0,
        'ingredients': 'Chicken Drumstick, Seasoning, Oil (1 drumstick, approx 35g meat)'
    },
    'drumstick': {
        'calories': 105.0, 'protein': 11.0, 'carbs': 2.0, 'fat': 5.5, 'sugar': 1.0,
        'ingredients': 'Chicken Drumstick, Seasoning, Oil (1 drumstick, approx 35g meat)'
    },
    'diced chicken for burrito bowl': {
        'calories': 185.0, 'protein': 35.0, 'carbs': 0.0, 'fat': 4.0, 'sugar': 0.0,
        'ingredients': 'Diced Seasoned Chicken Breast (approx 4 oz)'
    },
    'seasoned green beans': {
        'calories': 40.0, 'protein': 2.0, 'carbs': 8.0, 'fat': 0.3, 'sugar': 2.0,
        'ingredients': 'Seasoned Green Beans (0.5 cup)'
    },
    'green beans': {
        'calories': 40.0, 'protein': 2.0, 'carbs': 8.0, 'fat': 0.3, 'sugar': 2.0,
        'ingredients': 'Steamed Green Beans (0.5 cup)'
    },
    'chicken wing': {
        'calories': 85.0, 'protein': 9.0, 'carbs': 0.0, 'fat': 5.5, 'sugar': 0.0,
        'ingredients': 'Chicken Wing, Seasoning (1 wing)'
    },
    'chicken thigh': {
        'calories': 200.0, 'protein': 21.0, 'carbs': 0.0, 'fat': 12.0, 'sugar': 0.0,
        'ingredients': 'Chicken Thigh, Seasoning (1 thigh)'
    },
    'crinkle cut fries': {
        'calories': 220.0, 'protein': 2.8, 'carbs': 28.0, 'fat': 11.0, 'sugar': 0.5,
        'ingredients': 'Potatoes, Vegetable Oil, Sea Salt (1 serving, approx 3 oz)'
    },
    'french fries': {
        'calories': 220.0, 'protein': 2.8, 'carbs': 28.0, 'fat': 11.0, 'sugar': 0.5,
        'ingredients': 'Potatoes, Vegetable Oil, Sea Salt (1 serving, approx 3 oz)'
    },
    'fries': {
        'calories': 220.0, 'protein': 2.8, 'carbs': 28.0, 'fat': 11.0, 'sugar': 0.5,
        'ingredients': 'Potatoes, Vegetable Oil, Sea Salt (1 serving, approx 3 oz)'
    },
    'corn dog': {
        'calories': 230.0, 'protein': 7.0, 'carbs': 24.0, 'fat': 12.0, 'sugar': 5.0,
        'ingredients': 'Batter Wrapped Hot Dog (1 corn dog, approx 3 oz)'
    },
    'corndog': {
        'calories': 230.0, 'protein': 7.0, 'carbs': 24.0, 'fat': 12.0, 'sugar': 5.0,
        'ingredients': 'Batter Wrapped Hot Dog (1 corn dog, approx 3 oz)'
    },
    'swedish meatballs': {
        'calories': 260.0, 'protein': 18.0, 'carbs': 10.0, 'fat': 16.0, 'sugar': 2.0,
        'ingredients': 'Beef and Pork Meatballs in Savory Cream Gravy (4 meatballs, approx 4 oz)'
    },
    'swedish meatball': {
        'calories': 260.0, 'protein': 18.0, 'carbs': 10.0, 'fat': 16.0, 'sugar': 2.0,
        'ingredients': 'Beef and Pork Meatballs in Savory Cream Gravy (4 meatballs, approx 4 oz)'
    },
    'carne adobada': {
        'calories': 240.0, 'protein': 24.0, 'carbs': 3.0, 'fat': 14.0, 'sugar': 1.0,
        'ingredients': 'Slow-Braised Spiced Pork in Red Chile Adobo Sauce (approx 4 oz)'
    },
    'sofritas': {
        'calories': 150.0, 'protein': 10.0, 'carbs': 9.0, 'fat': 8.0, 'sugar': 4.0,
        'ingredients': 'Braised Organic Tofu, Chipotle Chilies, Roasted Poblano, Spices (approx 4 oz)'
    },
    'vegan chik nuggets': {
        'calories': 190.0, 'protein': 13.0, 'carbs': 14.0, 'fat': 9.0, 'sugar': 0.0,
        'ingredients': 'Crispy Plant-Based Chik Nuggets (4 nuggets)'
    },
    'french toast sticks': {
        'calories': 280.0, 'protein': 5.0, 'carbs': 38.0, 'fat': 12.0, 'sugar': 12.0,
        'ingredients': 'Crispy French Toast Sticks, Cinnamon Sugar (4 sticks)'
    },
    'french toast stick': {
        'calories': 280.0, 'protein': 5.0, 'carbs': 38.0, 'fat': 12.0, 'sugar': 12.0,
        'ingredients': 'Crispy French Toast Sticks, Cinnamon Sugar (4 sticks)'
    },
    'pancakes': {
        'calories': 220.0, 'protein': 5.0, 'carbs': 35.0, 'fat': 7.0, 'sugar': 7.0,
        'ingredients': 'Golden Buttermilk Pancakes (2 pancakes)'
    },
    'pancake': {
        'calories': 220.0, 'protein': 5.0, 'carbs': 35.0, 'fat': 7.0, 'sugar': 7.0,
        'ingredients': 'Golden Buttermilk Pancakes (2 pancakes)'
    },
    'sweet plantains': {
        'calories': 180.0, 'protein': 1.0, 'carbs': 36.0, 'fat': 4.5, 'sugar': 18.0,
        'ingredients': 'Fried Ripe Sweet Plantains / Maduros (0.5 cup)'
    },
    'samosa': {
        'calories': 170.0, 'protein': 3.5, 'carbs': 20.0, 'fat': 9.0, 'sugar': 1.0,
        'ingredients': 'Crispy Spiced Potato & Green Pea Samosa (1 piece)'
    },
    'fried pickles': {
        'calories': 180.0, 'protein': 2.0, 'carbs': 19.0, 'fat': 11.0, 'sugar': 1.0,
        'ingredients': 'Crispy Breaded Fried Pickles (4 pieces)'
    },
    'peas': {
        'calories': 65.0, 'protein': 4.0, 'carbs': 12.0, 'fat': 0.5, 'sugar': 4.5,
        'ingredients': 'Steamed Sweet Green Peas (0.5 cup)'
    },
    'baby carrots': {
        'calories': 35.0, 'protein': 0.8, 'carbs': 8.0, 'fat': 0.2, 'sugar': 5.0,
        'ingredients': 'Fresh Crisp Baby Carrots (approx 3 oz)'
    },
    'celery sticks': {
        'calories': 15.0, 'protein': 0.7, 'carbs': 3.0, 'fat': 0.2, 'sugar': 1.5,
        'ingredients': 'Fresh Crisp Celery Sticks (approx 3 oz)'
    },
    'sauteed seasoned mushrooms': {
        'calories': 40.0, 'protein': 2.0, 'carbs': 4.0, 'fat': 2.5, 'sugar': 1.5,
        'ingredients': 'Sauteed Seasoned Button Mushrooms (0.5 cup)'
    },
    'chopped green onions': {
        'calories': 5.0, 'protein': 0.3, 'carbs': 1.0, 'fat': 0.0, 'sugar': 0.4,
        'ingredients': 'Fresh Chopped Green Onions / Scallions (2 tbsp)'
    },
    'shredded cheddar cheese': {
        'calories': 110.0, 'protein': 7.0, 'carbs': 1.0, 'fat': 9.0, 'sugar': 0.5,
        'ingredients': 'Shredded Cheddar Cheese (1 oz / 0.25 cup)'
    },
    'shredded 3 cheese blend': {
        'calories': 110.0, 'protein': 7.0, 'carbs': 1.0, 'fat': 9.0, 'sugar': 0.5,
        'ingredients': 'Shredded Three-Cheese Blend (1 oz / 0.25 cup)'
    },
    'grated parmesan cheese': {
        'calories': 110.0, 'protein': 9.0, 'carbs': 1.0, 'fat': 8.0, 'sugar': 0.0,
        'ingredients': 'Grated Parmesan Cheese (1 oz / 0.25 cup)'
    },
    'vegan shredded mozzarella cheese': {
        'calories': 80.0, 'protein': 1.0, 'carbs': 7.0, 'fat': 6.0, 'sugar': 0.5,
        'ingredients': 'Plant-Based Shredded Mozzarella (1 oz / 0.25 cup)'
    },
    'shredded cheddar & mont. jack cheese': {
        'calories': 110.0, 'protein': 7.0, 'carbs': 1.0, 'fat': 9.0, 'sugar': 0.5,
        'ingredients': 'Shredded Cheddar & Monterey Jack Cheese (1 oz / 0.25 cup)'
    },
    'whipped butter': {
        'calories': 70.0, 'protein': 0.1, 'carbs': 0.1, 'fat': 8.0, 'sugar': 0.0,
        'ingredients': 'Whipped Table Butter (1 tbsp / 1 pat)'
    },
    'cinnamon honey butter': {
        'calories': 85.0, 'protein': 0.1, 'carbs': 4.0, 'fat': 7.5, 'sugar': 4.0,
        'ingredients': 'Whipped Butter with Honey & Cinnamon (1 tbsp)'
    },
    'chocolate ganache': {
        'calories': 130.0, 'protein': 1.0, 'carbs': 14.0, 'fat': 8.0, 'sugar': 12.0,
        'ingredients': 'Rich Chocolate Ganache Topping (2 tbsp)'
    },
    'whipped topping': {
        'calories': 30.0, 'protein': 0.0, 'carbs': 2.0, 'fat': 2.0, 'sugar': 2.0,
        'ingredients': 'Whipped Cream / Topping (2 tbsp)'
    },
    'edc bowl': {
        'calories': 440.0, 'protein': 26.0, 'carbs': 52.0, 'fat': 14.0, 'sugar': 4.0,
        'ingredients': 'Everyday Choices Grain, Vegetable & Protein Harvest Bowl'
    },
    'vanilla soy milk': {
        'calories': 100.0, 'protein': 7.0, 'carbs': 9.0, 'fat': 4.0, 'sugar': 6.0,
        'ingredients': 'Organic Vanilla Soy Milk (1 cup / 8 fl oz)'
    },
    'chocolate soy milk': {
        'calories': 140.0, 'protein': 7.0, 'carbs': 20.0, 'fat': 3.5, 'sugar': 17.0,
        'ingredients': 'Organic Chocolate Soy Milk (1 cup / 8 fl oz)'
    },
}

ORDERED_KEYWORD_MACROS = [
    # 1. Filled Sandwiches, Burgers, Wraps & Burritos
    ('corn dog', (230.0, 7.0, 24.0, 12.0, 5.0)),
    ('corndog', (230.0, 7.0, 24.0, 12.0, 5.0)),
    ('hot dog', (290.0, 10.0, 24.0, 16.0, 4.0)),
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
    ('chocolate ganache', (130.0, 1.0, 14.0, 8.0, 12.0)),
    ('apple pie', (320.0, 2.5, 46.0, 14.0, 24.0)),
    ('peach cobbler', (310.0, 3.0, 48.0, 12.0, 26.0)),
    ('cherry pie', (325.0, 2.5, 47.0, 14.5, 25.0)),
    ('pie', (320.0, 3.0, 45.0, 14.0, 22.0)),
    ('cheesecake', (350.0, 6.0, 32.0, 22.0, 24.0)),
    ('coffeecake', (280.0, 3.5, 42.0, 11.0, 22.0)),
    ('coffee cake', (280.0, 3.5, 42.0, 11.0, 22.0)),
    ('cake', (310.0, 3.5, 46.0, 12.0, 28.0)),
    ('brownie', (290.0, 3.5, 38.0, 14.0, 24.0)),
    ('cookie', (210.0, 2.5, 28.0, 10.0, 16.0)),
    ('donut', (270.0, 3.5, 33.0, 14.0, 15.0)),
    ('muffin', (340.0, 5.0, 48.0, 14.0, 24.0)),
    ('ice cream', (230.0, 4.0, 28.0, 12.0, 22.0)),
    ('pudding', (180.0, 3.0, 30.0, 5.0, 20.0)),

    # 4. Dips, sauces, condiments, and spreads
    ('whipped topping', (30.0, 0.0, 2.0, 2.0, 2.0)),
    ('cinnamon honey butter', (85.0, 0.1, 4.0, 7.5, 4.0)),
    ('whipped butter', (70.0, 0.1, 0.1, 8.0, 0.0)),
    ('butter', (100.0, 0.1, 0.0, 11.0, 0.0)),
    ('shredded cheddar', (110.0, 7.0, 1.0, 9.0, 0.5)),
    ('shredded mozzarella', (85.0, 6.0, 1.0, 6.5, 0.5)),
    ('shredded cheese', (110.0, 7.0, 1.0, 9.0, 0.5)),
    ('parmesan', (110.0, 9.0, 1.0, 8.0, 0.0)),
    ('cheddar', (110.0, 7.0, 1.0, 9.0, 0.5)),
    ('mozzarella', (85.0, 6.0, 1.0, 6.5, 0.5)),
    ('queso dip', (220.0, 8.0, 10.0, 16.0, 2.0)),
    ('queso', (210.0, 8.0, 9.0, 16.0, 2.0)),
    ('spinach dip', (230.0, 6.0, 11.0, 18.0, 2.0)),
    ('dip', (190.0, 5.0, 12.0, 14.0, 2.0)),
    ('gravy', (90.0, 2.0, 8.0, 5.5, 1.0)),
    ('glaze', (85.0, 0.2, 20.0, 0.2, 16.0)),
    ('syrup', (110.0, 0.0, 28.0, 0.0, 24.0)),
    ('dressing', (110.0, 0.5, 4.0, 10.0, 3.0)),
    ('aioli', (140.0, 0.5, 1.0, 15.0, 0.5)),
    ('ketchup', (20.0, 0.2, 5.0, 0.0, 4.0)),
    ('mustard', (10.0, 0.5, 1.0, 0.5, 0.0)),
    ('salsa', (20.0, 0.8, 4.0, 0.2, 2.0)),
    ('sauce', (80.0, 1.5, 10.0, 4.0, 5.0)),
    ('olive oil', (120.0, 0.0, 0.0, 14.0, 0.0)),

    # 5. Composite pasta, bowls, stir-fries, and dressed salads
    ('edc bowl', (440.0, 26.0, 52.0, 14.0, 4.0)),
    ('french toast sticks', (280.0, 5.0, 38.0, 12.0, 12.0)),
    ('french toast', (280.0, 5.0, 38.0, 12.0, 12.0)),
    ('pancakes', (220.0, 5.0, 35.0, 7.0, 7.0)),
    ('pancake', (220.0, 5.0, 35.0, 7.0, 7.0)),
    ('waffle', (240.0, 5.0, 32.0, 10.0, 4.0)),
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
    ('carne adobada', (240.0, 24.0, 3.0, 14.0, 1.0)),
    ('swedish meatball', (260.0, 18.0, 10.0, 16.0, 2.0)),
    ('meatball', (240.0, 16.0, 8.0, 15.0, 2.0)),
    ('sofritas', (150.0, 10.0, 9.0, 8.0, 4.0)),
    ('chik nuggets', (190.0, 13.0, 14.0, 9.0, 0.0)),
    ('chicken nugget', (210.0, 12.0, 14.0, 12.0, 0.0)),
    ('nugget', (200.0, 12.0, 14.0, 11.0, 0.0)),
    ('soy milk', (100.0, 7.0, 8.0, 4.0, 5.0)),
    ('scrambled egg', (180.0, 12.0, 2.0, 13.5, 1.0)),
    ('hard boiled egg', (78.0, 6.3, 0.6, 5.3, 0.6)),
    ('egg', (155.0, 12.5, 1.1, 10.6, 1.0)),
    ('grilled chicken breast', (185.0, 35.0, 0.0, 4.0, 0.0)),
    ('chicken breast', (185.0, 35.0, 0.0, 4.0, 0.0)),
    ('chicken thigh', (200.0, 21.0, 0.0, 12.0, 0.0)),
    ('chicken drumstick', (105.0, 11.0, 2.0, 5.5, 1.0)),
    ('drumstick', (105.0, 11.0, 2.0, 5.5, 1.0)),
    ('diced chicken', (185.0, 35.0, 0.0, 4.0, 0.0)),
    ('popcorn chicken', (240.0, 14.0, 16.0, 14.0, 0.5)),
    ('chicken wing', (85.0, 9.0, 0.0, 5.5, 0.0)),
    ('wing', (85.0, 9.0, 0.0, 5.5, 0.0)),
    ('chicken tender', (110.0, 11.0, 6.0, 4.5, 0.0)),
    ('chicken tenders', (110.0, 11.0, 6.0, 4.5, 0.0)),
    ('tender', (110.0, 11.0, 6.0, 4.5, 0.0)),
    ('chickpea chole curry', (260.0, 14.0, 38.0, 5.0, 4.0)),
    ('chole curry', (260.0, 14.0, 38.0, 5.0, 4.0)),
    ('chana masala', (260.0, 14.0, 38.0, 5.0, 4.0)),
    ('chickpea curry', (260.0, 14.0, 38.0, 5.0, 4.0)),
    ('curry', (250.0, 12.0, 35.0, 6.0, 4.0)),
    ('chicken', (215.0, 28.0, 2.0, 9.5, 0.5)),
    ('turkey breast', (175.0, 32.0, 0.0, 3.5, 0.0)),
    ('turkey', (200.0, 28.0, 1.0, 8.0, 0.5)),
    ('carne asada', (250.0, 27.0, 2.0, 14.0, 0.5)),
    ('roast beef', (235.0, 28.0, 1.0, 12.0, 0.0)),
    ('steak', (265.0, 29.0, 0.0, 16.0, 0.0)),
    ('hamburger patty', (250.0, 26.0, 1.0, 15.0, 0.0)),
    ('ground beef', (250.0, 26.0, 1.0, 15.0, 0.0)),
    ('beef', (250.0, 26.0, 1.5, 15.0, 0.5)),
    ('pork tenderloin', (240.0, 25.0, 2.0, 14.0, 0.0)),
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
    ('sweet plantains', (180.0, 1.0, 36.0, 4.5, 18.0)),
    ('plantain', (180.0, 1.0, 36.0, 4.5, 18.0)),
    ('samosa', (170.0, 3.5, 20.0, 9.0, 1.0)),
    ('fried pickle', (180.0, 2.0, 19.0, 11.0, 1.0)),
    ('garbanzo', (135.0, 7.3, 22.5, 2.1, 4.0)),
    ('chickpea', (135.0, 7.3, 22.5, 2.1, 4.0)),
    ('black bean', (130.0, 8.0, 23.0, 0.8, 1.0)),
    ('kidney bean', (130.0, 8.0, 23.0, 0.8, 1.0)),
    ('pinto bean', (130.0, 8.0, 23.0, 0.8, 1.0)),
    ('green beans', (40.0, 2.0, 8.0, 0.3, 2.0)),
    ('green bean', (40.0, 2.0, 8.0, 0.3, 2.0)),
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
    ('crinkle cut fries', (220.0, 2.8, 28.0, 11.0, 0.5)),
    ('french fries', (220.0, 2.8, 28.0, 11.0, 0.5)),
    ('fries', (220.0, 2.8, 28.0, 11.0, 0.5)),
    ('french fry', (220.0, 2.8, 28.0, 11.0, 0.5)),
    ('tater tots', (210.0, 2.5, 26.0, 11.0, 0.5)),
    ('tots', (210.0, 2.5, 26.0, 11.0, 0.5)),
    ('hash brown', (200.0, 2.0, 24.0, 11.0, 0.5)),
    ('hashbrown', (200.0, 2.0, 24.0, 11.0, 0.5)),
    ('potato', (160.0, 3.5, 36.0, 0.3, 1.5)),
    ('rotini', (210.0, 7.0, 42.0, 1.2, 1.5)),
    ('penne', (210.0, 7.0, 42.0, 1.2, 1.5)),
    ('spaghetti', (210.0, 7.0, 42.0, 1.2, 1.5)),
    ('fettuccine', (210.0, 7.0, 42.0, 1.2, 1.5)),
    ('pasta', (210.0, 7.0, 42.0, 1.2, 1.5)),
    ('noodle', (210.0, 7.0, 42.0, 1.2, 1.5)),
    ('oatmeal', (160.0, 5.5, 28.0, 3.0, 1.0)),
    ('oat', (160.0, 5.5, 28.0, 3.0, 1.0)),

    # 8. Vegetables and whole fruits
    ('peas', (65.0, 4.0, 12.0, 0.5, 4.5)),
    ('green peas', (65.0, 4.0, 12.0, 0.5, 4.5)),
    ('baby carrots', (35.0, 0.8, 8.0, 0.2, 5.0)),
    ('carrot', (35.0, 0.8, 8.0, 0.2, 5.0)),
    ('celery sticks', (15.0, 0.7, 3.0, 0.2, 1.5)),
    ('celery', (15.0, 0.7, 3.0, 0.2, 1.5)),
    ('sauteed seasoned mushrooms', (40.0, 2.0, 4.0, 2.5, 1.5)),
    ('mushrooms', (35.0, 2.0, 4.0, 2.0, 1.5)),
    ('mushroom', (35.0, 2.0, 4.0, 2.0, 1.5)),
    ('green onions', (5.0, 0.3, 1.0, 0.0, 0.4)),
    ('green onion', (5.0, 0.3, 1.0, 0.0, 0.4)),
    ('spinach', (15.0, 1.7, 2.2, 0.2, 0.3)),
    ('romaine', (15.0, 1.2, 3.0, 0.2, 1.0)),
    ('mixed greens', (15.0, 1.5, 2.5, 0.2, 0.4)),
    ('leafy greens', (15.0, 1.5, 2.5, 0.2, 0.4)),
    ('greens', (15.0, 1.5, 2.5, 0.2, 0.4)),
    ('broccoli', (45.0, 3.0, 8.0, 0.5, 2.0)),
    ('asparagus', (40.0, 3.5, 6.0, 0.4, 2.0)),
    ('brussels sprouts', (55.0, 4.0, 11.0, 0.4, 2.5)),
    ('cauliflower', (35.0, 2.5, 7.0, 0.3, 2.5)),
    ('zucchini', (30.0, 2.0, 6.0, 0.4, 3.0)),
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
    ('berry mix', (65.0, 1.0, 15.0, 0.4, 10.0)),
    ('strawberry', (55.0, 1.0, 13.0, 0.4, 8.0)),
    ('blueberry', (80.0, 1.0, 20.0, 0.4, 14.0)),
    ('red sour cherries', (50.0, 1.0, 12.0, 0.3, 8.0)),
    ('sour cherries', (50.0, 1.0, 12.0, 0.3, 8.0)),
    ('cherries', (55.0, 1.0, 13.0, 0.3, 9.0)),
    ('cherry', (55.0, 1.0, 13.0, 0.3, 9.0)),
    ('kiwi', (60.0, 1.2, 14.5, 0.5, 10.0)),
    ('peach', (60.0, 1.4, 14.0, 0.4, 13.0)),
    ('pear', (80.0, 0.5, 22.0, 0.2, 14.0)),
    ('grapes', (90.0, 0.9, 23.0, 0.2, 20.0)),
    ('fruit cocktail', (75.0, 0.8, 19.0, 0.2, 14.0)),
    ('fruit salad', (75.0, 0.8, 19.0, 0.2, 14.0)),
    ('fruit', (75.0, 0.8, 19.0, 0.2, 14.0)),
    ('chicken breast strip', (185.0, 35.0, 0.0, 4.0, 0.0)),
    ('hard cooked egg', (155.0, 12.5, 1.1, 10.6, 1.1)),
    ('steamed edamame', (120.0, 11.0, 9.0, 5.0, 2.0)),
    ('monterey vegetables', (50.0, 2.0, 9.0, 1.0, 3.0)),
]

SEED_OILS = [
    'canola oil', 'canola',
    'soybean oil', 'soya oil',
    'corn oil',
    'cottonseed oil',
    'sunflower oil', 'high oleic sunflower oil',
    'safflower oil', 'high oleic safflower oil',
    'rapeseed oil', 'grapeseed oil', 'rice bran oil',
    'vegetable oil', 'vegetable shortening',
    'margarine', 'shortening', 'hydrogenated', 'partially hydrogenated'
]

HIGH_SUGAR_ADDITIVES = [
    'high fructose corn syrup', 'corn syrup', 'cane sugar', 'brown sugar',
    'powdered sugar', 'dextrose', 'maltodextrin', 'invert sugar', 'icing',
    'frosting', 'glaze', 'waffle topping', 'pancake syrup', 'artificial syrup',
    'maple syrup flavored'
]

STRICT_REFINED_SUGAR_INGREDIENTS = [
    'high fructose corn syrup', 'corn syrup', 'powdered sugar',
    'invert sugar', 'icing', 'frosting', 'waffle topping', 'pancake syrup',
    'artificial syrup'
]

DEEP_FRIED_MARKERS = [
    'deep fried', 'breaded', 'battered', 'tempura', 'crispy fried',
    'panko', 'cornmeal crust', 'fried in', 'country fried', 'chicken fried',
    'fritter', 'nugget', 'nuggets', 'tenders', 'patty', 'patties'
]
ARTIFICIAL_DYES = [
    'red 40', 'red #40', 'yellow 5', 'yellow #5', 'yellow 6', 'yellow #6',
    'blue 1', 'blue #1', 'blue 2', 'blue #2'
]
CHEMICAL_PRESERVATIVES = [
    'sodium nitrite', 'sodium benzoate', 'potassium sorbate', 'bht', 'bha', 'tbhq'
]
ARTIFICIAL_ADDITIVES = ARTIFICIAL_DYES + CHEMICAL_PRESERVATIVES
WHOLE_FRUIT_KEYWORDS = [
    'watermelon', 'mandarin', 'orange', 'apple', 'banana', 'berries',
    'strawberry', 'blueberry', 'grapes', 'pineapple', 'cantaloupe', 'honeydew',
    'fruit mix', 'fresh fruit', 'kiwi', 'peach', 'pear', 'plum', 'grapefruit',
    'citrus', 'blackberry', 'raspberry', 'papaya', 'cherry', 'cherries', 'sour cherries'
]
NON_WHOLE_FRUIT_MARKERS = [
    'sauce', 'syrup', 'juice', 'topping', 'filling', 'glaze', 'compote',
    'jam', 'jelly', 'canned', 'pie', 'crisp', 'cobbler', 'puree', 'powder',
    'dried', 'candied', 'sugar'
]

STATION_HEADER_NAMES = {
    'pasta bar', 'salad bar', 'deli bar', 'taco bar', 'nacho bar',
    'baked potato bar', 'omelet bar', 'waffle bar', 'cereal bar',
    'soup bar', 'toppings bar', 'condiment bar', 'pizza toppers',
    'waffle brinner bar', 'build your own pizza bar', 'bread and condiments',
    'la fonda station', 'sundae brunch bar', 'sundae bar', 'yogurt bar',
    'ice cream bar', 'dessert bar', 'burger toppings', 'burrito bar',
    'oatmeal and pancake toppers'
}
DESSERT_KEYWORDS = [
    'pie', 'cake', 'cookie', 'brownie', 'cobbler', 'pudding',
    'ice cream', 'donut', 'muffin', 'pastry', 'tart', 'cupcake', 'gelato',
    'italian ice', 'sherbet', 'sorbet', 'coffeecake', 'coffee cake',
    'crumb cake', 'pound cake', 'crumble', 'crisp'
]

STANDALONE_CONDIMENT_KEYWORDS = [
    'sauce', 'glaze', 'dressing', 'gravy', 'salsa', 'aioli', 'ketchup',
    'mustard', 'syrup', 'ranch', 'vinaigrette', 'mayonnaise', 'mayo',
    'marinara', 'alfredo', 'pesto', 'au jus', 'chutney', 'relish',
    'jam', 'jelly', 'condiment', 'topping', 'powdered sugar', 'sprinkles',
    'crushed red pepper', 'seasoning', 'pancake syrup', 'olive oil',
    'extra virgin olive oil', 'vinegar', 'balsamic vinegar', 'red wine vinegar',
    'shredded cheese', 'grated cheese', 'parmesan cheese', 'grated parmesan',
    'cheddar cheese', 'shredded cheddar', 'mozzarella cheese', 'shredded mozzarella',
    'cheese blend', 'butter', 'whipped butter', 'green onion', 'green onions',
    'chopped green onions', 'chocolate ganache', 'whipped topping'
]
DIP_SPREAD_KEYWORDS = [
    'dip', 'queso', 'guacamole', 'hummus', 'tzatziki',
    'sour cream', 'cream cheese', 'spread'
]
ADDED_OIL_FAT_KEYWORDS = [
    'olive oil', 'avocado oil', 'butter', 'ghee', 'coconut oil', 'oil'
]

STANDALONE_BAKERY_KEYWORDS = [
    'bun', 'buns', 'bread', 'roll', 'rolls', 'bagel', 'tortilla', 'pita',
    'naan', 'croissant', 'biscuit', 'toast', 'english muffin', 'flatbread',
    'focaccia', 'ciabatta', 'brioche', 'breadstick', 'crackers', 'chips',
    'crouton', 'panko'
]

SANDWICH_ENTREE_MARKERS = [
    'sandwich', 'burger', 'cheeseburger', 'panini', 'wrap', 'sub',
    'hoagie', 'banh mi', 'gyro', 'melt', 'sliders', 'slider',
    'hot dog', 'hot dogs', 'corn dog', 'corn dogs', 'corndog', 'corndogs'
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
    'hard cooked egg', 'hard cooked eggs', 'hard boiled egg', 'hard boiled eggs',
    'boiled egg', 'boiled eggs', 'poached egg', 'poached eggs', 'fried egg', 'fried eggs',
    'egg white', 'egg whites', 'breakfast burrito', 'breakfast sandwich',
    'egg sandwich', 'eggs benedict', 'pancake', 'pancakes', 'waffle', 'waffles',
    'french toast', 'french toast stick', 'french toast sticks', 'breakfast skillet'
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
    'carrots', 'baby carrot', 'baby carrots', 'green bean', 'green beans',
    'spinach', 'kale', 'mixed vegetables', 'roasted vegetables', 'steamed vegetables',
    'peas', 'squash', 'bok choy', 'cabbage', 'edamame', 'bell pepper', 'peppers',
    'mushrooms', 'celery', 'celery stick', 'celery sticks',
    'corn on the cob', 'sweet corn', 'corn', 'romaine', 'mixed greens'
]

VERIFIED_NA_WHOLE_FOODS = [
    'plain white rice', 'long grain rice', 'jasmine rice', 'basmati rice',
    'plain brown rice', 'brown rice', 'steamed rice', 'steamed white rice',
    'steamed brown rice', 'baked potato', 'plain potato', 'baked sweet potato',
    'sweet potato', 'sweet potatoes', 'steamed broccoli', 'broccoli',
    'steamed vegetables', 'monterey vegetables', 'steamed asparagus', 'asparagus',
    'steamed green beans', 'green beans', 'steamed cauliflower', 'cauliflower',
    'steamed carrots', 'carrots', 'baby carrots', 'zucchini', 'brussels sprouts',
    'mixed greens', 'romaine', 'fresh spinach', 'baby spinach', 'spinach', 'raw spinach',
    'kale', 'cucumber', 'cucumbers', 'tomato', 'tomatoes', 'cherry tomatoes',
    'bell pepper', 'bell peppers', 'celery', 'radish', 'mushrooms', 'fresh mushrooms',
    'onion', 'red onion', 'peas', 'sweet peas', 'garbanzo beans', 'garbanzo',
    'chickpeas', 'black beans', 'kidney beans', 'pinto beans', 'lentils',
    'edamame', 'steamed edamame', 'plain edamame', 'quinoa', 'oatmeal', 'plain oatmeal',
    'plain grilled chicken breast', 'grilled chicken breast', 'chicken breast strip',
    'chicken breast strips', 'plain grilled chicken', 'baked chicken breast',
    'chicken thigh', 'turkey breast', 'pork loin', 'roast beef', 'tilapia',
    'salmon', 'baked salmon', 'cod', 'egg', 'eggs', 'hard boiled egg',
    'hard boiled eggs', 'hard-boiled egg', 'boiled egg', 'poached egg',
    'hard cooked eggs', 'hard cooked egg', 'scrambled eggs',
    'cottage cheese', 'plain greek yogurt', 'greek yogurt',
    'olive oil', 'extra virgin olive oil', 'avocado',
    'kiwi', 'peach slices', 'sliced strawberries', 'orange wedges', 'berry mix',
    'fruit cocktail', 'fruit salad', 'melon mix', 'fresh fruit',
    'red sour cherries', 'sour cherries', 'cherries', 'cherry'
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
    # Station and buffet line headers must never receive fallback food macros
    if lower_name in STATION_HEADER_NAMES or (
        any(lower_name.endswith(sfx) for sfx in (' bar', ' topper', ' toppers', ' toppings'))
        and not any(f in lower_name for f in ('ice cream bar', 'candy bar', 'granola bar', 'protein bar'))
    ):
        return None

    if lower_name in FALLBACK_MACROS:
        return FALLBACK_MACROS[lower_name]
    for key, macros in FALLBACK_MACROS.items():
        if re.search(rf'\b{re.escape(key)}(?:s|es)?\b', lower_name):
            return macros
    for kw, (cal, pro, carb, fat, sug) in ORDERED_KEYWORD_MACROS:
        if re.search(rf'\b{re.escape(kw)}(?:s|es)?\b', lower_name):
            return {
                'calories': cal,
                'protein': pro,
                'carbs': carb,
                'fat': fat,
                'sugar': sug,
                'ingredients': f'{item_name.title()} (Standard campus dining preparation)'
            }
    return None


# Verified permanent campus dining staples consistently available across all open Purdue Dining Courts
CAMPUS_PERMANENT_SALAD_STAPLES = [
    {
        'name': 'Fresh Baby Spinach (Salad Bar)',
        'station': 'Salad Stop',
        'calories': 15.0, 'protein': 2.0, 'carbs': 2.5, 'fat': 0.2, 'sugar': 0.4,
        'ingredients': 'Fresh Baby Spinach.',
        'allergens': ['vegetarian', 'vegan'],
        'is_vegetarian': True,
        'is_vegan': True,
        'serving_size': '2 cups raw',
    },
    {
        'name': 'Mesclun & Romaine Greens (Salad Bar)',
        'station': 'Salad Stop',
        'calories': 15.0, 'protein': 1.5, 'carbs': 2.5, 'fat': 0.2, 'sugar': 0.5,
        'ingredients': 'Chopped Romaine Lettuce, Mesclun Green Leaf Lettuce.',
        'allergens': ['vegetarian', 'vegan'],
        'is_vegetarian': True,
        'is_vegan': True,
        'serving_size': '2 cups raw',
    },
    {
        'name': 'Garbanzo Beans (Salad Bar)',
        'station': 'Salad Stop',
        'calories': 130.0, 'protein': 7.0, 'carbs': 22.0, 'fat': 2.0, 'sugar': 1.0,
        'ingredients': 'Prepared Garbanzo Beans (Chickpeas, Water, Salt).',
        'allergens': ['vegetarian', 'vegan'],
        'is_vegetarian': True,
        'is_vegan': True,
        'serving_size': '0.5 cup',
    },
    {
        'name': 'Hard Boiled Eggs (Salad Bar)',
        'station': 'Salad Stop',
        'calories': 155.0, 'protein': 12.5, 'carbs': 0.6, 'fat': 11.0, 'sugar': 0.6,
        'ingredients': 'Hard Cooked Whole Eggs.',
        'allergens': ['eggs', 'vegetarian'],
        'is_vegetarian': True,
        'is_vegan': False,
        'serving_size': '2 eggs',
    },
    {
        'name': 'Diced Cucumbers (Salad Bar)',
        'station': 'Salad Stop',
        'calories': 15.0, 'protein': 0.6, 'carbs': 3.0, 'fat': 0.1, 'sugar': 1.5,
        'ingredients': 'Fresh Cucumbers.',
        'allergens': ['vegetarian', 'vegan'],
        'is_vegetarian': True,
        'is_vegan': True,
        'serving_size': '0.5 cup diced',
    },
    {
        'name': 'Grape Tomatoes (Salad Bar)',
        'station': 'Salad Stop',
        'calories': 25.0, 'protein': 1.0, 'carbs': 5.0, 'fat': 0.2, 'sugar': 3.0,
        'ingredients': 'Fresh Grape Tomatoes.',
        'allergens': ['vegetarian', 'vegan'],
        'is_vegetarian': True,
        'is_vegan': True,
        'serving_size': '0.5 cup',
    },
    {
        'name': 'Matchstick Carrots (Salad Bar)',
        'station': 'Salad Stop',
        'calories': 30.0, 'protein': 0.7, 'carbs': 7.0, 'fat': 0.2, 'sugar': 3.5,
        'ingredients': 'Shredded Matchstick Carrots.',
        'allergens': ['vegetarian', 'vegan'],
        'is_vegetarian': True,
        'is_vegan': True,
        'serving_size': '0.5 cup',
    },
    {
        'name': 'Broccoli Florets (Salad Bar)',
        'station': 'Salad Stop',
        'calories': 30.0, 'protein': 2.5, 'carbs': 6.0, 'fat': 0.3, 'sugar': 1.5,
        'ingredients': 'Raw Fresh Broccoli Florets.',
        'allergens': ['vegetarian', 'vegan'],
        'is_vegetarian': True,
        'is_vegan': True,
        'serving_size': '1 cup',
    },
    {
        'name': 'Sliced Fresh Mushrooms (Salad Bar)',
        'station': 'Salad Stop',
        'calories': 20.0, 'protein': 2.2, 'carbs': 3.0, 'fat': 0.2, 'sugar': 1.5,
        'ingredients': 'Raw Sliced Mushrooms.',
        'allergens': ['vegetarian', 'vegan'],
        'is_vegetarian': True,
        'is_vegan': True,
        'serving_size': '0.75 cup',
    },
    {
        'name': 'Olive Oil (Extra Virgin) (Salad Bar)',
        'station': 'Salad Stop',
        'calories': 120.0, 'protein': 0.0, 'carbs': 0.0, 'fat': 14.0, 'sugar': 0.0,
        'ingredients': '100% Extra Virgin Olive Oil.',
        'allergens': ['vegetarian', 'vegan'],
        'is_vegetarian': True,
        'is_vegan': True,
        'serving_size': '1 tbsp',
    },
    {
        'name': 'Balsamic Vinegar (Salad Bar)',
        'station': 'Salad Stop',
        'calories': 15.0, 'protein': 0.0, 'carbs': 3.0, 'fat': 0.0, 'sugar': 3.0,
        'ingredients': 'Balsamic Vinegar, Wine Vinegar.',
        'allergens': ['vegetarian', 'vegan'],
        'is_vegetarian': True,
        'is_vegan': True,
        'serving_size': '1 tbsp',
    },
    {
        'name': 'Cottage Cheese (Salad Bar)',
        'station': 'Salad Stop',
        'calories': 110.0, 'protein': 13.0, 'carbs': 4.0, 'fat': 4.5, 'sugar': 3.0,
        'ingredients': 'Pasteurized Skim Milk, Milk, Cream, Salt.',
        'allergens': ['milk', 'vegetarian'],
        'is_vegetarian': True,
        'is_vegan': False,
        'serving_size': '0.5 cup',
    },
]

CAMPUS_PERMANENT_BREAKFAST_STAPLES = [
    {
        'name': 'Hard Cooked Eggs',
        'station': 'BoilerQ',
        'calories': 155.0, 'protein': 12.5, 'carbs': 0.6, 'fat': 11.0, 'sugar': 0.6,
        'ingredients': 'Hard Cooked Whole Eggs.',
        'allergens': ['eggs', 'vegetarian'],
        'is_vegetarian': True,
        'is_vegan': False,
        'serving_size': '2 eggs',
    },
    {
        'name': 'Oatmeal',
        'station': 'Salami and Swiss',
        'calories': 160.0, 'protein': 5.5, 'carbs': 28.0, 'fat': 2.5, 'sugar': 0.5,
        'ingredients': 'Whole Grain Rolled Oats, Water, Iodized Salt.',
        'allergens': ['gluten', 'vegetarian', 'vegan'],
        'is_vegetarian': True,
        'is_vegan': True,
        'serving_size': '1 bowl (8 oz)',
    },
    {
        'name': 'Fresh Blueberries',
        'station': 'Salami and Swiss',
        'calories': 40.0, 'protein': 0.5, 'carbs': 10.0, 'fat': 0.2, 'sugar': 7.0,
        'ingredients': 'Fresh Blueberries.',
        'allergens': ['vegetarian', 'vegan'],
        'is_vegetarian': True,
        'is_vegan': True,
        'serving_size': '0.5 cup',
    },
    {
        'name': 'Kiwi',
        'station': 'Salami and Swiss',
        'calories': 45.0, 'protein': 0.8, 'carbs': 11.0, 'fat': 0.4, 'sugar': 6.5,
        'ingredients': 'Fresh Raw Sliced Kiwi.',
        'allergens': ['vegetarian', 'vegan'],
        'is_vegetarian': True,
        'is_vegan': True,
        'serving_size': '1 medium kiwi',
    },
]

HILLENBRAND_SAFEBYTES_STAPLES = [
    {
        'name': 'SafeBytes Grilled Chicken Breast',
        'station': 'SafeBytes - Top 9 Free',
        'calories': 170.0, 'protein': 32.0, 'carbs': 0.0, 'fat': 4.0, 'sugar': 0.0,
        'ingredients': 'Chicken Breast, Sea Salt, Black Pepper, Olive Oil.',
        'allergens': [],
        'is_vegetarian': False,
        'is_vegan': False,
        'serving_size': '1 breast (5 oz)',
    },
    {
        'name': 'SafeBytes Steamed Broccoli Florets',
        'station': 'SafeBytes - Top 9 Free',
        'calories': 35.0, 'protein': 2.5, 'carbs': 6.0, 'fat': 0.4, 'sugar': 1.5,
        'ingredients': 'Broccoli Florets.',
        'allergens': ['vegetarian', 'vegan'],
        'is_vegetarian': True,
        'is_vegan': True,
        'serving_size': '1 cup',
    },
    {
        'name': 'SafeBytes Steamed Brown Rice',
        'station': 'SafeBytes - Top 9 Free',
        'calories': 215.0, 'protein': 5.0, 'carbs': 45.0, 'fat': 1.8, 'sugar': 0.5,
        'ingredients': 'Whole Grain Brown Rice, Water.',
        'allergens': ['vegetarian', 'vegan'],
        'is_vegetarian': True,
        'is_vegan': True,
        'serving_size': '1 cup cooked',
    },
    {
        'name': 'SafeBytes Roasted Sweet Potatoes',
        'station': 'SafeBytes - Top 9 Free',
        'calories': 130.0, 'protein': 2.0, 'carbs': 28.0, 'fat': 1.5, 'sugar': 6.0,
        'ingredients': 'Sweet Potatoes, Olive Oil, Sea Salt.',
        'allergens': ['vegetarian', 'vegan'],
        'is_vegetarian': True,
        'is_vegan': True,
        'serving_size': '0.75 cup',
    },
]


def _unpack_composite_items(base_item: dict) -> list[dict]:
    # Guard: If already a recognized staple or individual component, never re-unpack
    if base_item.get('is_staple'):
        return [base_item]

    name_raw = (base_item.get('name') or '').strip()
    name_lower = name_raw.lower()
    station_lower = (base_item.get('station') or '').lower().strip()

    # Guard: If item contains parentheses (e.g. 'Fresh Baby Spinach (Salad Bar)'), it is an individual food, not the composite bar line item!
    if '(' in name_raw and ')' in name_raw:
        direct_match = _match_fallback_macro(base_item['name'])
        if direct_match and base_item.get('calories', 0.0) == 0.0 and base_item.get('protein', 0.0) == 0.0:
            item_copy = dict(base_item)
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

    # Deconstruct composite 'Salad Bar' line items from Purdue API into individual whole food staples
    # Only match exact composite station or menu headers like "Salad Bar" or "Daily Salad Bar Selection"
    if name_lower in ('salad bar', 'daily salad bar selection', 'salad bar selection', 'daily salad bar'):
        unpacked = []
        for staple in CAMPUS_PERMANENT_SALAD_STAPLES:
            item_copy = dict(staple)
            item_copy.update({
                'location': base_item.get('location', 'Unknown'),
                'meal_period': base_item.get('meal_period', 'Unknown'),
                'hours_status': base_item.get('hours_status', 'Unknown'),
                'closing_time': base_item.get('closing_time', ''),
                'start_time': base_item.get('start_time', ''),
                'end_time': base_item.get('end_time', ''),
                'station': base_item.get('station', 'Salad Stop'),
                'used_fallback': True,
                'is_staple': True,
            })
            unpacked.append(item_copy)
        return unpacked

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


def ensure_campus_permanent_staples(items: list[dict]) -> list[dict]:
    """
    Guarantees verified whole-food permanent campus staples exist for every dining court session:
    - Every open Lunch / Late Lunch / Dinner / Brunch court has the permanent fresh Salad Bar selection.
    - Every open Breakfast court has Hard Cooked Eggs, Oatmeal, and Fresh Fruit.
    - Hillenbrand SafeBytes staples are available when Hillenbrand is open.
    """
    if not items:
        return []

    sessions: dict[tuple[str, str], list[dict]] = {}
    for it in items:
        loc = it.get('location') or 'Unknown'
        mp = it.get('meal_period') or 'Meal'
        sessions.setdefault((loc, mp), []).append(it)

    result = list(items)

    for (loc, mp), session_items in sessions.items():
        mp_lower = mp.strip().lower()
        hours_status = session_items[0].get('hours_status', 'Unknown')
        closing_time = session_items[0].get('closing_time', '')
        start_time = session_items[0].get('start_time', '')
        end_time = session_items[0].get('end_time', '')

        item_names_lower = {it.get('name', '').lower() for it in session_items}

        # 1. Lunch / Dinner / Late Lunch / Brunch -> Salad Bar Staples
        if any(period in mp_lower for period in ('lunch', 'dinner', 'brunch')):
            has_salad_staples = any(
                'spinach' in n or 'garbanzo' in n or 'hard boiled egg' in n or '(salad bar)' in n
                for n in item_names_lower
            )
            if not has_salad_staples:
                for staple in CAMPUS_PERMANENT_SALAD_STAPLES:
                    staple_record = dict(staple)
                    staple_record.update({
                        'location': loc,
                        'meal_period': mp,
                        'hours_status': hours_status,
                        'closing_time': closing_time,
                        'start_time': start_time,
                        'end_time': end_time,
                        'used_fallback': True,
                        'is_staple': True,
                    })
                    result.append(staple_record)

        # 2. Breakfast -> Hard Cooked Eggs, Oatmeal, Fruit
        if 'breakfast' in mp_lower:
            has_breakfast_eggs = any('hard cooked egg' in n or 'hard boiled egg' in n for n in item_names_lower)
            if not has_breakfast_eggs:
                for staple in CAMPUS_PERMANENT_BREAKFAST_STAPLES:
                    if staple['name'].lower() not in item_names_lower:
                        staple_record = dict(staple)
                        staple_record.update({
                            'location': loc,
                            'meal_period': mp,
                            'hours_status': hours_status,
                            'closing_time': closing_time,
                            'start_time': start_time,
                            'end_time': end_time,
                            'used_fallback': True,
                            'is_staple': True,
                        })
                        result.append(staple_record)

        # 3. Hillenbrand -> SafeBytes staples
        if loc.strip().lower() == 'hillenbrand' and any(period in mp_lower for period in ('lunch', 'dinner')):
            has_safebytes = any('safebytes' in (it.get('station') or '').lower() or 'safebytes' in (it.get('name') or '').lower() for it in session_items)
            if not has_safebytes:
                for staple in HILLENBRAND_SAFEBYTES_STAPLES:
                    staple_record = dict(staple)
                    staple_record.update({
                        'location': loc,
                        'meal_period': mp,
                        'hours_status': hours_status,
                        'closing_time': closing_time,
                        'start_time': start_time,
                        'end_time': end_time,
                        'used_fallback': True,
                        'is_staple': True,
                        'is_safebytes': True,
                    })
                    result.append(staple_record)

    return result


def hydrate_missing_macros(items: list[dict], inject_permanent_staples: bool = False) -> list[dict]:
    # 1. Unpack composite items (like 'Salad Bar' or 'Deli Bar') into individual items
    unpacked_items = []
    for it in items:
        unpacked_items.extend(_unpack_composite_items(it))

    # 2. Optionally ensure campus permanent staples for real dining court sessions
    processed_items = ensure_campus_permanent_staples(unpacked_items) if inject_permanent_staples else unpacked_items

    hydrated = []
    for item in processed_items:
        copy_item = dict(item)
        copy_item.setdefault('allergens', [])
        copy_item.setdefault('is_vegetarian', None)
        copy_item.setdefault('is_vegan', None)
        if copy_item['calories'] == 0.0 and copy_item['protein'] == 0.0:
            name_lower = copy_item['name'].lower().strip()
            if name_lower not in STATION_HEADER_NAMES:
                for kw, (cal, pro, carb, fat, sug) in ORDERED_KEYWORD_MACROS:
                    if re.search(rf'\b{re.escape(kw)}(?:s|es)?\b', name_lower):
                        copy_item['calories'] = cal
                        copy_item['protein'] = pro
                        copy_item['carbs'] = carb
                        copy_item['fat'] = fat
                        copy_item['sugar'] = sug
                        copy_item['used_fallback'] = True
                        break
        hydrated.append(copy_item)

    # 3. Deduplicate by (location, meal_period, name, station) to prevent explosive memory bloat
    seen = set()
    deduped = []
    for item in hydrated:
        key = (
            item.get('location', ''),
            item.get('meal_period', ''),
            item.get('name', ''),
            item.get('station', ''),
        )
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


_thread_local = threading.local()
_GLOBAL_ITEM_DETAIL_CACHE: dict[str, dict] = {}
_DETAIL_CACHE_LOCK = threading.Lock()


def _get_thread_session() -> rq.Session:
    if not hasattr(_thread_local, 'session'):
        session = rq.Session()
        session.headers.update({'Accept': 'application/json'})
        adapter = rq.adapters.HTTPAdapter(pool_connections=25, pool_maxsize=25, max_retries=2)
        session.mount('https://', adapter)
        session.mount('http://', adapter)
        _thread_local.session = session
    return _thread_local.session


def _fetch_single_item_detail(item_id: str) -> tuple[str, Optional[dict]]:
    with _DETAIL_CACHE_LOCK:
        if item_id in _GLOBAL_ITEM_DETAIL_CACHE:
            return item_id, _GLOBAL_ITEM_DETAIL_CACHE[item_id]

    detail_url = f'https://api.hfs.purdue.edu/menus/v2/items/{item_id}'
    session = _get_thread_session()
    try:
        res = session.get(detail_url, timeout=8)
        if res.status_code == 200:
            data = res.json()
            with _DETAIL_CACHE_LOCK:
                _GLOBAL_ITEM_DETAIL_CACHE[item_id] = data
            return item_id, data
    except (rq.exceptions.RequestException, ValueError):
        pass
    return item_id, None


def fetch_detailed_purdue_menu(location: str, target_date: Optional[str] = None) -> list[dict]:
    date_str = target_date or get_purdue_now().strftime('%Y-%m-%d')
    url = f'https://api.hfs.purdue.edu/menus/v2/locations/{location}/{date_str}'
    session = _get_thread_session()

    try:
        response = session.get(url, timeout=12)
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
    with _DETAIL_CACHE_LOCK:
        for iid in unique_item_ids:
            if iid in _GLOBAL_ITEM_DETAIL_CACHE:
                details_by_id[iid] = _GLOBAL_ITEM_DETAIL_CACHE[iid]

    needed_ids = [iid for iid in unique_item_ids if iid not in details_by_id]
    if needed_ids:
        with ThreadPoolExecutor(max_workers=min(16, len(needed_ids))) as executor:
            futures = [
                executor.submit(_fetch_single_item_detail, iid)
                for iid in needed_ids
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
                    serving_size = (detail_data.get('ServingSize') or '').strip()
                    serving_unit = (detail_data.get('ServingUnit') or '').strip()
                    if serving_unit:
                        serving_size = f'{serving_size} {serving_unit}'.strip()
                    if not serving_size:
                        serving_size = 'N/A'
                    ingredients = (detail_data.get('Ingredients') or '').strip() or 'N/A'

                    nutrients = detail_data.get('Nutrition') or detail_data.get('Nutrients') or []
                    for n in nutrients:
                        n_name = (n.get('Name') or '').strip().lower()
                        if n_name == 'serving size':
                            api_serving = n.get('LabelValue') or n.get('Value')
                            if api_serving and str(api_serving).strip().upper() not in ('N/A', 'NONE', ''):
                                serving_size = str(api_serving).strip()
                        raw_val = n.get('Value')
                        if raw_val is None:
                            raw_val = n.get('LabelValue')
                        n_val = _parse_numeric_value(raw_val)
                        if 'calorie' in n_name and 'fat' not in n_name:
                            calories = n_val
                            has_api_nutrients = True
                        elif 'protein' in n_name:
                            protein = n_val
                            has_api_nutrients = True
                        elif 'carbohydrate' in n_name:
                            carbs = n_val
                        elif n_name in ('total fat', 'fat'):
                            fat = n_val
                        elif 'sugar' in n_name:
                            sugar = max(sugar, n_val)

                used_fallback = False
                if not has_api_nutrients or (calories == 0.0 and protein == 0.0 and carbs == 0.0 and fat == 0.0):
                    fallback = _match_fallback_macro(item_name)
                    if fallback:
                        calories = fallback['calories']
                        protein = fallback['protein']
                        carbs = fallback['carbs']
                        fat = fallback['fat']
                        sugar = fallback['sugar']
                        if ingredients == 'N/A':
                            ingredients = fallback['ingredients']
                        if str(serving_size).strip().upper() in ('N/A', '', 'NONE') and fallback.get('serving_size'):
                            serving_size = fallback['serving_size']
                        used_fallback = True
                else:
                    if str(serving_size).strip().upper() in ('N/A', '', 'NONE'):
                        fallback = _match_fallback_macro(item_name)
                        if fallback and fallback.get('serving_size'):
                            serving_size = fallback['serving_size']

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
                    'serving_size': serving_size,
                }

                normalized_items.append(base_record)

    return hydrate_missing_macros(normalized_items)


_IN_MEMORY_DAILY_MENU_CACHE: dict[tuple[str, tuple[str, ...]], list[dict]] = {}


def get_daily_menus(
    locations: Optional[list[str]] = None,
    force_refresh: bool = False,
    target_date: Optional[str] = None,
) -> tuple[list[dict], bool]:
    date_str = target_date or get_purdue_now().strftime('%Y-%m-%d')
    cache_path = os.path.join(BASE_DIR, f'purdue_menu_cache_{date_str}.json')
    target_locations = list(locations or DEFAULT_DINING_COURTS)
    allowed_set = set(target_locations)
    mem_key = (date_str, tuple(sorted(target_locations)))

    # 1. Fast in-memory RAM lookup (instant sub-millisecond response)
    if not force_refresh and mem_key in _IN_MEMORY_DAILY_MENU_CACHE:
        return list(_IN_MEMORY_DAILY_MENU_CACHE[mem_key]), True

    # 2. Secondary local disk cache lookup
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
                    hydrated = hydrate_missing_macros(filtered, inject_permanent_staples=True)
                    _IN_MEMORY_DAILY_MENU_CACHE[mem_key] = hydrated
                    return list(hydrated), True
            elif isinstance(raw_cache, list) and raw_cache:
                filtered = [it for it in raw_cache if it.get('location') in allowed_set]
                if filtered:
                    hydrated = hydrate_missing_macros(filtered, inject_permanent_staples=True)
                    _IN_MEMORY_DAILY_MENU_CACHE[mem_key] = hydrated
                    return list(hydrated), True
        except (OSError, ValueError):
            pass

    # 3. Live fetch from Purdue HFS v2 API
    all_items = []
    with ThreadPoolExecutor(max_workers=len(target_locations) or 1) as executor:
        location_futures = [
            executor.submit(fetch_detailed_purdue_menu, loc, date_str)
            for loc in target_locations
        ]
        for future in as_completed(location_futures):
            all_items.extend(future.result())

    hydrated_items = hydrate_missing_macros(all_items, inject_permanent_staples=True)

    if hydrated_items:
        try:
            envelope = {
                'date': date_str,
                'locations': target_locations,
                'items': hydrated_items,
            }
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(envelope, f, indent=2)
        except OSError:
            pass
        _IN_MEMORY_DAILY_MENU_CACHE[mem_key] = hydrated_items

    return list(hydrated_items), False


# ==============================================================================
# MODULE 2: EXPANDED USDA DRI & SINGLE-MEAL MACRO CALCULATOR (WITH AGE SAFETY)
# ==============================================================================

def calculate_meal_targets(
    sex: Optional[str] = None,
    age: Optional[int] = None,
    weight_lbs: Optional[float] = None,
    height_in: Optional[float] = None,
    activity_level: Optional[str] = None,
    meals_per_day: Optional[int] = None,
    meal_goal: str = 'Balanced Maintenance',
    health_intensity: str = 'High',
    meal_period: str = 'Lunch',
    feet: Optional[int] = None,
    inches: Optional[int] = None,
) -> dict:
    """
    Calculates Mifflin-St Jeor DRI daily targets and meal-period-weighted targets:
    1. Converts user inputs safely with sensible defaults:
       - weight_kg = weight_lbs * 0.453592 (default 160.0 lbs)
       - height_cm = (feet * 12 + inches) * 2.54 or height_in * 2.54 (default 68.0 in)
       - age = 20 (default college age if omitted)
    2. BMR via Mifflin-St Jeor:
       - Male: (10 * weight_kg) + (6.25 * height_cm) - (5 * age) + 5
       - Female: (10 * weight_kg) + (6.25 * height_cm) - (5 * age) - 161
       - Unspecified/Other: average (-78)
    3. TDEE:
       - sedentary: 1.35, moderate: 1.55 (default), active: 1.75
    4. Goal offset:
       - lose/cut: tdee - 450 (safeguarded for minors < 18), floored at 1400 kcal
       - maintain: tdee, floored at 1400 kcal
       - gain/bulk: tdee + 350, floored at 1400 kcal
    5. Split daily calories across meals_per_day (default 2):
       - If meals_per_day == 2: 0.50 per meal
       - If meals_per_day == 3: 0.25 for Breakfast, 0.375 for Lunch/Late Lunch/Dinner
       - Otherwise: 1.0 / meals_per_day
    6. Daily protein:
       - weight_lbs * 0.95 if cutting, else weight_lbs * 0.80
       - split by the same meal-period ratio to get target_meal_calories and target_meal_protein
    """
    safe_age = int(age) if (age is not None and int(age) > 0) else 20
    is_minor = safe_age < 18

    safe_weight_lbs = float(weight_lbs) if (weight_lbs is not None and float(weight_lbs) > 0) else 160.0
    weight_kg = safe_weight_lbs * 0.453592

    if feet is not None or inches is not None:
        tot_inches = (int(feet or 0) * 12) + int(inches or 0)
        safe_height_in = float(tot_inches) if tot_inches > 0 else 68.0
    elif height_in is not None and float(height_in) > 0:
        safe_height_in = float(height_in)
    else:
        safe_height_in = 68.0

    height_cm = safe_height_in * 2.54

    sex_norm = str(sex or '').strip().upper()
    if sex_norm.startswith('M'):
        bmr = (10.0 * weight_kg) + (6.25 * height_cm) - (5.0 * safe_age) + 5.0
        daily_aha_sugar_cap = 36.0
    elif sex_norm.startswith('F'):
        bmr = (10.0 * weight_kg) + (6.25 * height_cm) - (5.0 * safe_age) - 161.0
        daily_aha_sugar_cap = 25.0
    else:
        bmr = (10.0 * weight_kg) + (6.25 * height_cm) - (5.0 * safe_age) - 78.0
        daily_aha_sugar_cap = 30.0

    act_norm = str(activity_level or '').strip().lower()
    if 'sedentary' in act_norm:
        activity_factor = 1.35
    elif 'active' in act_norm:
        activity_factor = 1.75
    else:
        activity_factor = 1.55

    tdee = bmr * activity_factor

    goal_norm = str(meal_goal or '').strip().lower()
    is_low_carb = any(k in goal_norm for k in ('low-carb', 'low carb', 'blood sugar', 'keto', 'diabetic'))
    is_cutting = any(k in goal_norm for k in ('cut', 'lose', 'loss', 'fat loss', 'lean'))
    is_bulking = any(k in goal_norm for k in ('gain', 'bulk', 'muscle', 'high protein'))
    is_endurance = any(k in goal_norm for k in ('athletic', 'endurance', 'energy', 'runner'))

    safety_note = 'Personalized dining court portion sizing based on Mifflin-St Jeor DRI calculation.'
    if is_cutting:
        if is_minor:
            daily_calories = max(1400.0, tdee)
            safety_note = (
                'Calorie deficits are disabled for users under 18; showing balanced '
                'maintenance portions. Consult a healthcare provider for personalized guidance.'
            )
        else:
            daily_calories = max(1400.0, tdee - 450.0)
    elif is_bulking:
        daily_calories = max(1400.0, tdee + 350.0)
    elif is_endurance:
        daily_calories = max(1400.0, tdee + 200.0)
    else:
        daily_calories = max(1400.0, tdee)

    meals = max(1, int(meals_per_day or 2))
    mp_norm = str(meal_period or '').strip().lower()
    if meals == 2:
        meal_ratio = 0.50
    elif meals == 3:
        if 'breakfast' in mp_norm:
            meal_ratio = 0.25
        else:
            meal_ratio = 0.375
    else:
        meal_ratio = 1.0 / float(meals)

    target_meal_calories = daily_calories * meal_ratio

    # Goal-tailored protein targets
    if is_bulking:
        daily_protein = safe_weight_lbs * 1.00
    elif is_cutting:
        daily_protein = safe_weight_lbs * 0.95
    elif is_low_carb:
        daily_protein = safe_weight_lbs * 0.95
    elif is_endurance:
        daily_protein = safe_weight_lbs * 0.80
    else:
        daily_protein = safe_weight_lbs * 0.80

    target_meal_protein = daily_protein * meal_ratio

    # Goal-tailored macro distributions
    if is_low_carb:
        c_pct = 0.18
        f_pct = 0.48
        c_cal = target_meal_calories * c_pct
        f_cal = target_meal_calories * f_pct
        carbs_target = max(c_cal / 4.0, 20.0)
        fat_target = max(f_cal / 9.0, 15.0)
        carbs_min = 15.0
        carbs_max = min(50.0, max(25.0, (target_meal_calories * 0.22) / 4.0))
        fat_min = (target_meal_calories * 0.35) / 9.0
        fat_max = (target_meal_calories * 0.60) / 9.0
    elif is_endurance:
        c_pct = 0.58
        f_pct = 0.22
        c_cal = target_meal_calories * c_pct
        f_cal = target_meal_calories * f_pct
        carbs_target = max(c_cal / 4.0, 40.0)
        fat_target = max(f_cal / 9.0, 10.0)
        carbs_min = (target_meal_calories * 0.45) / 4.0
        carbs_max = (target_meal_calories * 0.68) / 4.0
        fat_min = (target_meal_calories * 0.15) / 9.0
        fat_max = (target_meal_calories * 0.30) / 9.0
    elif is_cutting:
        c_pct = 0.38
        f_pct = 0.26
        c_cal = target_meal_calories * c_pct
        f_cal = target_meal_calories * f_pct
        carbs_target = max(c_cal / 4.0, 25.0)
        fat_target = max(f_cal / 9.0, 10.0)
        carbs_min = (target_meal_calories * 0.25) / 4.0
        carbs_max = (target_meal_calories * 0.45) / 4.0
        fat_min = (target_meal_calories * 0.18) / 9.0
        fat_max = (target_meal_calories * 0.35) / 9.0
    elif is_bulking:
        c_pct = 0.46
        f_pct = 0.26
        c_cal = target_meal_calories * c_pct
        f_cal = target_meal_calories * f_pct
        carbs_target = max(c_cal / 4.0, 30.0)
        fat_target = max(f_cal / 9.0, 10.0)
        carbs_min = (target_meal_calories * 0.32) / 4.0
        carbs_max = (target_meal_calories * 0.55) / 4.0
        fat_min = (target_meal_calories * 0.18) / 9.0
        fat_max = (target_meal_calories * 0.35) / 9.0
    else:
        # Balanced maintenance
        c_pct = 0.45
        f_pct = 0.28
        c_cal = target_meal_calories * c_pct
        f_cal = target_meal_calories * f_pct
        carbs_target = max(c_cal / 4.0, 30.0)
        fat_target = max(f_cal / 9.0, 10.0)
        carbs_min = (target_meal_calories * 0.30) / 4.0
        carbs_max = (target_meal_calories * 0.55) / 4.0
        fat_min = (target_meal_calories * 0.20) / 9.0
        fat_max = (target_meal_calories * 0.35) / 9.0

    daily_sugar_max = min(daily_aha_sugar_cap, 20.0) if health_intensity.strip().lower() in ('high', 'extreme') else daily_aha_sugar_cap

    return {
        'goal_label': meal_goal,
        'is_low_carb': is_low_carb,
        'is_cutting': is_cutting,
        'is_bulking': is_bulking,
        'is_endurance': is_endurance,
        'is_minor_safeguarded': is_minor,
        'disclaimer': safety_note,
        'daily': {
            'bmr': round(bmr, 1),
            'tdee': round(tdee, 1),
            'calories': round(daily_calories, 1),
            'protein_target': round(daily_protein, 1),
            'carbs_target': round((daily_calories * c_pct) / 4.0, 1),
            'fat_target': round((daily_calories * f_pct) / 9.0, 1),
            'sugar_max': round(daily_sugar_max, 1),
        },
        'per_meal': {
            'calories': round(target_meal_calories, 1),
            'protein_min': round(target_meal_protein * 0.8, 1),
            'protein_target': round(target_meal_protein, 1),
            'protein_max': round(target_meal_protein * 1.3, 1),
            'carbs_min': round(carbs_min, 1),
            'carbs_target': round(carbs_target, 1),
            'carbs_max': round(carbs_max, 1),
            'fat_min': round(fat_min, 1),
            'fat_target': round(fat_target, 1),
            'fat_max': round(fat_max, 1),
            'sugar_max': round(daily_sugar_max / float(meals), 1),
            'is_low_carb': is_low_carb,
            'is_cutting': is_cutting,
            'is_bulking': is_bulking,
            'is_endurance': is_endurance,
            'goal_label': meal_goal,
        },
    }


def _snap_multiplier(val: float, max_mult: float = 2.5, min_mult: float = 0.5) -> float:
    """Snaps a portion multiplier to 0.5 increments within [min_mult, max_mult]."""
    snapped = round(float(val) * 2.0) / 2.0
    return max(min_mult, min(max_mult, snapped))


def generate_portion_label(item: dict, multiplier: float) -> str:
    """
    Generates human dining-court portion labels based on item category and serving unit.
    Returns empty string if multiplier is 1.0. Never outputs '2x', '1.5x', or raw decimal multipliers.
    """
    if abs(multiplier - 1.0) < 0.05:
        return ""

    name_lower = (item.get('name') or '').lower()
    ss_lower = (item.get('serving_size') or '').lower()
    role = (item.get('food_type') or item.get('role') or '').lower()
    combined = f"{name_lower} {ss_lower}"

    # 1. Leafy greens / Salad Bar Bases
    is_leafy = any(k in combined for k in ('spinach', 'romaine', 'mesclun', 'greens', 'lettuce', 'spring mix', 'kale', 'salad bar')) or 'salad_base' in role
    if is_leafy:
        if multiplier <= 0.5:
            return "1 small handful"
        elif multiplier <= 1.5:
            return "1.5 handfuls"
        elif multiplier <= 2.0:
            return "2 handfuls"
        elif multiplier <= 2.5:
            return "2.5 handfuls"
        else:
            return "1 large bowl"

    # 2. Specific countable items
    count_noun = None
    if 'scrambled' in combined:
        count_noun = None
    elif 'corn dog' in combined or 'corndog' in combined:
        count_noun = ('corn dog', 'corn dogs')
    elif 'hot dog' in combined or 'hotdog' in combined:
        count_noun = ('hot dog', 'hot dogs')
    elif 'meatball' in combined:
        count_noun = ('meatball', 'meatballs')
    elif 'nugget' in combined:
        count_noun = ('nugget', 'nuggets')
    elif 'pancake' in combined:
        count_noun = ('pancake', 'pancakes')
    elif 'french toast stick' in combined or ('stick' in combined and 'french toast' in combined):
        count_noun = ('stick', 'sticks')
    elif 'samosa' in combined:
        count_noun = ('samosa', 'samosas')
    elif 'breast' in combined:
        count_noun = ('breast', 'breasts')
    elif 'patty' in combined or 'burger' in combined:
        count_noun = ('patty', 'patties')
    elif 'egg' in combined and ('hard' in combined or 'boiled' in combined or 'cooked' in combined):
        count_noun = ('egg', 'eggs')
    elif 'slice' in combined or 'pizza' in combined:
        count_noun = ('slice', 'slices')
    elif 'taco' in combined:
        count_noun = ('taco', 'tacos')
    elif 'cookie' in combined:
        count_noun = ('cookie', 'cookies')
    elif 'brownie' in combined:
        count_noun = ('brownie', 'brownies')
    elif 'muffin' in combined:
        count_noun = ('muffin', 'muffins')
    elif 'roll' in combined or 'dinner roll' in combined:
        count_noun = ('roll', 'rolls')
    elif 'bun' in combined:
        count_noun = ('bun', 'buns')
    elif 'biscuit' in combined:
        count_noun = ('biscuit', 'biscuits')
    elif 'bagel' in combined:
        count_noun = ('bagel', 'bagels')
    elif 'link' in combined or 'sausage' in combined:
        count_noun = ('link', 'links')
    elif 'tender' in combined:
        count_noun = ('tender', 'tenders')
    elif 'drumstick' in combined:
        count_noun = ('drumstick', 'drumsticks')
    elif 'wing' in combined:
        count_noun = ('wing', 'wings')
    elif 'thigh' in combined:
        count_noun = ('thigh', 'thighs')
    elif 'fillet' in combined or 'filet' in combined:
        count_noun = ('filet', 'filets')
    elif any(k in ss_lower for k in ('each', 'piece', 'ea', 'pc')):
        count_noun = ('piece', 'pieces')
    elif any(k in combined for k in ('chicken breast', 'pork chop', 'steak', 'salmon', 'tilapia', 'sandwich', 'burrito', 'quesadilla')):
        count_noun = ('piece', 'pieces')

    if count_noun:
        sing, plur = count_noun
        if multiplier <= 0.5:
            return f"half {sing}"
        elif multiplier == int(multiplier):
            cnt = int(multiplier)
            return f"{cnt} {plur if cnt > 1 else sing}"
        else:
            return f"{multiplier:g} {plur}"

    # 3. Scooped, cup, ladle, or side items (grains, beans, pasta, potatoes, soups, scrambled eggs, roasted veggies)
    is_scoop_or_cup = any(k in combined for k in ('cup', 'scoop', 'ladle', 'oz', 'rice', 'potato', 'grain', 'bean', 'corn', 'soup', 'chili', 'pasta', 'mac', 'scrambled')) or 'carb_side' in role or 'veg_side' in role
    if is_scoop_or_cup:
        if multiplier <= 0.5:
            return "half scoop"
        elif multiplier == 1.5:
            return "1.5 scoops"
        elif multiplier == 2.0:
            return "2 scoops"
        elif multiplier == 2.5:
            return "2.5 scoops"
        elif multiplier >= 3.0:
            return "1 full bowl"
        elif multiplier == int(multiplier):
            return f"{int(multiplier)} scoops"
        else:
            return f"{multiplier:g} scoops"

    # Default fallback
    if multiplier <= 0.5:
        return "half portion"
    elif multiplier == int(multiplier):
        return f"{int(multiplier)} portions"
    else:
        return f"{multiplier:g} portions"


def scale_combo_to_user(combo: dict, per_meal_targets: dict, tier_key: str = 'mid') -> dict:
    """
    Scales a top-3 dining combo to match the user's per-meal calorie & protein targets:
    - Never applies blind uniform multipliers to the whole plate.
    - Locks sauces, dressings, cheese toppings, and dense fats at 1.0 serving.
    - Scales primary protein anchor first to close protein/calorie gap.
    - If calories still needed, scales clean carb/base side (or secondary protein in Pure Health).
    - Snaps multipliers to 0.5 increments (0.5, 1.0, 1.5, 2.0, 2.5, max 3.0 for leafy greens/veggies).
    - Recomputes item macros, portion labels, and parent combo totals.
    """
    items = combo.get('items', [])
    if not items or not per_meal_targets:
        return combo

    target_cal = float(per_meal_targets.get('calories', 600.0))
    target_pro = float(per_meal_targets.get('protein_target', 35.0))

    cur_cal = sum(float(it.get('calories', 0.0)) for it in items)
    cur_pro = sum(float(it.get('protein', 0.0)) for it in items)

    def _is_locked(it: dict) -> bool:
        r = (it.get('food_type') or it.get('role') or '').lower()
        n = (it.get('name') or '').lower()
        if r in ('sauce_dressing', 'fat_topping', 'dessert'):
            return True
        if _is_dessert_item(n):
            return True
        locked_pattern = r'\b(sauces?|dressings?|vinaigrettes?|oils?|butters?|mayo|mayonnaise|cheeses?|gravy|gravies|syrups?|frostings?|dips?|creamers?|sour cream)\b'
        if re.search(locked_pattern, n, re.IGNORECASE) and not any(p in n for p in ('mac & cheese', 'macaroni', 'pizza', 'quesadilla', 'cheeseburger', 'cottage cheese')):
            return True
        return False

    non_locked = [it for it in items if not _is_locked(it)]
    if not non_locked:
        non_locked = list(items)

    protein_candidates = [
        it for it in non_locked
        if (it.get('food_type') or '').lower() in ('protein_entree', 'complete_entree', 'breakfast_entree', 'sandwich')
        or it.get('protein', 0.0) >= 12.0
    ]
    if protein_candidates:
        protein_anchor = max(protein_candidates, key=lambda x: x.get('protein', 0.0))
    else:
        protein_anchor = max(non_locked, key=lambda x: x.get('protein', 0.0))

    p0 = float(protein_anchor.get('protein', 0.0))
    c0 = float(protein_anchor.get('calories', 0.0))
    other_pro = cur_pro - p0
    other_cal = cur_cal - c0

    needed_p = max(5.0, target_pro - other_pro)
    pro_mult_raw = needed_p / max(p0, 1.0) if p0 > 0 else 1.0

    cal_gap = target_cal - cur_cal

    if cal_gap > 220 and pro_mult_raw < 1.4:
        raw_p_mult = max(pro_mult_raw, 1.5)
    elif cal_gap < -220 and pro_mult_raw > 0.6:
        raw_p_mult = min(pro_mult_raw, 0.5)
    else:
        raw_p_mult = pro_mult_raw

    pa_name = (protein_anchor.get('name') or '').lower()
    is_discrete_protein = (
        any(d in pa_name for d in (
            'drumstick', 'wing', 'thigh', 'hard boiled egg', 'hard cooked egg', 'taco', 'cookie',
            'link', 'corn dog', 'corndog', 'hot dog', 'meatball', 'nugget', 'pancake',
            'french toast stick', 'samosa'
        ))
        and 'scrambled' not in pa_name
    )
    if is_discrete_protein:
        if raw_p_mult < 1.4:
            p_mult = 1.0
        elif raw_p_mult < 2.4:
            p_mult = 2.0
        elif raw_p_mult < 3.4:
            p_mult = 3.0
        else:
            p_mult = 4.0
    else:
        p_mult = _snap_multiplier(raw_p_mult, max_mult=2.5, min_mult=0.5)

    multipliers: dict[int, float] = {id(it): 1.0 for it in items}
    multipliers[id(protein_anchor)] = p_mult

    est_cal = (c0 * p_mult) + other_cal
    rem_cal_gap = target_cal - est_cal

    remaining_candidates = [it for it in non_locked if id(it) != id(protein_anchor)]
    if remaining_candidates and (rem_cal_gap > 75 or rem_cal_gap < -80):
        if tier_key == 'extreme':
            carb_candidates = [
                it for it in remaining_candidates
                if any(k in (it.get('name') or '').lower() for k in ('quinoa', 'rice', 'potato', 'bean', 'garbanzo', 'chickpea', 'lentil', 'edamame', 'tofu', 'egg'))
                or (it.get('food_type') or '').lower() in ('carb_side', 'grain', 'complex_carb')
            ]
        else:
            carb_candidates = [
                it for it in remaining_candidates
                if (it.get('food_type') or '').lower() in ('carb_side', 'grain', 'side', 'complex_carb')
                or it.get('carbs', 0.0) >= 15.0
            ]

        if carb_candidates:
            carb_anchor = max(carb_candidates, key=lambda x: x.get('calories', 0.0))
        else:
            carb_anchor = max(remaining_candidates, key=lambda x: x.get('calories', 0.0))

        carb_c0 = float(carb_anchor.get('calories', 0.0))
        if carb_c0 > 15.0:
            raw_carb_mult = 1.0 + (rem_cal_gap / carb_c0)
            ca_name = (carb_anchor.get('name') or '').lower()
            is_discrete_carb = any(d in ca_name for d in (
                'cookie', 'taco', 'roll', 'biscuit', 'link', 'slice', 'corn dog',
                'pancake', 'french toast stick', 'samosa', 'fried pickle'
            ))
            if is_discrete_carb:
                if raw_carb_mult < 1.4:
                    carb_mult = 1.0
                elif raw_carb_mult < 2.4:
                    carb_mult = 2.0
                elif raw_carb_mult < 3.4:
                    carb_mult = 3.0
                else:
                    carb_mult = 4.0
            else:
                carb_mult = _snap_multiplier(raw_carb_mult, max_mult=2.5, min_mult=0.5)

            is_low_carb_mode = bool(per_meal_targets.get('is_low_carb'))
            is_cutting_mode = bool(per_meal_targets.get('is_cutting'))
            if is_low_carb_mode:
                carb_mult = min(carb_mult, 1.0)
            elif is_cutting_mode:
                carb_mult = min(carb_mult, 1.5)

            multipliers[id(carb_anchor)] = carb_mult
            rem_cal_gap -= (carb_mult - 1.0) * carb_c0

    # Leafy greens / veggie check: can scale up to 3.0
    leafy_candidates = [
        it for it in remaining_candidates
        if id(it) not in multipliers or multipliers[id(it)] == 1.0
    ]
    for it in leafy_candidates:
        n_low = (it.get('name') or '').lower()
        if any(k in n_low for k in ('spinach', 'romaine', 'mesclun', 'lettuce', 'spring mix', 'kale', 'greens')):
            if rem_cal_gap > 40 or tier_key == 'extreme':
                multipliers[id(it)] = _snap_multiplier(2.0, max_mult=3.0, min_mult=0.5)
            break

    # Apply multipliers, compute new item macros and natural portion labels
    for it in items:
        m = multipliers.get(id(it), 1.0)
        it['multiplier'] = m
        if abs(m - 1.0) > 0.05:
            it['calories'] = float(round(float(it['calories']) * m))
            it['protein'] = float(round(float(it['protein']) * m))
            it['carbs'] = float(round(float(it['carbs']) * m))
            it['fat'] = float(round(float(it['fat']) * m))
            it['portion_label'] = generate_portion_label(it, m)
            it['is_scaled'] = True
        else:
            it['calories'] = float(round(float(it['calories'])))
            it['protein'] = float(round(float(it['protein'])))
            it['carbs'] = float(round(float(it['carbs'])))
            it['fat'] = float(round(float(it['fat'])))
            it['portion_label'] = ""
            it['is_scaled'] = False

    tot_c = round(sum(it['calories'] for it in items))
    tot_p = round(sum(it['protein'] for it in items))
    tot_cb = round(sum(it['carbs'] for it in items))
    tot_f = round(sum(it['fat'] for it in items))
    tot_s = round(sum(it.get('sugar', 0.0) for it in items))

    combo['totals'] = {
        'calories': float(tot_c),
        'protein': float(tot_p),
        'carbs': float(tot_cb),
        'fat': float(tot_f),
        'sugar': float(tot_s),
    }
    combo['macro_split'] = _compute_macro_split(tot_p, tot_cb, tot_f)
    combo['is_scaled'] = any(it.get('is_scaled') for it in items)

    return combo


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
            if seconds_until_open <= 4500:
                updated['hours_status'] = f'Opens at {formatted_start}'
                open_items.append(updated)
            else:
                updated['hours_status'] = f'Opens at {formatted_start}'
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
    ing_raw = (item.get('ingredients') or '').strip()
    has_real_ing = bool(ing_raw and ing_raw.upper() != 'N/A')

    if has_real_ing:
        return 'verified'

    # Missing or N/A ingredients: apply heuristic fallback
    is_clean_whole, cert_flag, _ = _heuristic_evaluate_missing_ingredients(item)
    if is_clean_whole:
        return 'verified_whole_food'

    if item.get('used_fallback'):
        return 'estimated'

    return 'unknown'


def _sanitize_plant_based_text(text: str) -> str:
    cleaned = text
    for pat in PLANT_BASED_ANALOG_PATTERNS:
        cleaned = re.sub(pat, ' ', cleaned, flags=re.IGNORECASE)
    return cleaned


def _sanitize_non_dairy_text(text: str) -> str:
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


def _is_dessert_item(name_lower: str) -> bool:
    if any(sav in name_lower for sav in ['pot pie', 'shepherd', "shepherd's pie", 'cottage pie', 'quiche', 'savory pie']):
        return False
    if any(re.search(rf'\b{re.escape(d)}s?\b', name_lower) for d in DESSERT_KEYWORDS):
        return True
    if any(ds in name_lower for ds in DESSERT_SALAD_KEYWORDS):
        return True
    return False


def _is_whole_fruit(name_lower: str) -> bool:
    if any(d in name_lower for d in DESSERT_KEYWORDS + NON_WHOLE_FRUIT_MARKERS):
        return False
    return any(fr in name_lower for fr in WHOLE_FRUIT_KEYWORDS)


def _is_standalone_condiment(item: dict) -> bool:
    name_lower = (item.get('name') or '').lower().strip()
    station_lower = (item.get('station') or '').lower().strip()

    if any(k in station_lower for k in ['condiment', 'topping', 'dressing']):
        return True

    entree_contexts = (
        SANDWICH_ENTREE_MARKERS
        + COMPLETE_ENTREE_MARKERS
        + PASTA_ENTREE_MARKERS
        + BOWL_ENTREE_MARKERS
        + BREAKFAST_ENTREE_MARKERS
        + [
            'chicken', 'beef', 'steak', 'pork', 'salmon', 'fish', 'shrimp',
            'turkey', 'tofu', 'tempeh', 'meatball', 'wings', 'wing', 'ribs',
            'nugget', 'tender', 'salad', 'broccoli', 'cauliflower', 'potato',
            'rice', 'noodle'
        ]
    )
    if any(re.search(rf'\b{re.escape(ent)}(?:s|es)?\b', name_lower) for ent in entree_contexts):
        return False

    return any(re.search(rf'\b{re.escape(kw)}s?\b', name_lower) for kw in STANDALONE_CONDIMENT_KEYWORDS)


def _is_dip_or_condiment(item: dict) -> bool:
    if _is_standalone_condiment(item):
        return True
    name_lower = (item.get('name') or '').lower().strip()
    if any(ent in name_lower for ent in SANDWICH_ENTREE_MARKERS + COMPLETE_ENTREE_MARKERS):
        return False
    return any(re.search(rf'\b{re.escape(ds)}s?\b', name_lower) for ds in DIP_SPREAD_KEYWORDS)


def _is_added_oil_or_fat(item: dict) -> bool:
    name_lower = (item.get('name') or '').lower().strip()
    clean_name = re.sub(r'\(salad bar\)', '', name_lower).strip()
    if 'olive oil' in clean_name or 'extra virgin olive oil' in clean_name or 'butter' in clean_name:
        return True
    if any(w in clean_name for w in ['chicken', 'beef', 'steak', 'salmon', 'egg', 'rice', 'broccoli', 'spinach', 'salad']):
        return False
    return any(re.search(rf'\b{re.escape(kw)}s?\b', clean_name) for kw in ADDED_OIL_FAT_KEYWORDS)


def _is_standalone_bakery(item: dict) -> bool:
    name_lower = (item.get('name') or '').lower().strip()

    if any(re.search(rf'\b{re.escape(m)}\b', name_lower) for m in SANDWICH_ENTREE_MARKERS + COMPLETE_ENTREE_MARKERS + BREAKFAST_ENTREE_MARKERS):
        return False

    return any(re.search(rf'\b{re.escape(bk)}\b', name_lower) for bk in STANDALONE_BAKERY_KEYWORDS)


def _build_verified_na_regexes() -> list[re.Pattern]:
    patterns = []
    for vf in VERIFIED_NA_WHOLE_FOODS:
        escaped = re.escape(vf.strip().lower())
        patterns.append(re.compile(rf'\b{escaped}(?:s|es)?\b'))
    return patterns


_VERIFIED_NA_REGEXES = _build_verified_na_regexes()


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

    return any(pat.search(name_lower) for pat in _VERIFIED_NA_REGEXES)


def _heuristic_evaluate_missing_ingredients(item: dict) -> tuple[bool, str, str]:
    """
    Evaluates items whose ingredient list is missing ('N/A' or empty).
    Per Purdue Dining Optimizer rules:
    - If station or item name strongly implies processed preparation, heavy saucing,
      frying, or seed oil use (e.g. battered fish, patties, fried nuggets, creamy commercial dressings,
      stir fry, roasted vegetables cooked with standard oil), flag and exclude from strict modes.
    - If inherently a single-ingredient whole food (raw spinach, whole fruit, boiled eggs,
      plain steamed rice, plain potato, steamed edamame, etc.), permit it with 'verified_whole_food'.
    """
    name_lower = (item.get('name') or '').lower().strip()
    station_lower = (item.get('station') or '').lower().strip()

    # Immediate rejection if processed preparation or seed oils implied
    processed_markers = [
        'battered', 'breaded', 'crispy', 'fried', 'deep fried', 'tempura', 'fritter',
        'patty', 'patties', 'nugget', 'nuggets', 'tender', 'tenders', 'stick', 'sticks',
        'sauce', 'creamy', 'cream', 'dressing', 'marinated', 'glazed', 'glaze', 'gravy',
        'casserole', 'pot pie', 'shepherd', 'sausage', 'bacon', 'hot dog', 'frank',
        'syrup', 'topping', 'waffle', 'pancake', 'french toast', 'biscuit',
        'cookie', 'cake', 'pie', 'brownie', 'donut', 'muffin', 'pastry', 'turnover',
        'croissant', 'danish', 'cinnamon roll', 'aioli', 'mayo', 'mayonnaise',
        'roasted', 'sauteed', 'stir fried', 'stir-fry', 'seasoned'
    ]
    if any(pm in name_lower for pm in processed_markers):
        return False, 'unknown', 'Missing ingredients: implies processed preparation or seed-oil cooking'

    high_risk_stations = ['fryer', 'deep fry', 'granite grill', 'the grill', 'boilerq', 'pizza', 'bakery', 'pastry', 'dessert']
    if any(hrs in station_lower for hrs in high_risk_stations) and not any(pat.search(name_lower) for pat in _VERIFIED_NA_REGEXES):
        return False, 'unknown', 'Missing ingredients from high-risk processed food station'

    # Check if inherently single-ingredient whole food
    if _is_whole_fruit(name_lower) or any(pat.search(name_lower) for pat in _VERIFIED_NA_REGEXES):
        return True, 'verified_whole_food', 'Inherently whole food staple (verified via nutrition heuristic)'

    return False, 'unknown', 'Missing ingredient list: unable to verify seed-oil-free status'


def _compute_nutrient_density_score(item: dict) -> float:
    cal = max(item.get('calories', 0.0), 15.0)
    pro = item.get('protein', 0.0)
    sugar = item.get('sugar', 0.0)
    name_lower = (item.get('name') or '').lower()

    protein_density = min((pro / cal) * 260.0, 52.0)
    score = 42.0 + protein_density

    micro_superfoods = [
        'spinach', 'kale', 'broccoli', 'asparagus', 'brussels', 'cauliflower',
        'salmon', 'egg', 'chickpea', 'garbanzo', 'lentil', 'black bean',
        'edamame', 'olive oil', 'avocado', 'berries', 'blueberry', 'strawberry',
        'greek yogurt', 'cottage cheese', 'quinoa', 'sweet potato', 'green bean',
        'zucchini', 'romaine', 'mixed greens'
    ]
    if any(ms in name_lower for ms in micro_superfoods):
        score += 18.0

    if sugar > 6.0 and not _is_whole_fruit(name_lower):
        score -= min((sugar - 6.0) * 1.5, 16.0)

    return round(max(10.0, min(score, 100.0)), 1)


# ==============================================================================
# YUMMY MODE CROWD-PLEASER SCORING TIERS & MULTIPLIERS
# ==============================================================================

YUMMY_BASE_TIERS = [
    # Tier 1 — Elite Crowd-Pleasers (Base Score: 92–98)
    (98, [
        'chocolate chip cookie', 'warm cookie', 'brownie', 'lava cake',
        'cookie', 'cookies', 'fudge', 'cheesecake', 'cupcake'
    ]),
    (95, [
        'crispy bacon', 'bacon', 'scrambled eggs', 'scrambled egg', 'omelet',
        'omelette', 'breakfast sandwich', 'eggless scrambled'
    ]),
    (94, [
        'lasagna', 'baked ziti', 'meatball sub', 'pepperoni pizza', 'cheese pizza',
        'pizza'
    ]),
    (93, [
        'loaded fries', 'nachos', 'nacho', 'tater tots', 'tots', 'mozzarella sticks',
        'mozzarella stick', 'cheese stick', 'cheese curd'
    ]),
    (92, [
        'spaghetti & meatballs', 'chicken alfredo', 'fettuccine alfredo',
        'mac & cheese', 'macaroni and cheese', 'mac and cheese', 'alfredo'
    ]),

    # Tier 2 — Top Savory Favorites (Base Score: 85–91)
    (90, [
        'burrito bowl', 'burrito', 'quesadilla', 'fajitas', 'fajita',
        'birria', 'carnitas', 'carne asada'
    ]),
    (89, [
        'crispy chicken', 'fried chicken', 'chicken tenders', 'chicken tender',
        'tenders', 'chicken wings', 'chicken wing', 'wings', 'popcorn chicken',
        'orange chicken', 'general tso'
    ]),
    (88, [
        'bbq brisket', 'pulled pork', 'baby back ribs', 'smoked sausage',
        'bbq chicken', 'drumstick', 'chicken drumstick', 'ribs', 'pork potstickers',
        'potstickers', 'potsticker'
    ]),
    (87, [
        'smashburger', 'bacon burger', 'patty melt', 'philly cheesesteak',
        'cheeseburger', 'burger', 'burgers'
    ]),
    (85, [
        'garlic bread', 'breadsticks', 'breadstick', 'biscuits & gravy',
        'waffle', 'waffles', 'french toast', 'pancakes', 'pancake'
    ]),

    # Tier 3 — Solid Classics (Base Score: 75–84)
    (83, [
        'penne rosa', 'pesto pasta', 'ravioli', 'tortellini', 'pasta'
    ]),
    (81, [
        'grilled cheese', 'tomato soup'
    ]),
    (79, [
        'teriyaki chicken', 'beef & broccoli', 'sirloin', 'ribeye', 'steak',
        'myo stir fry', 'stir fry'
    ]),
    (77, [
        'soft serve', 'cinnamon roll', 'ice cream', 'gelato', 'churros', 'churro',
        'pie', 'cherry pie', 'cake', 'carrot cake', 'donut', 'donuts', 'donut holes'
    ]),
    (75, [
        'curly fries', 'mashed potatoes', 'roasted potatoes', 'french fries',
        'fries', 'sidewinder', 'sidewinders', 'tater'
    ]),

    # Tier 4 — Everyday Mains & Sides (Base Score: 60–74)
    (72, [
        'rice bowl', 'fried rice', 'lo mein', 'ramen', 'tacos', 'taco',
        'enchiladas', 'enchilada'
    ]),
    (68, [
        'roast turkey', 'honey glazed ham', 'grilled chicken', 'meatloaf',
        'mango chicken'
    ]),
    (64, [
        'chicken noodle soup', 'chili', 'baked potato'
    ]),
    (60, [
        'dinner roll', 'roll', 'plain rice', 'rice', 'basmati rice', 'jasmine rice'
    ]),
]

HIGH_APPEAL_MODIFIERS = [
    'crispy', 'loaded', 'melted', 'cheesy', 'glazed', 'smoked',
    'garlic', 'butter', 'caramelized', 'fried', 'bacon', 'alfredo',
    'bbq', 'buffalo', 'chocolate'
]

YUMMY_PENALTIES = [
    'steamed', 'plain', 'unseasoned', 'boiled', 'low-fat', 'sugar-free'
]


def compute_item_yummy_score(item: dict) -> float:
    name_lower = (item.get('name') or '').lower().strip()
    base_score = 55.0
    for tier_score, kws in YUMMY_BASE_TIERS:
        if any(kw in name_lower for kw in kws):
            base_score = float(tier_score)
            break

    bonus = sum(5.0 for mod in HIGH_APPEAL_MODIFIERS if mod in name_lower)
    penalty = sum(15.0 for pen in YUMMY_PENALTIES if pen in name_lower)

    if 'tofu' in name_lower and not ('crispy' in name_lower or 'general tso' in name_lower):
        penalty += 15.0

    return round(max(30.0, min(base_score + bonus - penalty, 100.0)), 1)


def compute_combo_yummy_score(slots: list[tuple[str, dict]]) -> float:
    items = [it for _, it in slots]
    names_lower = [(it.get('name') or '').lower().strip() for it in items]
    combined_text = ' '.join(names_lower)

    base_score = 55.0
    for tier_score, kws in YUMMY_BASE_TIERS:
        if any(kw in combined_text for kw in kws):
            base_score = float(tier_score)
            break

    bonus = sum(5.0 for mod in HIGH_APPEAL_MODIFIERS if mod in combined_text)
    penalty = sum(15.0 for pen in YUMMY_PENALTIES if pen in combined_text)

    if 'tofu' in combined_text and not ('crispy' in combined_text or 'general tso' in combined_text):
        penalty += 15.0

    return round(max(30.0, min(base_score + bonus - penalty, 100.0)), 1)


def evaluate_item_health(
    item: dict,
    health_intensity: str,
    narrow_breadth: bool = False,
) -> tuple[bool, float, str]:
    """
    Evaluates individual item eligibility and returns (allowed, raw_quality_score, explanation).
    Healthy ('High') and Pure Health ('Extreme') enforce strict eligibility without exception:
    zero seed oils, zero deep-fried foods, zero standalone desserts, and verified ingredients.
    Balanced ('Mid') allows wholesome real food while excluding desserts and excessive sugar.
    Yummy ('Low') prioritizes culinary appeal.
    """
    tier = health_intensity.strip().lower()
    name_lower = item['name'].lower().strip()
    ing_raw = (item.get('ingredients') or '').strip()
    ing_lower = ing_raw.lower()
    combined_text = f'{name_lower} {ing_lower}'
    certainty = _assess_ingredient_certainty(item)
    station_lower = (item.get('station') or '').lower().strip()
    is_safebytes = 'safebytes' in station_lower

    # SafeBytes station at Hillenbrand is strictly top-9 allergen-free and prepared without seed oils
    if is_safebytes and certainty in ('unknown', 'estimated') and not any(f in name_lower for f in ['fried', 'crispy', 'fritter', 'cookie', 'brownie']):
        certainty = 'verified_whole_food'
        item['_certainty'] = 'verified_whole_food'

    if _is_special_order_item(item):
        return False, 0.0, 'Excluded: custom ticket'
    if name_lower in STATION_HEADER_NAMES:
        return False, 0.0, 'Excluded: station header'
    if _is_standalone_bakery(item) and any(b in name_lower for b in ['hamburger bun', 'hot dog bun', 'sesame bun', 'wheat bun', 'white bun', 'bun', 'buns']):
        return False, 0.0, 'Excluded: standalone bun'

    # Explicit exclusion of standalone sugars, syrups, and zero-macro spices
    if name_lower in ('powdered sugar', 'sugar', 'brown sugar', 'pancake syrup', 'sugar free maple pancake syrup', 'artificial syrup', 'waffle topping', 'sprinkles'):
        return False, 0.0, 'Excluded: refined sugar topping'
    if name_lower in ('crushed red pepper', 'salt', 'black pepper', 'seasoning', 'water', 'ice', 'tea', 'black coffee', 'vinegar'):
        return False, 0.0, 'Negligible macro contribution: standalone spice / beverage'

    is_condiment = _is_standalone_condiment(item)
    is_dip = _is_dip_or_condiment(item) and not is_condiment
    is_added_fat = _is_added_oil_or_fat(item)

    has_seed_oil = any(
        re.search(rf'\b{re.escape(oil)}s?\b', combined_text) for oil in SEED_OILS
    )
    has_sugar_marker = any(s in combined_text for s in HIGH_SUGAR_ADDITIVES)
    has_strict_refined_ing = (
        any(s in ing_lower for s in STRICT_REFINED_SUGAR_INGREDIENTS)
        or any(s in name_lower for s in ('powdered sugar', 'pancake syrup', 'waffle topping', 'icing', 'frosting', 'glaze'))
        or (ing_lower.startswith('sugar') or ', sugar' in ing_lower or 'corn syrup' in ing_lower)
    )
    is_deep_fried = any(f in combined_text for f in DEEP_FRIED_MARKERS)
    has_dye = any(d in combined_text for d in ARTIFICIAL_DYES)
    is_dessert = _is_dessert_item(name_lower)
    whole_fruit = _is_whole_fruit(name_lower) or any(fs in name_lower for fs in FRUIT_SALAD_KEYWORDS)

    if is_condiment:
        if tier in ('high', 'extreme') and not is_added_fat:
            return False, 0.0, f'Excluded from {tier.title()}: standalone condiment or sauce'
        if tier in ('high', 'extreme') and (item.get('sugar', 0.0) > 5.0 or has_sugar_marker or has_seed_oil):
            return False, 0.0, 'Excluded: high-sugar or seed-oil condiment'
        cond_score = 42.0 - min(item.get('sugar', 0.0) * 2.5, 20.0)
        return True, round(max(20.0, cond_score), 1), 'Optional condiment'

    if is_dip:
        if tier in ('high', 'extreme'):
            return False, 0.0, f'Excluded from {tier.title()}: standalone commercial dip'
        return True, 54.0, 'Optional spread/dip'

    # Dry spice rub exemption for whole savory meats (e.g. SafeBytes dry-rubbed drumsticks)
    is_dry_rub_meat = (
        ('dry rub' in ing_lower or 'seasoning rub' in ing_lower or 'spice rub' in ing_lower)
        and item.get('sugar', 0.0) <= 2.5
        and item.get('carbs', 0.0) <= 5.0
        and not has_seed_oil
        and not is_deep_fried
    )
    if is_dry_rub_meat:
        has_strict_refined_ing = False

    has_high_sugar = False if is_dry_rub_meat else (has_strict_refined_ing or ((not whole_fruit) and (
        item.get('sugar', 0.0) > 8.0
        or (has_sugar_marker and item.get('sugar', 0.0) > 4.0)
    )))

    if tier == 'extreme':
        # Pure Health Mode: Strict whole-food nutrient & protein density (ZERO relaxation)
        if has_seed_oil:
            return False, 0.0, 'Excluded: contains seed oils'
        if is_deep_fried:
            return False, 0.0, 'Excluded: deep-fried'
        if is_dessert:
            return False, 0.0, 'Excluded: dessert'
        if has_dye:
            return False, 0.0, 'Excluded: artificial dyes'
        has_preservative = any(p in combined_text for p in CHEMICAL_PRESERVATIVES)
        if has_preservative and not is_added_fat:
            return False, 0.0, 'Excluded from Pure Health: chemical preservatives'
        if has_high_sugar:
            return False, 0.0, 'Excluded: high sugar or refined syrup'
        if (certainty in ('unknown', 'estimated')) and not is_added_fat:
            return False, 0.0, 'Excluded: unverified ingredients'

        density_score = _compute_nutrient_density_score(item)
        if is_safebytes:
            density_score = min(density_score + 10.0, 100.0)
            reason = 'SafeBytes Top-9 Allergen-Free line: clean whole food'
        elif is_added_fat:
            density_score = 78.0
            reason = 'Clean healthy fat source'
        else:
            reason = 'High micronutrient & protein density'
        return True, round(max(25.0, min(density_score, 100.0)), 1), reason

    elif tier == 'high':
        # Healthy Mode: Strict seed-oil-free, whole-food, deep-fry-free (ZERO relaxation)
        if is_dessert:
            return False, 0.0, 'Excluded: dessert'
        if has_seed_oil:
            return False, 0.0, 'Excluded: contains seed oils'
        if is_deep_fried:
            return False, 0.0, 'Excluded: deep-fried'
        if has_dye:
            return False, 0.0, 'Excluded: artificial dyes'
        if has_high_sugar:
            return False, 0.0, 'Excluded: added sugar or refined syrup'
        if certainty in ('unknown', 'estimated') and not is_added_fat:
            return False, 0.0, 'Excluded from Healthy: unverified ingredients'

        score = 72.0
        if is_safebytes:
            score += 16.0
            reason = 'SafeBytes Top-9 Allergen-Free line (Seed-Oil Free)'
        elif certainty == 'verified' and not has_seed_oil:
            score += 14.0
            reason = 'Verified seed-oil-free whole food'
        elif certainty == 'verified_whole_food' and not has_seed_oil:
            score += 9.0
            reason = 'Whole food staple (verified via nutrition heuristic)'
        else:
            reason = 'Wholesome clean food'

        if 'olive oil' in combined_text or 'butter' in combined_text or 'avocado oil' in combined_text:
            score += 8.0
        score += min(item.get('protein', 0.0) * 0.45, 14.0)
        return True, round(max(20.0, min(score, 100.0)), 1), reason

    elif tier == 'mid':
        # Balanced Mode: wholesome realistic dining court meals
        if is_dessert:
            return False, 0.0, 'Excluded: dessert'
        if is_deep_fried and not narrow_breadth:
            return False, 0.0, 'Excluded: deep-fried'
        if ((has_high_sugar and item.get('protein', 0.0) < 10.0) or (item.get('sugar', 0.0) > 20.0 and not whole_fruit)) and not narrow_breadth:
            return False, 0.0, 'Excluded: high sugar glaze'

        score = 62.0
        if certainty == 'verified' and not has_seed_oil:
            score += 15.0
            reason = 'Verified seed-oil-free whole food'
        elif certainty in ('unknown', 'estimated'):
            score += 5.0
            reason = 'Dining court staple (unverified ingredients)'
        else:
            score += 10.0
            reason = 'Balanced dining court entree'
        if is_deep_fried:
            score -= 18.0
        score += min(item.get('protein', 0.0) * 0.35, 14.0)
        return True, round(max(20.0, min(score, 100.0)), 1), reason

    else:
        # 'low' -> Yummy Mode (comfort food, cravings, and desserts; NO salads or greens)
        is_salad_or_greens = (
            _is_composed_salad(item)
            or any(g in name_lower for g in [
                'salad', 'spinach', 'kale', 'lettuce', 'spring mix', 'romaine',
                'mixed greens', 'arugula', 'chard', 'collard', 'cabbage slaw', 'coleslaw',
                'green beans', 'steamed broccoli', 'broccoli florets', 'raw broccoli',
                'steamed cauliflower', 'cauliflower florets', 'raw cauliflower',
                'baby carrots', 'steamed carrots', 'celery sticks', 'cucumber slices',
                'sliced cucumbers', 'steamed squash', 'steamed zucchini', 'steamed peas',
                'snap peas', 'garbanzo bean', 'chickpea salad', 'kidney bean salad'
            ])
            or (
                any(s in station_lower for s in ['salad bar', 'salad stop', 'data crunch', 'rabbit food', 'greens & grains'])
                and not is_dessert
                and not any(c in name_lower for c in ['chicken', 'beef', 'bacon', 'ham', 'cheese', 'pasta', 'potato'])
            )
        )
        if is_salad_or_greens:
            return False, 0.0, 'Excluded from Yummy: salads and greens (comfort foods & cravings prioritized)'

        appeal = compute_item_yummy_score(item)
        reason = (
            'Elite crowd-pleaser craving'
            if appeal >= 92.0
            else (
                'Top savory comfort favorite'
                if appeal >= 85.0
                else (
                    'Solid campus classic'
                    if appeal >= 75.0
                    else 'Campus comfort plate'
                )
            )
        )
        return True, round(appeal, 1), reason


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
    raw_name = (item.get('name') or '').strip()
    name_lower = raw_name.lower()
    ing_lower = (item.get('ingredients') or '').lower()

    if name_lower in STATION_HEADER_NAMES or (name_lower.endswith(' bar') and item.get('calories', 0.0) == 0.0 and item.get('protein', 0.0) == 0.0):
        return 'exclude'

    if _is_dessert_item(name_lower):
        return 'dessert'

    # Clean name by stripping station or parenthetical markers like '(salad bar)'
    clean_name = re.sub(r'\s*\([^)]*salad\s+bar[^)]*\)', '', name_lower).strip()

    if _is_standalone_condiment(item) or _is_added_oil_or_fat(item) or re.search(r'\b(?:vinegar|oil)s?\b', clean_name):
        return 'condiment'

    if ('shredded' in clean_name and 'cheese' in clean_name) or ('grated' in clean_name and 'parmesan' in clean_name):
        return 'condiment'

    if _is_dip_or_condiment(item):
        return 'condiment'

    if 'salad' in clean_name:
        if any(fs in clean_name for fs in FRUIT_SALAD_KEYWORDS):
            return 'side'
        if any(ss in clean_name for ss in STARCH_SALAD_KEYWORDS):
            return 'carb_base'
        if any(es in clean_name for es in ENTREE_PROTEIN_SALAD_KEYWORDS):
            return 'protein_entree'
        if _is_composed_salad(item):
            return 'composed_salad'
        return 'protein_entree'

    if any(re.search(rf'\b{re.escape(m)}\b', clean_name) for m in SANDWICH_ENTREE_MARKERS):
        if 'breakfast' in clean_name or 'egg' in clean_name:
            return 'breakfast_entree'
        return 'sandwich'

    if any(re.search(rf'\b{re.escape(m)}(?:s|es)?\b', clean_name) for m in BREAKFAST_ENTREE_MARKERS):
        return 'breakfast_entree'

    if any(re.search(rf'\b{re.escape(m)}\b', clean_name) for m in COMPLETE_ENTREE_MARKERS):
        return 'complete_entree'

    if any(re.search(rf'\b{re.escape(m)}\b', clean_name) for m in BOWL_ENTREE_MARKERS):
        return 'bowl'

    if any(re.search(rf'\b{re.escape(m)}\b', clean_name) for m in PASTA_ENTREE_MARKERS):
        return 'pasta_entree'

    if _is_standalone_bakery(item):
        if any(b in clean_name for b in ['hamburger bun', 'hot dog bun', 'bun', 'buns']):
            return 'exclude'
        return 'carb_base'

    if any(re.search(rf'\b{re.escape(v)}\b', clean_name) for v in VEGETABLE_KEYWORDS):
        if 'edamame' in clean_name:
            return 'protein_entree'
        return 'vegetable'

    if _is_whole_fruit(clean_name):
        return 'side'

    if any(re.search(rf'\b{re.escape(h)}(?:s|es)?\b', clean_name) for h in [
        'curry', 'chole', 'chana masala', 'drumstick', 'carne adobada', 'sofritas', 'meatball', 'chik nugget', 'nugget'
    ]):
        return 'protein_entree'

    entree_protein_hints = [
        'chicken', 'beef', 'steak', 'pork', 'salmon', 'fish', 'shrimp',
        'turkey', 'tofu', 'tempeh', 'seitan', 'egg', 'meatball',
        'carnitas', 'barbacoa', 'tilapia', 'cod', 'ham', 'tuna',
        'paneer', 'cottage cheese', 'greek yogurt', 'drumstick',
        'curry', 'chole', 'chana masala', 'dal', 'dhal',
        'carne adobada', 'sofritas', 'chik nuggets', 'nugget'
    ]
    has_protein_word = any(
        re.search(rf'\b{re.escape(h)}(?:s|es)?\b', clean_name)
        for h in entree_protein_hints
    )
    has_protein_ing = any(
        re.search(rf'\b{re.escape(h)}\b', ing_lower)
        for h in ['chicken breast', 'beef', 'pork', 'salmon', 'turkey', 'tofu', 'egg']
    )

    if item['protein'] >= 10.0 and (
        item['protein'] >= item['carbs'] * 0.4
        or has_protein_word
        or has_protein_ing
    ):
        return 'protein_entree'

    if item['carbs'] >= 15.0 and item['carbs'] > item['protein']:
        return 'carb_base'

    return 'side'


def _has_real_protein_entree_anchor(slots: list[tuple[str, dict]]) -> bool:
    anchor_roles = {
        'protein_entree', 'sandwich', 'complete_entree',
        'pasta_entree', 'bowl', 'breakfast_entree', 'composed_salad'
    }
    for _, it in slots:
        role = it.get('_role')
        if role in anchor_roles and it.get('protein', 0.0) >= 10.0:
            return True
    return False


def _meets_minimum_meal_floor(
    totals: dict,
    per_meal: Optional[dict],
    dri_enabled: bool,
    health_intensity: str,
    slots: Optional[list[tuple[str, dict]]] = None,
    template_name: str = '',
) -> bool:
    tier = health_intensity.strip().lower()
    pro = totals.get('protein', 0.0)
    cal = totals.get('calories', 0.0)

    items = [it for _, it in slots] if slots else []
    is_breakfast = (
        template_name.startswith('breakfast')
        or any(
            it.get('_role') == 'breakfast_entree'
            or it.get('_cuisine') == 'breakfast'
            or any(b in it.get('name', '').lower() for b in ('egg', 'oatmeal', 'pancake', 'waffle', 'frittata', 'omelet'))
            for it in items
        )
    )

    if is_breakfast:
        if tier == 'extreme':
            return pro >= 14.0 and cal >= 200.0
        if dri_enabled and per_meal:
            min_pro = max(per_meal.get('protein_target', 18.0) * 0.50, 12.0)
            min_cal = max(per_meal.get('calories', 300.0) * 0.50, 200.0)
            return pro >= min_pro and cal >= min_cal
        return pro >= 14.0 and cal >= 240.0

    if tier == 'extreme':
        return pro >= 18.0 and cal >= 240.0

    if dri_enabled and per_meal:
        min_pro = max(per_meal.get('protein_target', 22.0) * 0.60, 14.0)
        min_cal = max(per_meal.get('calories', 380.0) * 0.55, 260.0)
        return pro >= min_pro and cal >= min_cal

    if tier == 'high':
        return pro >= 18.0 and cal >= 320.0

    return pro >= 16.0 and cal >= 260.0


def _build_option_b_anchors(pool: list[dict], existing_proteins: list[dict]) -> list[dict]:
    anchors = list(existing_proteins)
    seen_names = {p['name'] for p in anchors}

    tier1 = sorted(
        [
            i for i in pool
            if i['name'] not in seen_names
            and not _is_standalone_bakery(i)
            and i['_role'] not in ('composed_salad', 'condiment')
            and (i['protein'] >= 8.0 and any(k in i['name'].lower() for k in ['egg', 'tofu', 'paneer', 'cottage cheese', 'greek yogurt', 'edamame']))
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
            and i['_role'] not in ('composed_salad', 'condiment')
            and (_is_plant_veg_anchor(i) and i['protein'] >= 8.0)
        ],
        key=lambda x: (x['_quality_score'] + x['protein'] * 1.1 + x['calories'] * 0.03),
        reverse=True,
    )
    for item in tier2:
        anchors.append(item)
        seen_names.add(item['name'])

    return anchors[:8]


def evaluate_culinary_compatibility(
    slots: list[tuple[str, dict]],
    template_name: str,
    health_intensity: str = 'Mid',
) -> tuple[bool, float, list[str]]:
    items = [it for _, it in slots]
    if not items:
        return False, 0.0, []

    tier = health_intensity.strip().lower()
    if tier == 'extreme':
        if len(items) < 2 or len(items) > 4:
            return False, 0.0, ['Pure Health requires 2–4 distinct whole-food items']
        added_fats = sum(1 for it in items if _is_added_oil_or_fat(it))
        if added_fats > 1:
            return False, 0.0, ['Pure Health allows max 1 added oil/fat serving']
        return True, 100.0, ['Pure nutrient-density whole-food assembly']

    roles = [it['_role'] for it in items]
    names_lower = [it['name'].lower() for it in items]

    if any(r == 'condiment' and not (_is_added_oil_or_fat(it) or 'oil' in it['name'].lower() or 'dressing' in it['name'].lower() or 'vinegar' in it['name'].lower()) for it, r in zip(items, roles)):
        return False, 0.0, ['Rejected: standalone condiment cannot serve as a meal component']

    complete_roles = {'sandwich', 'complete_entree', 'pasta_entree', 'bowl', 'breakfast_entree'}
    if sum(1 for r in roles if r in complete_roles) > 1:
        return False, 0.0, ['Rejected: multiple complete entrees']

    starch_count = 0
    for it in items:
        r = it['_role']
        if r == 'dessert':
            continue
        n = it['name'].lower()
        if r in ('pasta_entree', 'sandwich', 'complete_entree', 'bowl') or any(
            g in n for g in ['rice', 'pasta', 'noodle', 'spaghetti', 'penne', 'potato', 'bread', 'roll', 'tortilla', 'naan', 'pita', 'couscous', 'quinoa', 'macaroni', 'fry', 'fries', 'sidewinder', 'tots', 'rings']
        ):
            starch_count += 1

    if tier == 'low':
        if starch_count > 2:
            return False, 0.0, ['Rejected: excessive starch combinations']
    else:
        if starch_count > 1:
            return False, 0.0, ['Rejected: redundant carbohydrate/starch components']

    has_any_salad = 'composed_salad' in roles or any('salad' in n for n in names_lower)
    if has_any_salad and any(
        any(g in n for g in ['rice', 'pasta', 'noodle', 'spaghetti', 'penne', 'mac'])
        for n in names_lower
    ):
        return False, 0.0, ['Rejected: salad paired with heavy starch']

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

    if len(items) == 1:
        single_role = items[0]['_role']
        single_name = items[0]['name'].lower()
        if single_role in ('complete_entree', 'bowl', 'sandwich', 'pasta_entree', 'breakfast_entree'):
            return True, 78.0, [f'Self-contained {single_role.replace("_", " ")}']
        if single_role == 'composed_salad' or 'salad' in single_name:
            return True, 76.0, ['Standalone composed salad main']
        return True, 64.0, ['Single-component plate']

    score = 50.0
    reasons: list[str] = []

    if len(cuisines) >= 2 and len(distinct_cuisines) == 1:
        score += 18.0
        reasons.append(f'Cohesive {cuisines[0]} cuisine pairing')
    elif len(distinct_cuisines) == 1 and 'neutral' in [it['_cuisine'] for it in items]:
        score += 11.0
        reasons.append('Clean neutral accompaniment')
    elif len(distinct_cuisines) == 0:
        score += 9.0

    joined_names = ' | '.join(names_lower)
    classic_pairings = [
        (['teriyaki', 'orange chicken', 'general tso', 'stir fry', 'bulgogi', 'curry', 'tikka', 'chole', 'masala'], ['jasmine rice', 'white rice', 'brown rice', 'basmati rice', 'rice', 'couscous'], 16.0, 'Classic Asian protein & steamed rice pairing'),
        (['chicken parmesan', 'meatball', 'italian chicken', 'bolognese', 'marinara'], ['pasta', 'spaghetti', 'penne', 'fettuccine', 'broccoli', 'green beans'], 15.0, 'Classic Italian entree pairing'),
        (['taco', 'carnitas', 'barbacoa', 'carne asada', 'fajita', 'chorizo'], ['spanish rice', 'mexican rice', 'cilantro lime', 'black bean', 'pinto bean'], 16.0, 'Traditional Latin plate pairing'),
        (['chicken drumstick', 'drumstick', 'bbq chicken', 'grilled chicken', 'chicken breast', 'chicken', 'steak', 'salmon', 'pork loin', 'turkey'], ['rice', 'long grain rice', 'brown rice', 'white rice', 'roasted potato', 'sweet potato', 'mashed potato', 'quinoa', 'asparagus', 'broccoli', 'green beans', 'pasta salad', 'potato salad'], 16.0, 'Classic roasted protein & starch/vegetable plate'),
        (['burger', 'cheeseburger', 'sandwich', 'hot dog', 'corn dog', 'patty'], ['fry', 'fries', 'sidewinder', 'curly', 'waffle fries', 'tots', 'rings', 'onion rings', 'chips', 'mac'], 18.0, 'Classic burger & crispy craving side'),
        (['wings', 'wing', 'tender', 'tenders', 'drumstick', 'fried chicken', 'bbq chicken', 'bbq', 'ribs', 'pulled pork'], ['fry', 'fries', 'sidewinder', 'tots', 'mac', 'biscuit', 'waffle', 'cornbread'], 18.0, 'Classic fried/BBQ comfort craving pairing'),
        (['pizza'], ['breadstick', 'garlic bread', 'mozzarella', 'wings', 'cookie', 'brownie'], 18.0, 'Classic pizza craving plate'),
        (['gyro', 'shawarma', 'lemon herb', 'mediterranean', 'greek'], ['couscous', 'quinoa', 'chickpea', 'garbanzo', 'greek salad'], 15.0, 'Mediterranean flavor pairing'),
        (['burger', 'cheeseburger', 'sandwich', 'panini', 'wrap'], ['fruit', 'apple', 'berries', 'watermelon', 'broccoli', 'salad', 'sweet potato'], 12.0, 'Balanced sandwich/burger & crisp side'),
        (['scrambled', 'omelet', 'frittata', 'pancake', 'waffle', 'egg', 'eggs', 'hard cooked', 'hard boiled'], ['bacon', 'sausage', 'fruit', 'berries', 'banana', 'oatmeal', 'kiwi', 'blueberry', 'blueberries'], 14.0, 'Classic breakfast pairing'),
        (['spinach', 'romaine', 'greens', 'lettuce'], ['garbanzo', 'chickpea', 'egg', 'eggs', 'cucumber', 'tomato', 'olive oil'], 15.0, 'Salad Bar whole-food harvest balance'),
    ]
    for anchor_kws, partner_kws, bonus_pts, label in classic_pairings:
        if any(ak in joined_names for ak in anchor_kws) and any(pk in joined_names for pk in partner_kws):
            score += bonus_pts
            reasons.append(label)
            break

    if any(it['_role'] == 'dessert' for it in items):
        score += 14.0
        reasons.append('Satisfying meal & sweet dessert craving')

    flavor_sets = [it['_flavors'] for it in items if it['_flavors']]
    if len(flavor_sets) >= 2:
        shared_flavors = flavor_sets[0].intersection(*flavor_sets[1:])
        if shared_flavors:
            score += 8.0
            reasons.append('Shared flavor notes')
        elif any('clean_neutral' in fs for fs in flavor_sets):
            score += 6.0

    methods = {it['_method'] for it in items}
    if len(methods) >= 2:
        score += 7.0
        reasons.append('Complementary cooking textures')

    stations = [it['station'].lower().strip() for it in items]
    if len(stations) >= 2 and len(set(stations)) == 1:
        score += 5.0

    return True, round(min(score, 100.0), 1), reasons


def _generate_assembly_instructions(slots: list[tuple[str, dict]], location: str) -> list[dict]:
    """
    Builds clean, step-by-step assembly instructions telling the user exactly what to grab
    from each station in the dining court and how to combine them into the recommended custom bowl/plate.
    """
    by_station: dict[str, list[tuple[str, dict]]] = {}
    for role_label, item in slots:
        st = item.get('station') or 'Main Line'
        by_station.setdefault(st, []).append((role_label, item))

    def _station_order(st_name: str) -> int:
        s = st_name.lower()
        if any(k in s for k in ['salad', 'greens', 'produce', 'fruit', 'cold', 'market']):
            return 1
        if any(k in s for k in ['safebytes', 'simple servings', 'oasis', 'natural']):
            return 2
        if any(k in s for k in ['grill', 'carving', 'action', 'entree', 'hearth', 'comfort', 'potāto', 'potato', 'boilerq']):
            return 3
        if any(k in s for k in ['rice', 'grain', 'oatmeal', 'pasta', 'international', 'one world', 'gallery', 'asian', 'salami and swiss']):
            return 4
        if any(k in s for k in ['condiment', 'toppings', 'oil', 'spread']):
            return 6
        return 5

    ordered_stations = sorted(by_station.keys(), key=_station_order)
    steps = []

    for step_num, station_name in enumerate(ordered_stations, start=1):
        station_items = by_station[station_name]
        item_names = [it['name'] for _, it in station_items]
        st_low = station_name.lower()

        if any(k in st_low for k in ['salad', 'greens', 'produce', 'cold']):
            title = 'Fresh Salad Bar Foundation'
            instruction = f"At {station_name}, grab a clean bowl and lay down {', and '.join(item_names)} as your micronutrient-rich foundation."
        elif any(k in st_low for k in ['safebytes']):
            title = 'SafeBytes Top-9 Allergen-Free Anchor'
            instruction = f"Head to {station_name} and add {', and '.join(item_names)} prepared fresh without top allergens or seed oils."
        elif any(k in st_low for k in ['grill', 'carving', 'boilerq', 'potāto', 'potato', 'hearth', 'action']):
            title = 'Stack Clean Protein Anchor'
            instruction = f"Head to {station_name} and add {', and '.join(item_names)} to power your plate with bioavailable protein."
        elif any(k in st_low for k in ['rice', 'grain', 'simple servings', 'international', 'oatmeal', 'salami and swiss']):
            title = 'Add Clean Complex Fuel'
            instruction = f"Stop at {station_name} and scoop {', and '.join(item_names)} for sustained energy carbohydrates."
        elif any(k in st_low for k in ['condiment', 'toppings', 'oil']):
            title = 'Healthy Fat & Finishing Touch'
            instruction = f"At {station_name}, finish your plate with {', and '.join(item_names)}."
        else:
            title = f'Pick Up from {station_name}'
            instruction = f"At {station_name}, pick up {', and '.join(item_names)} to complete your balanced macro targets."

        steps.append({
            'step': step_num,
            'station': station_name,
            'title': title,
            'items': item_names,
            'instruction': instruction,
        })

    return steps


def _generate_pure_health_combo_title(items: list[dict]) -> str:
    names = [it['name'].lower() for it in items]
    has_greens = any(any(g in n for g in ('spinach', 'romaine', 'greens', 'salad', 'lettuce', 'broccoli', 'kale')) for n in names)
    has_chicken = any('chicken' in n for n in names)
    has_egg = any('egg' in n for n in names)
    has_rice = any('rice' in n for n in names)
    has_oatmeal = any('oatmeal' in n for n in names)
    has_edamame = any('edamame' in n for n in names)
    has_beans = any(any(b in n for b in ('bean', 'garbanzo', 'chickpea', 'lentil')) for n in names)
    has_berries = any(any(b in n for b in ('berry', 'berries', 'strawberry', 'blueberry', 'kiwi', 'fruit')) for n in names)

    if has_egg and has_oatmeal:
        return 'Clean Eggs & Oatmeal Power Fuel'
    if has_greens and (has_beans or has_egg):
        return 'Salad Bar Whole-Food Harvest Bowl'
    if has_greens and (has_chicken or has_edamame):
        return 'Custom Whole-Food Harvest Bowl'
    if has_chicken and has_rice:
        return 'Grilled Chicken & Jasmine Rice Bowl'
    if has_egg and has_berries:
        return 'Clean Whole Egg & Fresh Fruit Stack'
    if has_edamame and has_rice:
        return 'Plant Power Edamame & Rice Bowl'
    if len(items) >= 4:
        return 'Custom Macro Stacking Plate'
    first_clean = re.sub(r'\s*\([^)]*\)', '', items[0]['name']).strip()
    return f'{first_clean} Whole-Food Stack'


def _generate_pure_health_stacking_combos(pool: list[dict]) -> list[tuple[str, list[tuple[str, dict]]]]:
    """
    Pure Health Mode ('Extreme') Unconstrained Macro Assembler & Stacking:
    Decoupled from rigid plate structures. Pulls individual clean whole-food items
    across any open station in the dining court (e.g. plain eggs, grilled chicken breast strips,
    garbanzo beans, fresh spinach, steamed edamame, jasmine rice, berries) and combines
    them into custom power bowls or stacked plates.
    """
    eligible = [it for it in pool if it['_role'] != 'exclude']
    if len(eligible) < 2:
        return []

    # Categorize items into functional whole-food categories
    proteins = sorted(
        [it for it in eligible if it.get('protein', 0.0) >= 7.0 or it['_role'] in ('protein_entree', 'breakfast_entree') or any(k in it['name'].lower() for k in ('chicken', 'egg', 'edamame', 'tilapia', 'salmon', 'turkey', 'beef', 'beans', 'lentil', 'tofu'))],
        key=lambda x: x.get('protein', 0.0),
        reverse=True,
    )

    greens_and_vegs = sorted(
        [it for it in eligible if it['_role'] in ('vegetable', 'composed_salad') or any(v in it['name'].lower() for v in ('spinach', 'romaine', 'broccoli', 'zucchini', 'cucumber', 'pepper', 'asparagus', 'cauliflower', 'greens', 'beans', 'edamame'))],
        key=lambda x: x.get('_raw_quality', 50.0),
        reverse=True,
    )

    complex_carbs = sorted(
        [it for it in eligible if (it['_role'] in ('carb_base', 'side') or _is_whole_fruit(it['name'].lower())) and not _is_standalone_bakery(it) and not _is_added_oil_or_fat(it) and it not in proteins],
        key=lambda x: x.get('_raw_quality', 50.0),
        reverse=True,
    )

    healthy_fats = [it for it in eligible if _is_added_oil_or_fat(it)]

    candidates: list[tuple[str, list[tuple[str, dict]]]] = []
    seen_combos = set()

    def _add_candidate(tpl_name: str, slots: list[tuple[str, dict]]):
        names = tuple(sorted(it['name'] for _, it in slots))
        if names in seen_combos or len(names) != len(slots):
            return
        seen_combos.add(names)
        candidates.append((tpl_name, slots))

    # 1. Stacks with 3 items: Protein + Veg/Green + Complex Fuel
    for p in proteins[:8]:
        for g in greens_and_vegs[:6]:
            if g['name'] == p['name']:
                continue
            for c in complex_carbs[:6]:
                if c['name'] in (p['name'], g['name']):
                    continue
                _add_candidate('pure_stack_3', [('Protein Anchor', p), ('Fresh Greens', g), ('Clean Fuel', c)])

                # 4-item stack: add healthy fat
                for f in healthy_fats[:1]:
                    if f['name'] not in (p['name'], g['name'], c['name']):
                        _add_candidate('pure_stack_4_fat', [('Protein Anchor', p), ('Fresh Greens', g), ('Clean Fuel', c), ('Clean Fat', f)])

                # 4-item stack: add second vegetable / micro
                for g2 in greens_and_vegs[:4]:
                    if g2['name'] not in (p['name'], g['name'], c['name']):
                        _add_candidate('pure_stack_4_veg', [('Protein Anchor', p), ('Fresh Greens', g), ('Micronutrients', g2), ('Clean Fuel', c)])

                # 5-item stack: Double Protein + Greens + Complex Fuel + Fruit/Fat
                for p2 in proteins[:4]:
                    if p2['name'] not in (p['name'], g['name'], c['name']):
                        slots5 = [('Protein Anchor', p), ('Protein Booster', p2), ('Fresh Greens', g), ('Clean Fuel', c)]
                        if healthy_fats and healthy_fats[0]['name'] not in (p['name'], p2['name'], g['name'], c['name']):
                            slots5.append(('Clean Fat', healthy_fats[0]))
                        elif len(complex_carbs) > 1 and complex_carbs[1]['name'] not in (p['name'], p2['name'], g['name'], c['name']):
                            slots5.append(('Whole Fruit', complex_carbs[1]))
                        _add_candidate('pure_stack_5', slots5)

            # High-protein + double greens
            for g2 in greens_and_vegs[:4]:
                if g2['name'] not in (p['name'], g['name']):
                    _add_candidate('pure_stack_3_veg', [('Protein Anchor', p), ('Fresh Greens', g), ('Micronutrients', g2)])

    # 2. Double Protein Stacks (e.g. Eggs + Chicken + Fuel)
    for p1 in proteins[:6]:
        for p2 in proteins[:6]:
            if p1['name'] == p2['name']:
                continue
            for g in greens_and_vegs[:4]:
                if g['name'] not in (p1['name'], p2['name']):
                    _add_candidate('pure_double_pro_greens', [('Protein Anchor', p1), ('Protein Booster', p2), ('Fresh Greens', g)])
            for c in complex_carbs[:4]:
                if c['name'] not in (p1['name'], p2['name']):
                    _add_candidate('pure_double_pro_fuel', [('Protein Anchor', p1), ('Protein Booster', p2), ('Clean Fuel', c)])

    # 2b. Breakfast & Whole Fruit Stacks (e.g. Eggs + Oatmeal + Blueberries/Kiwi)
    whole_fruits = [it for it in eligible if _is_whole_fruit(it['name'].lower())]
    for p in proteins[:6]:
        for c in complex_carbs[:6]:
            if c['name'] == p['name']:
                continue
            _add_candidate('pure_stack_fuel_2', [('Protein Anchor', p), ('Clean Fuel', c)])
            for wf in whole_fruits[:4]:
                if wf['name'] not in (p['name'], c['name']):
                    _add_candidate('pure_stack_fruit_3', [('Protein Anchor', p), ('Clean Fuel', c), ('Fresh Fruit', wf)])

    # Double Protein + Breakfast Fuel (e.g. 2 portions eggs or eggs + cottage cheese + oatmeal)
    for p1 in proteins[:4]:
        for p2 in proteins[:4]:
            if p1['name'] == p2['name']:
                continue
            for c in complex_carbs[:4]:
                if c['name'] not in (p1['name'], p2['name']):
                    _add_candidate('pure_double_pro_breakfast', [('Protein Anchor', p1), ('Protein Booster', p2), ('Clean Fuel', c)])

    # 2c. Dedicated Salad Bar Harvest Bowl stacking:
    # Spinach + Garbanzo + Eggs + Cucumbers + Olive Oil
    salad_greens = [it for it in eligible if any(g in it['name'].lower() for g in ('spinach', 'romaine', 'mesclun', 'lettuce'))]
    salad_legumes = [it for it in eligible if any(l in it['name'].lower() for l in ('garbanzo', 'chickpea', 'black bean', 'kidney bean'))]
    salad_proteins = [it for it in proteins if any(e in it['name'].lower() for e in ('egg', 'chicken', 'tilapia', 'tofu', 'edamame'))]
    salad_cucumbers = [it for it in eligible if any(k in it['name'].lower() for k in ('cucumber', 'tomato', 'carrot', 'broccoli'))]

    if salad_greens and (salad_proteins or salad_legumes):
        for sg in salad_greens[:2]:
            for sp in (salad_proteins[:3] or salad_legumes[:2]):
                slots_harvest = [('Fresh Greens', sg), ('Protein Anchor', sp)]
                if salad_legumes and salad_legumes[0]['name'] != sp['name']:
                    slots_harvest.append(('Clean Fuel', salad_legumes[0]))
                if salad_cucumbers:
                    slots_harvest.append(('Fresh Crunch', salad_cucumbers[0]))
                if healthy_fats:
                    slots_harvest.append(('Clean Fat', healthy_fats[0]))
                _add_candidate('pure_salad_harvest_bowl', slots_harvest)

    # 3. Fallback 2-item stacks if the dining court has very few clean whole items
    if len(candidates) < 3:
        for p in proteins[:6]:
            for g in greens_and_vegs[:6]:
                if g['name'] != p['name']:
                    _add_candidate('pure_stack_2_veg', [('Protein Anchor', p), ('Fresh Greens', g)])
            for c in complex_carbs[:6]:
                if c['name'] != p['name']:
                    _add_candidate('pure_stack_2_fuel', [('Protein Anchor', p), ('Clean Fuel', c)])

    return candidates


def _generate_pure_health_templates(pool: list[dict]) -> list[tuple[str, list[tuple[str, dict]]]]:
    return _generate_pure_health_stacking_combos(pool)


def _generate_yummy_templates(pool: list[dict]) -> list[tuple[str, list[tuple[str, dict]]]]:
    by_role: dict[str, list[dict]] = {}
    for it in pool:
        if it['_role'] == 'condiment':
            continue
        by_role.setdefault(it['_role'], []).append(it)

    def _diverse_top(items_list: list[dict], limit: int) -> list[dict]:
        if len(items_list) <= limit:
            return items_list
        sorted_items = sorted(items_list, key=lambda x: x['_quality_score'], reverse=True)
        picked = []
        for it in sorted_items:
            picked.append(it)
            if len(picked) >= limit:
                break
        return picked

    complete_entrees = _diverse_top(by_role.get('complete_entree', []), 10)
    sandwiches = _diverse_top(by_role.get('sandwich', []), 10)
    proteins = _diverse_top(by_role.get('protein_entree', []), 12)
    carbs = _diverse_top(by_role.get('carb_base', []), 10)
    sides = _diverse_top(by_role.get('side', []), 10)
    pastas = _diverse_top(by_role.get('pasta_entree', []), 8)
    bowls = _diverse_top(by_role.get('bowl', []), 6)
    breakfasts = _diverse_top(by_role.get('breakfast_entree', []), 8)
    desserts = _diverse_top(by_role.get('dessert', []), 12)

    comfort_sides = [
        s for s in (sides + carbs)
        if any(k in s['name'].lower() for k in [
            'fry', 'fries', 'sidewinder', 'tot', 'ring', 'mac', 'biscuit',
            'bread', 'chips', 'potato', 'rice', 'queso', 'cheese', 'taco', 'nacho', 'waffle'
        ])
    ]
    if not comfort_sides:
        comfort_sides = (sides + carbs)[:8]

    candidates: list[tuple[str, list[tuple[str, dict]]]] = []

    # 1. Complete Entrees (Pizza, etc.)
    for ce in complete_entrees:
        candidates.append(('complete_entree', [('Main', ce)]))
        for d in desserts[:5]:
            if d['name'] != ce['name']:
                candidates.append(('complete_entree_dessert', [('Main', ce), ('Dessert', d)]))
        for cs in comfort_sides[:5]:
            if cs['name'] != ce['name']:
                candidates.append(('complete_entree_side', [('Main', ce), ('Side', cs)]))
                for d in desserts[:3]:
                    if d['name'] not in (ce['name'], cs['name']):
                        candidates.append(('complete_entree_side_dessert', [('Main', ce), ('Side', cs), ('Dessert', d)]))

    # 2. Sandwiches / Burgers
    for sw in sandwiches:
        candidates.append(('sandwich_meal', [('Main', sw)]))
        for cs in comfort_sides[:6]:
            if cs['name'] != sw['name']:
                candidates.append(('sandwich_side', [('Main', sw), ('Side', cs)]))
                for d in desserts[:3]:
                    if d['name'] not in (sw['name'], cs['name']):
                        candidates.append(('sandwich_side_dessert', [('Main', sw), ('Side', cs), ('Dessert', d)]))
        for d in desserts[:5]:
            if d['name'] != sw['name']:
                candidates.append(('sandwich_dessert', [('Main', sw), ('Dessert', d)]))

    # 3. Protein Entrees (BBQ Drumstick, Wings, Tenders, Pork, etc.)
    for p in proteins:
        for c in carbs[:6]:
            if c['name'] == p['name']:
                continue
            slots = [('Main', p), ('Base', c)]
            candidates.append(('protein_carb', slots))
            for d in desserts[:4]:
                if d['name'] not in (p['name'], c['name']):
                    candidates.append(('protein_carb_dessert', [('Main', p), ('Base', c), ('Dessert', d)]))
            for cs in comfort_sides[:4]:
                if cs['name'] not in (p['name'], c['name']):
                    candidates.append(('protein_carb_side', [('Main', p), ('Base', c), ('Side', cs)]))
        for cs in comfort_sides[:6]:
            if cs['name'] != p['name']:
                candidates.append(('protein_side', [('Main', p), ('Side', cs)]))
                for d in desserts[:4]:
                    if d['name'] not in (p['name'], cs['name']):
                        candidates.append(('protein_side_dessert', [('Main', p), ('Side', cs), ('Dessert', d)]))
        for d in desserts[:5]:
            if d['name'] != p['name']:
                candidates.append(('protein_dessert', [('Main', p), ('Dessert', d)]))

    # 4. Pastas
    for pa in pastas:
        candidates.append(('pasta_meal', [('Main', pa)]))
        for d in desserts[:4]:
            if d['name'] != pa['name']:
                candidates.append(('pasta_dessert', [('Main', pa), ('Dessert', d)]))
        for cs in comfort_sides[:4]:
            if cs['name'] != pa['name']:
                candidates.append(('pasta_side', [('Main', pa), ('Side', cs)]))
                for d in desserts[:3]:
                    if d['name'] not in (pa['name'], cs['name']):
                        candidates.append(('pasta_side_dessert', [('Main', pa), ('Side', cs), ('Dessert', d)]))

    # 5. Bowls
    for bw in bowls:
        candidates.append(('bowl_meal', [('Main', bw)]))
        for d in desserts[:4]:
            if d['name'] != bw['name']:
                candidates.append(('bowl_dessert', [('Main', bw), ('Dessert', d)]))

    # 6. Breakfasts
    for bf in breakfasts:
        candidates.append(('breakfast_meal', [('Main', bf)]))
        for c in carbs[:5]:
            if c['name'] != bf['name']:
                candidates.append(('breakfast_carb', [('Main', bf), ('Base', c)]))
                for d in desserts[:3]:
                    if d['name'] not in (bf['name'], c['name']):
                        candidates.append(('breakfast_carb_dessert', [('Main', bf), ('Base', c), ('Dessert', d)]))
        for d in desserts[:4]:
            if d['name'] != bf['name']:
                candidates.append(('breakfast_dessert', [('Main', bf), ('Dessert', d)]))

    return candidates


def _generate_meal_templates(pool: list[dict], health_intensity: str) -> list[tuple[str, list[tuple[str, dict]]]]:
    tier = health_intensity.strip().lower()
    if tier == 'extreme':
        return _generate_pure_health_templates(pool)
    if tier == 'low':
        return _generate_yummy_templates(pool)

    by_role: dict[str, list[dict]] = {}
    for it in pool:
        if it['_role'] == 'condiment':
            continue
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

    for p in proteins:
        is_protein_salad = 'salad' in p['name'].lower()
        if is_protein_salad:
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

    for ce in complete_entrees:
        candidates.append(('complete_entree', [('Main', ce)]))
        for ls in light_sides[:5]:
            if ls['name'] != ce['name']:
                candidates.append(('complete_entree_side', [('Main', ce), ('Side', ls)]))

    for sw in sandwiches:
        candidates.append(('sandwich_meal', [('Main', sw)]))
        for ls in light_sides[:5]:
            if ls['name'] != sw['name']:
                candidates.append(('sandwich_side', [('Main', sw), ('Side', ls)]))

    for pa in pasta_entrees:
        candidates.append(('pasta_meal', [('Main', pa)]))
        for v in vegs[:5]:
            if v['name'] != pa['name']:
                candidates.append(('pasta_veg', [('Main', pa), ('Side', v)]))

    for bw in bowls:
        candidates.append(('bowl_meal', [('Main', bw)]))
        for v in vegs[:4]:
            if v['name'] != bw['name']:
                candidates.append(('bowl_veg', [('Main', bw), ('Side', v)]))

    for sal in salads:
        for p in proteins[:6]:
            if p['name'] == sal['name'] or p['_role'] != 'protein_entree' or 'salad' in p['name'].lower():
                continue
            candidates.append(('salad_protein', [('Main', p), ('Base', sal)]))
            for side_opt in sides[:3]:
                if side_opt['name'] not in (p['name'], sal['name']):
                    candidates.append(('salad_protein_side', [('Main', p), ('Base', sal), ('Side', side_opt)]))

    # Dedicated Salad Bar Harvest Bowl template
    salad_greens = [it for it in pool if any(g in it['name'].lower() for g in ('spinach', 'romaine', 'mesclun', 'lettuce'))]
    salad_legumes = [it for it in pool if any(l in it['name'].lower() for l in ('garbanzo', 'chickpea', 'black bean', 'kidney bean'))]
    salad_proteins = [it for it in proteins if it['_role'] in ('protein_entree', 'breakfast_entree')]
    salad_vegs = [it for it in vegs if it['name'] not in [x['name'] for x in salad_greens]]
    salad_oils = [it for it in pool if _is_added_oil_or_fat(it) or 'olive oil' in it['name'].lower()]

    if salad_greens and (salad_proteins or salad_legumes):
        for sg in salad_greens[:2]:
            for sp in (salad_proteins[:3] or salad_legumes[:2]):
                slots_salad = [('Fresh Greens', sg), ('Protein Anchor', sp)]
                if salad_legumes and salad_legumes[0]['name'] != sp['name']:
                    slots_salad.append(('Complex Fuel', salad_legumes[0]))
                if salad_vegs:
                    slots_salad.append(('Fresh Crunch', salad_vegs[0]))
                if salad_oils:
                    slots_salad.append(('Healthy Fat', salad_oils[0]))
                candidates.append(('salad_bar_bowl', slots_salad))

    for bf in breakfasts:
        candidates.append(('breakfast_meal', [('Main', bf)]))
        for c in carbs[:6]:
            if c['name'] != bf['name']:
                candidates.append(('breakfast_carb', [('Main', bf), ('Base', c)]))
                for ls in light_sides[:4]:
                    if ls['name'] not in (bf['name'], c['name']):
                        candidates.append(('breakfast_carb_side', [('Main', bf), ('Base', c), ('Side', ls)]))
        for ls in light_sides[:5]:
            if ls['name'] != bf['name']:
                candidates.append(('breakfast_side', [('Main', bf), ('Side', ls)]))

    return candidates


def _score_meal_completeness(slots: list[tuple[str, dict]], template_name: str) -> float:
    items = [it for _, it in slots]
    roles = {it['_role'] for it in items}
    tot_cal = sum(it['calories'] for it in items)
    tot_pro = sum(it['protein'] for it in items)

    score = 62.0

    is_breakfast = (
        template_name.startswith('breakfast')
        or any(
            it.get('_role') == 'breakfast_entree'
            or it.get('_cuisine') == 'breakfast'
            or any(b in it.get('name', '').lower() for b in ('egg', 'oatmeal', 'pancake', 'waffle', 'frittata', 'omelet'))
            for it in items
        )
    )

    if 'dessert' in roles:
        score += 8.0

    if roles & {'complete_entree', 'sandwich', 'pasta_entree', 'bowl', 'breakfast_entree'}:
        score += 22.0
        if len(items) == 2:
            score += 8.0
    elif 'composed_salad' in roles and 'protein_entree' in roles:
        score += 26.0
    elif 'salad_bar_bowl' in template_name:
        score += 28.0
    elif 'protein_entree' in roles and 'carb_base' in roles and ('vegetable' in roles or 'side' in roles):
        score += 28.0
    elif 'protein_entree' in roles and ('carb_base' in roles or 'vegetable' in roles):
        score += 18.0
    elif len(items) >= 3:
        score += 22.0
    elif len(items) >= 2:
        score += 12.0

    if is_breakfast:
        if tot_cal < 240.0:
            score -= 18.0
        elif tot_cal > 750.0:
            score -= 15.0
        if tot_pro >= 15.0:
            score += 8.0
    else:
        if tot_cal < 340.0:
            score -= 20.0
        elif tot_cal > 1150.0:
            score -= 15.0
        if tot_pro >= 22.0:
            score += 8.0

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
        if any(k in goal_norm for k in ('high protein', 'muscle')):
            penalty = (pro_err * 36.0) + (cal_err * 24.0) + (carb_err * 14.0) + (fat_err * 14.0)
        elif any(k in goal_norm for k in ('lean cut', 'fat loss', 'cut')):
            penalty = (pro_err * 34.0) + (cal_err * 28.0) + (carb_err * 16.0) + (fat_err * 12.0)
        elif any(k in goal_norm for k in ('low-carb', 'low carb', 'blood sugar', 'keto')):
            penalty = (carb_err * 36.0) + (pro_err * 24.0) + (cal_err * 20.0) + (fat_err * 12.0)
            if carb > per_meal['carbs_max']:
                penalty += ((carb - per_meal['carbs_max']) / max(per_meal['carbs_max'], 1.0)) * 30.0
        elif any(k in goal_norm for k in ('endurance', 'athletic', 'energy')):
            penalty = (cal_err * 30.0) + (carb_err * 26.0) + (pro_err * 22.0) + (fat_err * 14.0)
        else:
            penalty = (cal_err * 26.0) + (pro_err * 26.0) + (carb_err * 18.0) + (fat_err * 18.0)

        if pro < per_meal['protein_min']:
            penalty += ((per_meal['protein_min'] - pro) / max(per_meal['protein_min'], 1.0)) * 25.0
        if sugar > per_meal.get('sugar_max', 25.0):
            penalty += min((sugar - per_meal.get('sugar_max', 25.0)) * 1.5, 15.0)

        return round(max(0.0, min(100.0 - penalty, 100.0)), 1)

    tier_key = health_intensity.strip().lower()

    if tier_key == 'extreme':
        target = per_meal or DEFAULT_PURE_HEALTH_PER_MEAL
        cal_err = abs(cal - target['calories']) / target['calories']
        pro_err = abs(pro - target['protein_target']) / target['protein_target']
        carb_err = _range_error(carb, target['carbs_min'], target['carbs_max'])
        fat_err = _range_error(fat, target['fat_min'], target['fat_max'])

        penalty = (cal_err * 24.0) + (pro_err * 28.0) + (carb_err * 14.0) + (fat_err * 14.0)
        if pro < target['protein_min']:
            penalty += ((target['protein_min'] - pro) / target['protein_min']) * 32.0
        if sugar > target.get('sugar_max', 20.0):
            penalty += min((sugar - target.get('sugar_max', 20.0)) * 1.5, 15.0)

        return round(max(20.0, min(100.0 - penalty, 100.0)), 1)

    profile = MODE_SCORING_PROFILES.get(tier_key, MODE_SCORING_PROFILES['mid'])
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

    if tier_key != 'low' and sugar > 24.0:
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

    if 'vegetable' in distinct_roles or 'composed_salad' in distinct_roles or 'dessert' in distinct_roles:
        score += 8.0

    return round(max(0.0, min(score, 100.0)), 1)


def _build_match_summary(
    slots: list[tuple[str, dict]],
    compat_reasons: list[str],
    health_intensity: str,
    narrow_breadth: bool = False,
) -> str:
    items = [it for _, it in slots]
    tier = health_intensity.strip().lower()

    if tier == 'extreme':
        if narrow_breadth:
            return 'Best clean option open now'
        return 'Pure Health • Max micronutrient & protein density'

    if narrow_breadth:
        return 'Best clean option open now'

    culinary_note = 'Balanced campus plate'
    if compat_reasons:
        specific = [
            r for r in compat_reasons
            if not r.startswith('Cohesive ') and r != 'Clean neutral accompaniment'
        ]
        culinary_note = specific[0] if specific else compat_reasons[0]

    reasons_text = ' '.join((it.get('_health_reason') or '').lower() for it in items)
    if 'verified seed-oil-free' in reasons_text:
        quality_note = 'Verified seed-oil-free'
    elif tier == 'low':
        quality_note = 'Campus comfort craving'
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


def _generate_combo_title(items: list[dict], cuisine: str, health_intensity: str = 'Mid') -> str:
    main_name = _clean_food_short_name(items[0]['name'])
    if len(items) == 1:
        return main_name

    if health_intensity.strip().lower() == 'extreme':
        second_name = _clean_food_short_name(items[1]['name'])
        return f"Pure Plate: {main_name} & {second_name}"

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


def _normalize_relative_scores(values: list[float], floor: float = 55.0, ceiling: float = 98.0) -> list[float]:
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    if hi - lo < 1e-6:
        return [round((floor + ceiling) / 2.0, 1) for _ in values]
    span = hi - lo
    return [
        round(floor + ((v - lo) / span) * (ceiling - floor), 1)
        for v in values
    ]


def _evaluate_and_assemble_location_candidates(
    location_items: list[dict],
    health_intensity: str,
    narrow_breadth: bool,
    per_meal: Optional[dict],
    dri_enabled: bool,
    meal_goal: str,
) -> tuple[list[dict], list[dict]]:
    """
    Evaluates items for a single dining hall under strict or relaxed (`narrow_breadth`)
    thresholds and returns (evaluated_pool, valid_raw_scored_candidates).
    """
    tier_key = health_intensity.strip().lower()
    evaluated_items: list[dict] = []

    for item in location_items:
        allowed, raw_quality_score, reason = evaluate_item_health(
            item, health_intensity, narrow_breadth=narrow_breadth
        )
        if not allowed:
            continue
        role = classify_food_item(item)
        if role == 'exclude':
            continue

        enriched = dict(item)
        enriched['_raw_quality'] = raw_quality_score
        enriched['_health_reason'] = reason
        enriched['_cuisine'] = _detect_cuisine_profile(enriched)
        enriched['_method'] = _detect_cooking_method(enriched)
        enriched['_flavors'] = _detect_flavor_tags(enriched)
        enriched['_role'] = role
        enriched['_certainty'] = _assess_ingredient_certainty(enriched)
        enriched['_main_ing'] = _extract_main_ingredient_key(enriched)
        evaluated_items.append(enriched)

    if not evaluated_items:
        return [], []

    if tier_key == 'extreme':
        # Pure Health Mode: eliminate relative pool normalization; use raw nutrient density
        for it in evaluated_items:
            it['_quality_score'] = it['_raw_quality']
    else:
        norm_qualities = _normalize_relative_scores(
            [it['_raw_quality'] for it in evaluated_items], floor=52.0, ceiling=98.0
        )
        for it, nq in zip(evaluated_items, norm_qualities):
            it['_quality_score'] = nq

    unique_items: dict[str, dict] = {}
    for it in evaluated_items:
        if it['name'] not in unique_items:
            unique_items[it['name']] = it
    pool = list(unique_items.values())

    template_candidates = _generate_meal_templates(pool, health_intensity)
    if not template_candidates:
        return pool, []

    raw_scored_candidates = []
    seen_signatures = set()

    for template_name, slots in template_candidates:
        sig = tuple(sorted(it['name'] for _, it in slots))
        if sig in seen_signatures:
            continue
        seen_signatures.add(sig)

        if tier_key != 'extreme' and not _has_real_protein_entree_anchor(slots):
            continue

        if tier_key == 'extreme':
            compatible = True
            compat_score = 92.0
            compat_reasons = ['Unconstrained clean whole-food stack']
        else:
            compatible, compat_score, compat_reasons = evaluate_culinary_compatibility(
                slots, template_name, health_intensity=health_intensity
            )
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

        if not _meets_minimum_meal_floor(totals_obj, per_meal, dri_enabled, health_intensity, slots=slots, template_name=template_name):
            continue

        if tier_key == 'extreme':
            completeness_score = 92.0
            variety_score = 90.0
        else:
            completeness_score = _score_meal_completeness(slots, template_name)
            variety_score = _score_variety_and_presentation(slots)

        food_quality_score = round(sum(it['_quality_score'] for _, it in slots) / len(slots), 1)
        raw_nutrition_score = _score_nutrition_balance(
            totals_obj, per_meal, dri_enabled, meal_goal, health_intensity
        )

        raw_scored_candidates.append({
            'template_name': template_name,
            'slots': slots,
            'totals_obj': totals_obj,
            'compat_score': compat_score,
            'compat_reasons': compat_reasons,
            'completeness_score': completeness_score,
            'food_quality_score': food_quality_score,
            'raw_nutrition_score': raw_nutrition_score,
            'variety_score': variety_score,
            'narrow_breadth': narrow_breadth,
        })

    return pool, raw_scored_candidates


def build_optimal_plates(
    open_items: list[dict],
    meal_targets: Optional[dict],
    meal_goal: str,
    health_intensity: str,
    dri_enabled: bool = False,
    dietary_filters: Optional[list[str]] = None,
    top_n: Optional[int] = None,
    custom_weights: Optional[dict] = None,
) -> list[dict]:
    active_filters = dietary_filters or []
    per_meal = (meal_targets or {}).get('per_meal') if dri_enabled else None
    tier_key = health_intensity.strip().lower()
    profile = MODE_SCORING_PROFILES.get(tier_key, MODE_SCORING_PROFILES['mid'])
    weights = custom_weights or profile['weights']

    diet_matched_open = [it for it in open_items if _passes_dietary_filters(it, active_filters)]

    items_by_location: dict[str, list[dict]] = {}
    for it in diet_matched_open:
        items_by_location.setdefault(it['location'], []).append(it)

    location_results = []

    for location, loc_items in items_by_location.items():
        # Per-dining-hall evaluation: candidate plate assembly and scoring runs on the exact
        # same dietary filtering, seed-oil screening, and culinary compatibility as the main feed.
        pool, raw_scored_candidates = _evaluate_and_assemble_location_candidates(
            location_items=loc_items,
            health_intensity=health_intensity,
            narrow_breadth=False,
            per_meal=None,
            dri_enabled=False,
            meal_goal=meal_goal,
        )
        used_hall_relaxation = False

        if tier_key not in ('high', 'extreme') and len(raw_scored_candidates) < 3:
            relaxed_pool, relaxed_candidates = _evaluate_and_assemble_location_candidates(
                location_items=loc_items,
                health_intensity=health_intensity,
                narrow_breadth=True,
                per_meal=None,
                dri_enabled=False,
                meal_goal=meal_goal,
            )
            if len(relaxed_candidates) > len(raw_scored_candidates):
                pool = relaxed_pool
                raw_scored_candidates = relaxed_candidates
                used_hall_relaxation = True

        if not raw_scored_candidates:
            location_results.append({
                'location': location,
                'hours_status': loc_items[0].get('hours_status', 'Open now'),
                'closing_time': loc_items[0].get('closing_time', ''),
                'score': 0.0,
                'combos': [],
                'items': [],
                'totals': {
                    'calories': 0.0,
                    'protein': 0.0,
                    'carbs': 0.0,
                    'fat': 0.0,
                    'sugar': 0.0,
                },
                'no_qualifying_reason': (
                    'No verified whole foods meeting Pure Health density available right now at this dining hall.'
                    if tier_key == 'extreme'
                    else (
                        'No verified seed-oil-free meals available right now at this dining hall.'
                        if tier_key == 'high'
                        else 'No meal combinations matched active dietary filters at this dining hall.'
                    )
                ),
            })
            continue

        if tier_key == 'extreme':
            # Pure Health Mode: absolute nutrition proximity scoring without relative pool scaling
            norm_nutritions = [c['raw_nutrition_score'] for c in raw_scored_candidates]
        else:
            norm_nutritions = _normalize_relative_scores(
                [c['raw_nutrition_score'] for c in raw_scored_candidates], floor=55.0, ceiling=98.0
            )

        # Check if the hall has any candidate featuring a hot line or specialty entree (not an all-staple salad bowl)
        def _is_all_staple_salad(slots_items: list[dict]) -> bool:
            return all(
                (it.get('is_staple') or 'salad' in (it.get('station') or '').lower() or '(salad bar)' in it.get('name', '').lower())
                for it in slots_items
            ) and any(k in slots_items[0]['name'].lower() for k in ('hard boiled egg', 'hard cooked egg', 'garbanzo', 'cottage cheese', 'spinach', 'romaine'))

        def _is_hot_court_entree(anchor_it: dict, slots_items: list[dict]) -> bool:
            if _is_all_staple_salad(slots_items):
                return False
            role = anchor_it.get('_role')
            st_low = (anchor_it.get('station') or '').lower()
            return (
                role in ('protein_entree', 'complete_entree', 'sandwich')
                or 'safebytes' in st_low
                or anchor_it.get('protein', 0.0) >= 15.0
            ) and not any(s in anchor_it['name'].lower() for s in ('salad bar', 'garbanzo', 'hard boiled egg'))

        has_featured_hot_entree = any(
            _is_hot_court_entree(c['slots'][0][1], [it for _, it in c['slots']])
            for c in raw_scored_candidates
        )

        scored_candidates = []
        for cand, norm_nut in zip(raw_scored_candidates, norm_nutritions):
            slots = cand['slots']
            compat_score = cand['compat_score']
            completeness_score = cand['completeness_score']
            food_quality_score = cand['food_quality_score']
            variety_score = cand['variety_score']

            if tier_key == 'extreme':
                weighted_total = (food_quality_score * 0.55) + (norm_nut * 0.45)
            elif tier_key == 'low':
                weighted_total = compute_combo_yummy_score(slots)
            else:
                weighted_total = (
                    (compat_score * weights['culinary_compatibility']) +
                    (completeness_score * weights['meal_completeness']) +
                    (food_quality_score * weights['food_quality']) +
                    (norm_nut * weights['nutrition_balance']) +
                    (variety_score * weights['variety_presentation'])
                )

            anchor_item = slots[0][1]
            slot_item_objs = [it for _, it in slots]
            is_generic_salad = _is_all_staple_salad(slot_item_objs)
            is_featured = _is_hot_court_entree(anchor_item, slot_item_objs)

            # Prioritize dining-hall-unique hot entrees over generic salad bar staple bowls
            if tier_key not in ('extreme', 'low') and has_featured_hot_entree:
                if is_featured:
                    weighted_total += 7.0
                elif is_generic_salad:
                    weighted_total -= 6.0
            meta = {
                'item_names': {it['name'] for _, it in slots},
                'anchor_name': anchor_item['name'],
                'main_ingredient': anchor_item['_main_ing'],
                'cuisine': anchor_item['_cuisine'],
                'template': cand['template_name'],
                'anchor_method': anchor_item['_method'],
            }

            breakdown = {
                'culinary_compatibility': compat_score,
                'meal_completeness': completeness_score,
                'food_quality': food_quality_score,
                'nutrition_balance': norm_nut,
                'variety_presentation': variety_score,
                'compatibility_notes': cand['compat_reasons'],
                'match_summary': _build_match_summary(
                    slots,
                    cand['compat_reasons'],
                    health_intensity,
                    narrow_breadth=used_hall_relaxation,
                ),
            }

            scored_candidates.append(
                (weighted_total, anchor_item, slots, cand['totals_obj'], breakdown, meta)
            )

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
            if tier_key == 'extreme':
                combo_name = _generate_pure_health_combo_title(slot_items)
            else:
                combo_name = _generate_combo_title(slot_items, dominant_cuisine, health_intensity=health_intensity)

            macro_split = _compute_macro_split(
                totals_obj['protein'], totals_obj['carbs'], totals_obj['fat']
            )

            is_seed_oil_free = all(
                it.get('_certainty') in ('verified', 'verified_whole_food')
                for _, it in slots
            ) and not any(
                any(re.search(rf'\b{re.escape(oil)}s?\b', f"{it.get('name','')} {it.get('ingredients','')}".lower()) for oil in SEED_OILS)
                for _, it in slots
            )

            has_salad_bar_staples = any(
                any(k in it['name'].lower() for k in ('spinach', 'romaine', 'lettuce', 'garbanzo', 'chickpea', 'salad bar', 'cucumber', 'kale', 'mesclun'))
                or 'salad' in (it.get('station') or '').lower()
                for _, it in slots
            )
            is_breakfast_stack = any(
                it.get('_role') == 'breakfast_entree' or it.get('_cuisine') == 'breakfast'
                or any(k in it['name'].lower() for k in ('egg', 'oatmeal', 'pancake', 'waffle', 'frittata', 'omelet'))
                for _, it in slots
            )

            if tier_key == 'low':
                builder_label = "Comfort Plate Guide"
                builder_type = "plate"
                builder_icon = "plate"
            elif has_salad_bar_staples:
                builder_label = "Salad & Bowl Builder"
                builder_type = "salad"
                builder_icon = "salad"
            elif is_breakfast_stack:
                builder_label = "Breakfast Assembly Guide"
                builder_type = "breakfast"
                builder_icon = "breakfast"
            else:
                builder_label = "Plate Assembly Guide"
                builder_type = "plate"
                builder_icon = "plate"

            is_salad_builder = (
                tier_key != 'low' and (
                    tier_key == 'extreme'
                    or 'stack' in _meta.get('template', '')
                    or 'salad' in _meta.get('template', '')
                    or 'bowl' in _meta.get('template', '')
                    or is_breakfast_stack
                    or has_salad_bar_staples
                )
            )
            assembly_instructions = _generate_assembly_instructions(slots, location) if is_salad_builder else []

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
                    'serving_size': it.get('serving_size', 'N/A'),
                })

            clean_totals = {
                'calories': float(round(sum(it['calories'] for it in formatted_items))),
                'protein': float(round(sum(it['protein'] for it in formatted_items))),
                'carbs': float(round(sum(it['carbs'] for it in formatted_items))),
                'fat': float(round(sum(it['fat'] for it in formatted_items))),
                'sugar': float(round(sum(it.get('sugar', 0.0) for it in formatted_items))),
            }
            clean_split = _compute_macro_split(
                clean_totals['protein'], clean_totals['carbs'], clean_totals['fat']
            )

            formatted_combos.append({
                'combo_id': f"{location.lower().replace(' ', '_')}_{idx}",
                'combo_name': combo_name,
                'station_tag': 'Custom Whole-Food Stack' if tier_key == 'extreme' else anchor_item['station'],
                'score': round(score_val, 1),
                'score_breakdown': breakdown,
                'items': formatted_items,
                'totals': clean_totals,
                'macro_split': clean_split,
                'is_seed_oil_free': is_seed_oil_free,
                'is_salad_builder': bool(assembly_instructions),
                'builder_label': builder_label,
                'builder_type': builder_type,
                'builder_icon': builder_icon,
                'assembly_instructions': assembly_instructions,
            })

        # Post-Assembly Smart Portion Scaling when dri_enabled
        if dri_enabled and per_meal:
            for combo in formatted_combos:
                scale_combo_to_user(combo, per_meal, tier_key=tier_key)

        top_combo = formatted_combos[0]
        location_results.append({
            'location': location,
            'hours_status': loc_items[0]['hours_status'],
            'closing_time': loc_items[0]['closing_time'],
            'score': top_combo['score'],
            'combos': formatted_combos,
            'items': top_combo['items'],
            'totals': top_combo['totals'],
        })

    location_results.sort(key=lambda r: (len(r.get('combos', [])) > 0, r['score']), reverse=True)

    # Cross-Court Uniqueness: diversify Card #1 across dining halls to avoid repetitive staples
    seen_top_anchors = set()
    for rec in location_results:
        combos = rec.get('combos', [])
        if not combos:
            continue

        top_c = combos[0]
        anchor_sig = tuple(sorted(it['name'].lower() for it in top_c['items'][:2]))

        if anchor_sig in seen_top_anchors and len(combos) > 1:
            alt_idx = None
            for idx in range(1, len(combos)):
                cand_sig = tuple(sorted(it['name'].lower() for it in combos[idx]['items'][:2]))
                if cand_sig not in seen_top_anchors:
                    alt_idx = idx
                    break
            if alt_idx is not None:
                # Promote distinct alternative combo to position 0 for this hall
                combos[0], combos[alt_idx] = combos[alt_idx], combos[0]
                top_c = combos[0]
                rec['items'] = top_c['items']
                rec['totals'] = top_c['totals']
                anchor_sig = tuple(sorted(it['name'].lower() for it in top_c['items'][:2]))

        seen_top_anchors.add(anchor_sig)

    return location_results[:top_n] if top_n is not None and top_n > 0 else location_results


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
        mp_guess = 'Lunch'
        if now:
            h = now.hour
            if h < 11:
                mp_guess = 'Breakfast'
            elif h < 16:
                mp_guess = 'Lunch'
            else:
                mp_guess = 'Dinner'

        targets = calculate_meal_targets(
            sex=str(sex) if sex else 'unspecified',
            age=int(age) if (age is not None and int(age) > 0) else 20,
            weight_lbs=float(weight_lbs) if (weight_lbs is not None and float(weight_lbs) > 0) else 160.0,
            height_in=float(height_in) if (height_in is not None and float(height_in) > 0) else 68.0,
            activity_level=str(activity_level) if activity_level else 'Moderate',
            meals_per_day=int(meals_per_day) if (meals_per_day is not None and int(meals_per_day) > 0) else 2,
            meal_goal=meal_goal,
            health_intensity=health_intensity,
            meal_period=mp_guess,
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
        top_n=None,
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