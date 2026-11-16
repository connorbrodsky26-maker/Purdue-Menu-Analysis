import unittest
from datetime import datetime
from purdue_menus_full_analysis import (
    PURDUE_TZ,
    classify_food_item,
    evaluate_item_health,
    evaluate_culinary_compatibility,
    build_optimal_plates,
    filter_open_locations,
    calculate_meal_targets,
    recommend_meals,
    _detect_cuisine_profile,
    _detect_cooking_method,
    _detect_flavor_tags,
    _assess_ingredient_certainty,
    CAMPUS_PERMANENT_SALAD_STAPLES,
    CAMPUS_PERMANENT_BREAKFAST_STAPLES,
    _unpack_composite_items,
)


def _make_item(
    name: str,
    location: str = 'Windsor',
    station: str = 'Main Line',
    calories: float = 220.0,
    protein: float = 24.0,
    carbs: float = 10.0,
    fat: float = 8.0,
    sugar: float = 2.0,
    ingredients: str = 'Chicken Breast, Olive Oil, Sea Salt',
    allergens: list = None,
    is_vegetarian: bool = False,
    is_vegan: bool = False,
    start_time: str = '11:00:00',
    end_time: str = '14:00:00',
    meal_period: str = 'Lunch',
) -> dict:
    item = {
        'location': location,
        'meal_period': meal_period,
        'hours_status': f'{meal_period} until 2:00 pm',
        'closing_time': '2:00 pm',
        'start_time': start_time,
        'end_time': end_time,
        'station': station,
        'name': name,
        'calories': calories,
        'protein': protein,
        'carbs': carbs,
        'fat': fat,
        'sugar': sugar,
        'ingredients': ingredients,
        'allergens': allergens or [],
        'is_vegetarian': is_vegetarian,
        'is_vegan': is_vegan,
        'used_fallback': False,
    }
    item['_role'] = classify_food_item(item)
    item['_cuisine'] = _detect_cuisine_profile(item)
    item['_method'] = _detect_cooking_method(item)
    item['_flavors'] = _detect_flavor_tags(item)
    item['_certainty'] = _assess_ingredient_certainty(item)
    return item


class TestFeastRecommendationEngine(unittest.TestCase):

    def test_sandwich_classification_overrides_bread_keyword(self):
        item = _make_item(
            'Chicken Sandwich on Wheat Bread',
            calories=440, protein=30, carbs=42, fat=16,
            ingredients='Chicken Breast, Whole Wheat Bread, Lettuce, Tomato'
        )
        self.assertEqual(item['_role'], 'sandwich')

    def test_burger_and_standalone_bun_handling(self):
        burger = _make_item('Cheeseburger', calories=510, protein=30, carbs=38, fat=25)
        bun = _make_item('Hamburger Bun', calories=130, protein=4, carbs=24, fat=2)
        self.assertEqual(burger['_role'], 'sandwich')
        self.assertEqual(bun['_role'], 'exclude')
        allowed, _, _ = evaluate_item_health(bun, 'Mid')
        self.assertFalse(allowed)

    def test_composed_salad_classification_and_foundation(self):
        salad = _make_item(
            'Mediterranean Greek Salad',
            calories=220, protein=7, carbs=14, fat=15,
            ingredients='Romaine Lettuce, Feta Cheese, Olives, Olive Oil, Lemon',
            is_vegetarian=True,
        )
        chicken = _make_item('Lemon Herb Grilled Chicken Breast', calories=190, protein=35, carbs=1, fat=4)
        self.assertEqual(salad['_role'], 'composed_salad')
        ok, score, _ = evaluate_culinary_compatibility([('Main', chicken), ('Base', salad)], 'salad_protein')
        self.assertTrue(ok)
        self.assertGreaterEqual(score, 75.0)

    def test_complete_burrito_and_pasta_avoid_redundant_carbs(self):
        burrito = _make_item('Carnitas Burrito', calories=560, protein=26, carbs=62, fat=20)
        pasta = _make_item('Chicken Parmesan Pasta', calories=480, protein=28, carbs=48, fat=16)
        rice = _make_item('Jasmine Rice', calories=205, protein=4.3, carbs=44.5, fat=0.4, is_vegetarian=True, is_vegan=True)

        self.assertEqual(burrito['_role'], 'complete_entree')
        self.assertEqual(pasta['_role'], 'pasta_entree')

        ok, _, reasons = evaluate_culinary_compatibility([('Main', pasta), ('Base', rice)], 'pasta_carb')
        self.assertFalse(ok)
        self.assertTrue(any('redundant' in r.lower() for r in reasons))

    def test_positive_culinary_compatibility_pairings(self):
        teriyaki = _make_item('Teriyaki Grilled Chicken', station='One World', calories=260, protein=28, carbs=14, fat=8)
        jasmine = _make_item('Jasmine Rice', station='One World', calories=205, protein=4.3, carbs=44.5, fat=0.4, is_vegetarian=True, is_vegan=True)
        marinara_pasta = _make_item('Penne Marinara', station='2Mato', calories=240, protein=8, carbs=46, fat=3, is_vegetarian=True)

        good_ok, good_score, _ = evaluate_culinary_compatibility([('Main', teriyaki), ('Base', jasmine)], 'protein_carb_veg')
        bad_ok, _, _ = evaluate_culinary_compatibility([('Main', teriyaki), ('Base', marinara_pasta)], 'protein_carb_veg')

        self.assertTrue(good_ok)
        self.assertGreaterEqual(good_score, 80.0)
        self.assertFalse(bad_ok)

    def test_missing_ingredient_uncertainty_and_healthiest_strictness(self):
        mystery_dish = _make_item('Mystery Glazed Chicken', ingredients='N/A', calories=320, protein=24, carbs=18, fat=14)
        verified_whole_na = _make_item('Steamed Broccoli', ingredients='N/A', calories=45, protein=3, carbs=8, fat=0.5, is_vegetarian=True, is_vegan=True)

        self.assertEqual(_assess_ingredient_certainty(mystery_dish), 'unknown')
        self.assertEqual(_assess_ingredient_certainty(verified_whole_na), 'verified_whole_food')

        high_mystery, _, _ = evaluate_item_health(mystery_dish, 'High')
        mid_mystery, _, _ = evaluate_item_health(mystery_dish, 'Mid')
        high_broccoli, _, _ = evaluate_item_health(verified_whole_na, 'High')

        self.assertFalse(high_mystery)
        self.assertTrue(mid_mystery)
        self.assertTrue(high_broccoli)

    def test_diversity_across_three_recommendations(self):
        items = [
            _make_item('Grilled Chicken Breast', station='Grill', calories=185, protein=35, carbs=0, fat=4),
            _make_item('Baked Salmon Fillet', station='Hearth', calories=235, protein=25, carbs=0, fat=14.5),
            _make_item('Carne Asada Steak', station='Latin', calories=250, protein=27, carbs=2, fat=14),
            _make_item('Jasmine Rice', station='One World', calories=205, protein=4.3, carbs=44.5, fat=0.4, is_vegetarian=True, is_vegan=True),
            _make_item('Spanish Rice', station='Latin', calories=210, protein=4.5, carbs=43, fat=2.0, is_vegetarian=True, is_vegan=True),
            _make_item('Steamed Broccoli', station='Sides', calories=45, protein=3, carbs=8, fat=0.5, is_vegetarian=True, is_vegan=True),
            _make_item('Roasted Asparagus', station='Sides', calories=40, protein=3.5, carbs=6, fat=0.4, is_vegetarian=True, is_vegan=True),
        ]
        plates = build_optimal_plates(items, meal_targets=None, meal_goal='Balanced Maintenance', health_intensity='Mid')
        self.assertEqual(len(plates), 1)
        combos = plates[0]['combos']
        self.assertEqual(len(combos), 3)
        anchors = {c['items'][0]['name'] for c in combos}
        self.assertEqual(len(anchors), 3)

    def test_time_filtering_open_and_closing_soon(self):
        lunch_item = _make_item('Grilled Chicken Breast', start_time='11:00:00', end_time='14:00:00', meal_period='Lunch')
        dinner_item = _make_item('Baked Salmon', start_time='17:00:00', end_time='20:30:00', meal_period='Dinner')

        at_1345 = datetime(2026, 11, 14, 13, 45, tzinfo=PURDUE_TZ)
        open_now = filter_open_locations([lunch_item, dinner_item], current_time=at_1345)
        self.assertEqual(len(open_now), 1)
        self.assertEqual(open_now[0]['name'], 'Grilled Chicken Breast')
        self.assertIn('Closes at', open_now[0]['hours_status'])

    def test_dri_minor_safeguard(self):
        minor_targets = calculate_meal_targets(
            sex='M', age=16, weight_lbs=145, height_in=69,
            activity_level='Active', meals_per_day=3,
            meal_goal='Lean Cut / Fat Loss', health_intensity='High'
        )
        adult_targets = calculate_meal_targets(
            sex='M', age=20, weight_lbs=145, height_in=69,
            activity_level='Active', meals_per_day=3,
            meal_goal='Lean Cut / Fat Loss', health_intensity='High'
        )
        self.assertTrue(minor_targets['is_minor_safeguarded'])
        self.assertGreater(minor_targets['daily']['calories'], adult_targets['daily']['calories'])

    def test_all_modes_and_empty_menu_handling(self):
        empty_res = recommend_meals(prebuilt_items=[])
        self.assertEqual(empty_res['recommendations'], [])

        sample_items = [
            _make_item('Teriyaki Chicken', station='One World', calories=270, protein=26, carbs=16, fat=9, ingredients='Chicken, Soy Sauce, Ginger, Garlic, Honey'),
            _make_item('Grilled Chicken Breast', station='Grill', calories=185, protein=35, carbs=0, fat=4, ingredients='Chicken Breast, Olive Oil, Sea Salt'),
            _make_item('Jasmine Rice', station='One World', calories=205, protein=4.3, carbs=44.5, fat=0.4, ingredients='Jasmine Rice, Water', is_vegetarian=True, is_vegan=True),
            _make_item('Steamed Broccoli', station='Grill', calories=45, protein=3, carbs=8, fat=0.5, ingredients='Broccoli, Water', is_vegetarian=True, is_vegan=True),
        ]
        lunch_time = datetime(2026, 11, 14, 12, 30, tzinfo=PURDUE_TZ)
        for mode in ('High', 'Mid', 'Low'):
            res = recommend_meals(health_intensity=mode, prebuilt_items=sample_items, current_time=lunch_time)
            self.assertEqual(len(res['recommendations']), 1)
            self.assertGreaterEqual(len(res['recommendations'][0]['combos']), 1)
            self.assertIn('score_breakdown', res['recommendations'][0]['combos'][0])

    def test_seed_oil_rejected_from_healthy_and_pure_health(self):
        canola_item = _make_item('Sauteed Green Beans', ingredients='Green Beans, Canola Oil, Salt')
        soy_item = _make_item('Roast Chicken', ingredients='Chicken, Soybean Oil, Spices')
        veg_oil_item = _make_item('Roasted Potatoes', ingredients='Potatoes, Vegetable Oil, Sea Salt')

        for item in (canola_item, soy_item, veg_oil_item):
            allowed_high, _, reason_high = evaluate_item_health(item, 'High')
            self.assertFalse(allowed_high)
            self.assertIn('contains seed oils', reason_high)

            allowed_pure, _, reason_pure = evaluate_item_health(item, 'Extreme')
            self.assertFalse(allowed_pure)
            self.assertIn('contains seed oils', reason_pure)

    def test_deep_fried_rejected_from_healthy(self):
        fried_steak = _make_item('Country Fried Steak', calories=420, protein=24, carbs=30, fat=22, ingredients='Beef, Battered, Fried, Flour, Salt')
        allowed, _, reason = evaluate_item_health(fried_steak, 'High')
        self.assertFalse(allowed)
        self.assertIn('deep-fried', reason)

    def test_unverified_ingredients_rejected_from_healthy(self):
        unknown_dish = _make_item('Mystery Casserole', ingredients='N/A')
        allowed, _, reason = evaluate_item_health(unknown_dish, 'High')
        self.assertFalse(allowed)
        self.assertIn('unverified ingredients', reason)

    def test_balanced_mode_accepts_normal_entrees_with_preservatives(self):
        fajitas = _make_item(
            'Shrimp Fajitas', calories=260, protein=22, carbs=12, fat=8,
            ingredients='Shrimp, Bell Peppers, Onions, Canola Oil, Spices, Potassium Sorbate, Sodium Benzoate'
        )
        allowed, _, _ = evaluate_item_health(fajitas, 'Mid')
        self.assertTrue(allowed)

    def test_clean_salad_and_bowl_not_excluded_by_name(self):
        clean_salad = _make_item(
            'Mediterranean Quinoa Salad', calories=240, protein=9, carbs=32, fat=7,
            ingredients='Quinoa, Cucumbers, Tomatoes, Feta Cheese, Kalamata Olives, Extra Virgin Olive Oil, Lemon Juice, Salt'
        )
        allowed, _, reason = evaluate_item_health(clean_salad, 'High')
        self.assertTrue(allowed)
        self.assertIn('Verified seed-oil-free', reason)

    def test_healthy_mode_honest_empty_when_no_clean_items(self):
        seed_oil_only = [
            _make_item('Fried Chicken Tender', calories=320, protein=20, carbs=18, fat=18, ingredients='Chicken, Soybean Oil, Flour'),
            _make_item('French Fries', calories=280, protein=3, carbs=38, fat=14, ingredients='Potatoes, Canola Oil, Salt'),
        ]
        lunch_time = datetime(2026, 11, 14, 12, 30, tzinfo=PURDUE_TZ)
        res = recommend_meals(health_intensity='High', prebuilt_items=seed_oil_only, current_time=lunch_time)
        self.assertEqual(len(res['recommendations']), 1)
        self.assertEqual(res['recommendations'][0]['combos'], [])
        self.assertIn('No verified seed-oil-free meals available', res['recommendations'][0]['no_qualifying_reason'])

    def test_pure_health_unconstrained_macro_stacking_and_instructions(self):
        whole_items = [
            _make_item('Chicken Breast Strip', station='The Grill', calories=185, protein=35, carbs=0, fat=4, ingredients='Chicken Breast, Water, Sea Salt'),
            _make_item('Hard Cooked Eggs', station='BoilerQ', calories=155, protein=12.5, carbs=1.1, fat=10.6, ingredients='Hard Cooked Egg'),
            _make_item('Steamed Edamame', station='Simple Servings', calories=120, protein=11, carbs=9, fat=5, ingredients='Edamame, Water, Salt'),
            _make_item('Jasmine Rice', station='Simple Servings', calories=205, protein=4.3, carbs=44.5, fat=0.4, ingredients='Jasmine Rice, Water'),
            _make_item('Fresh Baby Spinach', station='Salad Stop', calories=15, protein=2, carbs=2, fat=0, ingredients='Fresh Baby Spinach'),
        ]
        lunch_time = datetime(2026, 11, 14, 12, 30, tzinfo=PURDUE_TZ)
        res = recommend_meals(health_intensity='Extreme', prebuilt_items=whole_items, current_time=lunch_time)
        self.assertEqual(len(res['recommendations']), 1)
        combos = res['recommendations'][0]['combos']
        self.assertGreaterEqual(len(combos), 1)

        top_combo = combos[0]
        self.assertTrue(top_combo['is_seed_oil_free'])
        self.assertTrue(top_combo['is_salad_builder'])
        self.assertIn('assembly_instructions', top_combo)
        self.assertGreaterEqual(len(top_combo['assembly_instructions']), 2)

        # Instructions should follow logical station progression (Salad Stop first, then Grill/Carving)
        stations_in_steps = [s['station'] for s in top_combo['assembly_instructions']]
        if 'Salad Stop' in stations_in_steps and 'The Grill' in stations_in_steps:
            self.assertLess(stations_in_steps.index('Salad Stop'), stations_in_steps.index('The Grill'))

    def test_strict_ingredient_blacklist_and_syrup_rejection(self):
        powdered_sugar = _make_item('Powdered Sugar', calories=0, protein=0, carbs=0, fat=0, ingredients='Sugar, Cornstarch')
        waffle_topping = _make_item('Strawberry Waffle Topping', calories=80, protein=0.5, carbs=20, fat=0, ingredients='Strawberries, High Fructose Corn Syrup, Water, Sugar')
        country_gravy = _make_item('Country Gravy', calories=90, protein=2, carbs=10, fat=5, ingredients='Milk, Flour, Canola Oil, Salt')
        crushed_pepper = _make_item('Crushed Red Pepper', calories=0, protein=0, carbs=0, fat=0, ingredients='Red Pepper')

        for item in (powdered_sugar, waffle_topping, country_gravy, crushed_pepper):
            ok_extreme, _, reason_ex = evaluate_item_health(item, 'Extreme')
            ok_high, _, reason_hi = evaluate_item_health(item, 'High')
            self.assertFalse(ok_extreme, f"Expected {item['name']} to be excluded from Pure Health, got allowed with {reason_ex}")
            self.assertFalse(ok_high, f"Expected {item['name']} to be excluded from Healthy, got allowed with {reason_hi}")

    def test_heuristic_fallback_for_missing_ingredients(self):
        # Inherently whole foods with N/A ingredients should be permitted
        raw_spinach_na = _make_item('Fresh Baby Spinach', station='Salad Stop', ingredients='N/A', calories=15, protein=2, carbs=2, fat=0)
        kiwi_na = _make_item('Kiwi', station='Salad Stop', ingredients='N/A', calories=60, protein=1.2, carbs=14.5, fat=0.5)
        boiled_eggs_na = _make_item('Hard Cooked Eggs', station='BoilerQ', ingredients='N/A', calories=155, protein=12.5, carbs=1.1, fat=10.6)

        for item in (raw_spinach_na, kiwi_na, boiled_eggs_na):
            cert = _assess_ingredient_certainty(item)
            self.assertEqual(cert, 'verified_whole_food')
            ok, _, _ = evaluate_item_health(item, 'Extreme')
            self.assertTrue(ok, f"Expected {item['name']} to pass via whole food heuristic")

        # Processed or sauced foods with N/A ingredients should be rejected
        battered_fish_na = _make_item('Crispy Battered Fish Fillet', station='The Grill', ingredients='N/A', calories=310, protein=15, carbs=24, fat=18)
        creamy_ranch_na = _make_item('Creamy Ranch Dressing', station='Salad Stop', ingredients='N/A', calories=140, protein=1, carbs=2, fat=15)
        mystery_patty_na = _make_item('Homestyle Fried Chicken Patty', station='Granite Grill', ingredients='N/A', calories=280, protein=14, carbs=18, fat=17)

        for item in (battered_fish_na, creamy_ranch_na, mystery_patty_na):
            cert = _assess_ingredient_certainty(item)
            self.assertEqual(cert, 'unknown')
            ok, _, reason = evaluate_item_health(item, 'Extreme')
            self.assertFalse(ok, f"Expected {item['name']} to be rejected by heuristic, got allowed with {reason}")

    def test_pure_health_eliminates_relative_pool_normalization(self):
        # When a dining hall only has marginal/low-density items that pass, they should not be inflated
        low_density_items = [
            _make_item('Steamed White Rice', calories=205, protein=4.3, carbs=44.5, fat=0.4, ingredients='Rice, Water'),
            _make_item('Steamed Zucchini', calories=30, protein=1.2, carbs=6.0, fat=0.3, ingredients='Zucchini, Water'),
        ]
        # Does not meet minimum protein floor for Pure Health meal
        lunch_time = datetime(2026, 11, 14, 12, 30, tzinfo=PURDUE_TZ)
        res = recommend_meals(health_intensity='Extreme', prebuilt_items=low_density_items, current_time=lunch_time)
        self.assertEqual(len(res['recommendations']), 1)
        self.assertEqual(res['recommendations'][0]['combos'], [])
        self.assertIn('No verified whole foods meeting Pure Health density available', res['recommendations'][0]['no_qualifying_reason'])

    def test_distinct_mode_tiers_across_health_intensities(self):
        mixed_menu = [
            _make_item('Chicken Breast Strip', station='Grill', calories=185, protein=35, carbs=0, fat=4, ingredients='Chicken, Sea Salt'),
            _make_item('Jasmine Rice', station='Sides', calories=205, protein=4.3, carbs=44.5, fat=0.4, ingredients='Rice, Water'),
            _make_item('Steamed Broccoli', station='Sides', calories=45, protein=3, carbs=8, fat=0.5, ingredients='Broccoli, Water'),
            _make_item('Bang Bang Fried Shrimp', station='Entrees', calories=320, protein=20, carbs=24, fat=18, ingredients='Shrimp, Canola Oil, Flour, Sugar, Spices'),
            _make_item('Potato Gems', station='Sides', calories=160, protein=3.5, carbs=36, fat=0.3, ingredients='Potatoes, Vegetable Oil, Dextrose'),
        ]
        lunch_time = datetime(2026, 11, 14, 12, 30, tzinfo=PURDUE_TZ)

        res_pure = recommend_meals(health_intensity='Extreme', prebuilt_items=mixed_menu, current_time=lunch_time)
        res_high = recommend_meals(health_intensity='High', prebuilt_items=mixed_menu, current_time=lunch_time)
        res_mid = recommend_meals(health_intensity='Mid', prebuilt_items=mixed_menu, current_time=lunch_time)

        pure_combos = res_pure['recommendations'][0]['combos']
        high_combos = res_high['recommendations'][0]['combos']
        mid_combos = res_mid['recommendations'][0]['combos']

        # Pure Health combos must ONLY contain verified whole foods (no seed oil items)
        for c in pure_combos:
            for it in c['items']:
                self.assertNotIn('Fried', it['name'])
                self.assertNotIn('Potato Gems', it['name'])
            self.assertTrue(c['is_seed_oil_free'])
            self.assertTrue(c['is_salad_builder'])

        # Healthy combos must also be 100% seed-oil-free
        for c in high_combos:
            for it in c['items']:
                self.assertNotIn('Fried', it['name'])
                self.assertNotIn('Potato Gems', it['name'])
            self.assertTrue(c['is_seed_oil_free'])

        # Mid (Balanced) mode can include wholesome standard entrees (like Bang Bang Shrimp with canola oil)
        mid_item_names = {it['name'] for c in mid_combos for it in c['items']}
        self.assertTrue('Bang Bang Fried Shrimp' in mid_item_names or 'Potato Gems' in mid_item_names)

    def test_ford_breakfast_eggs_and_oatmeal_appear_in_healthy(self):
        breakfast_items = [
            _make_item('Hard Cooked Eggs', location='Ford', station='BoilerQ', calories=155, protein=12.5, carbs=0.6, fat=11.0, ingredients='Eggs', meal_period='Breakfast', start_time='07:00:00', end_time='10:00:00'),
            _make_item('Oatmeal', location='Ford', station='Salami and Swiss', calories=160, protein=5.5, carbs=28.0, fat=2.5, ingredients='Whole Grain Rolled Oats, Salt', meal_period='Breakfast', start_time='07:00:00', end_time='10:00:00'),
            _make_item('Fresh Blueberries', location='Ford', station='Salami and Swiss', calories=40, protein=0.5, carbs=10.0, fat=0.2, ingredients='Blueberries', meal_period='Breakfast', start_time='07:00:00', end_time='10:00:00'),
            _make_item('Pancake Syrup', location='Ford', station='BoilerQ', calories=200, protein=0, carbs=52, fat=0, ingredients='Corn Syrup, Water', meal_period='Breakfast', start_time='07:00:00', end_time='10:00:00'),
        ]
        breakfast_time = datetime(2026, 11, 14, 8, 0, tzinfo=PURDUE_TZ)
        res_high = recommend_meals(health_intensity='High', prebuilt_items=breakfast_items, current_time=breakfast_time)
        res_pure = recommend_meals(health_intensity='Extreme', prebuilt_items=breakfast_items, current_time=breakfast_time)

        self.assertEqual(len(res_high['recommendations']), 1)
        combos_high = res_high['recommendations'][0]['combos']
        self.assertGreaterEqual(len(combos_high), 1)

        # Combo should contain Hard Cooked Eggs and Oatmeal
        top_high = combos_high[0]
        item_names_high = [it['name'] for it in top_high['items']]
        self.assertIn('Hard Cooked Eggs', item_names_high)
        self.assertIn('Oatmeal', item_names_high)
        self.assertTrue(top_high['is_seed_oil_free'])

        # Pure Health should also stack clean eggs and oatmeal
        combos_pure = res_pure['recommendations'][0]['combos']
        self.assertGreaterEqual(len(combos_pure), 1)
        item_names_pure = [it['name'] for it in combos_pure[0]['items']]
        self.assertIn('Hard Cooked Eggs', item_names_pure)
        self.assertIn('Oatmeal', item_names_pure)

    def test_dynamic_builder_labeling_breakfast_vs_salad(self):
        breakfast_items = [
            _make_item('Hard Cooked Eggs', station='BoilerQ', calories=155, protein=12.5, carbs=0.6, fat=11.0, ingredients='Eggs', meal_period='Breakfast', start_time='07:00:00', end_time='10:00:00'),
            _make_item('Oatmeal', station='Salami and Swiss', calories=160, protein=5.5, carbs=28.0, fat=2.5, ingredients='Whole Grain Rolled Oats, Salt', meal_period='Breakfast', start_time='07:00:00', end_time='10:00:00'),
        ]
        breakfast_time = datetime(2026, 11, 14, 8, 0, tzinfo=PURDUE_TZ)
        res_bf = recommend_meals(health_intensity='High', prebuilt_items=breakfast_items, current_time=breakfast_time)
        top_bf = res_bf['recommendations'][0]['combos'][0]
        self.assertEqual(top_bf['builder_label'], 'Breakfast Assembly Guide')
        self.assertEqual(top_bf['builder_type'], 'breakfast')

        salad_items = [
            _make_item('Fresh Baby Spinach (Salad Bar)', station='Salad Stop', calories=15, protein=2, carbs=2.5, fat=0.2, ingredients='Fresh Baby Spinach', meal_period='Dinner', start_time='17:00:00', end_time='20:00:00'),
            _make_item('Hard Boiled Eggs (Salad Bar)', station='Salad Stop', calories=155, protein=12.5, carbs=0.6, fat=11.0, ingredients='Hard Cooked Whole Eggs', meal_period='Dinner', start_time='17:00:00', end_time='20:00:00'),
            _make_item('Garbanzo Beans (Salad Bar)', station='Salad Stop', calories=130, protein=7, carbs=22, fat=2, ingredients='Garbanzo Beans, Salt', meal_period='Dinner', start_time='17:00:00', end_time='20:00:00'),
            _make_item('Olive Oil (Extra Virgin) (Salad Bar)', station='Salad Stop', calories=120, protein=0, carbs=0, fat=14, ingredients='Extra Virgin Olive Oil', meal_period='Dinner', start_time='17:00:00', end_time='20:00:00'),
        ]
        dinner_time = datetime(2026, 11, 14, 18, 0, tzinfo=PURDUE_TZ)
        res_dinner = recommend_meals(health_intensity='High', prebuilt_items=salad_items, current_time=dinner_time)
        top_salad = res_dinner['recommendations'][0]['combos'][0]
        self.assertEqual(top_salad['builder_label'], 'Salad & Bowl Builder')
        self.assertEqual(top_salad['builder_type'], 'salad')

    def test_composite_salad_bar_item_unpacks_into_clean_staples(self):
        composite_item = {
            'location': 'Earhart',
            'meal_period': 'Dinner',
            'station': 'Salad Stop',
            'name': 'Salad Bar',
            'calories': 0.0,
            'protein': 0.0,
            'carbs': 0.0,
            'fat': 0.0,
            'sugar': 0.0,
            'ingredients': 'Grape Tomatoes (Tomatoes.), Bleu Cheese Dressing (Soybean Oil...), Hard Boiled Egg Slices, Garbanzo Beans, Fresh Spinach, Olive Oil',
            'allergens': [],
            'start_time': '17:00:00',
            'end_time': '20:00:00',
        }
        unpacked = _unpack_composite_items(composite_item)
        self.assertGreaterEqual(len(unpacked), 8)
        unpacked_names = [it['name'] for it in unpacked]
        self.assertIn('Fresh Baby Spinach (Salad Bar)', unpacked_names)
        self.assertIn('Hard Boiled Eggs (Salad Bar)', unpacked_names)
        self.assertIn('Garbanzo Beans (Salad Bar)', unpacked_names)
        self.assertIn('Olive Oil (Extra Virgin) (Salad Bar)', unpacked_names)

    def test_safebytes_station_quality_boost_and_verification(self):
        safebytes_dish = _make_item(
            'BoilerQ BBQ Chicken Drumstick',
            location='Hillenbrand',
            station='SafeBytes - Top 9 Free',
            calories=180, protein=26, carbs=4, fat=6,
            ingredients='Chicken Drumstick, Princess Dry Rub (Brown Sugar, Paprika, Salt, Garlic, Onion, Mustard, Ginger)'
        )
        ok, qual, reason = evaluate_item_health(safebytes_dish, 'High')
        self.assertTrue(ok)
        self.assertGreaterEqual(qual, 85.0)
        self.assertIn('SafeBytes', reason)

    def test_yummy_comfort_craving_and_dessert_rules(self):
        cookie = _make_item('Chocolate Chip Cookie', station='Dessert Line', calories=220, protein=3, carbs=32, fat=10, ingredients='Flour, Sugar, Butter, Chocolate Chips, Eggs')
        pie = _make_item('Cherry Pie', station='Dessert Line', calories=310, protein=3, carbs=48, fat=12, ingredients='Cherries, Sugar, Flour, Butter')
        spinach = _make_item('Fresh Baby Spinach (Salad Bar)', station='Salad Stop', calories=15, protein=2, carbs=2.5, fat=0.2, ingredients='Spinach')
        green_beans = _make_item('Seasoned Green Beans', station='Sides', calories=40, protein=1.5, carbs=6, fat=0.2, ingredients='Green Beans, Salt, Pepper')

        # Desserts excluded from High and Extreme, allowed in Low (Yummy)
        ok_high, _, _ = evaluate_item_health(cookie, 'High')
        self.assertFalse(ok_high)
        ok_extreme, _, _ = evaluate_item_health(cookie, 'Extreme')
        self.assertFalse(ok_extreme)
        ok_low, score_low, _ = evaluate_item_health(cookie, 'Low')
        self.assertTrue(ok_low)
        self.assertGreaterEqual(score_low, 80.0)

        # Salads and plain greens excluded from Low (Yummy)
        ok_spinach, _, _ = evaluate_item_health(spinach, 'Low')
        self.assertFalse(ok_spinach)
        ok_gb, _, _ = evaluate_item_health(green_beans, 'Low')
        self.assertFalse(ok_gb)

        # Recommendations in Low include comfort entree and dessert
        comfort_items = [
            _make_item('Cheeseburger', station='Grill', calories=520, protein=30, carbs=40, fat=26, ingredients='Beef patty, bun, cheddar cheese'),
            _make_item('Thin Cut Fries', station='Grill', calories=260, protein=3, carbs=34, fat=12, ingredients='Potatoes, Oil, Salt'),
            cookie,
        ]
        lunch_time = datetime(2026, 11, 14, 12, 30, tzinfo=PURDUE_TZ)
        res = recommend_meals(health_intensity='Low', prebuilt_items=comfort_items, current_time=lunch_time)
        top_combo = res['recommendations'][0]['combos'][0]
        combo_item_names = [it['name'] for it in top_combo['items']]
        self.assertIn('Cheeseburger', combo_item_names)
        self.assertIn('Chocolate Chip Cookie', combo_item_names)

    def test_yummy_crowd_pleaser_tiers_and_modifiers(self):
        from purdue_menus_full_analysis import compute_combo_yummy_score, compute_item_yummy_score

        # Tier 1 base score check
        cookie_item = _make_item('Chocolate Chip Cookie')
        self.assertEqual(compute_item_yummy_score(cookie_item), 100.0)  # 98 base + 5 chocolate modifier = 100 capped

        pizza_item = _make_item('Pepperoni Pizza')
        self.assertEqual(compute_item_yummy_score(pizza_item), 94.0)  # 94 base

        # Modifiers bonus (+5 pts)
        bbq_drumstick = _make_item('BBQ Chicken Drumstick')
        # 88 base (bbq chicken / drumstick) + 5 (bbq modifier) = 93.0
        self.assertEqual(compute_item_yummy_score(bbq_drumstick), 93.0)

        # Penalties (-15 pts)
        steamed_item = _make_item('Steamed Plain Rice')
        # 60 base (plain rice) - 15 (steamed) - 15 (plain) = 30.0 (floor)
        self.assertEqual(compute_item_yummy_score(steamed_item), 30.0)

        # Combo scoring takes highest base tier + modifiers
        slots = [
            ('Main', _make_item('Pepperoni Pizza')),
            ('Side', _make_item('Loaded French Fries')),
            ('Dessert', _make_item('Warm Chocolate Chip Cookie')),
        ]
        # Highest base = 98 (cookie). Modifiers: 'loaded' (+5), 'chocolate' (+5), 'fried' (+5) -> 98 + 15 = 113 -> capped at 100
        combo_score = compute_combo_yummy_score(slots)
        self.assertEqual(combo_score, 100.0)

    def test_feedback_dashboard_and_api(self):
        from app import app
        client = app.test_client()

        # Feedback dashboard page loads 200
        resp = client.get('/feedback')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Feedback Dashboard', resp.get_data(as_text=True))

        # Unauthorized access without key or wrong key
        unauth = client.get('/api/feedback?key=wrongkey')
        self.assertEqual(unauth.status_code, 401)

        # Authorized access with default key 'feast'
        auth_resp = client.get('/api/feedback?key=feast')
        self.assertEqual(auth_resp.status_code, 200)
        data = auth_resp.get_json()
        self.assertIn('count', data)
        self.assertIn('entries', data)

    def test_card_nutrition_details_decluttered(self):
        from app import app
        client = app.test_client()
        resp = client.get('/')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        # Confirm new button label "Nutrition Details"
        self.assertIn('Nutrition Details', html)
        self.assertNotIn('Nutrition &amp; Macro Split', html)
        self.assertNotIn('Nutrition & Macro Split', html)

        # Confirm tutorial step 1 does not use the word "pill"
        self.assertNotIn('Tap any pill at the top', html)
        self.assertIn('Tap any dining hall at the top', html)

        # Confirm Tailor Plates to My Goals (DRI) is disabled and hidden from public
        self.assertIn('<!-- Tailor Plates to My Goals (DRI) - Disabled for public release -->', html)
        self.assertIn('<div class="toggle-card" style="display: none !important;">', html)

        # Confirm Number of users today badge is present in header near open courts
        self.assertIn('Number of users today:', html)
        self.assertIn('usersTodayCount', html)
        self.assertIn('users-pill', html)

    def test_daily_user_counter_endpoints(self):
        from app import app, record_site_visit, get_today_visits
        initial_count = get_today_visits()
        self.assertGreaterEqual(initial_count, 0)

        # Record a visit
        new_count = record_site_visit()
        self.assertGreater(new_count, initial_count)
        self.assertEqual(get_today_visits(), new_count)

        # Test visit stats API
        client = app.test_client()
        stats_resp = client.get('/api/visit-stats')
        self.assertEqual(stats_resp.status_code, 200)
        data = stats_resp.get_json()
        self.assertTrue(data.get('ok'))
        self.assertEqual(data.get('users_today'), new_count)

        # Test healthz endpoint
        health_resp = client.get('/healthz')
        self.assertEqual(health_resp.status_code, 200)
        self.assertEqual(health_resp.get_data(as_text=True), 'OK')

    def test_redis_persistence_and_daily_ttl(self):
        """Verify that Redis integration persists counts and sets auto-expiration."""
        import app as app_module
        from app import record_site_visit, get_today_visits

        class FakeRedis:
            def __init__(self):
                self.store = {}
                self.ttls = {}

            def incr(self, key):
                val = self.store.get(key, 0) + 1
                self.store[key] = val
                return val

            def get(self, key):
                return self.store.get(key)

            def expire(self, key, seconds):
                self.ttls[key] = seconds
                return True

        fake_r = FakeRedis()
        orig_client = app_module._redis_client
        try:
            app_module._redis_client = fake_r
            c1 = record_site_visit()
            self.assertEqual(c1, 1)
            c2 = record_site_visit()
            self.assertEqual(c2, 2)
            self.assertEqual(get_today_visits(), 2)

            # Confirm 48-hour (172800s) TTL was applied
            today_key = [k for k in fake_r.store.keys() if k.startswith('feast:visits:')][0]
            self.assertEqual(fake_r.ttls.get(today_key), 172800)
        finally:
            app_module._redis_client = orig_client


if __name__ == '__main__':
    unittest.main()
